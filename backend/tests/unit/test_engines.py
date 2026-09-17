"""Connection settings for Neon's pooled and direct endpoints, and error translation
in the unit of work. No database needed: engines are built but never connected.
"""

import pytest
from sqlalchemy.exc import DBAPIError

from app.db import engine_options, make_engine, sqlalchemy_url
from app.shared.errors import DomainError
from tests.unit.test_errors import FakeOrig

POOLED = "postgresql://u:p@ep-x-pooler.c-6.us-east-2.aws.neon.tech/neondb?sslmode=require"
DIRECT = "postgresql://u:p@ep-x.c-6.us-east-2.aws.neon.tech/neondb?sslmode=require"


def test_pooled_endpoint_disables_prepared_statements() -> None:
    options = engine_options(pooled=True)
    assert options["connect_args"] == {"prepare_threshold": None}


def test_direct_endpoint_keeps_prepared_statements() -> None:
    assert engine_options(pooled=False)["connect_args"] == {}


def test_both_endpoints_pre_ping_for_suspended_computes() -> None:
    assert engine_options(pooled=True)["pool_pre_ping"] is True
    assert engine_options(pooled=False)["pool_pre_ping"] is True


def test_pool_size_bounds_concurrency() -> None:
    options = engine_options(pooled=False, pool_size=12)
    assert (options["pool_size"], options["max_overflow"]) == (12, 12)


@pytest.mark.parametrize("url", [POOLED, DIRECT])
def test_engines_use_psycopg_and_keep_query_args(url: str) -> None:
    engine = make_engine(url, pooled="-pooler" in url)
    assert engine.dialect.driver == "psycopg"
    assert engine.url.query["sslmode"] == "require"
    assert engine.pool._pre_ping is True
    engine.dispose()


def test_sqlalchemy_url_leaves_an_explicit_driver_alone() -> None:
    assert sqlalchemy_url("postgresql+psycopg://u:p@host/db").drivername == "postgresql+psycopg"


def test_unit_of_work_translates_database_errors() -> None:
    """``transaction`` maps a trigger's ``ledger.<code>`` onto DomainError; the real
    commit-time (deferred) path is proven against PostgreSQL in tests/ledger/test_posting.py.
    """
    from app.shared.errors import domain_error_from_db

    exc = DBAPIError(
        "COMMIT", {}, FakeOrig("ledger.unbalanced: entry MISC/2026/00001 debit 100 credit 99")
    )
    translated = domain_error_from_db(exc)
    assert isinstance(translated, DomainError)
    assert translated.code == "ledger.unbalanced"
