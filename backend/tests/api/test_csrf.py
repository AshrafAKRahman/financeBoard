"""Cookie-authenticated writes must come from our own origin (R12)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from tests.api.conftest import ORIGIN, PASSWORD, Person, sign_in

pytestmark = pytest.mark.db

FOREIGN = "https://evil.example.com"


def invite_body() -> dict:
    """A fresh address each time, so a repeat call is not refused as a duplicate."""
    from app.shared.ids import uuid7

    return {"email": f"invitee-{uuid7().hex[-10:]}@example.sa", "name": "Someone New"}


def test_accepted_origins_come_from_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """R12.AC1"""
    settings = get_settings()
    monkeypatch.setattr(settings, "public_base_url", "https://books.example.sa/", raising=False)
    monkeypatch.setattr(
        settings, "extra_accepted_origins", "http://localhost:5173, https://staging.example.sa/"
    )
    assert settings.accepted_origins == {
        "https://books.example.sa",
        "http://localhost:5173",
        "https://staging.example.sa",
    }


def test_a_foreign_origin_is_blocked(client: TestClient, administrator: Person) -> None:
    """R12.AC2"""
    sign_in(client, administrator)
    response = client.post("/api/v1/invitations", json=invite_body(), headers={"Origin": FOREIGN})
    assert response.status_code == 403
    assert response.json()["code"] == "identity.csrf_check_failed"


def test_a_cross_site_fetch_is_blocked(client: TestClient, administrator: Person) -> None:
    """R12.AC3"""
    sign_in(client, administrator)
    response = client.post(
        "/api/v1/invitations", json=invite_body(), headers={"Sec-Fetch-Site": "cross-site"}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "identity.csrf_check_failed"


def test_a_write_with_neither_header_is_blocked(client: TestClient, administrator: Person) -> None:
    """R12.AC4 — a cookie with no origin at all is refused, which also covers curl."""
    sign_in(client, administrator)
    response = client.post("/api/v1/invitations", json=invite_body())
    assert response.status_code == 403
    assert response.json()["code"] == "identity.csrf_check_failed"


@pytest.mark.parametrize(
    "headers", [{"Origin": ORIGIN}, {"Sec-Fetch-Site": "same-origin"}, {"Origin": ORIGIN + "/"}]
)
def test_our_own_origin_is_allowed(
    client: TestClient, administrator: Person, headers: dict
) -> None:
    """R12.AC5"""
    sign_in(client, administrator)
    response = client.post("/api/v1/invitations", json=invite_body(), headers=headers)
    assert response.status_code in {201, 502}  # 502 only if the relay refused
    assert response.json().get("code") != "identity.csrf_check_failed"


def test_reads_are_never_checked(client: TestClient, administrator: Person) -> None:
    """R12.AC6"""
    sign_in(client, administrator)
    assert client.get("/api/v1/auth/me", headers={"Origin": FOREIGN}).status_code == 200
    assert client.get("/api/v1/users", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200


def test_login_is_checked_even_without_a_session(client: TestClient, administrator: Person) -> None:
    """R12.AC7 — otherwise another site could sign someone into an account it controls."""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": administrator.email, "password": PASSWORD},
        headers={"Origin": FOREIGN},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "identity.csrf_check_failed"


def test_invitation_acceptance_is_checked_too(
    client: TestClient, session: Session, mailer, administrator: Person
) -> None:
    """R12.AC7 for the other public write."""
    from app.platform.identity import api as identity

    result = identity.invite_user(
        session, email="fresh-face@example.sa", name="Fresh Face", mailer=mailer
    )
    session.commit()
    token = result.link.rsplit("/", 2)[-2]

    blocked = client.post(
        f"/api/v1/invitations/{token}/accept",
        json={"password": "a-long-enough-password"},
        headers={"Origin": FOREIGN},
    )
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "identity.csrf_check_failed"

    allowed = client.post(
        f"/api/v1/invitations/{token}/accept",
        json={"password": "a-long-enough-password"},
        headers={"Origin": ORIGIN},
    )
    assert allowed.status_code == 204


def test_session_cookies_are_same_site_lax(client: TestClient, administrator: Person) -> None:
    """R12.AC8"""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": administrator.email, "password": PASSWORD},
        headers={"Origin": ORIGIN},
    )
    assert "samesite=lax" in response.headers["set-cookie"].lower()


def test_a_blocked_request_is_audited_with_its_origin(
    client: TestClient, session: Session, administrator: Person
) -> None:
    """R12.AC9"""
    sign_in(client, administrator)
    client.post("/api/v1/invitations", json=invite_body(), headers={"Origin": FOREIGN})

    session.commit()
    rows = (
        session.execute(
            text(
                "SELECT detail::text FROM audit_log WHERE action = 'request.csrf_blocked' "
                "ORDER BY at DESC LIMIT 1"
            )
        )
        .scalars()
        .all()
    )
    assert rows and FOREIGN in rows[0]
    assert "/api/v1/invitations" in rows[0]
