"""Books with known figures, so the right answer to each report is obvious by inspection."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from app.billing.documents import DocumentData, LineData, create_document, post_document
from app.ledger.api import PostingLine, PostingRequest, post
from app.reporting.periods import Period
from app.treasury.matching import match_amount, open_lines
from app.treasury.payments import PaymentData, create_payment, post_payment
from tests.factories import TreasuryBooks, make_partner, make_treasury_company

JANUARY = date(2026, 1, 15)
FEBRUARY = date(2026, 2, 15)
MARCH = date(2026, 3, 15)
APRIL = date(2026, 4, 15)
YEAR = Period(date(2026, 1, 1), date(2026, 12, 31), "2026")


@pytest.fixture
def books(session: Session) -> TreasuryBooks:
    return make_treasury_company(session)


@pytest.fixture
def customer(session: Session, books: TreasuryBooks) -> UUID:
    return make_partner(session, books.company_id, name="Al Noor Est", type="customer").id


@pytest.fixture
def vendor(session: Session, books: TreasuryBooks) -> UUID:
    return make_partner(session, books.company_id, name="Jeddah Properties", type="vendor").id


def invoice(
    session: Session,
    books: TreasuryBooks,
    partner_id: UUID,
    amount: str,
    *,
    on: date = JANUARY,
    due: date | None = None,
    tax: bool = True,
    post_it: bool = True,
):
    """A customer invoice. With VAT by default, because that is the Saudi normal."""
    document = create_document(
        session,
        books.company_id,
        DocumentData(
            type="out_invoice",
            partner_id=partner_id,
            journal_id=books.journals["INV"],
            date=on,
            due_date=due,
            lines=[
                LineData(
                    description="Consultancy",
                    quantity=Decimal(1),
                    unit_price=Decimal(amount),
                    account_id=books.accounts["4100"],
                    tax_ids=[books.taxes["sale"]] if tax else [],
                )
            ],
        ),
    )
    session.flush()
    if post_it:
        post_document(session, books.company_id, document.id)
        session.flush()
    return document


def bill(
    session: Session,
    books: TreasuryBooks,
    partner_id: UUID,
    amount: str,
    *,
    on: date = JANUARY,
    account: str = "5300",
    tax: bool = True,
):
    document = create_document(
        session,
        books.company_id,
        DocumentData(
            type="in_bill",
            partner_id=partner_id,
            journal_id=books.journals["BILL"],
            date=on,
            lines=[
                LineData(
                    description="Rent",
                    quantity=Decimal(1),
                    unit_price=Decimal(amount),
                    account_id=books.accounts[account],
                    tax_ids=[books.taxes["purchase"]] if tax else [],
                )
            ],
        ),
    )
    session.flush()
    post_document(session, books.company_id, document.id)
    session.flush()
    return document


def receipt(
    session: Session,
    books: TreasuryBooks,
    partner_id: UUID,
    amount: str,
    *,
    on: date = FEBRUARY,
    direction: str = "inbound",
):
    payment = create_payment(
        session,
        books.company_id,
        PaymentData(
            direction=direction,
            partner_id=partner_id,
            journal_id=books.journals["BNK"],
            date=on,
            amount=Decimal(amount),
        ),
    )
    session.flush()
    post_payment(session, books.company_id, payment.id)
    session.flush()
    return payment


def settle(session: Session, books: TreasuryBooks, document, payment, amount: str | None = None):
    """Match a document's open item against a payment's."""
    lines = {item.line.entry_id: item.line for item in open_lines(session, books.company_id)}
    document_line = lines[document.journal_entry_id]
    payment_line = lines[payment.journal_entry_id]
    debit, credit = (
        (document_line, payment_line)
        if document_line.debit > document_line.credit
        else (payment_line, document_line)
    )
    match = match_amount(
        session,
        books.company_id,
        debit.id,
        credit.id,
        Decimal(amount) if amount else None,
    )
    session.flush()
    return match


def cash_entry(
    session: Session,
    books: TreasuryBooks,
    *,
    on: date,
    cash_account: str,
    other_account: str,
    amount: str,
    cash_in: bool,
):
    """A manual entry that moves cash, for the cash flow report to classify."""
    value = Decimal(amount)
    entry = post(
        session,
        PostingRequest(
            company_id=books.company_id,
            journal_id=books.journals["MISC"],
            date=on,
            currency_code="SAR",
            lines=[
                PostingLine(
                    account_id=books.accounts[cash_account],
                    debit=value if cash_in else Decimal(0),
                    credit=Decimal(0) if cash_in else value,
                ),
                PostingLine(
                    account_id=books.accounts[other_account],
                    debit=Decimal(0) if cash_in else value,
                    credit=value if cash_in else Decimal(0),
                ),
            ],
        ),
    )
    session.flush()
    return entry


@dataclass(frozen=True)
class SimpleBooks:
    """One invoice, one bill, one receipt, one match — enough for every report to say
    something, with figures small enough to check by hand."""

    books: TreasuryBooks
    customer: UUID
    vendor: UUID
    invoice_total: Decimal
    bill_total: Decimal
    received: Decimal


@pytest.fixture
def simple(session: Session, books: TreasuryBooks, customer: UUID, vendor: UUID) -> SimpleBooks:
    sale = invoice(session, books, customer, "10000.00", on=JANUARY, due=date(2026, 2, 14))
    bill(session, books, vendor, "4000.00", on=JANUARY)
    payment = receipt(session, books, customer, "11500.00", on=FEBRUARY)
    settle(session, books, sale, payment)
    session.commit()
    return SimpleBooks(
        books=books,
        customer=customer,
        vendor=vendor,
        invoice_total=Decimal("11500.00"),
        bill_total=Decimal("4600.00"),
        received=Decimal("11500.00"),
    )
