"""Migration 0001 creates the whole ledger schema, and can be rolled back.

Proves the structural half of the invariants (constraints, composite foreign keys,
triggers) exists; the behavioural half is proven in tests/invariants/.
"""

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tests.conftest import migrate

TABLES = [
    "currency",
    "company",
    "sequence_counter",
    "exchange_rate",
    "account",
    "journal",
    "ledger_settings",
    "journal_entry",
    "journal_entry_line",
]

TRIGGERS = [
    ("company", "company_guard"),
    ("account", "account_guard"),
    ("journal_entry", "journal_entry_guard"),
    ("journal_entry_line", "journal_entry_line_guard"),
    ("journal_entry", "journal_entry_balance"),
]

INDEXES = [
    "journal_entry_number_uniq",
    "journal_entry_one_reversal",
    "journal_entry_one_per_source",
    "journal_entry_company_date",
    "journal_entry_line_account",
]


def scalar(session: Session, sql: str, **params) -> object:
    return session.execute(text(sql), params).scalar()


@pytest.mark.parametrize("table", TABLES)
def test_tables_exist(session: Session, table: str) -> None:
    assert scalar(session, "SELECT to_regclass(:t) IS NOT NULL", t=table) is True


def test_currencies_are_seeded_with_their_precision(session: Session) -> None:
    rows = dict(
        session.execute(text("SELECT code, decimal_places FROM currency")).all()  # type: ignore[arg-type]
    )
    assert rows["SAR"] == 2
    assert rows["KWD"] == 3 and rows["BHD"] == 3 and rows["OMR"] == 3
    assert rows["JPY"] == 0
    assert len(rows) == 13


@pytest.mark.parametrize(("table", "trigger"), TRIGGERS)
def test_triggers_exist(session: Session, table: str, trigger: str) -> None:
    found = scalar(
        session,
        """
        SELECT count(*) FROM pg_trigger t
        JOIN pg_class c ON c.oid = t.tgrelid
        WHERE c.relname = :table AND t.tgname = :trigger AND NOT t.tgisinternal
        """,
        table=table,
        trigger=trigger,
    )
    assert found == 1


def test_balance_check_is_a_deferred_constraint_trigger(session: Session) -> None:
    row = session.execute(
        text(
            """
            SELECT t.tgdeferrable, t.tginitdeferred, t.tgconstraint <> 0
            FROM pg_trigger t WHERE t.tgname = 'journal_entry_balance'
            """
        )
    ).one()
    assert row == (True, True, True)


@pytest.mark.parametrize("index", INDEXES)
def test_indexes_exist(session: Session, index: str) -> None:
    assert scalar(session, "SELECT to_regclass(:i) IS NOT NULL", i=index) is True


def test_composite_foreign_keys_scope_rows_to_one_company(session: Session) -> None:
    """Lines, journals and reversals reference (id, company_id), not just id."""
    rows = session.execute(
        text(
            """
            SELECT c.conrelid::regclass::text AS child,
                   c.confrelid::regclass::text AS parent,
                   array_length(c.conkey, 1) AS columns
            FROM pg_constraint c
            WHERE c.contype = 'f' AND array_length(c.conkey, 1) = 2
            ORDER BY 1, 2
            """
        )
    ).all()
    pairs = {(r.child, r.parent) for r in rows}
    assert ("journal_entry_line", "journal_entry") in pairs
    assert ("journal_entry_line", "account") in pairs
    assert ("journal_entry", "journal") in pairs
    assert ("journal_entry", "journal_entry") in pairs
    assert ("account", "account") in pairs
    assert all(r.columns == 2 for r in rows)


def test_money_columns_are_numeric_not_float(session: Session) -> None:
    rows = session.execute(
        text(
            """
            SELECT column_name, data_type, numeric_precision, numeric_scale
            FROM information_schema.columns
            WHERE table_name = 'journal_entry_line'
              AND column_name IN ('debit', 'credit', 'amount_currency')
            """
        )
    ).all()
    assert len(rows) == 3
    for row in rows:
        assert row.data_type == "numeric"
        assert (row.numeric_precision, row.numeric_scale) == (20, 6)


def test_migrations_run_on_the_direct_endpoint(engine: Engine) -> None:
    """Alembic must not go through Neon's pooler (no session state in transaction mode)."""
    assert "-pooler" not in (engine.url.host or "")


def test_upgrade_then_downgrade_leaves_no_ledger_objects(scratch_database: Engine) -> None:
    with scratch_database.begin() as connection:
        migrate(connection, "head")
        assert connection.execute(text("SELECT count(*) FROM currency")).scalar() == 13

    with scratch_database.begin() as connection:
        migrate(connection, "base")
        # alembic_version is Alembic's own bookkeeping table, not part of the schema.
        left = connection.execute(
            text(
                "SELECT count(*) FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            )
        ).scalar()
        functions = connection.execute(
            text(
                """
                SELECT count(*) FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = 'public' AND p.proname LIKE '%_guard'
                """
            )
        ).scalar()
    assert (left, functions) == (0, 0)

    with scratch_database.begin() as connection:
        migrate(connection, "head")
        assert connection.execute(text("SELECT to_regclass('journal_entry')")).scalar() is not None
