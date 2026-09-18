"""Users, invitations, authentication and sessions.

Nobody but an account's owner ever chooses its password: an administrator invites an
address, and the invitation link is the only way a password is first set (R1.AC10).

Services never commit — the caller owns the transaction, as in the ledger.
"""

import ipaddress
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.platform.audit.api import Actor, record
from app.platform.identity import passwords, tokens
from app.platform.identity.models import AppUser, Invitation, LoginAttempt, UserSession
from app.platform.mail.api import (
    MailDeliveryError,
    Mailer,
    get_mailer,
    invitation_link,
    render_invitation,
)
from app.shared.errors import DomainError
from app.shared.ids import uuid7

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")
ATTEMPT_RETENTION = timedelta(days=1)


@dataclass(frozen=True, slots=True)
class SessionToken:
    """The only time a session secret exists outside the browser."""

    raw: str
    session_id: UUID
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class InvitationResult:
    invitation: Invitation
    link: str
    delivery_error: str | None = None


def now() -> datetime:
    return datetime.now(UTC)


def clean_ip(value: str | None) -> str | None:
    """The column is `inet`; anything that is not an address is simply not recorded."""
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if not EMAIL_PATTERN.fullmatch(normalized):
        raise DomainError("identity.invalid_email", f"{email!r} is not an email address")
    return normalized


def get_user_by_email(session: Session, email: str) -> AppUser | None:
    return session.execute(
        select(AppUser).where(AppUser.email == email.strip().lower())
    ).scalar_one_or_none()


def get_user(session: Session, user_id: UUID) -> AppUser:
    user = session.get(AppUser, user_id)
    if user is None:
        raise DomainError("identity.user_not_found", f"user {user_id} not found")
    return user


# --------------------------------------------------------------------------- invitations


def invite_user(
    session: Session,
    *,
    email: str,
    name: str,
    actor: Actor | None = None,
    mailer: Mailer | None = None,
) -> InvitationResult:
    address = normalize_email(email)
    if not name.strip():
        raise DomainError("identity.missing_name", "a name is required")
    if get_user_by_email(session, address) is not None:
        raise DomainError("identity.duplicate_email", f"{address} already has an account")

    user = AppUser(id=uuid7(), email=address, name=name.strip(), state="invited")
    session.add(user)
    session.flush()
    return _issue_invitation(session, user, actor=actor, mailer=mailer, action="invitation.sent")


def resend_invitation(
    session: Session,
    invitation_id: UUID,
    *,
    actor: Actor | None = None,
    mailer: Mailer | None = None,
) -> InvitationResult:
    invitation = session.get(Invitation, invitation_id)
    if invitation is None:
        raise DomainError("identity.invitation_invalid", "invitation not found")
    if invitation.accepted_at is not None:
        raise DomainError("identity.invitation_used", "invitation has already been accepted")

    invitation.superseded_at = now()
    session.flush()
    user = get_user(session, invitation.user_id)
    return _issue_invitation(session, user, actor=actor, mailer=mailer, action="invitation.resent")


def revoke_invitation(
    session: Session, invitation_id: UUID, *, actor: Actor | None = None
) -> Invitation:
    invitation = session.get(Invitation, invitation_id)
    if invitation is None:
        raise DomainError("identity.invitation_invalid", "invitation not found")
    if invitation.accepted_at is not None:
        raise DomainError("identity.invitation_used", "invitation has already been accepted")

    invitation.revoked_at = now()
    session.flush()
    record(
        session,
        action="invitation.revoked",
        actor=actor,
        target_type="user",
        target_id=invitation.user_id,
        detail={"email": get_user(session, invitation.user_id).email},
    )
    return invitation


def open_invitation(session: Session, raw_token: str) -> Invitation:
    """Find a usable invitation, or say precisely why it is not (R11.AC5-AC7)."""
    invitation = session.execute(
        select(Invitation).where(Invitation.token_hash == tokens.token_hash(raw_token))
    ).scalar_one_or_none()
    if invitation is None:
        raise DomainError("identity.invitation_invalid", "this link is not valid")
    if invitation.accepted_at is not None:
        raise DomainError("identity.invitation_used", "this link has already been used")
    if invitation.revoked_at is not None or invitation.superseded_at is not None:
        raise DomainError("identity.invitation_invalid", "this link is no longer valid")
    if invitation.expires_at <= now():
        raise DomainError("identity.invitation_expired", "this link has expired")
    return invitation


def accept_invitation(
    session: Session,
    raw_token: str,
    password: str,
    *,
    user_agent: str | None = None,
    ip: str | None = None,
) -> tuple[AppUser, SessionToken]:
    invitation = open_invitation(session, raw_token)
    user = get_user(session, invitation.user_id)

    user.password_hash = passwords.hash_password(password)
    user.state = "active"
    user.email_verified_at = now()
    user.updated_at = now()
    invitation.accepted_at = now()
    session.flush()

    record(
        session,
        action="invitation.accepted",
        actor=Actor(user.id, user.email),
        target_type="user",
        target_id=user.id,
        detail={"email": user.email},
    )
    return user, start_session(session, user, user_agent=user_agent, ip=ip)


def _issue_invitation(
    session: Session,
    user: AppUser,
    *,
    actor: Actor | None,
    mailer: Mailer | None,
    action: str,
) -> InvitationResult:
    settings = get_settings()
    raw_token = tokens.new_token()
    invitation = Invitation(
        id=uuid7(),
        user_id=user.id,
        token_hash=tokens.token_hash(raw_token),
        created_by=actor.user_id if actor else None,
        expires_at=now() + timedelta(days=settings.invitation_expiry_days),
    )
    session.add(invitation)
    session.flush()

    link = invitation_link(raw_token)
    delivery_error: str | None = None
    try:
        (mailer or get_mailer()).send(
            render_invitation(user.email, user.name, link, invitation.expires_at.date())
        )
    except MailDeliveryError as exc:
        delivery_error = str(exc)

    record(
        session,
        action=action if delivery_error is None else "invitation.email_failed",
        actor=actor,
        target_type="user",
        target_id=user.id,
        # The link and the token are deliberately absent (R11.AC12).
        detail={"email": user.email, "expires_at": invitation.expires_at.isoformat()},
    )
    return InvitationResult(invitation, link, delivery_error)


# ------------------------------------------------------------------------- authentication


def recent_failures(session: Session, email: str) -> int:
    settings = get_settings()
    window_start = now() - timedelta(minutes=settings.login_attempt_window_minutes)
    return (
        session.execute(
            select(func.count())
            .select_from(LoginAttempt)
            .where(
                LoginAttempt.email == email,
                LoginAttempt.succeeded.is_(False),
                LoginAttempt.attempted_at > window_start,
            )
        ).scalar_one()
        or 0
    )


def _record_attempt(session: Session, email: str, *, succeeded: bool, ip: str | None) -> None:
    session.add(LoginAttempt(id=uuid7(), email=email, succeeded=succeeded, ip=clean_ip(ip)))
    if succeeded:
        # A success clears the failure count for that address (R3.AC6).
        session.execute(
            delete(LoginAttempt).where(
                LoginAttempt.email == email, LoginAttempt.succeeded.is_(False)
            )
        )
    else:
        session.execute(
            delete(LoginAttempt).where(LoginAttempt.attempted_at < now() - ATTEMPT_RETENTION)
        )
    session.flush()


def authenticate(session: Session, email: str, password: str, *, ip: str | None = None) -> AppUser:
    """One answer for every failure, and the same work either way (R3.AC3, R3.AC8)."""
    address = email.strip().lower()
    settings = get_settings()

    if recent_failures(session, address) >= settings.login_attempt_limit:
        record(
            session,
            action="login.throttled",
            actor=Actor(email=address),
            detail={"email": address},
        )
        raise DomainError(
            "identity.too_many_attempts", "too many sign-in attempts; try again later"
        )

    user = get_user_by_email(session, address)
    stored_hash = user.password_hash if user else None
    accepted = passwords.verify_password(stored_hash, password) if stored_hash else False
    if stored_hash is None:
        passwords.verify_dummy()

    if user is None or not accepted or user.state != "active":
        _record_attempt(session, address, succeeded=False, ip=ip)
        record(
            session,
            action="login.failed",
            actor=Actor(user.id if user else None, address),
            detail={"email": address},
        )
        raise DomainError("identity.invalid_credentials", "email address or password is wrong")

    if passwords.needs_rehash(stored_hash):
        user.password_hash = passwords.hash_password(password)
        user.updated_at = now()

    _record_attempt(session, address, succeeded=True, ip=ip)
    record(
        session,
        action="login.succeeded",
        actor=Actor(user.id, user.email),
        detail={"email": user.email},
    )
    return user


# ------------------------------------------------------------------------------ sessions


def start_session(
    session: Session, user: AppUser, *, user_agent: str | None = None, ip: str | None = None
) -> SessionToken:
    settings = get_settings()
    raw_token = tokens.new_token()
    expires_at = now() + timedelta(days=settings.session_absolute_days)
    row = UserSession(
        id=uuid7(),
        user_id=user.id,
        token_hash=tokens.token_hash(raw_token),
        expires_at=expires_at,
        user_agent=(user_agent or None),
        ip=clean_ip(ip),
    )
    session.add(row)
    session.flush()
    return SessionToken(raw=raw_token, session_id=row.id, expires_at=expires_at)


def load_session(session: Session, raw_token: str) -> tuple[UserSession, AppUser] | None:
    """The session and its user in one query, or None when it cannot be used."""
    settings = get_settings()
    row = session.execute(
        select(UserSession, AppUser)
        .join(AppUser, AppUser.id == UserSession.user_id)
        .where(UserSession.token_hash == tokens.token_hash(raw_token))
    ).one_or_none()
    if row is None:
        return None

    user_session, user = row
    idle_cutoff = now() - timedelta(hours=settings.session_idle_hours)
    unusable = (
        user_session.ended_at is not None
        or user_session.expires_at <= now()
        or user_session.last_used_at <= idle_cutoff
        or user.state != "active"
    )
    if unusable:
        return None

    user_session.last_used_at = now()
    session.flush()
    return user_session, user


def end_session(session: Session, session_id: UUID) -> None:
    row = session.get(UserSession, session_id)
    if row is not None and row.ended_at is None:
        row.ended_at = now()
        session.flush()


def end_all_sessions(
    session: Session, user_id: UUID, *, except_session_id: UUID | None = None
) -> int:
    rows = (
        session.execute(
            select(UserSession).where(
                UserSession.user_id == user_id, UserSession.ended_at.is_(None)
            )
        )
        .scalars()
        .all()
    )
    ended = 0
    for row in rows:
        if row.id == except_session_id:
            continue
        row.ended_at = now()
        ended += 1
    session.flush()
    return ended


# -------------------------------------------------------------------------- user changes


def change_password(
    session: Session,
    user: AppUser,
    current_password: str,
    new_password: str,
    *,
    keep_session_id: UUID | None = None,
) -> None:
    if not user.password_hash or not passwords.verify_password(
        user.password_hash, current_password
    ):
        raise DomainError("identity.invalid_credentials", "current password is wrong")

    user.password_hash = passwords.hash_password(new_password)
    user.updated_at = now()
    session.flush()
    end_all_sessions(session, user.id, except_session_id=keep_session_id)
    record(
        session,
        action="password.changed",
        actor=Actor(user.id, user.email),
        target_type="user",
        target_id=user.id,
    )


def deactivate_user(session: Session, user_id: UUID, *, actor: Actor | None = None) -> AppUser:
    user = get_user(session, user_id)
    user.state = "deactivated"
    user.updated_at = now()
    session.flush()
    end_all_sessions(session, user.id)
    record(
        session,
        action="user.deactivated",
        actor=actor,
        target_type="user",
        target_id=user.id,
        detail={"email": user.email},
    )
    return user


def delete_user(session: Session, user_id: UUID, *, actor: Actor | None = None) -> None:
    """Only a user who has left no trace can be removed (R1.AC7)."""
    user = get_user(session, user_id)
    referenced = session.execute(
        select(func.count())
        .select_from(_audit_log_table())
        .where(_audit_log_table().c.actor_user_id == user_id)
    ).scalar_one()
    if referenced:
        raise DomainError(
            "identity.user_in_use", "this user appears in the audit log and cannot be deleted"
        )

    session.execute(delete(UserSession).where(UserSession.user_id == user_id))
    session.execute(delete(Invitation).where(Invitation.user_id == user_id))
    session.delete(user)
    session.flush()
    record(session, action="user.deleted", actor=actor, target_type="user", target_id=user_id)


def _audit_log_table():
    from app.platform.audit.models import AuditLog

    return AuditLog.__table__
