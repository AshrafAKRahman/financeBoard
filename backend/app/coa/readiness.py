"""Is this chart ready to keep books?

Answers the question an accountant would otherwise discover halfway through their first
invoice: which defaults are unset, which bank journals have no account, which groups are
empty, and which currencies have no rate.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.coa.defaults import get_defaults
from app.coa.journals import NEEDS_BANK_ACCOUNT, list_journals
from app.ledger.api import Account, ExchangeRate
from app.platform.tenancy.api import Company, Currency


@dataclass(frozen=True, slots=True)
class Finding:
    code: str
    message: str
    subject: str | None = None


def check(session: Session, company_id: UUID) -> Sequence[Finding]:
    findings: list[Finding] = []

    accounts = (
        session.execute(
            select(Account).where(Account.company_id == company_id, Account.active.is_(True))
        )
        .scalars()
        .all()
    )
    if not accounts:
        # Nothing else is worth reporting until there is a chart at all (R8.AC5).
        return [
            Finding(
                "coa.chart_empty",
                "this company has no accounts yet; load a chart template to start",
            )
        ]

    for key in get_defaults(session, company_id).missing:
        findings.append(
            Finding("coa.default_missing", f"the {key} default account is not set", key)
        )

    for journal in list_journals(session, company_id):
        if journal.type in NEEDS_BANK_ACCOUNT and journal.default_account_id is None:
            findings.append(
                Finding(
                    "coa.journal_without_account",
                    f"{journal.code} is a {journal.type} journal with no account",
                    journal.code,
                )
            )

    children = {account.parent_id for account in accounts if account.parent_id is not None}
    for account in accounts:
        if account.is_group and account.id not in children:
            findings.append(
                Finding("coa.group_without_children", f"{account.code} has no accounts under it",
                        account.code)
            )

    findings.extend(_currencies_without_rates(session, company_id))
    return findings


def _currencies_without_rates(session: Session, company_id: UUID) -> list[Finding]:
    """R8.AC4 — an active currency the company cannot convert is a gap waiting to bite."""
    company = session.get(Company, company_id)
    if company is None:
        return []

    with_rates = set(
        session.execute(
            select(ExchangeRate.currency_code).where(ExchangeRate.company_id == company_id)
        ).scalars()
    )
    active = session.execute(select(Currency.code).where(Currency.active.is_(True))).scalars()

    return [
        Finding("coa.currency_without_rate", f"{code} has no exchange rate", code)
        for code in sorted(active)
        if code != company.base_currency and code not in with_rates
    ]
