"""Recurring invoices: the same bill every month, as a draft to check rather than retype.

There is no job runner yet, so generation is a call an operator or a scheduled request
makes. It is idempotent per due date, so running it twice bills nobody twice (R8.AC5).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.documents import DocumentData, LineData, create_document
from app.billing.models import Document, RecurringTemplate
from app.billing.partners import get_partner
from app.platform.audit.api import Actor, record
from app.shared.errors import DomainError
from app.shared.ids import uuid7


@dataclass(frozen=True, slots=True)
class TemplateLine:
    description: str
    quantity: Decimal
    unit_price: Decimal
    account_id: UUID
    tax_ids: Sequence[UUID] = ()
    description_ar: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "description_ar": self.description_ar,
            "quantity": str(self.quantity),
            "unit_price": str(self.unit_price),
            "account_id": str(self.account_id),
            "tax_ids": [str(tax_id) for tax_id in self.tax_ids],
        }


@dataclass(frozen=True, slots=True)
class TemplateData:
    name: str
    partner_id: UUID
    journal_id: UUID
    next_date: date
    lines: Sequence[TemplateLine]
    interval_months: int = 1
    currency_code: str = "SAR"
    tax_inclusive: bool = False


@dataclass
class GenerationResult:
    """What a run did, so an operator can see it rather than guess (R8.AC7)."""

    created: list[UUID] = field(default_factory=list)
    from_templates: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.created)


def now() -> datetime:
    return datetime.now(UTC)


def add_months(start: date, months: int) -> date:
    """Advance by whole months, keeping to the end of a short month."""
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    last_day = [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return date(year, month, min(start.day, last_day))


def get_template(session: Session, company_id: UUID, template_id: UUID) -> RecurringTemplate:
    template = session.execute(
        select(RecurringTemplate).where(
            RecurringTemplate.id == template_id, RecurringTemplate.company_id == company_id
        )
    ).scalar_one_or_none()
    if template is None:
        raise DomainError("invoicing.template_not_found", f"template {template_id} not found")
    return template


def list_templates(
    session: Session, company_id: UUID, *, include_paused: bool = True
) -> Sequence[RecurringTemplate]:
    query = select(RecurringTemplate).where(RecurringTemplate.company_id == company_id)
    if not include_paused:
        query = query.where(RecurringTemplate.active.is_(True))
    return session.execute(query.order_by(RecurringTemplate.name)).scalars().all()


def create_template(
    session: Session, company_id: UUID, data: TemplateData, *, actor: Actor | None = None
) -> RecurringTemplate:
    if not data.name.strip():
        raise DomainError("invoicing.missing_field", "a template needs a name")
    if not 1 <= data.interval_months <= 12:
        raise DomainError(
            "invoicing.invalid_interval", "an interval is between 1 and 12 months"
        )
    if not data.lines:
        raise DomainError("invoicing.no_lines", "a template needs at least one line")
    get_partner(session, company_id, data.partner_id)

    template = RecurringTemplate(
        id=uuid7(),
        company_id=company_id,
        name=data.name.strip(),
        partner_id=data.partner_id,
        journal_id=data.journal_id,
        currency_code=data.currency_code,
        tax_inclusive=data.tax_inclusive,
        interval_months=data.interval_months,
        next_date=data.next_date,
        lines=[line.as_json() for line in data.lines],
    )
    session.add(template)
    session.flush()
    record(
        session,
        action="recurring_template.created",
        actor=actor,
        company_id=company_id,
        target_type="recurring_template",
        target_id=template.id,
        detail={"name": template.name, "every_months": template.interval_months},
    )
    return template


def update_template(
    session: Session,
    company_id: UUID,
    template_id: UUID,
    changes: dict[str, Any],
    *,
    actor: Actor | None = None,
) -> RecurringTemplate:
    template = get_template(session, company_id, template_id)

    if "lines" in changes:
        lines = changes["lines"]
        if not lines:
            raise DomainError("invoicing.no_lines", "a template needs at least one line")
        template.lines = [line.as_json() for line in lines]
    for plain in ("name", "next_date", "interval_months", "currency_code", "tax_inclusive"):
        if plain in changes:
            setattr(template, plain, changes[plain])
    if "partner_id" in changes:
        get_partner(session, company_id, changes["partner_id"])
        template.partner_id = changes["partner_id"]

    template.updated_at = now()
    session.flush()
    record(
        session,
        action="recurring_template.updated",
        actor=actor,
        company_id=company_id,
        target_type="recurring_template",
        target_id=template.id,
        detail={"name": template.name, "changed": sorted(changes)},
    )
    return template


def set_active(
    session: Session,
    company_id: UUID,
    template_id: UUID,
    active: bool,
    *,
    actor: Actor | None = None,
) -> RecurringTemplate:
    """Pausing stops generation without losing the template (R8.AC6)."""
    template = get_template(session, company_id, template_id)
    template.active = active
    template.updated_at = now()
    session.flush()
    record(
        session,
        action="recurring_template.resumed" if active else "recurring_template.paused",
        actor=actor,
        company_id=company_id,
        target_type="recurring_template",
        target_id=template.id,
        detail={"name": template.name},
    )
    return template


def generate_due(
    session: Session, company_id: UUID, on: date, *, actor: Actor | None = None
) -> GenerationResult:
    """Create a draft invoice for every template due on or before ``on``."""
    result = GenerationResult()

    templates = (
        session.execute(
            select(RecurringTemplate)
            .where(
                RecurringTemplate.company_id == company_id,
                RecurringTemplate.active.is_(True),
                RecurringTemplate.next_date <= on,
            )
            .order_by(RecurringTemplate.next_date)
            .with_for_update()
        )
        .scalars()
        .all()
    )

    for template in templates:
        due = template.next_date
        if template.last_generated_for is not None and template.last_generated_for >= due:
            continue  # already billed for this date (R8.AC5)

        document = create_document(
            session,
            company_id,
            DocumentData(
                type="out_invoice",
                partner_id=template.partner_id,
                journal_id=template.journal_id,
                date=due,
                currency_code=template.currency_code,
                tax_inclusive=template.tax_inclusive,
                narration=f"Recurring: {template.name}",
                lines=[
                    LineData(
                        description=line["description"],
                        description_ar=line.get("description_ar"),
                        quantity=Decimal(line["quantity"]),
                        unit_price=Decimal(line["unit_price"]),
                        account_id=UUID(line["account_id"]),
                        tax_ids=[UUID(tax_id) for tax_id in line.get("tax_ids", [])],
                    )
                    for line in template.lines
                ],
            ),
            actor=actor,
        )

        template.last_generated_for = due
        template.next_date = add_months(due, template.interval_months)
        template.updated_at = now()
        session.flush()

        result.created.append(document.id)
        result.from_templates.append(template.name)

    record(
        session,
        action="recurring_template.generated",
        actor=actor,
        company_id=company_id,
        detail={"on": on.isoformat(), "created": result.count, "templates": result.from_templates},
    )
    return result


def documents_from_template(
    session: Session, company_id: UUID, template_name: str
) -> Sequence[Document]:
    return (
        session.execute(
            select(Document).where(
                Document.company_id == company_id,
                Document.narration == f"Recurring: {template_name}",
            )
        )
        .scalars()
        .all()
    )
