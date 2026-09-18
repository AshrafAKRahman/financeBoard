"""The lines behind a figure (R7).

Every other report is a sum; this is what it was a sum of. A figure nobody can open is a
figure nobody should trust, so the running balance here has to close exactly where the trial
balance says the account does (R7.AC4, R10.AC6).
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.reporting.periods import Period
from app.reporting.statements import ReportMeta, company_of, meta
from app.shared.errors import DomainError
from app.shared.money import ZERO


@dataclass(frozen=True, slots=True)
class DetailLine:
    line_id: UUID
    entry_id: UUID
    entry_number: str | None
    entry_date: date
    journal_code: str
    partner_id: UUID | None
    partner_name: str | None
    description: str | None
    document_number: str | None
    """The invoice, bill or payment this line came from, where one exists (R7.AC6)."""

    debit: Decimal
    credit: Decimal
    running_balance: Decimal


@dataclass(frozen=True, slots=True)
class AccountDetail:
    meta: ReportMeta
    account_id: UUID
    code: str
    name: str
    name_ar: str | None
    opening_balance: Decimal
    lines: tuple[DetailLine, ...]
    total_debit: Decimal
    total_credit: Decimal

    @property
    def closing_balance(self) -> Decimal:
        return self.opening_balance + self.total_debit - self.total_credit


ACCOUNT = """
SELECT id, code, name, name_ar FROM account WHERE id = :account AND company_id = :company
"""

OPENING = """
SELECT COALESCE(SUM(l.debit - l.credit), 0) AS opening
FROM journal_entry_line l
JOIN journal_entry e ON e.id = l.entry_id
WHERE l.company_id = :company AND l.account_id = :account
  AND e.state = 'posted' AND e.date < :start
  {partner}
"""

# A line's document is whatever posted the entry: an invoice, a payment, or nothing at all
# for a manual entry.
LINES = """
SELECT l.id, l.entry_id, e.number AS entry_number, e.date, j.code AS journal_code,
       l.partner_id, p.name AS partner_name, l.name AS description,
       l.debit, l.credit,
       COALESCE(d.number, pay.number) AS document_number
FROM journal_entry_line l
JOIN journal_entry e ON e.id = l.entry_id
JOIN journal j       ON j.id = e.journal_id
LEFT JOIN partner p  ON p.id = l.partner_id
LEFT JOIN document d ON d.journal_entry_id = e.id
LEFT JOIN payment pay ON pay.journal_entry_id = e.id
WHERE l.company_id = :company AND l.account_id = :account
  AND e.state = 'posted' AND e.date BETWEEN :start AND :end
  {partner}
ORDER BY e.date, e.number, l.line_no
"""


def account_detail(
    session: Session,
    company_id: UUID,
    account_id: UUID,
    period: Period,
    *,
    partner_id: UUID | None = None,
) -> AccountDetail:
    """R7 — the posted lines of one account, with a running balance."""
    company = company_of(session, company_id)
    account = session.execute(
        text(ACCOUNT), {"account": account_id, "company": company_id}
    ).one_or_none()
    if account is None:
        raise DomainError("reporting.account_not_found", f"account {account_id} not found")

    clause = "AND l.partner_id = :partner" if partner_id else ""
    params: dict[str, object] = {
        "company": company_id,
        "account": account_id,
        "start": period.start,
        "end": period.end,
    }
    if partner_id:
        params["partner"] = partner_id

    opening = session.execute(
        text(OPENING.format(partner=clause)),
        {k: v for k, v in params.items() if k != "end"},
    ).scalar_one()

    running = opening
    lines: list[DetailLine] = []
    for row in session.execute(text(LINES.format(partner=clause)), params).all():
        running += row.debit - row.credit
        lines.append(
            DetailLine(
                line_id=row.id,
                entry_id=row.entry_id,
                entry_number=row.entry_number,
                entry_date=row.date,
                journal_code=row.journal_code,
                partner_id=row.partner_id,
                partner_name=row.partner_name,
                description=row.description,
                document_number=row.document_number,
                debit=row.debit,
                credit=row.credit,
                running_balance=running,
            )
        )

    return AccountDetail(
        meta=meta(company, period, "account-detail"),
        account_id=account.id,
        code=account.code,
        name=account.name,
        name_ar=account.name_ar,
        opening_balance=opening,
        lines=tuple(lines),
        total_debit=sum((line.debit for line in lines), ZERO),
        total_credit=sum((line.credit for line in lines), ZERO),
    )
