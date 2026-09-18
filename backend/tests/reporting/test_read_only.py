"""A report changes nothing and comes back quickly (NFR2, NFR3, NFR6)."""

import time
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.reporting.aged import aged_receivables
from app.reporting.cash_flow import cash_flow
from app.reporting.detail import account_detail
from app.reporting.statements import balance_sheet, profit_and_loss, trial_balance
from app.reporting.vat_return import vat_return
from tests.factories import TreasuryBooks
from tests.reporting.conftest import JANUARY, YEAR, bill, invoice, receipt

pytestmark = pytest.mark.db

YEAR_END = date(2026, 12, 31)


def fingerprint(session: Session, books: TreasuryBooks) -> tuple:
    """Everything a report could plausibly disturb."""
    return tuple(
        session.execute(
            text(
                "SELECT (SELECT count(*) FROM journal_entry WHERE company_id = :c), "
                "(SELECT count(*) FROM journal_entry_line WHERE company_id = :c), "
                "(SELECT count(*) FROM reconciliation WHERE company_id = :c), "
                "(SELECT count(*) FROM audit_log WHERE company_id = :c), "
                "(SELECT COALESCE(SUM(residual), 0) FROM journal_entry_line "
                " WHERE company_id = :c)"
            ),
            {"c": books.company_id},
        ).one()
    )


def test_running_every_report_changes_nothing(
    session: Session, books: TreasuryBooks, customer, vendor
) -> None:
    """NFR6 — a reader can never move the books, not even by accident."""
    invoice(session, books, customer, "10000.00", on=JANUARY)
    bill(session, books, vendor, "4000.00", on=JANUARY)
    receipt(session, books, customer, "5000.00", on=JANUARY)
    session.commit()

    before = fingerprint(session, books)

    trial_balance(session, books.company_id, YEAR)
    profit_and_loss(session, books.company_id, YEAR, comparison=True)
    balance_sheet(session, books.company_id, YEAR_END)
    cash_flow(session, books.company_id, YEAR)
    aged_receivables(session, books.company_id, YEAR_END, today=YEAR_END)
    aged_receivables(session, books.company_id, date(2026, 2, 1), today=YEAR_END)
    vat_return(session, books.company_id, YEAR)
    account_detail(session, books.company_id, books.accounts["1200"], YEAR)
    session.commit()

    assert fingerprint(session, books) == before


def test_every_figure_is_a_decimal(session: Session, books: TreasuryBooks, customer) -> None:
    """NFR2 — no floats anywhere near money."""
    invoice(session, books, customer, "3333.33", on=JANUARY)
    session.flush()

    report = trial_balance(session, books.company_id, YEAR)
    sheet = balance_sheet(session, books.company_id, YEAR_END)

    assert isinstance(report.total_debit, Decimal)
    assert isinstance(sheet.current_year_earnings, Decimal)
    assert all(isinstance(node.closing, Decimal) for node in report.rows)


def test_a_year_of_entries_reports_within_two_seconds(
    session: Session, books: TreasuryBooks, customer
) -> None:
    """NFR3 — the reason Phase 1 needs no cache."""
    for month in range(1, 13):
        for day in (5, 15, 25):
            invoice(session, books, customer, "1000.00", on=date(2026, month, day))
    session.commit()

    started = time.perf_counter()
    trial_balance(session, books.company_id, YEAR)
    profit_and_loss(session, books.company_id, YEAR)
    balance_sheet(session, books.company_id, YEAR_END)
    elapsed = time.perf_counter() - started

    assert elapsed < 2.0, f"three statements took {elapsed:.2f}s"
