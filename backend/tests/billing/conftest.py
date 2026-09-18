"""Shared fixtures for invoicing tests: a company with a chart, taxes and a customer."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.ledger.api import Account, Journal
from app.platform.tenancy.api import Company
from app.shared.ids import uuid7
from tests.factories import (
    make_billing_company,
    make_partner,
    make_small_billing_company,
)

TODAY = date(2026, 3, 1)


@pytest.fixture
def plain_company(session: Session):
    """A company with no chart: enough for anything that does not touch accounts."""
    from app.ledger.api import LedgerSettings

    company = Company(id=uuid7(), name="Plain Co", base_currency="SAR")
    session.add(company)
    session.flush()
    session.add(LedgerSettings(company_id=company.id))
    session.commit()
    return company


@pytest.fixture
def books(session: Session):
    """A small chart with VAT: enough for invoices, and quick to build."""
    return make_small_billing_company(session)


@pytest.fixture
def saudi_books(session: Session):
    """The full Saudi chart template — for the tests that are about the template."""
    return make_billing_company(session)


def account_id(session: Session, company_id, code: str):
    from sqlalchemy import select

    return session.execute(
        select(Account.id).where(Account.company_id == company_id, Account.code == code)
    ).scalar_one()


def journal_id(session: Session, company_id, code: str):
    from sqlalchemy import select

    return session.execute(
        select(Journal.id).where(Journal.company_id == company_id, Journal.code == code)
    ).scalar_one()


@pytest.fixture
def customer(session: Session, books: Company):
    return make_partner(session, books.id, name_ar="مؤسسة النور", vat_number="310000000000003")


@pytest.fixture
def vendor(session: Session, books: Company):
    return make_partner(session, books.id, name="Gulf Supplies", type="vendor")


@pytest.fixture
def vat15(session: Session, books: Company):
    """The 15% sales tax the chart template creates."""
    from sqlalchemy import select

    from app.billing.models import Tax

    return session.execute(
        select(Tax).where(Tax.company_id == books.id, Tax.type == "sale", Tax.rate == Decimal(15))
    ).scalar_one()


@pytest.fixture
def vat15_purchase(session: Session, books: Company):
    from sqlalchemy import select

    from app.billing.models import Tax

    return session.execute(
        select(Tax).where(
            Tax.company_id == books.id, Tax.type == "purchase", Tax.rate == Decimal(15)
        )
    ).scalar_one()
