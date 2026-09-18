"""Fixtures for the treasury suite: a company that can invoice, pay and reconcile."""

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from app.billing.documents import DocumentData, LineData, create_document, post_document
from app.billing.models import Document
from app.treasury.payments import PaymentData, create_payment, post_payment
from tests.factories import TreasuryBooks, make_partner, make_treasury_company

PAYMENT_DATE = date(2026, 3, 15)
INVOICE_DATE = date(2026, 3, 1)


@pytest.fixture
def books(session: Session) -> TreasuryBooks:
    return make_treasury_company(session)


@pytest.fixture
def customer(session: Session, books: TreasuryBooks) -> UUID:
    return make_partner(session, books.company_id, name="Al Noor Est", type="customer").id


@pytest.fixture
def vendor(session: Session, books: TreasuryBooks) -> UUID:
    return make_partner(session, books.company_id, name="Jeddah Properties", type="vendor").id


def draft(
    books: TreasuryBooks,
    partner_id: UUID,
    amount: str = "1000.00",
    **overrides,
) -> PaymentData:
    values: dict = {
        "direction": "inbound",
        "partner_id": partner_id,
        "journal_id": books.journals["BNK"],
        "date": PAYMENT_DATE,
        "amount": Decimal(amount),
    }
    values.update(overrides)
    return PaymentData(**values)


def make_payment(
    session: Session,
    books: TreasuryBooks,
    partner_id: UUID,
    amount: str = "1000.00",
    *,
    post: bool = False,
    **overrides,
):
    payment = create_payment(
        session, books.company_id, draft(books, partner_id, amount, **overrides)
    )
    session.flush()
    if post:
        post_payment(session, books.company_id, payment.id)
    session.commit()
    return payment


def make_invoice(
    session: Session,
    books: TreasuryBooks,
    partner_id: UUID,
    unit_price: str = "1000.00",
    *,
    currency: str = "SAR",
    on: date = INVOICE_DATE,
    tax: bool = False,
    post: bool = True,
) -> Document:
    """A customer invoice, posted by default so it has an open receivable line."""
    document = create_document(
        session,
        books.company_id,
        DocumentData(
            type="out_invoice",
            partner_id=partner_id,
            journal_id=books.journals["INV"],
            date=on,
            currency_code=currency,
            lines=[
                LineData(
                    description="Consultancy",
                    quantity=Decimal(1),
                    unit_price=Decimal(unit_price),
                    account_id=books.accounts["4100"],
                    tax_ids=[books.taxes["sale"]] if tax else [],
                )
            ],
        ),
    )
    session.flush()
    if post:
        post_document(session, books.company_id, document.id)
    session.commit()
    return document


def make_bill(
    session: Session,
    books: TreasuryBooks,
    partner_id: UUID,
    unit_price: str = "1000.00",
    *,
    currency: str = "SAR",
    on: date = INVOICE_DATE,
    post: bool = True,
) -> Document:
    document = create_document(
        session,
        books.company_id,
        DocumentData(
            type="in_bill",
            partner_id=partner_id,
            journal_id=books.journals["BILL"],
            date=on,
            currency_code=currency,
            lines=[
                LineData(
                    description="March rent",
                    quantity=Decimal(1),
                    unit_price=Decimal(unit_price),
                    account_id=books.accounts["5300"],
                )
            ],
        ),
    )
    session.flush()
    if post:
        post_document(session, books.company_id, document.id)
    session.commit()
    return document
