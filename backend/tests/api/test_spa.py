"""The API serves the web application from its own origin (R10.AC3, C3, C4).

The cookie is `SameSite=Lax`, so a browser only sends it to the origin that set it. These
tests hold the API to that: the application's HTML comes from the same host as the data, a
deep link answers with the application rather than a 404, and an unknown API path stays a
404 so a caller is never handed HTML where it expected JSON.
"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.spa import mount_web_application

INDEX = "<!doctype html><title>Finance</title><div id=root></div>"


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    """A built frontend, small enough to read."""
    (tmp_path / "index.html").write_text(INDEX)
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "index-abc123.js").write_text("console.log(1)")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    return tmp_path


@pytest.fixture
def served(dist: Path) -> TestClient:
    application = FastAPI()

    @application.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    assert mount_web_application(application, dist)
    return TestClient(application)


def test_the_root_serves_the_application(served: TestClient) -> None:
    response = served.get("/")

    assert response.status_code == 200
    assert response.text == INDEX


def test_a_deep_link_serves_the_application(served: TestClient) -> None:
    # A person bookmarks a report. The browser asks the server for that path, and the
    # server has no such route — the application does (R10.AC3).
    response = served.get("/companies/019a0000-0000-7000-8000-000000000001/reports/trial-balance")

    assert response.status_code == 200
    assert response.text == INDEX


def test_an_asset_is_served_as_itself(served: TestClient) -> None:
    response = served.get("/assets/index-abc123.js")

    assert response.status_code == 200
    assert response.text == "console.log(1)"


def test_a_hashed_asset_may_be_cached_forever(served: TestClient) -> None:
    # Its name changes when its contents do, so it can never go stale (C4).
    response = served.get("/assets/index-abc123.js")

    assert "immutable" in response.headers["cache-control"]


def test_the_entry_document_is_never_cached(served: TestClient) -> None:
    # It names the current assets. Cached, a deploy would go unseen.
    response = served.get("/")

    assert response.headers["cache-control"] == "no-cache"


def test_a_file_beside_the_index_is_served(served: TestClient) -> None:
    response = served.get("/favicon.svg")

    assert response.status_code == 200
    assert response.text == "<svg/>"


def test_the_api_still_answers(served: TestClient) -> None:
    response = served.get("/api/v1/health")

    assert response.json() == {"status": "ok"}


def test_an_unknown_api_path_is_not_the_application(served: TestClient) -> None:
    # Answering with HTML would turn a missing endpoint into a parse error in the caller.
    response = served.get("/api/v1/nothing-here")

    assert response.status_code == 404
    assert "text/html" not in response.headers.get("content-type", "")


def test_a_path_outside_the_build_cannot_be_read(served: TestClient, dist: Path) -> None:
    # Traversal reaches for something outside `dist`; the application answers instead.
    (dist.parent / "secret.txt").write_text("not for the web")

    response = served.get("/../secret.txt")

    assert "not for the web" not in response.text


def test_nothing_is_mounted_without_a_build(tmp_path: Path) -> None:
    # Development: Vite serves the application, and the API is unchanged (C3).
    application = FastAPI()

    assert mount_web_application(application, tmp_path) is False
    assert TestClient(application).get("/").status_code == 404
