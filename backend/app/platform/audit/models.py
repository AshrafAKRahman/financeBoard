"""The append-only audit log (migration 0002; a trigger refuses UPDATE and DELETE)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("audit_log_by_company", "company_id", text("at DESC")),
        Index("audit_log_by_action", "action", text("at DESC")),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(server_default=func.now())
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("app_user.id"))
    actor_email: Mapped[str | None]
    company_id: Mapped[UUID | None] = mapped_column(ForeignKey("company.id"))
    action: Mapped[str]
    target_type: Mapped[str | None]
    target_id: Mapped[str | None]
    detail: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
