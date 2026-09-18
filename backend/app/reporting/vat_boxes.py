"""ZATCA's VAT return boxes, and which of our grid tags belong in each (R6.AC2).

The boxes are ZATCA's structure and the tags are ours, so the mapping is data. A tax created
with a tag already listed here lands in the right box without any code changing; a tax
created with a tag nobody mapped is reported as untagged rather than quietly dropped
(`R6.AC7`), because a figure missing from a filed return is worse than a figure in the wrong
place — at least an untagged one is visible.

Box numbers follow ZATCA's VAT return form. Verify them against the current form before a
real filing; the numbering has been stable, but the form is theirs to change.
"""

from dataclasses import dataclass

SALES = "sales"
PURCHASES = "purchases"


@dataclass(frozen=True, slots=True)
class VatBox:
    number: int
    name: str
    name_ar: str
    side: str
    """``sales`` for output tax, ``purchases`` for input tax (R6.AC3)."""

    taxable: bool = True
    """False where ZATCA expects the supply reported but no tax with it."""


BOXES: dict[str, VatBox] = {
    "sales_standard": VatBox(1, "Standard rated sales", "المبيعات الخاضعة للنسبة الأساسية", SALES),
    "sales_citizen_services": VatBox(
        2,
        "Private healthcare and education to citizens",
        "الخدمات الصحية والتعليمية الخاصة للمواطنين",
        SALES,
    ),
    "sales_zero_rated": VatBox(
        3, "Zero rated domestic sales", "المبيعات المحلية الخاضعة لنسبة الصفر", SALES, taxable=False
    ),
    "sales_exports": VatBox(4, "Exports", "الصادرات", SALES, taxable=False),
    "sales_exempt": VatBox(5, "Exempt sales", "المبيعات المعفاة", SALES, taxable=False),
    "purchases_standard": VatBox(
        7, "Standard rated domestic purchases", "المشتريات المحلية الخاضعة للضريبة", PURCHASES
    ),
    "purchases_imports_customs": VatBox(
        8, "Imports taxed at customs", "الواردات الخاضعة للضريبة لدى الجمارك", PURCHASES
    ),
    "purchases_imports_reverse": VatBox(
        9,
        "Imports under the reverse charge",
        "الواردات الخاضعة لآلية الاحتساب العكسي",
        PURCHASES,
    ),
    "purchases_zero_rated": VatBox(
        10, "Zero rated purchases", "المشتريات الخاضعة لنسبة الصفر", PURCHASES, taxable=False
    ),
    "purchases_exempt": VatBox(
        11, "Exempt purchases", "المشتريات المعفاة", PURCHASES, taxable=False
    ),
}

# Boxes 6 and 12 are the totals of the two sides; 13 to 16 are worked out from them.
TOTAL_SALES_BOX = 6
TOTAL_PURCHASES_BOX = 12
NET_TAX_BOX = 16


def box_for(grid_tag: str | None) -> VatBox | None:
    """The box a tagged line belongs in, or None when nobody has mapped that tag."""
    if grid_tag is None:
        return None
    return BOXES.get(grid_tag)
