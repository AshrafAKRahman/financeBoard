"""Sign-in: one answer for every failure, equal work, and a lockout (R3)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.platform.identity import api as identity
from app.platform.identity import passwords
from app.platform.mail.api import RecordingMailer
from app.shared.errors import DomainError
from tests.identity.conftest import PASSWORD, invite_and_accept

pytestmark = pytest.mark.db


def test_correct_credentials_return_the_user(
    session: Session, mailer: RecordingMailer, unique_email: str
) -> None:
    invite_and_accept(session, mailer, unique_email)
    user = identity.authenticate(session, unique_email, PASSWORD)
    session.commit()
    assert user.email == unique_email


def test_email_is_matched_case_insensitively(
    session: Session, mailer: RecordingMailer, unique_email: str
) -> None:
    invite_and_accept(session, mailer, unique_email)
    assert identity.authenticate(session, f" {unique_email.upper()} ", PASSWORD)
    session.commit()


@pytest.mark.parametrize("password", ["wrong-password-entirely", "", PASSWORD.upper()])
def test_a_wrong_password_is_refused(
    session: Session, mailer: RecordingMailer, unique_email: str, password: str
) -> None:
    invite_and_accept(session, mailer, unique_email)
    with pytest.raises(DomainError) as error:
        identity.authenticate(session, unique_email, password)
    assert error.value.code == "identity.invalid_credentials"
    session.commit()


def test_an_unknown_address_gives_the_same_error(session: Session) -> None:
    """R3.AC3 — the message must not reveal whether the address exists."""
    with pytest.raises(DomainError) as error:
        identity.authenticate(session, "nobody-at-all@example.sa", PASSWORD)
    assert error.value.code == "identity.invalid_credentials"
    assert error.value.message == "email address or password is wrong"
    session.commit()


def test_both_failures_word_it_identically(
    session: Session, mailer: RecordingMailer, unique_email: str
) -> None:
    invite_and_accept(session, mailer, unique_email)

    with pytest.raises(DomainError) as wrong_password:
        identity.authenticate(session, unique_email, "definitely-not-it")
    with pytest.raises(DomainError) as unknown_user:
        identity.authenticate(session, "ghost-user@example.sa", PASSWORD)
    session.commit()

    assert str(wrong_password.value) == str(unknown_user.value)


def test_unknown_addresses_still_cost_a_verification(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3.AC8 — proven by counting the work, not by timing the clock."""
    calls: list[str] = []
    monkeypatch.setattr(
        passwords, "verify_dummy", lambda: calls.append("dummy") or None, raising=True
    )
    monkeypatch.setattr(
        identity.passwords, "verify_dummy", lambda: calls.append("dummy") or None, raising=True
    )

    with pytest.raises(DomainError):
        identity.authenticate(session, "nobody-here@example.sa", PASSWORD)
    session.commit()
    assert calls == ["dummy"]


def test_an_invited_user_cannot_sign_in_yet(
    session: Session, mailer: RecordingMailer, unique_email: str
) -> None:
    """R3.AC9 — they have no password; the link is the only way in."""
    identity.invite_user(session, email=unique_email, name="Ashraf", mailer=mailer)
    session.commit()

    with pytest.raises(DomainError) as error:
        identity.authenticate(session, unique_email, PASSWORD)
    assert error.value.code == "identity.invalid_credentials"
    session.commit()


def test_a_deactivated_user_cannot_sign_in(
    session: Session, mailer: RecordingMailer, unique_email: str
) -> None:
    user, _, _ = invite_and_accept(session, mailer, unique_email)
    identity.deactivate_user(session, user.id)
    session.commit()

    with pytest.raises(DomainError) as error:
        identity.authenticate(session, unique_email, PASSWORD)
    assert error.value.code == "identity.invalid_credentials"
    session.commit()


def test_an_unreadable_stored_hash_refuses_the_login(
    session: Session, mailer: RecordingMailer, unique_email: str
) -> None:
    """R2.AC5"""
    user, _, _ = invite_and_accept(session, mailer, unique_email)
    session.execute(
        text("UPDATE app_user SET password_hash = 'corrupt' WHERE id = :id"), {"id": user.id}
    )
    session.commit()
    session.expire_all()

    with pytest.raises(DomainError) as error:
        identity.authenticate(session, unique_email, PASSWORD)
    assert error.value.code == "identity.invalid_credentials"
    session.commit()


def test_a_weak_stored_hash_is_upgraded_on_sign_in(
    session: Session, mailer: RecordingMailer, unique_email: str
) -> None:
    """R2.AC4"""
    from argon2 import PasswordHasher

    user, _, _ = invite_and_accept(session, mailer, unique_email)
    weak = PasswordHasher(memory_cost=8192, time_cost=1, parallelism=1).hash(PASSWORD)
    session.execute(
        text("UPDATE app_user SET password_hash = :hash WHERE id = :id"),
        {"hash": weak, "id": user.id},
    )
    session.commit()
    session.expire_all()

    signed_in = identity.authenticate(session, unique_email, PASSWORD)
    session.commit()
    assert signed_in.password_hash != weak
    assert not passwords.needs_rehash(signed_in.password_hash or "")


class TestLockout:
    def failures(self, session: Session, email: str, count: int) -> None:
        for _ in range(count):
            with pytest.raises(DomainError):
                identity.authenticate(session, email, "wrong-password-here")
            session.commit()

    def test_too_many_failures_stop_further_attempts(
        self, session: Session, mailer: RecordingMailer, unique_email: str
    ) -> None:
        invite_and_accept(session, mailer, unique_email)
        limit = get_settings().login_attempt_limit
        self.failures(session, unique_email, limit)

        with pytest.raises(DomainError) as error:
            identity.authenticate(session, unique_email, PASSWORD)  # even the right one
        assert error.value.code == "identity.too_many_attempts"
        session.commit()

    def test_attempts_below_the_limit_still_allow_signing_in(
        self, session: Session, mailer: RecordingMailer, unique_email: str
    ) -> None:
        invite_and_accept(session, mailer, unique_email)
        self.failures(session, unique_email, get_settings().login_attempt_limit - 1)

        assert identity.authenticate(session, unique_email, PASSWORD)
        session.commit()

    def test_a_success_clears_the_failure_count(
        self, session: Session, mailer: RecordingMailer, unique_email: str
    ) -> None:
        """R3.AC6"""
        invite_and_accept(session, mailer, unique_email)
        self.failures(session, unique_email, 3)
        assert identity.recent_failures(session, unique_email) == 3

        identity.authenticate(session, unique_email, PASSWORD)
        session.commit()
        assert identity.recent_failures(session, unique_email) == 0

    def test_only_failures_inside_the_window_count(
        self, session: Session, mailer: RecordingMailer, unique_email: str
    ) -> None:
        invite_and_accept(session, mailer, unique_email)
        self.failures(session, unique_email, 3)
        session.execute(
            text("UPDATE login_attempt SET attempted_at = :old WHERE email = :email"),
            {"old": datetime.now(UTC) - timedelta(hours=1), "email": unique_email},
        )
        session.commit()
        assert identity.recent_failures(session, unique_email) == 0

    def test_the_lockout_is_per_address(
        self, session: Session, mailer: RecordingMailer, unique_email: str
    ) -> None:
        other_email = unique_email.replace("user-", "other-")
        invite_and_accept(session, mailer, unique_email)
        invite_and_accept(session, mailer, other_email)
        self.failures(session, unique_email, get_settings().login_attempt_limit)

        assert identity.authenticate(session, other_email, PASSWORD)
        session.commit()


def test_sign_ins_are_audited(session: Session, mailer: RecordingMailer, unique_email: str) -> None:
    """R8.AC1 — success and failure both leave a record."""
    invite_and_accept(session, mailer, unique_email)
    with pytest.raises(DomainError):
        identity.authenticate(session, unique_email, "wrong-password-here")
    session.commit()
    identity.authenticate(session, unique_email, PASSWORD)
    session.commit()

    actions = (
        session.execute(
            text(
                "SELECT action FROM audit_log WHERE actor_email = :email "
                "AND action LIKE 'login.%' ORDER BY at"
            ),
            {"email": unique_email},
        )
        .scalars()
        .all()
    )
    assert actions == ["login.failed", "login.succeeded"]
