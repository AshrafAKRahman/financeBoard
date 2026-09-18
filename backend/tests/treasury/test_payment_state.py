"""What an invoice's payment state says (R6). Derived, so it cannot drift."""

from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.documents import cancel_document
from app.ledger.api import JournalEntryLine
from app.treasury.matching import match_amount
from app.treasury.payments import cancel_payment, create_payment, post_payment
from app.treasury.state import documents_settled_by, payment_state_of
from tests.factories import TreasuryBooks
from tests.treasury.conftest import draft, make_invoice

pytestmark = pytest.mark.db


def open_item(session: Session, entry_id: UUID) -> JournalEntryLine:
    return session.execute(
        select(JournalEntryLine).where(
            JournalEntryLine.entry_id == entry_id, JournalEntryLine.residual.is_not(None)
        )
    ).scalar_one()


def settle(
    session: Session,
    books: TreasuryBooks,
    customer: UUID,
    invoice,
    amount: str,
    *,
    match: str | None = None,
):
    payment = create_payment(session, books.company_id, draft(books, customer, amount))
    session.flush()
    post_payment(session, books.company_id, payment.id)
    match_amount(
        session,
        books.company_id,
        open_item(session, invoice.journal_entry_id).id,
        open_item(session, payment.journal_entry_id).id,
        Decimal(match) if match else None,
    )
    return payment


class TestTheThreeStates:
    def test_an_unpaid_invoice_says_so(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R6.AC2"""
        invoice = make_invoice(session, books, customer, "1000.00")

        state = payment_state_of(session, invoice)

        assert state.state == "not_paid"
        assert state.paid == Decimal(0)
        assert state.open_amount == Decimal("1000.00")

    def test_a_part_paid_invoice_says_how_much(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R6.AC3"""
        invoice = make_invoice(session, books, customer, "1000.00")
        settle(session, books, customer, invoice, "400.00")

        state = payment_state_of(session, invoice)

        assert state.state == "partial"
        assert state.paid == Decimal("400.00")
        assert state.open_amount == Decimal("600.00")

    def test_a_settled_invoice_is_paid(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R6.AC1"""
        invoice = make_invoice(session, books, customer, "1000.00")
        settle(session, books, customer, invoice, "1000.00")

        state = payment_state_of(session, invoice)

        assert state.state == "paid"
        assert state.is_paid
        assert state.open_amount == Decimal(0)

    def test_a_cancelled_invoice_is_neither_paid_nor_owing(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R6.AC4"""
        invoice = make_invoice(session, books, customer, "1000.00")
        cancel_document(session, books.company_id, invoice.id, reason="duplicate")

        assert payment_state_of(session, invoice).state == "cancelled"

    def test_a_draft_invoice_is_not_paid(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        invoice = make_invoice(session, books, customer, "1000.00", post=False)
        assert payment_state_of(session, invoice).state == "not_paid"


class TestWhichPaymentsSettledIt:
    def test_the_payment_and_its_share_are_named(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R6.AC5"""
        invoice = make_invoice(session, books, customer, "1000.00")
        payment = settle(session, books, customer, invoice, "1000.00")

        state = payment_state_of(session, invoice)

        assert len(state.payments) == 1
        assert state.payments[0].payment.id == payment.id
        assert state.payments[0].amount == Decimal("1000.00")

    def test_several_payments_are_all_named_with_their_shares(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R6.AC5"""
        invoice = make_invoice(session, books, customer, "1000.00")
        settle(session, books, customer, invoice, "400.00")
        settle(session, books, customer, invoice, "600.00")

        state = payment_state_of(session, invoice)

        assert sorted(entry.amount for entry in state.payments) == [
            Decimal("400.00"),
            Decimal("600.00"),
        ]
        assert state.state == "paid"

    def test_a_payment_says_which_documents_it_settled(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """The same relationship read from the payment's side."""
        invoice = make_invoice(session, books, customer, "1000.00")
        payment = settle(session, books, customer, invoice, "1000.00")

        settled = documents_settled_by(session, books.company_id, payment)

        assert [document.id for document in settled] == [invoice.id]

    def test_an_unmatched_payment_settled_nothing(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        payment = create_payment(session, books.company_id, draft(books, customer))
        session.flush()
        post_payment(session, books.company_id, payment.id)

        assert documents_settled_by(session, books.company_id, payment) == []


class TestTheStateFollowsTheLedger:
    def test_cancelling_the_payment_makes_the_invoice_unpaid_again(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R6.AC6, R2.AC10 — the state cannot lag, because it is read from the lines."""
        invoice = make_invoice(session, books, customer, "1000.00")
        payment = settle(session, books, customer, invoice, "1000.00")
        assert payment_state_of(session, invoice).state == "paid"

        cancel_payment(session, books.company_id, payment.id, reason="bounced")

        state = payment_state_of(session, invoice)
        assert state.state == "not_paid"
        assert state.open_amount == Decimal("1000.00")
        assert state.payments == ()

    def test_a_part_payment_cancelled_leaves_the_rest_as_it_was(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        invoice = make_invoice(session, books, customer, "1000.00")
        settle(session, books, customer, invoice, "400.00")
        second = settle(session, books, customer, invoice, "600.00")

        cancel_payment(session, books.company_id, second.id)

        state = payment_state_of(session, invoice)
        assert state.state == "partial"
        assert state.paid == Decimal("400.00")
