"""The period a report covers (R1.AC7, R3.AC5, R8.AC2, R8.AC3). No database in sight."""

from datetime import date

import pytest

from app.reporting.periods import Period, fiscal_quarter, fiscal_year_bounds, resolve
from app.shared.errors import DomainError

# A Saudi company on a calendar year, and one whose year starts in April.
JANUARY = 1
APRIL = 4


class TestFiscalYears:
    def test_a_calendar_year_starts_in_january(self) -> None:
        assert fiscal_year_bounds(date(2026, 6, 15), JANUARY) == (
            date(2026, 1, 1),
            date(2026, 12, 31),
        )

    def test_an_april_year_containing_june(self) -> None:
        """R3.AC5"""
        assert fiscal_year_bounds(date(2026, 6, 15), APRIL) == (
            date(2026, 4, 1),
            date(2027, 3, 31),
        )

    def test_an_april_year_containing_february(self) -> None:
        """February 2026 belongs to the year that started in April 2025."""
        assert fiscal_year_bounds(date(2026, 2, 15), APRIL) == (
            date(2025, 4, 1),
            date(2026, 3, 31),
        )

    def test_the_first_and_last_day_belong_to_their_own_year(self) -> None:
        assert fiscal_year_bounds(date(2026, 4, 1), APRIL)[0] == date(2026, 4, 1)
        assert fiscal_year_bounds(date(2026, 3, 31), APRIL)[1] == date(2026, 3, 31)

    def test_a_leap_year_is_still_a_year(self) -> None:
        assert fiscal_year_bounds(date(2028, 5, 1), APRIL) == (
            date(2028, 4, 1),
            date(2029, 3, 31),
        )


class TestQuarters:
    def test_q1_starts_when_the_fiscal_year_does(self) -> None:
        """R8.AC3 — not January, unless the company's year starts in January."""
        assert fiscal_quarter(1, date(2026, 6, 15), APRIL) == (
            date(2026, 4, 1),
            date(2026, 6, 30),
        )

    def test_q4_ends_when_the_fiscal_year_does(self) -> None:
        assert fiscal_quarter(4, date(2026, 6, 15), APRIL) == (
            date(2027, 1, 1),
            date(2027, 3, 31),
        )

    def test_a_calendar_companys_q1_is_january_to_march(self) -> None:
        assert fiscal_quarter(1, date(2026, 6, 15), JANUARY) == (
            date(2026, 1, 1),
            date(2026, 3, 31),
        )

    @pytest.mark.parametrize("quarter", [0, 5, -1])
    def test_there_are_only_four_quarters(self, quarter: int) -> None:
        with pytest.raises(DomainError) as caught:
            fiscal_quarter(quarter, date(2026, 6, 15), JANUARY)
        assert caught.value.code == "reporting.invalid_period"


class TestResolving:
    def test_no_period_means_the_fiscal_year_to_date(self) -> None:
        """R8.AC2"""
        period = resolve(start_month=APRIL, today=date(2026, 6, 15))
        assert (period.start, period.end) == (date(2026, 4, 1), date(2026, 6, 15))

    def test_an_explicit_range_is_taken_as_given(self) -> None:
        period = resolve(
            start_month=JANUARY,
            today=date(2026, 6, 15),
            start=date(2026, 2, 1),
            end=date(2026, 2, 28),
        )
        assert (period.start, period.end) == (date(2026, 2, 1), date(2026, 2, 28))

    def test_last_fiscal_year(self) -> None:
        period = resolve(start_month=APRIL, today=date(2026, 6, 15), named="last-fiscal-year")
        assert (period.start, period.end) == (date(2025, 4, 1), date(2026, 3, 31))

    def test_this_month(self) -> None:
        period = resolve(start_month=JANUARY, today=date(2026, 2, 10), named="this-month")
        assert (period.start, period.end) == (date(2026, 2, 1), date(2026, 2, 28))

    def test_last_month_across_a_year_boundary(self) -> None:
        period = resolve(start_month=JANUARY, today=date(2026, 1, 10), named="last-month")
        assert (period.start, period.end) == (date(2025, 12, 1), date(2025, 12, 31))

    def test_a_named_quarter(self) -> None:
        period = resolve(start_month=APRIL, today=date(2026, 6, 15), named="q2")
        assert (period.start, period.end) == (date(2026, 7, 1), date(2026, 9, 30))


class TestWhatIsRefused:
    def test_a_range_that_ends_before_it_starts(self) -> None:
        """R1.AC7"""
        with pytest.raises(DomainError) as caught:
            Period(date(2026, 3, 31), date(2026, 3, 1), "backwards")
        assert caught.value.code == "reporting.invalid_period"

    def test_half_a_range(self) -> None:
        with pytest.raises(DomainError) as caught:
            resolve(start_month=JANUARY, today=date(2026, 6, 15), start=date(2026, 1, 1))
        assert caught.value.code == "reporting.invalid_period"

    def test_a_range_and_a_name_together(self) -> None:
        with pytest.raises(DomainError) as caught:
            resolve(
                start_month=JANUARY,
                today=date(2026, 6, 15),
                start=date(2026, 1, 1),
                end=date(2026, 3, 31),
                named="q1",
            )
        assert caught.value.code == "reporting.invalid_period"

    def test_a_name_nobody_defined(self) -> None:
        with pytest.raises(DomainError) as caught:
            resolve(start_month=JANUARY, today=date(2026, 6, 15), named="last-fortnight")
        assert caught.value.code == "reporting.invalid_period"


def test_a_single_day_is_a_period_of_one_day() -> None:
    assert Period(date(2026, 3, 1), date(2026, 3, 1), "one day").days == 1
