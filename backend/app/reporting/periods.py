"""The period a report covers (R8.AC2, R8.AC3).

A fiscal year that starts in April is not a calendar year, and "Q1" means the company's
first quarter, not January to March. Everything here follows the company's configured
fiscal year start month, and nothing here touches the database beyond reading the company.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from app.platform.tenancy.api import fiscal_year
from app.shared.errors import DomainError

NAMED = (
    "this-fiscal-year",
    "last-fiscal-year",
    "this-month",
    "last-month",
    "q1",
    "q2",
    "q3",
    "q4",
)


@dataclass(frozen=True, slots=True)
class Period:
    """A closed date range: both ends are included."""

    start: date
    end: date
    label: str

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise DomainError(
                "reporting.invalid_period",
                f"{self.end} is before {self.start}",
            )

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def _add_months(on: date, months: int) -> date:
    """The same day of a month ahead or behind, clamped to that month's length."""
    total = on.month - 1 + months
    year = on.year + total // 12
    month = total % 12 + 1
    day = min(on.day, _days_in(year, month))
    return date(year, month, day)


def _days_in(year: int, month: int) -> int:
    first = date(year, month, 1)
    following = date(year + (month == 12), month % 12 + 1, 1)
    return (following - first).days


def fiscal_year_bounds(on: date, start_month: int) -> tuple[date, date]:
    """The fiscal year containing ``on`` (R3.AC5)."""
    start = date(fiscal_year(on, start_month), start_month, 1)
    return start, _add_months(start, 12) - timedelta(days=1)


def fiscal_quarter(quarter: int, on: date, start_month: int) -> tuple[date, date]:
    """Quarter 1 starts when the company's fiscal year does, not in January (R8.AC3)."""
    if not 1 <= quarter <= 4:
        raise DomainError("reporting.invalid_period", f"{quarter} is not a quarter")
    year_start, _ = fiscal_year_bounds(on, start_month)
    start = _add_months(year_start, (quarter - 1) * 3)
    return start, _add_months(start, 3) - timedelta(days=1)


def resolve(
    *,
    start_month: int,
    today: date,
    start: date | None = None,
    end: date | None = None,
    named: str | None = None,
) -> Period:
    """The period a report covers: an explicit range, a named one, or the year to date."""
    if named is not None and (start is not None or end is not None):
        raise DomainError(
            "reporting.invalid_period",
            "give either a named period or a date range, not both",
        )

    if start is not None or end is not None:
        if start is None or end is None:
            raise DomainError("reporting.invalid_period", "a date range needs both ends")
        return Period(start, end, f"{start.isoformat()} to {end.isoformat()}")

    if named is None:
        # R8.AC2 — the fiscal year to date is what an accountant means by "so far".
        year_start, _ = fiscal_year_bounds(today, start_month)
        return Period(year_start, today, "Fiscal year to date")

    return _named(named, today=today, start_month=start_month)


def _named(named: str, *, today: date, start_month: int) -> Period:
    if named == "this-fiscal-year":
        start, end = fiscal_year_bounds(today, start_month)
        return Period(start, end, f"Fiscal year {start.year}")

    if named == "last-fiscal-year":
        start, _ = fiscal_year_bounds(today, start_month)
        previous_start, previous_end = fiscal_year_bounds(start - timedelta(days=1), start_month)
        return Period(previous_start, previous_end, f"Fiscal year {previous_start.year}")

    if named == "this-month":
        start = today.replace(day=1)
        return Period(start, _add_months(start, 1) - timedelta(days=1), start.strftime("%B %Y"))

    if named == "last-month":
        start = _add_months(today.replace(day=1), -1)
        return Period(start, _add_months(start, 1) - timedelta(days=1), start.strftime("%B %Y"))

    if named in ("q1", "q2", "q3", "q4"):
        quarter = int(named[1])
        start, end = fiscal_quarter(quarter, today, start_month)
        return Period(start, end, f"Q{quarter} {start.year}")

    raise DomainError(
        "reporting.invalid_period",
        f"{named!r} is not a period; try one of {', '.join(NAMED)}",
    )
