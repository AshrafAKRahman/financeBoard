"""Engines and sessions.

Neon's pooled endpoint runs PgBouncer in transaction mode, so pooled connections
disable server-side prepared statements and must only use ``SET LOCAL``.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.shared.errors import domain_error_from_db


def sqlalchemy_url(url: str) -> URL:
    """Accept a plain ``postgresql://`` URL (as Neon hands out) and use psycopg 3."""
    parsed = make_url(url)
    if parsed.drivername in ("postgres", "postgresql"):
        parsed = parsed.set(drivername="postgresql+psycopg")
    return parsed


def engine_options(*, pooled: bool, pool_size: int = 5) -> dict:
    """Engine options for a Neon endpoint.

    Pooled endpoints run PgBouncer in transaction mode, which cannot keep server-side
    prepared statements; ``prepare_threshold=None`` stops psycopg creating them. Pre-ping
    replaces connections that Neon closed while the compute was suspended.
    """
    return {
        "pool_pre_ping": True,
        "pool_size": pool_size,
        "max_overflow": pool_size,
        "connect_args": {"prepare_threshold": None} if pooled else {},
    }


def make_engine(url: str | URL, *, pooled: bool, pool_size: int = 5) -> Engine:
    return create_engine(
        sqlalchemy_url(url) if isinstance(url, str) else url,
        **engine_options(pooled=pooled, pool_size=pool_size),
    )


@cache
def pooled_engine() -> Engine:
    return make_engine(get_settings().database_url, pooled=True)


@cache
def direct_engine() -> Engine:
    return make_engine(get_settings().database_url_direct, pooled=False)


@contextmanager
def transaction(engine: Engine | None = None) -> Iterator[Session]:
    """One unit of work: commit on success, rollback on error.

    Database invariant violations (raised by triggers as ``<module>.<code>: message``)
    are re-raised as ``DomainError`` — including deferred checks that only fire at commit.
    """
    with Session(engine or pooled_engine(), expire_on_commit=False) as session:
        try:
            yield session
            session.commit()
        except DBAPIError as exc:
            session.rollback()
            translated = domain_error_from_db(exc)
            if translated is not None:
                raise translated from exc
            raise
        except BaseException:
            session.rollback()
            raise
