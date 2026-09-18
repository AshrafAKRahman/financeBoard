"""The one query the statements are built from (R1).

Opening, debits, credits and closing per account, for a period. The trial balance *is* this
result; the profit and loss is it filtered to income and expense; the balance sheet is it for
assets, liabilities and equity. They cannot disagree about a figure because they read the
same figure — which is what makes the reconciliations in R10 structural rather than lucky.

Nesting accounts under their parents is a pure function over those rows, so it needs no
database and can be tested on its own.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.reporting.periods import Period
from app.shared.money import ZERO

# Which types belong to which statement (R2.AC7, R3.AC1).
PROFIT_AND_LOSS_TYPES = ("income", "expense")
BALANCE_SHEET_TYPES = ("asset", "liability", "equity")
# Types whose natural balance is a credit, so a positive figure means "more of it" (R2.AC2).
CREDIT_NATURED = ("liability", "equity", "income")


@dataclass(frozen=True, slots=True)
class AccountBalance:
    """One account's movement over a period, and where it started and finished."""

    account_id: UUID
    code: str
    name: str
    name_ar: str | None
    type: str
    subtype: str
    parent_id: UUID | None
    is_group: bool
    opening: Decimal
    debit: Decimal
    credit: Decimal
    year_movement: Decimal = ZERO
    """The fiscal year's movement, when the caller asked for it (R3.AC2)."""

    @property
    def movement(self) -> Decimal:
        return self.debit - self.credit

    @property
    def closing(self) -> Decimal:
        return self.opening + self.movement

    @property
    def is_credit_natured(self) -> bool:
        return self.type in CREDIT_NATURED

    def presented(self, amount: Decimal) -> Decimal:
        """The figure as a reader expects it: income and liabilities positive (R2.AC2, R3.AC6)."""
        return -amount if self.is_credit_natured else amount


@dataclass(slots=True)
class BalanceNode:
    """An account in the chart, with its children and their subtotals (R2.AC4, R3.AC7)."""

    account_id: UUID | None
    code: str | None
    name: str
    name_ar: str | None
    type: str
    subtype: str | None
    level: int
    is_group: bool
    opening: Decimal = ZERO
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    children: list["BalanceNode"] = field(default_factory=list)

    @property
    def movement(self) -> Decimal:
        return self.debit - self.credit

    @property
    def closing(self) -> Decimal:
        return self.opening + self.movement


BALANCES = """
SELECT a.id, a.code, a.name, a.name_ar, a.type, a.subtype, a.parent_id, a.is_group,
       COALESCE(SUM(CASE WHEN e.date < :start THEN l.debit - l.credit END), 0) AS opening,
       COALESCE(SUM(CASE WHEN e.date >= :start THEN l.debit END), 0)           AS debit,
       COALESCE(SUM(CASE WHEN e.date >= :start THEN l.credit END), 0)          AS credit,
       COALESCE(SUM(CASE WHEN e.date >= :year_start THEN l.debit - l.credit END), 0)
           AS year_movement
FROM account a
LEFT JOIN journal_entry_line l
       ON l.account_id = a.id AND l.company_id = a.company_id
LEFT JOIN journal_entry e
       ON e.id = l.entry_id AND e.state = 'posted' AND e.date <= :end {journal}
WHERE a.company_id = :company
  AND (l.id IS NULL OR e.id IS NOT NULL)
  {types}
GROUP BY a.id, a.code, a.name, a.name_ar, a.type, a.subtype, a.parent_id, a.is_group
ORDER BY a.code
"""


def account_balances(
    session: Session,
    company_id: UUID,
    period: Period,
    *,
    types: Sequence[str] | None = None,
    journal_id: UUID | None = None,
    year_start: date | None = None,
) -> list[AccountBalance]:
    """Every account in the chart, with its opening balance and the period's movement.

    Accounts that never moved come back with zeros rather than being absent: a trial balance
    that silently omitted an account would hide exactly the one worth asking about, and
    callers that want only the accounts in play pass ``hide_unused`` to `tree`.

    ``year_start`` asks for the fiscal year's movement alongside, which is what lets the
    balance sheet compute its earnings without a second query.
    """
    sql = BALANCES.format(
        journal="AND e.journal_id = :journal" if journal_id else "",
        types="AND a.type = ANY(:types)" if types else "",
    )
    params: dict[str, object] = {
        "company": company_id,
        "start": period.start,
        "end": period.end,
        "year_start": year_start or period.start,
    }
    if journal_id:
        params["journal"] = journal_id
    if types:
        params["types"] = list(types)

    return [
        AccountBalance(
            account_id=row.id,
            code=row.code,
            name=row.name,
            name_ar=row.name_ar,
            type=row.type,
            subtype=row.subtype,
            parent_id=row.parent_id,
            is_group=row.is_group,
            opening=row.opening,
            debit=row.debit,
            credit=row.credit,
            year_movement=row.year_movement,
        )
        for row in session.execute(text(sql), params).all()
    ]


@dataclass(frozen=True, slots=True)
class ChartEntry:
    """An account as the chart holds it, needed to nest balances under absent parents."""

    account_id: UUID
    code: str
    name: str
    name_ar: str | None
    type: str
    subtype: str
    parent_id: UUID | None
    is_group: bool


def chart(session: Session, company_id: UUID) -> list[ChartEntry]:
    rows = session.execute(
        text(
            "SELECT id, code, name, name_ar, type, subtype, parent_id, is_group "
            "FROM account WHERE company_id = :c ORDER BY code"
        ),
        {"c": company_id},
    ).all()
    return [
        ChartEntry(
            account_id=row.id,
            code=row.code,
            name=row.name,
            name_ar=row.name_ar,
            type=row.type,
            subtype=row.subtype,
            parent_id=row.parent_id,
            is_group=row.is_group,
        )
        for row in rows
    ]


def tree(
    balances: Sequence[AccountBalance],
    *,
    types: Sequence[str] | None = None,
    hide_unused: bool = False,
) -> list[BalanceNode]:
    """Nest the balances under their parents and subtotal upward (R2.AC4, R3.AC7).

    Pure: give it the rows, get a tree. A group account holds no lines of its own, so its
    figures are entirely its children's.
    """
    wanted = set(types) if types else None
    rows = [row for row in balances if wanted is None or row.type in wanted]
    nodes = {
        row.account_id: BalanceNode(
            account_id=row.account_id,
            code=row.code,
            name=row.name,
            name_ar=row.name_ar,
            type=row.type,
            subtype=row.subtype,
            level=0,
            is_group=row.is_group,
            opening=row.opening,
            debit=row.debit,
            credit=row.credit,
        )
        for row in rows
    }
    parents = {row.account_id: row.parent_id for row in rows}

    roots: list[BalanceNode] = []
    for account_id, node in nodes.items():
        parent_id = parents[account_id]
        if parent_id is not None and parent_id in nodes:
            nodes[parent_id].children.append(node)
        else:
            roots.append(node)

    for node in nodes.values():
        node.children.sort(key=lambda child: child.code or "")

    def settle(node: BalanceNode, level: int) -> None:
        node.level = level
        for child in node.children:
            settle(child, level + 1)
        if node.children:
            node.opening += sum((child.opening for child in node.children), ZERO)
            node.debit += sum((child.debit for child in node.children), ZERO)
            node.credit += sum((child.credit for child in node.children), ZERO)

    roots.sort(key=lambda node: node.code or "")
    for root in roots:
        settle(root, 0)

    if hide_unused:
        roots = [root for root in (_pruned(root) for root in roots) if root is not None]
    return roots


def _pruned(node: BalanceNode) -> BalanceNode | None:
    """R1.AC6 — an account that neither held nor moved anything is noise."""
    node.children = [
        child for child in (_pruned(child) for child in node.children) if child is not None
    ]
    if node.children:
        return node
    if node.opening == ZERO and node.debit == ZERO and node.credit == ZERO:
        return None
    return node


def flatten(nodes: Sequence[BalanceNode]) -> list[BalanceNode]:
    """Depth-first, which is the order a statement is read in."""
    out: list[BalanceNode] = []
    for node in nodes:
        out.append(node)
        out.extend(flatten(node.children))
    return out


def total_movement(balances: Sequence[AccountBalance], types: Sequence[str]) -> Decimal:
    """The net movement of a set of account types, as the ledger signs it."""
    wanted = set(types)
    return sum((b.movement for b in balances if b.type in wanted), ZERO)


def closing_balance(balances: Sequence[AccountBalance], types: Sequence[str]) -> Decimal:
    wanted = set(types)
    return sum((b.closing for b in balances if b.type in wanted), ZERO)


def as_of(day: date) -> Period:
    """Everything up to a date — what a balance sheet asks for (R3.AC1)."""
    return Period(date.min, day, f"As at {day.isoformat()}")
