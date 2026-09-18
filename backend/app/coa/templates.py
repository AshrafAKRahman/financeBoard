"""Ready-made charts of accounts.

The Saudi chart is data, not code: a table of accounts with Arabic and English names, the
journals a Saudi company needs, and every company default filled in. Loading runs in the
caller's transaction, so a failure leaves the company exactly as it was (R6.AC7).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.coa.accounts import RECONCILABLE_SUBTYPES
from app.coa.defaults import set_default
from app.coa.journals import JournalData, create_journal
from app.ledger.api import Account
from app.platform.audit.api import Actor, record
from app.shared.errors import DomainError
from app.shared.ids import uuid7


@dataclass(frozen=True, slots=True)
class TemplateAccount:
    code: str
    name: str
    name_ar: str
    type: str
    subtype: str
    parent: str | None = None
    is_group: bool = False
    cash_flow_tag: str | None = None


@dataclass(frozen=True, slots=True)
class TemplateJournal:
    code: str
    name: str
    type: str
    default_account: str | None = None


@dataclass(frozen=True, slots=True)
class ChartTemplate:
    key: str
    name: str
    description: str
    accounts: Sequence[TemplateAccount]
    journals: Sequence[TemplateJournal]
    defaults: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TemplateResult:
    accounts: int
    journals: int
    defaults: int


SAUDI_ACCOUNTS: tuple[TemplateAccount, ...] = (
    # Assets
    TemplateAccount("1", "Assets", "الأصول", "asset", "current_asset", is_group=True),
    TemplateAccount(
        "11", "Current Assets", "الأصول المتداولة", "asset", "current_asset", "1", True
    ),
    TemplateAccount("1110", "Cash on Hand", "النقد في الصندوق", "asset", "bank_cash", "11",
                    cash_flow_tag="operating"),
    TemplateAccount("1120", "Bank Current Account", "الحساب الجاري بالبنك", "asset", "bank_cash",
                    "11", cash_flow_tag="operating"),
    TemplateAccount("1130", "Outstanding Receipts", "المقبوضات المعلقة", "asset", "current_asset",
                    "11"),
    TemplateAccount("1200", "Trade Receivables", "الذمم المدينة التجارية", "asset", "receivable",
                    "11"),
    TemplateAccount("1300", "VAT Input", "ضريبة القيمة المضافة - المدخلات", "asset",
                    "current_asset", "11"),
    TemplateAccount("1400", "Prepaid Expenses", "المصروفات المدفوعة مقدماً", "asset", "prepayment",
                    "11"),
    TemplateAccount("1500", "Suspense", "حساب معلق", "asset", "current_asset", "11"),
    TemplateAccount("12", "Non-Current Assets", "الأصول غير المتداولة", "asset",
                    "non_current_asset", "1", True),
    TemplateAccount("1600", "Property and Equipment", "الممتلكات والمعدات", "asset",
                    "non_current_asset", "12", cash_flow_tag="investing"),
    TemplateAccount("1650", "Accumulated Depreciation", "مجمع الإهلاك", "asset",
                    "non_current_asset", "12"),
    # Liabilities
    TemplateAccount("2", "Liabilities", "الالتزامات", "liability", "current_liability",
                    is_group=True),
    TemplateAccount("21", "Current Liabilities", "الالتزامات المتداولة", "liability",
                    "current_liability", "2", True),
    TemplateAccount("2100", "Trade Payables", "الذمم الدائنة التجارية", "liability", "payable",
                    "21"),
    TemplateAccount("2130", "Outstanding Payments", "المدفوعات المعلقة", "liability",
                    "current_liability", "21"),
    TemplateAccount("2200", "VAT Output", "ضريبة القيمة المضافة - المخرجات", "liability",
                    "current_liability", "21"),
    TemplateAccount("2250", "VAT Payable", "ضريبة القيمة المضافة المستحقة", "liability",
                    "current_liability", "21"),
    TemplateAccount("2300", "Withholding Tax Payable", "ضريبة الاستقطاع المستحقة", "liability",
                    "current_liability", "21"),
    TemplateAccount("2400", "GOSI Payable", "التأمينات الاجتماعية المستحقة", "liability",
                    "current_liability", "21"),
    TemplateAccount("2450", "Salaries Payable", "الرواتب المستحقة", "liability",
                    "current_liability", "21"),
    TemplateAccount("2500", "Zakat Provision", "مخصص الزكاة", "liability", "current_liability",
                    "21"),
    TemplateAccount("2600", "Accrued Expenses", "المصروفات المستحقة", "liability",
                    "current_liability", "21"),
    TemplateAccount("22", "Non-Current Liabilities", "الالتزامات غير المتداولة", "liability",
                    "non_current_liability", "2", True),
    TemplateAccount("2700", "End of Service Provision", "مخصص مكافأة نهاية الخدمة", "liability",
                    "non_current_liability", "22"),
    TemplateAccount("2800", "Long Term Loans", "القروض طويلة الأجل", "liability",
                    "non_current_liability", "22", cash_flow_tag="financing"),
    # Equity
    TemplateAccount("3", "Equity", "حقوق الملكية", "equity", "equity", is_group=True),
    TemplateAccount("3100", "Share Capital", "رأس المال", "equity", "equity", "3",
                    cash_flow_tag="financing"),
    TemplateAccount("3200", "Statutory Reserve", "الاحتياطي النظامي", "equity", "equity", "3"),
    TemplateAccount("3300", "Retained Earnings", "الأرباح المبقاة", "equity", "equity", "3"),
    TemplateAccount("3400", "Current Year Earnings", "أرباح العام الحالي", "equity",
                    "current_year_earnings", "3"),
    TemplateAccount("3500", "Owner Drawings", "مسحوبات الملاك", "equity", "equity", "3",
                    cash_flow_tag="financing"),
    # Income
    TemplateAccount("4", "Income", "الإيرادات", "income", "income", is_group=True),
    TemplateAccount("4100", "Sales Revenue", "إيرادات المبيعات", "income", "income", "4"),
    TemplateAccount("4200", "Service Revenue", "إيرادات الخدمات", "income", "income", "4"),
    TemplateAccount("4300", "Other Income", "إيرادات أخرى", "income", "other_income", "4"),
    TemplateAccount("4400", "Exchange Gain", "أرباح فروق العملة", "income", "other_income", "4"),
    # Expenses
    TemplateAccount("5", "Expenses", "المصروفات", "expense", "expense", is_group=True),
    TemplateAccount("51", "Cost of Revenue", "تكلفة الإيرادات", "expense", "cost_of_revenue", "5",
                    True),
    TemplateAccount("5100", "Cost of Goods Sold", "تكلفة البضاعة المباعة", "expense",
                    "cost_of_revenue", "51"),
    TemplateAccount("52", "Operating Expenses", "المصروفات التشغيلية", "expense", "expense", "5",
                    True),
    TemplateAccount("5200", "Salaries and Wages", "الرواتب والأجور", "expense", "expense", "52"),
    TemplateAccount("5210", "GOSI Employer Contribution", "حصة صاحب العمل في التأمينات",
                    "expense", "expense", "52"),
    TemplateAccount("5220", "End of Service Expense", "مصروف نهاية الخدمة", "expense", "expense",
                    "52"),
    TemplateAccount("5300", "Rent", "الإيجار", "expense", "expense", "52"),
    TemplateAccount("5400", "Utilities", "المرافق", "expense", "expense", "52"),
    TemplateAccount("5500", "Professional Fees", "الأتعاب المهنية", "expense", "expense", "52"),
    TemplateAccount("5600", "Bank Charges", "الرسوم البنكية", "expense", "expense", "52"),
    TemplateAccount("5700", "Exchange Loss", "خسائر فروق العملة", "expense", "expense", "52"),
    TemplateAccount("5800", "Depreciation", "الإهلاك", "expense", "depreciation", "52"),
    TemplateAccount("5900", "Rounding Difference", "فروق التقريب", "expense", "expense", "52"),
)

SAUDI_JOURNALS: tuple[TemplateJournal, ...] = (
    TemplateJournal("INV", "Customer Invoices", "sales"),
    TemplateJournal("BILL", "Vendor Bills", "purchases"),
    TemplateJournal("BNK", "Bank", "bank", default_account="1120"),
    TemplateJournal("CSH", "Cash", "cash", default_account="1110"),
    TemplateJournal("MISC", "Miscellaneous Operations", "general"),
)

SAUDI_DEFAULTS = {
    "receivable": "1200",
    "payable": "2100",
    "rounding": "5900",
    "fx_gain": "4400",
    "fx_loss": "5700",
    "outstanding_receipts": "1130",
    "outstanding_payments": "2130",
    "suspense": "1500",
}

SAUDI = ChartTemplate(
    key="sa",
    name="Saudi Arabia — standard chart",
    description=(
        "A starting chart for a Saudi company: VAT input and output, withholding tax, "
        "Zakat and end-of-service provisions, GOSI, and the usual trading accounts, with "
        "Arabic and English names."
    ),
    accounts=SAUDI_ACCOUNTS,
    journals=SAUDI_JOURNALS,
    defaults=SAUDI_DEFAULTS,
)

TEMPLATES: dict[str, ChartTemplate] = {SAUDI.key: SAUDI}


def get_template(key: str) -> ChartTemplate:
    template = TEMPLATES.get(key)
    if template is None:
        raise DomainError("coa.template_not_found", f"no chart template called {key!r}")
    return template


def load_template(
    session: Session, company_id: UUID, key: str, *, actor: Actor | None = None
) -> TemplateResult:
    template = get_template(key)

    existing = session.execute(
        select(func.count()).select_from(Account).where(Account.company_id == company_id)
    ).scalar_one()
    if existing:
        raise DomainError(
            "coa.chart_not_empty",
            "this company already has accounts; a template only loads into an empty chart",
        )

    # Template data is validated by tests/unit/test_template_data.py, so the accounts go in
    # as one batch rather than one round trip each — a template is 50-odd rows.
    by_code: dict[str, Account] = {}
    for entry in template.accounts:
        by_code[entry.code] = Account(
            id=uuid7(),
            company_id=company_id,
            code=entry.code,
            name=entry.name,
            name_ar=entry.name_ar,
            type=entry.type,
            subtype=entry.subtype,
            parent_id=by_code[entry.parent].id if entry.parent else None,
            is_group=entry.is_group,
            is_reconcilable=entry.subtype in RECONCILABLE_SUBTYPES,
            cash_flow_tag=entry.cash_flow_tag,
        )
    session.add_all(by_code.values())
    session.flush()

    for journal in template.journals:
        create_journal(
            session,
            company_id,
            JournalData(
                code=journal.code,
                name=journal.name,
                type=journal.type,
                default_account_id=(
                    by_code[journal.default_account].id if journal.default_account else None
                ),
            ),
            actor=actor,
        )

    for default_key, code in template.defaults.items():
        set_default(session, company_id, default_key, by_code[code].id, actor=actor)

    record(
        session,
        action="chart_template.loaded",
        actor=actor,
        company_id=company_id,
        target_type="chart_template",
        target_id=template.key,
        detail={"template": template.key, "accounts": len(template.accounts)},
    )
    return TemplateResult(
        accounts=len(template.accounts),
        journals=len(template.journals),
        defaults=len(template.defaults),
    )
