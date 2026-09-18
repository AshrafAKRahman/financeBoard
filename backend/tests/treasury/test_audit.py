"""Every money movement leaves a record (R11.AC1, R11.AC2, R11.AC3, R11.AC5)."""

from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ledger.api import JournalEntryLine
from app.platform.audit.api import Actor
from app.platform.audit.models import AuditLog
from app.treasury.matching import match_amount, unmatch
from app.treasury.payments import cancel_payment, create_payment, post_payment
from app.treasury.reconciling import import_statement, reconcile_line, unreconciled_lines
from app.treasury.statements import CsvSource
from tests.factories import TreasuryBooks
from tests.treasury.conftest import draft, make_invoice

pytestmark = pytest.mark.db

ACTOR = Actor(None, "accountant@example.sa")
MAPPING = {"date": "Date", "amount": "Amount", "description": "Narrative", "reference": "Ref"}
STATEMENT = b"Date,Amount,Narrative,Ref\n2026-03-15,1000.00,Receipt,TRX-1\n"


def records(session: Session, company_id: UUID, action: str) -> list[AuditLog]:
    return list(
        session.execute(
            select(AuditLog)
            .where(AuditLog.company_id == company_id, AuditLog.action == action)
            .order_by(AuditLog.at)
        ).scalars()
    )


def open_item(session: Session, entry_id: UUID) -> JournalEntryLine:
    return session.execute(
        select(JournalEntryLine).where(
            JournalEntryLine.entry_id == entry_id, JournalEntryLine.residual.is_not(None)
        )
    ).scalar_one()


def receipt(session: Session, books: TreasuryBooks, partner_id: UUID, amount: str = "1000.00"):
    payment = create_payment(
        session, books.company_id, draft(books, partner_id, amount), actor=ACTOR
    )
    session.flush()
    post_payment(session, books.company_id, payment.id, actor=ACTOR)
    session.flush()
    return payment


class TestPayments:
    def test_posting_names_the_number_and_the_amount(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R11.AC1"""
        payment = receipt(session, books, customer)

        entry = records(session, books.company_id, "payment.posted")[-1]
        assert entry.actor_email == "accountant@example.sa"
        assert entry.detail["number"] == payment.number
        assert entry.detail["amount"] == "1000.00"
        assert entry.target_id == str(payment.id)

    def test_cancelling_names_the_reason_and_the_reversal(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R11.AC1"""
        payment = receipt(session, books, customer)
        cancel_payment(session, books.company_id, payment.id, reason="bounced", actor=ACTOR)

        entry = records(session, books.company_id, "payment.cancelled")[-1]
        assert entry.detail["reason"] == "bounced"
        assert entry.detail["reversal"]

    def test_recording_a_draft_is_recorded_too(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        create_payment(session, books.company_id, draft(books, customer), actor=ACTOR)
        session.flush()

        assert len(records(session, books.company_id, "payment.created")) == 1


class TestMatching:
    def test_matching_names_the_amount_and_both_lines(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R11.AC2"""
        invoice = make_invoice(session, books, customer, "1000.00")
        invoice_line = open_item(session, invoice.journal_entry_id)
        payment_line = open_item(session, receipt(session, books, customer).journal_entry_id)

        match_amount(session, books.company_id, invoice_line.id, payment_line.id, actor=ACTOR)

        entry = records(session, books.company_id, "reconciliation.matched")[-1]
        assert Decimal(entry.detail["amount"]) == Decimal("1000.00")
        assert entry.detail["debit_line"] == str(invoice_line.id)
        assert entry.detail["credit_line"] == str(payment_line.id)

    def test_unmatching_is_recorded_as_well(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R11.AC2 — undoing a match is as interesting as making it."""
        invoice = make_invoice(session, books, customer, "1000.00")
        match = match_amount(
            session,
            books.company_id,
            open_item(session, invoice.journal_entry_id).id,
            open_item(session, receipt(session, books, customer).journal_entry_id).id,
            actor=ACTOR,
        )

        unmatch(session, books.company_id, [match.id], actor=ACTOR)

        assert len(records(session, books.company_id, "reconciliation.unmatched")) == 1

    def test_cancelling_a_payment_records_the_unmatching_it_caused(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        invoice = make_invoice(session, books, customer, "1000.00")
        payment = receipt(session, books, customer)
        match_amount(
            session,
            books.company_id,
            open_item(session, invoice.journal_entry_id).id,
            open_item(session, payment.journal_entry_id).id,
            actor=ACTOR,
        )

        cancel_payment(session, books.company_id, payment.id, actor=ACTOR)

        assert len(records(session, books.company_id, "reconciliation.unmatched")) == 1


class TestStatements:
    def test_importing_names_the_file_and_the_counts(
        self, session: Session, books: TreasuryBooks
    ) -> None:
        """R11.AC3"""
        import_statement(
            session,
            books.company_id,
            books.accounts["1110"],
            CsvSource(MAPPING),
            STATEMENT,
            file_name="march.csv",
            actor=ACTOR,
        )
        session.flush()

        entry = records(session, books.company_id, "statement.imported")[-1]
        assert entry.detail["file"] == "march.csv"
        assert entry.detail["created"] == 1
        assert entry.detail["duplicates"] == 0

    def test_reconciling_a_line_is_recorded(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R11.AC5 — this is the entry that moves the bank, so it is worth recording."""
        payment = receipt(session, books, customer)
        import_statement(
            session,
            books.company_id,
            books.accounts["1110"],
            CsvSource(MAPPING),
            STATEMENT,
            actor=ACTOR,
        )
        session.flush()
        line = unreconciled_lines(session, books.company_id)[0]

        reconcile_line(session, books.company_id, line.id, payment_id=payment.id, actor=ACTOR)

        entry = records(session, books.company_id, "statement_line.reconciled")[-1]
        assert entry.detail["payment"] == payment.number
        assert Decimal(entry.detail["amount"]) == Decimal("1000.00")

    def test_undoing_a_reconciliation_is_recorded(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        from app.treasury.reconciling import undo_reconcile

        payment = receipt(session, books, customer)
        import_statement(
            session,
            books.company_id,
            books.accounts["1110"],
            CsvSource(MAPPING),
            STATEMENT,
            actor=ACTOR,
        )
        session.flush()
        line = unreconciled_lines(session, books.company_id)[0]
        reconcile_line(session, books.company_id, line.id, payment_id=payment.id, actor=ACTOR)

        undo_reconcile(session, books.company_id, line.id, actor=ACTOR)

        assert len(records(session, books.company_id, "statement_line.unreconciled")) == 1
