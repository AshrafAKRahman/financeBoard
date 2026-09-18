"""Request and response bodies.

No response model has a field for a password hash or a token, so neither can leak by
accident (R2.AC2, R10.AC3).
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    # Addresses are validated (and normalised) by identity.normalize_email, so there is
    # one rule for it rather than two that can disagree.
    email: str
    password: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class InviteRequest(BaseModel):
    email: str
    name: str = Field(min_length=1, max_length=200)


class AcceptInvitationRequest(BaseModel):
    password: str


class GrantRoleRequest(BaseModel):
    role_id: UUID


class CompanyAccess(BaseModel):
    company_id: UUID
    name: str
    permissions: list[str]


class Me(BaseModel):
    id: UUID
    email: str
    name: str
    companies: list[CompanyAccess]


class UserOut(BaseModel):
    id: UUID
    email: str
    name: str
    state: str
    email_verified_at: datetime | None


class InvitationOut(BaseModel):
    id: UUID
    user_id: UUID
    email: str
    expires_at: datetime
    email_sent: bool


class InvitationStatus(BaseModel):
    status: str
    email: str
    expires_at: datetime


class AuditEntryOut(BaseModel):
    id: UUID
    at: datetime
    actor_email: str | None
    action: str
    target_type: str | None
    target_id: str | None
    detail: dict[str, Any]
