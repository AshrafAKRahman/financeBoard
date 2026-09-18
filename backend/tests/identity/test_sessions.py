"""Sessions identify the caller and stop being usable when they should (R1, R4)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.platform.identity import api as identity
from app.platform.identity.models import UserSession
from app.platform.mail.api import RecordingMailer
from app.shared.errors import DomainError
from tests.identity.conftest import PASSWORD, invite_and_accept

pytestmark = pytest.mark.db

NEW_PASSWORD = "an-even-longer-password"


def age_session(session: Session, session_id, *, last_used=None, expires=None) -> None:
    updates, params = [], {"id": session_id}
    if last_used is not None:
        updates.append("last_used_at = :last_used")
        params["last_used"] = last_used
    if expires is not None:
        updates.append("expires_at = :expires")
        params["expires"] = expires
    session.execute(
        text(f"UPDATE user_session SET {', '.join(updates)} WHERE id = :id"), params
    )
    session.commit()
    session.expire_all()


def test_a_fresh_session_identifies_its_user(
    session: Session, mailer: RecordingMailer, unique_email: str
) -> None:
    user, token, _ = invite_and_accept(session, mailer, unique_email)

    loaded = identity.load_session(session, token.raw)
    session.commit()
    assert loaded is not None
    user_session, loaded_user = loaded
    assert loaded_user.id == user.id
    assert user_session.id == token.session_id


def test_only_the_hash_of_the_token_is_stored(
    session: Session, mailer: RecordingMailer, unique_email: str
) -> None:
    """R4.AC2"""
    _, token, _ = invite_and_accept(session, mailer, unique_email)
    stored = session.get(UserSession, token.session_id)
    assert stored is not None
    assert stored.token_hash != token.raw
    assert token.raw not in stored.token_hash


def test_an_unknown_token_loads_nothing(session: Session) -> None:
    assert identity.load_session(session, "not-a-real-token") is None


def test_using_a_session_records_the_time(
    session: Session, mailer: RecordingMailer, unique_email: str
) -> None:
    """R4.AC7"""
    _, token, _ = invite_and_accept(session, mailer, unique_email)
    age_session(session, token.session_id, last_used=datetime.now(UTC) - timedelta(minutes=30))

    identity.load_session(session, token.raw)
    session.commit()
    stored = session.get(UserSession, token.session_id)
    assert stored is not None
    assert datetime.now(UTC) - stored.last_used_at < timedelta(minutes=1)


def test_an_idle_session_expires(
    session: Session, mailer: RecordingMailer, unique_email: str
) -> None:
    """R4.AC5"""
    _, token, _ = invite_and_accept(session, mailer, unique_email)
    idle_hours = get_settings().session_idle_hours
    age_session(
        session, token.session_id, last_used=datetime.now(UTC) - timedelta(hours=idle_hours + 1)
    )
    assert identity.load_session(session, token.raw) is None


def test_an_old_session_expires_even_when_used(
    session: Session, mailer: RecordingMailer, unique_email: str
) -> None:
    """R4.AC6"""
    _, token, _ = invite_and_accept(session, mailer, unique_email)
    age_session(
        session,
        token.session_id,
        last_used=datetime.now(UTC),
        expires=datetime.now(UTC) - timedelta(seconds=1),
    )
    assert identity.load_session(session, token.raw) is None


def test_ending_a_session_stops_it(
    session: Session, mailer: RecordingMailer, unique_email: str
) -> None:
    """R3.AC7"""
    _, token, _ = invite_and_accept(session, mailer, unique_email)
    identity.end_session(session, token.session_id)
    session.commit()
    assert identity.load_session(session, token.raw) is None


def test_deactivating_a_user_ends_their_sessions(
    session: Session, mailer: RecordingMailer, unique_email: str
) -> None:
    """R1.AC6 and R4.AC8"""
    user, first, _ = invite_and_accept(session, mailer, unique_email)
    second = identity.start_session(session, user)
    session.commit()

    identity.deactivate_user(session, user.id)
    session.commit()

    assert identity.load_session(session, first.raw) is None
    assert identity.load_session(session, second.raw) is None


def test_ending_all_sessions_can_keep_the_current_one(
    session: Session, mailer: RecordingMailer, unique_email: str
) -> None:
    user, keep, _ = invite_and_accept(session, mailer, unique_email)
    other = identity.start_session(session, user)
    session.commit()

    ended = identity.end_all_sessions(session, user.id, except_session_id=keep.session_id)
    session.commit()

    assert ended == 1
    assert identity.load_session(session, keep.raw) is not None
    assert identity.load_session(session, other.raw) is None
    session.commit()


class TestPasswordChange:
    def test_changing_the_password_keeps_this_session_and_ends_the_others(
        self, session: Session, mailer: RecordingMailer, unique_email: str
    ) -> None:
        """R1.AC8"""
        user, current, _ = invite_and_accept(session, mailer, unique_email)
        elsewhere = identity.start_session(session, user)
        session.commit()

        identity.change_password(
            session, user, PASSWORD, NEW_PASSWORD, keep_session_id=current.session_id
        )
        session.commit()

        assert identity.load_session(session, current.raw) is not None
        assert identity.load_session(session, elsewhere.raw) is None
        assert identity.authenticate(session, unique_email, NEW_PASSWORD)
        session.commit()

    def test_the_old_password_stops_working(
        self, session: Session, mailer: RecordingMailer, unique_email: str
    ) -> None:
        user, _, _ = invite_and_accept(session, mailer, unique_email)
        identity.change_password(session, user, PASSWORD, NEW_PASSWORD)
        session.commit()

        with pytest.raises(DomainError) as error:
            identity.authenticate(session, unique_email, PASSWORD)
        assert error.value.code == "identity.invalid_credentials"
        session.commit()

    def test_the_current_password_is_required(
        self, session: Session, mailer: RecordingMailer, unique_email: str
    ) -> None:
        """R1.AC9"""
        user, _, _ = invite_and_accept(session, mailer, unique_email)
        with pytest.raises(DomainError) as error:
            identity.change_password(session, user, "not-the-current-one", NEW_PASSWORD)
        assert error.value.code == "identity.invalid_credentials"
        session.rollback()

    def test_the_new_password_must_be_long_enough(
        self, session: Session, mailer: RecordingMailer, unique_email: str
    ) -> None:
        user, _, _ = invite_and_accept(session, mailer, unique_email)
        with pytest.raises(DomainError) as error:
            identity.change_password(session, user, PASSWORD, "short")
        assert error.value.code == "identity.weak_password"
        session.rollback()

    def test_the_change_is_audited(
        self, session: Session, mailer: RecordingMailer, unique_email: str
    ) -> None:
        user, _, _ = invite_and_accept(session, mailer, unique_email)
        identity.change_password(session, user, PASSWORD, NEW_PASSWORD)
        session.commit()

        actions = (
            session.execute(
                text("SELECT action FROM audit_log WHERE target_id = :id AND action = :a"),
                {"id": str(user.id), "a": "password.changed"},
            )
            .scalars()
            .all()
        )
        assert actions == ["password.changed"]
