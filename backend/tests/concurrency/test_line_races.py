"""A line write racing a posting, in both orders (R11.AC3, R11.AC4).

Without the ``FOR SHARE`` lock the line trigger takes on its entry, one transaction could
add a line to an entry another transaction is posting — and the posted entry would end up
unbalanced. These two tests are the proof that cannot happen.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.shared.errors import DomainError, domain_error_from_db
from tests.factories import Books, insert_draft_entry, insert_line, make_books, mark_posted

pytestmark = pytest.mark.db

BALANCED = [("expense", "100.00", "0"), ("bank", "0", "100.00")]
LOCK_TIMEOUT = "SET LOCAL lock_timeout = '30s'"  # inside the transaction
HANDOVER = 0.75  # seconds the first transaction stays open while the second blocks


@pytest.fixture
def draft_entry(engine: Engine, session: Session) -> tuple[Books, object]:
    books = make_books(session)
    with engine.begin() as connection:
        entry_id = insert_draft_entry(connection, books, BALANCED)
    return books, entry_id


def state_of(engine: Engine, entry_id) -> str:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT state FROM journal_entry WHERE id = :id"), {"id": entry_id}
        ).scalar_one()


def line_count(engine: Engine, entry_id) -> int:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT count(*) FROM journal_entry_line WHERE entry_id = :e"), {"e": entry_id}
        ).scalar_one()


def test_a_line_cannot_slip_into_an_entry_being_posted(
    engine: Engine, draft_entry: tuple[Books, object]
) -> None:
    """R11.AC3 — the insert waits for the posting, then is refused as immutable."""
    books, entry_id = draft_entry
    posting_open = Event()
    insert_attempted = Event()
    result: dict[str, object] = {}

    def poster() -> None:
        with engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(text(LOCK_TIMEOUT))
            mark_posted(connection, entry_id, "MISC/2026/00600")
            posting_open.set()
            insert_attempted.wait(timeout=10)
            time.sleep(HANDOVER)  # the inserter is blocked on the entry row meanwhile
            transaction.commit()

    def inserter() -> None:
        assert posting_open.wait(timeout=10)
        with engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(text(LOCK_TIMEOUT))
            insert_attempted.set()
            started = time.monotonic()
            try:
                insert_line(connection, books, entry_id, "revenue", line_no=3)
                transaction.commit()
                result["outcome"] = "committed"
            except DBAPIError as exc:
                transaction.rollback()
                result["outcome"] = domain_error_from_db(exc)
            result["waited"] = time.monotonic() - started

    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in [pool.submit(poster), pool.submit(inserter)]:
            future.result(timeout=90)

    error = result["outcome"]
    assert isinstance(error, DomainError), f"line was accepted into a posted entry: {error}"
    assert error.code == "ledger.posted_immutable"
    waited = float(result["waited"])
    assert waited >= HANDOVER * 0.5, f"the insert should have waited, took {waited:.2f}s"

    assert state_of(engine, entry_id) == "posted"
    assert line_count(engine, entry_id) == 2


def test_posting_sees_a_line_committed_by_another_transaction(
    engine: Engine, draft_entry: tuple[Books, object]
) -> None:
    """R11.AC4 — the other order: a line is already pending, so the posting waits and then
    fails the balance check at COMMIT instead of committing a broken entry."""
    books, entry_id = draft_entry
    line_pending = Event()
    posting_attempted = Event()
    result: dict[str, object] = {}

    def inserter() -> None:
        with engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(text(LOCK_TIMEOUT))
            insert_line(connection, books, entry_id, "expense", debit="5.00", line_no=3)
            line_pending.set()
            posting_attempted.wait(timeout=10)
            time.sleep(HANDOVER)  # the poster is blocked on the entry row meanwhile
            transaction.commit()

    def poster() -> None:
        assert line_pending.wait(timeout=10)
        with engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(text(LOCK_TIMEOUT))
            posting_attempted.set()
            started = time.monotonic()
            try:
                mark_posted(connection, entry_id, "MISC/2026/00601")
                transaction.commit()
                result["outcome"] = "committed"
            except DBAPIError as exc:
                transaction.rollback()
                result["outcome"] = domain_error_from_db(exc)
            result["waited"] = time.monotonic() - started

    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in [pool.submit(inserter), pool.submit(poster)]:
            future.result(timeout=90)

    error = result["outcome"]
    assert isinstance(error, DomainError), f"an unbalanced entry was posted: {error}"
    assert error.code == "ledger.unbalanced"
    waited = float(result["waited"])
    assert waited >= HANDOVER * 0.5, f"the posting should have waited, took {waited:.2f}s"

    assert state_of(engine, entry_id) == "draft"
    assert line_count(engine, entry_id) == 3  # the extra line stayed on the draft


def test_two_transactions_may_add_lines_to_the_same_draft(
    engine: Engine, draft_entry: tuple[Books, object]
) -> None:
    """Shared locks do not block each other, so building drafts stays concurrent."""
    books, entry_id = draft_entry
    both_inserted = Event()

    def inserter(line_no: int) -> None:
        with engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(text(LOCK_TIMEOUT))
            insert_line(connection, books, entry_id, "revenue", line_no=line_no)
            if line_no == 4:
                both_inserted.set()
            else:
                assert both_inserted.wait(timeout=10), "the second insert was blocked"
            transaction.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in [pool.submit(inserter, 3), pool.submit(inserter, 4)]:
            future.result(timeout=60)

    assert line_count(engine, entry_id) == 4
    assert state_of(engine, entry_id) == "draft"
