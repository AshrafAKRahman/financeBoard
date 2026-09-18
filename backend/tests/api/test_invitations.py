"""The invitation endpoints, end to end (R11.AC3 and the flow around it)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.platform.identity import api as identity
from app.platform.mail.api import RecordingMailer
from app.shared.ids import uuid7
from tests.api.conftest import SAME_ORIGIN, Person, sign_in

pytestmark = pytest.mark.db

PASSWORD = "a-long-enough-password"


def fresh_email() -> str:
    return f"invited-{uuid7().hex[-10:]}@example.sa"


def token_from(mailer: RecordingMailer) -> str:
    link = next(word for word in mailer.sent[-1].text.split() if "/invitations/" in word)
    return link.rsplit("/", 2)[-2]


def test_inviting_creates_the_user_and_sends_the_link(
    client: TestClient, administrator: Person, mailer: RecordingMailer
) -> None:
    sign_in(client, administrator)
    email = fresh_email()

    response = client.post(
        "/api/v1/invitations", json={"email": email, "name": "New Joiner"}, headers=SAME_ORIGIN
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == email
    assert body["email_sent"] is True
    # The administrator fixture was itself invited, so check the latest email, not the count.
    assert mailer.sent[-1].to == email


def test_the_response_carries_no_token(
    client: TestClient, administrator: Person, mailer: RecordingMailer
) -> None:
    sign_in(client, administrator)
    response = client.post(
        "/api/v1/invitations", json={"email": fresh_email(), "name": "New Joiner"},
        headers=SAME_ORIGIN,
    )
    assert token_from(mailer) not in response.text


def test_accepting_the_link_sets_a_password_and_signs_in(
    client: TestClient, administrator: Person, mailer: RecordingMailer
) -> None:
    """R11.AC3"""
    sign_in(client, administrator)
    email = fresh_email()
    client.post(
        "/api/v1/invitations", json={"email": email, "name": "New Joiner"}, headers=SAME_ORIGIN
    )
    token = token_from(mailer)
    client.cookies.clear()

    accepted = client.post(
        f"/api/v1/invitations/{token}/accept", json={"password": PASSWORD}, headers=SAME_ORIGIN
    )

    assert accepted.status_code == 204
    assert "sid=" in accepted.headers["set-cookie"]
    profile = client.get("/api/v1/auth/me")
    assert profile.status_code == 200
    assert profile.json()["email"] == email


def test_checking_a_link_before_using_it(
    client: TestClient, administrator: Person, mailer: RecordingMailer
) -> None:
    sign_in(client, administrator)
    email = fresh_email()
    client.post(
        "/api/v1/invitations", json={"email": email, "name": "New Joiner"}, headers=SAME_ORIGIN
    )
    token = token_from(mailer)
    client.cookies.clear()

    body = client.get(f"/api/v1/invitations/{token}").json()
    assert body["status"] == "valid"
    assert body["email"] == email


@pytest.mark.parametrize(
    ("token", "status", "code"),
    [("made-up-token", 404, "identity.invitation_invalid")],
)
def test_a_bad_link_is_reported(
    client: TestClient, token: str, status: int, code: str
) -> None:
    response = client.get(f"/api/v1/invitations/{token}")
    assert response.status_code == status
    assert response.json()["code"] == code


def test_a_used_link_cannot_be_used_again(
    client: TestClient, administrator: Person, mailer: RecordingMailer
) -> None:
    sign_in(client, administrator)
    client.post(
        "/api/v1/invitations", json={"email": fresh_email(), "name": "New Joiner"},
        headers=SAME_ORIGIN,
    )
    token = token_from(mailer)
    client.cookies.clear()
    client.post(
        f"/api/v1/invitations/{token}/accept", json={"password": PASSWORD}, headers=SAME_ORIGIN
    )

    again = client.post(
        f"/api/v1/invitations/{token}/accept", json={"password": PASSWORD}, headers=SAME_ORIGIN
    )
    assert again.status_code == 409
    assert again.json()["code"] == "identity.invitation_used"


def test_resending_replaces_the_link(
    client: TestClient, administrator: Person, mailer: RecordingMailer
) -> None:
    sign_in(client, administrator)
    created = client.post(
        "/api/v1/invitations", json={"email": fresh_email(), "name": "New Joiner"},
        headers=SAME_ORIGIN,
    ).json()
    first_token = token_from(mailer)

    resent = client.post(
        f"/api/v1/invitations/{created['id']}/resend", headers=SAME_ORIGIN
    )
    assert resent.status_code == 200
    second_token = token_from(mailer)
    assert second_token != first_token

    client.cookies.clear()
    assert client.get(f"/api/v1/invitations/{first_token}").status_code == 404
    assert client.get(f"/api/v1/invitations/{second_token}").status_code == 200


def test_revoking_kills_the_link(
    client: TestClient, administrator: Person, mailer: RecordingMailer
) -> None:
    sign_in(client, administrator)
    created = client.post(
        "/api/v1/invitations", json={"email": fresh_email(), "name": "New Joiner"},
        headers=SAME_ORIGIN,
    ).json()
    token = token_from(mailer)

    assert client.post(
        f"/api/v1/invitations/{created['id']}/revoke", headers=SAME_ORIGIN
    ).status_code == 204

    client.cookies.clear()
    assert client.get(f"/api/v1/invitations/{token}").status_code == 404


def test_inviting_needs_the_permission(client: TestClient, bystander: Person) -> None:
    sign_in(client, bystander)
    response = client.post(
        "/api/v1/invitations", json={"email": fresh_email(), "name": "New Joiner"},
        headers=SAME_ORIGIN,
    )
    assert response.status_code == 403


def test_a_duplicate_address_is_refused(
    client: TestClient, administrator: Person
) -> None:
    sign_in(client, administrator)
    email = fresh_email()
    body = {"email": email, "name": "New Joiner"}
    assert client.post("/api/v1/invitations", json=body, headers=SAME_ORIGIN).status_code == 201

    again = client.post("/api/v1/invitations", json=body, headers=SAME_ORIGIN)
    assert again.status_code == 409
    assert again.json()["code"] == "identity.duplicate_email"


def test_an_invalid_address_is_refused(client: TestClient, administrator: Person) -> None:
    sign_in(client, administrator)
    response = client.post(
        "/api/v1/invitations", json={"email": "not-an-address", "name": "X"}, headers=SAME_ORIGIN
    )
    assert response.status_code == 422
    assert response.json()["code"] == "identity.invalid_email"


def test_a_refusing_relay_still_keeps_the_invitation(
    client: TestClient,
    session: Session,
    administrator: Person,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R11.AC10 — 502, but the invitation is there to resend."""
    failing = RecordingMailer(fail_with="relay unavailable")
    monkeypatch.setattr("app.platform.identity.api.get_mailer", lambda: failing)
    sign_in(client, administrator)
    email = fresh_email()

    response = client.post(
        "/api/v1/invitations", json={"email": email, "name": "New Joiner"}, headers=SAME_ORIGIN
    )

    assert response.status_code == 502
    assert response.json()["code"] == "identity.invitation_email_failed"
    session.commit()
    assert identity.get_user_by_email(session, email) is not None
