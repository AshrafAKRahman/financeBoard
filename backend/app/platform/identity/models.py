"""Identity tables. The schema is defined by migration 0002; these mappings must match it
(checked by tests/ledger/test_schema_drift.py).
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, Index, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base

USER_STATES = ("invited", "active", "deactivated")


class AppUser(Base):
    __tablename__ = "app_user"
    __table_args__ = (UniqueConstraint("email"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    email: Mapped[str]
    name: Mapped[str]
    password_hash: Mapped[str | None]
    state: Mapped[str] = mapped_column(server_default="invited")
    email_verified_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class UserSession(Base):
    __tablename__ = "user_session"
    __table_args__ = (
        UniqueConstraint("token_hash"),
        Index("user_session_open", "user_id", postgresql_where=text("ended_at IS NULL")),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("app_user.id"))
    token_hash: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_used_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime]
    ended_at: Mapped[datetime | None]
    user_agent: Mapped[str | None]
    ip: Mapped[str | None] = mapped_column(INET)


class Invitation(Base):
    __tablename__ = "invitation"
    __table_args__ = (
        UniqueConstraint("token_hash"),
        Index(
            "invitation_one_open",
            "user_id",
            unique=True,
            postgresql_where=text(
                "accepted_at IS NULL AND revoked_at IS NULL AND superseded_at IS NULL"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("app_user.id"))
    token_hash: Mapped[str]
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime]
    accepted_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
    superseded_at: Mapped[datetime | None]

    @property
    def is_open(self) -> bool:
        return self.accepted_at is None and self.revoked_at is None and self.superseded_at is None


class LoginAttempt(Base):
    __tablename__ = "login_attempt"
    __table_args__ = (Index("login_attempt_by_email", "email", text("attempted_at DESC")),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    email: Mapped[str]
    attempted_at: Mapped[datetime] = mapped_column(server_default=func.now())
    succeeded: Mapped[bool]
    ip: Mapped[str | None] = mapped_column(INET)
