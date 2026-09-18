"""Who may reach the chart endpoints at all (R14)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.protection import declared_access, iter_api_routes
from app.main import app
from app.platform.access.permissions import CODES, PERMISSIONS
from app.platform.tenancy.api import Company
from app.shared.ids import uuid7
from tests.api.conftest import SAME_ORIGIN, Person, sign_in

pytestmark = pytest.mark.db

NEW_PERMISSIONS = [
    "account:read",
    "account:manage",
    "journal:read",
    "journal:manage",
    "rate:read",
    "rate:manage",
    "chart:load",
]


@pytest.mark.parametrize("code", NEW_PERMISSIONS)
def test_the_catalogue_has_the_new_permissions(code: str) -> None:
    """R14.AC1"""
    assert code in CODES
    assert PERMISSIONS[code]


@pytest.mark.parametrize("code", NEW_PERMISSIONS)
def test_the_administrator_role_gets_them(session: Session, code: str) -> None:
    """R14.AC2 — the start-up sync grants new codes to the Administrator."""
    from app.platform.access.api import (
        ADMINISTRATOR_ROLE_NAME,
        ensure_catalogue_seeded,
        get_role_by_name,
        role_permissions,
    )

    ensure_catalogue_seeded(session)
    session.commit()
    administrator = get_role_by_name(session, ADMINISTRATOR_ROLE_NAME)
    assert code in role_permissions(session, administrator.id)


def test_every_chart_route_is_company_scoped_and_declared() -> None:
    """R14.AC3"""
    chart_routes = [
        route
        for route in iter_api_routes(app)
        if any(
            part in route.path
            for part in ("/accounts", "/journals", "/defaults", "/chart-", "/exchange-rates")
        )
    ]
    assert chart_routes
    for route in chart_routes:
        assert route.path.startswith("/api/v1/companies/{company_id}"), route.path
        assert declared_access(route) in CODES, route.path


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/accounts"),
        ("get", "/journals"),
        ("get", "/defaults"),
        ("get", "/chart-readiness"),
        ("get", "/exchange-rates"),
    ],
)
def test_signing_in_is_required(
    client: TestClient, company: Company, method: str, path: str
) -> None:
    """R14.AC4"""
    response = getattr(client, method)(f"/api/v1/companies/{company.id}{path}")
    assert response.status_code == 401
    assert response.json()["code"] == "identity.not_authenticated"


def test_a_company_you_do_not_belong_to_is_refused(
    client: TestClient, session: Session, administrator: Person
) -> None:
    """R14.AC5"""
    other = Company(id=uuid7(), name="Not Yours", base_currency="SAR")
    session.add(other)
    session.commit()

    sign_in(client, administrator)
    refused = client.get(f"/api/v1/companies/{other.id}/accounts")
    missing = client.get(f"/api/v1/companies/{uuid7()}/accounts")

    assert refused.status_code == missing.status_code == 403
    assert refused.json() == missing.json()
    assert refused.json()["code"] == "identity.company_forbidden"


def test_a_signed_in_user_without_the_permission_is_refused(
    client: TestClient, session: Session, bystander: Person, company: Company, reader_role
) -> None:
    """R9.AC6 and R14 — a role in the company is not the same as the right permission."""
    from app.platform.access.api import grant_role

    grant_role(
        session, user_id=bystander.user_id, company_id=company.id, role_id=reader_role.id
    )
    session.commit()

    sign_in(client, bystander)
    response = client.get(f"/api/v1/companies/{company.id}/accounts")
    assert response.status_code == 403
    assert response.json()["code"] == "identity.permission_denied"


def test_refusals_use_the_usual_problem_shape(
    client: TestClient, administrator: Person, company: Company
) -> None:
    """R14.AC6"""
    sign_in(client, administrator)
    response = client.post(
        f"/api/v1/companies/{company.id}/accounts",
        json={"code": "9000", "name": "Bad", "type": "asset", "subtype": "payable"},
        headers=SAME_ORIGIN,
    )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "coa.invalid_subtype"
    assert set(body) == {"type", "title", "status", "code", "detail"}


def test_writes_still_need_an_accepted_origin(
    client: TestClient, administrator: Person, company: Company
) -> None:
    """The CSRF middleware covers these endpoints too, with no extra work."""
    sign_in(client, administrator)
    response = client.post(
        f"/api/v1/companies/{company.id}/accounts",
        json={"code": "9001", "name": "Blocked", "type": "asset", "subtype": "current_asset"},
        headers={"Origin": "https://evil.example.com"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "identity.csrf_check_failed"
