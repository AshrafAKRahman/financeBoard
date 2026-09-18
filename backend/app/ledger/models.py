"""Ledger tables. The schema, including every invariant trigger, is defined by the
Alembic migrations; these mappings must match them (checked by tests/ledger/test_schema_drift.py).
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CHAR,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.db import Base

ACCOUNT_TYPES = ("asset", "liability", "equity", "income", "expense")

ACCOUNT_SUBTYPES: dict[str, tuple[str, ...]] = {
    "asset": ("bank_cash", "receivable", "current_asset", "non_current_asset", "prepayment"),
    "liability": ("payable", "current_liability", "non_current_liability"),
    "equity": ("equity", "current_year_earnings"),
    "income": ("income", "other_income"),
    "expense": ("cost_of_revenue", "expense", "depreciation"),
}

JOURNAL_TYPES = ("sales", "purchases", "bank", "cash", "general")


class ExchangeRate(Base):
    __tablename__ = "exchange_rate"
    __table_args__ = (UniqueConstraint("company_id", "currency_code", "rate_date"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(ForeignKey("company.id"))
    currency_code: Mapped[str] = mapped_column(CHAR(3), ForeignKey("currency.code"))
    rate_date: Mapped[date]
    # Company-currency amount for one unit of the foreign currency.
    rate: Mapped[Decimal] = mapped_column(Numeric(24, 12))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Account(Base):
    __tablename__ = "account"
    __table_args__ = (
        UniqueConstraint("company_id", "code"),
        UniqueConstraint("id", "company_id"),
        ForeignKeyConstraint(["parent_id", "company_id"], ["account.id", "account.company_id"]),
        Index("account_tree", "company_id", "parent_id", "code"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(ForeignKey("company.id"))
    code: Mapped[str]
    name: Mapped[str]
    name_ar: Mapped[str | None]
    type: Mapped[str]
    subtype: Mapped[str]
    parent_id: Mapped[UUID | None]
    is_reconcilable: Mapped[bool] = mapped_column(server_default="false")
    is_group: Mapped[bool] = mapped_column(server_default="false")
    cash_flow_tag: Mapped[str | None]
    active: Mapped[bool] = mapped_column(server_default="true")
    x_data: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Journal(Base):
    __tablename__ = "journal"
    __table_args__ = (
        UniqueConstraint("company_id", "code"),
        UniqueConstraint("id", "company_id"),
        ForeignKeyConstraint(
            ["default_account_id", "company_id"], ["account.id", "account.company_id"]
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(ForeignKey("company.id"))
    code: Mapped[str]
    name: Mapped[str]
    type: Mapped[str]
    currency_code: Mapped[str | None] = mapped_column(CHAR(3), ForeignKey("currency.code"))
    default_account_id: Mapped[UUID | None]
    active: Mapped[bool] = mapped_column(server_default="true")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class LedgerSettings(Base):
    __tablename__ = "ledger_settings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["rounding_account_id", "company_id"], ["account.id", "account.company_id"]
        ),
        ForeignKeyConstraint(
            ["fx_gain_account_id", "company_id"], ["account.id", "account.company_id"]
        ),
        ForeignKeyConstraint(
            ["fx_loss_account_id", "company_id"], ["account.id", "account.company_id"]
        ),
        ForeignKeyConstraint(
            ["receivable_account_id", "company_id"],
            ["account.id", "account.company_id"],
            name="ledger_settings_receivable_fkey",
        ),
        ForeignKeyConstraint(
            ["payable_account_id", "company_id"],
            ["account.id", "account.company_id"],
            name="ledger_settings_payable_fkey",
        ),
        ForeignKeyConstraint(
            ["outstanding_receipts_account_id", "company_id"],
            ["account.id", "account.company_id"],
            name="ledger_settings_outstanding_receipts_fkey",
        ),
        ForeignKeyConstraint(
            ["outstanding_payments_account_id", "company_id"],
            ["account.id", "account.company_id"],
            name="ledger_settings_outstanding_payments_fkey",
        ),
        ForeignKeyConstraint(
            ["suspense_account_id", "company_id"],
            ["account.id", "account.company_id"],
            name="ledger_settings_suspense_fkey",
        ),
    )

    company_id: Mapped[UUID] = mapped_column(ForeignKey("company.id"), primary_key=True)
    rounding_account_id: Mapped[UUID | None]
    fx_gain_account_id: Mapped[UUID | None]
    fx_loss_account_id: Mapped[UUID | None]
    # Added by migration 0003 with the chart of accounts.
    receivable_account_id: Mapped[UUID | None]
    payable_account_id: Mapped[UUID | None]
    outstanding_receipts_account_id: Mapped[UUID | None]
    outstanding_payments_account_id: Mapped[UUID | None]
    suspense_account_id: Mapped[UUID | None]


class JournalEntry(Base):
    __tablename__ = "journal_entry"
    __table_args__ = (
        UniqueConstraint("id", "company_id"),
        ForeignKeyConstraint(["journal_id", "company_id"], ["journal.id", "journal.company_id"]),
        ForeignKeyConstraint(
            ["reversed_entry_id", "company_id"],
            ["journal_entry.id", "journal_entry.company_id"],
        ),
        Index(
            "journal_entry_number_uniq",
            "journal_id",
            "number",
            unique=True,
            postgresql_where=text("number IS NOT NULL"),
        ),
        Index(
            "journal_entry_one_reversal",
            "reversed_entry_id",
            unique=True,
            postgresql_where=text("reversed_entry_id IS NOT NULL"),
        ),
        Index(
            "journal_entry_one_per_source",
            "source_type",
            "source_id",
            unique=True,
            postgresql_where=text("source_id IS NOT NULL"),
        ),
        Index("journal_entry_company_date", "company_id", "date"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(ForeignKey("company.id"))
    journal_id: Mapped[UUID]
    number: Mapped[str | None]
    date: Mapped[date]
    ref: Mapped[str | None]
    narration: Mapped[str | None]
    state: Mapped[str] = mapped_column(server_default="draft")
    currency_code: Mapped[str] = mapped_column(CHAR(3), ForeignKey("currency.code"))
    reversed_entry_id: Mapped[UUID | None]
    source_type: Mapped[str | None]
    source_id: Mapped[UUID | None]
    posted_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())

    lines: Mapped[list["JournalEntryLine"]] = relationship(
        back_populates="entry",
        order_by="JournalEntryLine.line_no",
        cascade="all, delete-orphan",
        foreign_keys="[JournalEntryLine.entry_id, JournalEntryLine.company_id]",
        primaryjoin="and_(JournalEntry.id == JournalEntryLine.entry_id, "
        "JournalEntry.company_id == JournalEntryLine.company_id)",
    )


class JournalEntryLine(Base):
    __tablename__ = "journal_entry_line"
    __table_args__ = (
        UniqueConstraint("entry_id", "line_no"),
        ForeignKeyConstraint(
            ["entry_id", "company_id"],
            ["journal_entry.id", "journal_entry.company_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(["account_id", "company_id"], ["account.id", "account.company_id"]),
        Index("journal_entry_line_account", "company_id", "account_id"),
        Index(
            "journal_entry_line_tax_grid",
            "company_id",
            "tax_grid_tag",
            postgresql_where=text("tax_grid_tag IS NOT NULL"),
        ),
        # Open amounts (migration 0005): what a posted line on a reconcilable account still
        # owes or is owed. Maintained by the reconciliation trigger, not by the ORM.
        UniqueConstraint("id", "company_id", name="journal_entry_line_id_company_key"),
        Index(
            "journal_entry_line_open",
            "company_id",
            "account_id",
            "partner_id",
            postgresql_where=text("residual IS NOT NULL AND NOT reconciled"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    entry_id: Mapped[UUID]
    company_id: Mapped[UUID]
    line_no: Mapped[int]
    account_id: Mapped[UUID]
    partner_id: Mapped[UUID | None]
    name: Mapped[str | None]
    debit: Mapped[Decimal] = mapped_column(server_default="0")
    credit: Mapped[Decimal] = mapped_column(server_default="0")
    currency_code: Mapped[str] = mapped_column(CHAR(3), ForeignKey("currency.code"))
    amount_currency: Mapped[Decimal] = mapped_column(server_default="0")
    due_date: Mapped[date | None]
    tax_id: Mapped[UUID | None]
    tax_grid_tag: Mapped[str | None]
    tax_base: Mapped[Decimal | None]
    """What the tax was charged on (migration 0006), so a VAT return needs no documents."""
    x_data: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    residual: Mapped[Decimal | None]
    residual_currency: Mapped[Decimal | None]
    reconciled: Mapped[bool] = mapped_column(server_default="false")

    entry: Mapped[JournalEntry] = relationship(
        back_populates="lines",
        foreign_keys="[JournalEntryLine.entry_id, JournalEntryLine.company_id]",
        primaryjoin="and_(JournalEntry.id == JournalEntryLine.entry_id, "
        "JournalEntry.company_id == JournalEntryLine.company_id)",
    )
