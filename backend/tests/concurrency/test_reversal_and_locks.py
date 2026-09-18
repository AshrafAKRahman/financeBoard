"""Two writers reversing one entry, and a posting racing a lock-date change
(R11.AC5, R8.AC2).
"""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier, Event

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.ledger.api import PostingLine, PostingRequest, post, reverse
from app.shared.errors import DomainError, domain_error_from_db
from tests.factories import Books, make_books

pytestmark = pytest.mark.db

ENTRY_DATE = date(2026, 3, 1)
LOCK_TIMEOUT = "SET LOCAL lock_timeout = '30s'"
HANDOVER = 0.75


def entry_request(books: Books, on: date = ENTRY_DATE) -> PostingRequest:
    return PostingRequest(
        company_id=books.company_id,
        journal_id=books.journals["MISC"],
        date=on,
        currency_code="SAR",
        lines=(
            PostingLine(books.accounts["expense"], debit=Decimal("100.00")),
            PostingLine(books.accounts["bank"], credit=Decimal("100.00")),
        ),
    )


def test_only_one_of_two_concurrent_reversals_commits(engine: Engine, session: Session) -> None:
    """R11.AC5 — the loser is told the entry was already reversed."""
    books = make_books(session)
    original = post(session, entry_request(books))
    session.commit()

    barrier = Barrier(2)
    outcomes: list[object] = []

    def reverser(_: int) -> None:
        barrier.wait()
        with Session(engine) as own:
            try:
                reversal = reverse(own, books.company_id, original.id)
                own.commit()
                outcomes.append(reversal.number)
            except DomainError as error:
                own.rollback()
                outcomes.append(error)
            except DBAPIError as error:
                own.rollback()
                outcomes.append(domain_error_from_db(error) or error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in [pool.submit(reverser, 0), pool.submit(reverser, 1)]:
            future.result(timeout=90)

    committed = [outcome for outcome in outcomes if isinstance(outcome, str)]
    refused = [outcome for outcome in outcomes if isinstance(outcome, DomainError)]
    assert len(committed) == 1, f"expected one reversal, got {outcomes}"
    assert len(refused) == 1 and refused[0].code == "ledger.already_reversed"

    with engine.connect() as connection:
        reversals = connection.execute(
            text("SELECT count(*) FROM journal_entry WHERE reversed_entry_id = :id"),
            {"id": original.id},
        ).scalar_one()
    assert reversals == 1


def test_reversals_of_different_entries_run_in_parallel(engine: Engine, session: Session) -> None:
    books = make_books(session)
    originals = [post(session, entry_request(books)) for _ in range(4)]
    session.commit()

    barrier = Barrier(len(originals))

    def reverser(entry_id) -> str:
        barrier.wait()
        with Session(engine) as own:
            reversal = reverse(own, books.company_id, entry_id)
            own.commit()
            return reversal.number

    with ThreadPoolExecutor(max_workers=len(originals)) as pool:
        numbers = list(pool.map(reverser, [entry.id for entry in originals]))

    assert len(set(numbers)) == len(originals)


def test_posting_waits_for_a_lock_date_change_then_is_refused(
    engine: Engine, session: Session
) -> None:
    """R8.AC2 — a period being closed cannot be overtaken by an in-flight posting."""
    books = make_books(session)
    lock_open = Event()
    posting_attempted = Event()
    result: dict[str, object] = {}

    def closer() -> None:
        with engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(text(LOCK_TIMEOUT))
            connection.execute(
                text("UPDATE company SET lock_date = :d WHERE id = :id"),
                {"d": date(2026, 3, 31), "id": books.company_id},
            )
            lock_open.set()
            posting_attempted.wait(timeout=10)
            time.sleep(HANDOVER)  # the posting is blocked on the company row meanwhile
            transaction.commit()

    def poster() -> None:
        assert lock_open.wait(timeout=10)
        with Session(engine) as own:
            own.execute(text(LOCK_TIMEOUT))
            posting_attempted.set()
            started = time.monotonic()
            try:
                post(own, entry_request(books))
                own.commit()
                result["outcome"] = "committed"
            except (DomainError, DBAPIError) as error:
                own.rollback()
                result["outcome"] = (
                    error if isinstance(error, DomainError) else domain_error_from_db(error)
                )
            result["waited"] = time.monotonic() - started

    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in [pool.submit(closer), pool.submit(poster)]:
            future.result(timeout=90)

    error = result["outcome"]
    assert isinstance(error, DomainError), f"posted into a period being locked: {error}"
    assert error.code == "ledger.period_locked"
    waited = float(result["waited"])
    assert waited >= HANDOVER * 0.5, f"the posting should have waited, took {waited:.2f}s"

    with engine.connect() as connection:
        posted = connection.execute(
            text("SELECT count(*) FROM journal_entry WHERE company_id = :c AND state = 'posted'"),
            {"c": books.company_id},
        ).scalar_one()
    assert posted == 0


def test_a_lock_date_change_waits_for_an_in_flight_posting(
    engine: Engine, session: Session
) -> None:
    """The other order: the posting finishes, then the period closes."""
    books = make_books(session)
    posting_open = Event()
    close_attempted = Event()
    result: dict[str, object] = {}

    def poster() -> None:
        with Session(engine) as own:
            own.execute(text(LOCK_TIMEOUT))
            post(own, entry_request(books))
            posting_open.set()
            close_attempted.wait(timeout=10)
            time.sleep(HANDOVER)  # the lock-date change is blocked meanwhile
            own.commit()

    def closer() -> None:
        assert posting_open.wait(timeout=10)
        with engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(text(LOCK_TIMEOUT))
            close_attempted.set()
            started = time.monotonic()
            connection.execute(
                text("UPDATE company SET lock_date = :d WHERE id = :id"),
                {"d": date(2026, 3, 31), "id": books.company_id},
            )
            transaction.commit()
            result["waited"] = time.monotonic() - started

    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in [pool.submit(poster), pool.submit(closer)]:
            future.result(timeout=90)

    waited = float(result["waited"])
    assert waited >= HANDOVER * 0.5, f"the lock-date change should have waited, took {waited:.2f}s"

    with engine.connect() as connection:
        posted, lock_date = connection.execute(
            text(
                """
                SELECT (SELECT count(*) FROM journal_entry
                        WHERE company_id = :c AND state = 'posted'),
                       (SELECT lock_date FROM company WHERE id = :c)
                """
            ),
            {"c": books.company_id},
        ).one()
    assert posted == 1 and lock_date == date(2026, 3, 31)
