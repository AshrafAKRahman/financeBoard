"""Managing the chart: creating accounts, moving them, archiving them, reading the tree.

The database enforces the hierarchy rules too (migration 0003); these checks run first so
an accountant gets a sentence rather than a constraint name.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.ledger.api import ACCOUNT_SUBTYPES, Account, JournalEntryLine, LedgerSettings
from app.platform.audit.api import Actor, record
from app.shared.errors import DomainError
from app.shared.ids import uuid7

RECONCILABLE_SUBTYPES = ("receivable", "payable")
DEFAULT_COLUMNS = (
    "receivable_account_id",
    "payable_account_id",
    "rounding_account_id",
    "fx_gain_account_id",
    "fx_loss_account_id",
    "outstanding_receipts_account_id",
    "outstanding_payments_account_id",
    "suspense_account_id",
)


@dataclass(frozen=True, slots=True)
class AccountData:
    code: str
    name: str
    type: str
    subtype: str
    name_ar: str | None = None
    parent_id: UUID | None = None
    is_group: bool = False
    is_reconcilable: bool = False
    cash_flow_tag: str | None = None


@dataclass(frozen=True, slots=True)
class ChartRow:
    account: Account
    depth: int


def now() -> datetime:
    return datetime.now(UTC)


def get_account(session: Session, company_id: UUID, account_id: UUID) -> Account:
    """Another company's account is reported as missing, so ids cannot be probed."""
    account = session.execute(
        select(Account).where(Account.id == account_id, Account.company_id == company_id)
    ).scalar_one_or_none()
    if account is None:
        raise DomainError("coa.account_not_found", f"account {account_id} not found")
    return account


def has_lines(session: Session, account_id: UUID) -> bool:
    return bool(
        session.execute(
            select(func.count())
            .select_from(JournalEntryLine)
            .where(JournalEntryLine.account_id == account_id)
        ).scalar_one()
    )


def has_children(session: Session, account_id: UUID) -> bool:
    return bool(
        session.execute(
            select(func.count()).select_from(Account).where(Account.parent_id == account_id)
        ).scalar_one()
    )


def is_a_default(session: Session, company_id: UUID, account_id: UUID) -> bool:
    settings = session.get(LedgerSettings, company_id)
    if settings is None:
        return False
    return any(getattr(settings, column) == account_id for column in DEFAULT_COLUMNS)


def validate_subtype(type_: str, subtype: str) -> None:
    if type_ not in ACCOUNT_SUBTYPES:
        raise DomainError("coa.invalid_subtype", f"{type_!r} is not an account type")
    if subtype not in ACCOUNT_SUBTYPES[type_]:
        allowed = ", ".join(ACCOUNT_SUBTYPES[type_])
        raise DomainError(
            "coa.invalid_subtype", f"{subtype!r} is not a {type_} subtype; use one of {allowed}"
        )


def _check_code_is_free(
    session: Session, company_id: UUID, code: str, *, except_id: UUID | None = None
) -> None:
    query = select(Account.id).where(Account.company_id == company_id, Account.code == code)
    if except_id is not None:
        query = query.where(Account.id != except_id)
    if session.execute(query).scalar_one_or_none() is not None:
        raise DomainError("coa.duplicate_code", f"account code {code} is already used")


def _check_parent(
    session: Session, company_id: UUID, parent_id: UUID | None, type_: str, account_id: UUID | None
) -> None:
    if parent_id is None:
        return

    parent = session.execute(
        select(Account).where(Account.id == parent_id, Account.company_id == company_id)
    ).scalar_one_or_none()
    if parent is None:
        raise DomainError("coa.parent_not_found", f"parent account {parent_id} not found")
    if not parent.is_group:
        raise DomainError("coa.parent_not_group", f"{parent.code} is not a group account")
    if parent.type != type_:
        raise DomainError(
            "coa.parent_type_mismatch", f"{parent.code} is a {parent.type} account, not {type_}"
        )
    if account_id is not None and _is_descendant(session, parent_id, account_id):
        raise DomainError(
            "coa.hierarchy_cycle", "that parent sits under this account, which would loop"
        )


def _is_descendant(session: Session, candidate_id: UUID, account_id: UUID) -> bool:
    """True when candidate is the account itself or one of its descendants."""
    if candidate_id == account_id:
        return True
    found = session.execute(
        text(
            """
            WITH RECURSIVE ancestors(id, parent_id, depth) AS (
                SELECT id, parent_id, 1 FROM account WHERE id = :candidate
                UNION ALL
                SELECT a.id, a.parent_id, ancestors.depth + 1
                FROM account a JOIN ancestors ON a.id = ancestors.parent_id
                WHERE ancestors.depth < 20
            )
            SELECT 1 FROM ancestors WHERE id = :account LIMIT 1
            """
        ),
        {"candidate": candidate_id, "account": account_id},
    ).scalar_one_or_none()
    return found is not None


def create_account(
    session: Session, company_id: UUID, data: AccountData, *, actor: Actor | None = None
) -> Account:
    code = data.code.strip()
    name = data.name.strip()
    if not code or not name:
        raise DomainError("coa.missing_field", "an account needs a code and a name")

    validate_subtype(data.type, data.subtype)
    _check_code_is_free(session, company_id, code)
    _check_parent(session, company_id, data.parent_id, data.type, None)

    account = Account(
        id=uuid7(),
        company_id=company_id,
        code=code,
        name=name,
        name_ar=(data.name_ar or None),
        type=data.type,
        subtype=data.subtype,
        parent_id=data.parent_id,
        is_group=data.is_group,
        # The ledger requires open-item accounts to be reconcilable, so this is not a choice.
        is_reconcilable=data.is_reconcilable or data.subtype in RECONCILABLE_SUBTYPES,
        cash_flow_tag=data.cash_flow_tag,
    )
    session.add(account)
    session.flush()

    record(
        session,
        action="account.created",
        actor=actor,
        company_id=company_id,
        target_type="account",
        target_id=account.id,
        detail={"code": account.code, "name": account.name},
    )
    return account


def update_account(
    session: Session,
    company_id: UUID,
    account_id: UUID,
    changes: dict[str, Any],
    *,
    actor: Actor | None = None,
) -> Account:
    account = get_account(session, company_id, account_id)
    in_use = has_lines(session, account_id)

    if "code" in changes or "name" in changes:
        code = str(changes.get("code", account.code)).strip()
        name = str(changes.get("name", account.name)).strip()
        if not code or not name:
            raise DomainError("coa.missing_field", "an account needs a code and a name")
        if code != account.code:
            _check_code_is_free(session, company_id, code, except_id=account_id)
        account.code, account.name = code, name

    if "name_ar" in changes:
        account.name_ar = changes["name_ar"] or None

    type_ = changes.get("type", account.type)
    subtype = changes.get("subtype", account.subtype)
    if type_ != account.type or subtype != account.subtype:
        if in_use:
            raise DomainError(
                "coa.account_in_use",
                f"{account.code} already has journal lines, so its type cannot change",
            )
        validate_subtype(type_, subtype)
        account.type, account.subtype = type_, subtype
        if subtype in RECONCILABLE_SUBTYPES:
            account.is_reconcilable = True

    if "parent_id" in changes:
        parent_id = changes["parent_id"]
        _check_parent(session, company_id, parent_id, account.type, account_id)
        account.parent_id = parent_id

    if "is_group" in changes and bool(changes["is_group"]) != account.is_group:
        if changes["is_group"]:
            if in_use:
                raise DomainError(
                    "coa.account_in_use",
                    f"{account.code} has journal lines and cannot become a group account",
                )
        elif has_children(session, account_id):
            raise DomainError(
                "coa.has_children", f"{account.code} has child accounts, so it stays a group"
            )
        account.is_group = bool(changes["is_group"])

    if "is_reconcilable" in changes and account.subtype not in RECONCILABLE_SUBTYPES:
        account.is_reconcilable = bool(changes["is_reconcilable"])
    if "cash_flow_tag" in changes:
        account.cash_flow_tag = changes["cash_flow_tag"] or None

    account.updated_at = now()
    session.flush()

    record(
        session,
        action="account.updated",
        actor=actor,
        company_id=company_id,
        target_type="account",
        target_id=account.id,
        detail={"code": account.code, "changed": sorted(changes)},
    )
    return account


def archive_account(
    session: Session, company_id: UUID, account_id: UUID, *, actor: Actor | None = None
) -> Account:
    """Keeps the account and its history; only new postings are refused (R3.AC1)."""
    account = get_account(session, company_id, account_id)
    if is_a_default(session, company_id, account_id):
        raise DomainError(
            "coa.account_is_default",
            f"{account.code} is a company default; point the default elsewhere first",
        )

    account.active = False
    account.updated_at = now()
    session.flush()
    record(
        session,
        action="account.archived",
        actor=actor,
        company_id=company_id,
        target_type="account",
        target_id=account.id,
        detail={"code": account.code},
    )
    return account


def restore_account(
    session: Session, company_id: UUID, account_id: UUID, *, actor: Actor | None = None
) -> Account:
    account = get_account(session, company_id, account_id)
    account.active = True
    account.updated_at = now()
    session.flush()
    record(
        session,
        action="account.restored",
        actor=actor,
        company_id=company_id,
        target_type="account",
        target_id=account.id,
        detail={"code": account.code},
    )
    return account


def delete_account(
    session: Session, company_id: UUID, account_id: UUID, *, actor: Actor | None = None
) -> None:
    """Only an account that has never been used and nothing points at (R3.AC4)."""
    account = get_account(session, company_id, account_id)
    if has_lines(session, account_id):
        raise DomainError(
            "coa.account_in_use", f"{account.code} has journal lines; archive it instead"
        )
    if is_a_default(session, company_id, account_id):
        raise DomainError("coa.account_is_default", f"{account.code} is a company default")
    if has_children(session, account_id):
        raise DomainError("coa.has_children", f"{account.code} has child accounts")

    code = account.code
    session.delete(account)
    session.flush()
    record(
        session,
        action="account.deleted",
        actor=actor,
        company_id=company_id,
        target_type="account",
        target_id=account_id,
        detail={"code": code},
    )


def list_chart(
    session: Session,
    company_id: UUID,
    *,
    include_archived: bool = False,
    search: str | None = None,
) -> Sequence[ChartRow]:
    """The tree in one query: each account with its depth, in code order within its parent."""
    rows = session.execute(
        text(
            """
            WITH RECURSIVE tree AS (
                SELECT a.id, 1 AS depth, a.code::text AS path
                FROM account a
                WHERE a.company_id = :company AND a.parent_id IS NULL
                UNION ALL
                SELECT a.id, tree.depth + 1, tree.path || '/' || a.code
                FROM account a JOIN tree ON a.parent_id = tree.id
                WHERE a.company_id = :company AND tree.depth < 20
            )
            SELECT id, depth FROM tree ORDER BY path
            """
        ),
        {"company": company_id},
    ).all()

    accounts = {
        account.id: account
        for account in session.execute(
            select(Account).where(Account.company_id == company_id)
        ).scalars()
    }

    chart = [ChartRow(accounts[row.id], row.depth) for row in rows if row.id in accounts]
    if not include_archived:
        chart = [row for row in chart if row.account.active]
    if search:
        needle = search.strip().lower()
        chart = [
            row
            for row in chart
            if needle in row.account.code.lower()
            or needle in row.account.name.lower()
            or needle in (row.account.name_ar or "").lower()
        ]
    return chart
