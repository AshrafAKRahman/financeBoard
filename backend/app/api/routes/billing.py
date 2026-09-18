"""Invoicing over HTTP: partners, taxes, documents and recurring templates.

Issuing is a separate permission from editing, so a junior can prepare a document and
someone else issues it.
"""

# A schema field called `date` would shadow the type inside its own class body,
# so the type is aliased here and the field keeps the name the API needs.
from datetime import UTC, datetime
from datetime import date as DateType
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import CallerDep, SessionDep, requires
from app.api.protection import needs
from app.billing import documents as documents_service
from app.billing import partners as partners_service
from app.billing import recurring as recurring_service
from app.billing import taxes as taxes_service
from app.platform.audit.api import Actor

router = APIRouter(prefix="/api/v1/companies/{company_id}", tags=["invoicing"])


# --------------------------------------------------------------------------- schemas


class PartnerIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: str
    name_ar: str | None = None
    vat_number: str | None = None
    cr_number: str | None = None
    email: str | None = None
    phone: str | None = None
    address: dict[str, Any] = Field(default_factory=dict)


class PartnerPatch(BaseModel):
    name: str | None = None
    type: str | None = None
    name_ar: str | None = None
    vat_number: str | None = None
    cr_number: str | None = None
    email: str | None = None
    phone: str | None = None
    address: dict[str, Any] | None = None


class PartnerOut(BaseModel):
    id: UUID
    name: str
    name_ar: str | None
    type: str
    vat_number: str | None
    cr_number: str | None
    email: str | None
    phone: str | None
    address: dict[str, Any]
    active: bool


class TaxIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    rate: Decimal
    type: str
    vat_category: str = "standard"
    name_ar: str | None = None
    exemption_reason: str | None = None
    account_id: UUID | None = None
    grid_tag: str | None = None
    effective_from: DateType | None = None
    effective_to: DateType | None = None


class TaxPatch(BaseModel):
    name: str | None = None
    name_ar: str | None = None
    rate: Decimal | None = None
    vat_category: str | None = None
    exemption_reason: str | None = None
    account_id: UUID | None = None
    grid_tag: str | None = None
    effective_from: DateType | None = None
    effective_to: DateType | None = None


class TaxOut(BaseModel):
    id: UUID
    name: str
    name_ar: str | None
    rate: Decimal
    type: str
    vat_category: str
    exemption_reason: str | None
    account_id: UUID | None
    grid_tag: str | None
    effective_from: DateType | None
    effective_to: DateType | None
    active: bool


class LineIn(BaseModel):
    description: str = Field(min_length=1)
    quantity: Decimal
    unit_price: Decimal
    account_id: UUID
    tax_ids: list[UUID] = Field(default_factory=list)
    discount_percent: Decimal = Decimal(0)
    description_ar: str | None = None


class DocumentIn(BaseModel):
    type: str
    partner_id: UUID
    journal_id: UUID
    date: DateType
    lines: list[LineIn] = Field(default_factory=list)
    due_date: DateType | None = None
    currency_code: str = "SAR"
    tax_inclusive: bool = False
    vendor_reference: str | None = None
    narration: str | None = None


class DocumentPatch(BaseModel):
    partner_id: UUID | None = None
    date: DateType | None = None
    due_date: DateType | None = None
    currency_code: str | None = None
    tax_inclusive: bool | None = None
    vendor_reference: str | None = None
    narration: str | None = None
    lines: list[LineIn] | None = None


class CancelIn(BaseModel):
    reason: str | None = None


class TaxGroupOut(BaseModel):
    tax_id: UUID
    name: str
    rate: Decimal
    vat_category: str
    base: Decimal
    amount: Decimal


class LineOut(BaseModel):
    id: UUID
    line_no: int
    description: str
    description_ar: str | None
    quantity: Decimal
    unit_price: Decimal
    discount_percent: Decimal
    account_id: UUID
    tax_ids: list[UUID]
    net: Decimal
    tax_total: Decimal


class DocumentSummaryOut(BaseModel):
    id: UUID
    type: str
    number: str | None
    state: str
    partner_id: UUID
    date: DateType
    due_date: DateType | None
    currency_code: str
    net: Decimal
    tax_total: Decimal
    total: Decimal
    payment_state: str = "not_paid"


class DocumentOut(DocumentSummaryOut):
    tax_inclusive: bool
    vendor_reference: str | None
    narration: str | None
    origin_document_id: UUID | None
    journal_entry_id: UUID | None
    lines: list[LineOut]
    tax_groups: list[TaxGroupOut]


class TemplateLineIn(BaseModel):
    description: str
    quantity: Decimal
    unit_price: Decimal
    account_id: UUID
    tax_ids: list[UUID] = Field(default_factory=list)
    description_ar: str | None = None


class TemplateIn(BaseModel):
    name: str = Field(min_length=1)
    partner_id: UUID
    journal_id: UUID
    next_date: DateType
    lines: list[TemplateLineIn]
    interval_months: int = 1
    currency_code: str = "SAR"
    tax_inclusive: bool = False


class TemplatePatch(BaseModel):
    name: str | None = None
    partner_id: UUID | None = None
    next_date: DateType | None = None
    interval_months: int | None = None
    currency_code: str | None = None
    tax_inclusive: bool | None = None
    lines: list[TemplateLineIn] | None = None


class TemplateOut(BaseModel):
    id: UUID
    name: str
    partner_id: UUID
    journal_id: UUID
    currency_code: str
    interval_months: int
    next_date: DateType
    last_generated_for: DateType | None
    active: bool


class GenerateIn(BaseModel):
    on: DateType | None = None


class GenerationOut(BaseModel):
    created: list[UUID]
    from_templates: list[str]
    count: int


def _actor(caller: CallerDep) -> Actor:
    return Actor(caller.user_id, caller.email)


def _summary(session, document) -> DocumentSummaryOut:
    totals = documents_service.totals_of(session, document)
    return DocumentSummaryOut(
        id=document.id,
        type=document.type,
        number=document.number,
        state=document.state,
        partner_id=document.partner_id,
        date=document.date,
        due_date=document.due_date,
        currency_code=document.currency_code,
        net=totals.net,
        tax_total=totals.tax_total,
        total=totals.total,
    )


def _full(session, document) -> DocumentOut:
    totals = documents_service.totals_of(session, document)
    places = 2
    lines = []
    for line in document.lines:
        taxes = documents_service.taxes_of(session, line)
        amounts = documents_service.document_totals(
            [
                documents_service.LineInput(
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    taxes=[taxes_service.as_rate(tax) for tax in taxes],
                    discount_percent=line.discount_percent,
                )
            ],
            places,
            tax_inclusive=document.tax_inclusive,
        )
        lines.append(
            LineOut(
                id=line.id,
                line_no=line.line_no,
                description=line.description,
                description_ar=line.description_ar,
                quantity=line.quantity,
                unit_price=line.unit_price,
                discount_percent=line.discount_percent,
                account_id=line.account_id,
                tax_ids=[tax.id for tax in taxes],
                net=amounts.net,
                tax_total=amounts.tax_total,
            )
        )

    return DocumentOut(
        **_summary(session, document).model_dump(),
        tax_inclusive=document.tax_inclusive,
        vendor_reference=document.vendor_reference,
        narration=document.narration,
        origin_document_id=document.origin_document_id,
        journal_entry_id=document.journal_entry_id,
        lines=lines,
        tax_groups=[
            TaxGroupOut(
                tax_id=group.tax.id,
                name=group.tax.name,
                rate=group.tax.rate,
                vat_category=group.tax.vat_category,
                base=group.base,
                amount=group.amount,
            )
            for group in totals.tax_groups
        ],
    )


def _line_data(lines: list[LineIn]) -> list[documents_service.LineData]:
    return [
        documents_service.LineData(
            description=line.description,
            description_ar=line.description_ar,
            quantity=line.quantity,
            unit_price=line.unit_price,
            discount_percent=line.discount_percent,
            account_id=line.account_id,
            tax_ids=line.tax_ids,
        )
        for line in lines
    ]


# -------------------------------------------------------------------------- partners


@router.get("/partners", response_model=list[PartnerOut], dependencies=[requires("partner:read")])
@needs("partner:read")
def list_partners(
    company_id: UUID,
    session: SessionDep,
    type: str | None = None,
    search: str | None = None,
    include_archived: bool = False,
) -> list:
    return list(
        partners_service.list_partners(
            session, company_id, type_=type, search=search, include_archived=include_archived
        )
    )


@router.post(
    "/partners",
    response_model=PartnerOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[requires("partner:manage")],
)
@needs("partner:manage")
def create_partner(company_id: UUID, body: PartnerIn, caller: CallerDep, session: SessionDep):
    return partners_service.create_partner(
        session,
        company_id,
        partners_service.PartnerData(**body.model_dump()),
        actor=_actor(caller),
    )


@router.patch(
    "/partners/{partner_id}",
    response_model=PartnerOut,
    dependencies=[requires("partner:manage")],
)
@needs("partner:manage")
def update_partner(
    company_id: UUID, partner_id: UUID, body: PartnerPatch, caller: CallerDep, session: SessionDep
):
    return partners_service.update_partner(
        session, company_id, partner_id, body.model_dump(exclude_unset=True), actor=_actor(caller)
    )


@router.post(
    "/partners/{partner_id}/archive",
    response_model=PartnerOut,
    dependencies=[requires("partner:manage")],
)
@needs("partner:manage")
def archive_partner(company_id: UUID, partner_id: UUID, caller: CallerDep, session: SessionDep):
    return partners_service.archive_partner(session, company_id, partner_id, actor=_actor(caller))


# ------------------------------------------------------------------------------ taxes


@router.get("/taxes", response_model=list[TaxOut], dependencies=[requires("tax:read")])
@needs("tax:read")
def list_taxes(
    company_id: UUID,
    session: SessionDep,
    type: str | None = None,
    on: DateType | None = None,
    include_archived: bool = False,
) -> list:
    return list(
        taxes_service.list_taxes(
            session, company_id, type_=type, on=on, include_archived=include_archived
        )
    )


@router.post(
    "/taxes",
    response_model=TaxOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[requires("tax:manage")],
)
@needs("tax:manage")
def create_tax(company_id: UUID, body: TaxIn, caller: CallerDep, session: SessionDep):
    return taxes_service.create_tax(
        session, company_id, taxes_service.TaxData(**body.model_dump()), actor=_actor(caller)
    )


@router.patch("/taxes/{tax_id}", response_model=TaxOut, dependencies=[requires("tax:manage")])
@needs("tax:manage")
def update_tax(
    company_id: UUID, tax_id: UUID, body: TaxPatch, caller: CallerDep, session: SessionDep
):
    return taxes_service.update_tax(
        session, company_id, tax_id, body.model_dump(exclude_unset=True), actor=_actor(caller)
    )


@router.post(
    "/taxes/{tax_id}/archive", response_model=TaxOut, dependencies=[requires("tax:manage")]
)
@needs("tax:manage")
def archive_tax(company_id: UUID, tax_id: UUID, caller: CallerDep, session: SessionDep):
    return taxes_service.archive_tax(session, company_id, tax_id, actor=_actor(caller))


# -------------------------------------------------------------------------- documents


@router.get(
    "/documents", response_model=list[DocumentSummaryOut], dependencies=[requires("invoice:read")]
)
@needs("invoice:read")
def list_documents(
    company_id: UUID,
    session: SessionDep,
    type: str | None = None,
    state: str | None = None,
    partner_id: UUID | None = None,
    since: DateType | None = None,
    until: DateType | None = None,
) -> list[DocumentSummaryOut]:
    documents = documents_service.list_documents(
        session,
        company_id,
        type_=type,
        state=state,
        partner_id=partner_id,
        since=since,
        until=until,
    )
    return [_summary(session, document) for document in documents]


@router.get(
    "/documents/{document_id}",
    response_model=DocumentOut,
    dependencies=[requires("invoice:read")],
)
@needs("invoice:read")
def read_document(company_id: UUID, document_id: UUID, session: SessionDep) -> DocumentOut:
    return _full(session, documents_service.get_document(session, company_id, document_id))


@router.post(
    "/documents",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[requires("invoice:manage")],
)
@needs("invoice:manage")
def create_document(
    company_id: UUID, body: DocumentIn, caller: CallerDep, session: SessionDep
) -> DocumentOut:
    payload = body.model_dump(exclude={"lines"})
    document = documents_service.create_document(
        session,
        company_id,
        documents_service.DocumentData(lines=_line_data(body.lines), **payload),
        actor=_actor(caller),
    )
    return _full(session, document)


@router.patch(
    "/documents/{document_id}",
    response_model=DocumentOut,
    dependencies=[requires("invoice:manage")],
)
@needs("invoice:manage")
def update_document(
    company_id: UUID,
    document_id: UUID,
    body: DocumentPatch,
    caller: CallerDep,
    session: SessionDep,
) -> DocumentOut:
    changes = body.model_dump(exclude_unset=True)
    if "lines" in changes and changes["lines"] is not None:
        changes["lines"] = _line_data(body.lines or [])
    document = documents_service.update_document(
        session, company_id, document_id, changes, actor=_actor(caller)
    )
    return _full(session, document)


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[requires("invoice:manage")],
)
@needs("invoice:manage")
def delete_document(
    company_id: UUID, document_id: UUID, caller: CallerDep, session: SessionDep
) -> None:
    documents_service.delete_document(session, company_id, document_id, actor=_actor(caller))


@router.post(
    "/documents/{document_id}/post",
    response_model=DocumentOut,
    dependencies=[requires("invoice:post")],
)
@needs("invoice:post")
def post_document(
    company_id: UUID, document_id: UUID, caller: CallerDep, session: SessionDep
) -> DocumentOut:
    document = documents_service.post_document(
        session, company_id, document_id, actor=_actor(caller)
    )
    return _full(session, document)


@router.post(
    "/documents/{document_id}/cancel",
    response_model=DocumentOut,
    dependencies=[requires("invoice:post")],
)
@needs("invoice:post")
def cancel_document(
    company_id: UUID,
    document_id: UUID,
    body: CancelIn,
    caller: CallerDep,
    session: SessionDep,
) -> DocumentOut:
    document = documents_service.cancel_document(
        session, company_id, document_id, reason=body.reason, actor=_actor(caller)
    )
    return _full(session, document)


@router.post(
    "/documents/{document_id}/credit-note",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[requires("invoice:post")],
)
@needs("invoice:post")
def credit_note(
    company_id: UUID, document_id: UUID, caller: CallerDep, session: SessionDep
) -> DocumentOut:
    note = documents_service.credit_note_from(
        session, company_id, document_id, actor=_actor(caller)
    )
    return _full(session, note)


# ------------------------------------------------------------------ recurring invoices


@router.get(
    "/recurring-templates",
    response_model=list[TemplateOut],
    dependencies=[requires("invoice:manage")],
)
@needs("invoice:manage")
def list_templates(company_id: UUID, session: SessionDep) -> list:
    return list(recurring_service.list_templates(session, company_id))


@router.post(
    "/recurring-templates",
    response_model=TemplateOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[requires("invoice:manage")],
)
@needs("invoice:manage")
def create_template(company_id: UUID, body: TemplateIn, caller: CallerDep, session: SessionDep):
    payload = body.model_dump(exclude={"lines"})
    return recurring_service.create_template(
        session,
        company_id,
        recurring_service.TemplateData(
            lines=[recurring_service.TemplateLine(**line.model_dump()) for line in body.lines],
            **payload,
        ),
        actor=_actor(caller),
    )


@router.patch(
    "/recurring-templates/{template_id}",
    response_model=TemplateOut,
    dependencies=[requires("invoice:manage")],
)
@needs("invoice:manage")
def update_template(
    company_id: UUID,
    template_id: UUID,
    body: TemplatePatch,
    caller: CallerDep,
    session: SessionDep,
):
    changes = body.model_dump(exclude_unset=True)
    if changes.get("lines") is not None:
        changes["lines"] = [
            recurring_service.TemplateLine(**line.model_dump()) for line in body.lines or []
        ]
    return recurring_service.update_template(
        session, company_id, template_id, changes, actor=_actor(caller)
    )


@router.post(
    "/recurring-templates/{template_id}/pause",
    response_model=TemplateOut,
    dependencies=[requires("invoice:manage")],
)
@needs("invoice:manage")
def pause_template(company_id: UUID, template_id: UUID, caller: CallerDep, session: SessionDep):
    return recurring_service.set_active(
        session, company_id, template_id, False, actor=_actor(caller)
    )


@router.post(
    "/recurring-templates/{template_id}/resume",
    response_model=TemplateOut,
    dependencies=[requires("invoice:manage")],
)
@needs("invoice:manage")
def resume_template(company_id: UUID, template_id: UUID, caller: CallerDep, session: SessionDep):
    return recurring_service.set_active(
        session, company_id, template_id, True, actor=_actor(caller)
    )


@router.post(
    "/recurring-templates/generate",
    response_model=GenerationOut,
    dependencies=[requires("invoice:manage")],
)
@needs("invoice:manage")
def generate_recurring(
    company_id: UUID, body: GenerateIn, caller: CallerDep, session: SessionDep
) -> GenerationOut:
    result = recurring_service.generate_due(
        session, company_id, body.on or datetime.now(UTC).date(), actor=_actor(caller)
    )
    return GenerationOut(
        created=result.created, from_templates=result.from_templates, count=result.count
    )
