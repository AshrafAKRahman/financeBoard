"""Trial balance, profit and loss, and balance sheet (R1, R2, R3).

All three read `account_balances`, so they cannot disagree about a number. The balance
sheet's earnings are computed from the same rows rather than posted, because there are no
closing entries (decision D6) — which is also why the profit and loss's net result and the
balance sheet's current-year earnings are necessarily the same figure (R10.AC1).
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.platform.tenancy.api import Company
from app.reporting.balances import (
    PROFIT_AND_LOSS_TYPES,
    BalanceNode,
    account_balances,
    as_of,
    total_movement,
    tree,
)
from app.reporting.periods import Period, fiscal_year_bounds
from app.shared.errors import DomainError
from app.shared.money import ZERO


@dataclass(frozen=True, slots=True)
class ReportMeta:
    """What every report says about itself (R8.AC5)."""

    report: str
    company_id: UUID
    company_name: str
    currency_code: str
    period: Period
    generated_at: datetime


@dataclass(frozen=True, slots=True)
class TrialBalance:
    meta: ReportMeta
    rows: tuple[BalanceNode, ...]
    total_debit: Decimal
    total_credit: Decimal

    @property
    def balances(self) -> bool:
        """R1.AC4 — the check the whole system rests on."""
        return self.total_debit == self.total_credit


@dataclass(frozen=True, slots=True)
class ProfitAndLoss:
    meta: ReportMeta
    income: tuple[BalanceNode, ...]
    expenses: tuple[BalanceNode, ...]
    total_income: Decimal
    cost_of_revenue: Decimal
    other_expenses: Decimal
    gross_profit: Decimal
    net_result: Decimal
    comparison: "ProfitAndLoss | None" = None


@dataclass(frozen=True, slots=True)
class BalanceSheet:
    meta: ReportMeta
    assets: tuple[BalanceNode, ...]
    liabilities: tuple[BalanceNode, ...]
    equity: tuple[BalanceNode, ...]
    total_assets: Decimal
    total_liabilities: Decimal
    posted_equity: Decimal
    retained_earnings: Decimal
    current_year_earnings: Decimal

    @property
    def total_equity(self) -> Decimal:
        return self.posted_equity + self.retained_earnings + self.current_year_earnings

    @property
    def balances(self) -> bool:
        """R3.AC4"""
        return self.total_assets == self.total_liabilities + self.total_equity


def company_of(session: Session, company_id: UUID) -> Company:
    company = session.get(Company, company_id)
    if company is None:
        raise DomainError("reporting.company_not_found", f"company {company_id} not found")
    if not 1 <= (company.fiscal_year_start_month or 0) <= 12:
        raise DomainError(
            "reporting.no_fiscal_year",
            f"{company.name} has no fiscal year start month",
        )
    return company


def meta(company: Company, period: Period, report: str) -> ReportMeta:
    return ReportMeta(
        report=report,
        company_id=company.id,
        company_name=company.name,
        currency_code=company.base_currency,
        period=period,
        generated_at=datetime.now(UTC),
    )


def trial_balance(
    session: Session,
    company_id: UUID,
    period: Period,
    *,
    journal_id: UUID | None = None,
    hide_unused: bool = False,
) -> TrialBalance:
    """R1 — every account's opening, movement and closing, and the proof they balance."""
    company = company_of(session, company_id)
    balances = account_balances(session, company_id, period, journal_id=journal_id)
    rows = tree(balances, hide_unused=hide_unused)

    return TrialBalance(
        meta=meta(company, period, "trial-balance"),
        rows=tuple(rows),
        total_debit=sum((b.debit for b in balances), ZERO),
        total_credit=sum((b.credit for b in balances), ZERO),
    )


def profit_and_loss(
    session: Session,
    company_id: UUID,
    period: Period,
    *,
    journal_id: UUID | None = None,
    comparison: bool = False,
) -> ProfitAndLoss:
    """R2 — what was earned and spent, with income shown the way a reader expects."""
    company = company_of(session, company_id)
    balances = account_balances(
        session, company_id, period, types=PROFIT_AND_LOSS_TYPES, journal_id=journal_id
    )
    income = tree(balances, types=("income",), hide_unused=True)
    expenses = tree(balances, types=("expense",), hide_unused=True)

    # The ledger signs income as a credit; a reader wants "earned 100", not "-100".
    total_income = -total_movement(balances, ("income",))
    cost_of_revenue = sum((b.movement for b in balances if b.subtype == "cost_of_revenue"), ZERO)
    total_expenses = total_movement(balances, ("expense",))
    other_expenses = total_expenses - cost_of_revenue

    earlier = None
    if comparison:
        earlier = profit_and_loss(
            session, company_id, _preceding(period), journal_id=journal_id, comparison=False
        )

    return ProfitAndLoss(
        meta=meta(company, period, "profit-and-loss"),
        income=tuple(income),
        expenses=tuple(expenses),
        total_income=total_income,
        cost_of_revenue=cost_of_revenue,
        other_expenses=other_expenses,
        gross_profit=total_income - cost_of_revenue,
        net_result=total_income - total_expenses,
        comparison=earlier,
    )


def _preceding(period: Period) -> Period:
    """R2.AC8 — the period of equal length immediately before this one."""
    from datetime import timedelta

    length = timedelta(days=period.days)
    end = period.start - timedelta(days=1)
    return Period(end - length + timedelta(days=1), end, f"Previous {period.days} days")


def balance_sheet(session: Session, company_id: UUID, on: date) -> BalanceSheet:
    """R3 — what the business owns and owes, with earnings computed rather than posted.

    One query covers all of it: the balance sheet accounts' closing balances, and the income
    and expense accounts' movement both for this fiscal year and for all of time. Asking the
    database three times for figures it can produce once is how a report gets slow.
    """
    company = company_of(session, company_id)
    period = as_of(on)
    year_start, _ = fiscal_year_bounds(on, company.fiscal_year_start_month)
    balances = account_balances(session, company_id, period, year_start=year_start)

    assets = tree(balances, types=("asset",), hide_unused=True)
    liabilities = tree(balances, types=("liability",), hide_unused=True)
    equity = tree(balances, types=("equity",), hide_unused=True)

    earnings = [row for row in balances if row.type in PROFIT_AND_LOSS_TYPES]
    # Income is a credit, so earnings are the negative of the ledger's movement (R3.AC2).
    current_year = -sum((row.year_movement for row in earnings), ZERO)
    all_years = -sum((row.closing for row in earnings), ZERO)

    return BalanceSheet(
        meta=meta(company, period, "balance-sheet"),
        assets=tuple(assets),
        liabilities=tuple(liabilities),
        equity=tuple(equity),
        total_assets=sum((b.closing for b in balances if b.type == "asset"), ZERO),
        total_liabilities=-sum((b.closing for b in balances if b.type == "liability"), ZERO),
        posted_equity=-sum((b.closing for b in balances if b.type == "equity"), ZERO),
        retained_earnings=all_years - current_year,
        current_year_earnings=current_year,
    )
