"""Drafts are editable, posted entries are not — proven with raw SQL (R1, R4)."""

from datetime import date

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.shared.ids import uuid7
from tests.factories import Books, insert_draft_entry, make_books, mark_posted
from tests.invariants.helpers import rejects

pytestmark = pytest.mark.db

BALANCED = [("expense", "100.00", "0"), ("bank", "0", "100.00")]


@pytest.fixture
def books(session: Session) -> Books:
    return make_books(session)


def draft(connection, books: Books):
    return insert_draft_entry(connection, books, BALANCED)


def posted(connection, books: Books, number: str = "MISC/2026/00001"):
    entry_id = insert_draft_entry(connection, books, BALANCED)
    mark_posted(connection, entry_id, number)
    return entry_id


class TestDraftsAreEditable:
    def test_header_can_change(self, engine: Engine, books: Books) -> None:
        with engine.begin() as connection:
            entry_id = draft(connection, books)
            connection.execute(
                text("UPDATE journal_entry SET ref = 'edited', date = :d WHERE id = :id"),
                {"id": entry_id, "d": date(2026, 3, 15)},
            )
        with engine.connect() as connection:
            row = connection.execute(
                text("SELECT ref, date FROM journal_entry WHERE id = :id"), {"id": entry_id}
            ).one()
        assert row == ("edited", date(2026, 3, 15))

    def test_lines_can_be_added_changed_and_removed(self, engine: Engine, books: Books) -> None:
        with engine.begin() as connection:
            entry_id = draft(connection, books)
            connection.execute(
                text(
                    "INSERT INTO journal_entry_line (id, entry_id, company_id, line_no, "
                    "account_id, debit, credit, currency_code, amount_currency) VALUES "
                    "(:id, :entry, :company, 3, :account, 0, 0.00, 'SAR', 0)"
                ),
                {
                    "id": uuid7(),
                    "entry": entry_id,
                    "company": books.company_id,
                    "account": books.accounts["revenue"],
                },
            )
            connection.execute(
                text("UPDATE journal_entry_line SET name = 'renamed' WHERE entry_id = :e"),
                {"e": entry_id},
            )
            connection.execute(
                text("DELETE FROM journal_entry_line WHERE entry_id = :e AND line_no = 3"),
                {"e": entry_id},
            )
        with engine.connect() as connection:
            count = connection.execute(
                text("SELECT count(*) FROM journal_entry_line WHERE entry_id = :e"),
                {"e": entry_id},
            ).scalar()
        assert count == 2

    def test_draft_can_be_deleted_with_its_lines(self, engine: Engine, books: Books) -> None:
        with engine.begin() as connection:
            entry_id = draft(connection, books)
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM journal_entry WHERE id = :id"), {"id": entry_id})
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT count(*) FROM journal_entry_line WHERE entry_id = :e"),
                    {"e": entry_id},
                ).scalar()
                == 0
            )


class TestPostedEntriesAreImmutable:
    def test_entries_cannot_be_inserted_already_posted(self, engine: Engine, books: Books) -> None:
        with rejects("ledger.insert_posted"), engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO journal_entry (id, company_id, journal_id, date, currency_code, "
                    "state, number, posted_at) VALUES "
                    "(:id, :company, :journal, :date, 'SAR', 'posted', 'X/2026/00001', now())"
                ),
                {
                    "id": uuid7(),
                    "company": books.company_id,
                    "journal": books.journals["MISC"],
                    "date": date(2026, 3, 1),
                },
            )

    def test_header_cannot_change(self, engine: Engine, books: Books) -> None:
        with engine.begin() as connection:
            entry_id = posted(connection, books, "MISC/2026/00010")
        with rejects("ledger.posted_immutable"), engine.begin() as connection:
            connection.execute(
                text("UPDATE journal_entry SET ref = 'tampered' WHERE id = :id"), {"id": entry_id}
            )

    def test_entry_cannot_be_deleted(self, engine: Engine, books: Books) -> None:
        with engine.begin() as connection:
            entry_id = posted(connection, books, "MISC/2026/00011")
        with rejects("ledger.posted_immutable"), engine.begin() as connection:
            connection.execute(text("DELETE FROM journal_entry WHERE id = :id"), {"id": entry_id})

    def test_cannot_go_back_to_draft(self, engine: Engine, books: Books) -> None:
        with engine.begin() as connection:
            entry_id = posted(connection, books, "MISC/2026/00012")
        with rejects("ledger.posted_immutable"), engine.begin() as connection:
            connection.execute(
                text("UPDATE journal_entry SET state = 'draft' WHERE id = :id"), {"id": entry_id}
            )

    def test_lines_cannot_be_added(self, engine: Engine, books: Books) -> None:
        with engine.begin() as connection:
            entry_id = posted(connection, books, "MISC/2026/00013")
        with rejects("ledger.posted_immutable"), engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO journal_entry_line (id, entry_id, company_id, line_no, "
                    "account_id, debit, credit, currency_code, amount_currency) VALUES "
                    "(:id, :entry, :company, 9, :account, 1.00, 0, 'SAR', 1.00)"
                ),
                {
                    "id": uuid7(),
                    "entry": entry_id,
                    "company": books.company_id,
                    "account": books.accounts["expense"],
                },
            )

    def test_lines_cannot_be_changed(self, engine: Engine, books: Books) -> None:
        with engine.begin() as connection:
            entry_id = posted(connection, books, "MISC/2026/00014")
        with rejects("ledger.posted_immutable"), engine.begin() as connection:
            connection.execute(
                text("UPDATE journal_entry_line SET debit = 1.00 WHERE entry_id = :e"),
                {"e": entry_id},
            )

    def test_lines_cannot_be_deleted(self, engine: Engine, books: Books) -> None:
        with engine.begin() as connection:
            entry_id = posted(connection, books, "MISC/2026/00015")
        with rejects("ledger.posted_immutable"), engine.begin() as connection:
            connection.execute(
                text("DELETE FROM journal_entry_line WHERE entry_id = :e"), {"e": entry_id}
            )

    def test_posting_is_allowed_exactly_once(self, engine: Engine, books: Books) -> None:
        """The draft to posted step itself works; everything after it is frozen."""
        with engine.begin() as connection:
            entry_id = posted(connection, books, "MISC/2026/00016")
        with engine.connect() as connection:
            state, number, posted_at = connection.execute(
                text("SELECT state, number, posted_at FROM journal_entry WHERE id = :id"),
                {"id": entry_id},
            ).one()
        assert (state, number) == ("posted", "MISC/2026/00016")
        assert posted_at is not None
