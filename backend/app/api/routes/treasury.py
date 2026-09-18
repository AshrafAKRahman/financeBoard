"""Payments, matching and bank reconciliation over HTTP.

Recording a payment is one permission; posting, matching and reconciling are another,
because those move money between accounts. Importing a statement is a third: the file comes
from outside, and whoever loaded it is worth recording.
"""

# A schema field called `date` would shadow the type inside its own class body, so the type
# is aliased here and the field keeps the name the API needs.
from datetime import date as DateType
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, UploadFile, status
from pydantic import BaseModel, Field

from app.api.deps import CallerDep, SessionDep, requires
from app.api.protection import needs
from app.platform.audit.api import Actor
from app.treasury import matching as matching_service
from app.treasury import payments as payments_service
from app.treasury import reconciling as reconciling_service
from app.treasury import state as state_service
from app.treasury.statements import CsvSource, Mt940Source, OfxSource, StatementSource

router = APIRouter(prefix="/api/v1/companies/{company_id}", tags=["payments"])


# --------------------------------------------------------------------------- schemas


class PaymentIn(BaseModel):
    direction: str
    partner_id: UUID
    journal_id: UUID
    date: DateType
    amount: Decimal
    currency_code: str = Field(default="SAR", min_length=3, max_length=3)
    withholding_tax_id: UUID | None = None
    reference: str | None = None
    memo: str | None = None


class PaymentOut(BaseModel):
    id: UUID
    direction: str
    partner_id: UUID
    journal_id: UUID
    number: str | None
    date: DateType
    amount: Decimal
    net_amount: Decimal
    currency_code: str
    state: str
    withholding_tax_id: UUID | None
    withheld_amount: Decimal
    reference: str | None
    memo: str | None
    journal_entry_id: UUID | None
    cancel_reason: str | None


class CancelIn(BaseModel):
    reason: str | None = None


class MatchIn(BaseModel):
    """Either a set of lines to match against each other, or one explicit pair."""

    line_ids: list[UUID] = Field(default_factory=list)
    debit_line_id: UUID | None = None
    credit_line_id: UUID | None = None
    amount: Decimal | None = None


class MatchOut(BaseModel):
    id: UUID
    debit_line_id: UUID
    credit_line_id: UUID
    debit_amount: Decimal
    credit_amount: Decimal
    fx_entry_id: UUID | None


class OpenItemOut(BaseModel):
    line_id: UUID
    entry_id: UUID
    entry_number: str | None
    entry_date: DateType
    account_id: UUID
    partner_id: UUID | None
    name: str | None
    is_debit: bool
    amount: Decimal
    open_amount: Decimal
    open_amount_currency: Decimal
    currency_code: str


class SuggestionOut(BaseModel):
    line_id: UUID
    entry_number: str | None
    amount: Decimal
    reason: str


class StatementOut(BaseModel):
    id: UUID
    bank_account_id: UUID
    name: str
    source_format: str
    file_name: str | None
    opening_balance: Decimal | None
    closing_balance: Decimal | None


class StatementLineOut(BaseModel):
    id: UUID
    statement_id: UUID
    line_no: int
    date: DateType
    amount: Decimal
    currency_code: str
    description: str | None
    counterparty: str | None
    bank_reference: str | None
    payment_id: UUID | None
    journal_entry_id: UUID | None
    reconciled: bool


class ImportOut(BaseModel):
    statement_id: UUID
    created: int
    duplicates: int
    rejected: list[tuple[int, str]]


class ReconcileIn(BaseModel):
    payment_id: UUID


class PaymentStateOut(BaseModel):
    state: str
    total: Decimal
    paid: Decimal
    open_amount: Decimal
    payments: list[dict]


class LineSuggestionOut(BaseModel):
    payment_id: UUID
    number: str | None
    date: DateType
    amount: Decimal
    reason: str


# --------------------------------------------------------------------------- helpers


def _actor(caller: CallerDep) -> Actor:
    return Actor(caller.user_id, caller.email)


def _payment(payment) -> PaymentOut:
    return PaymentOut(
        id=payment.id,
        direction=payment.direction,
        partner_id=payment.partner_id,
        journal_id=payment.journal_id,
        number=payment.number,
        date=payment.date,
        amount=payment.amount,
        net_amount=payment.net_amount,
        currency_code=payment.currency_code,
        state=payment.state,
        withholding_tax_id=payment.withholding_tax_id,
        withheld_amount=payment.withheld_amount,
        reference=payment.reference,
        memo=payment.memo,
        journal_entry_id=payment.journal_entry_id,
        cancel_reason=payment.cancel_reason,
    )


def _match(reconciliation) -> MatchOut:
    return MatchOut(
        id=reconciliation.id,
        debit_line_id=reconciliation.debit_line_id,
        credit_line_id=reconciliation.credit_line_id,
        debit_amount=reconciliation.debit_amount,
        credit_amount=reconciliation.credit_amount,
        fx_entry_id=reconciliation.fx_entry_id,
    )


def _open_item(item) -> OpenItemOut:
    line = item.line
    return OpenItemOut(
        line_id=line.id,
        entry_id=line.entry_id,
        entry_number=item.entry_number,
        entry_date=item.entry_date,
        account_id=line.account_id,
        partner_id=line.partner_id,
        name=line.name,
        is_debit=item.is_debit,
        amount=abs(line.debit - line.credit),
        open_amount=line.residual,
        open_amount_currency=line.residual_currency,
        currency_code=line.currency_code,
    )


def _statement_line(line) -> StatementLineOut:
    return StatementLineOut(
        id=line.id,
        statement_id=line.statement_id,
        line_no=line.line_no,
        date=line.date,
        amount=line.amount,
        currency_code=line.currency_code,
        description=line.description,
        counterparty=line.counterparty,
        bank_reference=line.bank_reference,
        payment_id=line.payment_id,
        journal_entry_id=line.journal_entry_id,
        reconciled=line.reconciled_at is not None,
    )


def _source(source_format: str, mapping: dict[str, str] | None) -> StatementSource:
    from app.shared.errors import DomainError

    if source_format == "csv":
        if not mapping:
            raise DomainError("payments.unreadable_file", "a CSV import needs a column mapping")
        return CsvSource(mapping)
    if source_format == "mt940":
        return Mt940Source()
    if source_format == "ofx":
        return OfxSource()
    raise DomainError("payments.unknown_format", f"{source_format!r} is not a statement format")


# -------------------------------------------------------------------------- payments


@router.get("/payments", response_model=list[PaymentOut], dependencies=[requires("payment:read")])
@needs("payment:read")
def list_payments(
    company_id: UUID,
    session: SessionDep,
    partner_id: UUID | None = None,
    state: str | None = None,
    direction: str | None = None,
) -> list[PaymentOut]:
    payments = payments_service.list_payments(
        session, company_id, partner_id=partner_id, state=state, direction=direction
    )
    return [_payment(payment) for payment in payments]


@router.get(
    "/payments/{payment_id}",
    response_model=PaymentOut,
    dependencies=[requires("payment:read")],
)
@needs("payment:read")
def read_payment(company_id: UUID, payment_id: UUID, session: SessionDep) -> PaymentOut:
    return _payment(payments_service.get_payment(session, company_id, payment_id))


@router.post(
    "/payments",
    response_model=PaymentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[requires("payment:manage")],
)
@needs("payment:manage")
def create_payment(
    company_id: UUID, body: PaymentIn, caller: CallerDep, session: SessionDep
) -> PaymentOut:
    payment = payments_service.create_payment(
        session,
        company_id,
        payments_service.PaymentData(**body.model_dump()),
        actor=_actor(caller),
    )
    return _payment(payment)


@router.patch(
    "/payments/{payment_id}",
    response_model=PaymentOut,
    dependencies=[requires("payment:manage")],
)
@needs("payment:manage")
def update_payment(
    company_id: UUID,
    payment_id: UUID,
    body: PaymentIn,
    caller: CallerDep,
    session: SessionDep,
) -> PaymentOut:
    payment = payments_service.update_payment(
        session,
        company_id,
        payment_id,
        payments_service.PaymentData(**body.model_dump()),
        actor=_actor(caller),
    )
    return _payment(payment)


@router.delete(
    "/payments/{payment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[requires("payment:manage")],
)
@needs("payment:manage")
def delete_payment(
    company_id: UUID, payment_id: UUID, caller: CallerDep, session: SessionDep
) -> None:
    payments_service.delete_payment(session, company_id, payment_id, actor=_actor(caller))


@router.post(
    "/payments/{payment_id}/post",
    response_model=PaymentOut,
    dependencies=[requires("payment:post")],
)
@needs("payment:post")
def post_payment(
    company_id: UUID, payment_id: UUID, caller: CallerDep, session: SessionDep
) -> PaymentOut:
    payment = payments_service.post_payment(session, company_id, payment_id, actor=_actor(caller))
    return _payment(payment)


@router.post(
    "/payments/{payment_id}/cancel",
    response_model=PaymentOut,
    dependencies=[requires("payment:post")],
)
@needs("payment:post")
def cancel_payment(
    company_id: UUID,
    payment_id: UUID,
    body: CancelIn,
    caller: CallerDep,
    session: SessionDep,
) -> PaymentOut:
    payment = payments_service.cancel_payment(
        session, company_id, payment_id, reason=body.reason, actor=_actor(caller)
    )
    return _payment(payment)


@router.get(
    "/payments/{payment_id}/suggestions",
    response_model=list[SuggestionOut],
    dependencies=[requires("payment:read")],
)
@needs("payment:read")
def payment_suggestions(
    company_id: UUID, payment_id: UUID, session: SessionDep
) -> list[SuggestionOut]:
    payment = payments_service.get_payment(session, company_id, payment_id)
    return [
        SuggestionOut(
            line_id=suggestion.line.id,
            entry_number=suggestion.entry_number,
            amount=suggestion.amount,
            reason=suggestion.reason,
        )
        for suggestion in matching_service.suggest_for_payment(session, company_id, payment)
    ]


# ------------------------------------------------------------------ matching


@router.get(
    "/open-items", response_model=list[OpenItemOut], dependencies=[requires("payment:read")]
)
@needs("payment:read")
def list_open_items(
    company_id: UUID,
    session: SessionDep,
    partner_id: UUID | None = None,
    account_id: UUID | None = None,
    currency_code: str | None = None,
) -> list[OpenItemOut]:
    items = matching_service.open_lines(
        session,
        company_id,
        partner_id=partner_id,
        account_id=account_id,
        currency_code=currency_code,
    )
    return [_open_item(item) for item in items]


@router.post(
    "/reconciliations",
    response_model=list[MatchOut],
    status_code=status.HTTP_201_CREATED,
    dependencies=[requires("payment:post")],
)
@needs("payment:post")
def match(
    company_id: UUID, body: MatchIn, caller: CallerDep, session: SessionDep
) -> list[MatchOut]:
    actor = _actor(caller)
    if body.debit_line_id is not None and body.credit_line_id is not None:
        return [
            _match(
                matching_service.match_amount(
                    session,
                    company_id,
                    body.debit_line_id,
                    body.credit_line_id,
                    body.amount,
                    actor=actor,
                )
            )
        ]

    matches = matching_service.match_lines(session, company_id, body.line_ids, actor=actor)
    return [_match(reconciliation) for reconciliation in matches]


@router.delete(
    "/reconciliations/{reconciliation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[requires("payment:post")],
)
@needs("payment:post")
def unmatch(
    company_id: UUID, reconciliation_id: UUID, caller: CallerDep, session: SessionDep
) -> None:
    matching_service.unmatch(session, company_id, [reconciliation_id], actor=_actor(caller))


@router.get(
    "/documents/{document_id}/payment-state",
    response_model=PaymentStateOut,
    dependencies=[requires("payment:read")],
)
@needs("payment:read")
def document_payment_state(
    company_id: UUID, document_id: UUID, session: SessionDep
) -> PaymentStateOut:
    from app.billing.documents import get_document

    document = get_document(session, company_id, document_id)
    state = state_service.payment_state_of(session, document)
    return PaymentStateOut(
        state=state.state,
        total=state.total,
        paid=state.paid,
        open_amount=state.open_amount,
        payments=[
            {
                "id": str(entry.payment.id),
                "number": entry.payment.number,
                "amount": str(entry.amount),
            }
            for entry in state.payments
        ],
    )


# ------------------------------------------------------------------ statements


@router.post(
    "/bank-statements/import",
    response_model=ImportOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[requires("statement:import")],
)
@needs("statement:import")
def import_bank_statement(
    company_id: UUID,
    caller: CallerDep,
    session: SessionDep,
    bank_account_id: Annotated[UUID, Form()],
    source_format: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    mapping: Annotated[str | None, Form()] = None,
    name: Annotated[str | None, Form()] = None,
) -> ImportOut:
    """A multipart upload: the bank's file, and for CSV the column mapping as JSON."""
    import json

    from app.shared.errors import DomainError

    columns: dict[str, str] | None = None
    if mapping:
        try:
            columns = json.loads(mapping)
        except json.JSONDecodeError as exc:
            raise DomainError(
                "payments.unreadable_file", "the column mapping is not valid JSON"
            ) from exc

    result = reconciling_service.import_statement(
        session,
        company_id,
        bank_account_id,
        _source(source_format, columns),
        file.file.read(),
        name=name,
        file_name=file.filename,
        actor=_actor(caller),
    )
    return ImportOut(
        statement_id=result.statement_id,
        created=result.created,
        duplicates=result.duplicates,
        rejected=result.rejected,
    )


@router.get(
    "/bank-statements",
    response_model=list[StatementOut],
    dependencies=[requires("payment:read")],
)
@needs("payment:read")
def list_bank_statements(company_id: UUID, session: SessionDep) -> list[StatementOut]:
    return [
        StatementOut(
            id=statement.id,
            bank_account_id=statement.bank_account_id,
            name=statement.name,
            source_format=statement.source_format,
            file_name=statement.file_name,
            opening_balance=statement.opening_balance,
            closing_balance=statement.closing_balance,
        )
        for statement in reconciling_service.list_statements(session, company_id)
    ]


@router.get(
    "/bank-statements/{statement_id}/lines",
    response_model=list[StatementLineOut],
    dependencies=[requires("payment:read")],
)
@needs("payment:read")
def list_statement_lines(
    company_id: UUID, statement_id: UUID, session: SessionDep
) -> list[StatementLineOut]:
    statement = reconciling_service.get_statement(session, company_id, statement_id)
    return [_statement_line(line) for line in statement.lines]


@router.get(
    "/bank-statement-lines",
    response_model=list[StatementLineOut],
    dependencies=[requires("payment:read")],
)
@needs("payment:read")
def list_unreconciled_lines(
    company_id: UUID, session: SessionDep, bank_account_id: UUID | None = None
) -> list[StatementLineOut]:
    lines = reconciling_service.unreconciled_lines(
        session, company_id, bank_account_id=bank_account_id
    )
    return [_statement_line(line) for line in lines]


@router.post(
    "/bank-statement-lines/{line_id}/reconcile",
    response_model=StatementLineOut,
    dependencies=[requires("payment:post")],
)
@needs("payment:post")
def reconcile_statement_line(
    company_id: UUID,
    line_id: UUID,
    body: ReconcileIn,
    caller: CallerDep,
    session: SessionDep,
) -> StatementLineOut:
    line = reconciling_service.reconcile_line(
        session, company_id, line_id, payment_id=body.payment_id, actor=_actor(caller)
    )
    return _statement_line(line)


@router.post(
    "/bank-statement-lines/{line_id}/undo",
    response_model=StatementLineOut,
    dependencies=[requires("payment:post")],
)
@needs("payment:post")
def undo_statement_line(
    company_id: UUID, line_id: UUID, caller: CallerDep, session: SessionDep
) -> StatementLineOut:
    line = reconciling_service.undo_reconcile(session, company_id, line_id, actor=_actor(caller))
    return _statement_line(line)


@router.get(
    "/bank-statement-lines/{line_id}/suggestions",
    response_model=list[LineSuggestionOut],
    dependencies=[requires("payment:read")],
)
@needs("payment:read")
def statement_line_suggestions(
    company_id: UUID, line_id: UUID, session: SessionDep
) -> list[LineSuggestionOut]:
    return [
        LineSuggestionOut(
            payment_id=suggestion.payment.id,
            number=suggestion.payment.number,
            date=suggestion.payment.date,
            amount=suggestion.payment.net_amount,
            reason=suggestion.reason,
        )
        for suggestion in reconciling_service.suggest_for_statement_line(
            session, company_id, line_id
        )
    ]
