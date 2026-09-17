"""Many writers posting at once: numbering stays gapless, journals stay independent,
and a failed posting leaves no hole (R11.AC1, R11.AC2, R11.AC6).

Each thread uses its own connection, as separate API requests or job workers would.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.ledger.api import PostingLine, PostingRequest, post
from app.shared.errors import DomainError
from tests.factories import Books, make_books

pytestmark = pytest.mark.db

ENTRY_DATE = date(2026, 3, 1)
THREADS = 8
PER_THREAD = 5


def request(books: Books, journal: str, amount: str = "100.00") -> PostingRequest:
    return PostingRequest(
        company_id=books.company_id,
        journal_id=books.journals[journal],
        date=ENTRY_DATE,
        currency_code="SAR",
        lines=(
            PostingLine(books.accounts["expense"], debit=Decimal(amount)),
            PostingLine(books.accounts["bank"], credit=Decimal(amount)),
        ),
    )


def numbers(engine: Engine, books: Books, journal_code: str) -> list[int]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT number FROM journal_entry WHERE company_id = :c AND state = 'posted' "
                "AND number LIKE :prefix ORDER BY number"
            ),
            {"c": books.company_id, "prefix": f"{journal_code}/%"},
        ).scalars()
        return sorted(int(number.rsplit("/", 1)[1]) for number in rows)


def test_concurrent_posting_to_one_journal_is_gapless(engine: Engine, session: Session) -> None:
    books = make_books(session)
    barrier = Barrier(THREADS)

    def worker(_: int) -> int:
        barrier.wait()
        posted = 0
        for _ in range(PER_THREAD):
            with Session(engine) as own:
                post(own, request(books, "MISC"))
                own.commit()
                posted += 1
        return posted

    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        assert sum(pool.map(worker, range(THREADS))) == THREADS * PER_THREAD

    assert numbers(engine, books, "MISC") == list(range(1, THREADS * PER_THREAD + 1))


def test_concurrent_posting_to_different_journals_does_not_wait(
    engine: Engine, session: Session
) -> None:
    """R11.AC2 — the counter lock is per journal and fiscal year, so different journals
    post in parallel. Each journal's own numbering still starts at 1."""
    books = make_books(session)
    journals = ["MISC", "INV", "BNK"]
    barrier = Barrier(len(journals))

    def worker(journal: str) -> None:
        barrier.wait()
        for _ in range(4):
            with Session(engine) as own:
                post(own, request(books, journal))
                own.commit()

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=len(journals)) as pool:
        list(pool.map(worker, journals))
    elapsed = time.monotonic() - started

    for journal in journals:
        assert numbers(engine, books, journal) == [1, 2, 3, 4]
    assert elapsed < 60, "parallel journals should not serialize into a slow run"


def test_a_failed_posting_leaves_no_gap(engine: Engine, session: Session) -> None:
    """R11.AC6 — rolled-back numbers come back, even while others keep posting."""
    books = make_books(session)
    barrier = Barrier(4)

    def good(_: int) -> None:
        barrier.wait()
        for _ in range(3):
            with Session(engine) as own:
                post(own, request(books, "MISC"))
                own.commit()

    def bad(_: int) -> None:
        barrier.wait()
        for _ in range(3):
            with Session(engine) as own:
                # Unbalanced: rejected in Python, so the number is never consumed.
                with pytest.raises(DomainError):
                    post(
                        own,
                        PostingRequest(
                            company_id=books.company_id,
                            journal_id=books.journals["MISC"],
                            date=ENTRY_DATE,
                            currency_code="SAR",
                            lines=(
                                PostingLine(books.accounts["expense"], debit=Decimal("10.00")),
                                PostingLine(books.accounts["bank"], credit=Decimal("9.00")),
                            ),
                        ),
                    )
                own.rollback()

    def rolled_back(_: int) -> None:
        barrier.wait()
        for _ in range(3):
            with Session(engine) as own:
                post(own, request(books, "MISC"))  # takes a number…
                own.rollback()  # …and gives it back

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(good, 0),
            pool.submit(good, 1),
            pool.submit(bad, 2),
            pool.submit(rolled_back, 3),
        ]
        for future in futures:
            future.result()

    assert numbers(engine, books, "MISC") == [1, 2, 3, 4, 5, 6]


def test_every_committed_entry_balances(engine: Engine, session: Session) -> None:
    """The point of the whole exercise: no concurrent writer can commit a broken entry."""
    books = make_books(session)
    barrier = Barrier(THREADS)

    def worker(index: int) -> None:
        barrier.wait()
        with Session(engine) as own:
            post(own, request(books, "MISC", amount=f"{index + 1}.50"))
            own.commit()

    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        list(pool.map(worker, range(THREADS)))

    with engine.connect() as connection:
        unbalanced = connection.execute(
            text(
                """
                SELECT e.number, sum(l.debit) - sum(l.credit) AS difference
                FROM journal_entry e JOIN journal_entry_line l ON l.entry_id = e.id
                WHERE e.company_id = :c AND e.state = 'posted'
                GROUP BY e.number HAVING sum(l.debit) <> sum(l.credit)
                """
            ),
            {"c": books.company_id},
        ).all()
    assert unbalanced == []
