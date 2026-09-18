"""Tax definitions and when they apply (R1)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.billing.taxes import (
    TaxData,
    archive_tax,
    create_tax,
    get_tax,
    list_taxes,
    update_tax,
)
from app.shared.errors import DomainError
from tests.billing.conftest import account_id

pytestmark = pytest.mark.db


def make_tax(session: Session, company_id, **overrides):
    values = {"name": "Test tax", "rate": Decimal("15"), "type": "sale"}
    values.update(overrides)
    return create_tax(session, company_id, TaxData(**values))


def test_a_tax_is_created_with_its_category(session: Session, books) -> None:
    """R1.AC1"""
    tax = make_tax(
        session,
        books.id,
        name="VAT 15% (services)",
        name_ar="ضريبة الخدمات",
        account_id=account_id(session, books.id, "2200"),
        grid_tag="sales_standard",
    )
    session.commit()

    stored = get_tax(session, books.id, tax.id)
    assert (stored.rate, stored.type, stored.vat_category) == (Decimal(15), "sale", "standard")
    assert stored.grid_tag == "sales_standard"
    assert stored.active is True


@pytest.mark.parametrize("type_", ["sale", "purchase", "withholding"])
def test_the_three_tax_types_are_supported(session: Session, books, type_: str) -> None:
    """R1.AC2"""
    tax = make_tax(session, books.id, name=f"Tax {type_}", type=type_)
    session.commit()
    assert tax.type == type_


@pytest.mark.parametrize(
    ("category", "reason"),
    [
        ("standard", None),
        ("zero_rated", "Export of goods"),
        ("exempt", "Exempt financial supply"),
        ("out_of_scope", "Outside the scope of Saudi VAT"),
    ],
)
def test_the_four_vat_categories_are_supported(
    session: Session, books, category: str, reason: str | None
) -> None:
    """R1.AC3"""
    tax = make_tax(
        session,
        books.id,
        name=f"Tax {category}",
        rate=Decimal("0") if category != "standard" else Decimal("15"),
        vat_category=category,
        exemption_reason=reason,
    )
    session.commit()
    assert tax.vat_category == category


@pytest.mark.parametrize("category", ["zero_rated", "exempt", "out_of_scope"])
def test_a_non_standard_tax_needs_a_reason(session: Session, books, category: str) -> None:
    """R1.AC4 — the invoice has to print it."""
    with pytest.raises(DomainError) as error:
        make_tax(session, books.id, name=f"No reason {category}", vat_category=category)
    assert error.value.code == "tax.missing_reason"
    session.rollback()


def test_effective_dates_decide_whether_a_tax_applies(session: Session, books) -> None:
    """R1.AC5"""
    old = make_tax(
        session,
        books.id,
        name="VAT 5% (2019)",
        rate=Decimal("5"),
        effective_from=date(2018, 1, 1),
        effective_to=date(2020, 6, 30),
    )
    current = make_tax(
        session, books.id, name="VAT 15% (2020 on)", effective_from=date(2020, 7, 1)
    )
    session.commit()

    assert old.is_effective_on(date(2019, 5, 1))
    assert not old.is_effective_on(date(2026, 3, 1))
    assert current.is_effective_on(date(2026, 3, 1))

    effective = {tax.id for tax in list_taxes(session, books.id, on=date(2026, 3, 1))}
    assert current.id in effective
    assert old.id not in effective


@pytest.mark.parametrize("rate", [Decimal("-1"), Decimal("101")])
def test_a_rate_must_be_a_percentage(session: Session, books, rate: Decimal) -> None:
    """R1.AC6"""
    with pytest.raises(DomainError) as error:
        make_tax(session, books.id, name=f"Bad {rate}", rate=rate)
    assert error.value.code == "tax.invalid_rate"
    session.rollback()


def test_an_account_from_another_company_is_refused(session: Session, books) -> None:
    """R1.AC7"""
    from tests.factories import make_billing_company

    other = make_billing_company(session)
    theirs = account_id(session, other.id, "2200")

    with pytest.raises(DomainError) as error:
        make_tax(session, books.id, name="Wrong account", account_id=theirs)
    assert error.value.code == "tax.account_not_found"
    session.rollback()


def test_a_used_rate_cannot_be_changed(session: Session, books, customer, vat15) -> None:
    """R1.AC8 — a new rate is a new tax, so old invoices keep their arithmetic."""
    from tests.billing.helpers import make_invoice, post_invoice

    invoice = make_invoice(session, books, customer, taxes=[vat15])
    post_invoice(session, books, invoice)
    session.commit()

    with pytest.raises(DomainError) as error:
        update_tax(session, books.id, vat15.id, {"rate": Decimal("16")})
    assert error.value.code == "tax.tax_in_use"
    session.rollback()


def test_an_unused_rate_can_be_changed(session: Session, books) -> None:
    tax = make_tax(session, books.id, name="Draft rate", rate=Decimal("10"))
    session.commit()

    updated = update_tax(session, books.id, tax.id, {"rate": Decimal("12.5")})
    session.commit()
    assert updated.rate == Decimal("12.5")


def test_archiving_keeps_it_on_old_documents_but_hides_it(session: Session, books) -> None:
    """R1.AC9"""
    tax = make_tax(session, books.id, name="Retired tax")
    session.commit()

    archive_tax(session, books.id, tax.id)
    session.commit()

    assert get_tax(session, books.id, tax.id).active is False
    assert tax.id not in {t.id for t in list_taxes(session, books.id)}
    assert tax.id in {t.id for t in list_taxes(session, books.id, include_archived=True)}


class TestSaudiTaxes:
    """These are about the template itself, so they load the full Saudi chart."""

    def test_loading_the_chart_installs_them(self, session: Session, saudi_books) -> None:
        """R1.AC10"""
        taxes = {tax.name: tax for tax in list_taxes(session, saudi_books.id)}

        assert "VAT 15%" in taxes
        assert "VAT 15% (purchases)" in taxes
        assert "Zero-rated exports" in taxes
        assert "Exempt supply" in taxes

    def test_the_standard_rate_is_fifteen_percent_on_both_sides(
        self, session: Session, saudi_books
    ) -> None:
        taxes = {tax.name: tax for tax in list_taxes(session, saudi_books.id)}
        assert taxes["VAT 15%"].rate == Decimal(15)
        assert taxes["VAT 15%"].type == "sale"
        assert taxes["VAT 15% (purchases)"].type == "purchase"

    def test_each_one_points_at_its_vat_account(self, session: Session, saudi_books) -> None:
        taxes = {tax.name: tax for tax in list_taxes(session, saudi_books.id)}
        assert taxes["VAT 15%"].account_id == account_id(session, saudi_books.id, "2200")
        purchases_vat = taxes["VAT 15% (purchases)"].account_id
        assert purchases_vat == account_id(session, saudi_books.id, "1300")

    def test_the_exempt_ones_carry_a_reason_and_a_grid_tag(
        self, session: Session, saudi_books
    ) -> None:
        taxes = {tax.name: tax for tax in list_taxes(session, saudi_books.id)}
        assert taxes["Zero-rated exports"].exemption_reason
        assert taxes["Exempt supply"].exemption_reason
        assert all(tax.grid_tag for tax in taxes.values())

    def test_they_are_audited(self, session: Session, saudi_books) -> None:
        created = (
            session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE company_id = :c "
                    "AND action = 'tax.created'"
                ),
                {"c": saudi_books.id},
            )
            .scalar_one()
        )
        assert created == 4
