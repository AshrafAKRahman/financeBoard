"""Company default accounts (R5)."""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.coa.accounts import archive_account
from app.coa.defaults import DEFAULT_SUBTYPES, get_defaults, set_default
from app.shared.errors import DomainError
from tests.coa.conftest import account
from tests.factories import Books

pytestmark = pytest.mark.db


def test_a_default_can_be_set_and_read_back(session: Session, books: Books) -> None:
    """R5.AC1"""
    defaults = set_default(
        session, books.company_id, "receivable", books.accounts["receivable"]
    )
    session.commit()
    assert defaults.accounts["receivable"] == books.accounts["receivable"]
    assert get_defaults(session, books.company_id).accounts["receivable"] == (
        books.accounts["receivable"]
    )


def test_every_default_has_a_home(session: Session, books: Books) -> None:
    """R5.AC2"""
    assert set(get_defaults(session, books.company_id).accounts) == set(DEFAULT_SUBTYPES)


def test_unset_defaults_are_reported(session: Session, books: Books) -> None:
    """R5.AC7"""
    missing = get_defaults(session, books.company_id).missing
    assert "receivable" in missing and "payable" in missing

    set_default(session, books.company_id, "receivable", books.accounts["receivable"])
    session.commit()
    assert "receivable" not in get_defaults(session, books.company_id).missing


@pytest.mark.parametrize(
    ("key", "account_key"),
    [("receivable", "payable"), ("payable", "receivable"), ("fx_loss", "revenue")],
)
def test_a_default_refuses_an_unsuitable_subtype(
    session: Session, books: Books, key: str, account_key: str
) -> None:
    """R5.AC3"""
    with pytest.raises(DomainError) as error:
        set_default(session, books.company_id, key, books.accounts[account_key])
    assert error.value.code == "coa.default_subtype_mismatch"
    session.rollback()


def test_an_archived_account_cannot_be_a_default(session: Session, books: Books) -> None:
    """R5.AC4"""
    target = account(session, books.company_id, "1320", subtype="receivable")
    archive_account(session, books.company_id, target.id)
    session.commit()

    with pytest.raises(DomainError) as error:
        set_default(session, books.company_id, "receivable", target.id)
    assert error.value.code == "coa.account_archived"
    session.rollback()


def test_another_companys_account_cannot_be_a_default(
    session: Session, books: Books, empty_company
) -> None:
    """R5.AC5"""
    theirs = account(session, empty_company.id, "1321", subtype="receivable")
    session.commit()

    with pytest.raises(DomainError) as error:
        set_default(session, books.company_id, "receivable", theirs.id)
    assert error.value.code == "coa.account_not_found"
    session.rollback()


def test_a_group_account_cannot_be_a_default(session: Session, books: Books) -> None:
    """R5.AC6"""
    with pytest.raises(DomainError) as error:
        set_default(session, books.company_id, "suspense", books.accounts["current_assets"])
    assert error.value.code == "coa.group_account"
    session.rollback()


def test_an_unknown_default_is_refused(session: Session, books: Books) -> None:
    with pytest.raises(DomainError) as error:
        set_default(session, books.company_id, "petty_cash", books.accounts["bank"])
    assert error.value.code == "coa.unknown_default"
    session.rollback()


def test_a_default_can_be_cleared(session: Session, books: Books) -> None:
    set_default(session, books.company_id, "receivable", books.accounts["receivable"])
    session.commit()
    set_default(session, books.company_id, "receivable", None)
    session.commit()
    assert "receivable" in get_defaults(session, books.company_id).missing


def test_setting_a_default_is_audited(session: Session, books: Books) -> None:
    """R11.AC4 at the service level."""
    set_default(session, books.company_id, "payable", books.accounts["payable"])
    session.commit()

    detail = session.execute(
        text(
            "SELECT detail::text FROM audit_log WHERE action = 'company_default.set' "
            "AND company_id = :c ORDER BY at DESC LIMIT 1"
        ),
        {"c": books.company_id},
    ).scalar_one()
    assert "payable" in detail and "2100" in detail
