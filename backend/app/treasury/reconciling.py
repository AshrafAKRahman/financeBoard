"""Importing a bank statement and reconciling its lines (R7, R8).

An imported line is the bank's claim, kept in its own table. It reaches the ledger only when
someone confirms it, and that entry is what finally moves the bank account: debit the bank,
credit outstanding receipts. Until then the bank balance in the books is the last thing the
bank actually told us.

Parsing lives in `statements`; this module does the part that needs a database.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.coa.accounts import get_account
from app.coa.defaults import get_defaults
from app.ledger.api import Journal, PostingLine, PostingRequest, post, reverse
from app.platform.audit.api import Actor, record
from app.shared.errors import DomainError
from app.shared.ids import uuid7
from app.shared.money import ZERO
from app.treasury.matching import match_amount
from app.treasury.models import BankStatement, BankStatementLine, Payment
from app.treasury.payments import get_payment
from app.treasury.statements import ImportResult, ParsedLine, StatementSource, line_hash


@dataclass(frozen=True, slots=True)
class LineSuggestion:
    """A payment a statement line probably is (R8.AC6)."""

    payment: Payment
    reason: str


def now() -> datetime:
    return datetime.now(UTC)


def import_statement(
    session: Session,
    company_id: UUID,
    bank_account_id: UUID,
    source: StatementSource,
    payload: bytes,
    *,
    name: str | None = None,
    file_name: str | None = None,
    actor: Actor | None = None,
) -> ImportResult:
    """R7 — parse first, then write. A file that cannot be read imports nothing."""
    account = get_account(session, company_id, bank_account_id)
    if account.subtype != "bank_cash":
        raise DomainError(
            "payments.not_a_bank_account", f"{account.code} is not a bank or cash account"
        )

    parsed = source.parse(payload)
    statement = BankStatement(
        id=uuid7(),
        company_id=company_id,
        bank_account_id=bank_account_id,
        name=name or file_name or f"{account.code} statement",
        source_format=source.format,
        file_name=file_name,
        opening_balance=parsed.opening_balance,
        closing_balance=parsed.closing_balance,
        imported_by=actor.user_id if actor else None,
    )
    session.add(statement)
    session.flush()

    running = parsed.opening_balance
    already = _existing_occurrences(session, company_id, bank_account_id)
    seen: Counter[str] = Counter()
    created = 0
    duplicates = 0

    for line_no, line in enumerate(parsed.lines, start=1):
        running = running + line.amount if running is not None else None
        fingerprint = line_hash(bank_account_id, line, running)
        seen[fingerprint] += 1
        # R7.AC4 — re-importing an overlapping file is normal, not an error. Counting
        # occurrences is what lets two identical payments on one day both through while a
        # re-import of the same file brings nothing.
        if seen[fingerprint] <= already[fingerprint]:
            duplicates += 1
            continue
        session.add(
            _row(
                session,
                statement,
                line,
                line_no=line_no,
                fingerprint=fingerprint,
                occurrence=seen[fingerprint],
            )
        )
        created += 1

    session.flush()
    result = ImportResult(
        statement_id=statement.id,
        created=created,
        duplicates=duplicates,
        rejected=parsed.rejected,
    )
    record(
        session,
        action="statement.imported",
        actor=actor,
        company_id=company_id,
        target_type="bank_statement",
        target_id=statement.id,
        detail={
            "file": file_name,
            "format": source.format,
            "created": created,
            "duplicates": duplicates,
            "rejected": len(parsed.rejected),
        },
    )
    return result


def get_statement(session: Session, company_id: UUID, statement_id: UUID) -> BankStatement:
    statement = session.execute(
        select(BankStatement).where(
            BankStatement.id == statement_id, BankStatement.company_id == company_id
        )
    ).scalar_one_or_none()
    if statement is None:
        raise DomainError("payments.statement_not_found", f"statement {statement_id} not found")
    return statement


def list_statements(session: Session, company_id: UUID, *, limit: int = 50) -> list[BankStatement]:
    return list(
        session.execute(
            select(BankStatement)
            .where(BankStatement.company_id == company_id)
            .order_by(BankStatement.imported_at.desc())
            .limit(limit)
        ).scalars()
    )


def get_statement_line(
    session: Session, company_id: UUID, line_id: UUID, *, lock: bool = False
) -> BankStatementLine:
    query = select(BankStatementLine).where(
        BankStatementLine.id == line_id, BankStatementLine.company_id == company_id
    )
    if lock:
        query = query.with_for_update()
    line = session.execute(query).scalar_one_or_none()
    if line is None:
        raise DomainError("payments.statement_line_not_found", f"line {line_id} not found")
    return line


def unreconciled_lines(
    session: Session, company_id: UUID, *, bank_account_id: UUID | None = None, limit: int = 200
) -> list[BankStatementLine]:
    """R7.AC8 — oldest first, because that is the order a bank is reconciled in."""
    query = (
        select(BankStatementLine)
        .join(BankStatement, BankStatement.id == BankStatementLine.statement_id)
        .where(
            BankStatementLine.company_id == company_id,
            BankStatementLine.reconciled_at.is_(None),
        )
        .order_by(BankStatementLine.date, BankStatementLine.line_no)
        .limit(limit)
    )
    if bank_account_id is not None:
        query = query.where(BankStatement.bank_account_id == bank_account_id)
    return list(session.execute(query).scalars())


def reconcile_line(
    session: Session,
    company_id: UUID,
    statement_line_id: UUID,
    *,
    payment_id: UUID,
    actor: Actor | None = None,
) -> BankStatementLine:
    """R8 — the bank account finally moves, and the payment leaves the holding account."""
    line = get_statement_line(session, company_id, statement_line_id, lock=True)
    if line.reconciled_at is not None:
        raise DomainError(
            "payments.already_reconciled", "this statement line is already reconciled"
        )

    payment = get_payment(session, company_id, payment_id)
    if payment.state != "posted":
        raise DomainError(
            "payments.not_posted", "only a posted payment can be matched to a statement line"
        )

    statement = get_statement(session, company_id, line.statement_id)
    _check_agrees(session, line, payment)
    entry = post(session, _entry_for(session, statement, line, payment))

    line.journal_entry_id = entry.id
    line.payment_id = payment.id
    line.reconciled_at = now()
    session.flush()

    _clear_outstanding(session, company_id, payment, entry, actor=actor)

    record(
        session,
        action="statement_line.reconciled",
        actor=actor,
        company_id=company_id,
        target_type="bank_statement_line",
        target_id=line.id,
        detail={
            "amount": str(line.amount),
            "payment": payment.number,
            "entry": str(entry.id),
        },
    )
    return line


def undo_reconcile(
    session: Session,
    company_id: UUID,
    statement_line_id: UUID,
    *,
    actor: Actor | None = None,
) -> BankStatementLine:
    """R8.AC5 — the entry is reversed, not deleted; the line goes back to unreconciled."""
    line = get_statement_line(session, company_id, statement_line_id, lock=True)
    if line.reconciled_at is None:
        raise DomainError("payments.not_reconciled", "this statement line is not reconciled")

    reverse(
        session,
        company_id,
        line.journal_entry_id,
        ref="Undo of a bank reconciliation",
    )
    line.journal_entry_id = None
    line.payment_id = None
    line.reconciled_at = None
    session.flush()

    record(
        session,
        action="statement_line.unreconciled",
        actor=actor,
        company_id=company_id,
        target_type="bank_statement_line",
        target_id=line.id,
        detail={"amount": str(line.amount)},
    )
    return line


def suggest_for_statement_line(
    session: Session, company_id: UUID, statement_line_id: UUID, *, limit: int = 20
) -> list[LineSuggestion]:
    """R8.AC6 — posted payments of the same amount and direction, nearest date first."""
    line = get_statement_line(session, company_id, statement_line_id)
    direction = "inbound" if line.amount > ZERO else "outbound"

    candidates = session.execute(
        select(Payment).where(
            Payment.company_id == company_id,
            Payment.state == "posted",
            Payment.direction == direction,
            Payment.id.not_in(
                select(BankStatementLine.payment_id).where(
                    BankStatementLine.company_id == company_id,
                    BankStatementLine.payment_id.is_not(None),
                )
            ),
        )
    ).scalars()

    suggestions = [
        LineSuggestion(
            payment=payment,
            reason=(
                "the amount and the reference match"
                if line.bank_reference and line.bank_reference == payment.reference
                else "the amount matches"
            ),
        )
        for payment in candidates
        if payment.net_amount == abs(line.amount)
    ]
    suggestions.sort(
        key=lambda s: (
            s.reason != "the amount and the reference match",
            abs((s.payment.date - line.date).days),
        )
    )
    return suggestions[:limit]


def _row(
    session: Session,
    statement: BankStatement,
    line: ParsedLine,
    *,
    line_no: int,
    fingerprint: str,
    occurrence: int,
) -> BankStatementLine:
    from app.platform.tenancy.api import Company

    company = session.get(Company, statement.company_id)
    return BankStatementLine(
        id=uuid7(),
        statement_id=statement.id,
        company_id=statement.company_id,
        line_no=line_no,
        date=line.date,
        amount=line.amount,
        currency_code=company.base_currency,
        description=line.description,
        counterparty=line.counterparty,
        bank_reference=line.bank_reference,
        import_hash=fingerprint,
        occurrence=occurrence,
    )


def _existing_occurrences(
    session: Session, company_id: UUID, bank_account_id: UUID
) -> Counter[str]:
    """How many times each fingerprint is already imported for this bank account."""
    rows = session.execute(
        select(BankStatementLine.import_hash, func.count())
        .join(BankStatement, BankStatement.id == BankStatementLine.statement_id)
        .where(
            BankStatementLine.company_id == company_id,
            BankStatement.bank_account_id == bank_account_id,
        )
        .group_by(BankStatementLine.import_hash)
    ).all()
    return Counter({fingerprint: count for fingerprint, count in rows})


def _check_agrees(session: Session, line: BankStatementLine, payment: Payment) -> None:
    """R8.AC7 — the bank moved a particular amount in a particular direction.

    The comparison happens in the currency the bank stated. A USD 100 receipt posted at 3.75
    reaches a SAR account as 375.00, and a payment with tax withheld reaches it net, so what
    to compare against is what the payment put through its outstanding account rather than
    the payment's face value.
    """
    wanted = "inbound" if line.amount > ZERO else "outbound"
    if payment.direction != wanted:
        raise DomainError(
            "payments.wrong_direction",
            f"the bank shows money {'in' if line.amount > ZERO else 'out'}, "
            f"but {payment.number} is an {payment.direction} payment",
        )

    expected = _as_the_bank_sees_it(session, line, payment)
    if expected != abs(line.amount):
        raise DomainError(
            "payments.amount_mismatch",
            f"the bank shows {abs(line.amount)} {line.currency_code} but {payment.number} "
            f"is for {expected}",
        )


def _as_the_bank_sees_it(session: Session, line: BankStatementLine, payment: Payment) -> Decimal:
    """What this payment should appear as on the statement, in the statement's currency."""
    if line.currency_code == payment.currency_code:
        return payment.net_amount

    from app.ledger.api import JournalEntryLine

    accounts = get_defaults(session, payment.company_id).accounts
    key = "outstanding_receipts" if payment.is_inbound else "outstanding_payments"
    amount = session.execute(
        select(func.abs(JournalEntryLine.debit - JournalEntryLine.credit)).where(
            JournalEntryLine.entry_id == payment.journal_entry_id,
            JournalEntryLine.account_id == accounts.get(key),
        )
    ).scalar_one_or_none()
    if amount is None:
        raise DomainError(
            "payments.amount_mismatch",
            f"{payment.number} has nothing on the outstanding account to compare",
        )
    return amount


def _entry_for(
    session: Session,
    statement: BankStatement,
    line: BankStatementLine,
    payment: Payment,
) -> PostingRequest:
    """R8.AC1, R8.AC2 — the bank account against the outstanding account."""
    accounts = get_defaults(session, statement.company_id).accounts
    key = "outstanding_receipts" if payment.is_inbound else "outstanding_payments"
    outstanding = accounts.get(key)
    if outstanding is None:
        raise DomainError(
            "payments.default_account_missing",
            f"the company has no {key.replace('_', ' ')} account",
        )

    amount = abs(line.amount)
    into_the_bank = line.amount > ZERO
    return PostingRequest(
        company_id=statement.company_id,
        journal_id=_bank_journal(session, statement),
        date=line.date,
        currency_code=line.currency_code,
        lines=[
            PostingLine(
                account_id=statement.bank_account_id,
                name=line.description or "Bank statement line",
                debit=amount if into_the_bank else ZERO,
                credit=ZERO if into_the_bank else amount,
            ),
            PostingLine(
                account_id=outstanding,
                name=f"Payment {payment.number}",
                debit=ZERO if into_the_bank else amount,
                credit=amount if into_the_bank else ZERO,
            ),
        ],
        ref=line.bank_reference,
        # Deliberately no source: the ledger allows one entry per source document, and a
        # line that was reconciled to the wrong payment must be able to be undone and
        # reconciled again (R8.AC5). The live link is the line's own journal_entry_id, and
        # the audit log keeps the history of every attempt.
        narration=f"Bank statement line {line.line_no}",
    )


def _bank_journal(session: Session, statement: BankStatement) -> UUID:
    """The journal whose default account is this bank account, or any bank journal."""
    journal_id = session.execute(
        select(Journal.id)
        .where(
            Journal.company_id == statement.company_id,
            Journal.type.in_(("bank", "cash")),
            Journal.active,
        )
        .order_by((Journal.default_account_id == statement.bank_account_id).desc(), Journal.code)
        .limit(1)
    ).scalar_one_or_none()
    if journal_id is None:
        raise DomainError(
            "payments.no_bank_journal", "reconciling a statement needs a bank or cash journal"
        )
    return journal_id


def _clear_outstanding(
    session: Session,
    company_id: UUID,
    payment: Payment,
    entry,
    *,
    actor: Actor | None,
) -> None:
    """If the outstanding account keeps open items, close the payment's against this entry.

    Most charts make outstanding receipts an ordinary current asset, in which case there is
    nothing to close and this does nothing at all.
    """
    from app.ledger.api import JournalEntryLine

    lines = list(
        session.execute(
            select(JournalEntryLine).where(
                JournalEntryLine.entry_id.in_((payment.journal_entry_id, entry.id)),
                JournalEntryLine.residual.is_not(None),
            )
        ).scalars()
    )
    pairs = [
        (debit, credit)
        for debit in lines
        for credit in lines
        if debit.debit > debit.credit
        and credit.credit > credit.debit
        and debit.account_id == credit.account_id
        and debit.entry_id != credit.entry_id
    ]
    for debit, credit in pairs:
        if debit.reconciled or credit.reconciled:
            continue
        match_amount(session, company_id, debit.id, credit.id, actor=actor)
