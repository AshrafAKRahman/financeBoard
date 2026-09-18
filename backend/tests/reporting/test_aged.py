"""Aged receivables and payables (R5) — including the report as it stood in the past."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.reporting.aged import aged_payables, aged_receivables, bucket_for
from tests.factories import TreasuryBooks
from tests.reporting.conftest import JANUARY, bill, invoice, receipt, settle

pytestmark = pytest.mark.db

# Everything is read from a fixed "today" so the buckets do not move with the calendar.
TODAY = date(2026, 4, 30)


class TestBuckets:
    def test_nothing_overdue_is_current(self) -> None:
        assert bucket_for(0) == "current"
        assert bucket_for(-5) == "current"

    def test_the_bands(self) -> None:
        """R5.AC1"""
        assert bucket_for(1) == "1-30"
        assert bucket_for(30) == "1-30"
        assert bucket_for(31) == "31-60"
        assert bucket_for(61) == "61-90"
        assert bucket_for(91) == "90+"
        assert bucket_for(400) == "90+"


class TestWhatIsOwed:
    def test_an_unpaid_invoice_appears_against_its_customer(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        invoice(session, books, customer, "10000.00", on=JANUARY, due=date(2026, 2, 14))

        report = aged_receivables(session, books.company_id, TODAY, today=TODAY)

        assert report.total == Decimal("11500.00")
        assert report.partners[0].partner_name == "Al Noor Est"

    def test_it_ages_by_its_due_date(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        """R5.AC2 — due 14 February, read on 30 April: 75 days late."""
        invoice(session, books, customer, "10000.00", on=JANUARY, due=date(2026, 2, 14))

        report = aged_receivables(session, books.company_id, TODAY, today=TODAY)
        assert report.buckets["61-90"] == Decimal("11500.00")

    def test_without_a_due_date_it_ages_from_the_entry(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        """R5.AC2 — 15 January to 30 April is more than 90 days."""
        invoice(session, books, customer, "10000.00", on=JANUARY)

        report = aged_receivables(session, books.company_id, TODAY, today=TODAY)
        assert report.buckets["90+"] == Decimal("11500.00")

    def test_a_settled_invoice_is_gone(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        """R5.AC3 — the ledger already holds what is open."""
        sale = invoice(session, books, customer, "10000.00", on=JANUARY)
        payment = receipt(session, books, customer, "11500.00", on=date(2026, 2, 20))
        settle(session, books, sale, payment)
        session.flush()

        report = aged_receivables(session, books.company_id, TODAY, today=TODAY)
        assert report.total == Decimal(0)

    def test_a_part_paid_invoice_shows_only_the_rest(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        sale = invoice(session, books, customer, "10000.00", on=JANUARY)
        payment = receipt(session, books, customer, "4000.00", on=date(2026, 2, 20))
        settle(session, books, sale, payment)
        session.flush()

        report = aged_receivables(session, books.company_id, TODAY, today=TODAY)
        assert report.total == Decimal("7500.00")

    def test_an_unmatched_payment_is_a_negative_open_item(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        """R5.AC7 — a customer who paid in advance is owed money, not owing it."""
        receipt(session, books, customer, "2000.00", on=date(2026, 2, 20))
        session.flush()

        report = aged_receivables(session, books.company_id, TODAY, today=TODAY)
        assert report.total == Decimal("-2000.00")

    def test_one_partner_can_be_singled_out(
        self, session: Session, books: TreasuryBooks, customer, vendor
    ) -> None:
        """R5.AC8"""
        from tests.factories import make_partner

        other = make_partner(session, books.company_id, name="Riyadh Retail", type="customer")
        invoice(session, books, customer, "1000.00", on=JANUARY)
        invoice(session, books, other.id, "2000.00", on=JANUARY)

        report = aged_receivables(
            session, books.company_id, TODAY, partner_id=other.id, today=TODAY
        )

        assert report.total == Decimal("2300.00")
        assert len(report.partners) == 1
        assert report.partners[0].items


class TestPayables:
    def test_a_bill_appears_against_its_vendor(
        self, session: Session, books: TreasuryBooks, vendor
    ) -> None:
        """R5.AC6 — the same report read from the other side."""
        bill(session, books, vendor, "4000.00", on=JANUARY)

        report = aged_payables(session, books.company_id, TODAY, today=TODAY)

        assert report.total == Decimal("4600.00")
        assert report.partners[0].partner_name == "Jeddah Properties"

    def test_receivables_and_payables_do_not_mix(
        self, session: Session, books: TreasuryBooks, customer, vendor
    ) -> None:
        invoice(session, books, customer, "10000.00", on=JANUARY)
        bill(session, books, vendor, "4000.00", on=JANUARY)

        assert aged_receivables(session, books.company_id, TODAY, today=TODAY).total == Decimal(
            "11500.00"
        )
        assert aged_payables(session, books.company_id, TODAY, today=TODAY).total == Decimal(
            "4600.00"
        )


class TestAsOfAPastDate:
    def test_a_later_payment_does_not_settle_an_earlier_report(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        """R5.AC4 — the whole point. Paid in March; the February report must not know."""
        sale = invoice(session, books, customer, "10000.00", on=JANUARY)
        payment = receipt(session, books, customer, "11500.00", on=date(2026, 3, 20))
        settle(session, books, sale, payment)
        session.commit()

        february = aged_receivables(session, books.company_id, date(2026, 2, 28), today=TODAY)
        march = aged_receivables(session, books.company_id, date(2026, 3, 31), today=TODAY)

        assert february.total == Decimal("11500.00")
        assert march.total == Decimal(0)

    def test_an_invoice_raised_later_is_not_in_an_earlier_report(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        invoice(session, books, customer, "10000.00", on=date(2026, 3, 10))
        session.commit()

        february = aged_receivables(session, books.company_id, date(2026, 2, 28), today=TODAY)
        assert february.total == Decimal(0)

    def test_both_paths_agree_when_the_date_is_today(
        self, session: Session, books: TreasuryBooks, customer
    ) -> None:
        """The stored open amount and the rebuilt one are the same number."""
        sale = invoice(session, books, customer, "10000.00", on=JANUARY)
        payment = receipt(session, books, customer, "4000.00", on=date(2026, 2, 20))
        settle(session, books, sale, payment)
        session.commit()

        stored = aged_receivables(session, books.company_id, TODAY, today=TODAY)
        rebuilt = aged_receivables(session, books.company_id, TODAY, today=date(2026, 5, 1))

        assert stored.total == rebuilt.total
        assert stored.buckets == rebuilt.buckets
