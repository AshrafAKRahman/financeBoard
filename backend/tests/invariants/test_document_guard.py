"""An issued document is evidence: raw SQL cannot rewrite it (R7.AC3, R7.AC4)."""

from datetime import date

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.shared.ids import uuid7
from tests.billing.conftest import account_id, journal_id
from tests.factories import make_billing_company, make_partner
from tests.invariants.helpers import rejects

pytestmark = pytest.mark.db


@pytest.fixture
def books(session: Session):
    return make_billing_company(session)


@pytest.fixture
def customer(session: Session, books):
    return make_partner(session, books.id)


def insert_document(connection, books, customer, *, state: str = "draft"):
    document_id = uuid7()
    session = Session(bind=connection)
    connection.execute(
        text(
            "INSERT INTO document (id, company_id, type, partner_id, journal_id, date, "
            "currency_code, state, number, posted_at) VALUES (:id, :company, 'out_invoice', "
            ":partner, :journal, :date, 'SAR', 'draft', NULL, NULL)"
        ),
        {
            "id": document_id,
            "company": books.id,
            "partner": customer.id,
            "journal": journal_id(session, books.id, "INV"),
            "date": date(2026, 3, 1),
        },
    )
    connection.execute(
        text(
            "INSERT INTO document_line (id, document_id, company_id, line_no, description, "
            "quantity, unit_price, account_id) VALUES (:id, :document, :company, 1, 'Line', "
            "1, 100, :account)"
        ),
        {
            "id": uuid7(),
            "document": document_id,
            "company": books.id,
            "account": account_id(session, books.id, "4100"),
        },
    )
    if state != "draft":
        # The table insists an issued document has a real journal entry, so post one.
        entry_id = post_minimal_entry(session, books)
        connection.execute(
            text(
                "UPDATE document SET state = :state, number = :number, posted_at = now(), "
                "journal_entry_id = :entry WHERE id = :id"
            ),
            {
                "id": document_id,
                "state": state,
                "number": f"INV/2026/{uuid7().int % 100000:05d}",
                "entry": entry_id,
            },
        )
    return document_id


def post_minimal_entry(session: Session, books):
    """A balanced entry, so the document has something real to point at."""
    from decimal import Decimal

    from app.ledger.api import PostingLine, PostingRequest, post

    entry = post(
        session,
        PostingRequest(
            company_id=books.id,
            journal_id=journal_id(session, books.id, "MISC"),
            date=date(2026, 3, 1),
            currency_code="SAR",
            lines=(
                PostingLine(account_id(session, books.id, "1200"), debit=Decimal("100.00")),
                PostingLine(account_id(session, books.id, "4100"), credit=Decimal("100.00")),
            ),
        ),
    )
    session.flush()
    return entry.id


def test_a_draft_can_still_be_changed(engine: Engine, books, customer) -> None:
    with engine.begin() as connection:
        document_id = insert_document(connection, books, customer)
        connection.execute(
            text("UPDATE document SET narration = 'edited' WHERE id = :id"), {"id": document_id}
        )
        connection.execute(
            text("UPDATE document_line SET quantity = 2 WHERE document_id = :id"),
            {"id": document_id},
        )


def test_a_draft_can_be_deleted_with_its_lines(engine: Engine, books, customer) -> None:
    with engine.begin() as connection:
        document_id = insert_document(connection, books, customer)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM document WHERE id = :id"), {"id": document_id})
    with engine.connect() as connection:
        left = connection.execute(
            text("SELECT count(*) FROM document_line WHERE document_id = :id"),
            {"id": document_id},
        ).scalar_one()
    assert left == 0


class TestIssuedDocuments:
    def test_the_header_cannot_change(self, engine: Engine, books, customer) -> None:
        with engine.begin() as connection:
            document_id = insert_document(connection, books, customer, state="posted")

        with rejects("invoicing.posted_immutable"), engine.begin() as connection:
            connection.execute(
                text("UPDATE document SET date = '2026-04-01' WHERE id = :id"),
                {"id": document_id},
            )

    def test_the_number_cannot_change(self, engine: Engine, books, customer) -> None:
        with engine.begin() as connection:
            document_id = insert_document(connection, books, customer, state="posted")

        with rejects("invoicing.posted_immutable"), engine.begin() as connection:
            connection.execute(
                text("UPDATE document SET number = 'INV/2026/00999' WHERE id = :id"),
                {"id": document_id},
            )

    def test_it_cannot_go_back_to_draft(self, engine: Engine, books, customer) -> None:
        with engine.begin() as connection:
            document_id = insert_document(connection, books, customer, state="posted")

        with rejects("invoicing.posted_immutable"), engine.begin() as connection:
            connection.execute(
                text("UPDATE document SET state = 'draft' WHERE id = :id"), {"id": document_id}
            )

    def test_it_cannot_be_deleted(self, engine: Engine, books, customer) -> None:
        """R7.AC4"""
        with engine.begin() as connection:
            document_id = insert_document(connection, books, customer, state="posted")

        with rejects("invoicing.posted_immutable"), engine.begin() as connection:
            connection.execute(text("DELETE FROM document WHERE id = :id"), {"id": document_id})

    def test_its_lines_are_frozen(self, engine: Engine, books, customer) -> None:
        with engine.begin() as connection:
            document_id = insert_document(connection, books, customer, state="posted")

        for statement in (
            "UPDATE document_line SET quantity = 99 WHERE document_id = :id",
            "DELETE FROM document_line WHERE document_id = :id",
        ):
            with rejects("invoicing.posted_immutable"), engine.begin() as connection:
                connection.execute(text(statement), {"id": document_id})

    def test_no_line_can_be_added(self, engine: Engine, books, customer) -> None:
        with engine.begin() as connection:
            document_id = insert_document(connection, books, customer, state="posted")

        with rejects("invoicing.posted_immutable"), engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO document_line (id, document_id, company_id, line_no, "
                    "description, quantity, unit_price, account_id) VALUES (:id, :document, "
                    ":company, 2, 'Sneaked in', 1, 1, :account)"
                ),
                {
                    "id": uuid7(),
                    "document": document_id,
                    "company": books.id,
                    "account": account_id(Session(bind=connection), books.id, "4100"),
                },
            )

    def test_cancelling_is_the_one_allowed_change(self, engine: Engine, books, customer) -> None:
        """R7.AC5 — the document stays, marked cancelled."""
        with engine.begin() as connection:
            document_id = insert_document(connection, books, customer, state="posted")

        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE document SET state = 'cancelled', cancelled_at = now(), "
                    "cancel_reason = 'duplicate' WHERE id = :id"
                ),
                {"id": document_id},
            )

        with engine.connect() as connection:
            state = connection.execute(
                text("SELECT state FROM document WHERE id = :id"), {"id": document_id}
            ).scalar_one()
        assert state == "cancelled"
