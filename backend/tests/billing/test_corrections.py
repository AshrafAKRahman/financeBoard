"""Credit and debit notes, and cancellation (R5, R7.AC5, R7.AC6)."""

from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.billing.documents import (
    LineData,
    cancel_document,
    credit_note_from,
    entry_of,
    get_document,
    post_document,
    totals_of,
    update_document,
)
from app.shared.errors import DomainError
from tests.billing.helpers import make_bill, make_invoice

pytestmark = pytest.mark.db


def posted_invoice(session: Session, books, customer, vat15, **kwargs):
    invoice = make_invoice(session, books, customer, taxes=[vat15], **kwargs)
    posted = post_document(session, books.id, invoice.id)
    session.commit()
    return posted


class TestCreditNotes:
    def test_a_note_copies_the_invoice(self, session: Session, books, customer, vat15) -> None:
        """R5.AC1"""
        invoice = posted_invoice(session, books, customer, vat15, unit_price="500.00")
        note = credit_note_from(session, books.id, invoice.id)
        session.commit()

        assert note.type == "out_credit"
        assert note.state == "draft"
        assert note.partner_id == invoice.partner_id
        assert note.currency_code == invoice.currency_code
        assert [line.description for line in note.lines] == [
            line.description for line in invoice.lines
        ]
        assert totals_of(session, note).total == totals_of(session, invoice).total

    def test_a_note_links_to_what_it_corrects(
        self, session: Session, books, customer, vat15
    ) -> None:
        """R5.AC3"""
        invoice = posted_invoice(session, books, customer, vat15)
        note = credit_note_from(session, books.id, invoice.id)
        session.commit()

        assert note.origin_document_id == invoice.id
        assert invoice.number in (note.narration or "")

    def test_posting_a_note_reverses_the_invoice(
        self, session: Session, books, customer, vat15
    ) -> None:
        """R5.AC2 — the books end up flat, with both documents visible."""
        invoice = posted_invoice(session, books, customer, vat15, unit_price="800.00")
        note = credit_note_from(session, books.id, invoice.id)
        posted_note = post_document(session, books.id, note.id)
        session.commit()

        balance = session.execute(
            text(
                "SELECT coalesce(sum(l.debit) - sum(l.credit), 0) FROM journal_entry_line l "
                "JOIN journal_entry e ON e.id = l.entry_id WHERE e.company_id = :c"
            ),
            {"c": books.id},
        ).scalar_one()
        assert balance == 0

        note_entry = entry_of(session, posted_note)
        receivable = next(line for line in note_entry.lines if line.credit)
        assert receivable.credit == Decimal("920.00")  # 800 + 15% credited back

    def test_a_note_can_be_trimmed_before_it_is_issued(
        self, session: Session, books, customer, vat15
    ) -> None:
        """R5.AC5 — a partial credit is the common case."""
        invoice = posted_invoice(
            session, books, customer, vat15, quantity="10", unit_price="100.00"
        )
        note = credit_note_from(session, books.id, invoice.id)
        trimmed = update_document(
            session,
            books.id,
            note.id,
            {
                "lines": [
                    LineData(
                        description=note.lines[0].description,
                        quantity=Decimal("3"),
                        unit_price=note.lines[0].unit_price,
                        account_id=note.lines[0].account_id,
                        tax_ids=[vat15.id],
                    )
                ]
            },
        )
        post_document(session, books.id, trimmed.id)
        session.commit()

        assert totals_of(session, trimmed).total == Decimal("345.00")

    def test_a_draft_cannot_be_corrected(self, session: Session, books, customer, vat15) -> None:
        """R5.AC4"""
        draft = make_invoice(session, books, customer, taxes=[vat15])
        session.commit()

        with pytest.raises(DomainError) as error:
            credit_note_from(session, books.id, draft.id)
        assert error.value.code == "invoicing.not_posted"
        session.rollback()

    def test_credits_cannot_exceed_the_invoice(
        self, session: Session, books, customer, vat15
    ) -> None:
        """R5.AC6 — two notes for the full amount: the second is refused."""
        invoice = posted_invoice(session, books, customer, vat15, unit_price="600.00")

        first = credit_note_from(session, books.id, invoice.id)
        post_document(session, books.id, first.id)
        session.commit()

        second = credit_note_from(session, books.id, invoice.id)
        with pytest.raises(DomainError) as error:
            post_document(session, books.id, second.id)
        assert error.value.code == "invoicing.exceeds_original"
        session.rollback()

    def test_two_partial_credits_that_fit_are_allowed(
        self, session: Session, books, customer, vat15
    ) -> None:
        invoice = posted_invoice(
            session, books, customer, vat15, quantity="10", unit_price="100.00"
        )

        for _ in range(2):
            note = credit_note_from(session, books.id, invoice.id)
            update_document(
                session,
                books.id,
                note.id,
                {
                    "lines": [
                        LineData(
                            description="Partial credit",
                            quantity=Decimal("4"),
                            unit_price=Decimal("100.00"),
                            account_id=note.lines[0].account_id,
                            tax_ids=[vat15.id],
                        )
                    ]
                },
            )
            post_document(session, books.id, note.id)
            session.commit()

        credited = session.execute(
            text("SELECT count(*) FROM document WHERE origin_document_id = :id"),
            {"id": invoice.id},
        ).scalar_one()
        assert credited == 2

    def test_a_bill_is_corrected_by_a_debit_note(
        self, session: Session, books, vendor, vat15_purchase
    ) -> None:
        bill = make_bill(session, books, vendor, taxes=[vat15_purchase])
        post_document(session, books.id, bill.id)
        session.commit()

        note = credit_note_from(session, books.id, bill.id)
        session.commit()
        assert note.type == "in_debit"


class TestCancelling:
    def test_cancelling_marks_the_document_and_reverses_the_entry(
        self, session: Session, books, customer, vat15
    ) -> None:
        """R7.AC5"""
        invoice = posted_invoice(session, books, customer, vat15)
        cancelled = cancel_document(session, books.id, invoice.id, reason="duplicate")
        session.commit()

        assert cancelled.state == "cancelled"
        assert cancelled.cancelled_at is not None
        reversals = session.execute(
            text("SELECT count(*) FROM journal_entry WHERE reversed_entry_id = :id"),
            {"id": invoice.journal_entry_id},
        ).scalar_one()
        assert reversals == 1

    def test_cancelling_twice_is_refused(self, session: Session, books, customer, vat15) -> None:
        """R7.AC6"""
        invoice = posted_invoice(session, books, customer, vat15)
        cancel_document(session, books.id, invoice.id)
        session.commit()

        with pytest.raises(DomainError) as error:
            cancel_document(session, books.id, invoice.id)
        assert error.value.code == "invoicing.already_cancelled"
        session.rollback()

    def test_a_draft_cannot_be_cancelled(self, session: Session, books, customer) -> None:
        draft = make_invoice(session, books, customer)
        session.commit()

        with pytest.raises(DomainError) as error:
            cancel_document(session, books.id, draft.id)
        assert error.value.code == "invoicing.not_posted"
        session.rollback()

    def test_a_cancelled_document_cannot_be_reissued(
        self, session: Session, books, customer, vat15
    ) -> None:
        invoice = posted_invoice(session, books, customer, vat15)
        cancel_document(session, books.id, invoice.id)
        session.commit()

        with pytest.raises(DomainError) as error:
            post_document(session, books.id, invoice.id)
        assert error.value.code == "invoicing.already_cancelled"
        session.rollback()

    def test_cancelling_is_audited(self, session: Session, books, customer, vat15) -> None:
        """R11.AC2"""
        invoice = posted_invoice(session, books, customer, vat15)
        cancel_document(session, books.id, invoice.id, reason="raised twice")
        session.commit()

        detail = session.execute(
            text(
                "SELECT detail::text FROM audit_log WHERE target_id = :id "
                "AND action = 'document.cancelled'"
            ),
            {"id": str(invoice.id)},
        ).scalar_one()
        assert "raised twice" in detail
        assert get_document(session, books.id, invoice.id).number in detail
