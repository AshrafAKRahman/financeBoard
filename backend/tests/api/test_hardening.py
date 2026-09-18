"""The security properties that are easy to lose quietly (NFR1, NFR2).

Timing equality is asserted by counting hash verifications rather than measuring the
clock, so this stays deterministic on a laptop and in CI.
"""

import pytest
from fastapi.testclient import TestClient

from app.api.protection import declared_access, iter_api_routes
from app.main import app
from app.platform.identity import passwords
from tests.api.conftest import ORIGIN, PASSWORD, Person, sign_in

pytestmark = pytest.mark.db

SECRET_MARKERS = ("password_hash", "token_hash", "$argon2", "sid=")


def test_sign_in_failures_are_indistinguishable(
    client: TestClient, administrator: Person
) -> None:
    """R3.AC3 — same status, same body, for a wrong password and an unknown address."""
    wrong_password = client.post(
        "/api/v1/auth/login",
        json={"email": administrator.email, "password": "definitely-not-it"},
        headers={"Origin": ORIGIN},
    )
    unknown_address = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody-at-all@example.sa", "password": PASSWORD},
        headers={"Origin": ORIGIN},
    )

    assert wrong_password.status_code == unknown_address.status_code == 401
    assert wrong_password.json() == unknown_address.json()
    assert "set-cookie" not in wrong_password.headers
    assert "set-cookie" not in unknown_address.headers


def test_both_failure_paths_do_one_hash_verification(
    client: TestClient, administrator: Person, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3.AC8 — an unknown address must not be cheaper than a wrong password."""
    counts: list[str] = []

    real_verify = passwords.verify_password
    monkeypatch.setattr(
        passwords,
        "verify_password",
        lambda stored, given: (counts.append("verify"), real_verify(stored, given))[1],
    )
    monkeypatch.setattr(passwords, "verify_dummy", lambda: counts.append("dummy"))

    client.post(
        "/api/v1/auth/login",
        json={"email": administrator.email, "password": "definitely-not-it"},
        headers={"Origin": ORIGIN},
    )
    after_wrong_password = list(counts)
    counts.clear()

    client.post(
        "/api/v1/auth/login",
        json={"email": "nobody-at-all@example.sa", "password": PASSWORD},
        headers={"Origin": ORIGIN},
    )

    assert len(after_wrong_password) == 1
    assert len(counts) == 1


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/auth/me"),
        ("get", "/api/v1/users"),
    ],
)
def test_no_response_leaks_a_stored_secret(
    client: TestClient, administrator: Person, method: str, path: str
) -> None:
    """R2.AC2, R10.AC3"""
    sign_in(client, administrator)
    body = getattr(client, method)(path).text
    for marker in SECRET_MARKERS:
        assert marker not in body, f"{path} leaked {marker}"


def test_error_responses_do_not_echo_the_password(
    client: TestClient, administrator: Person
) -> None:
    """R2.AC3"""
    secret = "the-password-i-typed"
    response = client.post(
        "/api/v1/auth/login",
        json={"email": administrator.email, "password": secret},
        headers={"Origin": ORIGIN},
    )
    assert secret not in response.text


def test_every_route_is_protected_or_deliberately_public() -> None:
    """NFR2 — the whole point of the start-up check, asserted once more here."""
    undeclared = [
        f"{sorted(route.methods)} {route.path}"
        for route in iter_api_routes(app)
        if declared_access(route) is None
    ]
    assert undeclared == []


def test_protected_routes_refuse_anonymous_callers(client: TestClient) -> None:
    """A sweep rather than a list: every non-public GET must answer 401 with no cookie."""
    for route in iter_api_routes(app):
        if declared_access(route) in {"public", None} or "GET" not in route.methods:
            continue
        path = route.path.replace("{company_id}", "00000000-0000-7000-8000-000000000000")
        path = path.replace("{token}", "x").replace("{user_id}", "x")
        response = client.get(path)
        assert response.status_code == 401, f"{path} answered {response.status_code}"


def test_cookies_are_http_only_and_same_site(
    client: TestClient, administrator: Person
) -> None:
    """NFR1 — the cookie flags are the browser-side half of the protection."""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": administrator.email, "password": PASSWORD},
        headers={"Origin": ORIGIN},
    )
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/" in cookie
