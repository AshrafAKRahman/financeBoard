"""The account hierarchy rules, proven with raw SQL (R2.AC3, R2.AC4, R2.AC5)."""

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.shared.ids import uuid7
from tests.factories import Books, make_books
from tests.invariants.helpers import rejects

pytestmark = pytest.mark.db


@pytest.fixture
def books(session: Session) -> Books:
    return make_books(session)


def add_account(
    connection,
    books: Books,
    code: str,
    *,
    type_: str = "asset",
    subtype: str = "current_asset",
    is_group: bool = False,
    parent_id=None,
):
    account_id = uuid7()
    connection.execute(
        text(
            "INSERT INTO account (id, company_id, code, name, type, subtype, is_group, parent_id) "
            "VALUES (:id, :company, :code, :name, :type, :subtype, :is_group, :parent)"
        ),
        {
            "id": account_id,
            "company": books.company_id,
            "code": code,
            "name": f"Account {code}",
            "type": type_,
            "subtype": subtype,
            "is_group": is_group,
            "parent": parent_id,
        },
    )
    return account_id


def test_a_group_parent_of_the_same_type_is_allowed(engine: Engine, books: Books) -> None:
    with engine.begin() as connection:
        parent = add_account(connection, books, "1500", is_group=True)
        add_account(connection, books, "1501", parent_id=parent)


def test_a_parent_must_be_a_group_account(engine: Engine, books: Books) -> None:
    """R2.AC3"""
    with rejects("coa.parent_not_group"), engine.begin() as connection:
        leaf = add_account(connection, books, "1600")
        add_account(connection, books, "1601", parent_id=leaf)


def test_a_parent_must_share_the_type(engine: Engine, books: Books) -> None:
    """R2.AC4"""
    with rejects("coa.parent_type_mismatch"), engine.begin() as connection:
        parent = add_account(connection, books, "1700", is_group=True)
        add_account(
            connection,
            books,
            "2700",
            type_="liability",
            subtype="current_liability",
            parent_id=parent,
        )


def test_an_account_cannot_be_its_own_parent(engine: Engine, books: Books) -> None:
    """R2.AC5"""
    with engine.begin() as connection:
        account = add_account(connection, books, "1800", is_group=True)

    with rejects("coa.hierarchy_cycle"), engine.begin() as connection:
        connection.execute(
            text("UPDATE account SET parent_id = id WHERE id = :id"), {"id": account}
        )


def test_a_loop_is_refused(engine: Engine, books: Books) -> None:
    """R2.AC5 — the case a single self-reference check would miss."""
    with engine.begin() as connection:
        grandparent = add_account(connection, books, "1900", is_group=True)
        parent = add_account(connection, books, "1910", is_group=True, parent_id=grandparent)
        child = add_account(connection, books, "1911", is_group=True, parent_id=parent)

    with rejects("coa.hierarchy_cycle"), engine.begin() as connection:
        connection.execute(
            text("UPDATE account SET parent_id = :child WHERE id = :grandparent"),
            {"child": child, "grandparent": grandparent},
        )


def test_an_unknown_parent_is_refused(engine: Engine, books: Books) -> None:
    with rejects(), engine.begin() as connection:
        add_account(connection, books, "1950", parent_id=uuid7())


def test_the_chart_cannot_nest_forever(engine: Engine, books: Books) -> None:
    """A depth limit keeps the ancestor walk bounded: ten levels are fine, eleven is not
    (design: Failure Modes)."""
    with engine.begin() as connection:
        parent = None
        for level in range(10):  # levels 1..10
            parent = add_account(
                connection, books, f"70{level:02d}", is_group=True, parent_id=parent
            )

    with rejects("coa.hierarchy_too_deep"), engine.begin() as connection:
        add_account(connection, books, "7099", is_group=True, parent_id=parent)
