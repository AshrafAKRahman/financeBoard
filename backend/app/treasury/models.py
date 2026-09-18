"""Payment, reconciliation and bank statement tables (migration 0005).

Kept in step with the migration by the schema drift test. The open amounts these rows
maintain live on `JournalEntryLine`, because "what is still open" is a fact about the
ledger, not about this module.
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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.db import Base

DIRECTIONS = ("inbound", "outbound")
PAYMENT_STATES = ("draft", "posted", "cancelled")
SOURCE_FORMATS = ("csv", "mt940", "ofx")

# Which company default each direction settles through, and which side of the partner
# account it moves. An inbound payment reduces what a customer owes us.
OUTSTANDING_DEFAULT = {"inbound": "outstanding_receipts", "outbound": "outstanding_payments"}
PARTNER_DEFAULT = {"inbound": "receivable", "outbound": "payable"}
JOURNAL_TYPES = ("bank", "cash")


class Reconciliation(Base):
    """One debit line settling one credit line.

    The two amounts are the same unless the rate moved between the two sides, in which case
    the gap is posted as an exchange difference and linked here as ``fx_entry_id`` (R5.AC4).
    """

    __tablename__ = "reconciliation"
    __table_args__ = (
        ForeignKeyConstraint(
            ["debit_line_id", "company_id"],
            ["journal_entry_line.id", "journal_entry_line.company_id"],
        ),
        ForeignKeyConstraint(
            ["credit_line_id", "company_id"],
            ["journal_entry_line.id", "journal_entry_line.company_id"],
        ),
        ForeignKeyConstraint(
            ["fx_entry_id", "company_id"],
            ["journal_entry.id", "journal_entry.company_id"],
        ),
        Index("reconciliation_by_debit", "debit_line_id"),
        Index("reconciliation_by_credit", "credit_line_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(ForeignKey("company.id"))
    debit_line_id: Mapped[UUID]
    credit_line_id: Mapped[UUID]
    debit_amount: Mapped[Decimal]
    credit_amount: Mapped[Decimal]
    debit_amount_currency: Mapped[Decimal] = mapped_column(server_default="0")
    credit_amount_currency: Mapped[Decimal] = mapped_column(server_default="0")
    fx_entry_id: Mapped[UUID | None]
    matched_at: Mapped[datetime] = mapped_column(server_default=func.now())
    matched_by: Mapped[UUID | None] = mapped_column(ForeignKey("app_user.id"))


class Payment(Base):
    """Money in or out, before anyone says which invoices it settles."""

    __tablename__ = "payment"
    __table_args__ = (
        UniqueConstraint("id", "company_id"),
        ForeignKeyConstraint(["partner_id", "company_id"], ["partner.id", "partner.company_id"]),
        ForeignKeyConstraint(["journal_id", "company_id"], ["journal.id", "journal.company_id"]),
        ForeignKeyConstraint(["withholding_tax_id", "company_id"], ["tax.id", "tax.company_id"]),
        ForeignKeyConstraint(
            ["journal_entry_id", "company_id"],
            ["journal_entry.id", "journal_entry.company_id"],
        ),
        Index(
            "payment_number_uniq",
            "company_id",
            "number",
            unique=True,
            postgresql_where=text("number IS NOT NULL"),
        ),
        Index("payment_by_date", "company_id", text("date DESC")),
        Index("payment_by_partner", "company_id", "partner_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(ForeignKey("company.id"))
    direction: Mapped[str]
    partner_id: Mapped[UUID]
    journal_id: Mapped[UUID]
    number: Mapped[str | None]
    date: Mapped[date]
    amount: Mapped[Decimal]
    currency_code: Mapped[str] = mapped_column(CHAR(3), ForeignKey("currency.code"))
    state: Mapped[str] = mapped_column(server_default="draft")
    withholding_tax_id: Mapped[UUID | None]
    withheld_amount: Mapped[Decimal] = mapped_column(server_default="0")
    reference: Mapped[str | None]
    memo: Mapped[str | None]
    journal_entry_id: Mapped[UUID | None]
    posted_at: Mapped[datetime | None]
    cancelled_at: Mapped[datetime | None]
    cancel_reason: Mapped[str | None]
    x_data: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())

    @property
    def is_inbound(self) -> bool:
        return self.direction == "inbound"

    @property
    def net_amount(self) -> Decimal:
        """What actually moves through the bank once tax is withheld (R9.AC2)."""
        return self.amount - self.withheld_amount


class BankStatement(Base):
    __tablename__ = "bank_statement"
    __table_args__ = (
        UniqueConstraint("id", "company_id"),
        ForeignKeyConstraint(
            ["bank_account_id", "company_id"], ["account.id", "account.company_id"]
        ),
        Index("bank_statement_by_account", "company_id", "bank_account_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(ForeignKey("company.id"))
    bank_account_id: Mapped[UUID]
    name: Mapped[str]
    source_format: Mapped[str]
    file_name: Mapped[str | None]
    opening_balance: Mapped[Decimal | None]
    closing_balance: Mapped[Decimal | None]
    imported_at: Mapped[datetime] = mapped_column(server_default=func.now())
    imported_by: Mapped[UUID | None] = mapped_column(ForeignKey("app_user.id"))

    lines: Mapped[list["BankStatementLine"]] = relationship(
        back_populates="statement",
        foreign_keys="[BankStatementLine.statement_id, BankStatementLine.company_id]",
        primaryjoin="and_(BankStatement.id == BankStatementLine.statement_id, "
        "BankStatement.company_id == BankStatementLine.company_id)",
        order_by="BankStatementLine.line_no",
        cascade="all, delete-orphan",
    )


class BankStatementLine(Base):
    """A row the bank says happened. Staging, not the ledger, until someone confirms it."""

    __tablename__ = "bank_statement_line"
    __table_args__ = (
        UniqueConstraint("statement_id", "line_no"),
        UniqueConstraint("id", "company_id"),
        ForeignKeyConstraint(
            ["statement_id", "company_id"],
            ["bank_statement.id", "bank_statement.company_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["journal_entry_id", "company_id"],
            ["journal_entry.id", "journal_entry.company_id"],
        ),
        ForeignKeyConstraint(["payment_id", "company_id"], ["payment.id", "payment.company_id"]),
        Index(
            "bank_statement_line_import_uniq",
            "company_id",
            "import_hash",
            "occurrence",
            unique=True,
        ),
        Index(
            "bank_statement_line_unreconciled",
            "company_id",
            "date",
            postgresql_where=text("reconciled_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    statement_id: Mapped[UUID]
    company_id: Mapped[UUID]
    line_no: Mapped[int]
    date: Mapped[date]
    amount: Mapped[Decimal]
    currency_code: Mapped[str] = mapped_column(CHAR(3), ForeignKey("currency.code"))
    description: Mapped[str | None]
    counterparty: Mapped[str | None]
    bank_reference: Mapped[str | None]
    import_hash: Mapped[str]
    occurrence: Mapped[int] = mapped_column(server_default="1")
    journal_entry_id: Mapped[UUID | None]
    payment_id: Mapped[UUID | None]
    reconciled_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    statement: Mapped[BankStatement] = relationship(
        back_populates="lines",
        foreign_keys="[BankStatementLine.statement_id, BankStatementLine.company_id]",
        primaryjoin="and_(BankStatement.id == BankStatementLine.statement_id, "
        "BankStatement.company_id == BankStatementLine.company_id)",
    )
