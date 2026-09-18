"""The reports agree on books nobody designed (R10, NFR1).

Every other test checks an answer somebody worked out in advance. This one builds random but
legal histories — invoices, bills, payments, partial matches, cancellations — and asserts the
identities hold anyway. It is the difference between "the reports agree on the cases we
thought of" and "the reports agree".

Kept deliberately small per example: each one builds real documents against a real database,
so the value is in the variety of shapes, not in the size of any one of them.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.billing.documents import cancel_document
from app.reporting.aged import aged_payables, aged_receivables
from app.reporting.cash_flow import cash_flow
from app.reporting.periods import Period
from app.reporting.statements import balance_sheet, profit_and_loss, trial_balance
from app.reporting.vat_return import vat_return
from tests.factories import TreasuryBooks, make_partner, make_treasury_company
from tests.reporting.conftest import bill, invoice, receipt, settle

pytestmark = pytest.mark.db

YEAR = Period(date(2026, 1, 1), date(2026, 12, 31), "2026")
YEAR_END = date(2026, 12, 31)
TODAY = date(2026, 12, 31)
START = date(2026, 1, 5)

# Each step is one thing a company does. The amounts stay small and round so a failure is
# readable; the interest is in the order and the mix, not in the digits.
amounts = st.sampled_from(["100.00", "250.00", "1000.00", "3333.33"])
days = st.integers(min_value=0, max_value=300)

STEP = st.one_of(
    st.tuples(st.just("invoice"), amounts, days),
    st.tuples(st.just("bill"), amounts, days),
    st.tuples(st.just("receipt"), amounts, days),
    st.tuples(st.just("pay-vendor"), amounts, days),
    st.tuples(st.just("settle"), amounts, days),
    st.tuples(st.just("cancel"), amounts, days),
)


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


def build(session: Session, books: TreasuryBooks, customer, vendor, steps) -> None:
    """Run the generated history. Steps that make no sense yet are simply skipped."""
    invoices: list = []
    receipts: list = []

    for kind, amount, offset in steps:
        on = START + timedelta(days=offset)

        if kind == "invoice":
            invoices.append(invoice(session, books, customer, amount, on=on, due=on))
        elif kind == "bill":
            bill(session, books, vendor, amount, on=on)
        elif kind == "receipt":
            receipts.append(receipt(session, books, customer, amount, on=on))
        elif kind == "pay-vendor":
            receipt(session, books, vendor, amount, on=on, direction="outbound")
        elif kind == "settle" and invoices and receipts:
            document = invoices[0]
            payment = receipts[0]
            try:
                settle(session, books, document, payment)
            except Exception:
                session.rollback()
                return
            invoices.pop(0)
            receipts.pop(0)
        elif kind == "cancel" and invoices:
            document = invoices.pop()
            try:
                cancel_document(session, books.company_id, document.id, reason="generated")
            except Exception:
                session.rollback()
                return
        session.flush()


@settings(
    max_examples=12,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(steps=st.lists(STEP, min_size=1, max_size=6))
def test_the_reports_agree_whatever_happened(session: Session, steps) -> None:
    books = make_treasury_company(session)
    customer = make_partner(session, books.company_id, name="Generated Customer").id
    vendor = make_partner(session, books.company_id, name="Generated Vendor", type="vendor").id

    build(session, books, customer, vendor, steps)
    session.flush()

    # The trial balance is zero, which is the premise of everything else.
    balance = trial_balance(session, books.company_id, YEAR)
    assert balance.total_debit == balance.total_credit

    # R10.AC1 — the profit and loss is the balance sheet's movement in earnings.
    year = profit_and_loss(session, books.company_id, YEAR)
    sheet = balance_sheet(session, books.company_id, YEAR_END)
    assert year.net_result == sheet.current_year_earnings

    # R10.AC2 — and the balance sheet balances.
    assert sheet.total_assets == sheet.total_liabilities + sheet.total_equity

    # R10.AC3 — cash in the report is cash in the accounts.
    flow = cash_flow(session, books.company_id, YEAR)
    assert flow.opening_cash + flow.net_movement == flow.closing_cash
    assert flow.closing_cash == cash_balance(session, books, YEAR_END)

    # R10.AC4 — what is owed, and what is owing.
    assert aged_receivables(
        session, books.company_id, YEAR_END, today=TODAY
    ).total == account_balance(session, books, "1200", YEAR_END)
    assert aged_payables(
        session, books.company_id, YEAR_END, today=TODAY
    ).total == -account_balance(session, books, "2100", YEAR_END)

    # R10.AC5 — and what is owed to ZATCA.
    vat = vat_return(session, books.company_id, YEAR)
    assert vat.output_tax == -account_balance(session, books, "2200", YEAR_END)
    assert vat.input_tax == account_balance(session, books, "1300", YEAR_END)

    session.rollback()


@settings(
    max_examples=8,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(
    steps=st.lists(STEP, min_size=1, max_size=5),
    offset=st.integers(min_value=1, max_value=300),
)
def test_aged_receivables_agree_on_any_past_date(session: Session, steps, offset: int) -> None:
    """R10.AC4 — the report as it stood on a date nobody chose in advance."""
    books = make_treasury_company(session)
    customer = make_partner(session, books.company_id, name="Generated Customer").id
    vendor = make_partner(session, books.company_id, name="Generated Vendor", type="vendor").id

    build(session, books, customer, vendor, steps)
    session.flush()

    on = START + timedelta(days=offset)
    report = aged_receivables(session, books.company_id, on, today=TODAY)

    assert report.total == account_balance(session, books, "1200", on)

    session.rollback()
