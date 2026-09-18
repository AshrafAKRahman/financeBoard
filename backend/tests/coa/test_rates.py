"""Exchange rates and bulk import (R7)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.coa.rates import import_rates, list_rates, set_rate
from app.ledger.api import get_rate
from app.platform.tenancy.api import Company
from app.shared.errors import DomainError
from tests.factories import Books

pytestmark = pytest.mark.db


def test_a_rate_is_recorded_and_used_by_the_ledger(session: Session, books: Books) -> None:
    """R7.AC1"""
    set_rate(session, books.company_id, "USD", date(2026, 3, 1), Decimal("3.7500"))
    session.commit()

    company = session.get(Company, books.company_id)
    assert get_rate(session, company, "USD", date(2026, 3, 5)) == Decimal("3.7500")


def test_a_second_rate_for_the_same_day_replaces_it(session: Session, books: Books) -> None:
    """R7.AC2"""
    set_rate(session, books.company_id, "USD", date(2026, 3, 1), Decimal("3.7500"))
    set_rate(session, books.company_id, "USD", date(2026, 3, 1), Decimal("3.7600"))
    session.commit()

    rates = list_rates(session, books.company_id, "USD")
    assert [rate.rate for rate in rates] == [Decimal("3.7600")]


@pytest.mark.parametrize("bad", ["0", "-1", "-3.75"])
def test_a_rate_must_be_positive(session: Session, books: Books, bad: str) -> None:
    """R7.AC3"""
    with pytest.raises(DomainError) as error:
        set_rate(session, books.company_id, "USD", date(2026, 3, 1), Decimal(bad))
    assert error.value.code == "coa.invalid_rate"
    session.rollback()


def test_the_base_currency_needs_no_rate(session: Session, books: Books) -> None:
    """R7.AC4"""
    with pytest.raises(DomainError) as error:
        set_rate(session, books.company_id, "SAR", date(2026, 3, 1), Decimal("1"))
    assert error.value.code == "coa.base_currency_rate"
    session.rollback()


def test_an_unknown_currency_is_refused(session: Session, books: Books) -> None:
    with pytest.raises(DomainError) as error:
        set_rate(session, books.company_id, "XXX", date(2026, 3, 1), Decimal("1"))
    assert error.value.code == "coa.currency_not_found"
    session.rollback()


def test_rates_come_back_in_date_order(session: Session, books: Books) -> None:
    """R7.AC5"""
    for day, rate in [(5, "3.77"), (1, "3.75"), (3, "3.76")]:
        set_rate(session, books.company_id, "USD", date(2026, 3, day), Decimal(rate))
    session.commit()

    dates = [rate.rate_date.day for rate in list_rates(session, books.company_id, "USD")]
    assert dates == [1, 3, 5]


def test_rates_are_scoped_to_one_company(
    session: Session, books: Books, empty_company
) -> None:
    set_rate(session, books.company_id, "USD", date(2026, 3, 1), Decimal("3.75"))
    session.commit()
    assert list_rates(session, empty_company.id, "USD") == []


class TestImport:
    def test_valid_rows_are_recorded(self, session: Session, books: Books) -> None:
        """R7.AC6"""
        result = import_rates(
            session,
            books.company_id,
            [
                {"currency_code": "USD", "rate_date": "2026-03-01", "rate": "3.7500"},
                {"currency_code": "EUR", "rate_date": date(2026, 3, 1), "rate": Decimal("4.05")},
            ],
        )
        session.commit()

        assert (result.recorded, result.rejected) == (2, [])
        assert len(list_rates(session, books.company_id)) == 2

    def test_bad_rows_are_reported_with_a_reason_and_the_rest_still_land(
        self, session: Session, books: Books
    ) -> None:
        """R7.AC6 — one bad line must not discard a month of rates."""
        result = import_rates(
            session,
            books.company_id,
            [
                {"currency_code": "USD", "rate_date": "2026-03-01", "rate": "3.7500"},
                {"currency_code": "SAR", "rate_date": "2026-03-01", "rate": "1"},
                {"currency_code": "USD", "rate_date": "2026-03-02", "rate": "-1"},
                {"currency_code": "ZZZ", "rate_date": "2026-03-02", "rate": "2"},
                {"currency_code": "USD", "rate_date": "not-a-date", "rate": "2"},
                {"rate_date": "2026-03-03", "rate": "2"},
                {"currency_code": "EUR", "rate_date": "2026-03-03", "rate": "4.10"},
            ],
        )
        session.commit()

        assert result.recorded == 2
        assert [row for row, _ in result.rejected] == [2, 3, 4, 5, 6]
        assert "own currency" in dict(result.rejected)[2]
        assert "greater than zero" in dict(result.rejected)[3]
        assert len(list_rates(session, books.company_id)) == 2

    def test_an_empty_import_is_harmless(self, session: Session, books: Books) -> None:
        result = import_rates(session, books.company_id, [])
        session.commit()
        assert (result.recorded, result.rejected) == (0, [])
