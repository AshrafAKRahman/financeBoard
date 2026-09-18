"""Migration 0006: the basis a VAT return needs, and the permission to read reports."""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.platform.access.permissions import CODES

pytestmark = pytest.mark.db


def test_a_ledger_line_can_record_what_a_tax_was_charged_on(session: Session) -> None:
    """R6.AC1"""
    columns = set(
        session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'journal_entry_line'"
            )
        ).scalars()
    )
    assert "tax_base" in columns


def test_the_report_permission_is_seeded_and_granted(session: Session) -> None:
    """R9.AC1 — a migrated database already knows the code."""
    assert "report:read" in CODES
    stored = session.execute(
        text("SELECT count(*) FROM permission WHERE code = 'report:read'")
    ).scalar_one()
    granted = session.execute(
        text(
            "SELECT count(*) FROM role_permission rp JOIN role r ON r.id = rp.role_id "
            "WHERE r.name = 'Administrator' AND rp.permission_code = 'report:read'"
        )
    ).scalar_one()
    assert (stored, granted) == (1, 1)


def test_the_grid_tag_index_exists(session: Session) -> None:
    """The VAT return groups by grid tag over a period, so it needs the index."""
    found = session.execute(
        text(
            "SELECT count(*) FROM pg_indexes "
            "WHERE tablename = 'journal_entry_line' AND indexname = 'journal_entry_line_tax_grid'"
        )
    ).scalar_one()
    assert found == 1
