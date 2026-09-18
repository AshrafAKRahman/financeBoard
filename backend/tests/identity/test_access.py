"""Roles, grants and the permission catalogue against the database (R5)."""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.platform.access import api as access
from app.platform.access.models import (
    ADMINISTRATOR_ROLE_ID,
    ADMINISTRATOR_ROLE_NAME,
    Role,
    UserCompanyRole,
)
from app.platform.access.permissions import CODES
from app.platform.audit.api import Actor
from app.platform.identity.models import AppUser
from app.platform.tenancy.api import Company
from app.shared.errors import DomainError
from app.shared.ids import uuid7

pytestmark = pytest.mark.db


@pytest.fixture
def company(session: Session) -> Company:
    company = Company(id=uuid7(), name="Grants Co", base_currency="SAR")
    session.add(company)
    session.commit()
    return company


@pytest.fixture
def user(session: Session) -> AppUser:
    user = AppUser(
        id=uuid7(),
        email=f"grantee-{uuid7().hex[-8:]}@example.sa",
        name="Grantee",
        state="active",
        password_hash="$argon2id$placeholder",
    )
    session.add(user)
    session.commit()
    return user


@pytest.fixture
def reader_role(session: Session) -> Role:
    role = Role(id=uuid7(), name=f"Reader {uuid7().hex[-6:]}", description="Read only")
    session.add(role)
    session.flush()
    access.set_role_permissions(session, role.id, ["user:read"])
    session.commit()
    return role


def test_a_grant_gives_its_permissions_in_that_company_only(
    session: Session, user: AppUser, company: Company, reader_role: Role
) -> None:
    """R5.AC2"""
    other = Company(id=uuid7(), name="Other Co", base_currency="SAR")
    session.add(other)
    access.grant_role(session, user_id=user.id, company_id=company.id, role_id=reader_role.id)
    session.commit()

    permissions = access.permissions_for(session, user.id)
    assert permissions == {company.id: frozenset({"user:read"})}
    assert other.id not in permissions


def test_grants_from_several_roles_add_up(
    session: Session, user: AppUser, company: Company, reader_role: Role
) -> None:
    access.grant_role(session, user_id=user.id, company_id=company.id, role_id=reader_role.id)
    access.grant_role(
        session, user_id=user.id, company_id=company.id, role_id=ADMINISTRATOR_ROLE_ID
    )
    session.commit()

    assert access.permissions_for(session, user.id)[company.id] == frozenset(CODES)


def test_granting_twice_changes_nothing(
    session: Session, user: AppUser, company: Company, reader_role: Role
) -> None:
    access.grant_role(session, user_id=user.id, company_id=company.id, role_id=reader_role.id)
    access.grant_role(session, user_id=user.id, company_id=company.id, role_id=reader_role.id)
    session.commit()

    count = session.execute(
        text("SELECT count(*) FROM user_company_role WHERE user_id = :u"), {"u": user.id}
    ).scalar_one()
    assert count == 1


def test_revoking_takes_the_permissions_away(
    session: Session, user: AppUser, company: Company, reader_role: Role
) -> None:
    """R5.AC4"""
    access.grant_role(session, user_id=user.id, company_id=company.id, role_id=reader_role.id)
    session.commit()
    access.revoke_role(session, user_id=user.id, company_id=company.id, role_id=reader_role.id)
    session.commit()

    assert access.permissions_for(session, user.id) == {}
    assert session.get(UserCompanyRole, (user.id, company.id, reader_role.id)) is None


def test_an_unknown_role_is_reported(
    session: Session, user: AppUser, company: Company
) -> None:
    """R5.AC5"""
    with pytest.raises(DomainError) as error:
        access.grant_role(
            session, user_id=user.id, company_id=company.id, role_id=uuid7()
        )
    assert error.value.code == "identity.role_not_found"
    session.rollback()


def test_the_last_administrator_cannot_be_revoked(
    session: Session, user: AppUser, company: Company
) -> None:
    """R5.AC6"""
    session.execute(text("DELETE FROM user_company_role WHERE role_id = :r"),
                    {"r": ADMINISTRATOR_ROLE_ID})
    access.grant_role(
        session, user_id=user.id, company_id=company.id, role_id=ADMINISTRATOR_ROLE_ID
    )
    session.commit()

    with pytest.raises(DomainError) as error:
        access.revoke_role(
            session, user_id=user.id, company_id=company.id, role_id=ADMINISTRATOR_ROLE_ID
        )
    assert error.value.code == "identity.last_administrator"
    session.rollback()


def test_an_administrator_can_be_revoked_while_another_remains(
    session: Session, user: AppUser, company: Company
) -> None:
    second = AppUser(
        id=uuid7(),
        email=f"admin2-{uuid7().hex[-8:]}@example.sa",
        name="Second Admin",
        state="active",
        password_hash="$argon2id$placeholder",
    )
    session.add(second)
    session.flush()
    for holder in (user, second):
        access.grant_role(
            session, user_id=holder.id, company_id=company.id, role_id=ADMINISTRATOR_ROLE_ID
        )
    session.commit()

    access.revoke_role(
        session, user_id=user.id, company_id=company.id, role_id=ADMINISTRATOR_ROLE_ID
    )
    session.commit()
    assert access.permissions_for(session, user.id) == {}
    assert access.permissions_for(session, second.id)[company.id] == frozenset(CODES)


def test_changing_a_roles_permissions_is_recorded(
    session: Session, reader_role: Role
) -> None:
    """R5.AC7"""
    access.set_role_permissions(
        session, reader_role.id, ["user:read", "audit:read"], actor=Actor(email="admin@example.sa")
    )
    session.commit()

    assert access.role_permissions(session, reader_role.id) == frozenset(
        {"user:read", "audit:read"}
    )
    actions = (
        session.execute(
            text("SELECT action FROM audit_log WHERE target_id = :id ORDER BY at DESC LIMIT 1"),
            {"id": str(reader_role.id)},
        )
        .scalars()
        .all()
    )
    assert actions == ["role.permissions_changed"]


def test_a_role_cannot_be_given_a_permission_that_does_not_exist(
    session: Session, reader_role: Role
) -> None:
    with pytest.raises(DomainError) as error:
        access.set_role_permissions(session, reader_role.id, ["user:read", "made:up"])
    assert error.value.code == "identity.permission_not_found"
    session.rollback()


def test_grants_and_revocations_are_audited(
    session: Session, user: AppUser, company: Company, reader_role: Role
) -> None:
    actor = Actor(email="admin@example.sa")
    access.grant_role(
        session, user_id=user.id, company_id=company.id, role_id=reader_role.id, actor=actor
    )
    access.revoke_role(
        session, user_id=user.id, company_id=company.id, role_id=reader_role.id, actor=actor
    )
    session.commit()

    actions = (
        session.execute(
            text("SELECT action FROM audit_log WHERE target_id = :id ORDER BY at"),
            {"id": str(user.id)},
        )
        .scalars()
        .all()
    )
    assert actions == ["role.granted", "role.revoked"]


class TestCatalogue:
    def test_the_administrator_role_ships_with_every_permission(self, session: Session) -> None:
        """R5.AC8"""
        administrator = access.get_role_by_name(session, ADMINISTRATOR_ROLE_NAME)
        assert access.role_permissions(session, administrator.id) == frozenset(CODES)

    def test_seeding_is_idempotent(self, session: Session) -> None:
        assert access.ensure_catalogue_seeded(session) == 0
        session.commit()

    def test_a_new_code_is_added_and_granted_to_the_administrator(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A permission added in code needs no migration.

        The code has to be one no migration has seeded, or there is nothing to add.
        """
        invented = "widget:polish"
        monkeypatch.setitem(access.PERMISSIONS, invented, "Polish widgets")

        assert access.ensure_catalogue_seeded(session) == 1
        session.commit()

        administrator = access.get_role_by_name(session, ADMINISTRATOR_ROLE_NAME)
        assert invented in access.role_permissions(session, administrator.id)

        session.execute(
            text("DELETE FROM role_permission WHERE permission_code = :code"),
            {"code": invented},
        )
        session.execute(text("DELETE FROM permission WHERE code = :code"), {"code": invented})
        session.commit()
