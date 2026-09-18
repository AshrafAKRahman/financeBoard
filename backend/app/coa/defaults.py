"""The company's default accounts: what posting uses when nobody says otherwise."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.coa.accounts import get_account
from app.ledger.api import LedgerSettings
from app.platform.audit.api import Actor, record
from app.shared.errors import DomainError

# Each default, and the account subtypes it may point at (R5.AC3).
DEFAULT_SUBTYPES: dict[str, tuple[str, ...]] = {
    "receivable": ("receivable",),
    "payable": ("payable",),
    "rounding": ("expense", "other_income"),
    "fx_gain": ("other_income", "income"),
    "fx_loss": ("expense",),
    "outstanding_receipts": ("current_asset", "bank_cash"),
    "outstanding_payments": ("current_liability", "bank_cash"),
    "suspense": ("current_asset", "current_liability"),
}

COLUMN_OF = {key: f"{key}_account_id" for key in DEFAULT_SUBTYPES}


@dataclass(frozen=True, slots=True)
class Defaults:
    accounts: dict[str, UUID | None]

    @property
    def missing(self) -> list[str]:
        """R5.AC7 — which defaults still need an account."""
        return sorted(key for key, account_id in self.accounts.items() if account_id is None)


def _settings(session: Session, company_id: UUID) -> LedgerSettings:
    settings = session.get(LedgerSettings, company_id)
    if settings is None:
        settings = LedgerSettings(company_id=company_id)
        session.add(settings)
        session.flush()
    return settings


def get_defaults(session: Session, company_id: UUID) -> Defaults:
    settings = _settings(session, company_id)
    return Defaults({key: getattr(settings, column) for key, column in COLUMN_OF.items()})


def set_default(
    session: Session,
    company_id: UUID,
    key: str,
    account_id: UUID | None,
    *,
    actor: Actor | None = None,
) -> Defaults:
    if key not in DEFAULT_SUBTYPES:
        raise DomainError("coa.unknown_default", f"{key!r} is not a company default")

    settings = _settings(session, company_id)
    code = None
    if account_id is not None:
        account = get_account(session, company_id, account_id)
        code = account.code
        if account.is_group:
            raise DomainError(
                "coa.group_account", f"{account.code} is a group account and cannot be posted to"
            )
        if not account.active:
            raise DomainError("coa.account_archived", f"{account.code} is archived")
        if account.subtype not in DEFAULT_SUBTYPES[key]:
            allowed = ", ".join(DEFAULT_SUBTYPES[key])
            raise DomainError(
                "coa.default_subtype_mismatch",
                f"the {key} default needs an account of subtype {allowed}, not {account.subtype}",
            )

    setattr(settings, COLUMN_OF[key], account_id)
    session.flush()
    record(
        session,
        action="company_default.set",
        actor=actor,
        company_id=company_id,
        target_type="company_default",
        target_id=key,
        detail={"default": key, "account": code},
    )
    return get_defaults(session, company_id)
