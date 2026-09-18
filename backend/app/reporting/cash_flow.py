"""Where the cash actually went (R4).

The direct method (decision D5), and it needs no allocation. For every entry that touches a
bank or cash account, the **non-cash** lines are classified by their own account's cash flow
tag. Those lines sum exactly to the cash movement, because the entry balances — so a payment
covering three things splits itself, with no pro-rata arithmetic and no rounding remainder.

A transfer between two bank accounts has no non-cash lines at all, and nets to zero. It
therefore never appears, which is correct: moving your own money is not a cash flow.
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.reporting.periods import Period
from app.reporting.statements import ReportMeta, company_of, meta
from app.shared.money import ZERO

OPERATING = "operating"
INVESTING = "investing"
FINANCING = "financing"
UNCLASSIFIED = "unclassified"

CLASSIFICATIONS = (OPERATING, INVESTING, FINANCING, UNCLASSIFIED)


@dataclass(frozen=True, slots=True)
class CashFlowLine:
    account_id: UUID
    code: str
    name: str
    name_ar: str | None
    amount: Decimal
    """Positive when cash came in."""


@dataclass(frozen=True, slots=True)
class CashFlowSection:
    classification: str
    lines: tuple[CashFlowLine, ...]
    total: Decimal


@dataclass(frozen=True, slots=True)
class CashFlow:
    meta: ReportMeta
    opening_cash: Decimal
    sections: tuple[CashFlowSection, ...]
    net_movement: Decimal
    closing_cash: Decimal

    @property
    def reconciles(self) -> bool:
        """R4.AC5"""
        return self.opening_cash + self.net_movement == self.closing_cash


CASH_BALANCE = """
SELECT COALESCE(SUM(l.debit - l.credit), 0) AS balance
FROM journal_entry_line l
JOIN journal_entry e ON e.id = l.entry_id
JOIN account a       ON a.id = l.account_id
WHERE l.company_id = :company AND e.state = 'posted'
  AND a.subtype = 'bank_cash' AND e.date <= :on
"""

# The counterpart lines of every cash-touching entry. A credit on the counterpart means cash
# came in, so the sign flips relative to the ledger.
MOVEMENTS = """
WITH cash_entries AS (
    SELECT DISTINCT l.entry_id
    FROM journal_entry_line l
    JOIN journal_entry e ON e.id = l.entry_id
    JOIN account a       ON a.id = l.account_id
    WHERE l.company_id = :company AND e.state = 'posted'
      AND a.subtype = 'bank_cash'
      AND e.date BETWEEN :start AND :end
)
SELECT a.id, a.code, a.name, a.name_ar,
       COALESCE(a.cash_flow_tag, 'unclassified') AS classification,
       SUM(l.credit - l.debit) AS amount
FROM journal_entry_line l
JOIN cash_entries ce ON ce.entry_id = l.entry_id
JOIN account a       ON a.id = l.account_id
WHERE a.subtype <> 'bank_cash'
GROUP BY a.id, a.code, a.name, a.name_ar, a.cash_flow_tag
HAVING SUM(l.credit - l.debit) <> 0
ORDER BY a.code
"""


def cash_flow(session: Session, company_id: UUID, period: Period) -> CashFlow:
    """R4 — opening cash, what moved it and where it finished."""
    company = company_of(session, company_id)

    opening = session.execute(
        text(CASH_BALANCE),
        {"company": company_id, "on": _day_before(period.start)},
    ).scalar_one()
    closing = session.execute(
        text(CASH_BALANCE), {"company": company_id, "on": period.end}
    ).scalar_one()

    rows = session.execute(
        text(MOVEMENTS),
        {"company": company_id, "start": period.start, "end": period.end},
    ).all()

    grouped: dict[str, list[CashFlowLine]] = {name: [] for name in CLASSIFICATIONS}
    for row in rows:
        grouped[row.classification].append(
            CashFlowLine(
                account_id=row.id,
                code=row.code,
                name=row.name,
                name_ar=row.name_ar,
                amount=row.amount,
            )
        )

    sections = tuple(
        CashFlowSection(
            classification=name,
            lines=tuple(grouped[name]),
            total=sum((line.amount for line in grouped[name]), ZERO),
        )
        for name in CLASSIFICATIONS
    )

    return CashFlow(
        meta=meta(company, period, "cash-flow"),
        opening_cash=opening,
        sections=sections,
        net_movement=sum((section.total for section in sections), ZERO),
        closing_cash=closing,
    )


def _day_before(on):
    from datetime import date, timedelta

    return on - timedelta(days=1) if on > date.min else date.min
