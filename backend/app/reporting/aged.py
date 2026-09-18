"""Who owes what, and for how long (R5).

Two honest paths, because "open" means different things on different dates:

- **As of today**, a line's open amount is the one the ledger already holds, kept true by the
  reconciliation trigger. One column, no arithmetic.
- **As of a past date**, that column is no use: it reflects every payment received since. The
  amount has to be rebuilt by subtracting only the matches whose *settling entry* is dated on
  or before that date — a payment received in April must not settle a March invoice on the
  March report.

The settling entry's date governs, not `matched_at`: money moved when the entry says it did,
and when somebody clicked the button is an audit fact rather than an accounting one.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.reporting.balances import as_of
from app.reporting.statements import ReportMeta, company_of, meta
from app.shared.money import ZERO

RECEIVABLE = "receivable"
PAYABLE = "payable"

# Days overdue. The last bucket has no upper bound.
BUCKETS = ((0, "current"), (1, "1-30"), (31, "31-60"), (61, "61-90"), (91, "90+"))
BUCKET_NAMES = tuple(name for _, name in BUCKETS)


@dataclass(frozen=True, slots=True)
class AgedItem:
    """One open line: an invoice, a credit note, or a payment nobody has matched yet."""

    line_id: UUID
    entry_id: UUID
    entry_number: str | None
    entry_date: date
    due_date: date
    account_id: UUID
    open_amount: Decimal
    bucket: str
    days_overdue: int


@dataclass(frozen=True, slots=True)
class AgedPartner:
    partner_id: UUID | None
    partner_name: str
    buckets: dict[str, Decimal]
    total: Decimal
    items: tuple[AgedItem, ...] = ()


@dataclass(frozen=True, slots=True)
class Aged:
    meta: ReportMeta
    side: str
    partners: tuple[AgedPartner, ...]
    buckets: dict[str, Decimal]
    total: Decimal


# Today's open amounts: the ledger holds them, so read them.
OPEN_NOW = """
SELECT l.id, l.entry_id, e.number, e.date, l.account_id, l.partner_id,
       COALESCE(p.name, 'No partner') AS partner_name,
       COALESCE(l.due_date, e.date) AS due_date,
       -- The stored open amount is unsigned, so the sign comes from which side the line
       -- is on: a customer invoice is owed to us, an unmatched receipt from that customer
       -- is owed back (R5.AC7). Payables read the same way, the other way round.
       CASE WHEN (l.debit > l.credit) = (a.subtype = 'receivable')
            THEN l.residual ELSE -l.residual END AS signed_open,
       l.debit, l.credit
FROM journal_entry_line l
JOIN journal_entry e ON e.id = l.entry_id
JOIN account a       ON a.id = l.account_id
LEFT JOIN partner p  ON p.id = l.partner_id
WHERE l.company_id = :company AND e.state = 'posted'
  AND a.subtype = :subtype
  AND l.residual IS NOT NULL AND l.residual <> 0
  AND e.date <= :on
  {partner}
ORDER BY e.date, e.number
"""

# A past date: rebuild the open amount from the matches that had happened by then.
OPEN_AS_OF = """
SELECT l.id, l.entry_id, e.number, e.date, l.account_id, l.partner_id,
       COALESCE(p.name, 'No partner') AS partner_name,
       COALESCE(l.due_date, e.date) AS due_date,
       abs(l.debit - l.credit) - COALESCE(settled.amount, 0) AS raw_open,
       l.debit, l.credit
FROM journal_entry_line l
JOIN journal_entry e ON e.id = l.entry_id
JOIN account a       ON a.id = l.account_id
LEFT JOIN partner p  ON p.id = l.partner_id
LEFT JOIN LATERAL (
    SELECT SUM(
        CASE WHEN r.debit_line_id = l.id THEN r.debit_amount ELSE r.credit_amount END
    ) AS amount
    FROM reconciliation r
    JOIN journal_entry_line other
      ON other.id = CASE WHEN r.debit_line_id = l.id THEN r.credit_line_id ELSE r.debit_line_id END
    JOIN journal_entry other_entry ON other_entry.id = other.entry_id
    WHERE (r.debit_line_id = l.id OR r.credit_line_id = l.id)
      AND other_entry.date <= :on
) settled ON TRUE
WHERE l.company_id = :company AND e.state = 'posted'
  AND a.subtype = :subtype
  AND l.residual IS NOT NULL
  AND e.date <= :on
  {partner}
ORDER BY e.date, e.number
"""


def bucket_for(days_overdue: int) -> str:
    """R5.AC1 — nothing overdue is current; everything else falls in a band."""
    name = BUCKET_NAMES[0]
    for threshold, label in BUCKETS:
        if days_overdue >= threshold:
            name = label
    return name


def aged_receivables(
    session: Session,
    company_id: UUID,
    on: date,
    *,
    partner_id: UUID | None = None,
    today: date | None = None,
) -> Aged:
    """R5.AC1 — what customers owe, aged by how late it is."""
    return _aged(session, company_id, on, RECEIVABLE, partner_id=partner_id, today=today)


def aged_payables(
    session: Session,
    company_id: UUID,
    on: date,
    *,
    partner_id: UUID | None = None,
    today: date | None = None,
) -> Aged:
    """R5.AC6 — the same report read from the other side."""
    return _aged(session, company_id, on, PAYABLE, partner_id=partner_id, today=today)


def _aged(
    session: Session,
    company_id: UUID,
    on: date,
    subtype: str,
    *,
    partner_id: UUID | None,
    today: date | None,
) -> Aged:
    company = company_of(session, company_id)
    today = today or date.today()  # noqa: DTZ011 (a business date, not a moment)

    historic = on < today
    sql = (OPEN_AS_OF if historic else OPEN_NOW).format(
        partner="AND l.partner_id = :partner" if partner_id else ""
    )
    params: dict[str, object] = {"company": company_id, "on": on, "subtype": subtype}
    if partner_id:
        params["partner"] = partner_id

    items: dict[UUID | None, list[AgedItem]] = {}
    names: dict[UUID | None, str] = {}

    for row in session.execute(text(sql), params).all():
        amount = row.raw_open if historic else row.signed_open
        if historic:
            # The rebuilt figure is unsigned, so take the side from the line itself.
            is_debit = row.debit > row.credit
            amount = amount if is_debit else -amount
            if subtype == PAYABLE:
                amount = -amount
        if amount == ZERO:
            continue

        days = (on - row.due_date).days
        items.setdefault(row.partner_id, []).append(
            AgedItem(
                line_id=row.id,
                entry_id=row.entry_id,
                entry_number=row.number,
                entry_date=row.date,
                due_date=row.due_date,
                account_id=row.account_id,
                open_amount=amount,
                bucket=bucket_for(days),
                days_overdue=max(days, 0),
            )
        )
        names[row.partner_id] = row.partner_name

    partners = []
    for key, rows in items.items():
        buckets = {name: ZERO for name in BUCKET_NAMES}
        for item in rows:
            buckets[item.bucket] += item.open_amount
        partners.append(
            AgedPartner(
                partner_id=key,
                partner_name=names[key],
                buckets=buckets,
                total=sum(buckets.values(), ZERO),
                items=tuple(rows),
            )
        )
    partners.sort(key=lambda entry: entry.partner_name)

    totals = {name: ZERO for name in BUCKET_NAMES}
    for partner in partners:
        for name, amount in partner.buckets.items():
            totals[name] += amount

    return Aged(
        meta=meta(
            company, as_of(on), f"aged-{'receivables' if subtype == RECEIVABLE else 'payables'}"
        ),
        side=subtype,
        partners=tuple(partners),
        buckets=totals,
        total=sum(totals.values(), ZERO),
    )
