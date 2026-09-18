"""Balance sheet (R3) — and the earnings nobody posted."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.reporting.balances import flatten
from app.reporting.statements import balance_sheet, profit_and_loss
from tests.factories import TreasuryBooks
from tests.reporting.conftest import JANUARY, YEAR, bill, invoice, receipt, settle

pytestmark = pytest.mark.db

YEAR_END = date(2026, 12, 31)


class TestItBalances:
    def test_assets_equal_liabilities_plus_equity(self, session: Session, simple) -> None:
        """R3.AC4 — including the earnings nobody posted."""
        sheet = balance_sheet(session, simple.books.company_id, YEAR_END)

        assert sheet.balances
        assert sheet.total_assets == sheet.total_liabilities + sheet.total_equity

    def test_it_balances_on_an_empty_company(self, session: Session, books: TreasuryBooks) -> None:
        sheet = balance_sheet(session, books.company_id, YEAR_END)

        assert sheet.total_assets == Decimal(0)
        assert sheet.balances

    def test_it_balances_midway_through_a_transaction(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        """An invoice raised and not yet paid still balances."""
        invoice(session, books, customer, "10000.00")

        assert balance_sheet(session, books.company_id, YEAR_END).balances


class TestTheFigures:
    def test_an_unpaid_invoice_is_an_asset(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        """R3.AC1"""
        invoice(session, books, customer, "10000.00")

        sheet = balance_sheet(session, books.company_id, YEAR_END)
        assert sheet.total_assets == Decimal("11500.00")

    def test_vat_owed_is_a_liability_and_reads_positive(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        """R3.AC6 — "we owe 1,500", not "-1,500"."""
        invoice(session, books, customer, "10000.00")

        sheet = balance_sheet(session, books.company_id, YEAR_END)
        assert sheet.total_liabilities == Decimal("1500.00")

    def test_this_years_profit_appears_without_being_posted(
        self, session: Session, books: TreasuryBooks, customer, vendor
    ) -> None:
        """R3.AC2 — decision D6: no closing entries, earnings computed."""
        invoice(session, books, customer, "10000.00")
        bill(session, books, vendor, "4000.00")

        sheet = balance_sheet(session, books.company_id, YEAR_END)
        assert sheet.current_year_earnings == Decimal("6000.00")

    def test_a_receipt_moves_money_without_changing_the_total(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        """Settling an invoice swaps one asset for another."""
        sale = invoice(session, books, customer, "10000.00")
        before = balance_sheet(session, books.company_id, YEAR_END).total_assets

        payment = receipt(session, books, customer, "11500.00")
        settle(session, books, sale, payment)
        session.flush()

        assert balance_sheet(session, books.company_id, YEAR_END).total_assets == before


class TestEarningsAcrossYears:
    def test_last_years_profit_becomes_retained_earnings(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        """R3.AC3 — 2025's profit is not 2026's."""
        invoice(session, books, customer, "5000.00", on=date(2025, 6, 10))
        invoice(session, books, customer, "3000.00", on=JANUARY)

        sheet = balance_sheet(session, books.company_id, YEAR_END)

        assert sheet.retained_earnings == Decimal("5000.00")
        assert sheet.current_year_earnings == Decimal("3000.00")

    def test_at_the_end_of_the_earlier_year_it_is_all_current(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        invoice(session, books, customer, "5000.00", on=date(2025, 6, 10))

        sheet = balance_sheet(session, books.company_id, date(2025, 12, 31))

        assert sheet.current_year_earnings == Decimal("5000.00")
        assert sheet.retained_earnings == Decimal(0)


def test_the_profit_and_loss_agrees_with_the_balance_sheet(
    session: Session, books: TreasuryBooks, customer, vendor
) -> None:
    """R10.AC1 — the identity that makes both reports trustworthy."""
    invoice(session, books, customer, "10000.00")
    bill(session, books, vendor, "4000.00")

    year = profit_and_loss(session, books.company_id, YEAR)
    sheet = balance_sheet(session, books.company_id, YEAR_END)

    assert year.net_result == sheet.current_year_earnings


def test_only_balance_sheet_accounts_are_listed(
    session: Session, books: TreasuryBooks, customer
) -> None:
    invoice(session, books, customer, "10000.00")

    sheet = balance_sheet(session, books.company_id, YEAR_END)
    codes = {
        node.code for node in flatten(sheet.assets + sheet.liabilities + sheet.equity) if node.code
    }

    assert "1200" in codes
    assert "4100" not in codes
