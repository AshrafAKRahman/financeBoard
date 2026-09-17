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
