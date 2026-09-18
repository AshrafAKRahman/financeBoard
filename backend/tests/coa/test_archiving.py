"""Archive rather than delete, once an account matters (R3)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.coa.accounts import archive_account, delete_account, get_account, restore_account
from app.ledger.api import PostingLine, PostingRequest, post
from app.shared.errors import DomainError
from tests.coa.conftest import account
from tests.factories import Books

pytestmark = pytest.mark.db


def post_to(session: Session, books: Books, account_id) -> None:
    post(
        session,
        PostingRequest(
            company_id=books.company_id,
            journal_id=books.journals["MISC"],
            date=date(2026, 3, 1),
            currency_code="SAR",
            lines=(
                PostingLine(account_id, debit=Decimal("25.00")),
                PostingLine(books.accounts["revenue"], credit=Decimal("25.00")),
            ),
        ),
    )


def test_archiving_keeps_the_account_and_its_lines(session: Session, books: Books) -> None:
    """R3.AC1"""
    target = account(session, books.company_id, "1310", subtype="bank_cash")
    session.commit()
    post_to(session, books, target.id)
    session.commit()

    archive_account(session, books.company_id, target.id)
    session.commit()

    stored = get_account(session, books.company_id, target.id)
    assert stored.active is False
    lines = session.execute(
        text("SELECT count(*) FROM journal_entry_line WHERE account_id = :id"), {"id": target.id}
    ).scalar_one()
    assert lines == 1


def test_an_archived_account_takes_no_new_postings(session: Session, books: Books) -> None:
    """R3.AC2 — enforced by the database, so no code path can slip past it."""
    target = account(session, books.company_id, "1311", subtype="bank_cash")
    archive_account(session, books.company_id, target.id)
    session.commit()

    with pytest.raises(DomainError) as error:
        post_to(session, books, target.id)
    assert error.value.code == "coa.account_archived"
    session.rollback()


def test_restoring_lets_it_post_again(session: Session, books: Books) -> None:
    target = account(session, books.company_id, "1312", subtype="bank_cash")
    archive_account(session, books.company_id, target.id)
    session.commit()

    restore_account(session, books.company_id, target.id)
    session.commit()
    post_to(session, books, target.id)
    session.commit()


def test_a_used_account_cannot_be_deleted(session: Session, books: Books) -> None:
    """R3.AC3"""
    target = account(session, books.company_id, "1313", subtype="bank_cash")
    session.commit()
    post_to(session, books, target.id)
    session.commit()

    with pytest.raises(DomainError) as error:
        delete_account(session, books.company_id, target.id)
    assert error.value.code == "coa.account_in_use"
    session.rollback()


def test_an_unused_account_can_be_deleted(session: Session, books: Books) -> None:
    """R3.AC4"""
    target = account(session, books.company_id, "1314")
    session.commit()

    delete_account(session, books.company_id, target.id)
    session.commit()

    with pytest.raises(DomainError) as error:
        get_account(session, books.company_id, target.id)
    assert error.value.code == "coa.account_not_found"


def test_a_default_account_cannot_be_archived_or_deleted(
    session: Session, books: Books
) -> None:
    """R3.AC5"""
    from app.coa.defaults import set_default

    target = account(session, books.company_id, "1315", subtype="receivable")
    set_default(session, books.company_id, "receivable", target.id)
    session.commit()

    for call in (archive_account, delete_account):
        with pytest.raises(DomainError) as error:
            call(session, books.company_id, target.id)
        assert error.value.code == "coa.account_is_default"
        session.rollback()


def test_an_account_with_children_cannot_be_deleted(session: Session, books: Books) -> None:
    group = account(session, books.company_id, "1316G", is_group=True)
    account(session, books.company_id, "1317", parent_id=group.id)
    session.commit()

    with pytest.raises(DomainError) as error:
        delete_account(session, books.company_id, group.id)
    assert error.value.code == "coa.has_children"
    session.rollback()


def test_archiving_is_audited(session: Session, books: Books) -> None:
    target = account(session, books.company_id, "1318")
    archive_account(session, books.company_id, target.id)
    session.commit()

    actions = (
        session.execute(
            text("SELECT action FROM audit_log WHERE target_id = :id ORDER BY at"),
            {"id": str(target.id)},
        )
        .scalars()
        .all()
    )
    assert actions == ["account.created", "account.archived"]
