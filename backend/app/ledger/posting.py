"""The only code path that creates journal entries.

Callers own the transaction: nothing here commits. The database re-checks every
invariant (balance at commit, immutability, lock dates), so the checks below exist
to fail early with clear errors, not for safety.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.ledger.models import Journal, JournalEntry, JournalEntryLine, LedgerSettings
from app.ledger.rates import currency_places, get_rate
from app.platform.sequence.api import next_number
from app.platform.tenancy.api import Company, fiscal_year
from app.shared.errors import DomainError, domain_error_from_db
from app.shared.ids import uuid7
from app.shared.money import ZERO, is_rounded, quantize


@dataclass(frozen=True, slots=True)
class PostingLine:
    """One line in the request's transaction currency."""

    account_id: UUID
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    name: str | None = None
    partner_id: UUID | None = None
    due_date: date | None = None
    tax_id: UUID | None = None
    tax_grid_tag: str | None = None


@dataclass(frozen=True, slots=True)
class PostingRequest:
    company_id: UUID
    journal_id: UUID
    date: date
    currency_code: str
    lines: Sequence[PostingLine]
    ref: str | None = None
    narration: str | None = None
    source_type: str | None = None
    source_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class LineValues:
    """A line ready to insert: company-currency debit/credit plus signed amount_currency."""

    account_id: UUID
    debit: Decimal
    credit: Decimal
    currency_code: str
    amount_currency: Decimal
    name: str | None = None
    partner_id: UUID | None = None
    due_date: date | None = None
    tax_id: UUID | None = None
    tax_grid_tag: str | None = None


ROUNDING_LINE_NAME = "Currency conversion rounding"


def validate_request(request: PostingRequest, places: int) -> None:
    if len(request.lines) < 2:
        raise DomainError("ledger.too_few_lines", "an entry needs at least two lines")
    if (request.source_type is None) != (request.source_id is None):
        raise DomainError("ledger.invalid_source", "source_type and source_id go together")

    for index, line in enumerate(request.lines, start=1):
        if line.debit < 0 or line.credit < 0:
            raise DomainError("ledger.negative_amount", f"line {index} has a negative amount")
        if line.debit and line.credit:
            raise DomainError("ledger.two_sided_line", f"line {index} has debit and credit")
        if not line.debit and not line.credit:
            raise DomainError("ledger.zero_line", f"line {index} has no amount")
        if not (is_rounded(line.debit, places) and is_rounded(line.credit, places)):
            raise DomainError(
                "ledger.unrounded",
                f"line {index} must have at most {places} decimal places "
                f"for {request.currency_code}",
            )

    debit = sum((line.debit for line in request.lines), ZERO)
    credit = sum((line.credit for line in request.lines), ZERO)
    if debit != credit:
        raise DomainError(
            "ledger.unbalanced",
            f"debit {debit} and credit {credit} differ in {request.currency_code}",
        )


def convert_lines(
    lines: Sequence[PostingLine],
    currency_code: str,
    rate: Decimal,
    base_places: int,
    rounding_account_id: UUID | None,
) -> list[LineValues]:
    """Convert to company currency at ``rate``, adding a rounding line if conversion
    left the entry unbalanced by a few minor units (decision D8)."""
    converted: list[LineValues] = []
    for line in lines:
        amount_currency = line.debit - line.credit
        company_amount = quantize(amount_currency * rate, base_places)
        converted.append(
            LineValues(
                account_id=line.account_id,
                debit=max(company_amount, ZERO),
                credit=max(-company_amount, ZERO),
                currency_code=currency_code,
                amount_currency=amount_currency,
                name=line.name,
                partner_id=line.partner_id,
                due_date=line.due_date,
                tax_id=line.tax_id,
                tax_grid_tag=line.tax_grid_tag,
            )
        )

    difference = sum((v.debit - v.credit for v in converted), ZERO)
    if difference == 0:
        return converted

    # Each line rounds by at most half a minor unit.
    max_rounding = Decimal(len(lines)) * Decimal("0.5") * Decimal(1).scaleb(-base_places)
    if abs(difference) > max_rounding:
        raise AssertionError(f"conversion difference {difference} exceeds rounding bounds")
    if rounding_account_id is None:
        raise DomainError(
            "ledger.rounding_account_missing",
            "set a rounding account in ledger settings to post foreign-currency entries",
        )

    converted.append(
        LineValues(
            account_id=rounding_account_id,
            debit=max(-difference, ZERO),
            credit=max(difference, ZERO),
            currency_code=currency_code,
            amount_currency=ZERO,
            name=ROUNDING_LINE_NAME,
        )
    )
    return converted


def post(session: Session, request: PostingRequest) -> JournalEntry:
    company = _company(session, request.company_id)
    journal = _journal(session, request.company_id, request.journal_id)

    validate_request(request, currency_places(session, request.currency_code))

    rate = get_rate(session, company, request.currency_code, request.date)
    settings = session.get(LedgerSettings, company.id)
    lines = convert_lines(
        request.lines,
        request.currency_code,
        rate,
        currency_places(session, company.base_currency),
        settings.rounding_account_id if settings else None,
    )

    return _create_posted_entry(
        session,
        company,
        journal,
        entry_date=request.date,
        currency_code=request.currency_code,
        lines=lines,
        ref=request.ref,
        narration=request.narration,
        source_type=request.source_type,
        source_id=request.source_id,
    )


def reverse(
    session: Session,
    company_id: UUID,
    entry_id: UUID,
    *,
    on: date | None = None,
    ref: str | None = None,
) -> JournalEntry:
    """Post an entry that exactly cancels ``entry_id``. Company amounts are copied, not
    re-converted, so the pair nets to zero in both currencies."""
    original = session.execute(
        select(JournalEntry)
        .where(JournalEntry.id == entry_id, JournalEntry.company_id == company_id)
        .with_for_update()
    ).scalar_one_or_none()
    if original is None:
        raise DomainError("ledger.entry_not_found", f"entry {entry_id} not found")
    if original.state != "posted":
        raise DomainError("ledger.reverse_unposted", "only posted entries can be reversed")

    already = session.execute(
        select(JournalEntry.number).where(JournalEntry.reversed_entry_id == entry_id)
    ).scalar_one_or_none()
    if already is not None:
        raise DomainError(
            "ledger.already_reversed", f"entry {original.number} was reversed by {already}"
        )

    lines = [
        LineValues(
            account_id=line.account_id,
            debit=line.credit,
            credit=line.debit,
            currency_code=line.currency_code,
            amount_currency=-line.amount_currency,
            name=line.name,
            partner_id=line.partner_id,
            due_date=line.due_date,
            tax_id=line.tax_id,
            tax_grid_tag=line.tax_grid_tag,
        )
        for line in original.lines
    ]

    return _create_posted_entry(
        session,
        _company(session, company_id),
        _journal(session, company_id, original.journal_id),
        entry_date=on or original.date,
        currency_code=original.currency_code,
        lines=lines,
        ref=ref or f"Reversal of {original.number}",
        narration=None,
        reversed_entry_id=original.id,
    )


def _create_posted_entry(
    session: Session,
    company: Company,
    journal: Journal,
    *,
    entry_date: date,
    currency_code: str,
    lines: Sequence[LineValues],
    ref: str | None,
    narration: str | None,
    source_type: str | None = None,
    source_id: UUID | None = None,
    reversed_entry_id: UUID | None = None,
) -> JournalEntry:
    year = fiscal_year(entry_date, company.fiscal_year_start_month)
    # Locks the counter row first (see architecture §6.2), then builds the entry.
    number = next_number(session, company.id, f"journal:{journal.id}", str(year))

    entry = JournalEntry(
        id=uuid7(),
        company_id=company.id,
        journal_id=journal.id,
        date=entry_date,
        ref=ref,
        narration=narration,
        state="draft",
        currency_code=currency_code,
        reversed_entry_id=reversed_entry_id,
        source_type=source_type,
        source_id=source_id,
        lines=[
            JournalEntryLine(
                id=uuid7(),
                company_id=company.id,
                line_no=line_no,
                account_id=v.account_id,
                partner_id=v.partner_id,
                name=v.name,
                debit=v.debit,
                credit=v.credit,
                currency_code=v.currency_code,
                amount_currency=v.amount_currency,
                due_date=v.due_date,
                tax_id=v.tax_id,
                tax_grid_tag=v.tax_grid_tag,
            )
            for line_no, v in enumerate(lines, start=1)
        ],
    )
    session.add(entry)
    _flush(session)

    entry.state = "posted"
    entry.number = f"{journal.code}/{year}/{number:05d}"
    entry.posted_at = datetime.now(UTC)
    _flush(session)
    return entry


def _company(session: Session, company_id: UUID) -> Company:
    company = session.get(Company, company_id)
    if company is None:
        raise DomainError("ledger.company_not_found", f"company {company_id} not found")
    return company


def _journal(session: Session, company_id: UUID, journal_id: UUID) -> Journal:
    journal = session.get(Journal, journal_id)
    if journal is None or journal.company_id != company_id:
        raise DomainError("ledger.journal_not_found", f"journal {journal_id} not found")
    if not journal.active:
        raise DomainError("ledger.journal_inactive", f"journal {journal.code} is archived")
    return journal


def _flush(session: Session) -> None:
    try:
        session.flush()
    except DBAPIError as exc:
        translated = domain_error_from_db(exc)
        if translated is not None:
            raise translated from exc
        raise
