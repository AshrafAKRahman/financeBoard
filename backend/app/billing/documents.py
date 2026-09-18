"""Invoices, bills and the notes that correct them.

A document is a draft until it is posted; posting builds one `PostingRequest` and hands it
to the ledger, which owns numbering, balance and immutability. Nothing here writes a
journal line itself.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.billing.models import (
    DOCUMENT_TYPES,
    TAX_TYPE_FOR,
    Document,
    DocumentLine,
    DocumentLineTax,
    Tax,
)
from app.billing.partners import get_partner
from app.billing.taxes import as_rate, get_tax
from app.billing.totals import DocumentTotals, LineInput, document_totals
from app.coa.accounts import get_account
from app.coa.defaults import get_defaults
from app.ledger.api import (
    Journal,
    JournalEntry,
    PostingLine,
    PostingRequest,
    currency_places,
    post,
    reverse,
)
from app.platform.audit.api import Actor, record
from app.shared.errors import DomainError
from app.shared.ids import uuid7
from app.shared.money import ZERO


@dataclass(frozen=True, slots=True)
class LineData:
    description: str
    quantity: Decimal
    unit_price: Decimal
    account_id: UUID
    tax_ids: Sequence[UUID] = ()
    discount_percent: Decimal = ZERO
    description_ar: str | None = None


@dataclass(frozen=True, slots=True)
class DocumentData:
    type: str
    partner_id: UUID
    journal_id: UUID
    date: date
    lines: Sequence[LineData] = ()
    due_date: date | None = None
    currency_code: str = "SAR"
    tax_inclusive: bool = False
    vendor_reference: str | None = None
    narration: str | None = None
    origin_document_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class GenerationLine:
    """A line as a recurring template stores it."""

    description: str
    quantity: str
    unit_price: str
    account_id: str
    tax_ids: list[str] = field(default_factory=list)


def now() -> datetime:
    return datetime.now(UTC)


def get_document(session: Session, company_id: UUID, document_id: UUID) -> Document:
    document = session.execute(
        select(Document)
        .options(selectinload(Document.lines).selectinload(DocumentLine.taxes))
        .where(Document.id == document_id, Document.company_id == company_id)
    ).scalar_one_or_none()
    if document is None:
        raise DomainError("invoicing.document_not_found", f"document {document_id} not found")
    return document


def list_documents(
    session: Session,
    company_id: UUID,
    *,
    type_: str | None = None,
    state: str | None = None,
    partner_id: UUID | None = None,
    since: date | None = None,
    until: date | None = None,
    limit: int = 100,
) -> Sequence[Document]:
    query = select(Document).where(Document.company_id == company_id)
    if type_:
        query = query.where(Document.type == type_)
    if state:
        query = query.where(Document.state == state)
    if partner_id:
        query = query.where(Document.partner_id == partner_id)
    if since:
        query = query.where(Document.date >= since)
    if until:
        query = query.where(Document.date <= until)
    query = query.order_by(Document.date.desc(), Document.created_at.desc()).limit(
        min(limit, 500)
    )
    return session.execute(query).scalars().all()


def taxes_of(session: Session, line: DocumentLine) -> list[Tax]:
    if not line.taxes:
        return []
    ids = [link.tax_id for link in line.taxes]
    return list(session.execute(select(Tax).where(Tax.id.in_(ids))).scalars())


def totals_of(session: Session, document: Document) -> DocumentTotals:
    """Always computed from the lines, never stored (R2.AC9)."""
    places = currency_places(session, document.currency_code)
    inputs = [
        LineInput(
            quantity=line.quantity,
            unit_price=line.unit_price,
            taxes=[as_rate(tax) for tax in taxes_of(session, line)],
            discount_percent=line.discount_percent,
        )
        for line in document.lines
    ]
    return document_totals(inputs, places, tax_inclusive=document.tax_inclusive)


def _require_draft(document: Document) -> None:
    if document.state != "draft":
        raise DomainError(
            "invoicing.posted_immutable",
            f"document {document.number or document.id} has been issued and cannot change",
        )


def _validate_line(session: Session, company_id: UUID, line: LineData) -> None:
    if not line.description.strip():
        raise DomainError("invoicing.invalid_line", "a line needs a description")
    if line.quantity < 0 or line.unit_price < 0:
        raise DomainError(
            "invoicing.invalid_line", "quantity and unit price cannot be negative"
        )
    if line.discount_percent < 0 or line.discount_percent > 100:
        raise DomainError("invoicing.invalid_line", "a discount is between 0 and 100 percent")
    try:
        account = get_account(session, company_id, line.account_id)
    except DomainError as error:
        raise DomainError("invoicing.account_not_found", error.message) from error
    if account.is_group:
        raise DomainError("invoicing.account_not_found", f"{account.code} is a group account")


def _write_lines(
    session: Session, document: Document, lines: Sequence[LineData], company_id: UUID
) -> None:
    for line in lines:
        _validate_line(session, company_id, line)

    document.lines.clear()
    session.flush()
    for line_no, line in enumerate(lines, start=1):
        row = DocumentLine(
            id=uuid7(),
            company_id=company_id,
            line_no=line_no,
            description=line.description.strip(),
            description_ar=line.description_ar or None,
            quantity=line.quantity,
            unit_price=line.unit_price,
            discount_percent=line.discount_percent,
            account_id=line.account_id,
        )
        document.lines.append(row)
        session.flush()
        for tax_id in dict.fromkeys(line.tax_ids):
            get_tax(session, company_id, tax_id)  # refuses another company's tax
            session.add(
                DocumentLineTax(line_id=row.id, tax_id=tax_id, company_id=company_id)
            )
    session.flush()


def create_document(
    session: Session, company_id: UUID, data: DocumentData, *, actor: Actor | None = None
) -> Document:
    if data.type not in DOCUMENT_TYPES:
        raise DomainError("invoicing.invalid_type", f"{data.type!r} is not a document type")
    get_partner(session, company_id, data.partner_id)

    journal = session.execute(
        select(Journal).where(
            Journal.id == data.journal_id, Journal.company_id == company_id
        )
    ).scalar_one_or_none()
    if journal is None:
        raise DomainError("invoicing.journal_not_found", f"journal {data.journal_id} not found")

    if data.vendor_reference:
        _check_vendor_reference(session, data.partner_id, data.vendor_reference)

    document = Document(
        id=uuid7(),
        company_id=company_id,
        type=data.type,
        partner_id=data.partner_id,
        journal_id=data.journal_id,
        date=data.date,
        due_date=data.due_date,
        currency_code=data.currency_code,
        tax_inclusive=data.tax_inclusive,
        vendor_reference=data.vendor_reference or None,
        narration=data.narration,
        origin_document_id=data.origin_document_id,
    )
    session.add(document)
    session.flush()
    _write_lines(session, document, data.lines, company_id)

    record(
        session,
        action="document.created",
        actor=actor,
        company_id=company_id,
        target_type="document",
        target_id=document.id,
        detail={"type": document.type, "partner": str(document.partner_id)},
    )
    return document


def _check_vendor_reference(
    session: Session, partner_id: UUID, reference: str, *, except_id: UUID | None = None
) -> None:
    """The duplicate-bill check an accounts payable clerk relies on (R4.AC3)."""
    query = select(Document.id).where(
        Document.partner_id == partner_id, Document.vendor_reference == reference
    )
    if except_id is not None:
        query = query.where(Document.id != except_id)
    if session.execute(query).scalar_one_or_none() is not None:
        raise DomainError(
            "invoicing.duplicate_vendor_reference",
            f"this vendor's document {reference} has already been recorded",
        )


def update_document(
    session: Session,
    company_id: UUID,
    document_id: UUID,
    changes: dict[str, Any],
    *,
    actor: Actor | None = None,
) -> Document:
    document = get_document(session, company_id, document_id)
    _require_draft(document)

    if "partner_id" in changes:
        get_partner(session, company_id, changes["partner_id"])
        document.partner_id = changes["partner_id"]
    for plain in ("date", "due_date", "currency_code", "tax_inclusive", "narration"):
        if plain in changes:
            setattr(document, plain, changes[plain])
    if "vendor_reference" in changes:
        if changes["vendor_reference"]:
            _check_vendor_reference(
                session, document.partner_id, changes["vendor_reference"], except_id=document.id
            )
        document.vendor_reference = changes["vendor_reference"] or None
    if "lines" in changes:
        _write_lines(session, document, changes["lines"], company_id)

    document.updated_at = now()
    session.flush()
    record(
        session,
        action="document.updated",
        actor=actor,
        company_id=company_id,
        target_type="document",
        target_id=document.id,
        detail={"changed": sorted(changes)},
    )
    return document


def delete_document(
    session: Session, company_id: UUID, document_id: UUID, *, actor: Actor | None = None
) -> None:
    document = get_document(session, company_id, document_id)
    _require_draft(document)
    session.delete(document)
    session.flush()
    record(
        session,
        action="document.deleted",
        actor=actor,
        company_id=company_id,
        target_type="document",
        target_id=document_id,
    )


# ----------------------------------------------------------------------------- posting


def _default_account(session: Session, document: Document) -> UUID:
    defaults = get_defaults(session, document.company_id)
    key = "receivable" if document.is_outgoing else "payable"
    account_id = defaults.accounts.get(key)
    if account_id is None:
        raise DomainError(
            "invoicing.default_account_missing",
            f"set the company's {key} default account before issuing documents",
        )
    return account_id


def _check_taxes(session: Session, document: Document) -> None:
    wanted = TAX_TYPE_FOR[document.type]
    for line in document.lines:
        for tax in taxes_of(session, line):
            if not tax.is_effective_on(document.date):
                raise DomainError(
                    "tax.not_effective",
                    f"{tax.name} does not apply on {document.date.isoformat()}",
                )
            if tax.type != wanted:
                raise DomainError(
                    "tax.wrong_tax_type",
                    f"{tax.name} is a {tax.type} tax; this document needs a {wanted} tax",
                )


def build_posting_request(session: Session, document: Document) -> PostingRequest:
    """One journal entry: the open item, the income or expense lines, and the taxes.

    Amounts are always positive; what changes is the side they land on. An invoice debits
    the customer and credits revenue; a credit note does exactly the reverse.
    """
    totals = totals_of(session, document)
    open_item_account = _default_account(session, document)

    # Customer documents put the open item on the debit side; a correcting note flips it.
    open_item_is_debit = document.is_outgoing
    if document.sign == -1:
        open_item_is_debit = not open_item_is_debit

    def sided(amount: Decimal, *, debit: bool) -> dict[str, Decimal]:
        return {"debit": amount, "credit": ZERO} if debit else {"debit": ZERO, "credit": amount}

    lines: list[PostingLine] = [
        PostingLine(
            account_id=open_item_account,
            partner_id=document.partner_id,
            due_date=document.due_date or document.date,
            name=f"{document.type} {document.number or ''}".strip(),
            **sided(totals.total, debit=open_item_is_debit),
        )
    ]

    places = currency_places(session, document.currency_code)
    for line in document.lines:
        amounts = document_totals(
            [
                LineInput(
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    taxes=[as_rate(tax) for tax in taxes_of(session, line)],
                    discount_percent=line.discount_percent,
                )
            ],
            places,
            tax_inclusive=document.tax_inclusive,
        )
        lines.append(
            PostingLine(
                account_id=line.account_id,
                name=line.description,
                **sided(amounts.net, debit=not open_item_is_debit),
            )
        )

    for group in totals.tax_groups:
        tax = session.get(Tax, group.tax.id)
        if tax is None or tax.account_id is None:
            raise DomainError(
                "tax.account_not_found", f"{group.tax.name} has no account to post to"
            )
        lines.append(
            PostingLine(
                account_id=tax.account_id,
                name=tax.name,
                tax_id=tax.id,
                tax_grid_tag=tax.grid_tag,
                **sided(group.amount, debit=not open_item_is_debit),
            )
        )

    return PostingRequest(
        company_id=document.company_id,
        journal_id=document.journal_id,
        date=document.date,
        currency_code=document.currency_code,
        lines=tuple(line for line in lines if line.debit or line.credit),
        ref=document.narration,
        source_type="document",
        source_id=document.id,
    )


def post_document(
    session: Session, company_id: UUID, document_id: UUID, *, actor: Actor | None = None
) -> Document:
    document = get_document(session, company_id, document_id)
    if document.state == "posted":
        raise DomainError("invoicing.already_posted", f"{document.number} is already issued")
    if document.state == "cancelled":
        raise DomainError("invoicing.already_cancelled", "a cancelled document cannot be issued")
    if not document.lines:
        raise DomainError("invoicing.no_lines", "a document needs at least one line to issue")

    _check_taxes(session, document)
    if document.origin_document_id is not None:
        _check_credit_note_limit(session, document)

    entry = post(session, build_posting_request(session, document))

    document.state = "posted"
    document.number = entry.number
    document.journal_entry_id = entry.id
    document.posted_at = now()
    document.due_date = document.due_date or document.date
    session.flush()

    totals = totals_of(session, document)
    record(
        session,
        action="document.posted",
        actor=actor,
        company_id=company_id,
        target_type="document",
        target_id=document.id,
        detail={
            "number": document.number,
            "total": str(totals.total),
            "currency": document.currency_code,
            "entry": str(entry.id),
        },
    )
    return document


def cancel_document(
    session: Session,
    company_id: UUID,
    document_id: UUID,
    *,
    reason: str | None = None,
    actor: Actor | None = None,
) -> Document:
    """The document and its entry both stay; a reversal makes the correction visible."""
    document = get_document(session, company_id, document_id)
    if document.state == "cancelled":
        raise DomainError("invoicing.already_cancelled", f"{document.number} is already cancelled")
    if document.state != "posted":
        raise DomainError("invoicing.not_posted", "only an issued document can be cancelled")

    reversal = reverse(
        session,
        company_id,
        document.journal_entry_id,
        ref=f"Cancellation of {document.number}",
    )
    document.state = "cancelled"
    document.cancelled_at = now()
    document.cancel_reason = reason
    session.flush()

    record(
        session,
        action="document.cancelled",
        actor=actor,
        company_id=company_id,
        target_type="document",
        target_id=document.id,
        detail={"number": document.number, "reason": reason, "reversal": str(reversal.id)},
    )
    return document


# ------------------------------------------------------------------------ credit notes


CORRECTION_OF = {"out_invoice": "out_credit", "in_bill": "in_debit"}


def credit_note_from(
    session: Session, company_id: UUID, document_id: UUID, *, actor: Actor | None = None
) -> Document:
    """A draft copy of the original, ready to be trimmed before it is issued (R5)."""
    origin = get_document(session, company_id, document_id)
    if origin.state != "posted":
        raise DomainError(
            "invoicing.not_posted", "only an issued document can be corrected by a note"
        )
    if origin.type not in CORRECTION_OF:
        raise DomainError(
            "invoicing.invalid_type", f"{origin.type} documents are not corrected by notes"
        )

    lines = [
        LineData(
            description=line.description,
            description_ar=line.description_ar,
            quantity=line.quantity,
            unit_price=line.unit_price,
            discount_percent=line.discount_percent,
            account_id=line.account_id,
            tax_ids=[link.tax_id for link in line.taxes],
        )
        for line in origin.lines
    ]

    return create_document(
        session,
        company_id,
        DocumentData(
            type=CORRECTION_OF[origin.type],
            partner_id=origin.partner_id,
            journal_id=origin.journal_id,
            date=origin.date,
            lines=lines,
            currency_code=origin.currency_code,
            tax_inclusive=origin.tax_inclusive,
            origin_document_id=origin.id,
            narration=f"Correction of {origin.number}",
        ),
        actor=actor,
    )


def _check_credit_note_limit(session: Session, note: Document) -> None:
    """Credits may not exceed what they correct (R5.AC6).

    The origin row is locked so two notes posted at the same moment cannot both pass.
    """
    origin = session.execute(
        select(Document)
        .options(selectinload(Document.lines).selectinload(DocumentLine.taxes))
        .where(Document.id == note.origin_document_id)
        .with_for_update()
    ).scalar_one_or_none()
    if origin is None:
        return

    already = ZERO
    others = session.execute(
        select(Document)
        .options(selectinload(Document.lines).selectinload(DocumentLine.taxes))
        .where(
            Document.origin_document_id == origin.id,
            Document.state == "posted",
            Document.id != note.id,
        )
    ).scalars()
    for other in others:
        already += totals_of(session, other).total

    if already + totals_of(session, note).total > totals_of(session, origin).total:
        raise DomainError(
            "invoicing.exceeds_original",
            f"credits against {origin.number} would exceed the document's total",
        )


def entry_of(session: Session, document: Document) -> JournalEntry | None:
    """The journal entry a posted document produced (R11.AC4)."""
    if document.journal_entry_id is None:
        return None
    return session.get(JournalEntry, document.journal_entry_id)


def count_documents(session: Session, company_id: UUID) -> int:
    return session.execute(
        select(func.count()).select_from(Document).where(Document.company_id == company_id)
    ).scalar_one()
