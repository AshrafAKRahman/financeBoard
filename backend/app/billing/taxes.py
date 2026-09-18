"""Tax definitions: the rates a company charges, and when each one applies."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.billing.models import (
    TAX_TYPES,
    VAT_CATEGORIES,
    Document,
    DocumentLine,
    DocumentLineTax,
    Tax,
)
from app.billing.totals import TaxRate
from app.coa.accounts import get_account
from app.platform.audit.api import Actor, record
from app.shared.errors import DomainError
from app.shared.ids import uuid7


@dataclass(frozen=True, slots=True)
class TaxData:
    name: str
    rate: Decimal
    type: str
    vat_category: str = "standard"
    name_ar: str | None = None
    exemption_reason: str | None = None
    account_id: UUID | None = None
    grid_tag: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None


def get_tax(session: Session, company_id: UUID, tax_id: UUID) -> Tax:
    tax = session.execute(
        select(Tax).where(Tax.id == tax_id, Tax.company_id == company_id)
    ).scalar_one_or_none()
    if tax is None:
        raise DomainError("tax.tax_not_found", f"tax {tax_id} not found")
    return tax


def list_taxes(
    session: Session,
    company_id: UUID,
    *,
    type_: str | None = None,
    on: date | None = None,
    include_archived: bool = False,
) -> Sequence[Tax]:
    query = select(Tax).where(Tax.company_id == company_id)
    if not include_archived:
        query = query.where(Tax.active.is_(True))
    if type_:
        query = query.where(Tax.type == type_)
    taxes = session.execute(query.order_by(Tax.name)).scalars().all()
    if on is not None:
        taxes = [tax for tax in taxes if tax.is_effective_on(on)]
    return taxes


def as_rate(tax: Tax) -> TaxRate:
    """The shape the arithmetic wants — no database rows in the totals module."""
    return TaxRate(id=tax.id, name=tax.name, rate=tax.rate, vat_category=tax.vat_category)


def _validate(data_or_tax: Any, *, rate: Decimal, category: str, reason: str | None) -> None:
    if rate < 0 or rate > 100:
        raise DomainError("tax.invalid_rate", "a tax rate is between 0 and 100")
    if category not in VAT_CATEGORIES:
        raise DomainError("tax.invalid_category", f"{category!r} is not a VAT category")
    if category != "standard" and not reason:
        raise DomainError(
            "tax.missing_reason",
            f"a {category} tax needs a reason, because the invoice has to print it",
        )


def create_tax(
    session: Session, company_id: UUID, data: TaxData, *, actor: Actor | None = None
) -> Tax:
    name = data.name.strip()
    if not name:
        raise DomainError("invoicing.missing_field", "a tax needs a name")
    if data.type not in TAX_TYPES:
        raise DomainError("tax.invalid_type", f"{data.type!r} is not a tax type")
    _validate(data, rate=data.rate, category=data.vat_category, reason=data.exemption_reason)

    if data.account_id is not None:
        try:
            get_account(session, company_id, data.account_id)
        except DomainError as error:
            raise DomainError("tax.account_not_found", error.message) from error

    if session.execute(
        select(Tax.id).where(Tax.company_id == company_id, Tax.name == name)
    ).scalar_one_or_none():
        raise DomainError("tax.duplicate_name", f"a tax called {name!r} already exists")

    tax = Tax(
        id=uuid7(),
        company_id=company_id,
        name=name,
        name_ar=data.name_ar or None,
        rate=data.rate,
        type=data.type,
        vat_category=data.vat_category,
        exemption_reason=data.exemption_reason or None,
        account_id=data.account_id,
        grid_tag=data.grid_tag,
        effective_from=data.effective_from,
        effective_to=data.effective_to,
    )
    session.add(tax)
    session.flush()
    record(
        session,
        action="tax.created",
        actor=actor,
        company_id=company_id,
        target_type="tax",
        target_id=tax.id,
        detail={"name": tax.name, "rate": str(tax.rate), "type": tax.type},
    )
    return tax


def is_used_on_a_posted_document(session: Session, tax_id: UUID) -> bool:
    return bool(
        session.execute(
            select(func.count())
            .select_from(DocumentLineTax)
            .join(DocumentLine, DocumentLine.id == DocumentLineTax.line_id)
            .join(Document, Document.id == DocumentLine.document_id)
            .where(DocumentLineTax.tax_id == tax_id, Document.state != "draft")
        ).scalar_one()
    )


def update_tax(
    session: Session,
    company_id: UUID,
    tax_id: UUID,
    changes: dict[str, Any],
    *,
    actor: Actor | None = None,
) -> Tax:
    tax = get_tax(session, company_id, tax_id)

    if "rate" in changes and Decimal(str(changes["rate"])) != tax.rate:
        if is_used_on_a_posted_document(session, tax_id):
            raise DomainError(
                "tax.tax_in_use",
                f"{tax.name} is on issued documents; create a new tax instead of changing it",
            )
        tax.rate = Decimal(str(changes["rate"]))

    category = changes.get("vat_category", tax.vat_category)
    reason = changes.get("exemption_reason", tax.exemption_reason)
    _validate(tax, rate=tax.rate, category=category, reason=reason)
    tax.vat_category, tax.exemption_reason = category, (reason or None)

    for plain in ("name", "name_ar", "grid_tag", "effective_from", "effective_to"):
        if plain in changes:
            setattr(tax, plain, changes[plain] or None)
    if "account_id" in changes:
        if changes["account_id"] is not None:
            try:
                get_account(session, company_id, changes["account_id"])
            except DomainError as error:
                raise DomainError("tax.account_not_found", error.message) from error
        tax.account_id = changes["account_id"]

    tax.updated_at = datetime.now(UTC)
    session.flush()
    record(
        session,
        action="tax.updated",
        actor=actor,
        company_id=company_id,
        target_type="tax",
        target_id=tax.id,
        detail={"name": tax.name, "changed": sorted(changes)},
    )
    return tax


def archive_tax(
    session: Session, company_id: UUID, tax_id: UUID, *, actor: Actor | None = None
) -> Tax:
    """Issued documents keep it; new ones are no longer offered it (R1.AC9)."""
    tax = get_tax(session, company_id, tax_id)
    tax.active = False
    tax.updated_at = datetime.now(UTC)
    session.flush()
    record(
        session,
        action="tax.archived",
        actor=actor,
        company_id=company_id,
        target_type="tax",
        target_id=tax.id,
        detail={"name": tax.name},
    )
    return tax


# The taxes a Saudi company needs on day one. They live here rather than in the chart
# template because taxes are billing's to own — the chart module sits below this one.
SAUDI_TAXES: tuple[dict[str, Any], ...] = (
    {
        "name": "VAT 15%",
        "name_ar": "ضريبة القيمة المضافة 15%",
        "rate": "15",
        "type": "sale",
        "account_code": "2200",
        "grid_tag": "sales_standard",
    },
    {
        "name": "VAT 15% (purchases)",
        "name_ar": "ضريبة المدخلات 15%",
        "rate": "15",
        "type": "purchase",
        "account_code": "1300",
        "grid_tag": "purchases_standard",
    },
    {
        "name": "Zero-rated exports",
        "name_ar": "صادرات خاضعة لنسبة الصفر",
        "rate": "0",
        "type": "sale",
        "account_code": "2200",
        "vat_category": "zero_rated",
        "exemption_reason": "Export of goods outside the GCC",
        "grid_tag": "sales_zero_rated",
    },
    {
        "name": "Exempt supply",
        "name_ar": "توريد معفى",
        "rate": "0",
        "type": "sale",
        "account_code": "2200",
        "vat_category": "exempt",
        "exemption_reason": "Exempt financial supply",
        "grid_tag": "sales_exempt",
    },
)


def install_saudi_taxes(
    session: Session, company_id: UUID, *, actor: Actor | None = None
) -> list[Tax]:
    """Create the standard Saudi taxes against an already-loaded chart (R1.AC10).

    Called after a chart template is loaded, because each tax needs its VAT account.
    """
    from app.coa.accounts import list_chart

    by_code = {row.account.code: row.account for row in list_chart(session, company_id)}
    created: list[Tax] = []
    for entry in SAUDI_TAXES:
        account = by_code.get(entry["account_code"])
        if account is None:
            raise DomainError(
                "tax.account_not_found",
                f"account {entry['account_code']} is missing; load a chart template first",
            )
        created.append(
            create_tax(
                session,
                company_id,
                TaxData(
                    name=entry["name"],
                    name_ar=entry["name_ar"],
                    rate=Decimal(entry["rate"]),
                    type=entry["type"],
                    vat_category=entry.get("vat_category", "standard"),
                    exemption_reason=entry.get("exemption_reason"),
                    account_id=account.id,
                    grid_tag=entry.get("grid_tag"),
                ),
                actor=actor,
            )
        )
    return created
