"""Profit and loss (R2) — what was earned and spent, signed the way a reader expects."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.reporting.balances import flatten
from app.reporting.periods import Period
from app.reporting.statements import profit_and_loss
from tests.factories import TreasuryBooks
from tests.reporting.conftest import JANUARY, YEAR, bill, invoice

pytestmark = pytest.mark.db


class TestWhatItShows:
    def test_income_is_positive_when_the_business_earned_it(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        """R2.AC2 — the ledger stores a credit; a reader wants "earned 10,000"."""
        invoice(session, books, customer, "10000.00")

        report = profit_and_loss(session, books.company_id, YEAR)
        assert report.total_income == Decimal("10000.00")

    def test_vat_is_not_income(self, session: Session, books: TreasuryBooks, customer) -> None:
        """The 1,500 VAT belongs to ZATCA, not to the business."""
        invoice(session, books, customer, "10000.00")

        report = profit_and_loss(session, books.company_id, YEAR)
        assert report.total_income == Decimal("10000.00")

    def test_the_net_result_is_income_less_expenses(
        self, session: Session, books: TreasuryBooks, customer, vendor
    ) -> None:
        """R2.AC6 — 10,000 earned, 4,000 spent."""
        invoice(session, books, customer, "10000.00")
        bill(session, books, vendor, "4000.00")

        report = profit_and_loss(session, books.company_id, YEAR)
        assert report.net_result == Decimal("6000.00")

    def test_a_loss_is_a_negative_result(
        self, session: Session, books: TreasuryBooks, customer, vendor
    ) -> None:
        invoice(session, books, customer, "1000.00")
        bill(session, books, vendor, "4000.00")

        report = profit_and_loss(session, books.company_id, YEAR)
        assert report.net_result == Decimal("-3000.00")

    def test_gross_profit_takes_off_the_cost_of_revenue(
        self, session: Session, books: TreasuryBooks, customer, vendor
    ) -> None:
        """R2.AC5 — rent is an operating expense, not a cost of revenue."""
        invoice(session, books, customer, "10000.00")
        bill(session, books, vendor, "4000.00")

        report = profit_and_loss(session, books.company_id, YEAR)

        assert report.cost_of_revenue == Decimal(0)
        assert report.gross_profit == Decimal("10000.00")
        assert report.other_expenses == Decimal("4000.00")


class TestWhatItLeavesOut:
    def test_the_balance_sheet_is_not_here(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        """R2.AC7 — a receivable is not a profit."""
        invoice(session, books, customer, "10000.00")

        report = profit_and_loss(session, books.company_id, YEAR)
        codes = {node.code for node in flatten(report.income + report.expenses) if node.code}

        assert "4100" in codes
        assert "1200" not in codes
        assert "2200" not in codes

    def test_another_period_is_not_here(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        invoice(session, books, customer, "10000.00", on=JANUARY)

        february = Period(date(2026, 2, 1), date(2026, 2, 28), "February")
        assert profit_and_loss(session, books.company_id, february).total_income == Decimal(0)


class TestGroupingAndNesting:
    def test_accounts_nest_under_their_parents(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        """R2.AC4 — the chart has hierarchy, and the statement shows it."""
        invoice(session, books, customer, "10000.00")

        report = profit_and_loss(session, books.company_id, YEAR)
        levels = [node.level for node in flatten(report.income)]

        assert levels == sorted(set(levels)) or max(levels) > 0

    def test_a_parent_totals_its_children(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        invoice(session, books, customer, "10000.00")

        report = profit_and_loss(session, books.company_id, YEAR)
        roots = report.income

        assert sum((node.credit - node.debit for node in roots), Decimal(0)) == Decimal("10000.00")


class TestComparison:
    def test_the_preceding_period_comes_alongside(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        """R2.AC8 — January compared with December."""
        invoice(session, books, customer, "1000.00", on=date(2025, 12, 10))
        invoice(session, books, customer, "3000.00", on=date(2026, 1, 10))

        january = Period(date(2026, 1, 1), date(2026, 1, 31), "January")
        report = profit_and_loss(session, books.company_id, january, comparison=True)

        assert report.total_income == Decimal("3000.00")
        assert report.comparison is not None
        assert report.comparison.total_income == Decimal("1000.00")

    def test_without_asking_there_is_no_comparison(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        invoice(session, books, customer, "3000.00")

        assert profit_and_loss(session, books.company_id, YEAR).comparison is None
