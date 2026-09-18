"""A user reaches exactly the companies they hold a role in (R6)."""

import pytest
from sqlalchemy.orm import Session

from app.platform.access import api as access
from app.platform.access.models import ADMINISTRATOR_ROLE_ID, Role
from app.platform.identity.models import AppUser
from app.platform.tenancy.api import Company
from app.shared.errors import DomainError
from app.shared.ids import uuid7

pytestmark = pytest.mark.db


@pytest.fixture
def two_companies(session: Session) -> tuple[Company, Company]:
    riyadh = Company(id=uuid7(), name="Riyadh Trading", base_currency="SAR")
    jeddah = Company(id=uuid7(), name="Jeddah Logistics", base_currency="SAR")
    session.add_all([riyadh, jeddah])
    session.commit()
    return riyadh, jeddah


@pytest.fixture
def user(session: Session) -> AppUser:
    user = AppUser(
        id=uuid7(),
        email=f"scoped-{uuid7().hex[-8:]}@example.sa",
        name="Scoped",
        state="active",
        password_hash="$argon2id$placeholder",
    )
    session.add(user)
    session.commit()
    return user


@pytest.fixture
def clerk_role(session: Session) -> Role:
    role = Role(id=uuid7(), name=f"Clerk {uuid7().hex[-6:]}")
    session.add(role)
    session.flush()
    access.set_role_permissions(session, role.id, ["user:read"])
    session.commit()
    return role


def caller_for(session: Session, user: AppUser) -> access.Caller:
    return access.Caller(
        user_id=user.id, email=user.email, permissions=access.permissions_for(session, user.id)
    )


def test_a_granted_company_is_reachable(
    session: Session, user: AppUser, two_companies, clerk_role: Role
) -> None:
    """R6.AC1"""
    riyadh, _ = two_companies
    access.grant_role(session, user_id=user.id, company_id=riyadh.id, role_id=clerk_role.id)
    session.commit()

    access.authorize(caller_for(session, user), riyadh.id, "user:read")


def test_a_company_without_a_grant_is_refused(
    session: Session, user: AppUser, two_companies, clerk_role: Role
) -> None:
    """R6.AC2"""
    riyadh, jeddah = two_companies
    access.grant_role(session, user_id=user.id, company_id=riyadh.id, role_id=clerk_role.id)
    session.commit()

    with pytest.raises(DomainError) as error:
        access.authorize(caller_for(session, user), jeddah.id, "user:read")
    assert error.value.code == "identity.company_forbidden"


def test_a_company_that_does_not_exist_is_refused_the_same_way(
    session: Session, user: AppUser, two_companies, clerk_role: Role
) -> None:
    """R6.AC3 — the API must not double as a directory of companies."""
    riyadh, jeddah = two_companies
    access.grant_role(session, user_id=user.id, company_id=riyadh.id, role_id=clerk_role.id)
    session.commit()
    caller = caller_for(session, user)

    with pytest.raises(DomainError) as missing:
        access.authorize(caller, uuid7(), "user:read")
    with pytest.raises(DomainError) as forbidden:
        access.authorize(caller, jeddah.id, "user:read")
    assert str(missing.value) == str(forbidden.value)


def test_a_profile_lists_only_the_users_own_companies(
    session: Session, user: AppUser, two_companies, clerk_role: Role
) -> None:
    """R6.AC4"""
    riyadh = two_companies[0]
    access.grant_role(session, user_id=user.id, company_id=riyadh.id, role_id=clerk_role.id)
    session.commit()

    assert caller_for(session, user).companies == {riyadh.id}


def test_permissions_differ_per_company(
    session: Session, user: AppUser, two_companies, clerk_role: Role
) -> None:
    """R6.AC5 — clerk here, administrator there."""
    riyadh, jeddah = two_companies
    access.grant_role(session, user_id=user.id, company_id=riyadh.id, role_id=clerk_role.id)
    access.grant_role(
        session, user_id=user.id, company_id=jeddah.id, role_id=ADMINISTRATOR_ROLE_ID
    )
    session.commit()
    caller = caller_for(session, user)

    assert caller.may(riyadh.id, "user:read")
    assert not caller.may(riyadh.id, "user:invite")
    assert caller.may(jeddah.id, "user:invite")


def test_revoking_the_last_role_removes_the_company(
    session: Session, user: AppUser, two_companies, clerk_role: Role
) -> None:
    riyadh, _ = two_companies
    access.grant_role(session, user_id=user.id, company_id=riyadh.id, role_id=clerk_role.id)
    session.commit()
    access.revoke_role(session, user_id=user.id, company_id=riyadh.id, role_id=clerk_role.id)
    session.commit()

    assert caller_for(session, user).companies == frozenset()


def test_a_role_with_no_permissions_still_makes_the_company_visible(
    session: Session, user: AppUser, two_companies
) -> None:
    """Being a member with nothing granted is 'permission denied', not 'no such company'."""
    riyadh = two_companies[0]
    empty_role = Role(id=uuid7(), name=f"Observer {uuid7().hex[-6:]}")
    session.add(empty_role)
    session.flush()
    access.grant_role(session, user_id=user.id, company_id=riyadh.id, role_id=empty_role.id)
    session.commit()

    caller = caller_for(session, user)
    assert caller.companies == {riyadh.id}
    with pytest.raises(DomainError) as error:
        access.authorize(caller, riyadh.id, "user:read")
    assert error.value.code == "identity.permission_denied"
