"""The trial balance (R1) — the report every other report is checked against."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.reporting.balances import flatten
from app.reporting.periods import Period
from app.reporting.statements import trial_balance
from app.shared.errors import DomainError
from tests.factories import TreasuryBooks
from tests.reporting.conftest import JANUARY, YEAR, invoice

pytestmark = pytest.mark.db


def rows_by_code(report) -> dict[str, object]:
    return {node.code: node for node in flatten(report.rows) if node.code}


class TestTheFigures:
    def test_an_invoice_appears_on_both_sides(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        """R1.AC1 — 10,000 plus 15% VAT: receivable 11,500, revenue 10,000, VAT 1,500."""
        invoice(session, books, customer, "10000.00")

        rows = rows_by_code(trial_balance(session, books.company_id, YEAR))

        assert rows["1200"].debit == Decimal("11500.00")
        assert rows["4100"].credit == Decimal("10000.00")
        assert rows["2200"].credit == Decimal("1500.00")

    def test_debits_equal_credits(self, session: Session, simple) -> None:
        """R1.AC4 — the check the whole system rests on."""
        report = trial_balance(session, simple.books.company_id, YEAR)

        assert report.balances
        assert report.total_debit == report.total_credit

    def test_closing_is_opening_plus_movement(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        invoice(session, books, customer, "10000.00")

        row = rows_by_code(trial_balance(session, books.company_id, YEAR))["1200"]
        assert row.closing == row.opening + row.debit - row.credit


class TestOpeningBalances:
    def test_an_earlier_invoice_becomes_an_opening_balance(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        """R1.AC5 — January's invoice is February's opening balance."""
        invoice(session, books, customer, "10000.00", on=JANUARY)

        february = Period(date(2026, 2, 1), date(2026, 2, 28), "February")
        row = rows_by_code(trial_balance(session, books.company_id, february))["1200"]

        assert row.opening == Decimal("11500.00")
        assert row.debit == Decimal(0)

    def test_the_period_shows_only_its_own_movement(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        invoice(session, books, customer, "10000.00", on=JANUARY)
        invoice(session, books, customer, "2000.00", on=date(2026, 2, 10))

        february = Period(date(2026, 2, 1), date(2026, 2, 28), "February")
        row = rows_by_code(trial_balance(session, books.company_id, february))["1200"]

        assert row.opening == Decimal("11500.00")
        assert row.debit == Decimal("2300.00")
        assert row.closing == Decimal("13800.00")


class TestWhatIsIncluded:
    def test_a_draft_invoice_is_invisible(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        """R1.AC2 — only posted entries are accounting."""
        invoice(session, books, customer, "10000.00", post_it=False)

        report = trial_balance(session, books.company_id, YEAR)
        assert report.total_debit == Decimal(0)

    def test_group_accounts_carry_subtotals_not_lines(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        """R1.AC8 — nothing posts to a group, but it still totals its children."""
        invoice(session, books, customer, "10000.00")

        rows = rows_by_code(trial_balance(session, books.company_id, YEAR, hide_unused=True))
        posting_accounts = [node for node in rows.values() if not node.is_group]
        assert all(node.debit or node.credit or node.opening for node in posting_accounts)

    def test_unused_accounts_can_be_hidden(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        """R1.AC6 — a 51-account chart with three accounts used is mostly noise."""
        invoice(session, books, customer, "10000.00")

        everything = trial_balance(session, books.company_id, YEAR)
        trimmed = trial_balance(session, books.company_id, YEAR, hide_unused=True)

        assert len(flatten(trimmed.rows)) < len(flatten(everything.rows))
        assert {"1200", "4100", "2200"} <= {n.code for n in flatten(trimmed.rows) if n.code}

    def test_one_journal_can_be_singled_out(
        self, session: Session, books: TreasuryBooks, customer, vendor
    ) -> None:
        """R8.AC6"""
        from tests.reporting.conftest import bill

        invoice(session, books, customer, "10000.00")
        bill(session, books, vendor, "4000.00")

        sales_only = trial_balance(
            session, books.company_id, YEAR, journal_id=books.journals["INV"], hide_unused=True
        )
        codes = {node.code for node in flatten(sales_only.rows) if node.code}

        assert "4100" in codes
        assert "5300" not in codes


class TestCurrencyAndPeriods:
    def test_every_figure_is_in_the_companys_currency(self, session: Session, simple) -> None:
        """R1.AC3"""
        report = trial_balance(session, simple.books.company_id, YEAR)
        assert report.meta.currency_code == "SAR"

    def test_a_backwards_period_is_refused(self, session: Session, books: TreasuryBooks) -> None:
        """R1.AC7"""
        with pytest.raises(DomainError) as caught:
            Period(date(2026, 12, 31), date(2026, 1, 1), "backwards")
        assert caught.value.code == "reporting.invalid_period"

    def test_the_report_says_what_it_covers(self, session: Session, simple) -> None:
        """R8.AC5"""
        report = trial_balance(session, simple.books.company_id, YEAR)

        assert report.meta.company_name == "Jeddah Trading"
        assert report.meta.period == YEAR
        assert report.meta.generated_at is not None
