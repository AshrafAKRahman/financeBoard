"""Posting a payment to the ledger (R2). One entry, a number, and a balance that moved."""

from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.coa.defaults import set_default
from app.ledger.api import JournalEntry, JournalEntryLine
from app.shared.errors import DomainError
from app.treasury.payments import (
    cancel_payment,
    create_payment,
    delete_payment,
    post_payment,
    update_payment,
)
from tests.factories import TreasuryBooks
from tests.treasury.conftest import PAYMENT_DATE, draft

pytestmark = pytest.mark.db


def lines_of(session: Session, entry_id: UUID) -> list[JournalEntryLine]:
    return list(
        session.execute(
            select(JournalEntryLine)
            .where(JournalEntryLine.entry_id == entry_id)
            .order_by(JournalEntryLine.line_no)
        ).scalars()
    )


def amounts_by_account(session: Session, entry_id: UUID) -> dict[UUID, tuple[Decimal, Decimal]]:
    return {line.account_id: (line.debit, line.credit) for line in lines_of(session, entry_id)}


class TestAnInboundPayment:
    def test_it_debits_outstanding_receipts_and_credits_the_receivable(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R2.AC1 — the bank account is untouched until the statement says so."""
        payment = create_payment(session, books.company_id, draft(books, customer))
        session.flush()
        post_payment(session, books.company_id, payment.id)

        amounts = amounts_by_account(session, payment.journal_entry_id)

        assert amounts[books.accounts["1120"]] == (Decimal("1000.00"), Decimal(0))
        assert amounts[books.accounts["1200"]] == (Decimal(0), Decimal("1000.00"))
        assert books.accounts["1110"] not in amounts

    def test_the_receivable_line_carries_the_partner_and_the_date(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R2.AC4"""
        payment = create_payment(session, books.company_id, draft(books, customer))
        session.flush()
        post_payment(session, books.company_id, payment.id)

        receivable = next(
            line
            for line in lines_of(session, payment.journal_entry_id)
            if line.account_id == books.accounts["1200"]
        )
        assert receivable.partner_id == customer
        assert receivable.due_date == PAYMENT_DATE

    def test_the_receivable_line_becomes_an_open_item(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R3.AC1 — the payment is itself something to match."""
        payment = create_payment(session, books.company_id, draft(books, customer))
        session.flush()
        post_payment(session, books.company_id, payment.id)

        receivable = next(
            line
            for line in lines_of(session, payment.journal_entry_id)
            if line.account_id == books.accounts["1200"]
        )
        assert receivable.residual == Decimal("1000.00")
        assert not receivable.reconciled

    def test_the_outstanding_line_is_not_an_open_item(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R3.AC6 — outstanding receipts is a holding account, not a ledger of debts."""
        payment = create_payment(session, books.company_id, draft(books, customer))
        session.flush()
        post_payment(session, books.company_id, payment.id)

        outstanding = next(
            line
            for line in lines_of(session, payment.journal_entry_id)
            if line.account_id == books.accounts["1120"]
        )
        assert outstanding.residual is None


class TestAnOutboundPayment:
    def test_it_credits_outstanding_payments_and_debits_the_payable(
        self, session: Session, books: TreasuryBooks, vendor: UUID
    ) -> None:
        """R2.AC2"""
        payment = create_payment(
            session, books.company_id, draft(books, vendor, direction="outbound")
        )
        session.flush()
        post_payment(session, books.company_id, payment.id)

        amounts = amounts_by_account(session, payment.journal_entry_id)

        assert amounts[books.accounts["2120"]] == (Decimal(0), Decimal("1000.00"))
        assert amounts[books.accounts["2100"]] == (Decimal("1000.00"), Decimal(0))


class TestTheEntryItself:
    def test_posting_creates_exactly_one_entry(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R2.AC3"""
        payment = create_payment(session, books.company_id, draft(books, customer))
        session.flush()
        post_payment(session, books.company_id, payment.id)

        entries = session.execute(
            select(JournalEntry).where(
                JournalEntry.source_type == "payment", JournalEntry.source_id == payment.id
            )
        ).scalars()
        assert len(list(entries)) == 1

    def test_the_payment_takes_its_journals_number(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R2.AC5"""
        payment = create_payment(session, books.company_id, draft(books, customer))
        session.flush()
        post_payment(session, books.company_id, payment.id)

        assert payment.number is not None
        assert payment.number.startswith("BNK/2026/")

    def test_numbers_are_gapless(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R2.AC5"""
        numbers = []
        for _ in range(3):
            payment = create_payment(session, books.company_id, draft(books, customer))
            session.flush()
            post_payment(session, books.company_id, payment.id)
            numbers.append(int(payment.number.split("/")[-1]))

        assert numbers == [numbers[0], numbers[0] + 1, numbers[0] + 2]

    def test_the_entry_is_linked_both_ways(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        payment = create_payment(session, books.company_id, draft(books, customer))
        session.flush()
        post_payment(session, books.company_id, payment.id)

        entry = session.get(JournalEntry, payment.journal_entry_id)
        assert entry.source_type == "payment"
        assert entry.source_id == payment.id
        assert entry.state == "posted"

    def test_the_reference_and_memo_reach_the_entry(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        payment = create_payment(
            session,
            books.company_id,
            draft(books, customer, reference="SADAD-1", memo="March receipts"),
        )
        session.flush()
        post_payment(session, books.company_id, payment.id)

        entry = session.get(JournalEntry, payment.journal_entry_id)
        assert (entry.ref, entry.narration) == ("SADAD-1", "March receipts")


class TestWhatPostingRefuses:
    def test_a_payment_cannot_be_posted_twice(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R2.AC6"""
        payment = create_payment(session, books.company_id, draft(books, customer))
        session.flush()
        post_payment(session, books.company_id, payment.id)

        with pytest.raises(DomainError) as caught:
            post_payment(session, books.company_id, payment.id)
        assert caught.value.code == "payments.already_posted"

    def test_a_cancelled_payment_cannot_be_posted(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        payment = create_payment(session, books.company_id, draft(books, customer))
        session.flush()
        post_payment(session, books.company_id, payment.id)
        cancel_payment(session, books.company_id, payment.id, reason="wrong customer")

        with pytest.raises(DomainError) as caught:
            post_payment(session, books.company_id, payment.id)
        assert caught.value.code == "payments.already_cancelled"

    def test_a_missing_outstanding_account_stops_posting(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R2.AC7"""
        set_default(session, books.company_id, "outstanding_receipts", None)
        payment = create_payment(session, books.company_id, draft(books, customer))
        session.flush()

        with pytest.raises(DomainError) as caught:
            post_payment(session, books.company_id, payment.id)
        assert caught.value.code == "payments.default_account_missing"

    def test_a_failed_posting_leaves_a_draft_with_no_entry(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R2.AC8"""
        set_default(session, books.company_id, "outstanding_receipts", None)
        payment = create_payment(session, books.company_id, draft(books, customer))
        session.flush()

        with pytest.raises(DomainError):
            post_payment(session, books.company_id, payment.id)

        assert payment.state == "draft"
        assert payment.journal_entry_id is None
        assert payment.number is None

    def test_a_posted_payment_cannot_be_changed(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R2.AC9 — refused by the service, and by the database underneath it."""
        payment = create_payment(session, books.company_id, draft(books, customer))
        session.flush()
        post_payment(session, books.company_id, payment.id)

        with pytest.raises(DomainError) as caught:
            update_payment(session, books.company_id, payment.id, draft(books, customer, "50.00"))
        assert caught.value.code == "payments.posted_immutable"

    def test_a_posted_payment_cannot_be_deleted(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        payment = create_payment(session, books.company_id, draft(books, customer))
        session.flush()
        post_payment(session, books.company_id, payment.id)

        with pytest.raises(DomainError) as caught:
            delete_payment(session, books.company_id, payment.id)
        assert caught.value.code == "payments.posted_immutable"


class TestCancelling:
    def test_cancelling_reverses_the_entry_and_says_why(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R2.AC10"""
        payment = create_payment(session, books.company_id, draft(books, customer))
        session.flush()
        post_payment(session, books.company_id, payment.id)
        entry_id = payment.journal_entry_id

        cancel_payment(session, books.company_id, payment.id, reason="paid twice by mistake")

        reversal = session.execute(
            select(JournalEntry).where(JournalEntry.reversed_entry_id == entry_id)
        ).scalar_one()
        assert payment.state == "cancelled"
        assert payment.cancel_reason == "paid twice by mistake"
        assert reversal.state == "posted"

    def test_the_original_entry_stays(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """A cancelled payment is history, not a mistake to hide."""
        payment = create_payment(session, books.company_id, draft(books, customer))
        session.flush()
        post_payment(session, books.company_id, payment.id)

        cancel_payment(session, books.company_id, payment.id)

        assert session.get(JournalEntry, payment.journal_entry_id).state == "posted"

    def test_the_two_entries_cancel_out(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        payment = create_payment(session, books.company_id, draft(books, customer))
        session.flush()
        post_payment(session, books.company_id, payment.id)
        cancel_payment(session, books.company_id, payment.id)

        reversal = session.execute(
            select(JournalEntry).where(JournalEntry.reversed_entry_id == payment.journal_entry_id)
        ).scalar_one()
        original = amounts_by_account(session, payment.journal_entry_id)
        undone = amounts_by_account(session, reversal.id)

        for account_id, (debit, credit) in original.items():
            assert undone[account_id] == (credit, debit)

    def test_a_draft_cannot_be_cancelled(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        payment = create_payment(session, books.company_id, draft(books, customer))
        session.flush()

        with pytest.raises(DomainError) as caught:
            cancel_payment(session, books.company_id, payment.id)
        assert caught.value.code == "payments.not_posted"

    def test_cancelling_twice_is_refused(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        payment = create_payment(session, books.company_id, draft(books, customer))
        session.flush()
        post_payment(session, books.company_id, payment.id)
        cancel_payment(session, books.company_id, payment.id)

        with pytest.raises(DomainError) as caught:
            cancel_payment(session, books.company_id, payment.id)
        assert caught.value.code == "payments.already_cancelled"
