"""Customers and vendors, with the details a Saudi tax invoice must carry."""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.models import PARTNER_TYPES, Partner
from app.platform.audit.api import Actor, record
from app.shared.errors import DomainError
from app.shared.ids import uuid7

# A Saudi VAT number is fifteen digits that start and end with 3 (ZATCA's rule).
SAUDI_VAT_NUMBER = re.compile(r"^3\d{13}3$")


@dataclass(frozen=True, slots=True)
class PartnerData:
    name: str
    type: str
    name_ar: str | None = None
    vat_number: str | None = None
    cr_number: str | None = None
    email: str | None = None
    phone: str | None = None
    address: dict[str, Any] = field(default_factory=dict)


def validate_vat_number(vat_number: str | None) -> str | None:
    if not vat_number:
        return None
    cleaned = vat_number.strip().replace(" ", "")
    if not SAUDI_VAT_NUMBER.fullmatch(cleaned):
        raise DomainError(
            "invoicing.invalid_vat_number",
            "a Saudi VAT number is fifteen digits beginning and ending with 3",
        )
    return cleaned


def get_partner(session: Session, company_id: UUID, partner_id: UUID) -> Partner:
    partner = session.execute(
        select(Partner).where(Partner.id == partner_id, Partner.company_id == company_id)
    ).scalar_one_or_none()
    if partner is None:
        raise DomainError("invoicing.partner_not_found", f"partner {partner_id} not found")
    return partner


def list_partners(
    session: Session,
    company_id: UUID,
    *,
    type_: str | None = None,
    include_archived: bool = False,
    search: str | None = None,
) -> Sequence[Partner]:
    query = select(Partner).where(Partner.company_id == company_id)
    if not include_archived:
        query = query.where(Partner.active.is_(True))
    if type_:
        query = query.where(Partner.type.in_([type_, "both"]))
    partners = session.execute(query.order_by(Partner.name)).scalars().all()
    if search:
        needle = search.strip().lower()
        partners = [
            partner
            for partner in partners
            if needle in partner.name.lower()
            or needle in (partner.name_ar or "").lower()
            or needle in (partner.vat_number or "")
        ]
    return partners


def create_partner(
    session: Session, company_id: UUID, data: PartnerData, *, actor: Actor | None = None
) -> Partner:
    name = data.name.strip()
    if not name:
        raise DomainError("invoicing.missing_field", "a partner needs a name")
    if data.type not in PARTNER_TYPES:
        raise DomainError("invoicing.invalid_partner_type", f"{data.type!r} is not a partner type")

    partner = Partner(
        id=uuid7(),
        company_id=company_id,
        name=name,
        name_ar=data.name_ar or None,
        type=data.type,
        vat_number=validate_vat_number(data.vat_number),
        cr_number=(data.cr_number or None),
        email=(data.email or None),
        phone=(data.phone or None),
        address=data.address or {},
    )
    session.add(partner)
    session.flush()
    record(
        session,
        action="partner.created",
        actor=actor,
        company_id=company_id,
        target_type="partner",
        target_id=partner.id,
        detail={"name": partner.name, "vat_number": partner.vat_number},
    )
    return partner


def update_partner(
    session: Session,
    company_id: UUID,
    partner_id: UUID,
    changes: dict[str, Any],
    *,
    actor: Actor | None = None,
) -> Partner:
    partner = get_partner(session, company_id, partner_id)

    if "name" in changes:
        name = str(changes["name"]).strip()
        if not name:
            raise DomainError("invoicing.missing_field", "a partner needs a name")
        partner.name = name
    if "type" in changes:
        if changes["type"] not in PARTNER_TYPES:
            raise DomainError(
                "invoicing.invalid_partner_type", f"{changes['type']!r} is not a partner type"
            )
        partner.type = changes["type"]
    if "vat_number" in changes:
        partner.vat_number = validate_vat_number(changes["vat_number"])
    for plain in ("name_ar", "cr_number", "email", "phone"):
        if plain in changes:
            setattr(partner, plain, changes[plain] or None)
    if "address" in changes:
        partner.address = changes["address"] or {}

    partner.updated_at = datetime.now(UTC)
    session.flush()
    record(
        session,
        action="partner.updated",
        actor=actor,
        company_id=company_id,
        target_type="partner",
        target_id=partner.id,
        detail={"name": partner.name, "changed": sorted(changes)},
    )
    return partner


def archive_partner(
    session: Session, company_id: UUID, partner_id: UUID, *, actor: Actor | None = None
) -> Partner:
    """Documents already issued keep their partner; new ones no longer offer it (R9.AC4)."""
    partner = get_partner(session, company_id, partner_id)
    partner.active = False
    partner.updated_at = datetime.now(UTC)
    session.flush()
    record(
        session,
        action="partner.archived",
        actor=actor,
        company_id=company_id,
        target_type="partner",
        target_id=partner.id,
        detail={"name": partner.name},
    )
    return partner
