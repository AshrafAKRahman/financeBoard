"""Customers and vendors (R9)."""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.billing.partners import (
    PartnerData,
    archive_partner,
    create_partner,
    get_partner,
    list_partners,
    update_partner,
)
from app.shared.errors import DomainError
from app.shared.ids import uuid7

pytestmark = pytest.mark.db


def test_a_partner_records_what_a_tax_invoice_needs(session: Session, plain_company) -> None:
    """R9.AC1 and R9.AC2"""
    partner = create_partner(
        session,
        plain_company.id,
        PartnerData(
            name="Al Noor Est",
            name_ar="مؤسسة النور",
            type="customer",
            vat_number="310000000000003",
            cr_number="1010101010",
            address={"city": "Riyadh", "street": "King Fahd Road", "country": "SA"},
            email="finance@alnoor.example.sa",
        ),
    )
    session.commit()

    stored = get_partner(session, plain_company.id, partner.id)
    assert (stored.name, stored.name_ar) == ("Al Noor Est", "مؤسسة النور")
    assert stored.vat_number == "310000000000003"
    assert stored.cr_number == "1010101010"
    assert stored.address["city"] == "Riyadh"
    assert stored.active is True


@pytest.mark.parametrize(
    "bad",
    ["123456789012345", "31000000000000", "3100000000000034", "31000000000000X", "abc"],
)
def test_a_bad_saudi_vat_number_is_refused(session: Session, plain_company, bad: str) -> None:
    """R9.AC3 — fifteen digits, first and last a 3."""
    with pytest.raises(DomainError) as error:
        create_partner(
            session,
            plain_company.id,
            PartnerData(name="Wrong", type="customer", vat_number=bad),
        )
    assert error.value.code == "invoicing.invalid_vat_number"
    session.rollback()


def test_a_vat_number_is_optional_and_spaces_are_tolerated(
    session: Session, plain_company
) -> None:
    without = create_partner(
        session, plain_company.id, PartnerData(name="Cash Sale", type="customer")
    )
    spaced = create_partner(
        session,
        plain_company.id,
        PartnerData(name="Spaced", type="customer", vat_number="3100 0000 0000 003"),
    )
    session.commit()

    assert without.vat_number is None
    assert spaced.vat_number == "310000000000003"


def test_a_partner_can_be_both_customer_and_vendor(session: Session, plain_company) -> None:
    partner = create_partner(session, plain_company.id, PartnerData(name="Both Co", type="both"))
    session.commit()

    customers = list_partners(session, plain_company.id, type_="customer")
    vendors = list_partners(session, plain_company.id, type_="vendor")
    assert partner.id in {p.id for p in customers}
    assert partner.id in {p.id for p in vendors}


def test_an_unknown_partner_type_is_refused(session: Session, plain_company) -> None:
    with pytest.raises(DomainError) as error:
        create_partner(session, plain_company.id, PartnerData(name="Odd", type="supplier"))
    assert error.value.code == "invoicing.invalid_partner_type"
    session.rollback()


def test_a_partner_is_updated(session: Session, plain_company) -> None:
    partner = create_partner(session, plain_company.id, PartnerData(name="Before", type="customer"))
    session.commit()

    updated = update_partner(
        session, plain_company.id, partner.id, {"name": "After", "vat_number": "310000000000003"}
    )
    session.commit()
    assert (updated.name, updated.vat_number) == ("After", "310000000000003")


def test_archiving_keeps_the_partner_but_hides_it(session: Session, plain_company) -> None:
    """R9.AC4"""
    partner = create_partner(
        session, plain_company.id, PartnerData(name="Retired", type="customer")
    )
    session.commit()

    archive_partner(session, plain_company.id, partner.id)
    session.commit()

    assert get_partner(session, plain_company.id, partner.id).active is False
    assert partner.id not in {p.id for p in list_partners(session, plain_company.id)}
    assert partner.id in {
        p.id for p in list_partners(session, plain_company.id, include_archived=True)
    }


def test_another_companys_partner_is_not_found(session: Session, plain_company) -> None:
    """R9.AC5"""
    from app.ledger.api import LedgerSettings
    from app.platform.tenancy.api import Company
    from app.shared.ids import uuid7 as new_id

    other = Company(id=new_id(), name="Other Co", base_currency="SAR")
    session.add(other)
    session.flush()
    session.add(LedgerSettings(company_id=other.id))
    theirs = create_partner(session, other.id, PartnerData(name="Theirs", type="customer"))
    session.commit()

    with pytest.raises(DomainError) as error:
        get_partner(session, plain_company.id, theirs.id)
    assert error.value.code == "invoicing.partner_not_found"


def test_an_unknown_partner_is_not_found(session: Session, plain_company) -> None:
    with pytest.raises(DomainError) as error:
        get_partner(session, plain_company.id, uuid7())
    assert error.value.code == "invoicing.partner_not_found"


def test_partners_can_be_searched(session: Session, plain_company) -> None:
    create_partner(
        session,
        plain_company.id,
        PartnerData(name="Al Noor Est", name_ar="مؤسسة النور", type="customer"),
    )
    create_partner(session, plain_company.id, PartnerData(name="Gulf Supplies", type="vendor"))
    session.commit()

    by_english = list_partners(session, plain_company.id, search="noor")
    by_arabic = list_partners(session, plain_company.id, search="النور")
    assert [p.name for p in by_english] == ["Al Noor Est"]
    assert [p.name for p in by_arabic] == ["Al Noor Est"]


def test_creating_is_audited(session: Session, plain_company) -> None:
    partner = create_partner(
        session, plain_company.id, PartnerData(name="Audited", type="customer")
    )
    session.commit()

    actions = (
        session.execute(
            text("SELECT action FROM audit_log WHERE target_id = :id"), {"id": str(partner.id)}
        )
        .scalars()
        .all()
    )
    assert actions == ["partner.created"]
