"""The first administrator on a fresh system (R9)."""

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.cli import bootstrap_admin
from app.platform.access.api import permissions_for
from app.platform.access.permissions import CODES
from app.platform.identity import api as identity
from app.platform.tenancy.api import Company
from app.shared.errors import DomainError
from app.shared.ids import uuid7
from tests.conftest import migrate

pytestmark = pytest.mark.db


@pytest.fixture
def fresh_database(scratch_database: Engine) -> Engine:
    """A system with no users at all — which is the only state bootstrap works in."""
    with scratch_database.begin() as connection:
        migrate(connection)
    return scratch_database


@pytest.fixture
def fresh_session(fresh_database: Engine):
    with Session(fresh_database, expire_on_commit=False) as session:
        yield session


def test_the_first_administrator_is_created_and_can_sign_in(fresh_session: Session) -> None:
    """R9.AC1"""
    company = Company(id=uuid7(), name="Riyadh Trading", base_currency="SAR")
    fresh_session.add(company)
    fresh_session.flush()

    result = bootstrap_admin(
        fresh_session, email="Owner@Example.SA ", password="a-long-enough-password"
    )
    fresh_session.commit()

    assert result.email == "owner@example.sa"
    assert result.generated_password is None

    user = identity.authenticate(fresh_session, "owner@example.sa", "a-long-enough-password")
    fresh_session.commit()
    assert user.state == "active"
    assert user.email_verified_at is not None


def test_the_administrator_gets_every_permission_in_every_company(
    fresh_session: Session,
) -> None:
    riyadh = Company(id=uuid7(), name="Riyadh", base_currency="SAR")
    jeddah = Company(id=uuid7(), name="Jeddah", base_currency="SAR")
    fresh_session.add_all([riyadh, jeddah])
    fresh_session.flush()

    result = bootstrap_admin(
        fresh_session, email="owner@example.sa", password="a-long-enough-password"
    )
    fresh_session.commit()

    granted = permissions_for(fresh_session, result.user_id)
    assert set(granted) == {riyadh.id, jeddah.id}
    assert all(codes == frozenset(CODES) for codes in granted.values())


def test_a_password_is_generated_and_shown_once(fresh_session: Session) -> None:
    """R9.AC3"""
    result = bootstrap_admin(fresh_session, email="owner@example.sa")
    fresh_session.commit()

    assert result.generated_password
    assert len(result.generated_password) >= 12
    assert identity.authenticate(
        fresh_session, "owner@example.sa", result.generated_password
    )
    fresh_session.commit()


def test_running_it_twice_is_refused(fresh_session: Session) -> None:
    """R9.AC2"""
    bootstrap_admin(fresh_session, email="owner@example.sa", password="a-long-enough-password")
    fresh_session.commit()

    with pytest.raises(DomainError) as error:
        bootstrap_admin(fresh_session, email="second@example.sa", password="another-password-x")
    assert error.value.code == "identity.already_bootstrapped"
    fresh_session.rollback()


def test_the_password_never_reaches_the_audit_log(fresh_session: Session) -> None:
    """R9.AC4"""
    result = bootstrap_admin(fresh_session, email="owner@example.sa")
    fresh_session.commit()

    logged = fresh_session.execute(text("SELECT detail::text FROM audit_log")).scalars().all()
    assert logged
    assert all(result.generated_password not in row for row in logged)
    assert any(action == "system.bootstrapped" for action in fresh_session.execute(
        text("SELECT action FROM audit_log")
    ).scalars())


def test_a_short_password_is_refused(fresh_session: Session) -> None:
    with pytest.raises(DomainError) as error:
        bootstrap_admin(fresh_session, email="owner@example.sa", password="short")
    assert error.value.code == "identity.weak_password"
    fresh_session.rollback()


def test_an_invalid_address_is_refused(fresh_session: Session) -> None:
    with pytest.raises(DomainError) as error:
        bootstrap_admin(fresh_session, email="not-an-address", password="a-long-enough-password")
    assert error.value.code == "identity.invalid_email"
    fresh_session.rollback()
