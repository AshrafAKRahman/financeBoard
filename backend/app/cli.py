"""Operator commands.

    uv run python -m app.cli bootstrap-admin --email you@example.sa [--password …]

Creates the first administrator on a fresh system. Everyone after that is invited from
inside the application, so this is the only place a password is ever set for someone.
"""

import argparse
import secrets
import sys
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import transaction
from app.platform.access.api import ensure_catalogue_seeded, grant_role
from app.platform.access.models import ADMINISTRATOR_ROLE_ID
from app.platform.audit.api import Actor, record
from app.platform.identity import passwords
from app.platform.identity.api import normalize_email, now
from app.platform.identity.models import AppUser
from app.platform.tenancy.api import Company
from app.shared.errors import DomainError
from app.shared.ids import uuid7

GENERATED_PASSWORD_BYTES = 24


@dataclass(frozen=True)
class Bootstrapped:
    user_id: UUID
    email: str
    generated_password: str | None


def bootstrap_admin(
    session: Session, *, email: str, password: str | None = None, company_id: UUID | None = None
) -> Bootstrapped:
    """R9 — only on a system with no users, and only once."""
    if session.execute(select(func.count()).select_from(AppUser)).scalar_one():
        raise DomainError(
            "identity.already_bootstrapped",
            "this system already has users; invite people from inside the application",
        )

    address = normalize_email(email)
    generated = None
    if not password:
        generated = secrets.token_urlsafe(GENERATED_PASSWORD_BYTES)
        password = generated

    user = AppUser(
        id=uuid7(),
        email=address,
        name="Administrator",
        password_hash=passwords.hash_password(password),
        state="active",
        email_verified_at=now(),
    )
    session.add(user)
    session.flush()

    ensure_catalogue_seeded(session)

    companies = (
        [company_id]
        if company_id is not None
        else list(session.execute(select(Company.id)).scalars())
    )
    for company in companies:
        grant_role(
            session,
            user_id=user.id,
            company_id=company,
            role_id=ADMINISTRATOR_ROLE_ID,
            actor=Actor(user.id, user.email),
        )

    # The password itself never reaches the log (R9.AC4).
    record(
        session,
        action="system.bootstrapped",
        actor=Actor(user.id, user.email),
        target_type="user",
        target_id=user.id,
        detail={"email": user.email, "companies": len(companies)},
    )
    return Bootstrapped(user.id, address, generated)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    commands = parser.add_subparsers(dest="command", required=True)

    bootstrap = commands.add_parser("bootstrap-admin", help="create the first administrator")
    bootstrap.add_argument("--email", required=True)
    bootstrap.add_argument("--password", help="omit to have one generated and printed once")
    bootstrap.add_argument("--company-id", help="grant only in this company")

    args = parser.parse_args(argv)

    try:
        with transaction() as session:
            result = bootstrap_admin(
                session,
                email=args.email,
                password=args.password,
                company_id=UUID(args.company_id) if args.company_id else None,
            )
    except DomainError as error:
        print(f"{error.code}: {error.message}", file=sys.stderr)
        return 1

    print(f"Administrator created: {result.email}")
    if result.generated_password:
        print(f"Password (shown once): {result.generated_password}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
