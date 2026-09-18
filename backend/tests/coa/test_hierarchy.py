"""Parents, children and reading the tree (R2)."""

import pytest
from sqlalchemy.orm import Session

from app.coa.accounts import list_chart, update_account
from app.shared.errors import DomainError
from app.shared.ids import uuid7
from tests.coa.conftest import account
from tests.factories import Books

pytestmark = pytest.mark.db


def test_an_account_can_be_put_under_a_group(session: Session, books: Books) -> None:
    """R2.AC1"""
    group = account(session, books.company_id, "1200G", is_group=True)
    child = account(session, books.company_id, "1201", parent_id=group.id)
    session.commit()
    assert child.parent_id == group.id


def test_a_parent_must_be_a_group(session: Session, books: Books) -> None:
    """R2.AC3"""
    leaf = account(session, books.company_id, "1202")
    session.commit()

    with pytest.raises(DomainError) as error:
        account(session, books.company_id, "1203", parent_id=leaf.id)
    assert error.value.code == "coa.parent_not_group"
    session.rollback()


def test_a_parent_must_share_the_type(session: Session, books: Books) -> None:
    """R2.AC4"""
    group = account(session, books.company_id, "1204G", is_group=True)
    session.commit()

    with pytest.raises(DomainError) as error:
        account(
            session,
            books.company_id,
            "2204",
            type="liability",
            subtype="current_liability",
            parent_id=group.id,
        )
    assert error.value.code == "coa.parent_type_mismatch"
    session.rollback()


def test_an_account_cannot_become_its_own_ancestor(session: Session, books: Books) -> None:
    """R2.AC5"""
    top = account(session, books.company_id, "1205G", is_group=True)
    middle = account(session, books.company_id, "1206G", is_group=True, parent_id=top.id)
    session.commit()

    with pytest.raises(DomainError) as error:
        update_account(session, books.company_id, top.id, {"parent_id": middle.id})
    assert error.value.code == "coa.hierarchy_cycle"
    session.rollback()


def test_an_account_cannot_be_its_own_parent(session: Session, books: Books) -> None:
    group = account(session, books.company_id, "1207G", is_group=True)
    session.commit()

    with pytest.raises(DomainError) as error:
        update_account(session, books.company_id, group.id, {"parent_id": group.id})
    assert error.value.code == "coa.hierarchy_cycle"
    session.rollback()


def test_a_parent_from_another_company_is_not_found(
    session: Session, books: Books, empty_company
) -> None:
    """R2.AC6"""
    theirs = account(session, empty_company.id, "1208G", is_group=True)
    session.commit()

    with pytest.raises(DomainError) as error:
        account(session, books.company_id, "1209", parent_id=theirs.id)
    assert error.value.code == "coa.parent_not_found"
    session.rollback()


def test_an_unknown_parent_is_not_found(session: Session, books: Books) -> None:
    with pytest.raises(DomainError) as error:
        account(session, books.company_id, "1210", parent_id=uuid7())
    assert error.value.code == "coa.parent_not_found"
    session.rollback()


def test_a_group_with_children_stays_a_group(session: Session, books: Books) -> None:
    """R2.AC8"""
    group = account(session, books.company_id, "1211G", is_group=True)
    account(session, books.company_id, "1212", parent_id=group.id)
    session.commit()

    with pytest.raises(DomainError) as error:
        update_account(session, books.company_id, group.id, {"is_group": False})
    assert error.value.code == "coa.has_children"
    session.rollback()


def test_an_empty_group_can_become_a_posting_account(session: Session, books: Books) -> None:
    group = account(session, books.company_id, "1213G", is_group=True)
    session.commit()

    updated = update_account(session, books.company_id, group.id, {"is_group": False})
    session.commit()
    assert updated.is_group is False


class TestReadingTheChart:
    def test_the_tree_comes_back_in_code_order_with_depth(
        self, session: Session, empty_company
    ) -> None:
        """R2.AC7"""
        assets = account(session, empty_company.id, "1", name="Assets", is_group=True)
        current = account(
            session, empty_company.id, "11", name="Current", is_group=True, parent_id=assets.id
        )
        account(session, empty_company.id, "1120", name="Bank", parent_id=current.id)
        account(session, empty_company.id, "1110", name="Cash", parent_id=current.id)
        account(
            session,
            empty_company.id,
            "5",
            name="Expenses",
            type="expense",
            subtype="expense",
            is_group=True,
        )
        session.commit()

        chart = list_chart(session, empty_company.id)
        assert [(row.account.code, row.depth) for row in chart] == [
            ("1", 1),
            ("11", 2),
            ("1110", 3),
            ("1120", 3),
            ("5", 1),
        ]

    def test_archived_accounts_are_left_out_unless_asked_for(
        self, session: Session, empty_company
    ) -> None:
        """R3.AC6"""
        from app.coa.accounts import archive_account

        kept = account(session, empty_company.id, "1300")
        gone = account(session, empty_company.id, "1301")
        archive_account(session, empty_company.id, gone.id)
        session.commit()

        assert [row.account.code for row in list_chart(session, empty_company.id)] == [kept.code]
        both = list_chart(session, empty_company.id, include_archived=True)
        assert {row.account.code for row in both} == {"1300", "1301"}

    def test_searching_matches_code_or_name_in_either_language(
        self, session: Session, empty_company
    ) -> None:
        """R9.AC2 is the API's version of this."""
        account(session, empty_company.id, "1400", name="Bank Account", name_ar="حساب البنك")
        account(session, empty_company.id, "1401", name="Trade Receivable", subtype="receivable")
        session.commit()

        assert [
            row.account.code for row in list_chart(session, empty_company.id, search="bank")
        ] == ["1400"]
        assert [
            row.account.code for row in list_chart(session, empty_company.id, search="البنك")
        ] == ["1400"]
        assert [
            row.account.code for row in list_chart(session, empty_company.id, search="140")
        ] == ["1400", "1401"]

    def test_one_companys_chart_never_shows_another(
        self, session: Session, books: Books, empty_company
    ) -> None:
        account(session, empty_company.id, "9999", name="Theirs")
        session.commit()

        codes = {row.account.code for row in list_chart(session, books.company_id)}
        assert "9999" not in codes
