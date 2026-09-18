from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Connection, text
from sqlalchemy.orm import Session

from app.ledger.api import Account, ExchangeRate, Journal, LedgerSettings
from app.platform.tenancy.api import Company
from app.shared.ids import uuid7

ACCOUNTS = {
    # key: (code, type, subtype, reconcilable, group)
    "current_assets": ("1100", "asset", "current_asset", False, True),
    "bank": ("1110", "asset", "bank_cash", False, False),
    "receivable": ("1200", "asset", "receivable", True, False),
    "vat_input": ("1300", "asset", "current_asset", False, False),
    "payable": ("2100", "liability", "payable", True, False),
    "vat_output": ("2200", "liability", "current_liability", False, False),
    "equity": ("3100", "equity", "equity", False, False),
    "revenue": ("4100", "income", "income", False, False),
    "expense": ("5100", "expense", "expense", False, False),
    "rounding": ("5900", "expense", "expense", False, False),
}


@dataclass(frozen=True)
class Books:
    company_id: UUID
    accounts: dict[str, UUID]
    journals: dict[str, UUID]


def make_books(
    session: Session,
    *,
    base_currency: str = "SAR",
    fiscal_year_start_month: int = 1,
    lock_date: date | None = None,
    with_rounding_account: bool = True,
) -> Books:
    company = Company(
        id=uuid7(),
        name="Test Trading Co",
        base_currency=base_currency,
        fiscal_year_start_month=fiscal_year_start_month,
        lock_date=lock_date,
    )
    session.add(company)
    session.flush()

    accounts: dict[str, UUID] = {}
    for key, (code, type_, subtype, reconcilable, group) in ACCOUNTS.items():
        account = Account(
            id=uuid7(),
            company_id=company.id,
            code=code,
            name=key.replace("_", " ").title(),
            type=type_,
            subtype=subtype,
            is_reconcilable=reconcilable,
            is_group=group,
        )
        session.add(account)
        accounts[key] = account.id
    session.flush()

    journals: dict[str, UUID] = {}
    for code, type_ in (("MISC", "general"), ("INV", "sales"), ("BNK", "bank")):
        journal = Journal(id=uuid7(), company_id=company.id, code=code, name=code, type=type_)
        session.add(journal)
        journals[code] = journal.id

    session.add(
        LedgerSettings(
            company_id=company.id,
            rounding_account_id=accounts["rounding"] if with_rounding_account else None,
        )
    )
    session.commit()
    return Books(company.id, accounts, journals)


def add_rate(session: Session, books: Books, currency: str, on: date, rate: str) -> None:
    session.add(
        ExchangeRate(
            id=uuid7(),
            company_id=books.company_id,
            currency_code=currency,
            rate_date=on,
            rate=Decimal(rate),
        )
    )
    session.commit()


def insert_draft_entry(
    connection: Connection,
    books: Books,
    lines: list[tuple[str, str, str]],
    *,
    currency: str = "SAR",
    on: date = date(2026, 3, 1),
    amounts_currency: list[str] | None = None,
) -> UUID:
    """Raw SQL, bypassing the application. ``lines`` are (account key, debit, credit)."""
    entry_id = uuid7()
    connection.execute(
        text(
            "INSERT INTO journal_entry (id, company_id, journal_id, date, currency_code) "
            "VALUES (:id, :company, :journal, :date, :currency)"
        ),
        {
            "id": entry_id,
            "company": books.company_id,
            "journal": books.journals["MISC"],
            "date": on,
            "currency": currency,
        },
    )
    for line_no, (account, debit, credit) in enumerate(lines, start=1):
        amount_currency = (
            amounts_currency[line_no - 1]
            if amounts_currency
            else str(Decimal(debit) - Decimal(credit))
        )
        connection.execute(
            text(
                "INSERT INTO journal_entry_line (id, entry_id, company_id, line_no, account_id, "
                "debit, credit, currency_code, amount_currency) VALUES "
                "(:id, :entry, :company, :no, :account, :debit, :credit, :currency, :amount)"
            ),
            {
                "id": uuid7(),
                "entry": entry_id,
                "company": books.company_id,
                "no": line_no,
                "account": books.accounts[account],
                "debit": debit,
                "credit": credit,
                "currency": currency,
                "amount": amount_currency,
            },
        )
    return entry_id


def mark_posted(connection: Connection, entry_id: UUID, number: str = "MISC/2026/99999") -> None:
    connection.execute(
        text(
            "UPDATE journal_entry SET state = 'posted', number = :number, posted_at = now() "
            "WHERE id = :id"
        ),
        {"id": entry_id, "number": number},
    )


def insert_line(
    connection: Connection,
    books: Books,
    entry_id: UUID,
    account: str,
    debit: str = "0",
    credit: str = "0",
    *,
    line_no: int,
    currency: str = "SAR",
    amount_currency: str | None = None,
) -> UUID:
    """Raw SQL insert of one line, bypassing the posting service."""
    if amount_currency is None:
        amount_currency = str(Decimal(debit) - Decimal(credit))
    line_id = uuid7()
    connection.execute(
        text(
            "INSERT INTO journal_entry_line (id, entry_id, company_id, line_no, account_id, "
            "debit, credit, currency_code, amount_currency) VALUES "
            "(:id, :entry, :company, :no, :account, :debit, :credit, :currency, :amount)"
        ),
        {
            "id": line_id,
            "entry": entry_id,
            "company": books.company_id,
            "no": line_no,
            "account": books.accounts[account],
            "debit": debit,
            "credit": credit,
            "currency": currency,
            "amount": amount_currency,
        },
    )
    return line_id


def make_billing_company(session: Session):
    """A company with the Saudi chart and its taxes — what a real customer starts from."""
    from app.billing.taxes import install_saudi_taxes
    from app.coa.templates import load_template
    from app.ledger.api import LedgerSettings

    company = Company(id=uuid7(), name="Riyadh Trading", base_currency="SAR", vat_number="3" * 15)
    session.add(company)
    session.flush()
    session.add(LedgerSettings(company_id=company.id))
    session.flush()
    load_template(session, company.id, "sa")
    install_saudi_taxes(session, company.id)
    session.commit()
    return company


def make_partner(session: Session, company_id: UUID, **overrides):
    from app.billing.partners import PartnerData, create_partner

    values = {"name": "Al Noor Est", "type": "customer"}
    values.update(overrides)
    partner = create_partner(session, company_id, PartnerData(**values))
    session.commit()
    return partner


SMALL_CHART = [
    # code, name, type, subtype
    ("1200", "Trade Receivables", "asset", "receivable"),
    ("1300", "VAT Input", "asset", "current_asset"),
    ("2100", "Trade Payables", "liability", "payable"),
    ("2200", "VAT Output", "liability", "current_liability"),
    ("4100", "Sales Revenue", "income", "income"),
    ("5300", "Rent", "expense", "expense"),
    ("5900", "Rounding", "expense", "expense"),
]


def make_small_billing_company(session: Session):
    """A company with just enough chart to raise an invoice.

    Built with direct inserts rather than the services: the services have their own tests,
    and this fixture runs before nearly every billing test, so its round trips are the
    difference between a fast suite and a slow one.
    """
    from decimal import Decimal as D

    from app.billing.models import Tax
    from app.ledger.api import Account, Journal, LedgerSettings

    company = Company(id=uuid7(), name="Small Co", base_currency="SAR", vat_number="3" * 15)
    session.add(company)
    session.flush()

    accounts = {
        code: Account(
            id=uuid7(),
            company_id=company.id,
            code=code,
            name=name,
            type=type_,
            subtype=subtype,
            is_reconcilable=subtype in ("receivable", "payable"),
        )
        for code, name, type_, subtype in SMALL_CHART
    }
    journals = [
        Journal(id=uuid7(), company_id=company.id, code=code, name=name, type=type_)
        for code, name, type_ in (
            ("INV", "Customer Invoices", "sales"),
            ("BILL", "Vendor Bills", "purchases"),
            ("MISC", "Miscellaneous", "general"),
        )
    ]
    session.add_all([*accounts.values(), *journals])
    session.flush()

    session.add(
        LedgerSettings(
            company_id=company.id,
            receivable_account_id=accounts["1200"].id,
            payable_account_id=accounts["2100"].id,
            rounding_account_id=accounts["5900"].id,
        )
    )
    session.add_all(
        [
            Tax(
                id=uuid7(),
                company_id=company.id,
                name="VAT 15%",
                rate=D("15"),
                type="sale",
                account_id=accounts["2200"].id,
                grid_tag="sales_standard",
            ),
            Tax(
                id=uuid7(),
                company_id=company.id,
                name="VAT 15% (purchases)",
                rate=D("15"),
                type="purchase",
                account_id=accounts["1300"].id,
                grid_tag="purchases_standard",
            ),
        ]
    )
    session.commit()
    return company


TREASURY_CHART = [
    # code, name, type, subtype
    ("1110", "Bank Current Account", "asset", "bank_cash"),
    ("1120", "Outstanding Receipts", "asset", "current_asset"),
    ("1200", "Trade Receivables", "asset", "receivable"),
    ("1300", "VAT Input", "asset", "current_asset"),
    ("2100", "Trade Payables", "liability", "payable"),
    ("2120", "Outstanding Payments", "liability", "current_liability"),
    ("2200", "VAT Output", "liability", "current_liability"),
    ("2300", "Withholding Tax Payable", "liability", "current_liability"),
    ("4100", "Sales Revenue", "income", "income"),
    ("4900", "Exchange Gain", "income", "other_income"),
    ("5300", "Rent", "expense", "expense"),
    ("5800", "Exchange Loss", "expense", "expense"),
    ("5900", "Rounding", "expense", "expense"),
]


@dataclass(frozen=True)
class TreasuryBooks:
    """A company that can raise an invoice, pay it, and reconcile the bank."""

    company_id: UUID
    accounts: dict[str, UUID]
    journals: dict[str, UUID]
    taxes: dict[str, UUID]


def make_treasury_company(session: Session, *, base_currency: str = "SAR") -> TreasuryBooks:
    from decimal import Decimal as D

    from app.billing.models import Tax
    from app.ledger.api import Account, Journal, LedgerSettings

    company = Company(
        id=uuid7(), name="Jeddah Trading", base_currency=base_currency, vat_number="3" * 15
    )
    session.add(company)
    session.flush()

    accounts = {
        code: Account(
            id=uuid7(),
            company_id=company.id,
            code=code,
            name=name,
            type=type_,
            subtype=subtype,
            is_reconcilable=subtype in ("receivable", "payable"),
        )
        for code, name, type_, subtype in TREASURY_CHART
    }
    journals = {
        code: Journal(id=uuid7(), company_id=company.id, code=code, name=name, type=type_)
        for code, name, type_ in (
            ("INV", "Customer Invoices", "sales"),
            ("BILL", "Vendor Bills", "purchases"),
            ("BNK", "Bank", "bank"),
            ("CSH", "Cash", "cash"),
            ("MISC", "Miscellaneous", "general"),
        )
    }
    session.add_all([*accounts.values(), *journals.values()])
    session.flush()

    session.add(
        LedgerSettings(
            company_id=company.id,
            receivable_account_id=accounts["1200"].id,
            payable_account_id=accounts["2100"].id,
            rounding_account_id=accounts["5900"].id,
            outstanding_receipts_account_id=accounts["1120"].id,
            outstanding_payments_account_id=accounts["2120"].id,
            fx_gain_account_id=accounts["4900"].id,
            fx_loss_account_id=accounts["5800"].id,
        )
    )
    taxes = {
        "sale": Tax(
            id=uuid7(),
            company_id=company.id,
            name="VAT 15%",
            rate=D("15"),
            type="sale",
            account_id=accounts["2200"].id,
            grid_tag="sales_standard",
        ),
        "purchase": Tax(
            id=uuid7(),
            company_id=company.id,
            name="VAT 15% (purchases)",
            rate=D("15"),
            type="purchase",
            account_id=accounts["1300"].id,
            grid_tag="purchases_standard",
        ),
        "withholding": Tax(
            id=uuid7(),
            company_id=company.id,
            name="Withholding 5%",
            rate=D("5"),
            type="withholding",
            account_id=accounts["2300"].id,
            grid_tag="withholding",
        ),
    }
    session.add_all(taxes.values())
    session.commit()
    return TreasuryBooks(
        company_id=company.id,
        accounts={code: account.id for code, account in accounts.items()},
        journals={code: journal.id for code, journal in journals.items()},
        taxes={key: tax.id for key, tax in taxes.items()},
    )
