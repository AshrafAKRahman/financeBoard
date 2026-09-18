"""Realised exchange differences (R5).

When a foreign-currency invoice is settled, the two sides close in the transaction currency
but rarely in company currency: the rate moved between issuing and paying. That gap is a
real gain or loss, and this module works out how much.

The rule needs no knowledge of receivables or payables. A match pairs a debit line with a
credit line; if the debit side is worth more in company currency, the account is left with a
debit balance that has to be credited away, and the other half of that entry is a loss. If
the credit side is worth more, it is a gain. Reading it off the sides rather than off the
document type is what makes one function right for customers and vendors alike.

No I/O here, so the arithmetic can be reasoned about — and property-tested — on its own.
"""

from dataclasses import dataclass
from decimal import Decimal

from app.shared.money import ZERO


@dataclass(frozen=True, slots=True)
class MatchedSide:
    """One side of a match, as far as this match goes."""

    amount: Decimal
    """The company-currency amount this match settles on this side (positive)."""

    amount_currency: Decimal
    """The transaction-currency amount this match settles on this side (positive)."""

    currency_code: str


@dataclass(frozen=True, slots=True)
class Difference:
    """What the rate did between the two sides of a match."""

    amount: Decimal
    """How far apart the sides are in company currency, always positive."""

    is_gain: bool

    @property
    def default_key(self) -> str:
        """Which company default account the difference belongs to."""
        return "fx_gain" if self.is_gain else "fx_loss"


def difference_between(
    debit_side: MatchedSide,
    credit_side: MatchedSide,
    *,
    base_currency: str,
) -> Difference | None:
    """The realised gain or loss this match creates, or None when there is none."""
    # R5.AC7 — a match wholly in company currency cannot move with the rate.
    if debit_side.currency_code == base_currency and credit_side.currency_code == base_currency:
        return None

    # Two different foreign currencies have no single rate to compare, so the caller has
    # already converted; anything left over is not an exchange difference.
    if debit_side.currency_code != credit_side.currency_code:
        return None

    gap = credit_side.amount - debit_side.amount
    if gap == ZERO:
        return None

    # The credit side was worth more than the debit it cleared: a gain (R5.AC2).
    return Difference(amount=abs(gap), is_gain=gap > ZERO)
