"""Invoicing tables (migration 0004). Kept in step with the migration by the drift test."""

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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.db import Base

PARTNER_TYPES = ("customer", "vendor", "both")
TAX_TYPES = ("sale", "purchase", "withholding")
VAT_CATEGORIES = ("standard", "zero_rated", "exempt", "out_of_scope")
DOCUMENT_TYPES = ("out_invoice", "in_bill", "out_credit", "in_debit")

# Which document types are ours to issue (as opposed to a vendor's).
OUTGOING = ("out_invoice", "out_credit")
# Which tax type each document type may carry.
TAX_TYPE_FOR = {
    "out_invoice": "sale",
    "out_credit": "sale",
    "in_bill": "purchase",
    "in_debit": "purchase",
}


class Partner(Base):
    __tablename__ = "partner"
    __table_args__ = (
        UniqueConstraint("id", "company_id"),
        Index(
            "partner_vat_number_uniq",
            "company_id",
            "vat_number",
            unique=True,
            postgresql_where=text("vat_number IS NOT NULL"),
        ),
        Index("partner_by_name", "company_id", "name"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(ForeignKey("company.id"))
    name: Mapped[str]
    name_ar: Mapped[str | None]
    type: Mapped[str]
    vat_number: Mapped[str | None]
    cr_number: Mapped[str | None]
    address: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    email: Mapped[str | None]
    phone: Mapped[str | None]
    active: Mapped[bool] = mapped_column(server_default="true")
    x_data: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Tax(Base):
    __tablename__ = "tax"
    __table_args__ = (
        UniqueConstraint("id", "company_id"),
        UniqueConstraint("company_id", "name"),
        ForeignKeyConstraint(["account_id", "company_id"], ["account.id", "account.company_id"]),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(ForeignKey("company.id"))
    name: Mapped[str]
    name_ar: Mapped[str | None]
    rate: Mapped[Decimal] = mapped_column(Numeric(6, 3))
    type: Mapped[str]
    vat_category: Mapped[str] = mapped_column(server_default="standard")
    exemption_reason: Mapped[str | None]
    account_id: Mapped[UUID | None]
    grid_tag: Mapped[str | None]
    effective_from: Mapped[date | None]
    effective_to: Mapped[date | None]
    active: Mapped[bool] = mapped_column(server_default="true")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())

    def is_effective_on(self, on: date) -> bool:
        if self.effective_from and on < self.effective_from:
            return False
        return not (self.effective_to and on > self.effective_to)


class Document(Base):
    __tablename__ = "document"
    __table_args__ = (
        UniqueConstraint("id", "company_id"),
        ForeignKeyConstraint(["partner_id", "company_id"], ["partner.id", "partner.company_id"]),
        ForeignKeyConstraint(["journal_id", "company_id"], ["journal.id", "journal.company_id"]),
        ForeignKeyConstraint(
            ["origin_document_id", "company_id"], ["document.id", "document.company_id"]
        ),
        ForeignKeyConstraint(
            ["journal_entry_id", "company_id"],
            ["journal_entry.id", "journal_entry.company_id"],
        ),
        Index(
            "document_number_uniq",
            "company_id",
            "type",
            "number",
            unique=True,
            postgresql_where=text("number IS NOT NULL"),
        ),
        Index(
            "document_vendor_reference_uniq",
            "partner_id",
            "vendor_reference",
            unique=True,
            postgresql_where=text("vendor_reference IS NOT NULL"),
        ),
        Index("document_by_date", "company_id", text("date DESC")),
        Index("document_by_partner", "company_id", "partner_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(ForeignKey("company.id"))
    type: Mapped[str]
    partner_id: Mapped[UUID]
    journal_id: Mapped[UUID]
    number: Mapped[str | None]
    date: Mapped[date]
    due_date: Mapped[date | None]
    currency_code: Mapped[str] = mapped_column(CHAR(3), ForeignKey("currency.code"))
    state: Mapped[str] = mapped_column(server_default="draft")
    tax_inclusive: Mapped[bool] = mapped_column(server_default="false")
    origin_document_id: Mapped[UUID | None]
    vendor_reference: Mapped[str | None]
    narration: Mapped[str | None]
    journal_entry_id: Mapped[UUID | None]
    posted_at: Mapped[datetime | None]
    cancelled_at: Mapped[datetime | None]
    cancel_reason: Mapped[str | None]
    x_data: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())

    lines: Mapped[list["DocumentLine"]] = relationship(
        back_populates="document",
        order_by="DocumentLine.line_no",
        cascade="all, delete-orphan",
        foreign_keys="[DocumentLine.document_id, DocumentLine.company_id]",
        primaryjoin="and_(Document.id == DocumentLine.document_id, "
        "Document.company_id == DocumentLine.company_id)",
    )

    @property
    def is_outgoing(self) -> bool:
        return self.type in OUTGOING

    @property
    def sign(self) -> int:
        """Credit and debit notes post the opposite way to what they correct."""
        return -1 if self.type in ("out_credit", "in_debit") else 1


class DocumentLine(Base):
    __tablename__ = "document_line"
    __table_args__ = (
        UniqueConstraint("document_id", "line_no"),
        UniqueConstraint("id", "company_id"),
        ForeignKeyConstraint(
            ["document_id", "company_id"],
            ["document.id", "document.company_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(["account_id", "company_id"], ["account.id", "account.company_id"]),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    document_id: Mapped[UUID]
    company_id: Mapped[UUID]
    line_no: Mapped[int]
    description: Mapped[str]
    description_ar: Mapped[str | None]
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(6, 3), server_default="0")
    account_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    document: Mapped[Document] = relationship(
        back_populates="lines",
        foreign_keys="[DocumentLine.document_id, DocumentLine.company_id]",
        primaryjoin="and_(Document.id == DocumentLine.document_id, "
        "Document.company_id == DocumentLine.company_id)",
    )
    taxes: Mapped[list["DocumentLineTax"]] = relationship(
        cascade="all, delete-orphan",
        foreign_keys="[DocumentLineTax.line_id, DocumentLineTax.company_id]",
        primaryjoin="and_(DocumentLine.id == DocumentLineTax.line_id, "
        "DocumentLine.company_id == DocumentLineTax.company_id)",
    )


class DocumentLineTax(Base):
    __tablename__ = "document_line_tax"
    __table_args__ = (
        ForeignKeyConstraint(
            ["line_id", "company_id"],
            ["document_line.id", "document_line.company_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(["tax_id", "company_id"], ["tax.id", "tax.company_id"]),
    )

    line_id: Mapped[UUID] = mapped_column(primary_key=True)
    tax_id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID]


class RecurringTemplate(Base):
    __tablename__ = "recurring_template"
    __table_args__ = (
        ForeignKeyConstraint(["partner_id", "company_id"], ["partner.id", "partner.company_id"]),
        ForeignKeyConstraint(["journal_id", "company_id"], ["journal.id", "journal.company_id"]),
        Index(
            "recurring_template_due",
            "company_id",
            "next_date",
            postgresql_where=text("active"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(ForeignKey("company.id"))
    name: Mapped[str]
    partner_id: Mapped[UUID]
    journal_id: Mapped[UUID]
    currency_code: Mapped[str] = mapped_column(CHAR(3), ForeignKey("currency.code"))
    tax_inclusive: Mapped[bool] = mapped_column(server_default="false")
    interval_months: Mapped[int]
    next_date: Mapped[date]
    last_generated_for: Mapped[date | None]
    # A template's lines are JSON, not rows: they are a recipe, not a document.
    lines: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    active: Mapped[bool] = mapped_column(server_default="true")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
