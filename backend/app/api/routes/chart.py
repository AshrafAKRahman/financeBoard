"""The chart of accounts over HTTP.

Everything is company-scoped, so identity's dependency does the work of deciding whether
this caller may touch this company at all.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import CallerDep, SessionDep, requires
from app.api.protection import needs
from app.billing.taxes import install_saudi_taxes
from app.coa import accounts as accounts_service
from app.coa import defaults as defaults_service
from app.coa import journals as journals_service
from app.coa import rates as rates_service
from app.coa import readiness as readiness_service
from app.coa import templates as templates_service
from app.platform.audit.api import Actor

router = APIRouter(prefix="/api/v1/companies/{company_id}", tags=["chart of accounts"])


# --------------------------------------------------------------------------- schemas


class AccountIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=200)
    type: str
    subtype: str
    name_ar: str | None = None
    parent_id: UUID | None = None
    is_group: bool = False
    is_reconcilable: bool = False
    cash_flow_tag: str | None = None


class AccountPatch(BaseModel):
    code: str | None = None
    name: str | None = None
    name_ar: str | None = None
    type: str | None = None
    subtype: str | None = None
    parent_id: UUID | None = None
    is_group: bool | None = None
    is_reconcilable: bool | None = None
    cash_flow_tag: str | None = None


class AccountOut(BaseModel):
    id: UUID
    code: str
    name: str
    name_ar: str | None
    type: str
    subtype: str
    parent_id: UUID | None
    is_group: bool
    is_reconcilable: bool
    cash_flow_tag: str | None
    active: bool
    depth: int = 1


class JournalIn(BaseModel):
    code: str = Field(min_length=1, max_length=8)
    name: str = Field(min_length=1, max_length=200)
    type: str
    default_account_id: UUID | None = None
    currency_code: str | None = None


class JournalPatch(BaseModel):
    code: str | None = None
    name: str | None = None
    default_account_id: UUID | None = None


class JournalOut(BaseModel):
    id: UUID
    code: str
    name: str
    type: str
    default_account_id: UUID | None
    currency_code: str | None
    active: bool


class DefaultIn(BaseModel):
    account_id: UUID | None = None


class DefaultsOut(BaseModel):
    accounts: dict[str, UUID | None]
    missing: list[str]


class TemplateOut(BaseModel):
    key: str
    name: str
    description: str


class TemplateLoadedOut(BaseModel):
    accounts: int
    journals: int
    defaults: int
    taxes: int


class RateIn(BaseModel):
    currency_code: str
    rate_date: date
    rate: Decimal


class RateOut(BaseModel):
    id: UUID
    currency_code: str
    rate_date: date
    rate: Decimal


class RateImportOut(BaseModel):
    recorded: int
    rejected: list[dict]


class FindingOut(BaseModel):
    code: str
    message: str
    subject: str | None


def _actor(caller: CallerDep) -> Actor:
    return Actor(caller.user_id, caller.email)


def _account_out(account, depth: int = 1) -> AccountOut:
    return AccountOut(
        id=account.id,
        code=account.code,
        name=account.name,
        name_ar=account.name_ar,
        type=account.type,
        subtype=account.subtype,
        parent_id=account.parent_id,
        is_group=account.is_group,
        is_reconcilable=account.is_reconcilable,
        cash_flow_tag=account.cash_flow_tag,
        active=account.active,
        depth=depth,
    )


# -------------------------------------------------------------------------- accounts


@router.get("/accounts", response_model=list[AccountOut], dependencies=[requires("account:read")])
@needs("account:read")
def list_accounts(
    company_id: UUID,
    session: SessionDep,
    include_archived: bool = False,
    search: str | None = None,
) -> list[AccountOut]:
    rows = accounts_service.list_chart(
        session, company_id, include_archived=include_archived, search=search
    )
    return [_account_out(row.account, row.depth) for row in rows]


@router.post(
    "/accounts",
    response_model=AccountOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[requires("account:manage")],
)
@needs("account:manage")
def create_account(
    company_id: UUID, body: AccountIn, caller: CallerDep, session: SessionDep
) -> AccountOut:
    account = accounts_service.create_account(
        session,
        company_id,
        accounts_service.AccountData(**body.model_dump()),
        actor=_actor(caller),
    )
    return _account_out(account)


@router.patch(
    "/accounts/{account_id}",
    response_model=AccountOut,
    dependencies=[requires("account:manage")],
)
@needs("account:manage")
def update_account(
    company_id: UUID,
    account_id: UUID,
    body: AccountPatch,
    caller: CallerDep,
    session: SessionDep,
) -> AccountOut:
    changes = body.model_dump(exclude_unset=True)
    account = accounts_service.update_account(
        session, company_id, account_id, changes, actor=_actor(caller)
    )
    return _account_out(account)


@router.post(
    "/accounts/{account_id}/archive",
    response_model=AccountOut,
    dependencies=[requires("account:manage")],
)
@needs("account:manage")
def archive_account(
    company_id: UUID, account_id: UUID, caller: CallerDep, session: SessionDep
) -> AccountOut:
    return _account_out(
        accounts_service.archive_account(session, company_id, account_id, actor=_actor(caller))
    )


@router.post(
    "/accounts/{account_id}/restore",
    response_model=AccountOut,
    dependencies=[requires("account:manage")],
)
@needs("account:manage")
def restore_account(
    company_id: UUID, account_id: UUID, caller: CallerDep, session: SessionDep
) -> AccountOut:
    return _account_out(
        accounts_service.restore_account(session, company_id, account_id, actor=_actor(caller))
    )


@router.delete(
    "/accounts/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[requires("account:manage")],
)
@needs("account:manage")
def delete_account(
    company_id: UUID, account_id: UUID, caller: CallerDep, session: SessionDep
) -> None:
    accounts_service.delete_account(session, company_id, account_id, actor=_actor(caller))


# -------------------------------------------------------------------------- journals


@router.get("/journals", response_model=list[JournalOut], dependencies=[requires("journal:read")])
@needs("journal:read")
def list_journals(company_id: UUID, session: SessionDep, include_archived: bool = False) -> list:
    return list(
        journals_service.list_journals(session, company_id, include_archived=include_archived)
    )


@router.post(
    "/journals",
    response_model=JournalOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[requires("journal:manage")],
)
@needs("journal:manage")
def create_journal(company_id: UUID, body: JournalIn, caller: CallerDep, session: SessionDep):
    return journals_service.create_journal(
        session,
        company_id,
        journals_service.JournalData(**body.model_dump()),
        actor=_actor(caller),
    )


@router.patch(
    "/journals/{journal_id}",
    response_model=JournalOut,
    dependencies=[requires("journal:manage")],
)
@needs("journal:manage")
def update_journal(
    company_id: UUID,
    journal_id: UUID,
    body: JournalPatch,
    caller: CallerDep,
    session: SessionDep,
):
    return journals_service.update_journal(
        session, company_id, journal_id, body.model_dump(exclude_unset=True), actor=_actor(caller)
    )


@router.post(
    "/journals/{journal_id}/archive",
    response_model=JournalOut,
    dependencies=[requires("journal:manage")],
)
@needs("journal:manage")
def archive_journal(company_id: UUID, journal_id: UUID, caller: CallerDep, session: SessionDep):
    return journals_service.archive_journal(session, company_id, journal_id, actor=_actor(caller))


# -------------------------------------------------------------------------- defaults


@router.get("/defaults", response_model=DefaultsOut, dependencies=[requires("account:read")])
@needs("account:read")
def get_defaults(company_id: UUID, session: SessionDep) -> DefaultsOut:
    defaults = defaults_service.get_defaults(session, company_id)
    return DefaultsOut(accounts=defaults.accounts, missing=defaults.missing)


@router.put(
    "/defaults/{key}", response_model=DefaultsOut, dependencies=[requires("account:manage")]
)
@needs("account:manage")
def set_default(
    company_id: UUID,
    key: str,
    body: DefaultIn,
    caller: CallerDep,
    session: SessionDep,
) -> DefaultsOut:
    defaults = defaults_service.set_default(
        session, company_id, key, body.account_id, actor=_actor(caller)
    )
    return DefaultsOut(accounts=defaults.accounts, missing=defaults.missing)


# ------------------------------------------------------------------------- templates


@router.get(
    "/chart-templates", response_model=list[TemplateOut], dependencies=[requires("chart:load")]
)
@needs("chart:load")
def list_templates(company_id: UUID) -> list[TemplateOut]:
    return [
        TemplateOut(key=template.key, name=template.name, description=template.description)
        for template in templates_service.TEMPLATES.values()
    ]


@router.post(
    "/chart-templates/{key}/load",
    response_model=TemplateLoadedOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[requires("chart:load")],
)
@needs("chart:load")
def load_template(
    company_id: UUID, key: str, caller: CallerDep, session: SessionDep
) -> TemplateLoadedOut:
    result = templates_service.load_template(session, company_id, key, actor=_actor(caller))
    # Taxes belong to billing, which sits above the chart module, so the two are composed
    # here rather than inside the template loader.
    taxes = install_saudi_taxes(session, company_id, actor=_actor(caller)) if key == "sa" else []
    return TemplateLoadedOut(
        accounts=result.accounts,
        journals=result.journals,
        defaults=result.defaults,
        taxes=len(taxes),
    )


# ----------------------------------------------------------------------------- rates


@router.get("/exchange-rates", response_model=list[RateOut], dependencies=[requires("rate:read")])
@needs("rate:read")
def list_rates(company_id: UUID, session: SessionDep, currency_code: str | None = None) -> list:
    return list(rates_service.list_rates(session, company_id, currency_code))


@router.put("/exchange-rates", response_model=RateOut, dependencies=[requires("rate:manage")])
@needs("rate:manage")
def set_rate(company_id: UUID, body: RateIn, caller: CallerDep, session: SessionDep):
    return rates_service.set_rate(
        session,
        company_id,
        body.currency_code,
        body.rate_date,
        body.rate,
        actor=_actor(caller),
    )


@router.post(
    "/exchange-rates/import",
    response_model=RateImportOut,
    dependencies=[requires("rate:manage")],
)
@needs("rate:manage")
def import_rates(
    company_id: UUID, body: list[RateIn], caller: CallerDep, session: SessionDep
) -> RateImportOut:
    result = rates_service.import_rates(
        session, company_id, [row.model_dump() for row in body], actor=_actor(caller)
    )
    return RateImportOut(
        recorded=result.recorded,
        rejected=[{"row": row, "reason": reason} for row, reason in result.rejected],
    )


# ------------------------------------------------------------------------- readiness


@router.get(
    "/chart-readiness", response_model=list[FindingOut], dependencies=[requires("account:read")]
)
@needs("account:read")
def chart_readiness(company_id: UUID, session: SessionDep) -> list[FindingOut]:
    return [
        FindingOut(code=finding.code, message=finding.message, subject=finding.subject)
        for finding in readiness_service.check(session, company_id)
    ]
