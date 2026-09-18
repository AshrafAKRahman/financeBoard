"""Login, logout, profile and password change over HTTP (R2.AC2, R3, R10)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.platform.access.api import grant_role
from app.platform.access.models import ADMINISTRATOR_ROLE_ID
from app.platform.tenancy.api import Company
from tests.api.conftest import PASSWORD, Person, sign_in

pytestmark = pytest.mark.db

NEW_PASSWORD = "an-even-longer-password"


class TestLogin:
    def test_correct_credentials_set_a_session_cookie(
        self, client: TestClient, administrator: Person
    ) -> None:
        """R3.AC1"""
        response = client.post(
            "/api/v1/auth/login",
            json={"email": administrator.email, "password": PASSWORD},
            headers={"Origin": str(client.base_url)},
        )

        assert response.status_code == 204
        cookie = response.headers["set-cookie"]
        assert "sid=" in cookie
        assert "HttpOnly" in cookie
        assert "SameSite=lax" in cookie.replace("samesite", "SameSite")

    def test_the_cookie_is_marked_secure_when_configured(
        self, client: TestClient, administrator: Person
    ) -> None:
        from app.config import get_settings

        settings = get_settings()
        settings.session_cookie_secure = True
        try:
            response = client.post(
                "/api/v1/auth/login",
                json={"email": administrator.email, "password": PASSWORD},
                headers={"Origin": str(client.base_url)},
            )
        finally:
            settings.session_cookie_secure = False
        assert "Secure" in response.headers["set-cookie"]

    @pytest.mark.parametrize("password", ["wrong-password-here", ""])
    def test_a_wrong_password_is_refused(
        self, client: TestClient, administrator: Person, password: str
    ) -> None:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": administrator.email, "password": password},
            headers={"Origin": str(client.base_url)},
        )
        assert response.status_code == 401
        assert response.json()["code"] == "identity.invalid_credentials"
        assert "set-cookie" not in response.headers

    def test_an_unknown_address_looks_identical(
        self, client: TestClient, administrator: Person
    ) -> None:
        """R3.AC3"""
        wrong = client.post(
            "/api/v1/auth/login",
            json={"email": administrator.email, "password": "wrong-password-here"},
            headers={"Origin": str(client.base_url)},
        )
        unknown = client.post(
            "/api/v1/auth/login",
            json={"email": "nobody-here@example.sa", "password": PASSWORD},
            headers={"Origin": str(client.base_url)},
        )
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json() == unknown.json()


class TestSessionCookie:
    def test_a_signed_in_caller_reaches_a_protected_endpoint(
        self, client: TestClient, administrator: Person
    ) -> None:
        sign_in(client, administrator)
        assert client.get("/api/v1/auth/me").status_code == 200

    def test_logging_out_ends_the_session(self, client: TestClient, administrator: Person) -> None:
        """R3.AC7"""
        sign_in(client, administrator)
        logout = client.post("/api/v1/auth/logout", headers={"Origin": str(client.base_url)})
        assert logout.status_code == 204
        assert client.get("/api/v1/auth/me").status_code == 401

    def test_a_tampered_cookie_is_refused(self, client: TestClient, administrator: Person) -> None:
        sign_in(client, administrator)
        client.cookies.set("sid", "not-a-real-session-token")
        response = client.get("/api/v1/auth/me")
        assert response.status_code == 401
        assert response.json()["code"] == "identity.session_expired"


class TestProfile:
    def test_the_profile_describes_the_caller_and_their_companies(
        self, client: TestClient, administrator: Person, company: Company
    ) -> None:
        """R10.AC1"""
        sign_in(client, administrator)
        body = client.get("/api/v1/auth/me").json()

        assert body["email"] == administrator.email
        assert body["name"] == "Admin"
        assert len(body["companies"]) == 1
        access = body["companies"][0]
        assert access["company_id"] == str(company.id)
        assert access["name"] == "Riyadh Trading"
        assert "user:invite" in access["permissions"]

    def test_the_profile_shows_only_companies_the_user_belongs_to(
        self,
        client: TestClient,
        session: Session,
        administrator: Person,
        company: Company,
    ) -> None:
        """R6.AC4"""
        from app.shared.ids import uuid7

        other = Company(id=uuid7(), name="Not Yours", base_currency="SAR")
        session.add(other)
        session.commit()

        sign_in(client, administrator)
        names = [access["name"] for access in client.get("/api/v1/auth/me").json()["companies"]]
        assert names == ["Riyadh Trading"]

    def test_the_profile_carries_no_secrets(
        self, client: TestClient, administrator: Person
    ) -> None:
        """R10.AC3"""
        sign_in(client, administrator)
        body = client.get("/api/v1/auth/me").text
        assert "argon2" not in body
        assert "password" not in body.lower()
        assert "token" not in body.lower()

    def test_signing_in_is_required(self, client: TestClient) -> None:
        """R10.AC2"""
        response = client.get("/api/v1/auth/me")
        assert response.status_code == 401
        assert response.json()["code"] == "identity.not_authenticated"

    def test_two_companies_are_both_listed(
        self,
        client: TestClient,
        session: Session,
        administrator: Person,
        company: Company,
    ) -> None:
        from app.shared.ids import uuid7

        jeddah = Company(id=uuid7(), name="Jeddah Logistics", base_currency="SAR")
        session.add(jeddah)
        session.flush()
        grant_role(
            session,
            user_id=administrator.user_id,
            company_id=jeddah.id,
            role_id=ADMINISTRATOR_ROLE_ID,
        )
        session.commit()

        sign_in(client, administrator)
        names = [access["name"] for access in client.get("/api/v1/auth/me").json()["companies"]]
        assert names == ["Jeddah Logistics", "Riyadh Trading"]


class TestPasswordChange:
    def test_a_user_can_change_their_own_password(
        self, client: TestClient, administrator: Person
    ) -> None:
        sign_in(client, administrator)
        response = client.post(
            "/api/v1/auth/password",
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
            headers={"Origin": str(client.base_url)},
        )
        assert response.status_code == 204

        client.cookies.clear()
        administrator.password = NEW_PASSWORD
        sign_in(client, administrator)

    def test_the_current_password_is_required(
        self, client: TestClient, administrator: Person
    ) -> None:
        sign_in(client, administrator)
        response = client.post(
            "/api/v1/auth/password",
            json={"current_password": "not-it-at-all", "new_password": NEW_PASSWORD},
            headers={"Origin": str(client.base_url)},
        )
        assert response.status_code == 401
        assert response.json()["code"] == "identity.invalid_credentials"

    def test_a_short_new_password_is_refused(
        self, client: TestClient, administrator: Person
    ) -> None:
        sign_in(client, administrator)
        response = client.post(
            "/api/v1/auth/password",
            json={"current_password": PASSWORD, "new_password": "short"},
            headers={"Origin": str(client.base_url)},
        )
        assert response.status_code == 422
        assert response.json()["code"] == "identity.weak_password"
