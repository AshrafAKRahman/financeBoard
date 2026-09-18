"""Journals: how documents are grouped and numbered."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.coa.accounts import get_account
from app.ledger.api import JOURNAL_TYPES, Journal, JournalEntry
from app.platform.audit.api import Actor, record
from app.shared.errors import DomainError
from app.shared.ids import uuid7

JOURNAL_CODE = re.compile(r"^[A-Z0-9]{1,8}$")
NEEDS_BANK_ACCOUNT = ("bank", "cash")


@dataclass(frozen=True, slots=True)
class JournalData:
    code: str
    name: str
    type: str
    default_account_id: UUID | None = None
    currency_code: str | None = None


def get_journal(session: Session, company_id: UUID, journal_id: UUID) -> Journal:
    journal = session.execute(
        select(Journal).where(Journal.id == journal_id, Journal.company_id == company_id)
    ).scalar_one_or_none()
    if journal is None:
        raise DomainError("coa.journal_not_found", f"journal {journal_id} not found")
    return journal


def list_journals(
    session: Session, company_id: UUID, *, include_archived: bool = False
) -> Sequence[Journal]:
    query = select(Journal).where(Journal.company_id == company_id)
    if not include_archived:
        query = query.where(Journal.active.is_(True))
    return session.execute(query.order_by(Journal.code)).scalars().all()


def has_entries(session: Session, journal_id: UUID) -> bool:
    return bool(
        session.execute(
            select(func.count())
            .select_from(JournalEntry)
            .where(JournalEntry.journal_id == journal_id)
        ).scalar_one()
    )


def _check_default_account(
    session: Session, company_id: UUID, type_: str, account_id: UUID | None
) -> None:
    if account_id is None:
        if type_ in NEEDS_BANK_ACCOUNT:
            raise DomainError(
                "coa.default_account_required",
                f"a {type_} journal needs a bank or cash account",
            )
        return

    account = get_account(session, company_id, account_id)
    if type_ in NEEDS_BANK_ACCOUNT and account.subtype != "bank_cash":
        raise DomainError(
            "coa.default_subtype_mismatch",
            f"a {type_} journal needs an account of subtype bank_cash, not {account.subtype}",
        )
    if account.is_group:
        raise DomainError("coa.group_account", f"{account.code} is a group account")


def create_journal(
    session: Session, company_id: UUID, data: JournalData, *, actor: Actor | None = None
) -> Journal:
    code = data.code.strip().upper()
    name = data.name.strip()
    if not code or not name:
        raise DomainError("coa.missing_field", "a journal needs a code and a name")
    if not JOURNAL_CODE.fullmatch(code):
        raise DomainError(
            "coa.invalid_journal_code",
            "a journal code is one to eight upper-case letters or digits",
        )
    if data.type not in JOURNAL_TYPES:
        raise DomainError("coa.invalid_journal_type", f"{data.type!r} is not a journal type")
    if session.execute(
        select(Journal.id).where(Journal.company_id == company_id, Journal.code == code)
    ).scalar_one_or_none():
        raise DomainError("coa.duplicate_code", f"journal code {code} is already used")

    _check_default_account(session, company_id, data.type, data.default_account_id)

    journal = Journal(
        id=uuid7(),
        company_id=company_id,
        code=code,
        name=name,
        type=data.type,
        default_account_id=data.default_account_id,
        currency_code=data.currency_code,
    )
    session.add(journal)
    session.flush()
    record(
        session,
        action="journal.created",
        actor=actor,
        company_id=company_id,
        target_type="journal",
        target_id=journal.id,
        detail={"code": journal.code, "type": journal.type},
    )
    return journal


def update_journal(
    session: Session,
    company_id: UUID,
    journal_id: UUID,
    changes: dict[str, Any],
    *,
    actor: Actor | None = None,
) -> Journal:
    journal = get_journal(session, company_id, journal_id)

    if "code" in changes:
        code = str(changes["code"]).strip().upper()
        if code != journal.code:
            if has_entries(session, journal_id):
                raise DomainError(
                    "coa.journal_in_use",
                    f"{journal.code} already has posted entries, so its code cannot change",
                )
            if not JOURNAL_CODE.fullmatch(code):
                raise DomainError(
                    "coa.invalid_journal_code",
                    "a journal code is one to eight upper-case letters or digits",
                )
            if session.execute(
                select(Journal.id).where(
                    Journal.company_id == company_id, Journal.code == code, Journal.id != journal_id
                )
            ).scalar_one_or_none():
                raise DomainError("coa.duplicate_code", f"journal code {code} is already used")
            journal.code = code

    if "name" in changes:
        name = str(changes["name"]).strip()
        if not name:
            raise DomainError("coa.missing_field", "a journal needs a name")
        journal.name = name

    if "default_account_id" in changes:
        _check_default_account(session, company_id, journal.type, changes["default_account_id"])
        journal.default_account_id = changes["default_account_id"]

    journal.updated_at = datetime.now(UTC)
    session.flush()
    record(
        session,
        action="journal.updated",
        actor=actor,
        company_id=company_id,
        target_type="journal",
        target_id=journal.id,
        detail={"code": journal.code, "changed": sorted(changes)},
    )
    return journal


def archive_journal(
    session: Session, company_id: UUID, journal_id: UUID, *, actor: Actor | None = None
) -> Journal:
    """Posted entries stay; the ledger already refuses to post to an archived journal."""
    journal = get_journal(session, company_id, journal_id)
    journal.active = False
    journal.updated_at = datetime.now(UTC)
    session.flush()
    record(
        session,
        action="journal.archived",
        actor=actor,
        company_id=company_id,
        target_type="journal",
        target_id=journal.id,
        detail={"code": journal.code},
    )
    return journal
