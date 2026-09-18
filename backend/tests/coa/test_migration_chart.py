"""Migration 0003: the rest of the company defaults, and the chart index (R5.AC2)."""

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.shared.ids import uuid7
from tests.invariants.helpers import FOREIGN_KEY_VIOLATION, rejects

pytestmark = pytest.mark.db

DEFAULT_COLUMNS = [
    "rounding_account_id",
    "fx_gain_account_id",
    "fx_loss_account_id",
    "receivable_account_id",
    "payable_account_id",
    "outstanding_receipts_account_id",
    "outstanding_payments_account_id",
    "suspense_account_id",
]


@pytest.mark.parametrize("column", DEFAULT_COLUMNS)
def test_every_default_has_a_column(session: Session, column: str) -> None:
    found = session.execute(
        text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'ledger_settings' AND column_name = :c"
        ),
        {"c": column},
    ).scalar_one()
    assert found == 1


@pytest.mark.parametrize("column", DEFAULT_COLUMNS)
def test_every_default_is_scoped_to_the_company(session: Session, column: str) -> None:
    """Each default is a composite foreign key, so it cannot point at another company."""
    found = session.execute(
        text(
            """
            SELECT count(*) FROM pg_constraint c
            WHERE c.conrelid = 'ledger_settings'::regclass AND c.contype = 'f'
              AND array_length(c.conkey, 1) = 2
              AND :column = ANY (
                  SELECT a.attname FROM pg_attribute a
                  WHERE a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
              )
            """
        ),
        {"column": column},
    ).scalar_one()
    assert found == 1


def test_a_default_cannot_point_at_another_companys_account(
    engine: Engine, session: Session
) -> None:
    from tests.factories import make_books

    ours = make_books(session)
    theirs = make_books(session)

    with rejects(sqlstate=FOREIGN_KEY_VIOLATION), engine.begin() as connection:
        connection.execute(
            text("UPDATE ledger_settings SET receivable_account_id = :a WHERE company_id = :c"),
            {"a": theirs.accounts["receivable"], "c": ours.company_id},
        )


def test_the_chart_index_exists(session: Session) -> None:
    assert session.execute(text("SELECT to_regclass('account_tree')")).scalar() is not None


def test_defaults_start_empty_for_a_new_company(session: Session) -> None:
    from app.ledger.api import LedgerSettings
    from app.platform.tenancy.api import Company

    company = Company(id=uuid7(), name="Fresh Co", base_currency="SAR")
    session.add(company)
    session.flush()
    settings = LedgerSettings(company_id=company.id)
    session.add(settings)
    session.commit()

    assert settings.receivable_account_id is None
    assert settings.suspense_account_id is None
