"""Company isolation, account safety, lock dates and uniqueness, all via raw SQL
(R6.AC5, R7.AC9, R7.AC10, R8.AC1, R9, R10, R12.AC1).
"""

from datetime import date

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.shared.ids import uuid7
from tests.factories import Books, insert_draft_entry, make_books, mark_posted
from tests.invariants.helpers import (
    CHECK_VIOLATION,
    FOREIGN_KEY_VIOLATION,
    UNIQUE_VIOLATION,
    rejects,
)

pytestmark = pytest.mark.db

BALANCED = [("expense", "100.00", "0"), ("bank", "0", "100.00")]


@pytest.fixture
def books(session: Session) -> Books:
    return make_books(session)


class TestCompanyIsolation:
    def test_a_line_cannot_use_another_companys_account(
        self, engine: Engine, books: Books, session: Session
    ) -> None:
        theirs = make_books(session)
        with rejects(sqlstate=FOREIGN_KEY_VIOLATION), engine.begin() as connection:
            entry_id = insert_draft_entry(connection, books, [("expense", "100.00", "0")])
            connection.execute(
                text(
                    "INSERT INTO journal_entry_line (id, entry_id, company_id, line_no, "
                    "account_id, debit, credit, currency_code, amount_currency) VALUES "
                    "(:id, :entry, :company, 2, :account, 0, 100.00, 'SAR', -100.00)"
                ),
                {
                    "id": uuid7(),
                    "entry": entry_id,
                    "company": books.company_id,
                    "account": theirs.accounts["bank"],  # different company
                },
            )

    def test_an_entry_cannot_use_another_companys_journal(
        self, engine: Engine, books: Books, session: Session
    ) -> None:
        theirs = make_books(session)
        with rejects(sqlstate=FOREIGN_KEY_VIOLATION), engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO journal_entry (id, company_id, journal_id, date, currency_code) "
                    "VALUES (:id, :company, :journal, :date, 'SAR')"
                ),
                {
                    "id": uuid7(),
                    "company": books.company_id,
                    "journal": theirs.journals["MISC"],
                    "date": date(2026, 3, 1),
                },
            )

    def test_a_reversal_cannot_cross_companies(
        self, engine: Engine, books: Books, session: Session
    ) -> None:
        theirs = make_books(session)
        with engine.begin() as connection:
            their_entry = insert_draft_entry(connection, theirs, BALANCED)
            mark_posted(connection, their_entry, "MISC/2026/00200")

        with rejects(sqlstate=FOREIGN_KEY_VIOLATION), engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO journal_entry (id, company_id, journal_id, date, currency_code, "
                    "reversed_entry_id) VALUES (:id, :company, :journal, :date, 'SAR', :reversed)"
                ),
                {
                    "id": uuid7(),
                    "company": books.company_id,
                    "journal": books.journals["MISC"],
                    "date": date(2026, 3, 1),
                    "reversed": their_entry,
                },
            )

    def test_base_currency_is_frozen_once_entries_exist(
        self, engine: Engine, books: Books
    ) -> None:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE company SET base_currency = 'USD' WHERE id = :id"),
                {"id": books.company_id},
            )  # allowed: no entries yet

        with engine.begin() as connection:
            connection.execute(
                text("UPDATE company SET base_currency = 'SAR' WHERE id = :id"),
                {"id": books.company_id},
            )
            insert_draft_entry(connection, books, BALANCED)

        with rejects("ledger.base_currency_locked"), engine.begin() as connection:
            connection.execute(
                text("UPDATE company SET base_currency = 'USD' WHERE id = :id"),
                {"id": books.company_id},
            )


class TestAccountSafety:
    def test_group_accounts_cannot_hold_lines(self, engine: Engine, books: Books) -> None:
        with rejects("ledger.group_account"), engine.begin() as connection:
            insert_draft_entry(
                connection, books, [("current_assets", "100.00", "0"), ("bank", "0", "100.00")]
            )

    def test_an_account_with_lines_cannot_become_a_group(
        self, engine: Engine, books: Books
    ) -> None:
        with engine.begin() as connection:
            insert_draft_entry(connection, books, BALANCED)

        with rejects("ledger.account_has_lines"), engine.begin() as connection:
            connection.execute(
                text("UPDATE account SET is_group = true WHERE id = :id"),
                {"id": books.accounts["bank"]},
            )

    def test_an_unused_account_can_become_a_group(self, engine: Engine, books: Books) -> None:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE account SET is_group = true WHERE id = :id"),
                {"id": books.accounts["vat_input"]},
            )

    @pytest.mark.parametrize(
        ("type_", "subtype"),
        [
            ("asset", "payable"),
            ("liability", "receivable"),
            ("income", "expense"),
            ("equity", "bank_cash"),
            ("expense", "income"),
        ],
    )
    def test_subtype_must_belong_to_the_type(
        self, engine: Engine, books: Books, type_: str, subtype: str
    ) -> None:
        with rejects(sqlstate=CHECK_VIOLATION), engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO account (id, company_id, code, name, type, subtype) "
                    "VALUES (:id, :company, :code, 'Bad account', :type, :subtype)"
                ),
                {
                    "id": uuid7(),
                    "company": books.company_id,
                    "code": f"9{abs(hash((type_, subtype))) % 1000:03d}",
                    "type": type_,
                    "subtype": subtype,
                },
            )

    @pytest.mark.parametrize("subtype", ["receivable", "payable"])
    def test_receivable_and_payable_accounts_must_be_reconcilable(
        self, engine: Engine, books: Books, subtype: str
    ) -> None:
        with rejects(sqlstate=CHECK_VIOLATION), engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO account (id, company_id, code, name, type, subtype, "
                    "is_reconcilable) VALUES (:id, :company, :code, 'Open items', :type, "
                    ":subtype, false)"
                ),
                {
                    "id": uuid7(),
                    "company": books.company_id,
                    "code": f"95{len(subtype)}",
                    "type": "asset" if subtype == "receivable" else "liability",
                    "subtype": subtype,
                },
            )


class TestLockDates:
    def test_posting_on_or_before_the_lock_date_is_refused(
        self, engine: Engine, session: Session
    ) -> None:
        books = make_books(session, lock_date=date(2026, 3, 31))

        for entry_date in (date(2026, 3, 31), date(2026, 1, 15)):
            with rejects("ledger.period_locked"), engine.begin() as connection:
                entry_id = insert_draft_entry(connection, books, BALANCED, on=entry_date)
                mark_posted(connection, entry_id, f"MISC/2026/{entry_date.month:05d}")

    def test_posting_after_the_lock_date_is_allowed(
        self, engine: Engine, session: Session
    ) -> None:
        books = make_books(session, lock_date=date(2026, 3, 31))
        with engine.begin() as connection:
            entry_id = insert_draft_entry(connection, books, BALANCED, on=date(2026, 4, 1))
            mark_posted(connection, entry_id, "MISC/2026/00300")

        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT state FROM journal_entry WHERE id = :id"), {"id": entry_id}
            ).scalar() == "posted"

    def test_a_draft_may_sit_in_a_locked_period(self, engine: Engine, session: Session) -> None:
        """Only posting is blocked, so a document can still be prepared and re-dated."""
        books = make_books(session, lock_date=date(2026, 3, 31))
        with engine.begin() as connection:
            insert_draft_entry(connection, books, BALANCED, on=date(2026, 2, 1))


class TestUniqueness:
    def test_numbers_are_unique_within_a_journal(self, engine: Engine, books: Books) -> None:
        with engine.begin() as connection:
            first = insert_draft_entry(connection, books, BALANCED)
            mark_posted(connection, first, "MISC/2026/00400")

        with rejects(sqlstate=UNIQUE_VIOLATION), engine.begin() as connection:
            second = insert_draft_entry(connection, books, BALANCED)
            mark_posted(connection, second, "MISC/2026/00400")

    def test_one_entry_per_source_document(self, engine: Engine, books: Books) -> None:
        invoice_id = uuid7()
        with engine.begin() as connection:
            entry_id = insert_draft_entry(connection, books, BALANCED)
            connection.execute(
                text(
                    "UPDATE journal_entry SET source_type = 'invoice', source_id = :source "
                    "WHERE id = :id"
                ),
                {"id": entry_id, "source": invoice_id},
            )

        with rejects(sqlstate=UNIQUE_VIOLATION), engine.begin() as connection:
            second = insert_draft_entry(connection, books, BALANCED)
            connection.execute(
                text(
                    "UPDATE journal_entry SET source_type = 'invoice', source_id = :source "
                    "WHERE id = :id"
                ),
                {"id": second, "source": invoice_id},
            )

    def test_one_reversal_per_entry(self, engine: Engine, books: Books) -> None:
        with engine.begin() as connection:
            original = insert_draft_entry(connection, books, BALANCED)
            mark_posted(connection, original, "MISC/2026/00401")

        def write_reversal(number: str) -> None:
            with engine.begin() as connection:
                reversal = insert_draft_entry(
                    connection, books, [("bank", "100.00", "0"), ("expense", "0", "100.00")]
                )
                connection.execute(
                    text("UPDATE journal_entry SET reversed_entry_id = :o WHERE id = :id"),
                    {"id": reversal, "o": original},
                )
                mark_posted(connection, reversal, number)

        write_reversal("MISC/2026/00402")
        with rejects(sqlstate=UNIQUE_VIOLATION):
            write_reversal("MISC/2026/00403")

    def test_an_entry_cannot_reverse_itself(self, engine: Engine, books: Books) -> None:
        with rejects(sqlstate=CHECK_VIOLATION), engine.begin() as connection:
            entry_id = insert_draft_entry(connection, books, BALANCED)
            connection.execute(
                text("UPDATE journal_entry SET reversed_entry_id = id WHERE id = :id"),
                {"id": entry_id},
            )

    def test_only_posted_entries_can_be_reversed(self, engine: Engine, books: Books) -> None:
        with engine.begin() as connection:
            draft_id = insert_draft_entry(connection, books, BALANCED)

        with rejects("ledger.reverse_unposted"), engine.begin() as connection:
            reversal = insert_draft_entry(
                connection, books, [("bank", "100.00", "0"), ("expense", "0", "100.00")]
            )
            connection.execute(
                text("UPDATE journal_entry SET reversed_entry_id = :o WHERE id = :id"),
                {"id": reversal, "o": draft_id},
            )
            mark_posted(connection, reversal, "MISC/2026/00404")


class TestExchangeRates:
    @pytest.mark.parametrize("rate", ["0", "-3.75"])
    def test_rates_must_be_positive(self, engine: Engine, books: Books, rate: str) -> None:
        with rejects(sqlstate=CHECK_VIOLATION), engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO exchange_rate (id, company_id, currency_code, rate_date, rate) "
                    "VALUES (:id, :company, 'USD', :date, :rate)"
                ),
                {
                    "id": uuid7(),
                    "company": books.company_id,
                    "date": date(2026, 3, 1),
                    "rate": rate,
                },
            )

    def test_one_rate_per_currency_and_day(self, engine: Engine, books: Books) -> None:
        def write_rate(rate: str) -> None:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO exchange_rate (id, company_id, currency_code, rate_date, "
                        "rate) VALUES (:id, :company, 'USD', :date, :rate)"
                    ),
                    {
                        "id": uuid7(),
                        "company": books.company_id,
                        "date": date(2026, 3, 1),
                        "rate": rate,
                    },
                )

        write_rate("3.7500")
        with rejects(sqlstate=UNIQUE_VIOLATION):
            write_rate("3.7600")
