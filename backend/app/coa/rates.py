"""Exchange rates: what the ledger converts foreign-currency documents with."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ledger.api import ExchangeRate
from app.platform.audit.api import Actor, record
from app.platform.tenancy.api import Company, Currency
from app.shared.errors import DomainError
from app.shared.ids import uuid7


@dataclass(frozen=True, slots=True)
class RateRow:
    currency_code: str
    rate_date: date
    rate: Decimal


@dataclass
class ImportResult:
    recorded: int = 0
    rejected: list[tuple[int, str]] = field(default_factory=list)


def _company(session: Session, company_id: UUID) -> Company:
    company = session.get(Company, company_id)
    if company is None:
        raise DomainError("coa.company_not_found", f"company {company_id} not found")
    return company


def set_rate(
    session: Session,
    company_id: UUID,
    currency_code: str,
    on: date,
    rate: Decimal,
    *,
    actor: Actor | None = None,
) -> ExchangeRate:
    """One rate per currency per day: a second one for the same day replaces it (R7.AC2)."""
    company = _company(session, company_id)
    code = currency_code.strip().upper()

    if session.get(Currency, code) is None:
        raise DomainError("coa.currency_not_found", f"{code} is not a known currency")
    if code == company.base_currency:
        raise DomainError(
            "coa.base_currency_rate",
            f"{code} is the company's own currency, so it needs no rate",
        )
    if rate <= 0:
        raise DomainError("coa.invalid_rate", "a rate must be greater than zero")

    existing = session.execute(
        select(ExchangeRate).where(
            ExchangeRate.company_id == company_id,
            ExchangeRate.currency_code == code,
            ExchangeRate.rate_date == on,
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.rate = rate
        stored = existing
    else:
        stored = ExchangeRate(
            id=uuid7(),
            company_id=company_id,
            currency_code=code,
            rate_date=on,
            rate=rate,
        )
        session.add(stored)
    session.flush()

    record(
        session,
        action="exchange_rate.set",
        actor=actor,
        company_id=company_id,
        target_type="exchange_rate",
        target_id=stored.id,
        detail={"currency": code, "date": on.isoformat(), "rate": str(rate)},
    )
    return stored


def list_rates(
    session: Session, company_id: UUID, currency_code: str | None = None
) -> Sequence[ExchangeRate]:
    query = select(ExchangeRate).where(ExchangeRate.company_id == company_id)
    if currency_code:
        query = query.where(ExchangeRate.currency_code == currency_code.strip().upper())
    return (
        session.execute(query.order_by(ExchangeRate.currency_code, ExchangeRate.rate_date))
        .scalars()
        .all()
    )


def import_rates(
    session: Session,
    company_id: UUID,
    rows: Sequence[dict[str, Any]],
    *,
    actor: Actor | None = None,
) -> ImportResult:
    """Every valid row is recorded and every rejected row explained, so one bad line does
    not discard a month of rates (R7.AC6)."""
    result = ImportResult()

    for index, row in enumerate(rows, start=1):
        try:
            parsed = _parse_row(row)
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            result.rejected.append((index, f"could not be read: {exc}"))
            continue

        try:
            with session.begin_nested():
                set_rate(
                    session,
                    company_id,
                    parsed.currency_code,
                    parsed.rate_date,
                    parsed.rate,
                    actor=actor,
                )
            result.recorded += 1
        except DomainError as error:
            result.rejected.append((index, error.message))

    record(
        session,
        action="exchange_rate.imported",
        actor=actor,
        company_id=company_id,
        detail={"recorded": result.recorded, "rejected": len(result.rejected)},
    )
    return result


def _parse_row(row: dict[str, Any]) -> RateRow:
    currency = str(row["currency_code"]).strip().upper()
    raw_date = row["rate_date"]
    rate_date = raw_date if isinstance(raw_date, date) else date.fromisoformat(str(raw_date))
    return RateRow(currency, rate_date, Decimal(str(row["rate"])))
