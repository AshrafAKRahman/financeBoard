"""Sign in, sign out, who am I, change my password."""

from fastapi import APIRouter, Request, Response, status

from app.api.cookies import clear_session_cookie, set_session_cookie
from app.api.deps import CallerDep, SessionDep
from app.api.protection import authenticated, public
from app.api.schemas import CompanyAccess, LoginRequest, Me, PasswordChangeRequest
from app.platform.identity.api import (
    authenticate,
    change_password,
    end_session,
    get_user,
    start_session,
)
from app.platform.tenancy.api import Company

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", status_code=status.HTTP_204_NO_CONTENT)
@public
def login(body: LoginRequest, request: Request, response: Response, session: SessionDep) -> None:
    user = authenticate(
        session,
        body.email,
        body.password,
        ip=request.client.host if request.client else None,
    )
    token = start_session(
        session,
        user,
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )
    set_session_cookie(response, token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
@authenticated
def logout(caller: CallerDep, response: Response, session: SessionDep) -> None:
    if caller.session_id is not None:
        end_session(session, caller.session_id)
    clear_session_cookie(response)


@router.get("/me", response_model=Me)
@authenticated
def me(caller: CallerDep, session: SessionDep) -> Me:
    companies = []
    for company_id, permissions in caller.permissions.items():
        company = session.get(Company, company_id)
        companies.append(
            CompanyAccess(
                company_id=company_id,
                name=company.name if company else "",
                permissions=sorted(permissions),
            )
        )
    companies.sort(key=lambda access: access.name)
    return Me(id=caller.user_id, email=caller.email, name=caller.name, companies=companies)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
@authenticated
def change_own_password(
    body: PasswordChangeRequest, caller: CallerDep, session: SessionDep
) -> None:
    user = get_user(session, caller.user_id)
    change_password(
        session,
        user,
        body.current_password,
        body.new_password,
        keep_session_id=caller.session_id,
    )
