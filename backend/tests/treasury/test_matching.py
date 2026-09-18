"""Matching payments to documents (R3.AC2, R3.AC3, R4)."""

from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ledger.api import JournalEntryLine
from app.shared.errors import DomainError
from app.shared.ids import uuid7
from app.treasury.matching import match_amount, match_lines, matches_for_lines, unmatch
from app.treasury.payments import create_payment, post_payment
from tests.factories import TreasuryBooks, make_partner
from tests.treasury.conftest import draft, make_bill, make_invoice

pytestmark = pytest.mark.db


def open_item(session: Session, books: TreasuryBooks, entry_id: UUID) -> JournalEntryLine:
    """The one line of an entry that keeps an open amount."""
    return session.execute(
        select(JournalEntryLine).where(
            JournalEntryLine.entry_id == entry_id,
            JournalEntryLine.residual.is_not(None),
        )
    ).scalar_one()


def receipt(
    session: Session, books: TreasuryBooks, partner_id: UUID, amount: str, **overrides
) -> JournalEntryLine:
    payment = create_payment(
        session, books.company_id, draft(books, partner_id, amount, **overrides)
    )
    session.flush()
    post_payment(session, books.company_id, payment.id)
    return open_item(session, books, payment.journal_entry_id)


class TestAFullSettlement:
    def test_both_lines_close(self, session: Session, books: TreasuryBooks, customer: UUID) -> None:
        """R3.AC3, R4.AC1"""
        invoice = make_invoice(session, books, customer, "1000.00")
        invoice_line = open_item(session, books, invoice.journal_entry_id)
        payment_line = receipt(session, books, customer, "1000.00")

        match_amount(session, books.company_id, invoice_line.id, payment_line.id)

        assert invoice_line.residual == Decimal(0)
        assert payment_line.residual == Decimal(0)
        assert invoice_line.reconciled
        assert payment_line.reconciled

    def test_the_match_records_what_each_side_gave_up(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        invoice = make_invoice(session, books, customer, "1000.00")
        invoice_line = open_item(session, books, invoice.journal_entry_id)
        payment_line = receipt(session, books, customer, "1000.00")

        match = match_amount(session, books.company_id, invoice_line.id, payment_line.id)

        assert match.debit_amount == Decimal("1000.00")
        assert match.credit_amount == Decimal("1000.00")
        assert match.fx_entry_id is None


class TestAPartialSettlement:
    def test_the_invoice_keeps_the_remainder_open(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R3.AC2, R4.AC3"""
        invoice = make_invoice(session, books, customer, "1000.00")
        invoice_line = open_item(session, books, invoice.journal_entry_id)
        payment_line = receipt(session, books, customer, "400.00")

        match_amount(session, books.company_id, invoice_line.id, payment_line.id)

        assert invoice_line.residual == Decimal("600.00")
        assert not invoice_line.reconciled
        assert payment_line.reconciled

    def test_a_named_amount_settles_only_that_much(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R4.AC3 — an accountant may match less than either side could take."""
        invoice = make_invoice(session, books, customer, "1000.00")
        invoice_line = open_item(session, books, invoice.journal_entry_id)
        payment_line = receipt(session, books, customer, "1000.00")

        match_amount(session, books.company_id, invoice_line.id, payment_line.id, Decimal("250.00"))

        assert invoice_line.residual == Decimal("750.00")
        assert payment_line.residual == Decimal("750.00")

    def test_two_payments_can_close_one_invoice(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R4.AC2"""
        invoice = make_invoice(session, books, customer, "1000.00")
        invoice_line = open_item(session, books, invoice.journal_entry_id)
        first = receipt(session, books, customer, "400.00")
        second = receipt(session, books, customer, "600.00")

        match_amount(session, books.company_id, invoice_line.id, first.id)
        match_amount(session, books.company_id, invoice_line.id, second.id)

        assert invoice_line.reconciled
        assert invoice_line.residual == Decimal(0)

    def test_one_payment_can_close_several_invoices(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R4.AC2"""
        first = make_invoice(session, books, customer, "300.00")
        second = make_invoice(session, books, customer, "700.00")
        payment_line = receipt(session, books, customer, "1000.00")

        lines = [
            open_item(session, books, first.journal_entry_id).id,
            open_item(session, books, second.journal_entry_id).id,
            payment_line.id,
        ]
        matches = match_lines(session, books.company_id, lines)

        assert len(matches) == 2
        assert payment_line.reconciled


class TestMatchingASet:
    def test_the_oldest_invoice_is_settled_first(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R4.AC1 — 500 against a 400 and a 600 invoice leaves 500 open on the newer one."""
        from datetime import date

        old = make_invoice(session, books, customer, "400.00", on=date(2026, 1, 15))
        new = make_invoice(session, books, customer, "600.00", on=date(2026, 2, 15))
        payment_line = receipt(session, books, customer, "500.00")

        old_line = open_item(session, books, old.journal_entry_id)
        new_line = open_item(session, books, new.journal_entry_id)
        match_lines(session, books.company_id, [old_line.id, new_line.id, payment_line.id])

        assert old_line.reconciled
        assert new_line.residual == Decimal("500.00")

    def test_matching_needs_two_lines(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        invoice = make_invoice(session, books, customer, "1000.00")
        line = open_item(session, books, invoice.journal_entry_id)

        with pytest.raises(DomainError) as caught:
            match_lines(session, books.company_id, [line.id])
        assert caught.value.code == "payments.invalid_match"

    def test_two_invoices_cannot_settle_each_other(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R4.AC4"""
        first = make_invoice(session, books, customer, "300.00")
        second = make_invoice(session, books, customer, "700.00")

        with pytest.raises(DomainError) as caught:
            match_lines(
                session,
                books.company_id,
                [
                    open_item(session, books, first.journal_entry_id).id,
                    open_item(session, books, second.journal_entry_id).id,
                ],
            )
        assert caught.value.code == "payments.same_side"


class TestWhatMatchingRefuses:
    def test_a_line_cannot_settle_itself(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        invoice = make_invoice(session, books, customer, "1000.00")
        line = open_item(session, books, invoice.journal_entry_id)

        with pytest.raises(DomainError) as caught:
            match_amount(session, books.company_id, line.id, line.id)
        assert caught.value.code == "payments.same_line"

    def test_one_customers_payment_cannot_settle_anothers_invoice(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R4.AC5"""
        other = make_partner(session, books.company_id, name="Riyadh Retail", type="customer")
        invoice = make_invoice(session, books, customer, "1000.00")
        payment_line = receipt(session, books, other.id, "1000.00")

        with pytest.raises(DomainError) as caught:
            match_amount(
                session,
                books.company_id,
                open_item(session, books, invoice.journal_entry_id).id,
                payment_line.id,
            )
        assert caught.value.code == "payments.partner_mismatch"

    def test_a_receivable_cannot_be_matched_to_a_payable(
        self, session: Session, books: TreasuryBooks, customer: UUID, vendor: UUID
    ) -> None:
        """R4.AC7 — different accounts, so matching them would move money sideways."""
        invoice = make_invoice(session, books, customer, "1000.00")
        bill = make_bill(session, books, vendor, "1000.00")

        with pytest.raises(DomainError) as caught:
            match_amount(
                session,
                books.company_id,
                open_item(session, books, invoice.journal_entry_id).id,
                open_item(session, books, bill.journal_entry_id).id,
            )
        assert caught.value.code in ("payments.account_mismatch", "payments.partner_mismatch")

    def test_a_line_that_keeps_no_open_amount_cannot_be_matched(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R4.AC6"""
        invoice = make_invoice(session, books, customer, "1000.00")
        revenue = session.execute(
            select(JournalEntryLine).where(
                JournalEntryLine.entry_id == invoice.journal_entry_id,
                JournalEntryLine.account_id == books.accounts["4100"],
            )
        ).scalar_one()
        payment_line = receipt(session, books, customer, "1000.00")

        with pytest.raises(DomainError) as caught:
            match_amount(session, books.company_id, payment_line.id, revenue.id)
        assert caught.value.code in ("payments.not_reconcilable", "payments.same_side")

    def test_a_closed_line_has_nothing_left_to_match(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        invoice = make_invoice(session, books, customer, "1000.00")
        invoice_line = open_item(session, books, invoice.journal_entry_id)
        first = receipt(session, books, customer, "1000.00")
        second = receipt(session, books, customer, "500.00")
        match_amount(session, books.company_id, invoice_line.id, first.id)

        with pytest.raises(DomainError) as caught:
            match_amount(session, books.company_id, invoice_line.id, second.id)
        assert caught.value.code == "payments.already_reconciled"

    def test_matching_more_than_is_open_is_refused(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R3.AC4 — the service says so before the trigger has to."""
        invoice = make_invoice(session, books, customer, "1000.00")
        invoice_line = open_item(session, books, invoice.journal_entry_id)
        payment_line = receipt(session, books, customer, "2000.00")

        with pytest.raises(DomainError) as caught:
            match_amount(
                session,
                books.company_id,
                invoice_line.id,
                payment_line.id,
                Decimal("1500.00"),
            )
        assert caught.value.code == "payments.over_matched"

    def test_a_match_of_nothing_is_refused(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        invoice = make_invoice(session, books, customer, "1000.00")
        payment_line = receipt(session, books, customer, "1000.00")

        with pytest.raises(DomainError) as caught:
            match_amount(
                session,
                books.company_id,
                open_item(session, books, invoice.journal_entry_id).id,
                payment_line.id,
                Decimal("0.00"),
            )
        assert caught.value.code == "payments.invalid_amount"

    def test_an_unknown_line_is_not_found(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        invoice = make_invoice(session, books, customer, "1000.00")

        with pytest.raises(DomainError) as caught:
            match_amount(
                session,
                books.company_id,
                open_item(session, books, invoice.journal_entry_id).id,
                uuid7(),
            )
        assert caught.value.code == "payments.line_not_found"


class TestUnmatching:
    def test_both_lines_reopen(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R4.AC8"""
        invoice = make_invoice(session, books, customer, "1000.00")
        invoice_line = open_item(session, books, invoice.journal_entry_id)
        payment_line = receipt(session, books, customer, "1000.00")
        match = match_amount(session, books.company_id, invoice_line.id, payment_line.id)

        unmatch(session, books.company_id, [match.id])

        assert invoice_line.residual == Decimal("1000.00")
        assert payment_line.residual == Decimal("1000.00")
        assert not invoice_line.reconciled
        assert not payment_line.reconciled

    def test_the_match_itself_is_gone(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        invoice = make_invoice(session, books, customer, "1000.00")
        invoice_line = open_item(session, books, invoice.journal_entry_id)
        payment_line = receipt(session, books, customer, "1000.00")
        match = match_amount(session, books.company_id, invoice_line.id, payment_line.id)

        unmatch(session, books.company_id, [match.id])

        assert matches_for_lines(session, books.company_id, [invoice_line.id]) == []

    def test_a_partial_match_reopens_only_what_it_closed(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        invoice = make_invoice(session, books, customer, "1000.00")
        invoice_line = open_item(session, books, invoice.journal_entry_id)
        first = receipt(session, books, customer, "400.00")
        second = receipt(session, books, customer, "600.00")
        match_amount(session, books.company_id, invoice_line.id, first.id)
        undo = match_amount(session, books.company_id, invoice_line.id, second.id)

        unmatch(session, books.company_id, [undo.id])

        assert invoice_line.residual == Decimal("600.00")
        assert first.reconciled
        assert not second.reconciled

    def test_an_unknown_match_is_not_found(self, session: Session, books: TreasuryBooks) -> None:
        with pytest.raises(DomainError) as caught:
            unmatch(session, books.company_id, [uuid7()])
        assert caught.value.code == "payments.reconciliation_not_found"
