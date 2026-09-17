"""Helpers for tests that write raw SQL, bypassing the application entirely (R3.AC9)."""

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy.exc import DBAPIError

from app.shared.errors import domain_error_from_db

CHECK_VIOLATION = "23514"
FOREIGN_KEY_VIOLATION = "23503"
UNIQUE_VIOLATION = "23505"
NOT_NULL_VIOLATION = "23502"


@contextmanager
def rejects(code: str | None = None, sqlstate: str | None = None) -> Iterator[None]:
    """Assert the database refuses the block, either with a coded trigger message
    (``ledger.<code>``) or with a specific constraint SQLSTATE."""
    with pytest.raises(DBAPIError) as caught:
        yield

    error = caught.value
    if code is not None:
        translated = domain_error_from_db(error)
        assert translated is not None, f"expected {code}, got: {error.orig}"
        assert translated.code == code, (
            f"expected {code}, got {translated.code}: {translated.message}"
        )
    if sqlstate is not None:
        actual = getattr(error.orig, "sqlstate", None)
        assert actual == sqlstate, f"expected SQLSTATE {sqlstate}, got {actual}: {error.orig}"
