"""Recurring invoices (R8)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.billing.documents import get_document, totals_of
from app.billing.recurring import (
    TemplateData,
    TemplateLine,
    add_months,
    create_template,
    generate_due,
    get_template,
    set_active,
    update_template,
)
from app.shared.errors import DomainError
from tests.billing.conftest import account_id, journal_id

pytestmark = pytest.mark.db


def make_template(session: Session, books, customer, vat15, **overrides):
    line = TemplateLine(
        description="Monthly retainer",
        description_ar="أتعاب شهرية",
        quantity=Decimal("1"),
        unit_price=Decimal("2000.00"),
        account_id=account_id(session, books.id, "4100"),
        tax_ids=[vat15.id],
    )
    data = {
        "name": "Al Noor retainer",
        "partner_id": customer.id,
        "journal_id": journal_id(session, books.id, "INV"),
        "next_date": date(2026, 3, 1),
        "lines": [line],
    }
    data.update(overrides)
    return create_template(session, books.id, TemplateData(**data))


def test_a_template_is_stored_with_its_lines(session: Session, books, customer, vat15) -> None:
    """R8.AC1"""
    template = make_template(session, books, customer, vat15, interval_months=3)
    session.commit()

    stored = get_template(session, books.id, template.id)
    assert stored.name == "Al Noor retainer"
    assert stored.interval_months == 3
    assert stored.active is True
    assert stored.lines[0]["description"] == "Monthly retainer"
    assert stored.lines[0]["unit_price"] == "2000.00"


def test_generating_creates_a_draft_invoice(session: Session, books, customer, vat15) -> None:
    """R8.AC2 and R8.AC4"""
    make_template(session, books, customer, vat15)
    result = generate_due(session, books.id, date(2026, 3, 1))
    session.commit()

    assert result.count == 1
    invoice = get_document(session, books.id, result.created[0])
    assert invoice.state == "draft"
    assert invoice.date == date(2026, 3, 1)
    assert invoice.partner_id == customer.id
    assert totals_of(session, invoice).total == Decimal("2300.00")
    assert invoice.lines[0].description_ar == "أتعاب شهرية"


def test_the_next_date_moves_on(session: Session, books, customer, vat15) -> None:
    """R8.AC3"""
    template = make_template(session, books, customer, vat15, interval_months=1)
    generate_due(session, books.id, date(2026, 3, 1))
    session.commit()

    assert get_template(session, books.id, template.id).next_date == date(2026, 4, 1)


def test_running_twice_for_the_same_date_bills_once(
    session: Session, books, customer, vat15
) -> None:
    """R8.AC5 — the safeguard that makes a retry harmless."""
    make_template(session, books, customer, vat15)
    first = generate_due(session, books.id, date(2026, 3, 1))
    session.commit()
    second = generate_due(session, books.id, date(2026, 3, 1))
    session.commit()

    assert (first.count, second.count) == (1, 0)
    invoices = session.execute(
        text("SELECT count(*) FROM document WHERE company_id = :c"), {"c": books.id}
    ).scalar_one()
    assert invoices == 1


def test_a_later_run_bills_the_next_period(session: Session, books, customer, vat15) -> None:
    make_template(session, books, customer, vat15)
    generate_due(session, books.id, date(2026, 3, 1))
    session.commit()
    later = generate_due(session, books.id, date(2026, 4, 1))
    session.commit()

    assert later.count == 1
    assert get_document(session, books.id, later.created[0]).date == date(2026, 4, 1)


def test_nothing_is_generated_before_it_is_due(session: Session, books, customer, vat15) -> None:
    make_template(session, books, customer, vat15, next_date=date(2026, 6, 1))
    result = generate_due(session, books.id, date(2026, 3, 1))
    session.commit()
    assert result.count == 0


def test_a_paused_template_generates_nothing(session: Session, books, customer, vat15) -> None:
    """R8.AC6"""
    template = make_template(session, books, customer, vat15)
    set_active(session, books.id, template.id, False)
    session.commit()

    assert generate_due(session, books.id, date(2026, 3, 1)).count == 0
    session.commit()

    set_active(session, books.id, template.id, True)
    session.commit()
    assert generate_due(session, books.id, date(2026, 3, 1)).count == 1
    session.commit()


def test_a_run_reports_what_it_did(session: Session, books, customer, vat15) -> None:
    """R8.AC7"""
    make_template(session, books, customer, vat15, name="First")
    make_template(session, books, customer, vat15, name="Second")
    result = generate_due(session, books.id, date(2026, 3, 1))
    session.commit()

    assert result.count == 2
    assert sorted(result.from_templates) == ["First", "Second"]

    detail = session.execute(
        text(
            "SELECT detail::text FROM audit_log WHERE company_id = :c "
            "AND action = 'recurring_template.generated' ORDER BY at DESC LIMIT 1"
        ),
        {"c": books.id},
    ).scalar_one()
    assert '"created": 2' in detail


def test_a_template_needs_lines_and_a_sane_interval(
    session: Session, books, customer, vat15
) -> None:
    with pytest.raises(DomainError) as no_lines:
        make_template(session, books, customer, vat15, lines=[])
    assert no_lines.value.code == "invoicing.no_lines"
    session.rollback()

    with pytest.raises(DomainError) as bad_interval:
        make_template(session, books, customer, vat15, interval_months=24)
    assert bad_interval.value.code == "invoicing.invalid_interval"
    session.rollback()


def test_a_template_can_be_changed(session: Session, books, customer, vat15) -> None:
    template = make_template(session, books, customer, vat15)
    session.commit()

    updated = update_template(
        session, books.id, template.id, {"name": "Renamed", "interval_months": 6}
    )
    session.commit()
    assert (updated.name, updated.interval_months) == ("Renamed", 6)


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        (date(2026, 1, 31), 1, date(2026, 2, 28)),
        (date(2024, 1, 31), 1, date(2024, 2, 29)),
        (date(2026, 11, 30), 3, date(2027, 2, 28)),
        (date(2026, 3, 15), 12, date(2027, 3, 15)),
    ],
)
def test_month_arithmetic_handles_short_months(
    start: date, months: int, expected: date
) -> None:
    assert add_months(start, months) == expected
