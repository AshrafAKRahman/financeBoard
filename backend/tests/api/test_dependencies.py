"""Authentication and permission checks on real requests (R4.AC3, R7.AC3, R7.AC4)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.platform.access.api import grant_role
from app.platform.tenancy.api import Company
from app.shared.ids import uuid7
from tests.api.conftest import SAME_ORIGIN, Person, sign_in

pytestmark = pytest.mark.db

PROTECTED = [
    ("get", "/api/v1/users"),
    ("get", "/api/v1/auth/me"),
]


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_without_a_cookie_a_protected_route_is_401(
    client: TestClient, method: str, path: str
) -> None:
    """R4.AC3 and R7.AC4"""
    response = getattr(client, method)(path)
    assert response.status_code == 401
    assert response.json()["code"] == "identity.not_authenticated"


def test_an_expired_session_is_401(
    client: TestClient, session: Session, administrator: Person
) -> None:
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import text

    sign_in(client, administrator)
    session.execute(
        text("UPDATE user_session SET expires_at = :past WHERE user_id = :user"),
        {"past": datetime.now(UTC) - timedelta(seconds=1), "user": administrator.user_id},
    )
    session.commit()

    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["code"] == "identity.session_expired"


def test_a_signed_in_user_without_the_permission_is_403(
    client: TestClient, bystander: Person
) -> None:
    """R7.AC3"""
    sign_in(client, bystander)
    response = client.get("/api/v1/users")
    assert response.status_code == 403
    assert response.json()["code"] == "identity.permission_denied"
    assert "user:read" in response.json()["detail"]


def test_a_company_route_needs_a_role_in_that_company(
    client: TestClient, session: Session, administrator: Person, company: Company
) -> None:
    """R6.AC2"""
    other = Company(id=uuid7(), name="Someone Else", base_currency="SAR")
    session.add(other)
    session.commit()

    sign_in(client, administrator)
    assert client.get(f"/api/v1/companies/{company.id}/audit-log").status_code == 200

    refused = client.get(f"/api/v1/companies/{other.id}/audit-log")
    assert refused.status_code == 403
    assert refused.json()["code"] == "identity.company_forbidden"


def test_a_company_that_does_not_exist_answers_the_same_way(
    client: TestClient, administrator: Person, company: Company
) -> None:
    """R6.AC3"""
    sign_in(client, administrator)
    missing = client.get(f"/api/v1/companies/{uuid7()}/audit-log")
    assert missing.status_code == 403
    assert missing.json()["code"] == "identity.company_forbidden"


def test_permissions_are_checked_per_company(
    client: TestClient,
    session: Session,
    bystander: Person,
    company: Company,
    reader_role,
) -> None:
    """R6.AC5 — user:read here, nothing in the other company."""
    other = Company(id=uuid7(), name="Elsewhere", base_currency="SAR")
    session.add(other)
    session.flush()
    grant_role(
        session, user_id=bystander.user_id, company_id=company.id, role_id=reader_role.id
    )
    session.commit()

    sign_in(client, bystander)
    assert client.get("/api/v1/users").status_code == 200  # holds user:read somewhere
    assert client.get(f"/api/v1/companies/{other.id}/audit-log").status_code == 403


def test_the_request_transaction_rolls_back_on_a_refusal(
    client: TestClient, session: Session, bystander: Person
) -> None:
    """A refused write must leave nothing behind."""
    from sqlalchemy import text

    sign_in(client, bystander)
    before = session.execute(text("SELECT count(*) FROM app_user")).scalar_one()

    refused = client.post(
        "/api/v1/invitations",
        json={"email": "new-person@example.sa", "name": "New Person"},
        headers=SAME_ORIGIN,
    )
    assert refused.status_code == 403

    session.commit()  # fresh read
    assert session.execute(text("SELECT count(*) FROM app_user")).scalar_one() == before
