"""Shared helpers for identity tests."""

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from app.platform.identity import api as identity
from app.platform.mail.api import RecordingMailer

PASSWORD = "a-long-enough-password"


@pytest.fixture
def mailer() -> RecordingMailer:
    return RecordingMailer()


@pytest.fixture
def unique_email() -> Iterator[str]:
    """A fresh address per test, since the database is shared across a worker's tests."""
    from app.shared.ids import uuid7

    yield f"user-{uuid7().hex[-10:]}@example.sa"


def invite_and_accept(
    session: Session, mailer: RecordingMailer, email: str, name: str = "Test Person"
):
    """The normal way a user comes into being: invited, then accepts with their own password."""
    result = identity.invite_user(session, email=email, name=name, mailer=mailer)
    raw_token = result.link.rsplit("/", 2)[-2]
    user, token = identity.accept_invitation(session, raw_token, PASSWORD)
    session.commit()
    return user, token, raw_token
