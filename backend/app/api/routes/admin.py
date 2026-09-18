"""Users, role grants and the audit log."""

from uuid import UUID

from fastapi import APIRouter, status
from sqlalchemy import select

from app.api.deps import CallerDep, SessionDep, requires
from app.api.protection import needs
from app.api.schemas import AuditEntryOut, GrantRoleRequest, UserOut
from app.platform.access.api import grant_role, revoke_role
from app.platform.audit.api import Actor, read_company_log
from app.platform.identity.api import deactivate_user, end_all_sessions, get_user
from app.platform.identity.models import AppUser

router = APIRouter(prefix="/api/v1", tags=["administration"])


@router.get("/users", response_model=list[UserOut], dependencies=[requires("user:read")])
@needs("user:read")
def list_users(session: SessionDep) -> list[AppUser]:
    return list(session.execute(select(AppUser).order_by(AppUser.email)).scalars().all())


@router.post(
    "/users/{user_id}/deactivate",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[requires("user:manage")],
)
@needs("user:manage")
def deactivate(user_id: UUID, caller: CallerDep, session: SessionDep) -> None:
    deactivate_user(session, user_id, actor=Actor(caller.user_id, caller.email))


@router.post(
    "/users/{user_id}/sessions/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[requires("user:manage")],
)
@needs("user:manage")
def revoke_sessions(user_id: UUID, caller: CallerDep, session: SessionDep) -> None:
    user = get_user(session, user_id)
    end_all_sessions(session, user.id)


@router.post(
    "/companies/{company_id}/users/{user_id}/roles",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[requires("role:grant")],
)
@needs("role:grant")
def grant(
    company_id: UUID,
    user_id: UUID,
    body: GrantRoleRequest,
    caller: CallerDep,
    session: SessionDep,
) -> None:
    get_user(session, user_id)
    grant_role(
        session,
        user_id=user_id,
        company_id=company_id,
        role_id=body.role_id,
        actor=Actor(caller.user_id, caller.email),
    )


@router.delete(
    "/companies/{company_id}/users/{user_id}/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[requires("role:grant")],
)
@needs("role:grant")
def revoke(
    company_id: UUID, user_id: UUID, role_id: UUID, caller: CallerDep, session: SessionDep
) -> None:
    revoke_role(
        session,
        user_id=user_id,
        company_id=company_id,
        role_id=role_id,
        actor=Actor(caller.user_id, caller.email),
    )


@router.get(
    "/companies/{company_id}/audit-log",
    response_model=list[AuditEntryOut],
    dependencies=[requires("audit:read")],
)
@needs("audit:read")
def audit_log(company_id: UUID, session: SessionDep, limit: int = 50) -> list:
    return list(read_company_log(session, company_id, limit=limit))
