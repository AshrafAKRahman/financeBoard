"""What every endpoint is handed: a transaction, the caller, and a checked permission."""

from collections.abc import Iterator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import pooled_engine
from app.platform.access.api import Caller, authorize, permissions_for
from app.platform.identity.api import load_session
from app.shared.errors import DomainError


def db_session() -> Iterator[Session]:
    """One transaction per request: committed when the endpoint returns, rolled back on
    any error (including a domain error turned into a problem response)."""
    with Session(pooled_engine(), expire_on_commit=False) as session:
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise


SessionDep = Annotated[Session, Depends(db_session)]


def current_caller(request: Request, session: SessionDep) -> Caller:
    settings = get_settings()
    raw_token = request.cookies.get(settings.session_cookie_name)
    if not raw_token:
        raise DomainError("identity.not_authenticated", "sign in to continue")

    loaded = load_session(session, raw_token)
    if loaded is None:
        raise DomainError("identity.session_expired", "your session has ended; sign in again")

    user_session, user = loaded
    return Caller(
        user_id=user.id,
        email=user.email,
        name=user.name,
        permissions=permissions_for(session, user.id),
        session_id=user_session.id,
    )


CallerDep = Annotated[Caller, Depends(current_caller)]


def requires(permission: str):
    """Dependency that enforces the permission the route declared.

    Company-scoped routes check it in the company named in the path; the rest accept the
    permission held in any company, because users and roles are not owned by a company.
    """

    def check(request: Request, caller: CallerDep) -> Caller:
        company_id = request.path_params.get("company_id")
        if company_id is not None:
            authorize(caller, UUID(str(company_id)), permission)
            return caller

        if not any(permission in codes for codes in caller.permissions.values()):
            raise DomainError("identity.permission_denied", f"{permission} is required")
        return caller

    return Depends(check)
