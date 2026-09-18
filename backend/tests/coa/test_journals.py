"""Journals (R4)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.coa.journals import (
    JournalData,
    archive_journal,
    create_journal,
    list_journals,
    update_journal,
)
from app.ledger.api import PostingLine, PostingRequest, post
from app.shared.errors import DomainError
from tests.coa.conftest import account
from tests.factories import Books

pytestmark = pytest.mark.db


def make_journal(session: Session, company_id, code: str, **kwargs):
    return create_journal(
        session,
        company_id,
        JournalData(
            code=code,
            name=kwargs.pop("name", f"Journal {code}"),
            type=kwargs.pop("type", "general"),
            **kwargs,
        ),
    )


def test_a_journal_is_created(session: Session, books: Books) -> None:
    """R4.AC1"""
    journal = make_journal(session, books.company_id, "SAL2", name="Sales 2", type="sales")
    session.commit()
    assert (journal.code, journal.type, journal.active) == ("SAL2", "sales", True)


def test_listing_returns_active_journals_in_code_order(session: Session, books: Books) -> None:
    """R4.AC1"""
    codes = [journal.code for journal in list_journals(session, books.company_id)]
    assert codes == sorted(codes)
    assert {"MISC", "INV", "BNK"} <= set(codes)


@pytest.mark.parametrize("type_", ["bank", "cash"])
def test_bank_and_cash_journals_need_a_bank_account(
    session: Session, books: Books, type_: str
) -> None:
    """R4.AC2"""
    with pytest.raises(DomainError) as error:
        make_journal(session, books.company_id, f"{type_.upper()[:3]}2", type=type_)
    assert error.value.code == "coa.default_account_required"
    session.rollback()

    ok = make_journal(
        session,
        books.company_id,
        f"{type_.upper()[:3]}3",
        type=type_,
        default_account_id=books.accounts["bank"],
    )
    session.commit()
    assert ok.default_account_id == books.accounts["bank"]


def test_a_bank_journal_refuses_a_non_bank_account(session: Session, books: Books) -> None:
    with pytest.raises(DomainError) as error:
        make_journal(
            session,
            books.company_id,
            "BNK4",
            type="bank",
            default_account_id=books.accounts["revenue"],
        )
    assert error.value.code == "coa.default_subtype_mismatch"
    session.rollback()


def test_a_duplicate_code_is_refused(session: Session, books: Books) -> None:
    """R4.AC3"""
    with pytest.raises(DomainError) as error:
        make_journal(session, books.company_id, "MISC")
    assert error.value.code == "coa.duplicate_code"
    session.rollback()


@pytest.mark.parametrize("code", ["TOOLONGCODE", "WITH SPACE", "", "MI-SC"])
def test_the_code_shape_is_enforced(session: Session, books: Books, code: str) -> None:
    """R4.AC4"""
    with pytest.raises(DomainError) as error:
        make_journal(session, books.company_id, code)
    assert error.value.code in {"coa.invalid_journal_code", "coa.missing_field"}
    session.rollback()


def test_a_lower_case_code_is_accepted_and_upper_cased(session: Session, books: Books) -> None:
    """Typing is forgiving; storage is not: codes are always upper case."""
    journal = make_journal(session, books.company_id, "cash9", type="general")
    session.commit()
    assert journal.code == "CASH9"


def test_the_code_of_a_used_journal_cannot_change(session: Session, books: Books) -> None:
    """R4.AC5"""
    post(
        session,
        PostingRequest(
            company_id=books.company_id,
            journal_id=books.journals["MISC"],
            date=date(2026, 3, 1),
            currency_code="SAR",
            lines=(
                PostingLine(books.accounts["expense"], debit=Decimal("5.00")),
                PostingLine(books.accounts["bank"], credit=Decimal("5.00")),
            ),
        ),
    )
    session.commit()

    with pytest.raises(DomainError) as error:
        update_journal(session, books.company_id, books.journals["MISC"], {"code": "GEN"})
    assert error.value.code == "coa.journal_in_use"
    session.rollback()


def test_an_unused_journal_can_be_renamed_and_recoded(session: Session, books: Books) -> None:
    journal = make_journal(session, books.company_id, "TMP")
    session.commit()

    updated = update_journal(
        session, books.company_id, journal.id, {"code": "TMP2", "name": "Renamed"}
    )
    session.commit()
    assert (updated.code, updated.name) == ("TMP2", "Renamed")


def test_archiving_keeps_entries_and_stops_new_ones(session: Session, books: Books) -> None:
    """R4.AC6"""
    journal = make_journal(session, books.company_id, "OLD")
    session.commit()
    archive_journal(session, books.company_id, journal.id)
    session.commit()

    assert journal.code not in {j.code for j in list_journals(session, books.company_id)}
    with pytest.raises(DomainError) as error:
        post(
            session,
            PostingRequest(
                company_id=books.company_id,
                journal_id=journal.id,
                date=date(2026, 3, 1),
                currency_code="SAR",
                lines=(
                    PostingLine(books.accounts["expense"], debit=Decimal("1.00")),
                    PostingLine(books.accounts["bank"], credit=Decimal("1.00")),
                ),
            ),
        )
    assert error.value.code == "ledger.journal_inactive"
    session.rollback()


def test_a_default_account_from_another_company_is_refused(
    session: Session, books: Books, empty_company
) -> None:
    """R4.AC7"""
    theirs = account(session, empty_company.id, "1119", subtype="bank_cash")
    session.commit()

    with pytest.raises(DomainError) as error:
        make_journal(session, books.company_id, "BNK9", type="bank", default_account_id=theirs.id)
    assert error.value.code == "coa.account_not_found"
    session.rollback()
