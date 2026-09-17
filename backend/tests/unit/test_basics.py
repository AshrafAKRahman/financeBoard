from datetime import date
from decimal import Decimal

import pytest

from app.db import sqlalchemy_url
from app.platform.tenancy.api import fiscal_year
from app.shared.money import is_rounded, quantize


@pytest.mark.parametrize(
    ("value", "places", "expected"),
    [
        ("1.005", 2, "1.01"),
        ("-1.005", 2, "-1.01"),  # half away from zero, like PostgreSQL round()
        ("2.5", 0, "3"),
        ("1.0004", 3, "1.000"),
    ],
)
def test_quantize(value: str, places: int, expected: str) -> None:
    assert quantize(Decimal(value), places) == Decimal(expected)


def test_is_rounded() -> None:
    assert is_rounded(Decimal("10.50"), 2)
    assert not is_rounded(Decimal("10.501"), 2)


@pytest.mark.parametrize(
    ("on", "start_month", "expected"),
    [
        (date(2026, 3, 1), 1, 2026),
        (date(2026, 3, 1), 4, 2025),
        (date(2026, 4, 1), 4, 2026),
        (date(2026, 12, 31), 7, 2026),
    ],
)
def test_fiscal_year(on: date, start_month: int, expected: int) -> None:
    assert fiscal_year(on, start_month) == expected


def test_neon_url_uses_psycopg() -> None:
    url = sqlalchemy_url("postgresql://u:p@ep-x.eu-central-1.aws.neon.tech/app?sslmode=require")
    assert url.drivername == "postgresql+psycopg"
    assert url.query["sslmode"] == "require"
