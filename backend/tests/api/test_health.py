"""The health endpoint Railway will poll: honest about the database (R14.AC4, R14.AC5)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine

from app import main  # the FastAPI module; "app" alone is the package


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app, raise_server_exceptions=False)


@pytest.mark.db
def test_reports_ok_when_the_database_answers(
    client: TestClient, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main, "pooled_engine", lambda: engine)

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_reports_degraded_when_the_database_is_unreachable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No database needed: the endpoint must fail soft, not raise."""
    unreachable = create_engine(
        "postgresql+psycopg://nobody:nobody@127.0.0.1:1/none",
        connect_args={"connect_timeout": 1},
    )
    monkeypatch.setattr(main, "pooled_engine", lambda: unreachable)

    response = client.get("/api/v1/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unreachable"}
    unreachable.dispose()
