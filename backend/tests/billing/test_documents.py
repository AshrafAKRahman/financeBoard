"""Drafting invoices and bills (R3, R4)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.billing.documents import (
    DocumentData,
    LineData,
    create_document,
    delete_document,
    get_document,
    list_documents,
    totals_of,
    update_document,
)
from app.shared.errors import DomainError
from app.shared.ids import uuid7
from tests.billing.conftest import account_id, journal_id
from tests.billing.helpers import TODAY, make_bill, make_invoice

pytestmark = pytest.mark.db


def test_an_invoice_starts_as_a_draft(session: Session, books, customer, vat15) -> None:
    """R3.AC1"""
    invoice = make_invoice(session, books, customer, taxes=[vat15])
    session.commit()

    stored = get_document(session, books.id, invoice.id)
    assert stored.state == "draft"
    assert stored.number is None
    assert stored.journal_entry_id is None
    assert len(stored.lines) == 1
    assert stored.lines[0].description == "Consulting services"
    assert stored.lines[0].description_ar == "خدمات استشارية"


def test_totals_come_from_the_lines(session: Session, books, customer, vat15) -> None:
    """R2.AC9 in practice: nothing is stored, so nothing can drift."""
    invoice = make_invoice(session, books, customer, taxes=[vat15], quantity="3",
                           unit_price="100.00")
    session.commit()

    totals = totals_of(session, get_document(session, books.id, invoice.id))
    assert totals.net == Decimal("300.00")
    assert totals.tax_total == Decimal("45.00")
    assert totals.total == Decimal("345.00")


def test_a_draft_can_be_changed(session: Session, books, customer, vat15) -> None:
    """R3.AC2"""
    invoice = make_invoice(session, books, customer, taxes=[vat15])
    session.commit()

    updated = update_document(
        session,
        books.id,
        invoice.id,
        {
            "date": date(2026, 4, 1),
            "narration": "April work",
            "lines": [
                LineData(
                    description="Retainer",
                    quantity=Decimal("2"),
                    unit_price=Decimal("250.00"),
                    account_id=account_id(session, books.id, "4100"),
                    tax_ids=[vat15.id],
                )
            ],
        },
    )
    session.commit()

    assert updated.date == date(2026, 4, 1)
    assert [line.description for line in updated.lines] == ["Retainer"]
    assert totals_of(session, updated).total == Decimal("575.00")


def test_a_due_date_is_stored(session: Session, books, customer) -> None:
    """R3.AC3"""
    invoice = make_invoice(session, books, customer, due_date=date(2026, 4, 15))
    session.commit()
    assert get_document(session, books.id, invoice.id).due_date == date(2026, 4, 15)


@pytest.mark.parametrize(
    ("quantity", "price"), [("-1", "100.00"), ("1", "-100.00")]
)
def test_a_negative_line_is_refused(
    session: Session, books, customer, quantity: str, price: str
) -> None:
    """R3.AC5"""
    with pytest.raises(DomainError) as error:
        make_invoice(session, books, customer, quantity=quantity, unit_price=price)
    assert error.value.code == "invoicing.invalid_line"
    session.rollback()


def test_a_line_needs_a_description(session: Session, books, customer) -> None:
    with pytest.raises(DomainError) as error:
        create_document(
            session,
            books.id,
            DocumentData(
                type="out_invoice",
                partner_id=customer.id,
                journal_id=journal_id(session, books.id, "INV"),
                date=TODAY,
                lines=[
                    LineData(
                        description="   ",
                        quantity=Decimal("1"),
                        unit_price=Decimal("10"),
                        account_id=account_id(session, books.id, "4100"),
                    )
                ],
            ),
        )
    assert error.value.code == "invoicing.invalid_line"
    session.rollback()


def test_an_account_from_another_company_is_refused(session: Session, books, customer) -> None:
    """R3.AC6"""
    from tests.factories import make_small_billing_company

    other = make_small_billing_company(session)
    with pytest.raises(DomainError) as error:
        create_document(
            session,
            books.id,
            DocumentData(
                type="out_invoice",
                partner_id=customer.id,
                journal_id=journal_id(session, books.id, "INV"),
                date=TODAY,
                lines=[
                    LineData(
                        description="Theirs",
                        quantity=Decimal("1"),
                        unit_price=Decimal("10"),
                        account_id=account_id(session, other.id, "4100"),
                    )
                ],
            ),
        )
    assert error.value.code == "invoicing.account_not_found"
    session.rollback()


def test_a_partner_from_another_company_is_refused(session: Session, books) -> None:
    """R9.AC5 at the document level."""
    from tests.factories import make_partner, make_small_billing_company

    other = make_small_billing_company(session)
    theirs = make_partner(session, other.id)

    with pytest.raises(DomainError) as error:
        make_invoice(session, books, theirs)
    assert error.value.code == "invoicing.partner_not_found"
    session.rollback()


def test_a_draft_can_be_deleted(session: Session, books, customer) -> None:
    """R3.AC7"""
    invoice = make_invoice(session, books, customer)
    session.commit()

    delete_document(session, books.id, invoice.id)
    session.commit()

    with pytest.raises(DomainError) as error:
        get_document(session, books.id, invoice.id)
    assert error.value.code == "invoicing.document_not_found"


def test_documents_can_be_listed_and_filtered(
    session: Session, books, customer, vendor, vat15
) -> None:
    """R10.AC1 and R10.AC2 at the service level."""
    make_invoice(session, books, customer, taxes=[vat15], on=date(2026, 3, 1))
    make_invoice(session, books, customer, on=date(2026, 5, 1))
    make_bill(session, books, vendor, on=date(2026, 4, 1))
    session.commit()

    everything = list_documents(session, books.id)
    assert [document.date for document in everything] == [
        date(2026, 5, 1),
        date(2026, 4, 1),
        date(2026, 3, 1),
    ]
    assert len(list_documents(session, books.id, type_="in_bill")) == 1
    assert len(list_documents(session, books.id, partner_id=customer.id)) == 2
    assert len(list_documents(session, books.id, since=date(2026, 4, 1))) == 2
    assert len(list_documents(session, books.id, until=date(2026, 3, 31))) == 1


class TestVendorBills:
    def test_a_bill_records_the_vendors_own_number(
        self, session: Session, books, vendor
    ) -> None:
        """R4.AC1 and R4.AC2"""
        bill = make_bill(session, books, vendor, vendor_reference="INV-5521")
        session.commit()

        stored = get_document(session, books.id, bill.id)
        assert (stored.type, stored.state) == ("in_bill", "draft")
        assert stored.vendor_reference == "INV-5521"

    def test_the_same_vendor_reference_twice_is_refused(
        self, session: Session, books, vendor
    ) -> None:
        """R4.AC3 — the duplicate-bill check an accounts payable clerk relies on."""
        make_bill(session, books, vendor, vendor_reference="INV-7788")
        session.commit()

        with pytest.raises(DomainError) as error:
            make_bill(session, books, vendor, vendor_reference="INV-7788")
        assert error.value.code == "invoicing.duplicate_vendor_reference"
        session.rollback()

    def test_two_vendors_may_use_the_same_number(self, session: Session, books, vendor) -> None:
        from tests.factories import make_partner

        other_vendor = make_partner(session, books.id, name="Second Supplier", type="vendor")
        make_bill(session, books, vendor, vendor_reference="0001")
        make_bill(session, books, other_vendor, vendor_reference="0001")
        session.commit()


def test_an_unknown_document_is_not_found(session: Session, books) -> None:
    with pytest.raises(DomainError) as error:
        get_document(session, books.id, uuid7())
    assert error.value.code == "invoicing.document_not_found"
