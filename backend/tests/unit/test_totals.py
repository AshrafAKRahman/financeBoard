"""What a document adds up to (R2). Pure arithmetic, so no database in sight."""

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.billing.totals import (
    LineInput,
    TaxRate,
    document_totals,
    line_amounts,
)
from app.shared.ids import uuid7

VAT15 = TaxRate(id=uuid7(), name="VAT 15%", rate=Decimal("15"))
VAT5 = TaxRate(id=uuid7(), name="VAT 5%", rate=Decimal("5"))
ZERO_RATED = TaxRate(id=uuid7(), name="Zero rated", rate=Decimal("0"), vat_category="zero_rated")


def d(value: str) -> Decimal:
    return Decimal(value)


class TestOneLine:
    def test_quantity_times_price_with_vat(self) -> None:
        line = LineInput(quantity=d("3"), unit_price=d("100.00"), taxes=[VAT15])
        amounts = line_amounts(line, 2)

        assert amounts.net == d("300.00")
        assert amounts.tax_total == d("45.00")
        assert amounts.gross == d("345.00")

    def test_tax_is_rounded_per_line(self) -> None:
        """R2.AC1 — 33.33 x 15% = 4.9995, which becomes 5.00 on this line."""
        amounts = line_amounts(LineInput(d("1"), d("33.33"), [VAT15]), 2)
        assert amounts.taxes[0].amount == d("5.00")

    def test_a_discount_reduces_the_base(self) -> None:
        """R2.AC2"""
        amounts = line_amounts(
            LineInput(d("2"), d("50.00"), [VAT15], discount_percent=d("10")), 2
        )
        assert amounts.net == d("90.00")
        assert amounts.tax_total == d("13.50")

    def test_several_taxes_are_not_compounded(self) -> None:
        """R2.AC4 — both are charged on the same net, never tax on tax."""
        amounts = line_amounts(LineInput(d("1"), d("200.00"), [VAT15, VAT5]), 2)

        assert [entry.amount for entry in amounts.taxes] == [d("30.00"), d("10.00")]
        assert all(entry.base == d("200.00") for entry in amounts.taxes)
        assert amounts.gross == d("240.00")

    def test_tax_inclusive_prices_work_backwards(self) -> None:
        """R2.AC3 — 115.00 including 15% is 100.00 plus 15.00."""
        amounts = line_amounts(LineInput(d("1"), d("115.00"), [VAT15]), 2, tax_inclusive=True)

        assert amounts.net == d("100.00")
        assert amounts.tax_total == d("15.00")
        assert amounts.gross == d("115.00")

    def test_a_zero_rate_still_appears_as_a_tax(self) -> None:
        """A zero-rated line is not an untaxed line: ZATCA wants it reported."""
        amounts = line_amounts(LineInput(d("1"), d("500.00"), [ZERO_RATED]), 2)

        assert amounts.tax_total == d("0.00")
        assert len(amounts.taxes) == 1
        assert amounts.taxes[0].tax.vat_category == "zero_rated"

    def test_a_line_with_no_taxes_is_its_own_gross(self) -> None:
        amounts = line_amounts(LineInput(d("4"), d("25.00")), 2)
        assert (amounts.net, amounts.tax_total, amounts.gross) == (
            d("100.00"),
            d("0"),
            d("100.00"),
        )

    def test_three_decimal_currencies_keep_their_precision(self) -> None:
        amounts = line_amounts(LineInput(d("1"), d("10.005"), [VAT15]), 3)
        assert amounts.net == d("10.005")
        assert amounts.taxes[0].amount == d("1.501")


class TestDocument:
    def test_totals_add_the_lines_up(self) -> None:
        """R2.AC6"""
        totals = document_totals(
            [
                LineInput(d("1"), d("100.00"), [VAT15]),
                LineInput(d("2"), d("50.00"), [VAT15]),
            ],
            2,
        )
        assert totals.net == d("200.00")
        assert totals.tax_total == d("30.00")
        assert totals.total == d("230.00")

    def test_tax_is_grouped_by_tax(self) -> None:
        """R2.AC5 — the shape a VAT return and a ZATCA invoice both need."""
        totals = document_totals(
            [
                LineInput(d("1"), d("100.00"), [VAT15]),
                LineInput(d("1"), d("200.00"), [VAT5]),
                LineInput(d("1"), d("300.00"), [VAT15]),
            ],
            2,
        )
        groups = {group.tax.name: group for group in totals.tax_groups}

        assert set(groups) == {"VAT 15%", "VAT 5%"}
        assert groups["VAT 15%"].base == d("400.00")
        assert groups["VAT 15%"].amount == d("60.00")
        assert groups["VAT 5%"].amount == d("10.00")

    def test_rounding_happens_per_line_not_on_the_total(self) -> None:
        """R2.AC1 — three lines of 0.10 at 15% are 0.02 each, so 0.06, not 0.05."""
        totals = document_totals([LineInput(d("1"), d("0.10"), [VAT15])] * 3, 2)

        assert totals.net == d("0.30")
        assert totals.tax_total == d("0.06")
        assert totals.total == d("0.36")

    def test_an_empty_document_is_zero(self) -> None:
        totals = document_totals([], 2)
        assert (totals.net, totals.tax_total, totals.total) == (d("0"), d("0"), d("0"))

    def test_a_mixed_document_keeps_each_category(self) -> None:
        totals = document_totals(
            [LineInput(d("1"), d("100.00"), [VAT15]), LineInput(d("1"), d("100.00"), [ZERO_RATED])],
            2,
        )
        categories = {group.tax.vat_category: group.amount for group in totals.tax_groups}
        assert categories == {"standard": d("15.00"), "zero_rated": d("0.00")}


@given(
    amounts=st.lists(
        st.tuples(
            st.decimals(min_value=d("0.01"), max_value=d("9999.99"), places=2),
            st.integers(min_value=1, max_value=50),
            st.decimals(min_value=d("0"), max_value=d("100"), places=2),
        ),
        min_size=1,
        max_size=15,
    ),
    inclusive=st.booleans(),
)
def test_totals_always_hold_together(amounts: list, inclusive: bool) -> None:
    """Whatever the lines, net plus tax is the total and nothing is lost to rounding."""
    lines = [
        LineInput(
            quantity=Decimal(quantity),
            unit_price=price,
            taxes=[VAT15],
            discount_percent=discount,
        )
        for price, quantity, discount in amounts
    ]
    totals = document_totals(lines, 2, tax_inclusive=inclusive)
    computed = [line_amounts(line, 2, tax_inclusive=inclusive) for line in lines]

    assert totals.net == sum(line.net for line in computed)
    assert totals.tax_total == sum(line.tax_total for line in computed)
    assert totals.total == totals.net + totals.tax_total
    assert totals.total == sum(line.gross for line in computed)
    assert totals.net.as_tuple().exponent >= -2
    assert totals.tax_total.as_tuple().exponent >= -2


@pytest.mark.parametrize("places", [0, 2, 3])
def test_totals_respect_the_currencys_precision(places: int) -> None:
    totals = document_totals([LineInput(d("1"), d("123.456789"), [VAT15])], places)
    assert -totals.net.as_tuple().exponent == places
