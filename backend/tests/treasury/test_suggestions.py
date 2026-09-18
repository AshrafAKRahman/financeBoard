"""Open items and what to match them against (R4.AC9, NFR6)."""

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from app.treasury.matching import match_amount, open_lines, suggest_for_payment
from app.treasury.payments import create_payment, post_payment
from tests.factories import TreasuryBooks, make_partner
from tests.treasury.conftest import draft, make_invoice

pytestmark = pytest.mark.db


def receipt(session: Session, books: TreasuryBooks, partner_id: UUID, amount: str):
    payment = create_payment(session, books.company_id, draft(books, partner_id, amount))
    session.flush()
    post_payment(session, books.company_id, payment.id)
    return payment


class TestOpenItems:
    def test_only_unsettled_lines_come_back(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """NFR6 — an aged position straight from the ledger."""
        settled = make_invoice(session, books, customer, "300.00")
        still_owing = make_invoice(session, books, customer, "700.00")
        payment = receipt(session, books, customer, "300.00")

        settled_line = next(
            item.line
            for item in open_lines(session, books.company_id)
            if item.line.entry_id == settled.journal_entry_id
        )
        payment_line = next(
            item.line
            for item in open_lines(session, books.company_id)
            if item.line.entry_id == payment.journal_entry_id
        )
        match_amount(session, books.company_id, settled_line.id, payment_line.id)

        entries = {item.line.entry_id for item in open_lines(session, books.company_id)}
        assert still_owing.journal_entry_id in entries
        assert settled.journal_entry_id not in entries

    def test_they_come_back_oldest_first(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        make_invoice(session, books, customer, "100.00", on=date(2026, 2, 20))
        make_invoice(session, books, customer, "200.00", on=date(2026, 1, 5))

        dates = [item.entry_date for item in open_lines(session, books.company_id)]
        assert dates == sorted(dates)

    def test_they_can_be_narrowed_to_one_partner(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        other = make_partner(session, books.company_id, name="Riyadh Retail", type="customer")
        make_invoice(session, books, customer, "100.00")
        make_invoice(session, books, other.id, "200.00")

        found = open_lines(session, books.company_id, partner_id=other.id)
        assert [item.line.residual for item in found] == [Decimal("200.00")]

    def test_a_partly_paid_invoice_still_counts_as_open(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        invoice = make_invoice(session, books, customer, "1000.00")
        payment = receipt(session, books, customer, "400.00")
        lines = {item.line.entry_id: item.line for item in open_lines(session, books.company_id)}
        match_amount(
            session,
            books.company_id,
            lines[invoice.journal_entry_id].id,
            lines[payment.journal_entry_id].id,
        )

        remaining = {
            item.line.entry_id: item.line.residual for item in open_lines(session, books.company_id)
        }
        assert remaining[invoice.journal_entry_id] == Decimal("600.00")


class TestSuggestionsForAPayment:
    def test_the_partners_invoices_are_suggested(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R4.AC9"""
        invoice = make_invoice(session, books, customer, "1000.00")
        payment = receipt(session, books, customer, "1000.00")

        suggestions = suggest_for_payment(session, books.company_id, payment)

        assert [s.line.entry_id for s in suggestions] == [invoice.journal_entry_id]
        assert suggestions[0].amount == Decimal("1000.00")

    def test_an_exact_amount_is_suggested_first(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R4.AC9 — the strongest signal an accountant has."""
        make_invoice(session, books, customer, "725.00", on=date(2026, 1, 10))
        exact = make_invoice(session, books, customer, "1000.00", on=date(2026, 2, 10))
        payment = receipt(session, books, customer, "1000.00")

        suggestions = suggest_for_payment(session, books.company_id, payment)

        assert suggestions[0].line.entry_id == exact.journal_entry_id
        assert suggestions[0].reason == "the amount matches exactly"

    def test_another_partners_invoice_is_never_suggested(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        other = make_partner(session, books.company_id, name="Riyadh Retail", type="customer")
        make_invoice(session, books, other.id, "1000.00")
        payment = receipt(session, books, customer, "1000.00")

        assert suggest_for_payment(session, books.company_id, payment) == []

    def test_a_settled_invoice_is_no_longer_suggested(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        invoice = make_invoice(session, books, customer, "1000.00")
        first = receipt(session, books, customer, "1000.00")
        lines = {item.line.entry_id: item.line for item in open_lines(session, books.company_id)}
        match_amount(
            session,
            books.company_id,
            lines[invoice.journal_entry_id].id,
            lines[first.journal_entry_id].id,
        )

        later = receipt(session, books, customer, "1000.00")
        assert suggest_for_payment(session, books.company_id, later) == []

    def test_a_draft_payment_has_nothing_to_suggest_against(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        make_invoice(session, books, customer, "1000.00")
        payment = create_payment(session, books.company_id, draft(books, customer))
        session.flush()

        assert suggest_for_payment(session, books.company_id, payment) == []

    def test_a_suggestion_offers_only_what_both_sides_can_take(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        make_invoice(session, books, customer, "1000.00")
        payment = receipt(session, books, customer, "250.00")

        suggestions = suggest_for_payment(session, books.company_id, payment)
        assert suggestions[0].amount == Decimal("250.00")
