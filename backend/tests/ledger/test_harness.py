"""The test harness itself: per-worker Neon databases, migrations, cleanup, and the
skip behaviour when no test branch is configured (R15).
"""

import os
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from tests import conftest
from tests.factories import make_books

pytestmark = pytest.mark.db


def test_worker_gets_its_own_database(engine: Engine, worker_id: str) -> None:
    """R15.AC1 — the database is this worker's alone, never the branch's default."""
    name = engine.url.database or ""
    assert name.startswith(f"ledger_test_{worker_id}_")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT current_database()")).scalar() == name


def test_database_is_migrated(engine: Engine) -> None:
    """R15.AC2 — migrations ran, so the schema and seed data are present."""
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM currency")).scalar() == 13
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert version == "0001"


def test_cleanup_drops_databases_it_created(admin_engine: Engine, test_database_url: str) -> None:
    """R15.AC3 — create/drop is exercised here so the session teardown path is proven."""
    name = "ledger_harness_probe"
    conftest._create_database(admin_engine, name)
    with admin_engine.connect() as connection:
        assert connection.execute(
            text("SELECT count(*) FROM pg_database WHERE datname = :n"), {"n": name}
        ).scalar() == 1

    conftest._drop_database(admin_engine, name)
    with admin_engine.connect() as connection:
        assert connection.execute(
            text("SELECT count(*) FROM pg_database WHERE datname = :n"), {"n": name}
        ).scalar() == 0


def test_skips_when_no_test_branch_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """R15.AC4 — without TEST_DATABASE_URL, database tests skip with a clear message."""
    monkeypatch.delenv(conftest.TEST_URL_VAR, raising=False)
    monkeypatch.setattr(conftest, "ENV_FILE", Path("/nonexistent/.env"))

    with pytest.raises(pytest.skip.Exception) as skipped:
        conftest.test_database_url.__wrapped__()

    assert conftest.TEST_URL_VAR in str(skipped.value)


def test_env_file_supplies_the_test_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """The harness reads backend/.env so no variables have to be exported by hand.

    That file is git-ignored and local-only; in CI the URL comes from a secret instead.
    """
    if not conftest.ENV_FILE.exists():
        pytest.skip("backend/.env is local-only; CI supplies TEST_DATABASE_URL directly")

    monkeypatch.delenv(conftest.TEST_URL_VAR, raising=False)
    conftest._load_env_file()
    assert os.environ[conftest.TEST_URL_VAR].startswith("postgresql://")


def test_factories_build_an_isolated_company(session) -> None:
    """Every test creates its own company, which is what keeps tests independent."""
    first = make_books(session)
    second = make_books(session)
    assert first.company_id != second.company_id
    assert set(first.journals) == {"MISC", "INV", "BNK"}
    assert {"bank", "receivable", "revenue", "rounding"} <= set(first.accounts)

    count = session.execute(
        text("SELECT count(*) FROM account WHERE company_id = :c"), {"c": first.company_id}
    ).scalar()
    assert count == len(first.accounts)
