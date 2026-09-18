"""Issuing a document puts it in the books, exactly once (R6, R7.AC1, R7.AC2)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.billing.documents import (
    cancel_document,
    entry_of,
    get_document,
    post_document,
    totals_of,
    update_document,
)
from app.billing.taxes import TaxData, create_tax
from app.coa.defaults import set_default
from app.ledger.api import JournalEntry
from app.shared.errors import DomainError
from tests.billing.conftest import account_id
from tests.billing.helpers import TODAY, make_bill, make_invoice

pytestmark = pytest.mark.db


def lines_by_account(session: Session, entry: JournalEntry) -> dict[str, tuple]:
    from app.ledger.api import Account

    out = {}
    for line in entry.lines:
        code = session.get(Account, line.account_id).code
        out[code] = (line.debit, line.credit)
    return out


def test_posting_creates_one_entry_and_numbers_the_document(
    session: Session, books, customer, vat15
) -> None:
    """R6.AC1, R6.AC6, R7.AC1"""
    invoice = make_invoice(session, books, customer, taxes=[vat15])
    posted = post_document(session, books.id, invoice.id)
    session.commit()

    assert posted.state == "posted"
    assert posted.number and posted.number.startswith("INV/2026/")
    assert posted.journal_entry_id is not None
    assert posted.posted_at is not None

    entries = session.execute(
        text("SELECT count(*) FROM journal_entry WHERE source_id = :id"), {"id": invoice.id}
    ).scalar_one()
    assert entries == 1


def test_a_draft_has_no_number(session: Session, books, customer) -> None:
    """R7.AC2"""
    invoice = make_invoice(session, books, customer)
    session.commit()
    assert get_document(session, books.id, invoice.id).number is None


def test_an_invoice_debits_the_customer_and_credits_revenue_and_vat(
    session: Session, books, customer, vat15
) -> None:
    """R6.AC2 and R6.AC3 — the whole point of the feature, line by line."""
    invoice = make_invoice(session, books, customer, taxes=[vat15], unit_price="1000.00")
    posted = post_document(session, books.id, invoice.id)
    session.commit()

    entry = entry_of(session, posted)
    amounts = lines_by_account(session, entry)

    assert amounts["1200"] == (Decimal("1150.00"), Decimal("0"))  # receivable
    assert amounts["4100"] == (Decimal("0"), Decimal("1000.00"))  # revenue
    assert amounts["2200"] == (Decimal("0"), Decimal("150.00"))  # VAT output
    assert sum(line.debit for line in entry.lines) == sum(line.credit for line in entry.lines)


def test_a_bill_credits_the_vendor_and_debits_the_expense(
    session: Session, books, vendor, vat15_purchase
) -> None:
    """R4.AC4"""
    bill = make_bill(session, books, vendor, taxes=[vat15_purchase], unit_price="400.00")
    posted = post_document(session, books.id, bill.id)
    session.commit()

    amounts = lines_by_account(session, entry_of(session, posted))
    assert amounts["2100"] == (Decimal("0"), Decimal("460.00"))  # payable
    assert amounts["5300"] == (Decimal("400.00"), Decimal("0"))  # rent expense
    assert amounts["1300"] == (Decimal("60.00"), Decimal("0"))  # VAT input


def test_the_open_item_line_carries_the_partner_and_due_date(
    session: Session, books, customer, vat15
) -> None:
    """R6.AC4 and R6.AC5 — what the aged receivables report will need."""
    invoice = make_invoice(session, books, customer, taxes=[vat15], due_date=date(2026, 4, 30))
    posted = post_document(session, books.id, invoice.id)
    session.commit()

    entry = entry_of(session, posted)
    receivable = next(line for line in entry.lines if line.debit)
    assert receivable.partner_id == customer.id
    assert receivable.due_date == date(2026, 4, 30)


def test_without_a_due_date_the_document_date_is_used(session: Session, books, customer) -> None:
    """R3.AC9"""
    invoice = make_invoice(session, books, customer)
    posted = post_document(session, books.id, invoice.id)
    session.commit()

    assert posted.due_date == TODAY
    receivable = next(line for line in entry_of(session, posted).lines if line.debit)
    assert receivable.due_date == TODAY


def test_an_empty_document_cannot_be_issued(session: Session, books, customer) -> None:
    """R3.AC4"""
    from app.billing.documents import DocumentData, create_document
    from tests.billing.conftest import journal_id

    empty = create_document(
        session,
        books.id,
        DocumentData(
            type="out_invoice",
            partner_id=customer.id,
            journal_id=journal_id(session, books.id, "INV"),
            date=TODAY,
        ),
    )
    session.commit()

    with pytest.raises(DomainError) as error:
        post_document(session, books.id, empty.id)
    assert error.value.code == "invoicing.no_lines"
    session.rollback()


def test_posting_twice_is_refused(session: Session, books, customer, vat15) -> None:
    """R6.AC7"""
    invoice = make_invoice(session, books, customer, taxes=[vat15])
    post_document(session, books.id, invoice.id)
    session.commit()

    with pytest.raises(DomainError) as error:
        post_document(session, books.id, invoice.id)
    assert error.value.code == "invoicing.already_posted"
    session.rollback()


def test_a_posted_document_cannot_be_edited(session: Session, books, customer, vat15) -> None:
    """R7.AC3 at the service level; the trigger covers raw SQL."""
    invoice = make_invoice(session, books, customer, taxes=[vat15])
    post_document(session, books.id, invoice.id)
    session.commit()

    with pytest.raises(DomainError) as error:
        update_document(session, books.id, invoice.id, {"narration": "sneaky"})
    assert error.value.code == "invoicing.posted_immutable"
    session.rollback()


def test_without_a_default_account_posting_is_refused(
    session: Session, books, customer, vat15
) -> None:
    """R6.AC8"""
    set_default(session, books.id, "receivable", None)
    session.commit()

    invoice = make_invoice(session, books, customer, taxes=[vat15])
    with pytest.raises(DomainError) as error:
        post_document(session, books.id, invoice.id)
    assert error.value.code == "invoicing.default_account_missing"
    session.rollback()


def test_a_failed_posting_leaves_a_draft_and_no_entry(
    session: Session, books, customer, vat15
) -> None:
    """R6.AC9 — proven by locking the period the invoice falls in."""
    session.execute(
        text("UPDATE company SET lock_date = :lock WHERE id = :id"),
        {"lock": date(2026, 12, 31), "id": books.id},
    )
    session.commit()

    invoice = make_invoice(session, books, customer, taxes=[vat15])
    session.commit()

    with pytest.raises(DomainError) as error:
        post_document(session, books.id, invoice.id)
    assert error.value.code == "ledger.period_locked"
    session.rollback()

    stored = get_document(session, books.id, invoice.id)
    assert (stored.state, stored.number, stored.journal_entry_id) == ("draft", None, None)
    assert (
        session.execute(
            text("SELECT count(*) FROM journal_entry WHERE source_id = :id"), {"id": invoice.id}
        ).scalar_one()
        == 0
    )


def test_a_foreign_currency_invoice_is_converted_by_the_ledger(
    session: Session, books, customer, vat15
) -> None:
    """R6.AC10"""
    from app.coa.rates import set_rate

    set_rate(session, books.id, "USD", date(2026, 1, 1), Decimal("3.75"))
    session.commit()

    invoice = make_invoice(
        session, books, customer, taxes=[vat15], unit_price="100.00", currency_code="USD"
    )
    posted = post_document(session, books.id, invoice.id)
    session.commit()

    entry = entry_of(session, posted)
    receivable = next(line for line in entry.lines if line.debit)
    assert receivable.amount_currency == Decimal("115.00")  # USD
    assert receivable.debit == Decimal("431.25")  # SAR at 3.75
    assert entry.currency_code == "USD"


def test_posting_is_audited_with_the_number_and_total(
    session: Session, books, customer, vat15
) -> None:
    """R11.AC1"""
    invoice = make_invoice(session, books, customer, taxes=[vat15])
    posted = post_document(session, books.id, invoice.id)
    session.commit()

    detail = session.execute(
        text(
            "SELECT detail::text FROM audit_log WHERE target_id = :id "
            "AND action = 'document.posted'"
        ),
        {"id": str(invoice.id)},
    ).scalar_one()
    assert posted.number in detail
    assert str(totals_of(session, posted).total) in detail


def test_a_posted_document_reports_its_entry(session: Session, books, customer, vat15) -> None:
    """R11.AC4"""
    invoice = make_invoice(session, books, customer, taxes=[vat15])
    posted = post_document(session, books.id, invoice.id)
    session.commit()

    entry = entry_of(session, posted)
    assert entry is not None
    assert entry.source_type == "document"
    assert entry.source_id == invoice.id


class TestTaxRulesAtPosting:
    def test_a_tax_that_is_not_yet_effective_is_refused(
        self, session: Session, books, customer
    ) -> None:
        """R2.AC7"""
        future = create_tax(
            session,
            books.id,
            TaxData(
                name="VAT 20% (2027)",
                rate=Decimal("20"),
                type="sale",
                account_id=account_id(session, books.id, "2200"),
                effective_from=date(2027, 1, 1),
            ),
        )
        session.commit()

        invoice = make_invoice(session, books, customer, taxes=[future])
        with pytest.raises(DomainError) as error:
            post_document(session, books.id, invoice.id)
        assert error.value.code == "tax.not_effective"
        session.rollback()

    def test_a_purchase_tax_on_a_customer_invoice_is_refused(
        self, session: Session, books, customer, vat15_purchase
    ) -> None:
        """R2.AC8"""
        invoice = make_invoice(session, books, customer, taxes=[vat15_purchase])
        with pytest.raises(DomainError) as error:
            post_document(session, books.id, invoice.id)
        assert error.value.code == "tax.wrong_tax_type"
        session.rollback()

    def test_a_sales_tax_on_a_bill_is_refused(self, session: Session, books, vendor, vat15) -> None:
        """R2.AC8, the other way round."""
        bill = make_bill(session, books, vendor, taxes=[vat15])
        with pytest.raises(DomainError) as error:
            post_document(session, books.id, bill.id)
        assert error.value.code == "tax.wrong_tax_type"
        session.rollback()

    def test_a_tax_without_an_account_cannot_post(self, session: Session, books, customer) -> None:
        homeless = create_tax(
            session,
            books.id,
            TaxData(name="Unbooked tax", rate=Decimal("5"), type="sale"),
        )
        session.commit()

        invoice = make_invoice(session, books, customer, taxes=[homeless])
        with pytest.raises(DomainError) as error:
            post_document(session, books.id, invoice.id)
        assert error.value.code == "tax.account_not_found"
        session.rollback()


def test_cancelling_reverses_the_entry(session: Session, books, customer, vat15) -> None:
    """R7.AC5 — the document and both entries stay."""
    invoice = make_invoice(session, books, customer, taxes=[vat15])
    post_document(session, books.id, invoice.id)
    session.commit()

    cancelled = cancel_document(session, books.id, invoice.id, reason="raised in error")
    session.commit()

    assert cancelled.state == "cancelled"
    assert cancelled.cancel_reason == "raised in error"

    balance = session.execute(
        text(
            "SELECT coalesce(sum(l.debit) - sum(l.credit), 0) FROM journal_entry_line l "
            "JOIN journal_entry e ON e.id = l.entry_id WHERE e.company_id = :c"
        ),
        {"c": books.id},
    ).scalar_one()
    assert balance == 0
    assert entry_of(session, cancelled) is not None
