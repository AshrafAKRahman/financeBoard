"""Migration 0005: open amounts on ledger lines, and the payment tables."""

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.platform.access.permissions import CODES
from app.shared.ids import uuid7
from tests.factories import insert_draft_entry, make_books, mark_posted
from tests.invariants.helpers import CHECK_VIOLATION, UNIQUE_VIOLATION, rejects

pytestmark = pytest.mark.db

TABLES = ["reconciliation", "payment", "bank_statement", "bank_statement_line"]
NEW_PERMISSIONS = [
    "payment:read",
    "payment:manage",
    "payment:post",
    "statement:read",
    "statement:import",
]


@pytest.mark.parametrize("table", TABLES)
def test_tables_exist(session: Session, table: str) -> None:
    assert session.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar() is not None


@pytest.mark.parametrize("code", NEW_PERMISSIONS)
def test_the_new_permissions_are_seeded_and_granted(session: Session, code: str) -> None:
    """R10.AC7 is enforced in code; a migrated database must already know these codes."""
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


def test_a_ledger_line_carries_its_open_amount(session: Session) -> None:
    """R3.AC1 — the three columns the ledger reserved for this feature."""
    columns = set(
        session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'journal_entry_line'"
            )
        ).scalars()
    )
    assert {"residual", "residual_currency", "reconciled"} <= columns


def test_a_statement_line_records_what_the_bank_said(session: Session) -> None:
    """R7.AC3"""
    columns = set(
        session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'bank_statement_line'"
            )
        ).scalars()
    )
    assert {"date", "amount", "description", "counterparty", "bank_reference"} <= columns


class TestOpenAmountColumns:
    def test_an_open_amount_cannot_be_negative(self, engine: Engine, books) -> None:
        with engine.begin() as connection:
            insert_draft_entry(
                connection, books, [("receivable", "100", "0"), ("revenue", "0", "100")]
            )
            with rejects(sqlstate=CHECK_VIOLATION):
                connection.execute(
                    text("UPDATE journal_entry_line SET residual = -1, residual_currency = -1")
                )

    def test_an_open_amount_cannot_exceed_the_line(self, engine: Engine, books) -> None:
        """R3.AC5 — the column itself refuses nonsense before any trigger runs."""
        with engine.begin() as connection:
            insert_draft_entry(
                connection, books, [("receivable", "100", "0"), ("revenue", "0", "100")]
            )
            with rejects(sqlstate=CHECK_VIOLATION):
                connection.execute(
                    text(
                        "UPDATE journal_entry_line SET residual = 500, residual_currency = 500 "
                        "WHERE debit = 100"
                    )
                )

    def test_both_currencies_are_set_together(self, engine: Engine, books) -> None:
        with engine.begin() as connection:
            insert_draft_entry(
                connection, books, [("receivable", "100", "0"), ("revenue", "0", "100")]
            )
            with rejects(sqlstate=CHECK_VIOLATION):
                connection.execute(
                    text("UPDATE journal_entry_line SET residual = 100 WHERE debit = 100")
                )

    def test_a_line_cannot_claim_to_be_reconciled_with_money_open(
        self, engine: Engine, books
    ) -> None:
        with engine.begin() as connection:
            insert_draft_entry(
                connection, books, [("receivable", "100", "0"), ("revenue", "0", "100")]
            )
            with rejects(sqlstate=CHECK_VIOLATION):
                connection.execute(
                    text(
                        "UPDATE journal_entry_line "
                        "SET residual = 100, residual_currency = 100, reconciled = true "
                        "WHERE debit = 100"
                    )
                )


class TestPostedLinesStayFrozen:
    def test_an_open_amount_may_change_on_a_posted_line(self, engine: Engine, books) -> None:
        """R3.AC2, R3.AC3 — the one door migration 0005 opens in the ledger's line guard,
        and the whole cycle done in raw SQL: post, match, close."""
        with engine.begin() as connection:
            invoice = insert_draft_entry(
                connection, books, [("receivable", "100", "0"), ("revenue", "0", "100")]
            )
            receipt = insert_draft_entry(
                connection, books, [("bank", "60", "0"), ("receivable", "0", "60")]
            )
            for entry, number in ((invoice, "MISC/2026/00101"), (receipt, "MISC/2026/00102")):
                mark_posted(connection, entry, number)
            connection.execute(
                text(
                    "UPDATE journal_entry_line l SET residual = abs(l.debit - l.credit), "
                    "residual_currency = abs(l.amount_currency) FROM account a "
                    "WHERE a.id = l.account_id AND a.is_reconcilable AND l.entry_id IN (:i, :r)"
                ),
                {"i": invoice, "r": receipt},
            )

        with engine.begin() as connection:
            open_invoice, paid = connection.execute(
                text(
                    "SELECT l.id FROM journal_entry_line l JOIN account a ON a.id = l.account_id "
                    "WHERE a.is_reconcilable AND l.entry_id IN (:i, :r) ORDER BY l.debit DESC"
                ),
                {"i": invoice, "r": receipt},
            ).scalars()
            connection.execute(
                text(
                    "INSERT INTO reconciliation (id, company_id, debit_line_id, credit_line_id, "
                    "debit_amount, credit_amount, debit_amount_currency, credit_amount_currency) "
                    "VALUES (:id, :c, :d, :cr, 60, 60, 60, 60)"
                ),
                {"id": uuid7(), "c": books.company_id, "d": open_invoice, "cr": paid},
            )
            connection.execute(
                text(
                    "UPDATE journal_entry_line SET residual = 40, residual_currency = 40 "
                    "WHERE id = :id"
                ),
                {"id": open_invoice},
            )
            connection.execute(
                text(
                    "UPDATE journal_entry_line SET residual = 0, residual_currency = 0, "
                    "reconciled = true WHERE id = :id"
                ),
                {"id": paid},
            )

        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT residual, reconciled FROM journal_entry_line "
                    "WHERE id IN (:d, :c) ORDER BY residual DESC"
                ),
                {"d": open_invoice, "c": paid},
            ).all()
        assert rows == [(40, False), (0, True)]

    def test_nothing_else_may_change_on_a_posted_line(self, engine: Engine, books) -> None:
        """NFR3 — the guard still refuses everything it refused before."""
        with engine.begin() as connection:
            entry = insert_draft_entry(
                connection, books, [("receivable", "100", "0"), ("revenue", "0", "100")]
            )
            mark_posted(connection, entry, "MISC/2026/00102")

        with engine.begin() as connection, rejects("ledger.posted_immutable"):
            connection.execute(
                text("UPDATE journal_entry_line SET debit = 999 WHERE entry_id = :e"),
                {"e": entry},
            )

    def test_an_amount_change_disguised_as_an_open_amount_change_is_refused(
        self, engine: Engine, books
    ) -> None:
        with engine.begin() as connection:
            entry = insert_draft_entry(
                connection, books, [("receivable", "100", "0"), ("revenue", "0", "100")]
            )
            mark_posted(connection, entry, "MISC/2026/00103")

        with engine.begin() as connection, rejects("ledger.posted_immutable"):
            connection.execute(
                text(
                    "UPDATE journal_entry_line SET residual = 50, residual_currency = 50, "
                    "name = 'quietly rewritten' WHERE entry_id = :e AND debit = 100"
                ),
                {"e": entry},
            )


class TestReconciliationTable:
    def test_a_match_must_be_for_a_positive_amount(self, engine: Engine, books) -> None:
        with engine.begin() as connection:
            entry = insert_draft_entry(
                connection, books, [("receivable", "100", "0"), ("revenue", "0", "100")]
            )
            debit, credit = connection.execute(
                text("SELECT id FROM journal_entry_line WHERE entry_id = :e ORDER BY line_no"),
                {"e": entry},
            ).scalars()
            with rejects(sqlstate=CHECK_VIOLATION):
                connection.execute(
                    text(
                        "INSERT INTO reconciliation (id, company_id, debit_line_id, "
                        "credit_line_id, debit_amount, credit_amount) "
                        "VALUES (:id, :c, :d, :cr, 0, 0)"
                    ),
                    {"id": uuid7(), "c": books.company_id, "d": debit, "cr": credit},
                )

    def test_a_line_cannot_settle_itself(self, engine: Engine, books) -> None:
        with engine.begin() as connection:
            entry = insert_draft_entry(
                connection, books, [("receivable", "100", "0"), ("revenue", "0", "100")]
            )
            line = connection.execute(
                text("SELECT id FROM journal_entry_line WHERE entry_id = :e LIMIT 1"),
                {"e": entry},
            ).scalar_one()
            with rejects(sqlstate=CHECK_VIOLATION):
                connection.execute(
                    text(
                        "INSERT INTO reconciliation (id, company_id, debit_line_id, "
                        "credit_line_id, debit_amount, credit_amount) "
                        "VALUES (:id, :c, :l, :l, 10, 10)"
                    ),
                    {"id": uuid7(), "c": books.company_id, "l": line},
                )


class TestStatementLines:
    def test_the_same_row_cannot_be_imported_twice(self, engine: Engine, books) -> None:
        """R7.AC4 rests on this index."""
        statement_id = uuid7()
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO bank_statement (id, company_id, bank_account_id, name, "
                    "source_format) VALUES (:id, :c, :a, 'March', 'csv')"
                ),
                {"id": statement_id, "c": books.company_id, "a": books.accounts["bank"]},
            )
            for line_no in (1, 2):
                statement = {
                    "id": uuid7(),
                    "s": statement_id,
                    "c": books.company_id,
                    "no": line_no,
                    "hash": "the-same-row",
                }
                insert = text(
                    "INSERT INTO bank_statement_line (id, statement_id, company_id, line_no, "
                    "date, amount, currency_code, import_hash) VALUES "
                    "(:id, :s, :c, :no, '2026-03-01', 115, 'SAR', :hash)"
                )
                if line_no == 1:
                    connection.execute(insert, statement)
                else:
                    with rejects(sqlstate=UNIQUE_VIOLATION):
                        connection.execute(insert, statement)

    def test_a_statement_line_is_reconciled_exactly_when_it_has_an_entry(
        self, engine: Engine, books
    ) -> None:
        """R7.AC7 — reconciled and "in the ledger" are the same thing."""
        statement_id = uuid7()
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO bank_statement (id, company_id, bank_account_id, name, "
                    "source_format) VALUES (:id, :c, :a, 'March', 'csv')"
                ),
                {"id": statement_id, "c": books.company_id, "a": books.accounts["bank"]},
            )
            with rejects(sqlstate=CHECK_VIOLATION):
                connection.execute(
                    text(
                        "INSERT INTO bank_statement_line (id, statement_id, company_id, line_no, "
                        "date, amount, currency_code, import_hash, reconciled_at) VALUES "
                        "(:id, :s, :c, 1, '2026-03-01', 115, 'SAR', 'h', now())"
                    ),
                    {"id": uuid7(), "s": statement_id, "c": books.company_id},
                )


def test_the_backfill_leaves_unreconcilable_lines_empty(engine: Engine, books) -> None:
    """R3.AC6 — a revenue line has no open amount to carry."""
    with engine.begin() as connection:
        entry = insert_draft_entry(
            connection, books, [("receivable", "100", "0"), ("revenue", "0", "100")]
        )
        mark_posted(connection, entry, "MISC/2026/00104")
        revenue_open = connection.execute(
            text(
                "SELECT l.residual FROM journal_entry_line l JOIN account a ON a.id = l.account_id"
                " WHERE l.entry_id = :e AND NOT a.is_reconcilable"
            ),
            {"e": entry},
        ).scalar_one()
    assert revenue_open is None


@pytest.fixture
def books(session: Session):
    return make_books(session)
