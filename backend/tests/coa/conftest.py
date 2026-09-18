"""Shared fixtures for chart-of-accounts service tests."""

import pytest
from sqlalchemy.orm import Session

from app.coa.accounts import AccountData, create_account
from tests.factories import Books, make_books


@pytest.fixture
def books(session: Session) -> Books:
    """A company with the ledger's test chart already in place."""
    return make_books(session)


@pytest.fixture
def empty_company(session: Session):
    """A company with no accounts, journals or defaults at all."""
    from app.ledger.api import LedgerSettings
    from app.platform.tenancy.api import Company
    from app.shared.ids import uuid7

    company = Company(id=uuid7(), name="Empty Co", base_currency="SAR")
    session.add(company)
    session.flush()
    session.add(LedgerSettings(company_id=company.id))
    session.commit()
    return company


def account(session: Session, company_id, code: str, **kwargs):
    data = AccountData(
        code=code,
        name=kwargs.pop("name", f"Account {code}"),
        type=kwargs.pop("type", "asset"),
        subtype=kwargs.pop("subtype", "current_asset"),
        **kwargs,
    )
    return create_account(session, company_id, data)
