"""What a document adds up to.

Pure arithmetic, no database: the screen, the posting request and (next feature) the ZATCA
XML all call this, so the three can never disagree. Tax is rounded per line and then summed,
which is decision D2 and matches ZATCA's line-level amounts.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from app.shared.money import ZERO, quantize

HUNDRED = Decimal(100)


@dataclass(frozen=True, slots=True)
class TaxRate:
    """Just enough of a tax to do arithmetic with it."""

    id: UUID
    name: str
    rate: Decimal
    vat_category: str = "standard"


@dataclass(frozen=True, slots=True)
class LineInput:
    quantity: Decimal
    unit_price: Decimal
    taxes: Sequence[TaxRate] = ()
    discount_percent: Decimal = ZERO


@dataclass(frozen=True, slots=True)
class TaxAmount:
    tax: TaxRate
    base: Decimal
    amount: Decimal


@dataclass(frozen=True, slots=True)
class LineAmounts:
    net: Decimal
    taxes: tuple[TaxAmount, ...]
    tax_total: Decimal
    gross: Decimal


@dataclass(frozen=True, slots=True)
class TaxGroup:
    tax: TaxRate
    base: Decimal
    amount: Decimal


@dataclass(frozen=True, slots=True)
class DocumentTotals:
    net: Decimal
    tax_groups: tuple[TaxGroup, ...]
    tax_total: Decimal
    total: Decimal


def line_amounts(line: LineInput, places: int, *, tax_inclusive: bool = False) -> LineAmounts:
    """One line's net, its tax per tax, and its gross.

    Several taxes on one line are each charged on the same net amount — Saudi VAT is not
    compounded (`R2.AC4`).
    """
    gross_of_discount = line.quantity * line.unit_price
    after_discount = gross_of_discount * (HUNDRED - line.discount_percent) / HUNDRED

    combined_rate = sum((tax.rate for tax in line.taxes), ZERO)
    if tax_inclusive and combined_rate:
        # The price includes tax, so work back to the net amount (`R2.AC3`).
        net = quantize(after_discount * HUNDRED / (HUNDRED + combined_rate), places)
    else:
        net = quantize(after_discount, places)

    taxes = tuple(
        TaxAmount(tax=tax, base=net, amount=quantize(net * tax.rate / HUNDRED, places))
        for tax in line.taxes
    )
    tax_total = sum((entry.amount for entry in taxes), ZERO)
    return LineAmounts(net=net, taxes=taxes, tax_total=tax_total, gross=net + tax_total)


def document_totals(
    lines: Sequence[LineInput], places: int, *, tax_inclusive: bool = False
) -> DocumentTotals:
    """The document's net, its tax grouped by tax, and its total (`R2.AC5`, `R2.AC6`)."""
    computed = [line_amounts(line, places, tax_inclusive=tax_inclusive) for line in lines]

    net = sum((line.net for line in computed), ZERO)
    grouped: dict[UUID, TaxGroup] = {}
    for line in computed:
        for entry in line.taxes:
            existing = grouped.get(entry.tax.id)
            grouped[entry.tax.id] = TaxGroup(
                tax=entry.tax,
                base=(existing.base if existing else ZERO) + entry.base,
                amount=(existing.amount if existing else ZERO) + entry.amount,
            )

    groups = tuple(sorted(grouped.values(), key=lambda group: group.tax.name))
    tax_total = sum((group.amount for group in groups), ZERO)
    return DocumentTotals(net=net, tax_groups=groups, tax_total=tax_total, total=net + tax_total)
