from datetime import date

from app.platform.tenancy.models import Company, Currency

__all__ = ["Company", "Currency", "fiscal_year"]


def fiscal_year(on: date, start_month: int) -> int:
    """The calendar year in which the fiscal year containing ``on`` starts."""
    if not 1 <= start_month <= 12:
        raise ValueError(f"start_month must be 1-12, got {start_month}")
    return on.year if on.month >= start_month else on.year - 1
