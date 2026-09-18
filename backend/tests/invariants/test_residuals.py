"""Open amounts and posted payments, proven against raw SQL (NFR1, NFR3).

Nothing here goes through the application. If the database lets a transaction through, an
accountant with psql could do the same, and an invoice could be paid twice.
"""

from datetime import date
from uuid import UUID

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.orm import Session

from app.shared.ids import uuid7
from tests.factories import Books, insert_draft_entry, make_books, mark_posted
from tests.invariants.helpers import CHECK_VIOLATION, rejects

pytestmark = pytest.mark.db


def open_item(connection: Connection, books: Books, debit: str, credit: str, number: str) -> UUID:
    """A posted, reconcilable line carrying its full amount as open."""
    entry = insert_draft_entry(
        connection,
        books,
        [("receivable", debit, credit), ("revenue", credit, debit)],
        on=date(2026, 3, 1),
    )
    mark_posted(connection, entry, number)
    return connection.execute(
        text(
            "UPDATE journal_entry_line l SET residual = abs(l.debit - l.credit), "
            "residual_currency = abs(l.amount_currency) "
            "WHERE l.entry_id = :e AND l.account_id = :a RETURNING l.id"
        ),
        {"e": entry, "a": books.accounts["receivable"]},
    ).scalar_one()


def match(connection: Connection, books: Books, debit: UUID, credit: UUID, amount: str) -> UUID:
    reconciliation_id = uuid7()
    connection.execute(
        text(
            "INSERT INTO reconciliation (id, company_id, debit_line_id, credit_line_id, "
            "debit_amount, credit_amount, debit_amount_currency, credit_amount_currency) "
            "VALUES (:id, :c, :d, :cr, :amount, :amount, :amount, :amount)"
        ),
        {
            "id": reconciliation_id,
            "c": books.company_id,
            "d": debit,
            "cr": credit,
            "amount": amount,
        },
    )
    return reconciliation_id


def set_open(connection: Connection, line_id: UUID, amount: str) -> None:
    connection.execute(
        text(
            "UPDATE journal_entry_line SET residual = cast(:a AS numeric), "
            "residual_currency = cast(:a AS numeric), "
            "reconciled = (cast(:a AS numeric) = 0) WHERE id = :id"
        ),
        {"a": amount, "id": line_id},
    )


class TestOverMatching:
    def test_a_single_match_cannot_exceed_the_line(self, engine: Engine, books: Books) -> None:
        """R3.AC4 — the invoice is 100; nobody may match 150 against it."""
        with engine.begin() as connection:
            invoice = open_item(connection, books, "100", "0", "MISC/2026/10001")
            receipt = open_item(connection, books, "0", "150", "MISC/2026/10002")

        with rejects("payments.over_matched"), engine.begin() as connection:
            match(connection, books, invoice, receipt, "150")
            set_open(connection, invoice, "0")
            set_open(connection, receipt, "0")

    def test_two_matches_cannot_add_up_to_more_than_the_line(
        self, engine: Engine, books: Books
    ) -> None:
        """R3.AC4 — the second receipt has nothing left to settle."""
        with engine.begin() as connection:
            invoice = open_item(connection, books, "100", "0", "MISC/2026/10003")
            first = open_item(connection, books, "0", "100", "MISC/2026/10004")
            second = open_item(connection, books, "0", "50", "MISC/2026/10005")

        with engine.begin() as connection:
            match(connection, books, invoice, first, "100")
            set_open(connection, invoice, "0")
            set_open(connection, first, "0")

        with rejects("payments.over_matched"), engine.begin() as connection:
            match(connection, books, invoice, second, "50")
            set_open(connection, second, "0")

    def test_matching_the_whole_line_is_allowed(self, engine: Engine, books: Books) -> None:
        """The boundary itself is fine: paying an invoice in full closes it (R3.AC3)."""
        with engine.begin() as connection:
            invoice = open_item(connection, books, "100", "0", "MISC/2026/10006")
            receipt = open_item(connection, books, "0", "100", "MISC/2026/10007")

        with engine.begin() as connection:
            match(connection, books, invoice, receipt, "100")
            set_open(connection, invoice, "0")
            set_open(connection, receipt, "0")

        with engine.connect() as connection:
            closed = connection.execute(
                text("SELECT reconciled FROM journal_entry_line WHERE id IN (:d, :c)"),
                {"d": invoice, "c": receipt},
            ).scalars()
        assert list(closed) == [True, True]


class TestOpenAmountsStayTrue:
    def test_a_match_that_leaves_the_open_amount_untouched_is_refused(
        self, engine: Engine, books: Books
    ) -> None:
        """R3.AC5 — the whole point: a match must move the open amount with it."""
        with engine.begin() as connection:
            invoice = open_item(connection, books, "100", "0", "MISC/2026/10008")
            receipt = open_item(connection, books, "0", "60", "MISC/2026/10009")

        with rejects("payments.residual_mismatch"), engine.begin() as connection:
            match(connection, books, invoice, receipt, "60")

    def test_an_open_amount_cannot_be_written_down_without_a_match(
        self, engine: Engine, books: Books
    ) -> None:
        """R3.AC5 — forgiving a debt quietly is exactly what this prevents."""
        with engine.begin() as connection:
            invoice = open_item(connection, books, "100", "0", "MISC/2026/10010")

        with rejects("payments.residual_mismatch"), engine.begin() as connection:
            set_open(connection, invoice, "0")

    def test_deleting_a_match_must_reopen_the_line(self, engine: Engine, books: Books) -> None:
        """R3.AC5 — unmatching is the same rule read backwards."""
        with engine.begin() as connection:
            invoice = open_item(connection, books, "100", "0", "MISC/2026/10011")
            receipt = open_item(connection, books, "0", "100", "MISC/2026/10012")

        with engine.begin() as connection:
            reconciliation = match(connection, books, invoice, receipt, "100")
            set_open(connection, invoice, "0")
            set_open(connection, receipt, "0")

        with rejects("payments.residual_mismatch"), engine.begin() as connection:
            connection.execute(
                text("DELETE FROM reconciliation WHERE id = :id"), {"id": reconciliation}
            )

    def test_unmatching_that_reopens_the_line_is_allowed(
        self, engine: Engine, books: Books
    ) -> None:
        with engine.begin() as connection:
            invoice = open_item(connection, books, "100", "0", "MISC/2026/10013")
            receipt = open_item(connection, books, "0", "100", "MISC/2026/10014")

        with engine.begin() as connection:
            reconciliation = match(connection, books, invoice, receipt, "100")
            set_open(connection, invoice, "0")
            set_open(connection, receipt, "0")

        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM reconciliation WHERE id = :id"), {"id": reconciliation}
            )
            set_open(connection, invoice, "100")
            set_open(connection, receipt, "100")

        with engine.connect() as connection:
            rows = connection.execute(
                text("SELECT residual, reconciled FROM journal_entry_line WHERE id IN (:d, :c)"),
                {"d": invoice, "c": receipt},
            ).all()
        assert rows == [(100, False), (100, False)]

    def test_a_partly_matched_line_keeps_the_remainder_open(
        self, engine: Engine, books: Books
    ) -> None:
        """R3.AC2"""
        with engine.begin() as connection:
            invoice = open_item(connection, books, "100", "0", "MISC/2026/10015")
            receipt = open_item(connection, books, "0", "30", "MISC/2026/10016")

        with engine.begin() as connection:
            match(connection, books, invoice, receipt, "30")
            set_open(connection, invoice, "70")
            set_open(connection, receipt, "0")

        with engine.connect() as connection:
            row = connection.execute(
                text("SELECT residual, reconciled FROM journal_entry_line WHERE id = :id"),
                {"id": invoice},
            ).one()
        assert row == (70, False)

    def test_a_line_flagged_reconciled_with_money_open_is_refused(
        self, engine: Engine, books: Books
    ) -> None:
        with engine.begin() as connection:
            invoice = open_item(connection, books, "100", "0", "MISC/2026/10017")
            receipt = open_item(connection, books, "0", "30", "MISC/2026/10018")

        with engine.begin() as connection, rejects(sqlstate=CHECK_VIOLATION):
            match(connection, books, invoice, receipt, "30")
            connection.execute(
                text(
                    "UPDATE journal_entry_line SET residual = 70, residual_currency = 70, "
                    "reconciled = true WHERE id = :id"
                ),
                {"id": invoice},
            )


class TestPostedPaymentsAreEvidence:
    def test_a_posted_payment_cannot_be_changed(self, engine: Engine, books: Books) -> None:
        """R2.AC9"""
        payment = self.post_payment(engine, books, "PAY/2026/00001")

        with rejects("payments.posted_immutable"), engine.begin() as connection:
            connection.execute(
                text("UPDATE payment SET amount = 999 WHERE id = :id"), {"id": payment}
            )

    def test_a_posted_payment_cannot_be_deleted(self, engine: Engine, books: Books) -> None:
        payment = self.post_payment(engine, books, "PAY/2026/00002")

        with rejects("payments.posted_immutable"), engine.begin() as connection:
            connection.execute(text("DELETE FROM payment WHERE id = :id"), {"id": payment})

    def test_a_posted_payment_cannot_go_back_to_draft(self, engine: Engine, books: Books) -> None:
        payment = self.post_payment(engine, books, "PAY/2026/00003")

        with rejects("payments.posted_immutable"), engine.begin() as connection:
            connection.execute(
                text("UPDATE payment SET state = 'draft' WHERE id = :id"), {"id": payment}
            )

    def test_cancelling_is_the_one_change_it_accepts(self, engine: Engine, books: Books) -> None:
        """R2.AC10 — the door the guard leaves open."""
        payment = self.post_payment(engine, books, "PAY/2026/00004")

        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE payment SET state = 'cancelled', cancelled_at = now(), "
                    "cancel_reason = 'paid the wrong vendor' WHERE id = :id"
                ),
                {"id": payment},
            )
            state = connection.execute(
                text("SELECT state FROM payment WHERE id = :id"), {"id": payment}
            ).scalar_one()
        assert state == "cancelled"

    def test_a_draft_payment_is_still_editable(self, engine: Engine, books: Books) -> None:
        with engine.begin() as connection:
            payment = self.insert_payment(connection, books)
            connection.execute(
                text("UPDATE payment SET amount = 250 WHERE id = :id"), {"id": payment}
            )
            amount = connection.execute(
                text("SELECT amount FROM payment WHERE id = :id"), {"id": payment}
            ).scalar_one()
        assert amount == 250

    @staticmethod
    def insert_payment(connection: Connection, books: Books) -> UUID:
        partner_id = uuid7()
        connection.execute(
            text(
                "INSERT INTO partner (id, company_id, name, type) "
                "VALUES (:id, :c, 'Al Noor Est', 'customer')"
            ),
            {"id": partner_id, "c": books.company_id},
        )
        payment_id = uuid7()
        connection.execute(
            text(
                "INSERT INTO payment (id, company_id, direction, partner_id, journal_id, date, "
                "amount, currency_code) "
                "VALUES (:id, :c, 'inbound', :p, :j, '2026-03-01', 100, 'SAR')"
            ),
            {
                "id": payment_id,
                "c": books.company_id,
                "p": partner_id,
                "j": books.journals["BNK"],
            },
        )
        return payment_id

    def post_payment(self, engine: Engine, books: Books, number: str) -> UUID:
        with engine.begin() as connection:
            payment_id = self.insert_payment(connection, books)
            entry = insert_draft_entry(
                connection, books, [("bank", "100", "0"), ("receivable", "0", "100")]
            )
            mark_posted(connection, entry, f"BNK/{number[-5:]}")
            connection.execute(
                text(
                    "UPDATE payment SET state = 'posted', number = :n, posted_at = now(), "
                    "journal_entry_id = :e WHERE id = :id"
                ),
                {"n": number, "e": entry, "id": payment_id},
            )
        return payment_id


@pytest.fixture
def books(session: Session) -> Books:
    return make_books(session)
