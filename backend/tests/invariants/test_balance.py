"""Double-entry rules enforced by the database, proven with raw SQL only (R3, NFR1).

Nothing here goes through the posting service: if these pass, no bug or manual UPDATE
can leave the books unbalanced.
"""

from datetime import date

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.orm import Session

from app.shared.ids import uuid7
from tests.factories import Books, make_books
from tests.invariants.helpers import CHECK_VIOLATION, rejects

pytestmark = pytest.mark.db

ENTRY_DATE = date(2026, 3, 1)


@pytest.fixture
def books(session: Session) -> Books:
    return make_books(session)


def new_entry(connection: Connection, books: Books, *, currency: str = "SAR", journal="MISC"):
    entry_id = uuid7()
    connection.execute(
        text(
            "INSERT INTO journal_entry (id, company_id, journal_id, date, currency_code) "
            "VALUES (:id, :company, :journal, :date, :currency)"
        ),
        {
            "id": entry_id,
            "company": books.company_id,
            "journal": books.journals[journal],
            "date": ENTRY_DATE,
            "currency": currency,
        },
    )
    return entry_id


def add_line(
    connection: Connection,
    books: Books,
    entry_id,
    account: str,
    debit: str = "0",
    credit: str = "0",
    *,
    line_no: int = 1,
    currency: str = "SAR",
    amount_currency: str | None = None,
) -> None:
    if amount_currency is None:
        from decimal import Decimal

        amount_currency = str(Decimal(debit) - Decimal(credit))
    connection.execute(
        text(
            "INSERT INTO journal_entry_line (id, entry_id, company_id, line_no, account_id, "
            "debit, credit, currency_code, amount_currency) VALUES "
            "(:id, :entry, :company, :no, :account, :debit, :credit, :currency, :amount)"
        ),
        {
            "id": uuid7(),
            "entry": entry_id,
            "company": books.company_id,
            "no": line_no,
            "account": books.accounts[account],
            "debit": debit,
            "credit": credit,
            "currency": currency,
            "amount": amount_currency,
        },
    )


def post(connection: Connection, entry_id, number: str) -> None:
    connection.execute(
        text(
            "UPDATE journal_entry SET state = 'posted', number = :number, posted_at = now() "
            "WHERE id = :id"
        ),
        {"id": entry_id, "number": number},
    )


class TestBalanceAtCommit:
    def test_a_balanced_entry_commits(self, engine: Engine, books: Books) -> None:
        with engine.begin() as connection:
            entry_id = new_entry(connection, books)
            add_line(connection, books, entry_id, "expense", debit="100.00", line_no=1)
            add_line(connection, books, entry_id, "bank", credit="100.00", line_no=2)
            post(connection, entry_id, "MISC/2026/00100")

        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT state FROM journal_entry WHERE id = :id"), {"id": entry_id}
            ).scalar() == "posted"

    def test_debits_must_equal_credits(self, engine: Engine, books: Books) -> None:
        """R3.AC1 — the check fires at COMMIT, not at INSERT."""
        with rejects("ledger.unbalanced"), engine.begin() as connection:
            entry_id = new_entry(connection, books)
            add_line(connection, books, entry_id, "expense", debit="100.00", line_no=1)
            add_line(connection, books, entry_id, "bank", credit="99.00", line_no=2)
            post(connection, entry_id, "MISC/2026/00101")

    def test_single_currency_entries_must_also_balance_in_that_currency(
        self, engine: Engine, books: Books
    ) -> None:
        """R3.AC2 — company amounts balance, but the USD amounts do not."""
        with rejects("ledger.unbalanced_currency"), engine.begin() as connection:
            entry_id = new_entry(connection, books, currency="USD")
            add_line(
                connection,
                books,
                entry_id,
                "receivable",
                debit="375.00",
                line_no=1,
                currency="USD",
                amount_currency="100.00",
            )
            add_line(
                connection,
                books,
                entry_id,
                "revenue",
                credit="375.00",
                line_no=2,
                currency="USD",
                amount_currency="-99.00",
            )
            post(connection, entry_id, "MISC/2026/00102")

    def test_mixed_currency_entries_only_balance_in_company_currency(
        self, engine: Engine, books: Books
    ) -> None:
        """Two transaction currencies in one entry: only the SAR totals must match, which
        is what lets a future payment settle a foreign invoice."""
        with engine.begin() as connection:
            entry_id = new_entry(connection, books, currency="USD")
            add_line(
                connection,
                books,
                entry_id,
                "receivable",
                debit="375.00",
                line_no=1,
                currency="USD",
                amount_currency="100.00",
            )
            add_line(
                connection,
                books,
                entry_id,
                "bank",
                credit="375.00",
                line_no=2,
                currency="EUR",
                amount_currency="-92.00",
            )
            post(connection, entry_id, "MISC/2026/00103")

        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT count(*) FROM journal_entry_line WHERE entry_id = :e"),
                {"e": entry_id},
            ).scalar() == 2

    def test_a_posted_entry_needs_lines(self, engine: Engine, books: Books) -> None:
        with rejects("ledger.empty_entry"), engine.begin() as connection:
            entry_id = new_entry(connection, books)
            post(connection, entry_id, "MISC/2026/00104")

    def test_a_posted_entry_needs_a_non_zero_amount(self, engine: Engine, books: Books) -> None:
        with rejects("ledger.empty_entry"), engine.begin() as connection:
            entry_id = new_entry(connection, books)
            add_line(connection, books, entry_id, "expense", line_no=1)
            add_line(connection, books, entry_id, "bank", line_no=2)
            post(connection, entry_id, "MISC/2026/00105")

    def test_drafts_may_sit_unbalanced(self, engine: Engine, books: Books) -> None:
        """Documents are built line by line; only posting demands balance."""
        with engine.begin() as connection:
            entry_id = new_entry(connection, books)
            add_line(connection, books, entry_id, "expense", debit="100.00", line_no=1)

        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT state FROM journal_entry WHERE id = :id"), {"id": entry_id}
            ).scalar() == "draft"


class TestLineLevelRules:
    def test_negative_amounts_are_refused(self, engine: Engine, books: Books) -> None:
        with rejects(sqlstate=CHECK_VIOLATION), engine.begin() as connection:
            entry_id = new_entry(connection, books)
            add_line(connection, books, entry_id, "expense", debit="-100.00", line_no=1)

    def test_a_line_cannot_be_both_debit_and_credit(self, engine: Engine, books: Books) -> None:
        with rejects(sqlstate=CHECK_VIOLATION), engine.begin() as connection:
            entry_id = new_entry(connection, books)
            add_line(
                connection,
                books,
                entry_id,
                "expense",
                debit="100.00",
                credit="100.00",
                line_no=1,
                amount_currency="0",
            )

    def test_currency_amount_cannot_oppose_the_company_amount(
        self, engine: Engine, books: Books
    ) -> None:
        """R3.AC6 — a debit in company currency cannot be a credit in its own currency."""
        with rejects(sqlstate=CHECK_VIOLATION), engine.begin() as connection:
            entry_id = new_entry(connection, books, currency="USD")
            add_line(
                connection,
                books,
                entry_id,
                "receivable",
                debit="375.00",
                line_no=1,
                currency="USD",
                amount_currency="-100.00",
            )

    def test_company_currency_lines_must_agree_with_debit_minus_credit(
        self, engine: Engine, books: Books
    ) -> None:
        with rejects("ledger.base_amount_mismatch"), engine.begin() as connection:
            entry_id = new_entry(connection, books)
            add_line(
                connection,
                books,
                entry_id,
                "expense",
                debit="100.00",
                line_no=1,
                amount_currency="99.00",
            )

    def test_company_amounts_must_be_rounded_to_the_base_currency(
        self, engine: Engine, books: Books
    ) -> None:
        with rejects("ledger.unrounded"), engine.begin() as connection:
            entry_id = new_entry(connection, books)
            add_line(connection, books, entry_id, "expense", debit="100.001", line_no=1)

    def test_currency_amounts_must_be_rounded_to_their_own_currency(
        self, engine: Engine, books: Books
    ) -> None:
        """JPY has no minor unit, so 1.5 JPY cannot exist even though 1.50 SAR can."""
        with rejects("ledger.unrounded"), engine.begin() as connection:
            entry_id = new_entry(connection, books, currency="JPY")
            add_line(
                connection,
                books,
                entry_id,
                "receivable",
                debit="5.00",
                line_no=1,
                currency="JPY",
                amount_currency="1.5",
            )

    def test_three_decimal_currencies_are_allowed_their_precision(
        self, engine: Engine, books: Books
    ) -> None:
        with engine.begin() as connection:
            entry_id = new_entry(connection, books, currency="KWD")
            add_line(
                connection,
                books,
                entry_id,
                "receivable",
                debit="122.61",
                line_no=1,
                currency="KWD",
                amount_currency="10.005",
            )
            add_line(
                connection,
                books,
                entry_id,
                "revenue",
                credit="122.61",
                line_no=2,
                currency="KWD",
                amount_currency="-10.005",
            )
            post(connection, entry_id, "MISC/2026/00106")

        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT sum(amount_currency) FROM journal_entry_line WHERE entry_id = :e"),
                {"e": entry_id},
            ).scalar() == 0
