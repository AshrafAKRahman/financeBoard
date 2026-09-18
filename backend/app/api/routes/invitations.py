"""Invitations: the only path from "no account" to "signed in"."""

from uuid import UUID

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse

from app.api.cookies import set_session_cookie
from app.api.deps import CallerDep, SessionDep, requires
from app.api.errors import problem
from app.api.protection import needs, public
from app.api.schemas import AcceptInvitationRequest, InvitationOut, InvitationStatus, InviteRequest
from app.platform.audit.api import Actor
from app.platform.identity.api import (
    accept_invitation,
    get_user,
    invite_user,
    open_invitation,
    resend_invitation,
    revoke_invitation,
)

router = APIRouter(prefix="/api/v1/invitations", tags=["invitations"])


def _as_out(session, result) -> InvitationOut:
    user = get_user(session, result.invitation.user_id)
    return InvitationOut(
        id=result.invitation.id,
        user_id=user.id,
        email=user.email,
        expires_at=result.invitation.expires_at,
        email_sent=result.delivery_error is None,
    )


def _respond(session, result, *, status_code: int) -> Response:
    """A relay failure keeps the invitation, so this returns a response rather than
    raising: raising would roll the transaction back (R11.AC10)."""
    body = _as_out(session, result)
    if result.delivery_error is not None:
        return problem(
            "identity.invitation_email_failed",
            f"the invitation was created but could not be emailed: {result.delivery_error}",
        )
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[requires("user:invite")])
@needs("user:invite")
def invite(body: InviteRequest, caller: CallerDep, session: SessionDep) -> Response:
    result = invite_user(
        session,
        email=body.email,
        name=body.name,
        actor=Actor(caller.user_id, caller.email),
    )
    return _respond(session, result, status_code=status.HTTP_201_CREATED)


@router.post("/{invitation_id}/resend", dependencies=[requires("user:invite")])
@needs("user:invite")
def resend(invitation_id: UUID, caller: CallerDep, session: SessionDep) -> Response:
    result = resend_invitation(session, invitation_id, actor=Actor(caller.user_id, caller.email))
    return _respond(session, result, status_code=status.HTTP_200_OK)


@router.post(
    "/{invitation_id}/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[requires("user:invite")],
)
@needs("user:invite")
def revoke(invitation_id: UUID, caller: CallerDep, session: SessionDep) -> None:
    revoke_invitation(session, invitation_id, actor=Actor(caller.user_id, caller.email))


@router.get("/{token}", response_model=InvitationStatus)
@public
def check(token: str, session: SessionDep) -> InvitationStatus:
    """Lets the sign-up screen say "this link has expired" before asking for a password."""
    invitation = open_invitation(session, token)
    user = get_user(session, invitation.user_id)
    return InvitationStatus(status="valid", email=user.email, expires_at=invitation.expires_at)


@router.post("/{token}/accept", status_code=status.HTTP_204_NO_CONTENT)
@public
def accept(
    token: str,
    body: AcceptInvitationRequest,
    request: Request,
    response: Response,
    session: SessionDep,
) -> None:
    _, session_token = accept_invitation(
        session,
        token,
        body.password,
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )
    set_session_cookie(response, session_token)
