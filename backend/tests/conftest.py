"""Database tests run against the Neon branch in TEST_DATABASE_URL (direct endpoint).

Each pytest-xdist worker gets its own throwaway database on that branch, migrated from
scratch and dropped afterwards. Tests commit for real — the deferred balance check only
fires at COMMIT — and stay isolated from each other by creating their own company.
"""

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, text
from sqlalchemy.orm import Session

from app.db import make_engine, sqlalchemy_url

BACKEND_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BACKEND_DIR / ".env"
TEST_URL_VAR = "TEST_DATABASE_URL"


def _load_env_file() -> None:
    """Make backend/.env available to tests without exporting variables by hand."""
    if os.environ.get(TEST_URL_VAR) or not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _admin_engine(base_url: str) -> Engine:
    return make_engine(base_url, pooled=False, pool_size=1).execution_options(
        isolation_level="AUTOCOMMIT"
    )


def _create_database(admin: Engine, name: str) -> None:
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{name}"'))


def _drop_database(admin: Engine, name: str) -> None:
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def migrate(connection: Connection, revision: str = "head") -> None:
    """Run Alembic over an open connection (the direct endpoint, never the pooler)."""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["connection"] = connection
    if revision == "base":
        command.downgrade(config, "base")
    else:
        command.upgrade(config, revision)


@pytest.fixture(scope="session")
def test_database_url() -> str:
    _load_env_file()
    url = os.environ.get(TEST_URL_VAR)
    if not url:
        pytest.skip(f"{TEST_URL_VAR} not set — point it at the direct URL of a Neon branch")
    return url


@pytest.fixture(scope="session")
def admin_engine(test_database_url: str) -> Iterator[Engine]:
    engine = _admin_engine(test_database_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def engine(test_database_url: str, admin_engine: Engine, worker_id: str) -> Iterator[Engine]:
    """A migrated database of this worker's own, dropped when the session ends."""
    database = f"ledger_test_{worker_id}_{uuid.uuid4().hex[:8]}"
    _create_database(admin_engine, database)

    test_engine = make_engine(
        sqlalchemy_url(test_database_url).set(database=database), pooled=False, pool_size=12
    )
    with test_engine.begin() as connection:
        migrate(connection)

    yield test_engine

    test_engine.dispose()
    _drop_database(admin_engine, database)


@pytest.fixture
def scratch_database(test_database_url: str, admin_engine: Engine) -> Iterator[Engine]:
    """An empty, un-migrated database for tests that apply migrations themselves."""
    database = f"ledger_scratch_{uuid.uuid4().hex[:8]}"
    _create_database(admin_engine, database)
    engine = make_engine(
        sqlalchemy_url(test_database_url).set(database=database), pooled=False, pool_size=2
    )
    yield engine
    engine.dispose()
    _drop_database(admin_engine, database)


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine, expire_on_commit=False) as s:
        yield s
        s.rollback()
