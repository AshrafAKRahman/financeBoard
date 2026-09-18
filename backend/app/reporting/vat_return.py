"""The ZATCA VAT return for a filing period (R6).

Built from posted entries alone. Each tagged line carries the box it belongs to
(`tax_grid_tag`) and what the tax was charged on (`tax_base`, added by migration 0006), so
the return needs no documents beside it — which is what makes it reconcilable to the ledger
rather than merely consistent with it.

A tagged line whose tag nobody has mapped to a box is reported as untagged. A figure missing
from a filed return is worse than one that is visibly homeless.
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.reporting.periods import Period
from app.reporting.statements import ReportMeta, company_of, meta
from app.reporting.vat_boxes import BOXES, PURCHASES, SALES, VatBox, box_for
from app.shared.money import ZERO


@dataclass(frozen=True, slots=True)
class VatBoxTotal:
    box: VatBox
    net: Decimal
    """What the tax was charged on."""

    tax: Decimal


@dataclass(frozen=True, slots=True)
class UntaggedTotal:
    grid_tag: str | None
    net: Decimal
    tax: Decimal


@dataclass(frozen=True, slots=True)
class VatReturn:
    meta: ReportMeta
    sales: tuple[VatBoxTotal, ...]
    purchases: tuple[VatBoxTotal, ...]
    untagged: tuple[UntaggedTotal, ...]
    total_sales_net: Decimal
    output_tax: Decimal
    total_purchases_net: Decimal
    input_tax: Decimal

    @property
    def net_tax_due(self) -> Decimal:
        """R6.AC4 — what is owed to ZATCA, or reclaimable when negative."""
        return self.output_tax - self.input_tax


# A tagged line's own amount is the tax; tax_base is what it was charged on. Both are summed
# once per side, and the box picks the side it belongs to — so a credit note reduces the box
# its invoice increased rather than landing in the other half of the return.
#
# tax_base is stored unsigned, so it takes its sign from the line: a reversal is a debit where
# the original was a credit, and the two cancel. Summing the raw column would report a
# cancelled sale twice over.
TAGGED = """
SELECT l.tax_grid_tag,
       COALESCE(SUM(CASE WHEN l.credit > l.debit THEN l.tax_base ELSE -l.tax_base END), 0)
           AS credit_net,
       COALESCE(SUM(CASE WHEN l.debit > l.credit THEN l.tax_base ELSE -l.tax_base END), 0)
           AS debit_net,
       COALESCE(SUM(l.credit - l.debit), 0)  AS credit_tax,
       COALESCE(SUM(l.debit - l.credit), 0)  AS debit_tax
FROM journal_entry_line l
JOIN journal_entry e ON e.id = l.entry_id
WHERE l.company_id = :company
  AND e.state = 'posted'
  AND e.date BETWEEN :start AND :end
  AND l.tax_grid_tag IS NOT NULL
GROUP BY l.tax_grid_tag
ORDER BY l.tax_grid_tag
"""


def vat_return(session: Session, company_id: UUID, period: Period) -> VatReturn:
    """R6 — one row per box, with the net and the tax, and what could not be placed."""
    company = company_of(session, company_id)
    rows = session.execute(
        text(TAGGED),
        {"company": company_id, "start": period.start, "end": period.end},
    ).all()

    sales: list[VatBoxTotal] = []
    purchases: list[VatBoxTotal] = []
    untagged: list[UntaggedTotal] = []

    for row in rows:
        box = box_for(row.tax_grid_tag)
        if box is None:
            untagged.append(
                UntaggedTotal(grid_tag=row.tax_grid_tag, net=row.credit_net, tax=row.credit_tax)
            )
            continue

        # Output tax is a credit; input tax is a debit. Taking the sign from the box means a
        # credit note reduces the box it belongs to rather than landing in the other one.
        tax = row.credit_tax if box.side == SALES else row.debit_tax
        net = row.credit_net if box.side == SALES else row.debit_net
        # A zero-rated line carries its basis on the revenue line, whose own amount is the
        # net, not a tax. Reporting that as tax would invent a liability.
        if not box.taxable:
            tax = ZERO

        total = VatBoxTotal(box=box, net=net, tax=tax)
        (sales if box.side == SALES else purchases).append(total)

    sales.sort(key=lambda entry: entry.box.number)
    purchases.sort(key=lambda entry: entry.box.number)

    return VatReturn(
        meta=meta(company, period, "vat-return"),
        sales=tuple(sales),
        purchases=tuple(purchases),
        untagged=tuple(untagged),
        total_sales_net=sum((entry.net for entry in sales), ZERO),
        output_tax=sum((entry.tax for entry in sales), ZERO),
        total_purchases_net=sum((entry.net for entry in purchases), ZERO),
        input_tax=sum((entry.tax for entry in purchases), ZERO),
    )


def known_tags() -> frozenset[str]:
    """Every tag this return knows how to place; used by the tests that guard the map."""
    return frozenset(BOXES)


__all__ = [
    "PURCHASES",
    "SALES",
    "UntaggedTotal",
    "VatBoxTotal",
    "VatReturn",
    "known_tags",
    "vat_return",
]
