"""API tests drive the real app, with the request transaction pointed at the test database."""

from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api import deps
from app.config import get_settings
from app.main import app
from app.platform.access.api import grant_role, set_role_permissions
from app.platform.access.models import ADMINISTRATOR_ROLE_ID, Role
from app.platform.identity import api as identity
from app.platform.mail.api import RecordingMailer
from app.platform.tenancy.api import Company
from app.shared.ids import uuid7

PASSWORD = "a-long-enough-password"
ORIGIN = "http://localhost:5173"
SAME_ORIGIN = {"Origin": ORIGIN}


@dataclass
class Person:
    user_id: UUID
    email: str
    password: str = PASSWORD


@pytest.fixture
def mailer(monkeypatch: pytest.MonkeyPatch) -> RecordingMailer:
    """Invitations are recorded instead of sent, and the link stays reachable in tests."""
    recorder = RecordingMailer()
    monkeypatch.setattr("app.platform.identity.api.get_mailer", lambda: recorder)
    return recorder


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    def test_session() -> Iterator[Session]:
        with Session(engine, expire_on_commit=False) as session:
            try:
                yield session
                session.commit()
            except BaseException:
                session.rollback()
                raise

    app.dependency_overrides[deps.db_session] = test_session
    # The start-up catalogue sync uses this too, so tests never touch the real database.
    app.state.session_factory = lambda: Session(engine, expire_on_commit=False)
    settings = get_settings()
    secure = settings.session_cookie_secure
    settings.session_cookie_secure = False  # the test client speaks http
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as test_client:
        yield test_client
    settings.session_cookie_secure = secure
    app.dependency_overrides.clear()
    app.state.session_factory = None


@pytest.fixture
def company(session: Session) -> Company:
    company = Company(id=uuid7(), name="Riyadh Trading", base_currency="SAR")
    session.add(company)
    session.commit()
    return company


def make_person(
    session: Session, mailer: RecordingMailer, *, name: str = "Test Person"
) -> Person:
    email = f"api-{uuid7().hex[-10:]}@example.sa"
    result = identity.invite_user(session, email=email, name=name, mailer=mailer)
    identity.accept_invitation(session, result.link.rsplit("/", 2)[-2], PASSWORD)
    session.commit()
    user = identity.get_user_by_email(session, email)
    assert user is not None
    return Person(user_id=user.id, email=email)


@pytest.fixture
def administrator(session: Session, mailer: RecordingMailer, company: Company) -> Person:
    person = make_person(session, mailer, name="Admin")
    grant_role(
        session, user_id=person.user_id, company_id=company.id, role_id=ADMINISTRATOR_ROLE_ID
    )
    session.commit()
    return person


@pytest.fixture
def bystander(session: Session, mailer: RecordingMailer) -> Person:
    """Signed in, but holds no role anywhere."""
    return make_person(session, mailer, name="Bystander")


@pytest.fixture
def reader_role(session: Session, company: Company) -> Role:
    role = Role(id=uuid7(), name=f"Reader {uuid7().hex[-6:]}")
    session.add(role)
    session.flush()
    set_role_permissions(session, role.id, ["user:read"])
    session.commit()
    return role


def sign_in(client: TestClient, person: Person) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": person.email, "password": person.password},
        headers=SAME_ORIGIN,
    )
    assert response.status_code == 204, response.text
