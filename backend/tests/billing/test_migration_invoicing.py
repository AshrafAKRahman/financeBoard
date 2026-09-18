"""Migration 0004: the invoicing tables and their constraints."""

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.platform.access.permissions import CODES
from app.shared.ids import uuid7
from tests.invariants.helpers import CHECK_VIOLATION, UNIQUE_VIOLATION, rejects

pytestmark = pytest.mark.db

TABLES = ["partner", "tax", "document", "document_line", "document_line_tax", "recurring_template"]
NEW_PERMISSIONS = [
    "partner:read",
    "partner:manage",
    "tax:read",
    "tax:manage",
    "invoice:read",
    "invoice:manage",
    "invoice:post",
]


@pytest.mark.parametrize("table", TABLES)
def test_tables_exist(session: Session, table: str) -> None:
    assert session.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar() is not None


@pytest.mark.parametrize("code", NEW_PERMISSIONS)
def test_the_new_permissions_are_seeded_and_granted(session: Session, code: str) -> None:
    """R10.AC9 rests on these existing in a freshly migrated database."""
    assert code in CODES
    stored = session.execute(
        text("SELECT count(*) FROM permission WHERE code = :c"), {"c": code}
    ).scalar_one()
    granted = session.execute(
        text(
            "SELECT count(*) FROM role_permission rp JOIN role r ON r.id = rp.role_id "
            "WHERE r.name = 'Administrator' AND rp.permission_code = :c"
        ),
        {"c": code},
    ).scalar_one()
    assert (stored, granted) == (1, 1)


def test_a_line_records_everything_an_invoice_needs(session: Session) -> None:
    """R3.AC8"""
    columns = set(
        session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'document_line'"
            )
        ).scalars()
    )
    assert {
        "description",
        "description_ar",
        "quantity",
        "unit_price",
        "discount_percent",
        "account_id",
    } <= columns


def test_a_partner_records_what_a_tax_invoice_needs(session: Session) -> None:
    """R9.AC2 — and NFR5: ZATCA needs these next."""
    columns = set(
        session.execute(
            text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'partner'"
            )
        ).scalars()
    )
    assert {"vat_number", "cr_number", "address", "name_ar"} <= columns


def test_a_note_links_to_the_document_it_corrects(session: Session) -> None:
    """R5.AC3"""
    found = session.execute(
        text(
            "SELECT count(*) FROM pg_constraint WHERE conrelid = 'document'::regclass "
            "AND contype = 'f' AND confrelid = 'document'::regclass"
        )
    ).scalar_one()
    assert found == 1


class TestConstraints:
    def make_partner(self, connection, company_id, **overrides):
        values = {
            "id": uuid7(),
            "company": company_id,
            "name": "Partner",
            "type": "customer",
            "vat": None,
        }
        values.update(overrides)
        connection.execute(
            text(
                "INSERT INTO partner (id, company_id, name, type, vat_number) "
                "VALUES (:id, :company, :name, :type, :vat)"
            ),
            values,
        )
        return values["id"]

    def test_a_vat_number_is_unique_within_a_company(self, engine: Engine, books) -> None:
        with engine.begin() as connection:
            self.make_partner(connection, books.id, vat="399999999999993")
        with rejects(sqlstate=UNIQUE_VIOLATION), engine.begin() as connection:
            self.make_partner(connection, books.id, vat="399999999999993")

    def test_a_tax_that_is_not_standard_must_give_a_reason(self, engine: Engine, books) -> None:
        """R1.AC4 — the invoice has to print it."""
        with rejects(sqlstate=CHECK_VIOLATION), engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO tax (id, company_id, name, rate, type, vat_category) "
                    "VALUES (:id, :company, 'Zero no reason', 0, 'sale', 'zero_rated')"
                ),
                {"id": uuid7(), "company": books.id},
            )

    @pytest.mark.parametrize("rate", ["-1", "101"])
    def test_a_rate_stays_between_zero_and_a_hundred(
        self, engine: Engine, books, rate: str
    ) -> None:
        with rejects(sqlstate=CHECK_VIOLATION), engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO tax (id, company_id, name, rate, type) "
                    "VALUES (:id, :company, :name, :rate, 'sale')"
                ),
                {"id": uuid7(), "company": books.id, "name": f"Bad {rate}", "rate": rate},
            )

    def test_a_due_date_cannot_precede_the_document(self, engine: Engine, books, customer) -> None:
        from tests.billing.conftest import journal_id

        with rejects(sqlstate=CHECK_VIOLATION), engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO document (id, company_id, type, partner_id, journal_id, date, "
                    "due_date, currency_code) VALUES (:id, :company, 'out_invoice', :partner, "
                    ":journal, '2026-03-10', '2026-03-01', 'SAR')"
                ),
                {
                    "id": uuid7(),
                    "company": books.id,
                    "partner": customer.id,
                    "journal": journal_id(Session(bind=connection), books.id, "INV"),
                },
            )

    def test_a_vendor_reference_is_unique_per_vendor(
        self, engine: Engine, books, vendor
    ) -> None:
        """R4.AC3"""
        from tests.billing.conftest import journal_id

        def insert_bill(connection) -> None:
            connection.execute(
                text(
                    "INSERT INTO document (id, company_id, type, partner_id, journal_id, date, "
                    "currency_code, vendor_reference) VALUES (:id, :company, 'in_bill', :partner, "
                    ":journal, '2026-03-01', 'SAR', 'INV-9001')"
                ),
                {
                    "id": uuid7(),
                    "company": books.id,
                    "partner": vendor.id,
                    "journal": journal_id(Session(bind=connection), books.id, "BILL"),
                },
            )

        with engine.begin() as connection:
            insert_bill(connection)
        with rejects(sqlstate=UNIQUE_VIOLATION), engine.begin() as connection:
            insert_bill(connection)
