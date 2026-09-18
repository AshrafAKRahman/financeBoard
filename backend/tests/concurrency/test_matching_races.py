"""Two clerks, one invoice (R11.AC4, R11.AC5).

The failure this prevents is paying an invoice twice: two people open the same invoice, each
matches a payment to it, and both succeed. Each thread uses its own connection and its own
transaction, as two API requests would.
"""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from uuid import UUID

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.ledger.api import JournalEntryLine
from app.shared.errors import DomainError
from app.treasury.matching import match_amount
from app.treasury.payments import create_payment, post_payment
from app.treasury.reconciling import import_statement, reconcile_line, unreconciled_lines
from app.treasury.statements import CsvSource
from tests.factories import TreasuryBooks, make_partner, make_treasury_company
from tests.treasury.conftest import draft, make_invoice

pytestmark = pytest.mark.db

MAPPING = {"date": "Date", "amount": "Amount", "description": "Narrative", "reference": "Ref"}
STATEMENT = b"Date,Amount,Narrative,Ref\n2026-03-15,1000.00,Receipt,TRX-1\n"


def open_item(session: Session, entry_id: UUID) -> UUID:
    return session.execute(
        select(JournalEntryLine.id).where(
            JournalEntryLine.entry_id == entry_id, JournalEntryLine.residual.is_not(None)
        )
    ).scalar_one()


def receipt(session: Session, books: TreasuryBooks, partner_id: UUID, amount: str) -> UUID:
    payment = create_payment(session, books.company_id, draft(books, partner_id, amount))
    session.flush()
    post_payment(session, books.company_id, payment.id)
    session.commit()
    return payment.journal_entry_id


def matched_total(engine: Engine, line_id: UUID) -> Decimal:
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT coalesce(sum(CASE WHEN debit_line_id = :l THEN debit_amount "
                "ELSE credit_amount END), 0) FROM reconciliation "
                "WHERE debit_line_id = :l OR credit_line_id = :l"
            ),
            {"l": line_id},
        ).scalar_one()


def test_two_threads_cannot_pay_one_invoice_twice(engine: Engine, session: Session) -> None:
    """R11.AC4 — the invoice is 1,000 and two receipts of 1,000 are waiting."""
    books = make_treasury_company(session)
    customer = make_partner(session, books.company_id, name="Al Noor Est", type="customer").id
    invoice = make_invoice(session, books, customer, "1000.00")
    invoice_line = open_item(session, invoice.journal_entry_id)
    payments = [open_item(session, receipt(session, books, customer, "1000.00")) for _ in range(2)]
    barrier = Barrier(2)

    def worker(payment_line: UUID) -> str:
        barrier.wait()
        with Session(engine) as own:
            try:
                match_amount(own, books.company_id, invoice_line, payment_line)
                own.commit()
                return "matched"
            except DomainError as error:
                own.rollback()
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(worker, payments))

    assert outcomes.count("matched") == 1
    assert sorted(outcomes)[0] in ("matched", "payments.already_reconciled")
    assert matched_total(engine, invoice_line) == Decimal("1000.000000")


def test_the_total_matched_never_exceeds_what_is_open(engine: Engine, session: Session) -> None:
    """R11.AC4 — four threads, each matching 400 against a 1,000 invoice."""
    books = make_treasury_company(session)
    customer = make_partner(session, books.company_id, name="Al Noor Est", type="customer").id
    invoice = make_invoice(session, books, customer, "1000.00")
    invoice_line = open_item(session, invoice.journal_entry_id)
    payments = [open_item(session, receipt(session, books, customer, "400.00")) for _ in range(4)]
    barrier = Barrier(4)

    def worker(payment_line: UUID) -> str:
        barrier.wait()
        with Session(engine) as own:
            try:
                match_amount(own, books.company_id, invoice_line, payment_line, Decimal("400.00"))
                own.commit()
                return "matched"
            except DomainError as error:
                own.rollback()
                return error.code

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(worker, payments))

    # Two full matches fit in 1,000; the rest must be refused rather than squeezed in.
    assert outcomes.count("matched") == 2
    assert matched_total(engine, invoice_line) <= Decimal("1000.000000")

    with engine.connect() as connection:
        still_open = connection.execute(
            text("SELECT residual FROM journal_entry_line WHERE id = :l"), {"l": invoice_line}
        ).scalar_one()
    assert still_open == Decimal("200.000000")


def test_only_one_thread_reconciles_a_statement_line(engine: Engine, session: Session) -> None:
    """R11.AC5 — the bank must not be credited twice for one row."""
    books = make_treasury_company(session)
    customer = make_partner(session, books.company_id, name="Al Noor Est", type="customer").id
    payments = []
    for _ in range(2):
        payment = create_payment(session, books.company_id, draft(books, customer, "1000.00"))
        session.flush()
        post_payment(session, books.company_id, payment.id)
        payments.append(payment.id)
    session.commit()

    import_statement(
        session, books.company_id, books.accounts["1110"], CsvSource(MAPPING), STATEMENT
    )
    session.commit()
    line_id = unreconciled_lines(session, books.company_id)[0].id
    barrier = Barrier(2)

    def worker(payment_id: UUID) -> str:
        barrier.wait()
        with Session(engine) as own:
            try:
                reconcile_line(own, books.company_id, line_id, payment_id=payment_id)
                own.commit()
                return "reconciled"
            except DomainError as error:
                own.rollback()
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(worker, payments))

    assert outcomes.count("reconciled") == 1
    with engine.connect() as connection:
        # The proof that matters: the bank account was credited once, not twice.
        balance = connection.execute(
            text(
                "SELECT coalesce(sum(debit - credit), 0) FROM journal_entry_line "
                "WHERE company_id = :c AND account_id = :a"
            ),
            {"c": books.company_id, "a": books.accounts["1110"]},
        ).scalar_one()
        attempts = connection.execute(
            text(
                "SELECT count(*) FROM audit_log "
                "WHERE action = 'statement_line.reconciled' AND target_id = :l"
            ),
            {"l": str(line_id)},
        ).scalar_one()
    assert balance == Decimal("1000.000000")
    assert attempts == 1


def test_a_refused_match_leaves_the_open_amount_untouched(engine: Engine, session: Session) -> None:
    """R11.AC4 — a loser must roll back completely, not partly."""
    books = make_treasury_company(session)
    customer = make_partner(session, books.company_id, name="Al Noor Est", type="customer").id
    invoice = make_invoice(session, books, customer, "500.00")
    invoice_line = open_item(session, invoice.journal_entry_id)
    payments = [open_item(session, receipt(session, books, customer, "500.00")) for _ in range(3)]
    barrier = Barrier(3)

    def worker(payment_line: UUID) -> str:
        barrier.wait()
        with Session(engine) as own:
            try:
                match_amount(own, books.company_id, invoice_line, payment_line)
                own.commit()
                return "matched"
            except DomainError as error:
                own.rollback()
                return error.code

    with ThreadPoolExecutor(max_workers=3) as pool:
        outcomes = list(pool.map(worker, payments))

    assert outcomes.count("matched") == 1
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT residual, reconciled FROM journal_entry_line WHERE id = :l"),
            {"l": invoice_line},
        ).one()
    assert row == (Decimal("0.000000"), True)
