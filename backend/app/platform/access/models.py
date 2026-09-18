"""Roles, permissions and grants (migration 0002)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base

ADMINISTRATOR_ROLE_ID = UUID("019a0000-0000-7000-8000-000000000001")
ADMINISTRATOR_ROLE_NAME = "Administrator"


class Permission(Base):
    __tablename__ = "permission"

    code: Mapped[str] = mapped_column(primary_key=True)
    description: Mapped[str]


class Role(Base):
    __tablename__ = "role"
    __table_args__ = (UniqueConstraint("name"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str]
    description: Mapped[str] = mapped_column(server_default="")
    is_system: Mapped[bool] = mapped_column(server_default="false")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class RolePermission(Base):
    __tablename__ = "role_permission"

    role_id: Mapped[UUID] = mapped_column(
        ForeignKey("role.id", ondelete="CASCADE"), primary_key=True
    )
    permission_code: Mapped[str] = mapped_column(ForeignKey("permission.code"), primary_key=True)


class UserCompanyRole(Base):
    __tablename__ = "user_company_role"
    __table_args__ = (Index("user_company_role_by_user", "user_id"),)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("app_user.id"), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(ForeignKey("company.id"), primary_key=True)
    role_id: Mapped[UUID] = mapped_column(ForeignKey("role.id"), primary_key=True)
    granted_at: Mapped[datetime] = mapped_column(server_default=func.now())
    granted_by: Mapped[UUID | None] = mapped_column(ForeignKey("app_user.id"))
