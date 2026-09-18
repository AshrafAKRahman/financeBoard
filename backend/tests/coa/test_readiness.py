"""Is the chart ready to keep books? (R8)"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.coa.defaults import DEFAULT_SUBTYPES, set_default
from app.coa.journals import JournalData, create_journal
from app.coa.rates import set_rate
from app.coa.readiness import check
from app.coa.templates import load_template
from tests.coa.conftest import account
from tests.factories import Books

pytestmark = pytest.mark.db


def codes(findings) -> set[str]:
    return {finding.code for finding in findings}


def test_an_empty_company_is_told_to_start(session: Session, empty_company) -> None:
    """R8.AC5"""
    findings = check(session, empty_company.id)
    assert [finding.code for finding in findings] == ["coa.chart_empty"]
    assert "template" in findings[0].message


def test_unset_defaults_are_reported(session: Session, books: Books) -> None:
    """R8.AC1"""
    findings = check(session, books.company_id)
    missing = {finding.subject for finding in findings if finding.code == "coa.default_missing"}
    # The ledger's test factory already sets the rounding account; everything else is open.
    assert missing == set(DEFAULT_SUBTYPES) - {"rounding"}

    set_default(session, books.company_id, "receivable", books.accounts["receivable"])
    session.commit()

    missing = {
        finding.subject
        for finding in check(session, books.company_id)
        if finding.code == "coa.default_missing"
    }
    assert "receivable" not in missing


def test_a_bank_journal_without_an_account_is_reported(session: Session, books: Books) -> None:
    """R8.AC2"""
    journal = create_journal(
        session,
        books.company_id,
        JournalData(
            code="BNK5",
            name="Second Bank",
            type="bank",
            default_account_id=books.accounts["bank"],
        ),
    )
    session.commit()
    reported = {
        finding.subject
        for finding in check(session, books.company_id)
        if finding.code == "coa.journal_without_account"
    }
    assert "BNK5" not in reported  # it has an account, so it is not a finding

    # Clearing it through raw SQL is the only way — the service refuses to.
    from sqlalchemy import text

    session.execute(
        text("UPDATE journal SET default_account_id = NULL WHERE id = :id"), {"id": journal.id}
    )
    session.commit()
    session.expire_all()  # the raw UPDATE bypassed the ORM's copy of the row

    reported = {
        finding.subject
        for finding in check(session, books.company_id)
        if finding.code == "coa.journal_without_account"
    }
    assert "BNK5" in reported


def test_a_group_with_no_children_is_reported(session: Session, books: Books) -> None:
    """R8.AC3"""
    lonely = account(session, books.company_id, "1900G", is_group=True)
    session.commit()

    findings = [
        finding
        for finding in check(session, books.company_id)
        if finding.code == "coa.group_without_children"
    ]
    assert lonely.code in {finding.subject for finding in findings}


def test_currencies_without_a_rate_are_reported(session: Session, books: Books) -> None:
    """R8.AC4"""
    findings = check(session, books.company_id)
    without = {
        finding.subject for finding in findings if finding.code == "coa.currency_without_rate"
    }
    assert "USD" in without
    assert "SAR" not in without  # the company's own currency needs no rate

    set_rate(session, books.company_id, "USD", date(2026, 3, 1), Decimal("3.75"))
    session.commit()

    without = {
        finding.subject
        for finding in check(session, books.company_id)
        if finding.code == "coa.currency_without_rate"
    }
    assert "USD" not in without


def test_a_freshly_loaded_saudi_chart_has_no_chart_findings(
    session: Session, empty_company
) -> None:
    """The point of the template: setup leaves nothing for the accountant to chase, apart
    from exchange rates, which only they can supply."""
    load_template(session, empty_company.id, "sa")
    session.commit()

    findings = check(session, empty_company.id)
    assert codes(findings) <= {"coa.currency_without_rate"}


def test_findings_name_what_they_are_about(session: Session, books: Books) -> None:
    for finding in check(session, books.company_id):
        assert finding.code.startswith("coa.")
        assert finding.message
