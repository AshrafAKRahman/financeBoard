"""Gapless counters (R6.AC2, R6.AC4). Concurrency is proven in tests/concurrency/."""

import pytest
from sqlalchemy.orm import Session

from app.platform.sequence.api import next_number
from tests.factories import make_books

pytestmark = pytest.mark.db


def test_numbers_start_at_one_and_count_up(session: Session) -> None:
    books = make_books(session)
    scope = f"journal:{books.journals['MISC']}"
    assert [next_number(session, books.company_id, scope, "2026") for _ in range(5)] == [
        1,
        2,
        3,
        4,
        5,
    ]


def test_scopes_and_periods_count_independently(session: Session) -> None:
    books = make_books(session)
    misc = f"journal:{books.journals['MISC']}"
    sales = f"journal:{books.journals['INV']}"

    assert next_number(session, books.company_id, misc, "2026") == 1
    assert next_number(session, books.company_id, sales, "2026") == 1
    assert next_number(session, books.company_id, misc, "2027") == 1
    assert next_number(session, books.company_id, misc, "2026") == 2


def test_companies_count_independently(session: Session) -> None:
    ours = make_books(session)
    theirs = make_books(session)
    scope = "journal:shared-scope-name"

    assert next_number(session, ours.company_id, scope, "2026") == 1
    assert next_number(session, theirs.company_id, scope, "2026") == 1
    assert next_number(session, ours.company_id, scope, "2026") == 2


def test_a_rolled_back_number_is_reused(session: Session) -> None:
    """R6.AC4 — the counter is transactional, so a failed posting leaves no gap."""
    books = make_books(session)
    scope = f"journal:{books.journals['MISC']}"

    assert next_number(session, books.company_id, scope, "2026") == 1
    session.commit()

    assert next_number(session, books.company_id, scope, "2026") == 2
    session.rollback()

    assert next_number(session, books.company_id, scope, "2026") == 2
    session.commit()
    assert next_number(session, books.company_id, scope, "2026") == 3


def test_first_number_is_reused_after_a_rollback(session: Session) -> None:
    """The very first call inserts the counter row; a rollback must remove it again."""
    books = make_books(session)
    scope = f"journal:{books.journals['BNK']}"

    assert next_number(session, books.company_id, scope, "2026") == 1
    session.rollback()
    assert next_number(session, books.company_id, scope, "2026") == 1
