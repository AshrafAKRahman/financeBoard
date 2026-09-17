from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal(0)


def quantize(amount: Decimal, decimal_places: int) -> Decimal:
    """Round half away from zero, matching PostgreSQL's ``round(numeric, int)``."""
    return amount.quantize(Decimal(1).scaleb(-decimal_places), rounding=ROUND_HALF_UP)


def is_rounded(amount: Decimal, decimal_places: int) -> bool:
    return amount == quantize(amount, decimal_places)
