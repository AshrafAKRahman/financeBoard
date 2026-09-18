"""Loading a chart template (R6)."""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.coa.accounts import list_chart
from app.coa.defaults import get_defaults
from app.coa.journals import list_journals
from app.coa.templates import SAUDI, get_template, load_template
from app.shared.errors import DomainError
from tests.coa.conftest import account
from tests.factories import Books

pytestmark = pytest.mark.db


def test_loading_creates_the_accounts_with_both_names(session: Session, empty_company) -> None:
    """R6.AC1"""
    result = load_template(session, empty_company.id, "sa")
    session.commit()

    assert result.accounts == len(SAUDI.accounts)
    chart = {row.account.code: row.account for row in list_chart(session, empty_company.id)}
    assert len(chart) == len(SAUDI.accounts)
    assert chart["1200"].name == "Trade Receivables"
    assert chart["1200"].name_ar == "الذمم المدينة التجارية"
    assert all(account.name_ar for account in chart.values())


def test_the_hierarchy_is_built(session: Session, empty_company) -> None:
    load_template(session, empty_company.id, "sa")
    session.commit()

    rows = {row.account.code: row for row in list_chart(session, empty_company.id)}
    assert rows["1"].depth == 1
    assert rows["11"].depth == 2
    assert rows["1120"].depth == 3
    assert rows["1120"].account.parent_id == rows["11"].account.id


def test_the_defaults_are_set(session: Session, empty_company) -> None:
    """R6.AC2"""
    result = load_template(session, empty_company.id, "sa")
    session.commit()

    defaults = get_defaults(session, empty_company.id)
    assert defaults.missing == []
    assert result.defaults == len(SAUDI.defaults)

    chart = {row.account.code: row.account for row in list_chart(session, empty_company.id)}
    assert defaults.accounts["receivable"] == chart["1200"].id
    assert defaults.accounts["fx_loss"] == chart["5700"].id


def test_the_journals_are_created_with_their_accounts(session: Session, empty_company) -> None:
    """R6.AC3"""
    load_template(session, empty_company.id, "sa")
    session.commit()

    journals = {journal.code: journal for journal in list_journals(session, empty_company.id)}
    assert {journal.type for journal in journals.values()} == {
        "sales",
        "purchases",
        "bank",
        "cash",
        "general",
    }
    chart = {row.account.code: row.account for row in list_chart(session, empty_company.id)}
    assert journals["BNK"].default_account_id == chart["1120"].id
    assert journals["CSH"].default_account_id == chart["1110"].id


@pytest.mark.parametrize(
    ("code", "what"),
    [
        ("1300", "VAT input"),
        ("2200", "VAT output"),
        ("2300", "withholding tax"),
        ("2400", "GOSI"),
        ("2500", "Zakat"),
        ("2700", "end of service"),
    ],
)
def test_the_saudi_specific_accounts_exist(
    session: Session, empty_company, code: str, what: str
) -> None:
    """R6.AC4"""
    load_template(session, empty_company.id, "sa")
    session.commit()

    chart = {row.account.code for row in list_chart(session, empty_company.id)}
    assert code in chart, f"{what} account missing"


def test_a_company_that_already_has_a_chart_is_refused(
    session: Session, books: Books
) -> None:
    """R6.AC5"""
    with pytest.raises(DomainError) as error:
        load_template(session, books.company_id, "sa")
    assert error.value.code == "coa.chart_not_empty"
    session.rollback()


def test_loaded_accounts_can_be_changed_afterwards(session: Session, empty_company) -> None:
    """R6.AC6 — a template is a starting point, not a cage."""
    from app.coa.accounts import archive_account, update_account

    load_template(session, empty_company.id, "sa")
    session.commit()

    chart = {row.account.code: row.account for row in list_chart(session, empty_company.id)}
    renamed = update_account(
        session, empty_company.id, chart["5300"].id, {"name": "Office Rent"}
    )
    archive_account(session, empty_company.id, chart["5400"].id)
    session.commit()

    assert renamed.name == "Office Rent"
    remaining = {row.account.code for row in list_chart(session, empty_company.id)}
    assert "5400" not in remaining


def test_an_unknown_template_is_reported(session: Session, empty_company) -> None:
    with pytest.raises(DomainError) as error:
        load_template(session, empty_company.id, "atlantis")
    assert error.value.code == "coa.template_not_found"
    session.rollback()


def test_a_failed_load_leaves_nothing_behind(session: Session, empty_company) -> None:
    """R6.AC7 and NFR5 — the load is one transaction, so a failure is invisible."""
    # An account with a code the template uses makes the load fail partway.
    account(session, empty_company.id, "2200", name="Clash", type="liability",
            subtype="current_liability")
    session.commit()

    with pytest.raises(DomainError):
        load_template(session, empty_company.id, "sa")
    session.rollback()

    remaining = {row.account.code for row in list_chart(session, empty_company.id)}
    assert remaining == {"2200"}
    assert list_journals(session, empty_company.id) == []
    assert get_defaults(session, empty_company.id).missing == sorted(SAUDI.defaults)


def test_loading_is_audited(session: Session, empty_company) -> None:
    """R12.AC4 at the service level."""
    load_template(session, empty_company.id, "sa")
    session.commit()

    actions = (
        session.execute(
            text("SELECT action FROM audit_log WHERE company_id = :c AND action = :a"),
            {"c": empty_company.id, "a": "chart_template.loaded"},
        )
        .scalars()
        .all()
    )
    assert actions == ["chart_template.loaded"]


def test_templates_can_be_listed_with_their_descriptions(session: Session) -> None:
    """R12.AC3"""
    template = get_template("sa")
    assert (template.key, template.name) == ("sa", SAUDI.name)
    assert template.description
