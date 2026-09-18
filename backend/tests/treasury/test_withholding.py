"""Withholding tax at payment (R9).

Saudi withholding tax is deducted when a non-resident is paid: the vendor's bill is settled
in full, but part of the money goes to ZATCA instead of to the vendor.
"""

from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.models import Tax
from app.ledger.api import JournalEntryLine
from app.shared.errors import DomainError
from app.treasury.payments import create_payment, post_payment
from tests.factories import TreasuryBooks
from tests.treasury.conftest import draft

pytestmark = pytest.mark.db


def amounts_by_account(session: Session, entry_id: UUID) -> dict[UUID, tuple[Decimal, Decimal]]:
    lines = session.execute(
        select(JournalEntryLine).where(JournalEntryLine.entry_id == entry_id)
    ).scalars()
    return {line.account_id: (line.debit, line.credit) for line in lines}


def withholding_payment(books: TreasuryBooks, vendor: UUID, amount: str = "1000.00"):
    return draft(
        books,
        vendor,
        amount,
        direction="outbound",
        withholding_tax_id=books.taxes["withholding"],
    )


class TestWhatIsWithheld:
    def test_the_withheld_amount_follows_from_the_tax(
        self, session: Session, books: TreasuryBooks, vendor: UUID
    ) -> None:
        """R9.AC1 — 5% of 1,000, worked out rather than typed in."""
        payment = create_payment(session, books.company_id, withholding_payment(books, vendor))

        assert payment.withheld_amount == Decimal("50.00")
        assert payment.net_amount == Decimal("950.00")

    def test_no_tax_means_nothing_withheld(
        self, session: Session, books: TreasuryBooks, vendor: UUID
    ) -> None:
        payment = create_payment(
            session, books.company_id, draft(books, vendor, direction="outbound")
        )
        assert payment.withheld_amount == Decimal(0)
        assert payment.net_amount == payment.amount

    def test_the_withheld_amount_is_rounded_to_the_currency(
        self, session: Session, books: TreasuryBooks, vendor: UUID
    ) -> None:
        """5% of 333.33 is 16.6665, which is 16.67 in SAR."""
        payment = create_payment(
            session, books.company_id, withholding_payment(books, vendor, "333.33")
        )
        assert payment.withheld_amount == Decimal("16.67")


class TestThePostedEntry:
    def test_the_vendor_is_settled_in_full(
        self, session: Session, books: TreasuryBooks, vendor: UUID
    ) -> None:
        """R9.AC3 — the bill was for 1,000, so 1,000 comes off the payable."""
        payment = create_payment(session, books.company_id, withholding_payment(books, vendor))
        session.flush()
        post_payment(session, books.company_id, payment.id)

        amounts = amounts_by_account(session, payment.journal_entry_id)
        assert amounts[books.accounts["2100"]] == (Decimal("1000.00"), Decimal(0))

    def test_only_the_net_amount_leaves_the_bank(
        self, session: Session, books: TreasuryBooks, vendor: UUID
    ) -> None:
        """R9.AC2"""
        payment = create_payment(session, books.company_id, withholding_payment(books, vendor))
        session.flush()
        post_payment(session, books.company_id, payment.id)

        amounts = amounts_by_account(session, payment.journal_entry_id)
        assert amounts[books.accounts["2120"]] == (Decimal(0), Decimal("950.00"))

    def test_the_withheld_tax_is_owed_to_zatca(
        self, session: Session, books: TreasuryBooks, vendor: UUID
    ) -> None:
        """R9.AC2 — a liability, not a saving."""
        payment = create_payment(session, books.company_id, withholding_payment(books, vendor))
        session.flush()
        post_payment(session, books.company_id, payment.id)

        amounts = amounts_by_account(session, payment.journal_entry_id)
        assert amounts[books.accounts["2300"]] == (Decimal(0), Decimal("50.00"))

    def test_the_withholding_line_carries_its_tax_and_grid(
        self, session: Session, books: TreasuryBooks, vendor: UUID
    ) -> None:
        """What the withholding return will be built from."""
        payment = create_payment(session, books.company_id, withholding_payment(books, vendor))
        session.flush()
        post_payment(session, books.company_id, payment.id)

        line = session.execute(
            select(JournalEntryLine).where(
                JournalEntryLine.entry_id == payment.journal_entry_id,
                JournalEntryLine.account_id == books.accounts["2300"],
            )
        ).scalar_one()
        assert line.tax_id == books.taxes["withholding"]
        assert line.tax_grid_tag == "withholding"

    def test_the_entry_still_balances(
        self, session: Session, books: TreasuryBooks, vendor: UUID
    ) -> None:
        payment = create_payment(session, books.company_id, withholding_payment(books, vendor))
        session.flush()
        post_payment(session, books.company_id, payment.id)

        amounts = amounts_by_account(session, payment.journal_entry_id)
        debits = sum(debit for debit, _ in amounts.values())
        credits = sum(credit for _, credit in amounts.values())
        assert debits == credits == Decimal("1000.00")

    def test_an_inbound_payment_can_have_tax_withheld_from_it(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """A customer abroad may withhold from what they pay us; the sides simply flip."""
        payment = create_payment(
            session,
            books.company_id,
            draft(books, customer, withholding_tax_id=books.taxes["withholding"]),
        )
        session.flush()
        post_payment(session, books.company_id, payment.id)

        amounts = amounts_by_account(session, payment.journal_entry_id)
        assert amounts[books.accounts["1200"]] == (Decimal(0), Decimal("1000.00"))
        assert amounts[books.accounts["1120"]] == (Decimal("950.00"), Decimal(0))
        assert amounts[books.accounts["2300"]] == (Decimal("50.00"), Decimal(0))


class TestWhatIsRefused:
    def test_a_vat_rate_is_not_a_withholding_tax(
        self, session: Session, books: TreasuryBooks, vendor: UUID
    ) -> None:
        """R9.AC4"""
        with pytest.raises(DomainError) as caught:
            create_payment(
                session,
                books.company_id,
                draft(
                    books,
                    vendor,
                    direction="outbound",
                    withholding_tax_id=books.taxes["purchase"],
                ),
            )
        assert caught.value.code == "payments.wrong_tax_type"

    def test_withholding_cannot_take_the_whole_payment(
        self, session: Session, books: TreasuryBooks, vendor: UUID
    ) -> None:
        """Then nothing would leave the bank, and the entry would be a fiction."""
        everything = session.get(Tax, books.taxes["withholding"])
        everything.rate = Decimal("100")
        session.flush()

        with pytest.raises(DomainError) as caught:
            create_payment(session, books.company_id, withholding_payment(books, vendor))
        assert caught.value.code == "payments.invalid_amount"

    def test_a_tax_with_no_account_stops_posting(
        self, session: Session, books: TreasuryBooks, vendor: UUID
    ) -> None:
        payment = create_payment(session, books.company_id, withholding_payment(books, vendor))
        session.flush()
        session.get(Tax, books.taxes["withholding"]).account_id = None
        session.flush()

        with pytest.raises(DomainError) as caught:
            post_payment(session, books.company_id, payment.id)
        assert caught.value.code == "tax.account_not_found"
