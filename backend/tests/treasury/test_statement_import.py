"""Importing a bank statement (R7.AC4, R7.AC6, R7.AC7, R7.AC8)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ledger.api import JournalEntry
from app.shared.errors import DomainError
from app.treasury.models import BankStatementLine
from app.treasury.reconciling import (
    get_statement,
    import_statement,
    list_statements,
    unreconciled_lines,
)
from app.treasury.statements import CsvSource, Mt940Source
from tests.factories import TreasuryBooks

pytestmark = pytest.mark.db

MAPPING = {
    "date": "Date",
    "amount": "Amount",
    "description": "Narrative",
    "counterparty": "Payee",
    "reference": "Ref",
}

MARCH = b"""Date,Amount,Narrative,Payee,Ref
2026-03-01,1150.00,Invoice INV/2026/00001,Al Noor Est,TRX-1
2026-03-02,-500.00,Rent,Jeddah Properties,TRX-2
"""

MARCH_AND_APRIL = MARCH + b"2026-04-01,2000.00,Invoice INV/2026/00002,Al Noor Est,TRX-3\n"


def load(session: Session, books: TreasuryBooks, payload: bytes = MARCH, **kwargs):
    result = import_statement(
        session,
        books.company_id,
        books.accounts["1110"],
        CsvSource(MAPPING),
        payload,
        **kwargs,
    )
    session.commit()
    return result


class TestImporting:
    def test_every_row_becomes_a_line(self, session: Session, books: TreasuryBooks) -> None:
        """R7.AC6"""
        result = load(session, books, file_name="march.csv")

        assert result.created == 2
        assert result.duplicates == 0
        assert result.rejected == []

    def test_the_statement_records_where_it_came_from(
        self, session: Session, books: TreasuryBooks
    ) -> None:
        result = load(session, books, file_name="march.csv")

        statement = get_statement(session, books.company_id, result.statement_id)
        assert statement.file_name == "march.csv"
        assert statement.source_format == "csv"
        assert statement.bank_account_id == books.accounts["1110"]

    def test_the_lines_keep_what_the_bank_said(
        self, session: Session, books: TreasuryBooks
    ) -> None:
        """R7.AC3"""
        result = load(session, books)

        statement = get_statement(session, books.company_id, result.statement_id)
        first = statement.lines[0]
        assert first.date == date(2026, 3, 1)
        assert first.amount == Decimal("1150.00")
        assert first.counterparty == "Al Noor Est"
        assert first.bank_reference == "TRX-1"

    def test_nothing_reaches_the_ledger(self, session: Session, books: TreasuryBooks) -> None:
        """R7.AC7 — an imported line is the bank's claim, not an entry."""
        result = load(session, books)

        statement = get_statement(session, books.company_id, result.statement_id)
        assert [line.journal_entry_id for line in statement.lines] == [None, None]
        entries = session.execute(
            select(JournalEntry).where(JournalEntry.company_id == books.company_id)
        ).scalars()
        assert list(entries) == []

    def test_an_mt940_file_imports_the_same_way(
        self, session: Session, books: TreasuryBooks
    ) -> None:
        payload = b""":25:SA03
:60F:C260301SAR12500,00
:61:2603010301C1150,00NTRFINV//TRX-1
:86:Receipt
:62F:C260301SAR13650,00
"""
        result = import_statement(
            session,
            books.company_id,
            books.accounts["1110"],
            Mt940Source(),
            payload,
            file_name="march.sta",
        )
        session.commit()

        statement = get_statement(session, books.company_id, result.statement_id)
        assert result.created == 1
        assert statement.source_format == "mt940"
        assert statement.opening_balance == Decimal("12500.00")

    def test_statements_are_listed_newest_first(
        self, session: Session, books: TreasuryBooks
    ) -> None:
        load(session, books, file_name="first.csv")
        load(session, books, MARCH_AND_APRIL, file_name="second.csv")

        names = [statement.file_name for statement in list_statements(session, books.company_id)]
        assert names == ["second.csv", "first.csv"]


class TestDuplicates:
    def test_the_same_file_twice_creates_nothing_the_second_time(
        self, session: Session, books: TreasuryBooks
    ) -> None:
        """R7.AC4"""
        load(session, books)
        again = load(session, books)

        assert again.created == 0
        assert again.duplicates == 2

    def test_an_overlapping_file_imports_only_what_is_new(
        self, session: Session, books: TreasuryBooks
    ) -> None:
        """R7.AC4 — the everyday case: last month's statement overlaps this month's."""
        load(session, books)
        overlapping = load(session, books, MARCH_AND_APRIL)

        assert overlapping.created == 1
        assert overlapping.duplicates == 2

    def test_the_same_rows_on_another_account_are_not_duplicates(
        self, session: Session, books: TreasuryBooks
    ) -> None:
        load(session, books)
        other = import_statement(
            session,
            books.company_id,
            books.accounts["1110"],
            CsvSource(MAPPING),
            MARCH,
        )
        session.commit()
        assert other.duplicates == 2

    def test_two_genuinely_identical_payments_both_import(
        self, session: Session, books: TreasuryBooks
    ) -> None:
        """R7.AC4 — two identical payments on one day are two transactions.

        They are told apart by being the first and second occurrence of that row, so a
        re-import of the same file still brings nothing new.
        """
        payload = b"Date,Amount,Narrative\n2026-03-01,500.00,Deposit\n2026-03-01,500.00,Deposit\n"
        result = import_statement(
            session,
            books.company_id,
            books.accounts["1110"],
            CsvSource({"date": "Date", "amount": "Amount", "description": "Narrative"}),
            payload,
        )
        session.commit()

        statement = get_statement(session, books.company_id, result.statement_id)
        assert result.created == 2
        assert [line.occurrence for line in statement.lines] == [1, 2]

        again = import_statement(
            session,
            books.company_id,
            books.accounts["1110"],
            CsvSource({"date": "Date", "amount": "Amount", "description": "Narrative"}),
            payload,
        )
        session.commit()
        assert (again.created, again.duplicates) == (0, 2)


class TestBadFiles:
    def test_a_file_that_cannot_be_read_imports_nothing(
        self, session: Session, books: TreasuryBooks
    ) -> None:
        """R7.AC5"""
        with pytest.raises(DomainError) as caught:
            import_statement(
                session,
                books.company_id,
                books.accounts["1110"],
                CsvSource(MAPPING),
                b"",
            )
        session.rollback()

        assert caught.value.code == "payments.unreadable_file"
        ours = session.execute(
            select(BankStatementLine).where(BankStatementLine.company_id == books.company_id)
        ).scalars()
        assert list(ours) == []

    def test_unreadable_rows_are_reported_and_the_rest_imported(
        self, session: Session, books: TreasuryBooks
    ) -> None:
        """R7.AC6"""
        result = load(session, books, MARCH + b"whenever,nonsense,,,\n")

        assert result.created == 2
        assert len(result.rejected) == 1

    def test_an_account_that_is_not_a_bank_account_is_refused(
        self, session: Session, books: TreasuryBooks
    ) -> None:
        with pytest.raises(DomainError) as caught:
            import_statement(
                session,
                books.company_id,
                books.accounts["1200"],
                CsvSource(MAPPING),
                MARCH,
            )
        assert caught.value.code == "payments.not_a_bank_account"


class TestWhatIsStillUnreconciled:
    def test_unreconciled_lines_come_back_oldest_first(
        self, session: Session, books: TreasuryBooks
    ) -> None:
        """R7.AC8"""
        load(session, books, MARCH_AND_APRIL)

        dates = [line.date for line in unreconciled_lines(session, books.company_id)]
        assert dates == sorted(dates)
        assert len(dates) == 3

    def test_they_can_be_narrowed_to_one_bank_account(
        self, session: Session, books: TreasuryBooks
    ) -> None:
        load(session, books)

        found = unreconciled_lines(
            session, books.company_id, bank_account_id=books.accounts["1110"]
        )
        assert len(found) == 2
