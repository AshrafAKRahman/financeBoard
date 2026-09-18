"""What a tax was charged on reaches the ledger (R6.AC2, R6.AC5, R6.AC7).

The VAT return is built from posted entries alone, so the basis has to be there — including
for a zero-rated supply, whose tax line is worth nothing and never survives posting.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.documents import DocumentData, LineData, create_document, post_document
from app.billing.models import Tax
from app.ledger.api import JournalEntryLine
from app.shared.errors import DomainError
from app.shared.ids import uuid7
from tests.factories import TreasuryBooks, make_partner, make_treasury_company

pytestmark = pytest.mark.db

INVOICE_DATE = date(2026, 3, 1)


@pytest.fixture
def books(session: Session) -> TreasuryBooks:
    return make_treasury_company(session)


@pytest.fixture
def customer(session: Session, books: TreasuryBooks) -> UUID:
    return make_partner(session, books.company_id, name="Al Noor Est", type="customer").id


def zero_rated_tax(session: Session, books: TreasuryBooks) -> Tax:
    tax = Tax(
        id=uuid7(),
        company_id=books.company_id,
        name="Zero-rated exports",
        rate=Decimal("0"),
        type="sale",
        vat_category="zero_rated",
        exemption_reason="Export of goods outside the GCC",
        account_id=books.accounts["2200"],
        grid_tag="sales_zero_rated",
    )
    session.add(tax)
    session.flush()
    return tax


def invoice(
    session: Session, books: TreasuryBooks, customer: UUID, tax_ids: list[UUID], amount="5000.00"
):
    document = create_document(
        session,
        books.company_id,
        DocumentData(
            type="out_invoice",
            partner_id=customer,
            journal_id=books.journals["INV"],
            date=INVOICE_DATE,
            lines=[
                LineData(
                    description="Consultancy",
                    quantity=Decimal(1),
                    unit_price=Decimal(amount),
                    account_id=books.accounts["4100"],
                    tax_ids=tax_ids,
                )
            ],
        ),
    )
    session.flush()
    post_document(session, books.company_id, document.id)
    session.flush()
    return document


def tagged_lines(session: Session, entry_id: UUID) -> list[JournalEntryLine]:
    return list(
        session.execute(
            select(JournalEntryLine).where(
                JournalEntryLine.entry_id == entry_id,
                JournalEntryLine.tax_grid_tag.is_not(None),
            )
        ).scalars()
    )


class TestAStandardRatedSale:
    def test_the_tax_line_records_what_it_was_charged_on(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R6.AC2 — 15% of 5,000 is 750, charged on 5,000."""
        document = invoice(session, books, customer, [books.taxes["sale"]])

        lines = tagged_lines(session, document.journal_entry_id)

        assert len(lines) == 1
        assert lines[0].tax_grid_tag == "sales_standard"
        assert lines[0].tax_base == Decimal("5000.00")
        assert lines[0].credit == Decimal("750.00")

    def test_the_revenue_line_carries_no_tag(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """Only one line per tax may carry a box, or the return would double-count."""
        document = invoice(session, books, customer, [books.taxes["sale"]])

        revenue = session.execute(
            select(JournalEntryLine).where(
                JournalEntryLine.entry_id == document.journal_entry_id,
                JournalEntryLine.account_id == books.accounts["4100"],
            )
        ).scalar_one()
        assert revenue.tax_grid_tag is None
        assert revenue.tax_base is None


class TestAZeroRatedSale:
    def test_the_supply_is_still_reportable(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R6.AC5 — the tax is nothing, but the supply belongs on the return."""
        zero = zero_rated_tax(session, books)
        document = invoice(session, books, customer, [zero.id])

        lines = tagged_lines(session, document.journal_entry_id)

        assert len(lines) == 1
        assert lines[0].tax_grid_tag == "sales_zero_rated"
        assert lines[0].tax_base == Decimal("5000.00")

    def test_the_tag_sits_on_the_revenue_line(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """There is no tax line to carry it: a 0.00 line never survives posting."""
        zero = zero_rated_tax(session, books)
        document = invoice(session, books, customer, [zero.id])

        lines = tagged_lines(session, document.journal_entry_id)
        assert lines[0].account_id == books.accounts["4100"]

    def test_the_entry_still_has_only_two_lines(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """Recording the basis must not add an empty line to the books."""
        zero = zero_rated_tax(session, books)
        document = invoice(session, books, customer, [zero.id])

        count = len(
            session.execute(
                select(JournalEntryLine).where(
                    JournalEntryLine.entry_id == document.journal_entry_id
                )
            )
            .scalars()
            .all()
        )
        assert count == 2


class TestWhatIsRefused:
    def test_two_taxes_worth_nothing_on_one_line_are_refused(
        self, session: Session, books: TreasuryBooks, customer: UUID
    ) -> None:
        """R6.AC7 — one line cannot be reported under two boxes."""
        first = zero_rated_tax(session, books)
        second = Tax(
            id=uuid7(),
            company_id=books.company_id,
            name="Exempt supply",
            rate=Decimal("0"),
            type="sale",
            vat_category="exempt",
            exemption_reason="Exempt financial supply",
            account_id=books.accounts["2200"],
            grid_tag="sales_exempt",
        )
        session.add(second)
        session.flush()

        with pytest.raises(DomainError) as caught:
            invoice(session, books, customer, [first.id, second.id])
        assert caught.value.code == "tax.ambiguous_zero_rated"


def test_a_reversal_carries_the_basis_back(
    session: Session, books: TreasuryBooks, customer: UUID
) -> None:
    """A cancelled sale must leave the return net of itself, not reporting the supply twice."""
    from app.billing.documents import cancel_document

    document = invoice(session, books, customer, [books.taxes["sale"]])
    cancel_document(session, books.company_id, document.id, reason="wrong customer")
    session.flush()

    from app.ledger.api import JournalEntry

    reversal = session.execute(
        select(JournalEntry).where(JournalEntry.reversed_entry_id == document.journal_entry_id)
    ).scalar_one()
    lines = tagged_lines(session, reversal.id)

    assert len(lines) == 1
    assert lines[0].tax_base == Decimal("5000.00")
    assert lines[0].debit == Decimal("750.00")
