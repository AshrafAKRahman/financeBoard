"""Creating and editing accounts (R1)."""

import pytest
from sqlalchemy.orm import Session

from app.coa.accounts import AccountData, create_account, get_account, update_account
from app.ledger.api import PostingLine, PostingRequest, post
from app.shared.errors import DomainError
from tests.coa.conftest import account
from tests.factories import Books

pytestmark = pytest.mark.db


def test_an_account_is_created_with_its_details(session: Session, books: Books) -> None:
    """R1.AC1"""
    created = create_account(
        session,
        books.company_id,
        AccountData(
            code="1150",
            name="Petty Cash",
            name_ar="النقدية",
            type="asset",
            subtype="bank_cash",
            cash_flow_tag="operating",
        ),
    )
    session.commit()

    stored = get_account(session, books.company_id, created.id)
    assert (stored.code, stored.name, stored.name_ar) == ("1150", "Petty Cash", "النقدية")
    assert (stored.type, stored.subtype) == ("asset", "bank_cash")
    assert stored.active is True


def test_the_arabic_name_is_optional(session: Session, books: Books) -> None:
    """R1.AC2"""
    created = account(session, books.company_id, "1151")
    session.commit()
    assert created.name_ar is None


def test_renaming_keeps_the_code_type_and_subtype(session: Session, books: Books) -> None:
    """R1.AC3"""
    created = account(session, books.company_id, "1152", name="Old Name")
    session.commit()

    updated = update_account(
        session, books.company_id, created.id, {"name": "New Name", "name_ar": "اسم"}
    )
    session.commit()

    assert updated.name == "New Name"
    assert (updated.code, updated.type, updated.subtype) == ("1152", "asset", "current_asset")


def test_a_duplicate_code_is_refused(session: Session, books: Books) -> None:
    """R1.AC4"""
    account(session, books.company_id, "1153")
    session.commit()

    with pytest.raises(DomainError) as error:
        account(session, books.company_id, "1153")
    assert error.value.code == "coa.duplicate_code"
    session.rollback()


def test_the_same_code_in_another_company_is_fine(
    session: Session, books: Books, empty_company
) -> None:
    account(session, books.company_id, "1154")
    account(session, empty_company.id, "1154")
    session.commit()


@pytest.mark.parametrize(
    ("type_", "subtype"),
    [("asset", "payable"), ("income", "expense"), ("equity", "bank_cash"), ("asset", "nonsense")],
)
def test_a_subtype_must_belong_to_the_type(
    session: Session, books: Books, type_: str, subtype: str
) -> None:
    """R1.AC5"""
    with pytest.raises(DomainError) as error:
        account(session, books.company_id, "1155", type=type_, subtype=subtype)
    assert error.value.code == "coa.invalid_subtype"
    session.rollback()


@pytest.mark.parametrize(("code", "name"), [("", "Name"), ("1156", ""), ("   ", "Name")])
def test_a_code_and_a_name_are_required(
    session: Session, books: Books, code: str, name: str
) -> None:
    """R1.AC6"""
    with pytest.raises(DomainError) as error:
        create_account(
            session,
            books.company_id,
            AccountData(code=code, name=name, type="asset", subtype="current_asset"),
        )
    assert error.value.code == "coa.missing_field"
    session.rollback()


def test_open_item_accounts_are_made_reconcilable(session: Session, books: Books) -> None:
    """The ledger requires it, so the service does not leave it to the caller."""
    created = account(
        session, books.company_id, "1157", subtype="receivable", is_reconcilable=False
    )
    session.commit()
    assert created.is_reconcilable is True


def test_the_type_of_a_used_account_cannot_change(session: Session, books: Books) -> None:
    """R1.AC7"""
    from datetime import date
    from decimal import Decimal

    target = account(session, books.company_id, "1158", subtype="bank_cash")
    session.commit()

    post(
        session,
        PostingRequest(
            company_id=books.company_id,
            journal_id=books.journals["MISC"],
            date=date(2026, 3, 1),
            currency_code="SAR",
            lines=(
                PostingLine(target.id, debit=Decimal("10.00")),
                PostingLine(books.accounts["revenue"], credit=Decimal("10.00")),
            ),
        ),
    )
    session.commit()

    with pytest.raises(DomainError) as error:
        update_account(
            session, books.company_id, target.id, {"type": "expense", "subtype": "expense"}
        )
    assert error.value.code == "coa.account_in_use"
    session.rollback()


def test_an_unused_account_can_change_type(session: Session, books: Books) -> None:
    """R1.AC8"""
    created = account(session, books.company_id, "1159")
    session.commit()

    updated = update_account(
        session, books.company_id, created.id, {"type": "expense", "subtype": "expense"}
    )
    session.commit()
    assert (updated.type, updated.subtype) == ("expense", "expense")


def test_another_companys_account_is_not_found(
    session: Session, books: Books, empty_company
) -> None:
    created = account(session, books.company_id, "1160")
    session.commit()

    with pytest.raises(DomainError) as error:
        get_account(session, empty_company.id, created.id)
    assert error.value.code == "coa.account_not_found"


def test_creating_and_updating_are_audited(session: Session, books: Books) -> None:
    """R9.AC8 is the API's version; the service is what records it."""
    from sqlalchemy import text

    created = account(session, books.company_id, "1161")
    update_account(session, books.company_id, created.id, {"name": "Renamed"})
    session.commit()

    actions = (
        session.execute(
            text("SELECT action FROM audit_log WHERE target_id = :id ORDER BY at"),
            {"id": str(created.id)},
        )
        .scalars()
        .all()
    )
    assert actions == ["account.created", "account.updated"]
