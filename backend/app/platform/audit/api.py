"""Append-only security log.

The table refuses UPDATE and DELETE (migration 0002), and this writer refuses to store
anything that looks like a secret, so the log can be read by anyone with `audit:read`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.platform.audit.models import AuditLog
from app.shared.errors import DomainError
from app.shared.ids import uuid7

# Substrings that must never appear in a detail key (R8.AC4, R11.AC12).
DENIED_KEY_PARTS = ("password", "token", "secret", "hash", "credential")


@dataclass(frozen=True, slots=True)
class Actor:
    """Who did it. Both fields are empty for actions with no signed-in user (a failed login)."""

    user_id: UUID | None = None
    email: str | None = None


def _check_detail(detail: dict[str, Any]) -> None:
    for key, value in detail.items():
        lowered = key.lower()
        if any(part in lowered for part in DENIED_KEY_PARTS):
            raise DomainError("audit.secret_in_detail", f"audit detail must not carry {key!r}")
        if isinstance(value, dict):
            _check_detail(value)


def record(
    session: Session,
    *,
    action: str,
    actor: Actor | None = None,
    company_id: UUID | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    detail = detail or {}
    _check_detail(detail)
    actor = actor or Actor()

    entry = AuditLog(
        id=uuid7(),
        actor_user_id=actor.user_id,
        actor_email=actor.email,
        company_id=company_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        detail=detail,
    )
    session.add(entry)
    session.flush()
    return entry


def read_company_log(
    session: Session,
    company_id: UUID,
    *,
    limit: int = 50,
    before: datetime | None = None,
) -> Sequence[AuditLog]:
    """Newest first, oldest last (R8.AC5)."""
    query = select(AuditLog).where(AuditLog.company_id == company_id)
    if before is not None:
        query = query.where(AuditLog.at < before)
    query = query.order_by(AuditLog.at.desc(), AuditLog.id.desc()).limit(min(limit, 200))
    return session.execute(query).scalars().all()
