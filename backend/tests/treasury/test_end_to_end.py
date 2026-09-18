"""One foreign-currency invoice, from issue to reconciled bank (R5.AC4, R6.AC3, NFR6).

Every other test in this suite looks at one step. This one walks the whole way through and
checks the things an auditor would: the invoice reads as paid, the exchange difference is in
the ledger, the bank account holds what the bank said, and the trial balance is still zero.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ledger.api import ExchangeRate, JournalEntry, JournalEntryLine
from app.shared.ids import uuid7
from app.treasury.matching import match_amount, open_lines
from app.treasury.payments import create_payment, post_payment
from app.treasury.reconciling import import_statement, reconcile_line, unreconciled_lines
from app.treasury.state import payment_state_of
from app.treasury.statements import CsvSource
from tests.factories import TreasuryBooks
from tests.treasury.conftest import draft, make_invoice

pytestmark = pytest.mark.db

INVOICE_DATE = date(2026, 3, 1)
PAYMENT_DATE = date(2026, 3, 15)
MAPPING = {"date": "Date", "amount": "Amount", "description": "Narrative", "reference": "Ref"}
# The bank sees SAR: USD 100 at 3.75 is 375.00.
STATEMENT = b"Date,Amount,Narrative,Ref\n2026-03-15,375.00,Al Noor Est,TRX-1\n"


def balance(session: Session, company_id: UUID, account_id: UUID) -> Decimal:
    return session.execute(
        select(func.coalesce(func.sum(JournalEntryLine.debit - JournalEntryLine.credit), 0)).where(
            JournalEntryLine.company_id == company_id,
            JournalEntryLine.account_id == account_id,
        )
    ).scalar_one()


def trial_balance(session: Session, company_id: UUID) -> Decimal:
    return session.execute(
        select(func.coalesce(func.sum(JournalEntryLine.debit - JournalEntryLine.credit), 0)).where(
            JournalEntryLine.company_id == company_id
        )
    ).scalar_one()


def test_a_foreign_currency_invoice_through_to_a_reconciled_bank(
    session: Session, books: TreasuryBooks, customer: UUID
) -> None:
    # USD was worth 3.80 when the invoice went out and 3.75 when it was paid.
    for on, rate in ((INVOICE_DATE, "3.80"), (PAYMENT_DATE, "3.75")):
        session.add(
            ExchangeRate(
                id=uuid7(),
                company_id=books.company_id,
                currency_code="USD",
                rate_date=on,
                rate=Decimal(rate),
            )
        )
    session.commit()

    # 1. Issue a USD 100 invoice: the customer owes SAR 380.
    invoice = make_invoice(session, books, customer, "100.00", currency="USD", on=INVOICE_DATE)
    assert payment_state_of(session, invoice).state == "not_paid"
    assert balance(session, books.company_id, books.accounts["1200"]) == Decimal("380.00")

    # 2. Record and post the receipt: still nothing in the bank account.
    payment = create_payment(
        session,
        books.company_id,
        draft(books, customer, "100.00", currency_code="USD", date=PAYMENT_DATE),
    )
    session.flush()
    post_payment(session, books.company_id, payment.id)
    session.commit()
    assert balance(session, books.company_id, books.accounts["1110"]) == Decimal(0)

    # 3. Match them. The rate moved, so the difference is a realised loss of SAR 5.
    items = {item.line.entry_id: item.line for item in open_lines(session, books.company_id)}
    match = match_amount(
        session,
        books.company_id,
        items[invoice.journal_entry_id].id,
        items[payment.journal_entry_id].id,
    )
    session.commit()

    assert match.fx_entry_id is not None
    assert balance(session, books.company_id, books.accounts["5800"]) == Decimal("5.00")
    # R6.AC3 read at the top of the scale: the invoice is settled.
    assert payment_state_of(session, invoice).state == "paid"
    # NFR6 — nothing is left open on the customer's account.
    assert open_lines(session, books.company_id, partner_id=customer) == []
    # The receivable account is back to zero, difference and all.
    assert balance(session, books.company_id, books.accounts["1200"]) == Decimal(0)

    # 4. The bank's own statement arrives and is reconciled.
    import_statement(
        session,
        books.company_id,
        books.accounts["1110"],
        CsvSource(MAPPING),
        STATEMENT,
        file_name="march.csv",
    )
    session.commit()
    line = unreconciled_lines(session, books.company_id)[0]
    reconcile_line(session, books.company_id, line.id, payment_id=payment.id)
    session.commit()

    # 5. Now, and only now, the bank account holds what the bank says it holds.
    assert balance(session, books.company_id, books.accounts["1110"]) == Decimal("375.00")
    assert balance(session, books.company_id, books.accounts["1120"]) == Decimal(0)
    assert unreconciled_lines(session, books.company_id) == []

    # 6. And the books still balance, after five entries in three currencies' worth of work.
    assert trial_balance(session, books.company_id) == Decimal(0)
    entries = session.execute(
        select(func.count())
        .select_from(JournalEntry)
        .where(JournalEntry.company_id == books.company_id, JournalEntry.state == "posted")
    ).scalar_one()
    assert entries == 4


def test_a_part_paid_invoice_reads_as_part_paid_all_the_way_through(
    session: Session, books: TreasuryBooks, customer: UUID
) -> None:
    """The same walk in company currency, stopping halfway: 400 of a 1,000 invoice."""
    invoice = make_invoice(session, books, customer, "1000.00")
    payment = create_payment(session, books.company_id, draft(books, customer, "400.00"))
    session.flush()
    post_payment(session, books.company_id, payment.id)
    session.commit()

    items = {item.line.entry_id: item.line for item in open_lines(session, books.company_id)}
    match_amount(
        session,
        books.company_id,
        items[invoice.journal_entry_id].id,
        items[payment.journal_entry_id].id,
    )
    session.commit()

    state = payment_state_of(session, invoice)
    assert (state.state, state.paid, state.open_amount) == (
        "partial",
        Decimal("400.00"),
        Decimal("600.00"),
    )
    # NFR6 — the aged position is one query against the ledger.
    remaining = open_lines(session, books.company_id, partner_id=customer)
    assert [line.line.residual for line in remaining] == [Decimal("600.00")]
    assert trial_balance(session, books.company_id) == Decimal(0)
