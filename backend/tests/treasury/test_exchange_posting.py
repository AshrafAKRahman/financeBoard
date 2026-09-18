"""Exchange differences posted when a foreign-currency item is settled (R5.AC4, R5.AC5, R5.AC6)."""

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.coa.defaults import set_default
from app.ledger.api import ExchangeRate, JournalEntry, JournalEntryLine
from app.shared.errors import DomainError
from app.shared.ids import uuid7
from app.treasury.matching import match_amount, unmatch
from app.treasury.payments import create_payment, post_payment
from tests.factories import TreasuryBooks
from tests.treasury.conftest import draft, make_bill, make_invoice

pytestmark = pytest.mark.db

INVOICE_DATE = date(2026, 3, 1)
PAYMENT_DATE = date(2026, 3, 15)


@pytest.fixture
def rates(session: Session, books: TreasuryBooks) -> None:
    """USD was worth 3.80 when the invoice went out and 3.75 when it was paid."""
    for on, rate in ((INVOICE_DATE, "3.80"), (PAYMENT_DATE, "3.75")):
        session.add(
            ExchangeRate(
                id=uuid7(),
                company_id=books.company_id,
                currency_code="USD",
                rate_date=on,
                rate=Decimal(rate),
            )
        )
    session.commit()


def open_item(session: Session, entry_id: UUID) -> JournalEntryLine:
    return session.execute(
        select(JournalEntryLine).where(
            JournalEntryLine.entry_id == entry_id, JournalEntryLine.residual.is_not(None)
        )
    ).scalar_one()


def usd_receipt(
    session: Session, books: TreasuryBooks, partner_id: UUID, amount: str, **overrides
) -> JournalEntryLine:
    payment = create_payment(
        session,
        books.company_id,
        draft(
            books,
            partner_id,
            amount,
            currency_code="USD",
            date=PAYMENT_DATE,
            **overrides,
        ),
    )
    session.flush()
    post_payment(session, books.company_id, payment.id)
    return open_item(session, payment.journal_entry_id)


def fx_lines(session: Session, entry_id: UUID) -> dict[UUID, tuple[Decimal, Decimal]]:
    lines = session.execute(
        select(JournalEntryLine).where(JournalEntryLine.entry_id == entry_id)
    ).scalars()
    return {line.account_id: (line.debit, line.credit) for line in lines}


class TestALossOnACustomerInvoice:
    def test_the_difference_is_posted_to_the_loss_account(
        self, session: Session, books: TreasuryBooks, customer: UUID, rates: None
    ) -> None:
        """R5.AC3 — USD 100 invoiced at 3.80 (SAR 380) but received at 3.75 (SAR 375)."""
        invoice = make_invoice(session, books, customer, "100.00", currency="USD", on=INVOICE_DATE)
        invoice_line = open_item(session, invoice.journal_entry_id)
        payment_line = usd_receipt(session, books, customer, "100.00")

        match = match_amount(session, books.company_id, invoice_line.id, payment_line.id)

        assert match.fx_entry_id is not None
        amounts = fx_lines(session, match.fx_entry_id)
        assert amounts[books.accounts["5800"]] == (Decimal("5.00"), Decimal(0))
        assert amounts[books.accounts["1200"]] == (Decimal(0), Decimal("5.00"))

    def test_the_difference_is_linked_to_the_match(
        self, session: Session, books: TreasuryBooks, customer: UUID, rates: None
    ) -> None:
        """R5.AC4"""
        invoice = make_invoice(session, books, customer, "100.00", currency="USD", on=INVOICE_DATE)
        payment_line = usd_receipt(session, books, customer, "100.00")

        match = match_amount(
            session,
            books.company_id,
            open_item(session, invoice.journal_entry_id).id,
            payment_line.id,
        )

        entry = session.get(JournalEntry, match.fx_entry_id)
        assert entry.source_type == "reconciliation"
        assert entry.source_id == match.id

    def test_the_receivable_account_is_left_at_zero(
        self, session: Session, books: TreasuryBooks, customer: UUID, rates: None
    ) -> None:
        """The point of the difference: no stray 5 SAR on the customer's account."""
        invoice = make_invoice(session, books, customer, "100.00", currency="USD", on=INVOICE_DATE)
        payment_line = usd_receipt(session, books, customer, "100.00")
        match_amount(
            session,
            books.company_id,
            open_item(session, invoice.journal_entry_id).id,
            payment_line.id,
        )
        session.flush()

        balance = session.execute(
            select(JournalEntryLine.debit.op("-")(JournalEntryLine.credit).label("movement")).where(
                JournalEntryLine.company_id == books.company_id,
                JournalEntryLine.account_id == books.accounts["1200"],
            )
        ).scalars()
        assert sum(balance) == Decimal(0)

    def test_the_difference_line_is_not_a_new_open_item(
        self, session: Session, books: TreasuryBooks, customer: UUID, rates: None
    ) -> None:
        """Otherwise every settled foreign invoice would leave dust in aged receivables."""
        invoice = make_invoice(session, books, customer, "100.00", currency="USD", on=INVOICE_DATE)
        payment_line = usd_receipt(session, books, customer, "100.00")
        match = match_amount(
            session,
            books.company_id,
            open_item(session, invoice.journal_entry_id).id,
            payment_line.id,
        )

        difference = session.execute(
            select(JournalEntryLine).where(
                JournalEntryLine.entry_id == match.fx_entry_id,
                JournalEntryLine.account_id == books.accounts["1200"],
            )
        ).scalar_one()
        assert difference.residual is None


class TestAGainOnAVendorBill:
    def test_paying_a_bill_at_a_better_rate_is_a_gain(
        self, session: Session, books: TreasuryBooks, vendor: UUID, rates: None
    ) -> None:
        """R5.AC2 — owed SAR 380, settled for SAR 375."""
        bill = make_bill(session, books, vendor, "100.00", currency="USD", on=INVOICE_DATE)
        bill_line = open_item(session, bill.journal_entry_id)
        payment_line = usd_receipt(session, books, vendor, "100.00", direction="outbound")

        match = match_amount(session, books.company_id, payment_line.id, bill_line.id)

        assert match.fx_entry_id is not None
        amounts = fx_lines(session, match.fx_entry_id)
        assert amounts[books.accounts["4900"]] == (Decimal(0), Decimal("5.00"))
        assert amounts[books.accounts["2100"]] == (Decimal("5.00"), Decimal(0))


class TestWhenNoDifferenceArises:
    def test_a_company_currency_match_posts_nothing(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R5.AC7"""
        invoice = make_invoice(session, books, customer, "1000.00")
        payment = create_payment(session, books.company_id, draft(books, customer, "1000.00"))
        session.flush()
        post_payment(session, books.company_id, payment.id)

        match = match_amount(
            session,
            books.company_id,
            open_item(session, invoice.journal_entry_id).id,
            open_item(session, payment.journal_entry_id).id,
        )
        assert match.fx_entry_id is None

    def test_an_unchanged_rate_posts_nothing(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R5.AC1 — a foreign currency is not the same thing as a difference."""
        session.add(
            ExchangeRate(
                id=uuid7(),
                company_id=books.company_id,
                currency_code="USD",
                rate_date=INVOICE_DATE,
                rate=Decimal("3.75"),
            )
        )
        session.commit()
        invoice = make_invoice(session, books, customer, "100.00", currency="USD", on=INVOICE_DATE)
        payment_line = usd_receipt(session, books, customer, "100.00")

        match = match_amount(
            session,
            books.company_id,
            open_item(session, invoice.journal_entry_id).id,
            payment_line.id,
        )
        assert match.fx_entry_id is None


class TestWhatIsRefused:
    def test_no_loss_account_stops_the_match(
        self, session: Session, books: TreasuryBooks, customer: UUID, rates: None
    ) -> None:
        """R5.AC5 — better to refuse than to hide a difference somewhere convenient."""
        invoice = make_invoice(session, books, customer, "100.00", currency="USD", on=INVOICE_DATE)
        payment_line = usd_receipt(session, books, customer, "100.00")
        set_default(session, books.company_id, "fx_loss", None)
        session.flush()

        with pytest.raises(DomainError) as caught:
            match_amount(
                session,
                books.company_id,
                open_item(session, invoice.journal_entry_id).id,
                payment_line.id,
            )
        assert caught.value.code == "payments.fx_account_missing"


class TestUndoingTheDifference:
    def test_unmatching_reverses_the_difference_entry(
        self, session: Session, books: TreasuryBooks, customer: UUID, rates: None
    ) -> None:
        """R5.AC6 — otherwise a reopened invoice keeps a gain it never made."""
        invoice = make_invoice(session, books, customer, "100.00", currency="USD", on=INVOICE_DATE)
        payment_line = usd_receipt(session, books, customer, "100.00")
        match = match_amount(
            session,
            books.company_id,
            open_item(session, invoice.journal_entry_id).id,
            payment_line.id,
        )
        fx_entry_id = match.fx_entry_id

        unmatch(session, books.company_id, [match.id])

        reversal = session.execute(
            select(JournalEntry).where(JournalEntry.reversed_entry_id == fx_entry_id)
        ).scalar_one()
        assert reversal.state == "posted"

    def test_the_lines_reopen_in_both_currencies(
        self, session: Session, books: TreasuryBooks, customer: UUID, rates: None
    ) -> None:
        invoice = make_invoice(session, books, customer, "100.00", currency="USD", on=INVOICE_DATE)
        invoice_line = open_item(session, invoice.journal_entry_id)
        payment_line = usd_receipt(session, books, customer, "100.00")
        match = match_amount(session, books.company_id, invoice_line.id, payment_line.id)

        unmatch(session, books.company_id, [match.id])

        assert invoice_line.residual == Decimal("380.00")
        assert invoice_line.residual_currency == Decimal("100.00")
        assert payment_line.residual == Decimal("375.00")
        assert payment_line.residual_currency == Decimal("100.00")
