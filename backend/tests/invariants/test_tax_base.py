"""A tax basis with no return box would be unreportable (R6.AC1). Proven with raw SQL."""

import pytest
from sqlalchemy import Engine, text

from tests.factories import Books, insert_draft_entry, make_books
from tests.invariants.helpers import CHECK_VIOLATION, rejects

pytestmark = pytest.mark.db


@pytest.fixture
def books(session) -> Books:
    return make_books(session)


def test_a_basis_without_a_grid_tag_is_refused(engine: Engine, books: Books) -> None:
    with engine.begin() as connection:
        entry = insert_draft_entry(
            connection, books, [("receivable", "115", "0"), ("revenue", "0", "115")]
        )
        with rejects(sqlstate=CHECK_VIOLATION):
            connection.execute(
                text("UPDATE journal_entry_line SET tax_base = 100 WHERE entry_id = :e"),
                {"e": entry},
            )


def test_a_basis_with_a_grid_tag_is_allowed(engine: Engine, books: Books) -> None:
    with engine.begin() as connection:
        entry = insert_draft_entry(
            connection, books, [("receivable", "115", "0"), ("vat_output", "0", "115")]
        )
        connection.execute(
            text(
                "UPDATE journal_entry_line SET tax_grid_tag = 'sales_standard', tax_base = 100 "
                "WHERE entry_id = :e AND credit > 0"
            ),
            {"e": entry},
        )
        basis = connection.execute(
            text("SELECT tax_base FROM journal_entry_line WHERE entry_id = :e AND credit > 0"),
            {"e": entry},
        ).scalar_one()
    assert basis == 100


def test_a_tag_without_a_basis_is_allowed(engine: Engine, books: Books) -> None:
    """Entries posted before migration 0006 have tags and no basis; they must still be valid."""
    with engine.begin() as connection:
        entry = insert_draft_entry(
            connection, books, [("receivable", "115", "0"), ("vat_output", "0", "115")]
        )
        connection.execute(
            text(
                "UPDATE journal_entry_line SET tax_grid_tag = 'sales_standard' "
                "WHERE entry_id = :e AND credit > 0"
            ),
            {"e": entry},
        )
        tagged = connection.execute(
            text(
                "SELECT count(*) FROM journal_entry_line "
                "WHERE entry_id = :e AND tax_grid_tag IS NOT NULL AND tax_base IS NULL"
            ),
            {"e": entry},
        ).scalar_one()
    assert tagged == 1
