"""What a document's payment state is (R6).

Derived on read, never stored. A cached state would be one more thing that can disagree with
the ledger; the open amounts on the document's own entry already say everything, and the
invoicing feature settled on the same rule for totals.
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.models import Document
from app.ledger.api import JournalEntry, JournalEntryLine
from app.shared.money import ZERO
from app.treasury.matching import matches_for_lines
from app.treasury.models import Payment

NOT_PAID = "not_paid"
PARTIAL = "partial"
PAID = "paid"
CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class SettledBy:
    """One payment, and what it contributed to this document."""

    payment: Payment
    amount: Decimal


@dataclass(frozen=True, slots=True)
class PaymentState:
    state: str
    total: Decimal
    """The document's open item in company currency."""

    paid: Decimal
    open_amount: Decimal
    payments: tuple[SettledBy, ...] = ()

    @property
    def is_paid(self) -> bool:
        return self.state == PAID


def payment_state_of(session: Session, document: Document) -> PaymentState:
    """R6.AC1 through R6.AC6"""
    if document.state == "cancelled":
        return PaymentState(state=CANCELLED, total=ZERO, paid=ZERO, open_amount=ZERO)
    if document.state != "posted" or document.journal_entry_id is None:
        return PaymentState(state=NOT_PAID, total=ZERO, paid=ZERO, open_amount=ZERO)

    open_items = list(
        session.execute(
            select(JournalEntryLine).where(
                JournalEntryLine.entry_id == document.journal_entry_id,
                JournalEntryLine.residual.is_not(None),
            )
        ).scalars()
    )
    if not open_items:
        return PaymentState(state=NOT_PAID, total=ZERO, paid=ZERO, open_amount=ZERO)

    total = sum((abs(line.debit - line.credit) for line in open_items), ZERO)
    still_open = sum((line.residual for line in open_items), ZERO)
    paid = total - still_open

    if still_open == total:
        state = NOT_PAID
    elif still_open == ZERO:
        state = PAID
    else:
        state = PARTIAL

    return PaymentState(
        state=state,
        total=total,
        paid=paid,
        open_amount=still_open,
        payments=_payments_behind(session, document.company_id, open_items),
    )


def _payments_behind(
    session: Session, company_id: UUID, open_items: list[JournalEntryLine]
) -> tuple[SettledBy, ...]:
    """Which payments settled this document, and by how much (R6.AC5)."""
    our_lines = {line.id for line in open_items}
    matches = matches_for_lines(session, company_id, our_lines)
    if not matches:
        return ()

    # The other side of each match: whatever settled us.
    other_lines: dict[UUID, Decimal] = {}
    for match in matches:
        if match.debit_line_id in our_lines:
            other_lines[match.credit_line_id] = (
                other_lines.get(match.credit_line_id, ZERO) + match.debit_amount
            )
        else:
            other_lines[match.debit_line_id] = (
                other_lines.get(match.debit_line_id, ZERO) + match.credit_amount
            )

    entry_of = dict(
        session.execute(
            select(JournalEntryLine.id, JournalEntryLine.entry_id).where(
                JournalEntryLine.id.in_(other_lines)
            )
        ).all()
    )
    payments = {
        payment.journal_entry_id: payment
        for payment in session.execute(
            select(Payment).where(
                Payment.company_id == company_id,
                Payment.journal_entry_id.in_(set(entry_of.values())),
            )
        ).scalars()
    }

    settled: dict[UUID, Decimal] = {}
    for line_id, amount in other_lines.items():
        payment = payments.get(entry_of.get(line_id))
        if payment is not None:
            settled[payment.id] = settled.get(payment.id, ZERO) + amount

    return tuple(
        SettledBy(payment=payment, amount=settled[payment.id])
        for payment in payments.values()
        if payment.id in settled
    )


def documents_settled_by(session: Session, company_id: UUID, payment: Payment) -> list[Document]:
    """Which documents a payment settled — the same relationship read the other way."""
    if payment.journal_entry_id is None:
        return []

    payment_lines = set(
        session.execute(
            select(JournalEntryLine.id).where(JournalEntryLine.entry_id == payment.journal_entry_id)
        ).scalars()
    )
    matches = matches_for_lines(session, company_id, payment_lines)
    other_lines = {
        match.credit_line_id if match.debit_line_id in payment_lines else match.debit_line_id
        for match in matches
    }
    if not other_lines:
        return []

    entry_ids = set(
        session.execute(
            select(JournalEntryLine.entry_id).where(JournalEntryLine.id.in_(other_lines))
        ).scalars()
    )
    return list(
        session.execute(
            select(Document)
            .join(JournalEntry, JournalEntry.id == Document.journal_entry_id)
            .where(Document.company_id == company_id, Document.journal_entry_id.in_(entry_ids))
            .order_by(Document.date)
        ).scalars()
    )
