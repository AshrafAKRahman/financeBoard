"""Users, role grants, session revocation and the audit log over HTTP (R8.AC5)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.platform.access.models import ADMINISTRATOR_ROLE_ID
from app.platform.tenancy.api import Company
from app.shared.ids import uuid7
from tests.api.conftest import SAME_ORIGIN, Person, sign_in

pytestmark = pytest.mark.db


class TestUsers:
    def test_the_list_shows_users_without_secrets(
        self, client: TestClient, administrator: Person, bystander: Person
    ) -> None:
        sign_in(client, administrator)
        response = client.get("/api/v1/users")

        assert response.status_code == 200
        emails = {user["email"] for user in response.json()}
        assert {administrator.email, bystander.email} <= emails
        assert "password" not in response.text.lower()
        assert "argon2" not in response.text

    def test_reading_users_needs_the_permission(
        self, client: TestClient, bystander: Person
    ) -> None:
        sign_in(client, bystander)
        assert client.get("/api/v1/users").status_code == 403

    def test_deactivating_ends_that_users_sessions(
        self, client: TestClient, administrator: Person, bystander: Person
    ) -> None:
        """R1.AC6 over HTTP."""
        other = TestClient(client.app, base_url=str(client.base_url))
        sign_in(other, bystander)
        assert other.get("/api/v1/auth/me").status_code == 200

        sign_in(client, administrator)
        response = client.post(
            f"/api/v1/users/{bystander.user_id}/deactivate", headers=SAME_ORIGIN
        )
        assert response.status_code == 204
        assert other.get("/api/v1/auth/me").status_code == 401

    def test_sessions_can_be_revoked_without_deactivating(
        self, client: TestClient, administrator: Person, bystander: Person
    ) -> None:
        """R4.AC8"""
        other = TestClient(client.app, base_url=str(client.base_url))
        sign_in(other, bystander)

        sign_in(client, administrator)
        response = client.post(
            f"/api/v1/users/{bystander.user_id}/sessions/revoke", headers=SAME_ORIGIN
        )
        assert response.status_code == 204
        assert other.get("/api/v1/auth/me").status_code == 401

        # Still able to sign in again: the account is intact.
        sign_in(other, bystander)

    def test_deactivating_needs_the_permission(
        self, client: TestClient, bystander: Person, administrator: Person
    ) -> None:
        sign_in(client, bystander)
        response = client.post(
            f"/api/v1/users/{administrator.user_id}/deactivate", headers=SAME_ORIGIN
        )
        assert response.status_code == 403


class TestRoleGrants:
    def test_granting_a_role_gives_access_to_that_company(
        self,
        client: TestClient,
        administrator: Person,
        bystander: Person,
        company: Company,
        reader_role,
    ) -> None:
        sign_in(client, administrator)
        response = client.post(
            f"/api/v1/companies/{company.id}/users/{bystander.user_id}/roles",
            json={"role_id": str(reader_role.id)},
            headers=SAME_ORIGIN,
        )
        assert response.status_code == 204

        other = TestClient(client.app, base_url=str(client.base_url))
        sign_in(other, bystander)
        companies = other.get("/api/v1/auth/me").json()["companies"]
        assert [access["permissions"] for access in companies] == [["user:read"]]

    def test_revoking_takes_it_away(
        self,
        client: TestClient,
        administrator: Person,
        bystander: Person,
        company: Company,
        reader_role,
    ) -> None:
        sign_in(client, administrator)
        client.post(
            f"/api/v1/companies/{company.id}/users/{bystander.user_id}/roles",
            json={"role_id": str(reader_role.id)},
            headers=SAME_ORIGIN,
        )
        response = client.request(
            "DELETE",
            f"/api/v1/companies/{company.id}/users/{bystander.user_id}/roles/{reader_role.id}",
            headers=SAME_ORIGIN,
        )
        assert response.status_code == 204

        other = TestClient(client.app, base_url=str(client.base_url))
        sign_in(other, bystander)
        assert other.get("/api/v1/auth/me").json()["companies"] == []

    def test_the_last_administrator_cannot_be_revoked(
        self, client: TestClient, administrator: Person, company: Company, session: Session
    ) -> None:
        """R5.AC6"""
        from sqlalchemy import text

        session.execute(
            text("DELETE FROM user_company_role WHERE role_id = :role AND user_id <> :user"),
            {"role": ADMINISTRATOR_ROLE_ID, "user": administrator.user_id},
        )
        session.commit()

        sign_in(client, administrator)
        response = client.request(
            "DELETE",
            f"/api/v1/companies/{company.id}/users/{administrator.user_id}"
            f"/roles/{ADMINISTRATOR_ROLE_ID}",
            headers=SAME_ORIGIN,
        )
        assert response.status_code == 409
        assert response.json()["code"] == "identity.last_administrator"

    def test_granting_in_another_company_is_refused(
        self,
        client: TestClient,
        session: Session,
        administrator: Person,
        bystander: Person,
        reader_role,
    ) -> None:
        elsewhere = Company(id=uuid7(), name="Elsewhere", base_currency="SAR")
        session.add(elsewhere)
        session.commit()

        sign_in(client, administrator)
        response = client.post(
            f"/api/v1/companies/{elsewhere.id}/users/{bystander.user_id}/roles",
            json={"role_id": str(reader_role.id)},
            headers=SAME_ORIGIN,
        )
        assert response.status_code == 403
        assert response.json()["code"] == "identity.company_forbidden"


class TestAuditLog:
    def test_the_log_comes_back_newest_first(
        self, client: TestClient, administrator: Person, bystander: Person, company: Company,
        reader_role,
    ) -> None:
        """R8.AC5"""
        sign_in(client, administrator)
        client.post(
            f"/api/v1/companies/{company.id}/users/{bystander.user_id}/roles",
            json={"role_id": str(reader_role.id)},
            headers=SAME_ORIGIN,
        )

        response = client.get(f"/api/v1/companies/{company.id}/audit-log")
        assert response.status_code == 200
        entries = response.json()
        assert entries[0]["action"] == "role.granted"
        assert entries[0]["actor_email"] == administrator.email
        assert entries[0]["target_id"] == str(bystander.user_id)

    def test_reading_the_log_needs_the_permission(
        self, client: TestClient, session: Session, bystander: Person, company: Company,
        reader_role,
    ) -> None:
        from app.platform.access.api import grant_role

        grant_role(
            session, user_id=bystander.user_id, company_id=company.id, role_id=reader_role.id
        )
        session.commit()

        sign_in(client, bystander)
        response = client.get(f"/api/v1/companies/{company.id}/audit-log")
        assert response.status_code == 403
        assert response.json()["code"] == "identity.permission_denied"

    def test_the_log_carries_no_secrets(
        self, client: TestClient, administrator: Person, company: Company
    ) -> None:
        sign_in(client, administrator)
        body = client.get(f"/api/v1/companies/{company.id}/audit-log").text
        assert "argon2" not in body
        assert "sid=" not in body
