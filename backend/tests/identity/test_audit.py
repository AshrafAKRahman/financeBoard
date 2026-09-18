"""The audit writer: what it records, and what it refuses to record (R8)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.platform.audit import api as audit
from app.platform.audit.api import Actor
from app.platform.tenancy.api import Company
from app.shared.errors import DomainError
from app.shared.ids import uuid7

pytestmark = pytest.mark.db


@pytest.fixture
def company(session: Session) -> Company:
    company = Company(id=uuid7(), name="Audit Co", base_currency="SAR")
    session.add(company)
    session.commit()
    return company


def test_a_record_keeps_the_actor_action_and_target(session: Session, company: Company) -> None:
    """R8.AC2"""
    actor = Actor(user_id=None, email="admin@example.sa")
    target = uuid7()
    entry = audit.record(
        session,
        action="role.granted",
        actor=actor,
        company_id=company.id,
        target_type="user",
        target_id=target,
        detail={"role": "Administrator"},
    )
    session.commit()

    assert entry.actor_email == "admin@example.sa"
    assert entry.action == "role.granted"
    assert (entry.target_type, entry.target_id) == ("user", str(target))
    assert entry.detail == {"role": "Administrator"}
    assert entry.at is not None


@pytest.mark.parametrize(
    "detail",
    [
        {"password": "hunter2"},
        {"token": "abc"},
        {"session_token": "abc"},
        {"password_hash": "$argon2id$"},
        {"api_secret": "x"},
        {"credential": "x"},
        {"nested": {"reset_token": "x"}},
    ],
)
def test_secrets_are_refused(session: Session, detail: dict) -> None:
    """R8.AC4 and R11.AC12 — the writer will not store anything secret-shaped."""
    with pytest.raises(DomainError) as error:
        audit.record(session, action="test.event", detail=detail)
    assert error.value.code == "audit.secret_in_detail"
    session.rollback()


def test_ordinary_details_are_allowed(session: Session) -> None:
    entry = audit.record(
        session, action="test.event", detail={"email": "a@example.sa", "origin": "https://x"}
    )
    session.commit()
    assert entry.detail["email"] == "a@example.sa"


def test_a_company_log_comes_back_newest_first(session: Session, company: Company) -> None:
    """R8.AC5"""
    for index in range(3):
        audit.record(session, action=f"test.event.{index}", company_id=company.id)
        session.commit()

    entries = audit.read_company_log(session, company.id)
    assert [entry.action for entry in entries][:3] == [
        "test.event.2",
        "test.event.1",
        "test.event.0",
    ]


def test_a_company_log_shows_only_its_own_records(session: Session, company: Company) -> None:
    other = Company(id=uuid7(), name="Other Co", base_currency="SAR")
    session.add(other)
    audit.record(session, action="ours", company_id=company.id)
    audit.record(session, action="theirs", company_id=other.id)
    session.commit()

    assert [entry.action for entry in audit.read_company_log(session, company.id)] == ["ours"]


def test_the_log_can_be_paged_backwards(session: Session, company: Company) -> None:
    for index in range(5):
        audit.record(session, action=f"page.{index}", company_id=company.id)
        session.commit()

    first_page = audit.read_company_log(session, company.id, limit=2)
    second_page = audit.read_company_log(session, company.id, limit=2, before=first_page[-1].at)

    assert [entry.action for entry in first_page] == ["page.4", "page.3"]
    assert next(entry.action for entry in second_page) == "page.2"


def test_records_cannot_be_changed_or_removed(session: Session, company: Company) -> None:
    """R8.AC3 — the database refuses, whatever the application tries."""
    entry = audit.record(session, action="permanent.event", company_id=company.id)
    session.commit()

    for statement in (
        "UPDATE audit_log SET action = 'edited' WHERE id = :id",
        "DELETE FROM audit_log WHERE id = :id",
    ):
        with pytest.raises(Exception) as error:  # the DBAPI error type varies
            session.execute(text(statement), {"id": entry.id})
            session.commit()
        assert "audit.append_only" in str(error.value)
        session.rollback()


def test_old_records_are_kept(session: Session, company: Company) -> None:
    """Nothing prunes the log: it is the evidence trail."""
    entry = audit.record(session, action="old.event", company_id=company.id)
    session.commit()
    assert audit.read_company_log(session, company.id, before=datetime.now(UTC) + timedelta(1))
    assert session.get(type(entry), entry.id) is not None
