"""Matching open items (R3, R4) and the exchange differences matching realises (R5).

One service, one lock order. Lines are locked `FOR UPDATE` by id ascending, so two clerks
matching the same invoice queue instead of both spending it, and the deferred residual
trigger rejects an over-match even if something bypasses this module entirely (R11.AC4).

A match is a pair: one debit line, one credit line, and how much of each it settles. That
is enough to express a payment covering several invoices, several payments covering one
invoice, and a credit note cancelling part of a bill.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.coa.defaults import get_defaults
from app.ledger.api import (
    JournalEntry,
    JournalEntryLine,
    PostingLine,
    PostingRequest,
    currency_places,
    post,
    reverse,
)
from app.platform.audit.api import Actor, record
from app.platform.tenancy.api import Company
from app.shared.errors import DomainError
from app.shared.money import ZERO, quantize
from app.treasury.exchange import MatchedSide, difference_between
from app.treasury.models import Payment, Reconciliation


@dataclass(frozen=True, slots=True)
class OpenLine:
    """An open item as the matching screen needs to show it."""

    line: JournalEntryLine
    entry_number: str | None
    entry_date: object

    @property
    def is_debit(self) -> bool:
        return self.line.debit > self.line.credit


def open_lines(
    session: Session,
    company_id: UUID,
    *,
    partner_id: UUID | None = None,
    account_id: UUID | None = None,
    currency_code: str | None = None,
    limit: int = 200,
) -> list[OpenLine]:
    """What is still owed or owing, oldest first — an aged position straight from the
    ledger (NFR6)."""
    query = (
        select(JournalEntryLine, JournalEntry.number, JournalEntry.date)
        .join(JournalEntry, JournalEntry.id == JournalEntryLine.entry_id)
        .where(
            JournalEntryLine.company_id == company_id,
            JournalEntryLine.residual.is_not(None),
            JournalEntryLine.reconciled.is_(False),
            JournalEntry.state == "posted",
        )
        .order_by(JournalEntry.date, JournalEntry.number)
        .limit(limit)
    )
    if partner_id is not None:
        query = query.where(JournalEntryLine.partner_id == partner_id)
    if account_id is not None:
        query = query.where(JournalEntryLine.account_id == account_id)
    if currency_code is not None:
        query = query.where(JournalEntryLine.currency_code == currency_code)

    return [
        OpenLine(line=line, entry_number=number, entry_date=entry_date)
        for line, number, entry_date in session.execute(query).all()
    ]


def match_amount(
    session: Session,
    company_id: UUID,
    debit_line_id: UUID,
    credit_line_id: UUID,
    amount: Decimal | None = None,
    *,
    actor: Actor | None = None,
) -> Reconciliation:
    """Settle one debit against one credit. ``amount`` defaults to as much as both can take.

    The amount is in the lines' own currency when they share one, and in company currency
    otherwise.
    """
    if debit_line_id == credit_line_id:
        raise DomainError("payments.same_line", "a line cannot settle itself")

    debit, credit = _lock(session, company_id, [debit_line_id, credit_line_id])
    _check_pair(debit, credit)

    company = session.get(Company, company_id)
    base = company.base_currency
    shared_currency = debit.currency_code == credit.currency_code
    places = currency_places(session, debit.currency_code if shared_currency else base)

    available = (
        min(debit.residual_currency, credit.residual_currency)
        if shared_currency
        else min(debit.residual, credit.residual)
    )
    take = available if amount is None else quantize(amount, places)
    if take <= ZERO:
        raise DomainError("payments.invalid_amount", "a match must be for more than nothing")
    if take > available:
        raise DomainError(
            "payments.over_matched",
            f"only {available} is open on these lines, not {take}",
        )

    reconciliation = _write_match(session, debit, credit, take, shared=shared_currency)
    _post_difference(session, company_id, reconciliation, debit, credit, base=base)

    record(
        session,
        action="reconciliation.matched",
        actor=actor,
        company_id=company_id,
        target_type="reconciliation",
        target_id=reconciliation.id,
        detail={
            "debit_line": str(debit.id),
            "credit_line": str(credit.id),
            "amount": str(reconciliation.debit_amount),
        },
    )
    return reconciliation


def match_lines(
    session: Session,
    company_id: UUID,
    line_ids: Sequence[UUID],
    *,
    actor: Actor | None = None,
) -> list[Reconciliation]:
    """Match a set of lines against each other, oldest first (R4.AC1, R4.AC2).

    The usual call: an accountant ticks a payment and the invoices it covers, and the
    service works out the pairs.
    """
    if len(set(line_ids)) < 2:
        raise DomainError("payments.invalid_match", "matching needs at least two lines")

    lines = _lock(session, company_id, line_ids)
    for line in lines:
        _check_open(line)
    _check_one_partner(lines)

    debits = [line for line in lines if line.debit > line.credit]
    credits = [line for line in lines if line.credit > line.debit]
    if not debits or not credits:
        raise DomainError(
            "payments.same_side", "matching needs at least one debit and one credit line"
        )

    matches: list[Reconciliation] = []
    for debit in debits:
        for credit in credits:
            if debit.reconciled or credit.reconciled:
                continue
            if debit.residual <= ZERO or credit.residual <= ZERO:
                continue
            matches.append(
                match_amount(session, company_id, debit.id, credit.id, None, actor=actor)
            )
    return matches


def unmatch(
    session: Session,
    company_id: UUID,
    reconciliation_ids: Sequence[UUID],
    *,
    actor: Actor | None = None,
) -> None:
    """Reopen what a match closed, and reverse the exchange difference it caused
    (R4.AC8, R5.AC6)."""
    for reconciliation_id in reconciliation_ids:
        reconciliation = session.execute(
            select(Reconciliation)
            .where(
                Reconciliation.id == reconciliation_id,
                Reconciliation.company_id == company_id,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if reconciliation is None:
            raise DomainError(
                "payments.reconciliation_not_found", f"match {reconciliation_id} not found"
            )
        _undo(session, company_id, reconciliation, actor=actor)


def unmatch_payment(
    session: Session, company_id: UUID, payment: Payment, *, actor: Actor | None = None
) -> None:
    """Undo everything a payment settled, so cancelling it leaves no invoice looking paid
    (R2.AC10)."""
    if payment.journal_entry_id is None:
        return

    line_ids = set(
        session.execute(
            select(JournalEntryLine.id).where(JournalEntryLine.entry_id == payment.journal_entry_id)
        ).scalars()
    )
    if not line_ids:
        return

    matches = session.execute(
        select(Reconciliation)
        .where(
            Reconciliation.company_id == company_id,
            Reconciliation.debit_line_id.in_(line_ids)
            | Reconciliation.credit_line_id.in_(line_ids),
        )
        .with_for_update()
    ).scalars()
    for reconciliation in list(matches):
        _undo(session, company_id, reconciliation, actor=actor)


def matches_for_lines(
    session: Session, company_id: UUID, line_ids: Iterable[UUID]
) -> list[Reconciliation]:
    ids = set(line_ids)
    if not ids:
        return []
    return list(
        session.execute(
            select(Reconciliation).where(
                Reconciliation.company_id == company_id,
                Reconciliation.debit_line_id.in_(ids) | Reconciliation.credit_line_id.in_(ids),
            )
        ).scalars()
    )


def _undo(
    session: Session,
    company_id: UUID,
    reconciliation: Reconciliation,
    *,
    actor: Actor | None,
) -> None:
    debit, credit = _lock(
        session, company_id, [reconciliation.debit_line_id, reconciliation.credit_line_id]
    )
    if reconciliation.fx_entry_id is not None:
        reverse(
            session,
            company_id,
            reconciliation.fx_entry_id,
            ref="Reversal of an exchange difference",
        )

    _reopen(debit, reconciliation.debit_amount, reconciliation.debit_amount_currency)
    _reopen(credit, reconciliation.credit_amount, reconciliation.credit_amount_currency)
    session.delete(reconciliation)
    session.flush()

    record(
        session,
        action="reconciliation.unmatched",
        actor=actor,
        company_id=company_id,
        target_type="reconciliation",
        target_id=reconciliation.id,
        detail={
            "debit_line": str(debit.id),
            "credit_line": str(credit.id),
            "amount": str(reconciliation.debit_amount),
        },
    )


def _write_match(
    session: Session,
    debit: JournalEntryLine,
    credit: JournalEntryLine,
    take: Decimal,
    *,
    shared: bool,
) -> Reconciliation:
    """Take ``take`` off both sides and record what each side gave up.

    When the lines share a currency, ``take`` is in that currency and each side's
    company-currency share is proportional to what it had open — so settling a line in full
    closes it exactly, with no rounding dust left behind.
    """
    from app.shared.ids import uuid7

    if shared:
        debit_amount = _company_share(debit, take)
        credit_amount = _company_share(credit, take)
        debit_currency = credit_currency = take
    else:
        debit_amount = credit_amount = take
        debit_currency = _currency_share(debit, take)
        credit_currency = _currency_share(credit, take)

    reconciliation = Reconciliation(
        id=uuid7(),
        company_id=debit.company_id,
        debit_line_id=debit.id,
        credit_line_id=credit.id,
        debit_amount=debit_amount,
        credit_amount=credit_amount,
        debit_amount_currency=debit_currency,
        credit_amount_currency=credit_currency,
    )
    session.add(reconciliation)

    _close(debit, debit_amount, debit_currency)
    _close(credit, credit_amount, credit_currency)
    session.flush()
    return reconciliation


def _company_share(line: JournalEntryLine, take: Decimal) -> Decimal:
    """What ``take`` of this line's own currency is worth in company currency."""
    if line.residual_currency == ZERO:
        return ZERO
    if take == line.residual_currency:
        return line.residual
    places = _places_of(line.residual)
    return quantize(line.residual * take / line.residual_currency, places)


def _currency_share(line: JournalEntryLine, take: Decimal) -> Decimal:
    if line.residual == ZERO:
        return ZERO
    if take == line.residual:
        return line.residual_currency
    places = _places_of(line.residual_currency)
    return quantize(line.residual_currency * take / line.residual, places)


def _places_of(amount: Decimal) -> int:
    exponent = amount.as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 2


def _close(line: JournalEntryLine, amount: Decimal, amount_currency: Decimal) -> None:
    line.residual -= amount
    line.residual_currency -= amount_currency
    # R3.AC3 — closed is closed in both currencies.
    line.reconciled = line.residual == ZERO and line.residual_currency == ZERO


def _reopen(line: JournalEntryLine, amount: Decimal, amount_currency: Decimal) -> None:
    line.residual += amount
    line.residual_currency += amount_currency
    line.reconciled = line.residual == ZERO and line.residual_currency == ZERO


def _post_difference(
    session: Session,
    company_id: UUID,
    reconciliation: Reconciliation,
    debit: JournalEntryLine,
    credit: JournalEntryLine,
    *,
    base: str,
) -> None:
    """The gap between the two sides is a realised gain or loss (R5)."""
    difference = difference_between(
        MatchedSide(
            amount=reconciliation.debit_amount,
            amount_currency=reconciliation.debit_amount_currency,
            currency_code=debit.currency_code,
        ),
        MatchedSide(
            amount=reconciliation.credit_amount,
            amount_currency=reconciliation.credit_amount_currency,
            currency_code=credit.currency_code,
        ),
        base_currency=base,
    )
    if difference is None:
        return

    accounts = get_defaults(session, company_id).accounts
    account_id = accounts.get(difference.default_key)
    if account_id is None:
        raise DomainError(
            "payments.fx_account_missing",
            f"the company has no exchange {'gain' if difference.is_gain else 'loss'} account",
        )

    # Both lines are on the same account; the difference brings that account's
    # company-currency balance to zero, and the other half is the gain or loss.
    entry_date = max(_date_of(session, debit), _date_of(session, credit))

    lines = [
        PostingLine(
            account_id=debit.account_id,
            partner_id=debit.partner_id or credit.partner_id,
            name="Exchange difference",
            debit=difference.amount if difference.is_gain else ZERO,
            credit=ZERO if difference.is_gain else difference.amount,
            # Not an open item: it settles the account rather than opening anything on it.
            open_item=False,
        ),
        PostingLine(
            account_id=account_id,
            name="Exchange difference",
            debit=ZERO if difference.is_gain else difference.amount,
            credit=difference.amount if difference.is_gain else ZERO,
        ),
    ]
    entry = post(
        session,
        PostingRequest(
            company_id=company_id,
            journal_id=_difference_journal(session, company_id),
            date=entry_date,
            currency_code=base,
            lines=lines,
            ref="Exchange difference",
            source_type="reconciliation",
            source_id=reconciliation.id,
        ),
    )
    # R5.AC4 — the difference is findable from the match that caused it.
    reconciliation.fx_entry_id = entry.id
    session.flush()


def _difference_journal(session: Session, company_id: UUID) -> UUID:
    from app.ledger.api import Journal

    journal_id = session.execute(
        select(Journal.id)
        .where(Journal.company_id == company_id, Journal.type == "general", Journal.active)
        .order_by(Journal.code)
        .limit(1)
    ).scalar_one_or_none()
    if journal_id is None:
        raise DomainError(
            "payments.no_general_journal",
            "an exchange difference needs a general journal to post to",
        )
    return journal_id


def _date_of(session: Session, line: JournalEntryLine):
    return session.execute(
        select(JournalEntry.date).where(JournalEntry.id == line.entry_id)
    ).scalar_one()


def _lock(session: Session, company_id: UUID, line_ids: Sequence[UUID]) -> list[JournalEntryLine]:
    """Lock the lines in a fixed order, so concurrent matches queue rather than deadlock
    (R11.AC4)."""
    wanted = sorted(set(line_ids), key=str)
    lines = list(
        session.execute(
            select(JournalEntryLine)
            .where(
                JournalEntryLine.id.in_(wanted),
                JournalEntryLine.company_id == company_id,
            )
            .order_by(JournalEntryLine.id)
            .with_for_update()
        ).scalars()
    )
    if len(lines) != len(wanted):
        found = {line.id for line in lines}
        missing = next(iter(set(wanted) - found))
        raise DomainError("payments.line_not_found", f"line {missing} not found")

    order = {line_id: index for index, line_id in enumerate(line_ids)}
    return sorted(lines, key=lambda line: order[line.id])


def _check_pair(debit: JournalEntryLine, credit: JournalEntryLine) -> None:
    _check_open(debit)
    _check_open(credit)
    if debit.debit <= debit.credit or credit.credit <= credit.debit:
        raise DomainError("payments.same_side", "a match needs one debit line and one credit line")
    _check_one_partner([debit, credit])
    if debit.account_id != credit.account_id:
        raise DomainError(
            "payments.account_mismatch",
            "a match settles two lines on the same account",
        )


def _check_open(line: JournalEntryLine) -> None:
    if line.residual is None:
        raise DomainError(
            "payments.not_reconcilable",
            f"line {line.id} is not on an account that keeps open items",
        )
    if line.reconciled or line.residual <= ZERO:
        raise DomainError("payments.already_reconciled", f"line {line.id} has nothing open")


def _check_one_partner(lines: Sequence[JournalEntryLine]) -> None:
    """R4.AC5 — one customer's payment cannot settle another customer's invoice."""
    partners = {line.partner_id for line in lines if line.partner_id is not None}
    if len(partners) > 1:
        raise DomainError("payments.partner_mismatch", "these lines belong to different partners")


@dataclass(frozen=True, slots=True)
class Suggestion:
    """An open line that probably belongs to what the caller is looking at (R4.AC9)."""

    line: JournalEntryLine
    entry_number: str | None
    amount: Decimal
    """How much of the line this match could settle."""

    reason: str


def suggest_for_payment(
    session: Session, company_id: UUID, payment: Payment, *, limit: int = 20
) -> list[Suggestion]:
    """The partner's open items on the other side, oldest first (R4.AC9).

    Deliberately not automatic matching: a suggestion is a shortlist for a person, so the
    rule stays one an accountant can predict — same partner, opposite side, oldest first,
    with an exact-amount match promoted to the top.
    """
    if payment.journal_entry_id is None:
        return []

    our_lines = [
        line
        for line in open_lines(session, company_id, partner_id=payment.partner_id)
        if line.line.entry_id == payment.journal_entry_id
    ]
    if not our_lines:
        return []

    ours = our_lines[0]
    candidates = [
        candidate
        for candidate in open_lines(session, company_id, partner_id=payment.partner_id)
        if candidate.line.entry_id != payment.journal_entry_id
        and candidate.line.account_id == ours.line.account_id
        and candidate.is_debit != ours.is_debit
    ]

    suggestions = [
        Suggestion(
            line=candidate.line,
            entry_number=candidate.entry_number,
            amount=min(candidate.line.residual, ours.line.residual),
            reason=(
                "the amount matches exactly"
                if candidate.line.residual == ours.line.residual
                else "the same partner has this open"
            ),
        )
        for candidate in candidates
    ]
    # An exact amount is the strongest signal an accountant has; everything else stays in
    # date order behind it.
    suggestions.sort(key=lambda s: s.reason != "the amount matches exactly")
    return suggestions[:limit]
