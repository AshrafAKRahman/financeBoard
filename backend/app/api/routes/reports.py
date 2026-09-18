"""The financial reports over HTTP.

One permission for all of them: a report shows the whole financial position, so being allowed
to read the chart of accounts is not the same as being allowed to read the profit. Every
response carries the same envelope — company, currency, period, when it was read — and every
row that stands for an account carries its id, so a screen can link a figure to its detail.
"""

from datetime import date as DateType
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import SessionDep, requires
from app.api.protection import needs
from app.reporting import aged as aged_service
from app.reporting import cash_flow as cash_flow_service
from app.reporting import detail as detail_service
from app.reporting import statements as statements_service
from app.reporting import vat_return as vat_service
from app.reporting.balances import BalanceNode
from app.reporting.periods import Period, resolve
from app.reporting.statements import ReportMeta, company_of

router = APIRouter(prefix="/api/v1/companies/{company_id}/reports", tags=["reports"])


# --------------------------------------------------------------------------- schemas


class MetaOut(BaseModel):
    report: str
    company_id: UUID
    company_name: str
    currency_code: str
    period_start: DateType
    period_end: DateType
    period_label: str
    generated_at: str


class RowOut(BaseModel):
    account_id: UUID | None
    code: str | None
    name: str
    name_ar: str | None
    level: int
    is_group: bool
    opening: Decimal
    debit: Decimal
    credit: Decimal
    closing: Decimal
    children: list["RowOut"] = []


class TrialBalanceOut(BaseModel):
    meta: MetaOut
    rows: list[RowOut]
    total_debit: Decimal
    total_credit: Decimal
    balances: bool


class ProfitAndLossOut(BaseModel):
    meta: MetaOut
    income: list[RowOut]
    expenses: list[RowOut]
    total_income: Decimal
    cost_of_revenue: Decimal
    other_expenses: Decimal
    gross_profit: Decimal
    net_result: Decimal
    comparison: "ProfitAndLossOut | None" = None


class BalanceSheetOut(BaseModel):
    meta: MetaOut
    assets: list[RowOut]
    liabilities: list[RowOut]
    equity: list[RowOut]
    total_assets: Decimal
    total_liabilities: Decimal
    posted_equity: Decimal
    retained_earnings: Decimal
    current_year_earnings: Decimal
    total_equity: Decimal
    balances: bool


class CashFlowLineOut(BaseModel):
    account_id: UUID
    code: str
    name: str
    name_ar: str | None
    amount: Decimal


class CashFlowSectionOut(BaseModel):
    classification: str
    lines: list[CashFlowLineOut]
    total: Decimal


class CashFlowOut(BaseModel):
    meta: MetaOut
    opening_cash: Decimal
    sections: list[CashFlowSectionOut]
    net_movement: Decimal
    closing_cash: Decimal
    reconciles: bool


class AgedItemOut(BaseModel):
    line_id: UUID
    entry_id: UUID
    entry_number: str | None
    entry_date: DateType
    due_date: DateType
    account_id: UUID
    open_amount: Decimal
    bucket: str
    days_overdue: int


class AgedPartnerOut(BaseModel):
    partner_id: UUID | None
    partner_name: str
    buckets: dict[str, Decimal]
    total: Decimal
    items: list[AgedItemOut]


class AgedOut(BaseModel):
    meta: MetaOut
    side: str
    partners: list[AgedPartnerOut]
    buckets: dict[str, Decimal]
    total: Decimal


class VatBoxOut(BaseModel):
    number: int
    name: str
    name_ar: str
    side: str
    net: Decimal
    tax: Decimal


class UntaggedOut(BaseModel):
    grid_tag: str | None
    net: Decimal
    tax: Decimal


class VatReturnOut(BaseModel):
    meta: MetaOut
    sales: list[VatBoxOut]
    purchases: list[VatBoxOut]
    untagged: list[UntaggedOut]
    total_sales_net: Decimal
    output_tax: Decimal
    total_purchases_net: Decimal
    input_tax: Decimal
    net_tax_due: Decimal


class DetailLineOut(BaseModel):
    line_id: UUID
    entry_id: UUID
    entry_number: str | None
    entry_date: DateType
    journal_code: str
    partner_id: UUID | None
    partner_name: str | None
    description: str | None
    document_number: str | None
    debit: Decimal
    credit: Decimal
    running_balance: Decimal


class AccountDetailOut(BaseModel):
    meta: MetaOut
    account_id: UUID
    code: str
    name: str
    name_ar: str | None
    opening_balance: Decimal
    lines: list[DetailLineOut]
    total_debit: Decimal
    total_credit: Decimal
    closing_balance: Decimal


# --------------------------------------------------------------------------- helpers


def _meta(value: ReportMeta) -> MetaOut:
    return MetaOut(
        report=value.report,
        company_id=value.company_id,
        company_name=value.company_name,
        currency_code=value.currency_code,
        period_start=value.period.start,
        period_end=value.period.end,
        period_label=value.period.label,
        generated_at=value.generated_at.isoformat(),
    )


def _rows(nodes) -> list[RowOut]:
    return [
        RowOut(
            account_id=node.account_id,
            code=node.code,
            name=node.name,
            name_ar=node.name_ar,
            level=node.level,
            is_group=node.is_group,
            opening=node.opening,
            debit=node.debit,
            credit=node.credit,
            closing=node.closing,
            children=_rows(node.children),
        )
        for node in nodes
    ]


def _period(
    session: SessionDep,
    company_id: UUID,
    start: DateType | None,
    end: DateType | None,
    named: str | None,
) -> Period:
    """The period from the query string, against this company's fiscal year (R8.AC2)."""
    company = company_of(session, company_id)
    return resolve(
        start_month=company.fiscal_year_start_month,
        today=DateType.today(),  # noqa: DTZ011 (a business date, not a moment)
        start=start,
        end=end,
        named=named,
    )


def _profit_and_loss_out(report) -> ProfitAndLossOut:
    return ProfitAndLossOut(
        meta=_meta(report.meta),
        income=_rows(report.income),
        expenses=_rows(report.expenses),
        total_income=report.total_income,
        cost_of_revenue=report.cost_of_revenue,
        other_expenses=report.other_expenses,
        gross_profit=report.gross_profit,
        net_result=report.net_result,
        comparison=_profit_and_loss_out(report.comparison) if report.comparison else None,
    )


def _aged_out(report) -> AgedOut:
    return AgedOut(
        meta=_meta(report.meta),
        side=report.side,
        partners=[
            AgedPartnerOut(
                partner_id=partner.partner_id,
                partner_name=partner.partner_name,
                buckets=partner.buckets,
                total=partner.total,
                items=[
                    AgedItemOut(
                        line_id=item.line_id,
                        entry_id=item.entry_id,
                        entry_number=item.entry_number,
                        entry_date=item.entry_date,
                        due_date=item.due_date,
                        account_id=item.account_id,
                        open_amount=item.open_amount,
                        bucket=item.bucket,
                        days_overdue=item.days_overdue,
                    )
                    for item in partner.items
                ],
            )
            for partner in report.partners
        ],
        buckets=report.buckets,
        total=report.total,
    )


# --------------------------------------------------------------------------- routes


@router.get(
    "/trial-balance", response_model=TrialBalanceOut, dependencies=[requires("report:read")]
)
@needs("report:read")
def read_trial_balance(
    company_id: UUID,
    session: SessionDep,
    start: DateType | None = None,
    end: DateType | None = None,
    period: str | None = None,
    journal_id: UUID | None = None,
    hide_unused: bool = False,
) -> TrialBalanceOut:
    """R1"""
    report = statements_service.trial_balance(
        session,
        company_id,
        _period(session, company_id, start, end, period),
        journal_id=journal_id,
        hide_unused=hide_unused,
    )
    return TrialBalanceOut(
        meta=_meta(report.meta),
        rows=_rows(report.rows),
        total_debit=report.total_debit,
        total_credit=report.total_credit,
        balances=report.balances,
    )


@router.get(
    "/profit-and-loss", response_model=ProfitAndLossOut, dependencies=[requires("report:read")]
)
@needs("report:read")
def read_profit_and_loss(
    company_id: UUID,
    session: SessionDep,
    start: DateType | None = None,
    end: DateType | None = None,
    period: str | None = None,
    journal_id: UUID | None = None,
    comparison: bool = False,
) -> ProfitAndLossOut:
    """R2"""
    return _profit_and_loss_out(
        statements_service.profit_and_loss(
            session,
            company_id,
            _period(session, company_id, start, end, period),
            journal_id=journal_id,
            comparison=comparison,
        )
    )


@router.get(
    "/balance-sheet", response_model=BalanceSheetOut, dependencies=[requires("report:read")]
)
@needs("report:read")
def read_balance_sheet(
    company_id: UUID, session: SessionDep, on: DateType | None = None
) -> BalanceSheetOut:
    """R3"""
    report = statements_service.balance_sheet(
        session,
        company_id,
        on or DateType.today(),  # noqa: DTZ011 (a business date, not a moment)
    )
    return BalanceSheetOut(
        meta=_meta(report.meta),
        assets=_rows(report.assets),
        liabilities=_rows(report.liabilities),
        equity=_rows(report.equity),
        total_assets=report.total_assets,
        total_liabilities=report.total_liabilities,
        posted_equity=report.posted_equity,
        retained_earnings=report.retained_earnings,
        current_year_earnings=report.current_year_earnings,
        total_equity=report.total_equity,
        balances=report.balances,
    )


@router.get("/cash-flow", response_model=CashFlowOut, dependencies=[requires("report:read")])
@needs("report:read")
def read_cash_flow(
    company_id: UUID,
    session: SessionDep,
    start: DateType | None = None,
    end: DateType | None = None,
    period: str | None = None,
) -> CashFlowOut:
    """R4"""
    report = cash_flow_service.cash_flow(
        session, company_id, _period(session, company_id, start, end, period)
    )
    return CashFlowOut(
        meta=_meta(report.meta),
        opening_cash=report.opening_cash,
        sections=[
            CashFlowSectionOut(
                classification=section.classification,
                lines=[
                    CashFlowLineOut(
                        account_id=line.account_id,
                        code=line.code,
                        name=line.name,
                        name_ar=line.name_ar,
                        amount=line.amount,
                    )
                    for line in section.lines
                ],
                total=section.total,
            )
            for section in report.sections
        ],
        net_movement=report.net_movement,
        closing_cash=report.closing_cash,
        reconciles=report.reconciles,
    )


@router.get("/aged-receivables", response_model=AgedOut, dependencies=[requires("report:read")])
@needs("report:read")
def read_aged_receivables(
    company_id: UUID,
    session: SessionDep,
    on: DateType | None = None,
    partner_id: UUID | None = None,
) -> AgedOut:
    """R5"""
    return _aged_out(
        aged_service.aged_receivables(
            session,
            company_id,
            on or DateType.today(),  # noqa: DTZ011
            partner_id=partner_id,
        )
    )


@router.get("/aged-payables", response_model=AgedOut, dependencies=[requires("report:read")])
@needs("report:read")
def read_aged_payables(
    company_id: UUID,
    session: SessionDep,
    on: DateType | None = None,
    partner_id: UUID | None = None,
) -> AgedOut:
    """R5.AC6"""
    return _aged_out(
        aged_service.aged_payables(
            session,
            company_id,
            on or DateType.today(),  # noqa: DTZ011
            partner_id=partner_id,
        )
    )


@router.get("/vat-return", response_model=VatReturnOut, dependencies=[requires("report:read")])
@needs("report:read")
def read_vat_return(
    company_id: UUID,
    session: SessionDep,
    start: DateType | None = None,
    end: DateType | None = None,
    period: str | None = None,
) -> VatReturnOut:
    """R6"""
    report = vat_service.vat_return(
        session, company_id, _period(session, company_id, start, end, period)
    )

    def boxes(entries: Any) -> list[VatBoxOut]:
        return [
            VatBoxOut(
                number=entry.box.number,
                name=entry.box.name,
                name_ar=entry.box.name_ar,
                side=entry.box.side,
                net=entry.net,
                tax=entry.tax,
            )
            for entry in entries
        ]

    return VatReturnOut(
        meta=_meta(report.meta),
        sales=boxes(report.sales),
        purchases=boxes(report.purchases),
        untagged=[
            UntaggedOut(grid_tag=entry.grid_tag, net=entry.net, tax=entry.tax)
            for entry in report.untagged
        ],
        total_sales_net=report.total_sales_net,
        output_tax=report.output_tax,
        total_purchases_net=report.total_purchases_net,
        input_tax=report.input_tax,
        net_tax_due=report.net_tax_due,
    )


@router.get(
    "/accounts/{account_id}/detail",
    response_model=AccountDetailOut,
    dependencies=[requires("report:read")],
)
@needs("report:read")
def read_account_detail(
    company_id: UUID,
    account_id: UUID,
    session: SessionDep,
    start: DateType | None = None,
    end: DateType | None = None,
    period: str | None = None,
    partner_id: UUID | None = None,
) -> AccountDetailOut:
    """R7"""
    report = detail_service.account_detail(
        session,
        company_id,
        account_id,
        _period(session, company_id, start, end, period),
        partner_id=partner_id,
    )
    return AccountDetailOut(
        meta=_meta(report.meta),
        account_id=report.account_id,
        code=report.code,
        name=report.name,
        name_ar=report.name_ar,
        opening_balance=report.opening_balance,
        lines=[
            DetailLineOut(
                line_id=line.line_id,
                entry_id=line.entry_id,
                entry_number=line.entry_number,
                entry_date=line.entry_date,
                journal_code=line.journal_code,
                partner_id=line.partner_id,
                partner_name=line.partner_name,
                description=line.description,
                document_number=line.document_number,
                debit=line.debit,
                credit=line.credit,
                running_balance=line.running_balance,
            )
            for line in report.lines
        ],
        total_debit=report.total_debit,
        total_credit=report.total_credit,
        closing_balance=report.closing_balance,
    )


__all__ = ["BalanceNode", "router"]
