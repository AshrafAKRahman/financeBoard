"""Who may do what, and where.

`permissions_for` answers in one query; everything after that is a pure decision on the
value object, so a request never pays for authorization more than once (NFR4).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.platform.access.models import (
    ADMINISTRATOR_ROLE_ID,
    ADMINISTRATOR_ROLE_NAME,
    Permission,
    Role,
    RolePermission,
    UserCompanyRole,
)
from app.platform.access.permissions import PERMISSIONS
from app.platform.audit.api import Actor, record
from app.shared.errors import DomainError


@dataclass(frozen=True, slots=True)
class Caller:
    """What an endpoint is given: never the ORM user, never a password hash."""

    user_id: UUID
    email: str
    name: str = ""
    permissions: Mapping[UUID, frozenset[str]] = field(default_factory=dict)
    session_id: UUID | None = None

    @property
    def companies(self) -> frozenset[UUID]:
        return frozenset(self.permissions)

    def may(self, company_id: UUID, permission: str) -> bool:
        return permission in self.permissions.get(company_id, frozenset())


def authorize(caller: Caller, company_id: UUID, permission: str) -> None:
    """A company the caller has no role in is refused the same way one that does not
    exist is, so the two cannot be told apart (R6.AC2, R6.AC3)."""
    if company_id not in caller.permissions:
        raise DomainError("identity.company_forbidden", "this company is not available to you")
    if permission not in caller.permissions[company_id]:
        raise DomainError("identity.permission_denied", f"{permission} is required")


def permissions_for(session: Session, user_id: UUID) -> dict[UUID, frozenset[str]]:
    rows = session.execute(
        select(UserCompanyRole.company_id, RolePermission.permission_code)
        .join(RolePermission, RolePermission.role_id == UserCompanyRole.role_id)
        .where(UserCompanyRole.user_id == user_id)
    ).all()

    granted: dict[UUID, set[str]] = {}
    for company_id, permission in rows:
        granted.setdefault(company_id, set()).add(permission)
    # A company with a role but no permissions still counts as reachable.
    for company_id in session.execute(
        select(UserCompanyRole.company_id).where(UserCompanyRole.user_id == user_id)
    ).scalars():
        granted.setdefault(company_id, set())
    return {company: frozenset(codes) for company, codes in granted.items()}


def ensure_catalogue_seeded(session: Session) -> int:
    """Codes in the code are the truth; new ones are added to the table and to the
    Administrator role, so a permission needs no migration."""
    existing = set(session.execute(select(Permission.code)).scalars())
    added = 0
    for code, description in PERMISSIONS.items():
        if code not in existing:
            session.add(Permission(code=code, description=description))
            added += 1
    session.flush()

    administrator = get_role_by_name(session, ADMINISTRATOR_ROLE_NAME)
    held = set(
        session.execute(
            select(RolePermission.permission_code).where(RolePermission.role_id == administrator.id)
        ).scalars()
    )
    for code in PERMISSIONS:
        if code not in held:
            session.add(RolePermission(role_id=administrator.id, permission_code=code))
    session.flush()
    return added


def get_role_by_name(session: Session, name: str) -> Role:
    role = session.execute(select(Role).where(Role.name == name)).scalar_one_or_none()
    if role is None:
        raise DomainError("identity.role_not_found", f"role {name!r} not found")
    return role


def get_role(session: Session, role_id: UUID) -> Role:
    role = session.get(Role, role_id)
    if role is None:
        raise DomainError("identity.role_not_found", f"role {role_id} not found")
    return role


def role_permissions(session: Session, role_id: UUID) -> frozenset[str]:
    return frozenset(
        session.execute(
            select(RolePermission.permission_code).where(RolePermission.role_id == role_id)
        ).scalars()
    )


def grant_role(
    session: Session,
    *,
    user_id: UUID,
    company_id: UUID,
    role_id: UUID,
    actor: Actor | None = None,
) -> UserCompanyRole:
    role = get_role(session, role_id)
    existing = session.get(UserCompanyRole, (user_id, company_id, role_id))
    if existing is not None:
        return existing

    grant = UserCompanyRole(
        user_id=user_id,
        company_id=company_id,
        role_id=role_id,
        granted_by=actor.user_id if actor else None,
    )
    session.add(grant)
    session.flush()
    record(
        session,
        action="role.granted",
        actor=actor,
        company_id=company_id,
        target_type="user",
        target_id=user_id,
        detail={"role": role.name},
    )
    return grant


def revoke_role(
    session: Session,
    *,
    user_id: UUID,
    company_id: UUID,
    role_id: UUID,
    actor: Actor | None = None,
) -> None:
    role = get_role(session, role_id)
    grant = session.get(UserCompanyRole, (user_id, company_id, role_id))
    if grant is None:
        return

    if role_id == ADMINISTRATOR_ROLE_ID and _administrator_grants(session) <= 1:
        raise DomainError(
            "identity.last_administrator",
            "this is the last administrator; grant another before revoking",
        )

    session.delete(grant)
    session.flush()
    record(
        session,
        action="role.revoked",
        actor=actor,
        company_id=company_id,
        target_type="user",
        target_id=user_id,
        detail={"role": role.name},
    )


def set_role_permissions(
    session: Session, role_id: UUID, codes: Iterable[str], *, actor: Actor | None = None
) -> frozenset[str]:
    role = get_role(session, role_id)
    wanted = frozenset(codes)
    unknown = wanted - frozenset(PERMISSIONS)
    if unknown:
        raise DomainError(
            "identity.permission_not_found", f"unknown permissions: {', '.join(sorted(unknown))}"
        )

    session.execute(delete(RolePermission).where(RolePermission.role_id == role_id))
    for code in sorted(wanted):
        session.add(RolePermission(role_id=role_id, permission_code=code))
    session.flush()
    record(
        session,
        action="role.permissions_changed",
        actor=actor,
        target_type="role",
        target_id=role_id,
        detail={"role": role.name, "permissions": sorted(wanted)},
    )
    return wanted


def _administrator_grants(session: Session) -> int:
    return (
        session.execute(
            select(func.count())
            .select_from(UserCompanyRole)
            .where(UserCompanyRole.role_id == ADMINISTRATOR_ROLE_ID)
        ).scalar_one()
        or 0
    )
