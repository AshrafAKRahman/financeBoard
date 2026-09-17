from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ledger.models import ExchangeRate
from app.platform.tenancy.api import Company, Currency
from app.shared.errors import DomainError


def currency_places(session: Session, code: str) -> int:
    currency = session.get(Currency, code)
    if currency is None:
        raise DomainError("ledger.currency_not_found", f"unknown currency {code}")
    return currency.decimal_places


def get_rate(session: Session, company: Company, currency_code: str, on: date) -> Decimal:
    """Company-currency value of one unit of ``currency_code`` on ``on``: the latest rate
    dated on or before that day. A missing rate is an error, never a silent 1."""
    if currency_code == company.base_currency:
        return Decimal(1)

    rate = session.execute(
        select(ExchangeRate.rate)
        .where(
            ExchangeRate.company_id == company.id,
            ExchangeRate.currency_code == currency_code,
            ExchangeRate.rate_date <= on,
        )
        .order_by(ExchangeRate.rate_date.desc())
        .limit(1)
    ).scalar_one_or_none()

    if rate is None:
        raise DomainError(
            "ledger.rate_missing",
            f"no {currency_code} rate on or before {on.isoformat()} for {company.name}",
        )
    return rate
