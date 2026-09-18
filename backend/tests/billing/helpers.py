"""Builders for invoicing tests: a document in one call."""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.billing.documents import DocumentData, LineData, create_document, post_document
from tests.billing.conftest import account_id, journal_id

TODAY = date(2026, 3, 1)


def make_invoice(
    session: Session,
    books,
    partner,
    *,
    taxes=(),
    quantity: str = "1",
    unit_price: str = "100.00",
    account_code: str = "4100",
    journal_code: str = "INV",
    type_: str = "out_invoice",
    on: date = TODAY,
    **document_kwargs,
):
    line = LineData(
        description="Consulting services",
        description_ar="خدمات استشارية",
        quantity=Decimal(quantity),
        unit_price=Decimal(unit_price),
        account_id=account_id(session, books.id, account_code),
        tax_ids=[tax.id for tax in taxes],
    )
    return create_document(
        session,
        books.id,
        DocumentData(
            type=type_,
            partner_id=partner.id,
            journal_id=journal_id(session, books.id, journal_code),
            date=on,
            lines=[line],
            **document_kwargs,
        ),
    )


def make_bill(session: Session, books, vendor, *, taxes=(), **kwargs):
    return make_invoice(
        session,
        books,
        vendor,
        taxes=taxes,
        account_code=kwargs.pop("account_code", "5300"),
        journal_code=kwargs.pop("journal_code", "BILL"),
        type_="in_bill",
        **kwargs,
    )


def post_invoice(session: Session, books, document):
    return post_document(session, books.id, document.id)
