"""Recording and posting payments (R1, R2, R9).

A payment is money in or out, recorded before anyone decides which invoices it settles. It
is a draft until posted; posting builds one `PostingRequest` and hands it to the ledger,
which owns numbering, balance and immutability. Nothing here writes a journal line itself.

Posting deliberately does not touch the bank account. An inbound payment debits *outstanding
receipts* — money we believe is on its way — and the bank account moves only when the bank's
own statement line is reconciled (R2.AC1, R8.AC1). That is what makes the bank balance in
the books defensible: it is what the bank says, not what we hope has cleared.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.partners import get_partner
from app.billing.taxes import get_tax
from app.coa.defaults import get_defaults
from app.ledger.api import Journal, PostingLine, PostingRequest, currency_places, post, reverse
from app.platform.audit.api import Actor, record
from app.shared.errors import DomainError
from app.shared.ids import uuid7
from app.shared.money import ZERO, quantize
from app.treasury.models import (
    DIRECTIONS,
    JOURNAL_TYPES,
    OUTSTANDING_DEFAULT,
    PARTNER_DEFAULT,
    Payment,
)


@dataclass(frozen=True, slots=True)
class PaymentData:
    direction: str
    partner_id: UUID
    journal_id: UUID
    date: date
    amount: Decimal
    currency_code: str = "SAR"
    withholding_tax_id: UUID | None = None
    reference: str | None = None
    memo: str | None = None


def now() -> datetime:
    return datetime.now(UTC)


def get_payment(session: Session, company_id: UUID, payment_id: UUID) -> Payment:
    payment = session.execute(
        select(Payment).where(Payment.id == payment_id, Payment.company_id == company_id)
    ).scalar_one_or_none()
    if payment is None:
        raise DomainError("payments.payment_not_found", f"payment {payment_id} not found")
    return payment


def list_payments(
    session: Session,
    company_id: UUID,
    *,
    partner_id: UUID | None = None,
    state: str | None = None,
    direction: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Payment]:
    """Newest first: an accountant is nearly always looking at what just happened
    (R10.AC1)."""
    query = select(Payment).where(Payment.company_id == company_id)
    if partner_id is not None:
        query = query.where(Payment.partner_id == partner_id)
    if state is not None:
        query = query.where(Payment.state == state)
    if direction is not None:
        query = query.where(Payment.direction == direction)
    query = query.order_by(Payment.date.desc(), Payment.created_at.desc())
    return list(session.execute(query.limit(limit).offset(offset)).scalars())


def create_payment(
    session: Session, company_id: UUID, data: PaymentData, *, actor: Actor | None = None
) -> Payment:
    """R1.AC1 — stored as a draft, so nothing reaches the books yet."""
    _validate(session, company_id, data)

    payment = Payment(
        id=uuid7(),
        company_id=company_id,
        direction=data.direction,
        partner_id=data.partner_id,
        journal_id=data.journal_id,
        date=data.date,
        amount=data.amount,
        currency_code=data.currency_code,
        withholding_tax_id=data.withholding_tax_id,
        withheld_amount=_withheld(session, company_id, data),
        reference=data.reference,
        memo=data.memo,
        state="draft",
    )
    session.add(payment)
    session.flush()

    record(
        session,
        action="payment.created",
        actor=actor,
        company_id=company_id,
        target_type="payment",
        target_id=payment.id,
        detail={
            "direction": payment.direction,
            "amount": str(payment.amount),
            "currency": payment.currency_code,
        },
    )
    return payment


def update_payment(
    session: Session,
    company_id: UUID,
    payment_id: UUID,
    data: PaymentData,
    *,
    actor: Actor | None = None,
) -> Payment:
    """R1.AC3 — a draft is still being written; a posted payment is evidence (R2.AC9)."""
    payment = get_payment(session, company_id, payment_id)
    _require_draft(payment, "changed")
    _validate(session, company_id, data)

    payment.direction = data.direction
    payment.partner_id = data.partner_id
    payment.journal_id = data.journal_id
    payment.date = data.date
    payment.amount = data.amount
    payment.currency_code = data.currency_code
    payment.withholding_tax_id = data.withholding_tax_id
    payment.withheld_amount = _withheld(session, company_id, data)
    payment.reference = data.reference
    payment.memo = data.memo
    session.flush()
    return payment


def delete_payment(
    session: Session, company_id: UUID, payment_id: UUID, *, actor: Actor | None = None
) -> None:
    """R1.AC7"""
    payment = get_payment(session, company_id, payment_id)
    _require_draft(payment, "deleted")
    session.delete(payment)
    session.flush()

    record(
        session,
        action="payment.deleted",
        actor=actor,
        company_id=company_id,
        target_type="payment",
        target_id=payment_id,
        detail={"amount": str(payment.amount)},
    )


def post_payment(
    session: Session, company_id: UUID, payment_id: UUID, *, actor: Actor | None = None
) -> Payment:
    """R2 — one entry, a gapless number, and the partner's balance moved."""
    payment = get_payment(session, company_id, payment_id)
    if payment.state == "posted":
        raise DomainError("payments.already_posted", f"{payment.number} is already posted")
    if payment.state == "cancelled":
        raise DomainError("payments.already_cancelled", "a cancelled payment cannot be posted")

    entry = post(session, build_posting_request(session, payment))

    payment.state = "posted"
    payment.number = entry.number
    payment.journal_entry_id = entry.id
    payment.posted_at = now()
    session.flush()

    record(
        session,
        action="payment.posted",
        actor=actor,
        company_id=company_id,
        target_type="payment",
        target_id=payment.id,
        detail={
            "number": payment.number,
            "amount": str(payment.amount),
            "currency": payment.currency_code,
            "entry": str(entry.id),
        },
    )
    return payment


def cancel_payment(
    session: Session,
    company_id: UUID,
    payment_id: UUID,
    *,
    reason: str | None = None,
    actor: Actor | None = None,
) -> Payment:
    """R2.AC10 — undo the matches, reverse the entry, and say why."""
    from app.treasury.matching import unmatch_payment

    payment = get_payment(session, company_id, payment_id)
    if payment.state == "cancelled":
        raise DomainError("payments.already_cancelled", f"{payment.number} is already cancelled")
    if payment.state != "posted":
        raise DomainError("payments.not_posted", "only a posted payment can be cancelled")

    unmatch_payment(session, company_id, payment, actor=actor)
    reversal = reverse(
        session,
        company_id,
        payment.journal_entry_id,
        ref=f"Cancellation of {payment.number}",
    )
    payment.state = "cancelled"
    payment.cancelled_at = now()
    payment.cancel_reason = reason
    session.flush()

    record(
        session,
        action="payment.cancelled",
        actor=actor,
        company_id=company_id,
        target_type="payment",
        target_id=payment.id,
        detail={
            "number": payment.number,
            "amount": str(payment.amount),
            "reason": reason,
            "reversal": str(reversal.id),
        },
    )
    return payment


def build_posting_request(session: Session, payment: Payment) -> PostingRequest:
    """One entry: the partner's account, the outstanding account, and any tax withheld.

    Amounts are positive; what changes is the side they land on. An inbound payment debits
    outstanding receipts and credits the receivable; an outbound payment does the reverse
    (R2.AC1, R2.AC2).
    """
    accounts = get_defaults(session, payment.company_id).accounts
    outstanding = accounts.get(OUTSTANDING_DEFAULT[payment.direction])
    partner_account = accounts.get(PARTNER_DEFAULT[payment.direction])

    if outstanding is None or partner_account is None:
        missing = OUTSTANDING_DEFAULT[payment.direction] if outstanding is None else "partner"
        raise DomainError(
            "payments.default_account_missing",
            f"the company has no {missing.replace('_', ' ')} account",
        )

    lines = [
        # The partner side settles the invoice or bill in full, tax withheld included
        # (R2.AC4, R9.AC3).
        PostingLine(
            account_id=partner_account,
            partner_id=payment.partner_id,
            due_date=payment.date,
            name=f"Payment {payment.number or ''}".strip(),
            debit=ZERO if payment.is_inbound else payment.amount,
            credit=payment.amount if payment.is_inbound else ZERO,
        ),
        # What actually moves: the amount less anything withheld (R9.AC2).
        PostingLine(
            account_id=outstanding,
            name=f"Payment {payment.number or ''}".strip(),
            debit=payment.net_amount if payment.is_inbound else ZERO,
            credit=ZERO if payment.is_inbound else payment.net_amount,
        ),
    ]

    if payment.withheld_amount > ZERO:
        tax = get_tax(session, payment.company_id, payment.withholding_tax_id)
        if tax.account_id is None:
            raise DomainError(
                "tax.account_not_found", f"{tax.name} has no account to post the withholding to"
            )
        lines.append(
            PostingLine(
                account_id=tax.account_id,
                name=tax.name,
                tax_id=tax.id,
                tax_grid_tag=tax.grid_tag,
                debit=payment.withheld_amount if payment.is_inbound else ZERO,
                credit=ZERO if payment.is_inbound else payment.withheld_amount,
            )
        )

    return PostingRequest(
        company_id=payment.company_id,
        journal_id=payment.journal_id,
        date=payment.date,
        currency_code=payment.currency_code,
        lines=lines,
        ref=payment.reference,
        narration=payment.memo,
        source_type="payment",
        source_id=payment.id,
    )


def _validate(session: Session, company_id: UUID, data: PaymentData) -> None:
    if data.direction not in DIRECTIONS:
        raise DomainError(
            "payments.invalid_direction", f"{data.direction!r} is not a payment direction"
        )
    if data.amount <= ZERO:
        raise DomainError("payments.invalid_amount", "a payment must be for more than nothing")

    places = currency_places(session, data.currency_code)
    if data.amount != quantize(data.amount, places):
        raise DomainError(
            "payments.invalid_amount",
            f"{data.currency_code} amounts have at most {places} decimal places",
        )

    try:
        get_partner(session, company_id, data.partner_id)
    except DomainError as exc:
        raise DomainError("payments.partner_not_found", exc.message) from exc

    journal = session.execute(
        select(Journal).where(Journal.id == data.journal_id, Journal.company_id == company_id)
    ).scalar_one_or_none()
    if journal is None:
        raise DomainError("payments.journal_not_found", f"journal {data.journal_id} not found")
    if journal.type not in JOURNAL_TYPES:
        raise DomainError(
            "payments.wrong_journal_type",
            f"{journal.code} is a {journal.type} journal; a payment needs a bank or cash journal",
        )


def _withheld(session: Session, company_id: UUID, data: PaymentData) -> Decimal:
    """R9.AC1 — the withheld amount follows from the tax, so nobody can mistype it."""
    if data.withholding_tax_id is None:
        return ZERO

    tax = get_tax(session, company_id, data.withholding_tax_id)
    if tax.type != "withholding":
        raise DomainError(
            "payments.wrong_tax_type", f"{tax.name} is a {tax.type} tax, not a withholding tax"
        )

    places = currency_places(session, data.currency_code)
    withheld = quantize(data.amount * tax.rate / Decimal(100), places)
    if withheld >= data.amount:
        raise DomainError("payments.invalid_amount", "withholding cannot take the whole payment")
    return withheld


def _require_draft(payment: Payment, verb: str) -> None:
    if payment.state != "draft":
        raise DomainError(
            "payments.posted_immutable", f"a {payment.state} payment cannot be {verb}"
        )
