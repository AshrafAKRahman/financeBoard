"""The ZATCA VAT return (R6), built from posted entries alone."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.billing.models import Tax
from app.reporting.periods import Period
from app.reporting.vat_return import vat_return
from app.shared.ids import uuid7
from tests.factories import TreasuryBooks
from tests.reporting.conftest import JANUARY, bill, invoice

pytestmark = pytest.mark.db

Q1 = Period(date(2026, 1, 1), date(2026, 3, 31), "Q1 2026")


def box(report, number: int):
    for entry in report.sales + report.purchases:
        if entry.box.number == number:
            return entry
    return None


def zero_rated(session: Session, books: TreasuryBooks, tag: str = "sales_zero_rated") -> Tax:
    tax = Tax(
        id=uuid7(),
        company_id=books.company_id,
        name=f"Zero {tag}",
        rate=Decimal("0"),
        type="sale",
        vat_category="zero_rated",
        exemption_reason="Export of goods outside the GCC",
        account_id=books.accounts["2200"],
        grid_tag=tag,
    )
    session.add(tax)
    session.flush()
    return tax


class TestStandardRates:
    def test_a_sale_reports_its_net_and_its_tax(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        """R6.AC1 — box 1: 10,000 of standard rated sales, 1,500 of tax."""
        invoice(session, books, customer, "10000.00", on=JANUARY)

        standard = box(vat_return(session, books.company_id, Q1), 1)

        assert standard.net == Decimal("10000.00")
        assert standard.tax == Decimal("1500.00")

    def test_a_purchase_reports_input_tax(
        self, session: Session, books: TreasuryBooks, vendor
    ) -> None:
        """R6.AC3 — box 7, on the other side of the return."""
        bill(session, books, vendor, "4000.00", on=JANUARY)

        purchases = box(vat_return(session, books.company_id, Q1), 7)

        assert purchases.net == Decimal("4000.00")
        assert purchases.tax == Decimal("600.00")

    def test_output_and_input_are_kept_apart(
        self, session: Session, books: TreasuryBooks, customer, vendor
    ) -> None:
        """R6.AC3"""
        invoice(session, books, customer, "10000.00", on=JANUARY)
        bill(session, books, vendor, "4000.00", on=JANUARY)

        report = vat_return(session, books.company_id, Q1)

        assert report.output_tax == Decimal("1500.00")
        assert report.input_tax == Decimal("600.00")

    def test_the_net_tax_due_is_output_less_input(
        self, session: Session, books: TreasuryBooks, customer, vendor
    ) -> None:
        """R6.AC4 — what actually gets paid to ZATCA."""
        invoice(session, books, customer, "10000.00", on=JANUARY)
        bill(session, books, vendor, "4000.00", on=JANUARY)

        assert vat_return(session, books.company_id, Q1).net_tax_due == Decimal("900.00")

    def test_a_reclaim_is_a_negative_net(
        self, session: Session, books: TreasuryBooks, customer, vendor
    ) -> None:
        invoice(session, books, customer, "1000.00", on=JANUARY)
        bill(session, books, vendor, "4000.00", on=JANUARY)

        assert vat_return(session, books.company_id, Q1).net_tax_due == Decimal("-450.00")


class TestZeroRatedAndExempt:
    def test_an_export_is_reported_with_no_tax(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        """R6.AC5 — the supply belongs on the return even though the tax is nothing."""
        tax = zero_rated(session, books)
        from app.billing.documents import DocumentData, LineData, create_document, post_document

        document = create_document(
            session,
            books.company_id,
            DocumentData(
                type="out_invoice",
                partner_id=customer,
                journal_id=books.journals["INV"],
                date=JANUARY,
                lines=[
                    LineData(
                        description="Export",
                        quantity=Decimal(1),
                        unit_price=Decimal("5000.00"),
                        account_id=books.accounts["4100"],
                        tax_ids=[tax.id],
                    )
                ],
            ),
        )
        session.flush()
        post_document(session, books.company_id, document.id)
        session.flush()

        zero = box(vat_return(session, books.company_id, Q1), 3)

        assert zero is not None
        assert zero.net == Decimal("5000.00")
        assert zero.tax == Decimal(0)


class TestWhatItCounts:
    def test_another_period_is_not_in_this_return(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        invoice(session, books, customer, "10000.00", on=date(2026, 5, 10))

        assert vat_return(session, books.company_id, Q1).output_tax == Decimal(0)

    def test_a_cancelled_invoice_nets_itself_out(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        """A reversal carries the same tag and basis, so the supply leaves the return."""
        from app.billing.documents import cancel_document

        document = invoice(session, books, customer, "10000.00", on=JANUARY)
        cancel_document(session, books.company_id, document.id, reason="wrong customer")
        session.flush()

        report = vat_return(session, books.company_id, Q1)

        assert report.output_tax == Decimal(0)
        assert box(report, 1).net == Decimal(0)

    def test_a_tag_nobody_mapped_is_reported_as_untagged(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        """R6.AC7 — visible, rather than dropped from a legal return.

        A posted line cannot be edited, so the tag has to arrive the way a real one would:
        on a tax somebody created before the box map knew about it.
        """
        from app.billing.documents import DocumentData, LineData, create_document, post_document

        unmapped = Tax(
            id=uuid7(),
            company_id=books.company_id,
            name="Some new levy",
            rate=Decimal("5"),
            type="sale",
            account_id=books.accounts["2200"],
            grid_tag="a_tag_nobody_mapped",
        )
        session.add(unmapped)
        session.flush()

        document = create_document(
            session,
            books.company_id,
            DocumentData(
                type="out_invoice",
                partner_id=customer,
                journal_id=books.journals["INV"],
                date=JANUARY,
                lines=[
                    LineData(
                        description="Levied",
                        quantity=Decimal(1),
                        unit_price=Decimal("1000.00"),
                        account_id=books.accounts["4100"],
                        tax_ids=[unmapped.id],
                    )
                ],
            ),
        )
        session.flush()
        post_document(session, books.company_id, document.id)
        session.flush()

        report = vat_return(session, books.company_id, Q1)

        assert [entry.grid_tag for entry in report.untagged] == ["a_tag_nobody_mapped"]
        assert report.untagged[0].tax == Decimal("50.00")
        assert report.output_tax == Decimal(0)


def test_the_return_agrees_with_the_vat_accounts(
    session: Session, books: TreasuryBooks, customer, vendor
) -> None:
    """R6.AC6 — the reconciliation that makes the return trustworthy."""
    invoice(session, books, customer, "10000.00", on=JANUARY)
    bill(session, books, vendor, "4000.00", on=JANUARY)
    session.flush()

    report = vat_return(session, books.company_id, Q1)

    output = session.execute(
        text(
            "SELECT COALESCE(SUM(l.credit - l.debit), 0) FROM journal_entry_line l "
            "JOIN journal_entry e ON e.id = l.entry_id "
            "WHERE l.company_id = :c AND e.state = 'posted' AND l.account_id = :a"
        ),
        {"c": books.company_id, "a": books.accounts["2200"]},
    ).scalar_one()
    input_tax = session.execute(
        text(
            "SELECT COALESCE(SUM(l.debit - l.credit), 0) FROM journal_entry_line l "
            "JOIN journal_entry e ON e.id = l.entry_id "
            "WHERE l.company_id = :c AND e.state = 'posted' AND l.account_id = :a"
        ),
        {"c": books.company_id, "a": books.accounts["1300"]},
    ).scalar_one()

    assert report.output_tax == output
    assert report.input_tax == input_tax
