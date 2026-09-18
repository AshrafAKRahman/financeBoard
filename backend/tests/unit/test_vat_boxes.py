"""Which ZATCA box a grid tag belongs in (R6.AC3, R6.AC5). Pure data, checked for sense."""

import pytest

from app.billing.taxes import SAUDI_TAXES
from app.reporting.vat_boxes import BOXES, PURCHASES, SALES, box_for


def test_every_tag_the_saudi_chart_installs_has_a_box() -> None:
    """The taxes a Saudi company starts with must all be reportable."""
    installed = {tax["grid_tag"] for tax in SAUDI_TAXES if tax.get("grid_tag")}
    assert installed <= set(BOXES), f"unmapped: {installed - set(BOXES)}"


def test_box_numbers_are_unique() -> None:
    numbers = [box.number for box in BOXES.values()]
    assert len(numbers) == len(set(numbers))


def test_sales_and_purchases_are_separated() -> None:
    """R6.AC3 — output tax and input tax are different halves of the return."""
    assert {box.side for box in BOXES.values()} == {SALES, PURCHASES}
    assert box_for("sales_standard").side == SALES
    assert box_for("purchases_standard").side == PURCHASES


def test_standard_rates_carry_tax_and_zero_rates_do_not() -> None:
    """R6.AC5 — a zero-rated supply is reported, with no tax beside it."""
    assert box_for("sales_standard").taxable
    assert not box_for("sales_zero_rated").taxable
    assert not box_for("sales_exempt").taxable


def test_sales_boxes_come_before_purchase_boxes() -> None:
    """ZATCA's form puts sales first; a return that reordered them would confuse a filer."""
    sales = max(box.number for box in BOXES.values() if box.side == SALES)
    purchases = min(box.number for box in BOXES.values() if box.side == PURCHASES)
    assert sales < purchases


def test_every_box_is_named_in_both_languages() -> None:
    for tag, box in BOXES.items():
        assert box.name.strip(), tag
        assert box.name_ar.strip(), tag


@pytest.mark.parametrize("tag", [None, "", "something_nobody_mapped"])
def test_an_unmapped_tag_has_no_box(tag) -> None:
    """R6.AC7 — reported as untagged rather than dropped or guessed."""
    assert box_for(tag) is None
