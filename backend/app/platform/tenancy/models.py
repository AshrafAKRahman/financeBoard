from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CHAR, ForeignKey, SmallInteger, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base


class Currency(Base):
    __tablename__ = "currency"

    code: Mapped[str] = mapped_column(CHAR(3), primary_key=True)
    name: Mapped[str]
    decimal_places: Mapped[int] = mapped_column(SmallInteger)
    active: Mapped[bool] = mapped_column(server_default="true")


class Company(Base):
    __tablename__ = "company"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str]
    base_currency: Mapped[str] = mapped_column(CHAR(3), ForeignKey("currency.code"))
    fiscal_year_start_month: Mapped[int] = mapped_column(SmallInteger, server_default="1")
    vat_number: Mapped[str | None]
    cr_number: Mapped[str | None]
    lock_date: Mapped[date | None]
    x_data: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
