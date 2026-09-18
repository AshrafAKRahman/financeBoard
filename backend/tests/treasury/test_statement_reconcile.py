"""Reconciling a statement line to the bank account (R8)."""

from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ledger.api import JournalEntry, JournalEntryLine
from app.shared.errors import DomainError
from app.shared.ids import uuid7
from app.treasury.models import BankStatementLine
from app.treasury.payments import create_payment, post_payment
from app.treasury.reconciling import (
    import_statement,
    reconcile_line,
    suggest_for_statement_line,
    undo_reconcile,
    unreconciled_lines,
)
from app.treasury.statements import CsvSource
from tests.factories import TreasuryBooks
from tests.treasury.conftest import draft

pytestmark = pytest.mark.db

MAPPING = {"date": "Date", "amount": "Amount", "description": "Narrative", "reference": "Ref"}
STATEMENT = b"""Date,Amount,Narrative,Ref
2026-03-15,1000.00,Receipt from Al Noor,TRX-1
2026-03-16,-750.00,Paid Jeddah Properties,TRX-2
"""


@pytest.fixture
def statement_lines(session: Session, books: TreasuryBooks) -> list[BankStatementLine]:
    import_statement(
        session,
        books.company_id,
        books.accounts["1110"],
        CsvSource(MAPPING),
        STATEMENT,
        file_name="march.csv",
    )
    session.commit()
    return unreconciled_lines(session, books.company_id)


def receipt(session: Session, books: TreasuryBooks, partner_id: UUID, amount: str, **overrides):
    payment = create_payment(
        session, books.company_id, draft(books, partner_id, amount, **overrides)
    )
    session.flush()
    post_payment(session, books.company_id, payment.id)
    session.flush()
    return payment


def amounts_by_account(session: Session, entry_id: UUID) -> dict[UUID, tuple[Decimal, Decimal]]:
    lines = session.execute(
        select(JournalEntryLine).where(JournalEntryLine.entry_id == entry_id)
    ).scalars()
    return {line.account_id: (line.debit, line.credit) for line in lines}


class TestMoneyIn:
    def test_the_bank_account_is_debited_and_outstanding_receipts_cleared(
        self,
        session: Session,
        books: TreasuryBooks,
        customer: UUID,
        statement_lines: list[BankStatementLine],
    ) -> None:
        """R8.AC1, R8.AC2 — this is the entry that finally moves the bank."""
        payment = receipt(session, books, customer, "1000.00")
        line = statement_lines[0]

        reconcile_line(session, books.company_id, line.id, payment_id=payment.id)

        amounts = amounts_by_account(session, line.journal_entry_id)
        assert amounts[books.accounts["1110"]] == (Decimal("1000.00"), Decimal(0))
        assert amounts[books.accounts["1120"]] == (Decimal(0), Decimal("1000.00"))

    def test_the_line_records_what_it_was_reconciled_to(
        self,
        session: Session,
        books: TreasuryBooks,
        customer: UUID,
        statement_lines: list[BankStatementLine],
    ) -> None:
        """R8.AC3"""
        payment = receipt(session, books, customer, "1000.00")
        line = statement_lines[0]

        reconcile_line(session, books.company_id, line.id, payment_id=payment.id)

        assert line.payment_id == payment.id
        assert line.reconciled_at is not None
        assert line.journal_entry_id is not None

    def test_a_reconciled_line_leaves_the_to_do_list(
        self,
        session: Session,
        books: TreasuryBooks,
        customer: UUID,
        statement_lines: list[BankStatementLine],
    ) -> None:
        payment = receipt(session, books, customer, "1000.00")
        reconcile_line(session, books.company_id, statement_lines[0].id, payment_id=payment.id)
        session.flush()

        remaining = unreconciled_lines(session, books.company_id)
        assert [line.id for line in remaining] == [statement_lines[1].id]

    def test_the_entry_takes_its_date_from_the_bank(
        self,
        session: Session,
        books: TreasuryBooks,
        customer: UUID,
        statement_lines: list[BankStatementLine],
    ) -> None:
        """When the money moved is the bank's business, not ours."""
        payment = receipt(session, books, customer, "1000.00")
        line = statement_lines[0]

        reconcile_line(session, books.company_id, line.id, payment_id=payment.id)

        entry = session.get(JournalEntry, line.journal_entry_id)
        assert entry.date == line.date
        assert entry.ref == line.bank_reference


class TestMoneyOut:
    def test_the_bank_account_is_credited(
        self,
        session: Session,
        books: TreasuryBooks,
        vendor: UUID,
        statement_lines: list[BankStatementLine],
    ) -> None:
        """R8.AC1 read the other way."""
        payment = receipt(session, books, vendor, "750.00", direction="outbound")
        line = statement_lines[1]

        reconcile_line(session, books.company_id, line.id, payment_id=payment.id)

        amounts = amounts_by_account(session, line.journal_entry_id)
        assert amounts[books.accounts["1110"]] == (Decimal(0), Decimal("750.00"))
        assert amounts[books.accounts["2120"]] == (Decimal("750.00"), Decimal(0))


class TestWhatIsRefused:
    def test_a_line_cannot_be_reconciled_twice(
        self,
        session: Session,
        books: TreasuryBooks,
        customer: UUID,
        statement_lines: list[BankStatementLine],
    ) -> None:
        """R8.AC4"""
        first = receipt(session, books, customer, "1000.00")
        second = receipt(session, books, customer, "1000.00")
        reconcile_line(session, books.company_id, statement_lines[0].id, payment_id=first.id)

        with pytest.raises(DomainError) as caught:
            reconcile_line(session, books.company_id, statement_lines[0].id, payment_id=second.id)
        assert caught.value.code == "payments.already_reconciled"

    def test_a_different_amount_is_refused(
        self,
        session: Session,
        books: TreasuryBooks,
        customer: UUID,
        statement_lines: list[BankStatementLine],
    ) -> None:
        """R8.AC7 — the bank says 1,000; a 900 payment is not this line."""
        payment = receipt(session, books, customer, "900.00")

        with pytest.raises(DomainError) as caught:
            reconcile_line(session, books.company_id, statement_lines[0].id, payment_id=payment.id)
        assert caught.value.code == "payments.amount_mismatch"

    def test_money_in_cannot_be_an_outbound_payment(
        self,
        session: Session,
        books: TreasuryBooks,
        vendor: UUID,
        statement_lines: list[BankStatementLine],
    ) -> None:
        """R8.AC7"""
        payment = receipt(session, books, vendor, "1000.00", direction="outbound")

        with pytest.raises(DomainError) as caught:
            reconcile_line(session, books.company_id, statement_lines[0].id, payment_id=payment.id)
        assert caught.value.code == "payments.wrong_direction"

    def test_a_draft_payment_cannot_be_reconciled(
        self,
        session: Session,
        books: TreasuryBooks,
        customer: UUID,
        statement_lines: list[BankStatementLine],
    ) -> None:
        payment = create_payment(session, books.company_id, draft(books, customer, "1000.00"))
        session.flush()

        with pytest.raises(DomainError) as caught:
            reconcile_line(session, books.company_id, statement_lines[0].id, payment_id=payment.id)
        assert caught.value.code == "payments.not_posted"

    def test_an_unknown_statement_line_is_not_found(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        payment = receipt(session, books, customer, "1000.00")

        with pytest.raises(DomainError) as caught:
            reconcile_line(session, books.company_id, uuid7(), payment_id=payment.id)
        assert caught.value.code == "payments.statement_line_not_found"

    def test_a_withheld_payment_matches_on_what_actually_moved(
        self, session: Session, books: TreasuryBooks, vendor: UUID
    ) -> None:
        """R9.AC2 — the bank only ever sees the net amount.

        A 1,000 bill with 5% withheld leaves 950 in the bank statement, and that is what
        the line has to agree with.
        """
        import_statement(
            session,
            books.company_id,
            books.accounts["1110"],
            CsvSource(MAPPING),
            b"Date,Amount,Narrative,Ref\n2026-03-16,-950.00,Paid a non-resident,TRX-5\n",
        )
        session.commit()
        line = unreconciled_lines(session, books.company_id)[0]
        payment = receipt(
            session,
            books,
            vendor,
            "1000.00",
            direction="outbound",
            withholding_tax_id=books.taxes["withholding"],
        )

        reconcile_line(session, books.company_id, line.id, payment_id=payment.id)

        assert line.reconciled_at is not None
        assert payment.net_amount == Decimal("950.00")


class TestUndoing:
    def test_the_entry_is_reversed_and_the_line_reopens(
        self,
        session: Session,
        books: TreasuryBooks,
        customer: UUID,
        statement_lines: list[BankStatementLine],
    ) -> None:
        """R8.AC5"""
        payment = receipt(session, books, customer, "1000.00")
        line = statement_lines[0]
        reconcile_line(session, books.company_id, line.id, payment_id=payment.id)
        entry_id = line.journal_entry_id

        undo_reconcile(session, books.company_id, line.id)

        reversal = session.execute(
            select(JournalEntry).where(JournalEntry.reversed_entry_id == entry_id)
        ).scalar_one()
        assert reversal.state == "posted"
        assert line.reconciled_at is None
        assert line.payment_id is None

    def test_it_can_then_be_reconciled_to_the_right_payment(
        self,
        session: Session,
        books: TreasuryBooks,
        customer: UUID,
        statement_lines: list[BankStatementLine],
    ) -> None:
        """Correcting a mistake must not need a database administrator."""
        wrong = receipt(session, books, customer, "1000.00")
        right = receipt(session, books, customer, "1000.00")
        line = statement_lines[0]
        reconcile_line(session, books.company_id, line.id, payment_id=wrong.id)
        undo_reconcile(session, books.company_id, line.id)

        reconcile_line(session, books.company_id, line.id, payment_id=right.id)

        assert line.payment_id == right.id

    def test_an_unreconciled_line_cannot_be_undone(
        self,
        session: Session,
        books: TreasuryBooks,
        statement_lines: list[BankStatementLine],
    ) -> None:
        with pytest.raises(DomainError) as caught:
            undo_reconcile(session, books.company_id, statement_lines[0].id)
        assert caught.value.code == "payments.not_reconciled"


class TestSuggestions:
    def test_a_payment_of_the_same_amount_is_suggested(
        self,
        session: Session,
        books: TreasuryBooks,
        customer: UUID,
        statement_lines: list[BankStatementLine],
    ) -> None:
        """R8.AC6"""
        payment = receipt(session, books, customer, "1000.00")

        suggestions = suggest_for_statement_line(session, books.company_id, statement_lines[0].id)

        assert [s.payment.id for s in suggestions] == [payment.id]

    def test_a_matching_reference_is_suggested_first(
        self,
        session: Session,
        books: TreasuryBooks,
        customer: UUID,
        statement_lines: list[BankStatementLine],
    ) -> None:
        """R8.AC6 — the bank's own reference is the strongest signal there is."""
        receipt(session, books, customer, "1000.00")
        referenced = receipt(session, books, customer, "1000.00", reference="TRX-1")

        suggestions = suggest_for_statement_line(session, books.company_id, statement_lines[0].id)

        assert suggestions[0].payment.id == referenced.id
        assert suggestions[0].reason == "the amount and the reference match"

    def test_the_wrong_direction_is_never_suggested(
        self,
        session: Session,
        books: TreasuryBooks,
        vendor: UUID,
        statement_lines: list[BankStatementLine],
    ) -> None:
        receipt(session, books, vendor, "1000.00", direction="outbound")

        assert suggest_for_statement_line(session, books.company_id, statement_lines[0].id) == []

    def test_an_already_reconciled_payment_is_not_suggested_again(
        self,
        session: Session,
        books: TreasuryBooks,
        customer: UUID,
        statement_lines: list[BankStatementLine],
    ) -> None:
        payment = receipt(session, books, customer, "1000.00")
        reconcile_line(session, books.company_id, statement_lines[0].id, payment_id=payment.id)
        session.flush()

        import_statement(
            session,
            books.company_id,
            books.accounts["1110"],
            CsvSource(MAPPING),
            b"Date,Amount,Narrative,Ref\n2026-03-20,1000.00,Another receipt,TRX-9\n",
        )
        session.flush()
        later = unreconciled_lines(session, books.company_id)[-1]

        assert suggest_for_statement_line(session, books.company_id, later.id) == []
