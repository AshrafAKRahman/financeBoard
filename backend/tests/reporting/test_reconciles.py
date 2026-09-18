"""The reports agree with each other and with the ledger (R10).

Each of these is an identity an auditor would check by hand. If one fails, one of the reports
is lying, and the ledger is the one that is right.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.reporting.aged import aged_payables, aged_receivables
from app.reporting.balances import flatten
from app.reporting.cash_flow import cash_flow
from app.reporting.detail import account_detail
from app.reporting.periods import Period
from app.reporting.statements import balance_sheet, profit_and_loss, trial_balance
from app.reporting.vat_return import vat_return
from tests.factories import TreasuryBooks
from tests.reporting.conftest import (
    FEBRUARY,
    JANUARY,
    MARCH,
    YEAR,
    bill,
    cash_entry,
    invoice,
    receipt,
    settle,
)

pytestmark = pytest.mark.db

YEAR_END = date(2026, 12, 31)
TODAY = date(2026, 12, 31)


@pytest.fixture
def busy(session: Session, books: TreasuryBooks, customer, vendor) -> TreasuryBooks:
    """A company that has done enough for the reports to have something to disagree about."""
    paid = invoice(session, books, customer, "10000.00", on=JANUARY, due=date(2026, 2, 14))
    invoice(session, books, customer, "4000.00", on=MARCH, due=date(2026, 4, 30))
    bill(session, books, vendor, "3000.00", on=JANUARY)
    bill(session, books, vendor, "1500.00", on=FEBRUARY)

    payment = receipt(session, books, customer, "11500.00", on=FEBRUARY)
    settle(session, books, paid, payment)

    part = invoice(session, books, customer, "2000.00", on=FEBRUARY)
    small = receipt(session, books, customer, "1000.00", on=MARCH)
    settle(session, books, part, small, "1000.00")

    cash_entry(
        session,
        books,
        on=MARCH,
        cash_account="1110",
        other_account="5300",
        amount="800.00",
        cash_in=False,
    )
    session.commit()
    return books


def account_balance(session: Session, books: TreasuryBooks, code: str, on: date) -> Decimal:
    return session.execute(
        text(
            "SELECT COALESCE(SUM(l.debit - l.credit), 0) FROM journal_entry_line l "
            "JOIN journal_entry e ON e.id = l.entry_id "
            "WHERE l.company_id = :c AND e.state = 'posted' AND l.account_id = :a AND e.date <= :on"
        ),
        {"c": books.company_id, "a": books.accounts[code], "on": on},
    ).scalar_one()


def cash_balance(session: Session, books: TreasuryBooks, on: date) -> Decimal:
    """Every bank and cash account, read from the chart rather than named by code — so the
    test cannot drift from what the cash flow statement considers cash."""
    return session.execute(
        text(
            "SELECT COALESCE(SUM(l.debit - l.credit), 0) FROM journal_entry_line l "
            "JOIN journal_entry e ON e.id = l.entry_id "
            "JOIN account a ON a.id = l.account_id "
            "WHERE l.company_id = :c AND e.state = 'posted' "
            "AND a.subtype = 'bank_cash' AND e.date <= :on"
        ),
        {"c": books.company_id, "on": on},
    ).scalar_one()


def test_the_trial_balance_is_zero(session: Session, busy: TreasuryBooks) -> None:
    """The one every other identity rests on."""
    report = trial_balance(session, busy.company_id, YEAR)
    assert report.total_debit == report.total_credit


def test_the_profit_and_loss_matches_the_balance_sheet(
    session: Session, busy: TreasuryBooks
) -> None:
    """R10.AC1"""
    year = profit_and_loss(session, busy.company_id, YEAR)
    sheet = balance_sheet(session, busy.company_id, YEAR_END)

    assert year.net_result == sheet.current_year_earnings


def test_the_balance_sheet_balances(session: Session, busy: TreasuryBooks) -> None:
    """R10.AC2"""
    sheet = balance_sheet(session, busy.company_id, YEAR_END)
    assert sheet.total_assets == sheet.total_liabilities + sheet.total_equity


@pytest.mark.parametrize("on", [date(2026, 1, 31), date(2026, 2, 28), date(2026, 6, 30)])
def test_the_balance_sheet_balances_on_any_date(
    session: Session, busy: TreasuryBooks, on: date
) -> None:
    """R10.AC2 — not just at the year end."""
    sheet = balance_sheet(session, busy.company_id, on)
    assert sheet.total_assets == sheet.total_liabilities + sheet.total_equity


def test_the_cash_flow_matches_the_cash_accounts(session: Session, busy: TreasuryBooks) -> None:
    """R10.AC3"""
    report = cash_flow(session, busy.company_id, YEAR)

    assert report.opening_cash + report.net_movement == report.closing_cash
    assert report.closing_cash == cash_balance(session, busy, YEAR_END)


def test_aged_receivables_match_the_receivable_account(
    session: Session, busy: TreasuryBooks
) -> None:
    """R10.AC4, R5.AC5"""
    report = aged_receivables(session, busy.company_id, YEAR_END, today=TODAY)
    assert report.total == account_balance(session, busy, "1200", YEAR_END)


def test_aged_payables_match_the_payable_account(session: Session, busy: TreasuryBooks) -> None:
    """R10.AC4 read from the other side; payables are a credit balance."""
    report = aged_payables(session, busy.company_id, YEAR_END, today=TODAY)
    assert report.total == -account_balance(session, busy, "2100", YEAR_END)


@pytest.mark.parametrize("on", [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)])
def test_aged_receivables_match_on_a_past_date(
    session: Session, busy: TreasuryBooks, on: date
) -> None:
    """R10.AC4 — the hard case: the report as it stood, not as it stands."""
    report = aged_receivables(session, busy.company_id, on, today=TODAY)
    assert report.total == account_balance(session, busy, "1200", on)


def test_the_vat_return_matches_the_vat_accounts(session: Session, busy: TreasuryBooks) -> None:
    """R10.AC5"""
    report = vat_return(session, busy.company_id, YEAR)

    output = -account_balance(session, busy, "2200", YEAR_END)
    paid = account_balance(session, busy, "1300", YEAR_END)

    assert report.output_tax == output
    assert report.input_tax == paid


def test_an_accounts_detail_closes_where_the_trial_balance_says(
    session: Session, busy: TreasuryBooks
) -> None:
    """R10.AC6 — for every account that moved."""
    report = trial_balance(session, busy.company_id, YEAR, hide_unused=True)

    for node in flatten(report.rows):
        if node.is_group or node.account_id is None:
            continue
        detail = account_detail(session, busy.company_id, node.account_id, YEAR)
        assert detail.closing_balance == node.closing, node.code


def test_a_draft_entry_is_in_no_report(session: Session, books: TreasuryBooks, customer) -> None:
    """R10.AC7"""
    invoice(session, books, customer, "9000.00", on=JANUARY, post_it=False)
    session.flush()

    assert trial_balance(session, books.company_id, YEAR).total_debit == Decimal(0)
    assert profit_and_loss(session, books.company_id, YEAR).total_income == Decimal(0)
    assert balance_sheet(session, books.company_id, YEAR_END).total_assets == Decimal(0)


def test_a_reversal_shows_as_a_correction_not_a_disappearance(
    session: Session, books: TreasuryBooks, customer
) -> None:
    """R10.AC8 — both entries stay, and the reports net to nothing."""
    from app.billing.documents import cancel_document

    document = invoice(session, books, customer, "9000.00", on=JANUARY)
    cancel_document(session, books.company_id, document.id, reason="wrong customer")
    session.flush()

    detail = account_detail(session, books.company_id, books.accounts["1200"], YEAR)
    report = profit_and_loss(session, books.company_id, YEAR)

    assert len(detail.lines) == 2
    assert detail.closing_balance == Decimal(0)
    assert report.total_income == Decimal(0)


def test_a_period_with_nothing_in_it_still_reconciles(
    session: Session, books: TreasuryBooks
) -> None:
    """Empty books are the easiest case to get wrong."""
    empty = Period(date(2020, 1, 1), date(2020, 12, 31), "2020")

    assert trial_balance(session, books.company_id, empty).balances
    assert balance_sheet(session, books.company_id, date(2020, 12, 31)).balances
    assert cash_flow(session, books.company_id, empty).reconciles
    assert aged_receivables(
        session, books.company_id, date(2020, 12, 31), today=TODAY
    ).total == Decimal(0)
