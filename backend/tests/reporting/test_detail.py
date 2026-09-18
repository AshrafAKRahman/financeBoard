"""Account detail (R7) — the lines behind a figure, and the running balance that proves it."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.reporting.detail import account_detail
from app.reporting.periods import Period
from app.reporting.statements import trial_balance
from app.shared.errors import DomainError
from app.shared.ids import uuid7
from tests.factories import TreasuryBooks, make_partner
from tests.reporting.conftest import FEBRUARY, JANUARY, YEAR, invoice, receipt, settle

pytestmark = pytest.mark.db


class TestTheLines:
    def test_each_posted_line_appears(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        """R7.AC1"""
        invoice(session, books, customer, "10000.00", on=JANUARY)

        detail = account_detail(session, books.company_id, books.accounts["1200"], YEAR)

        assert len(detail.lines) == 1
        assert detail.lines[0].debit == Decimal("11500.00")
        assert detail.lines[0].entry_number.startswith("INV/")

    def test_a_line_names_its_document(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        """R7.AC6 — an invoice number leads back to the invoice."""
        document = invoice(session, books, customer, "10000.00", on=JANUARY)

        detail = account_detail(session, books.company_id, books.accounts["1200"], YEAR)
        assert detail.lines[0].document_number == document.number

    def test_a_line_names_its_partner(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        invoice(session, books, customer, "10000.00", on=JANUARY)

        detail = account_detail(session, books.company_id, books.accounts["1200"], YEAR)
        assert detail.lines[0].partner_name == "Al Noor Est"

    def test_lines_come_in_date_order(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        """R7.AC2"""
        invoice(session, books, customer, "2000.00", on=FEBRUARY)
        invoice(session, books, customer, "1000.00", on=JANUARY)

        detail = account_detail(session, books.company_id, books.accounts["1200"], YEAR)
        dates = [line.entry_date for line in detail.lines]

        assert dates == sorted(dates)


class TestTheRunningBalance:
    def test_it_starts_from_the_opening_balance(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        """R7.AC3 — January's invoice is February's opening balance."""
        invoice(session, books, customer, "10000.00", on=JANUARY)
        invoice(session, books, customer, "1000.00", on=FEBRUARY)

        february = Period(date(2026, 2, 1), date(2026, 2, 28), "February")
        detail = account_detail(session, books.company_id, books.accounts["1200"], february)

        assert detail.opening_balance == Decimal("11500.00")
        assert detail.lines[0].running_balance == Decimal("12650.00")

    def test_it_accumulates_down_the_page(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        sale = invoice(session, books, customer, "10000.00", on=JANUARY)
        payment = receipt(session, books, customer, "4000.00", on=FEBRUARY)
        settle(session, books, sale, payment)
        session.flush()

        detail = account_detail(session, books.company_id, books.accounts["1200"], YEAR)
        balances = [line.running_balance for line in detail.lines]

        assert balances == [Decimal("11500.00"), Decimal("7500.00")]

    def test_it_closes_where_the_trial_balance_says(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        """R7.AC4, R10.AC6 — the reconciliation that makes the detail worth opening."""
        invoice(session, books, customer, "10000.00", on=JANUARY)
        invoice(session, books, customer, "3000.00", on=FEBRUARY)

        detail = account_detail(session, books.company_id, books.accounts["1200"], YEAR)
        from app.reporting.balances import flatten

        row = next(
            node
            for node in flatten(trial_balance(session, books.company_id, YEAR).rows)
            if node.code == "1200"
        )

        assert detail.closing_balance == row.closing


class TestNarrowing:
    def test_one_partner_can_be_singled_out(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        """R7.AC5"""
        other = make_partner(session, books.company_id, name="Riyadh Retail", type="customer")
        invoice(session, books, customer, "1000.00", on=JANUARY)
        invoice(session, books, other.id, "2000.00", on=JANUARY)

        detail = account_detail(
            session, books.company_id, books.accounts["1200"], YEAR, partner_id=other.id
        )

        assert len(detail.lines) == 1
        assert detail.closing_balance == Decimal("2300.00")

    def test_an_unknown_account_is_not_found(self, session: Session, books: TreasuryBooks) -> None:
        with pytest.raises(DomainError) as caught:
            account_detail(session, books.company_id, uuid7(), YEAR)
        assert caught.value.code == "reporting.account_not_found"

    def test_a_draft_entry_is_not_here(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        invoice(session, books, customer, "10000.00", on=JANUARY, post_it=False)

        detail = account_detail(session, books.company_id, books.accounts["1200"], YEAR)
        assert detail.lines == ()
