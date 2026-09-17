"""Currency precision and date-based exchange-rate lookup (R7.AC2, R7.AC7, R7.AC8)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.ledger.api import currency_places, get_rate
from app.platform.tenancy.api import Company
from app.shared.errors import DomainError
from tests.factories import add_rate, make_books

pytestmark = pytest.mark.db


def company(session: Session, company_id) -> Company:
    return session.get(Company, company_id)  # type: ignore[return-value]


@pytest.mark.parametrize(("code", "places"), [("SAR", 2), ("USD", 2), ("KWD", 3), ("JPY", 0)])
def test_currency_places(session: Session, code: str, places: int) -> None:
    assert currency_places(session, code) == places


def test_unknown_currency_is_rejected(session: Session) -> None:
    with pytest.raises(DomainError) as error:
        currency_places(session, "XXX")
    assert error.value.code == "ledger.currency_not_found"


def test_base_currency_always_rates_one(session: Session) -> None:
    books = make_books(session)
    assert get_rate(session, company(session, books.company_id), "SAR", date(2026, 3, 1)) == 1


def test_uses_the_latest_rate_on_or_before_the_date(session: Session) -> None:
    books = make_books(session)
    add_rate(session, books, "USD", date(2026, 1, 1), "3.7500")
    add_rate(session, books, "USD", date(2026, 3, 1), "3.7550")
    add_rate(session, books, "USD", date(2026, 6, 1), "3.7600")
    subject = company(session, books.company_id)

    assert get_rate(session, subject, "USD", date(2026, 1, 1)) == Decimal("3.7500")
    assert get_rate(session, subject, "USD", date(2026, 2, 28)) == Decimal("3.7500")
    assert get_rate(session, subject, "USD", date(2026, 3, 1)) == Decimal("3.7550")
    assert get_rate(session, subject, "USD", date(2026, 5, 31)) == Decimal("3.7550")
    assert get_rate(session, subject, "USD", date(2027, 1, 1)) == Decimal("3.7600")


def test_missing_rate_is_an_error_not_a_default_of_one(session: Session) -> None:
    books = make_books(session)
    add_rate(session, books, "USD", date(2026, 3, 1), "3.7550")
    subject = company(session, books.company_id)

    with pytest.raises(DomainError) as error:
        get_rate(session, subject, "USD", date(2026, 2, 28))
    assert error.value.code == "ledger.rate_missing"

    with pytest.raises(DomainError) as no_currency:
        get_rate(session, subject, "EUR", date(2026, 3, 1))
    assert no_currency.value.code == "ledger.rate_missing"


def test_rates_are_scoped_to_one_company(session: Session) -> None:
    ours = make_books(session)
    theirs = make_books(session)
    add_rate(session, theirs, "USD", date(2026, 1, 1), "3.7500")

    with pytest.raises(DomainError) as error:
        get_rate(session, company(session, ours.company_id), "USD", date(2026, 3, 1))
    assert error.value.code == "ledger.rate_missing"


def test_a_company_with_a_foreign_base_currency_needs_no_rate(session: Session) -> None:
    books = make_books(session, base_currency="USD")
    subject = company(session, books.company_id)
    assert get_rate(session, subject, "USD", date(2026, 3, 1)) == 1
    with pytest.raises(DomainError):
        get_rate(session, subject, "SAR", date(2026, 3, 1))
