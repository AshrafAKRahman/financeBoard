"""Realised exchange differences (R5). Pure arithmetic, so no database in sight."""

from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from app.treasury.exchange import MatchedSide, difference_between


def d(value: str) -> Decimal:
    return Decimal(value)


def side(amount: str, foreign: str, currency: str = "USD") -> MatchedSide:
    return MatchedSide(amount=d(amount), amount_currency=d(foreign), currency_code=currency)


class TestACustomerInvoice:
    def test_a_weaker_rate_at_payment_is_a_loss(self) -> None:
        """R5.AC3 — invoiced USD 100 at 3.80, received it when USD was worth 3.75."""
        difference = difference_between(
            side("380.00", "100"), side("375.00", "100"), base_currency="SAR"
        )

        assert difference is not None
        assert difference.amount == d("5.00")
        assert not difference.is_gain
        assert difference.default_key == "fx_loss"

    def test_a_stronger_rate_at_payment_is_a_gain(self) -> None:
        """R5.AC2 — the receipt was worth more than the invoice it settled."""
        difference = difference_between(
            side("380.00", "100"), side("390.00", "100"), base_currency="SAR"
        )

        assert difference is not None
        assert (difference.amount, difference.is_gain) == (d("10.00"), True)
        assert difference.default_key == "fx_gain"


class TestAVendorBill:
    def test_paying_less_than_the_bill_was_worth_is_a_gain(self) -> None:
        """The bill is the credit side; the payment debits it. R5.AC2 from the other end."""
        difference = difference_between(
            side("375.00", "100"), side("380.00", "100"), base_currency="SAR"
        )

        assert difference is not None
        assert (difference.amount, difference.is_gain) == (d("5.00"), True)

    def test_paying_more_than_the_bill_was_worth_is_a_loss(self) -> None:
        difference = difference_between(
            side("390.00", "100"), side("380.00", "100"), base_currency="SAR"
        )

        assert difference is not None
        assert (difference.amount, difference.is_gain) == (d("10.00"), False)


class TestWhenThereIsNoDifference:
    def test_the_same_rate_on_both_sides_is_no_difference(self) -> None:
        assert (
            difference_between(side("380.00", "100"), side("380.00", "100"), base_currency="SAR")
            is None
        )

    def test_company_currency_never_produces_a_difference(self) -> None:
        """R5.AC7 — and the amounts here could not differ anyway."""
        assert (
            difference_between(
                side("100.00", "100", "SAR"),
                side("100.00", "100", "SAR"),
                base_currency="SAR",
            )
            is None
        )

    def test_a_company_currency_line_paid_in_company_currency_is_left_alone(self) -> None:
        """R5.AC7 — even if the caller passes amounts that disagree, SAR has no rate."""
        assert (
            difference_between(
                side("100.00", "100", "SAR"),
                side("99.00", "99", "SAR"),
                base_currency="SAR",
            )
            is None
        )

    def test_two_different_foreign_currencies_are_not_a_rate_difference(self) -> None:
        assert (
            difference_between(
                side("380.00", "100", "USD"),
                side("375.00", "92", "EUR"),
                base_currency="SAR",
            )
            is None
        )


class TestPartialSettlement:
    def test_only_the_matched_part_counts(self) -> None:
        """Half of a USD 200 invoice, settled at a rate 0.10 lower."""
        difference = difference_between(
            side("380.00", "100"), side("370.00", "100"), base_currency="SAR"
        )

        assert difference is not None
        assert difference.amount == d("10.00")


@given(
    invoice=st.decimals(min_value=d("0.01"), max_value=d("1000000"), places=2),
    payment=st.decimals(min_value=d("0.01"), max_value=d("1000000"), places=2),
)
def test_a_difference_is_always_positive_and_points_one_way(
    invoice: Decimal, payment: Decimal
) -> None:
    """Whatever the rates did, the amount is positive and the direction follows the sides."""
    difference = difference_between(
        MatchedSide(invoice, d("100"), "USD"),
        MatchedSide(payment, d("100"), "USD"),
        base_currency="SAR",
    )

    if invoice == payment:
        assert difference is None
        return

    assert difference is not None
    assert difference.amount > 0
    assert difference.amount == abs(payment - invoice)
    assert difference.is_gain == (payment > invoice)


@given(amount=st.decimals(min_value=d("0.01"), max_value=d("10000"), places=2))
def test_swapping_the_sides_swaps_the_direction(amount: Decimal) -> None:
    """The same gap read from the other side of the match is the opposite sign."""
    one = difference_between(
        MatchedSide(amount, d("100"), "USD"),
        MatchedSide(amount + d("7.00"), d("100"), "USD"),
        base_currency="SAR",
    )
    other = difference_between(
        MatchedSide(amount + d("7.00"), d("100"), "USD"),
        MatchedSide(amount, d("100"), "USD"),
        base_currency="SAR",
    )

    assert one is not None and other is not None
    assert one.amount == other.amount == d("7.00")
    assert one.is_gain is not other.is_gain
