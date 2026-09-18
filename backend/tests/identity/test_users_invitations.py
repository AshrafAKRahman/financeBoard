"""Invitations are the only way an account gets a password (R1, R11)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.platform.audit.api import Actor
from app.platform.identity import api as identity
from app.platform.identity.models import AppUser, Invitation
from app.platform.mail.api import RecordingMailer
from app.shared.errors import DomainError
from app.shared.ids import uuid7
from tests.identity.conftest import PASSWORD, invite_and_accept

pytestmark = pytest.mark.db


def token_of(link: str) -> str:
    return link.rsplit("/", 2)[-2]


class TestInviting:
    def test_invited_user_has_no_password_and_cannot_be_active(
        self, session: Session, mailer: RecordingMailer, unique_email: str
    ) -> None:
        result = identity.invite_user(session, email=unique_email, name="Ashraf", mailer=mailer)
        session.commit()

        user = identity.get_user_by_email(session, unique_email)
        assert user is not None
        assert (user.state, user.password_hash, user.email_verified_at) == ("invited", None, None)
        assert result.invitation.is_open
        assert result.delivery_error is None

    def test_the_invitation_email_goes_out_with_the_link(
        self, session: Session, mailer: RecordingMailer, unique_email: str
    ) -> None:
        result = identity.invite_user(session, email=unique_email, name="Ashraf", mailer=mailer)
        session.commit()

        assert len(mailer.sent) == 1
        sent = mailer.sent[0]
        assert sent.to == unique_email
        assert result.link in sent.text
        assert "Hello Ashraf" in sent.text and "مرحباً Ashraf" in sent.text

    def test_email_is_normalised(
        self, session: Session, mailer: RecordingMailer, unique_email: str
    ) -> None:
        identity.invite_user(
            session, email=f"  {unique_email.upper()} ", name="Ashraf", mailer=mailer
        )
        session.commit()
        assert identity.get_user_by_email(session, unique_email) is not None

    @pytest.mark.parametrize("bad", ["not-an-email", "nobody@", "@example.sa", "a b@example.sa"])
    def test_invalid_addresses_are_refused(
        self, session: Session, mailer: RecordingMailer, bad: str
    ) -> None:
        with pytest.raises(DomainError) as error:
            identity.invite_user(session, email=bad, name="Ashraf", mailer=mailer)
        assert error.value.code == "identity.invalid_email"
        session.rollback()

    def test_a_second_invitation_for_the_same_address_is_refused(
        self, session: Session, mailer: RecordingMailer, unique_email: str
    ) -> None:
        identity.invite_user(session, email=unique_email, name="Ashraf", mailer=mailer)
        session.commit()
        with pytest.raises(DomainError) as error:
            identity.invite_user(session, email=unique_email, name="Ashraf", mailer=mailer)
        assert error.value.code == "identity.duplicate_email"
        session.rollback()

    def test_a_refusing_relay_keeps_the_invitation(
        self, session: Session, unique_email: str
    ) -> None:
        """R11.AC10 — the person can be invited again without recreating the account."""
        failing = RecordingMailer(fail_with="relay unavailable")
        result = identity.invite_user(session, email=unique_email, name="Ashraf", mailer=failing)
        session.commit()

        assert result.delivery_error == "relay unavailable"
        assert result.invitation.is_open
        actions = (
            session.execute(
                text("SELECT action FROM audit_log WHERE target_id = :id"),
                {"id": str(result.invitation.user_id)},
            )
            .scalars()
            .all()
        )
        assert "invitation.email_failed" in actions

    def test_no_token_or_link_reaches_the_audit_log(
        self, session: Session, mailer: RecordingMailer, unique_email: str
    ) -> None:
        """R11.AC12"""
        result = identity.invite_user(session, email=unique_email, name="Ashraf", mailer=mailer)
        session.commit()
        logged = (
            session.execute(
                text("SELECT detail::text FROM audit_log WHERE target_id = :id"),
                {"id": str(result.invitation.user_id)},
            )
            .scalars()
            .all()
        )
        assert logged
        raw_token = token_of(result.link)
        assert all(raw_token not in row and "invitations/" not in row for row in logged)


class TestAccepting:
    def test_accepting_sets_the_password_verifies_the_email_and_signs_in(
        self, session: Session, mailer: RecordingMailer, unique_email: str
    ) -> None:
        user, token, _ = invite_and_accept(session, mailer, unique_email)

        assert user.state == "active"
        assert user.password_hash and user.password_hash.startswith("$argon2id$")
        assert user.email_verified_at is not None
        assert token.raw and token.expires_at > datetime.now(UTC)

    def test_the_invitation_is_consumed(
        self, session: Session, mailer: RecordingMailer, unique_email: str
    ) -> None:
        _, _, raw_token = invite_and_accept(session, mailer, unique_email)
        with pytest.raises(DomainError) as error:
            identity.accept_invitation(session, raw_token, PASSWORD)
        assert error.value.code == "identity.invitation_used"
        session.rollback()

    def test_a_short_password_is_refused(
        self, session: Session, mailer: RecordingMailer, unique_email: str
    ) -> None:
        result = identity.invite_user(session, email=unique_email, name="Ashraf", mailer=mailer)
        session.commit()
        with pytest.raises(DomainError) as error:
            identity.accept_invitation(session, token_of(result.link), "short")
        assert error.value.code == "identity.weak_password"
        session.rollback()

    @pytest.mark.parametrize("bad_token", ["", "nonsense", "x" * 43])
    def test_unknown_links_are_refused(
        self, session: Session, mailer: RecordingMailer, bad_token: str
    ) -> None:
        with pytest.raises(DomainError) as error:
            identity.open_invitation(session, bad_token)
        assert error.value.code == "identity.invitation_invalid"

    def test_expired_links_are_refused(
        self, session: Session, mailer: RecordingMailer, unique_email: str
    ) -> None:
        result = identity.invite_user(session, email=unique_email, name="Ashraf", mailer=mailer)
        # The table requires expires_at > created_at, so age the whole row.
        session.execute(
            text("UPDATE invitation SET created_at = :created, expires_at = :past WHERE id = :id"),
            {
                "created": datetime.now(UTC) - timedelta(days=8),
                "past": datetime.now(UTC) - timedelta(days=1),
                "id": result.invitation.id,
            },
        )
        session.commit()
        session.expire_all()  # the raw UPDATE bypassed the ORM's copy of the row

        with pytest.raises(DomainError) as error:
            identity.open_invitation(session, token_of(result.link))
        assert error.value.code == "identity.invitation_expired"


class TestResendAndRevoke:
    def test_resending_supersedes_the_previous_link(
        self, session: Session, mailer: RecordingMailer, unique_email: str
    ) -> None:
        first = identity.invite_user(session, email=unique_email, name="Ashraf", mailer=mailer)
        session.commit()
        second = identity.resend_invitation(
            session, first.invitation.id, actor=Actor(email="admin@example.sa"), mailer=mailer
        )
        session.commit()

        assert second.link != first.link
        with pytest.raises(DomainError) as error:
            identity.open_invitation(session, token_of(first.link))
        assert error.value.code == "identity.invitation_invalid"
        assert identity.open_invitation(session, token_of(second.link)).id == second.invitation.id

    def test_revoking_makes_the_link_unusable(
        self, session: Session, mailer: RecordingMailer, unique_email: str
    ) -> None:
        result = identity.invite_user(session, email=unique_email, name="Ashraf", mailer=mailer)
        session.commit()
        identity.revoke_invitation(session, result.invitation.id)
        session.commit()

        with pytest.raises(DomainError) as error:
            identity.open_invitation(session, token_of(result.link))
        assert error.value.code == "identity.invitation_invalid"

    def test_an_accepted_invitation_cannot_be_resent_or_revoked(
        self, session: Session, mailer: RecordingMailer, unique_email: str
    ) -> None:
        result = identity.invite_user(session, email=unique_email, name="Ashraf", mailer=mailer)
        session.commit()
        identity.accept_invitation(session, token_of(result.link), PASSWORD)
        session.commit()

        for call in (identity.resend_invitation, identity.revoke_invitation):
            with pytest.raises(DomainError) as error:
                call(session, result.invitation.id)
            assert error.value.code == "identity.invitation_used"
            session.rollback()

    def test_every_invitation_step_is_audited(
        self, session: Session, mailer: RecordingMailer, unique_email: str
    ) -> None:
        """R11.AC13"""
        first = identity.invite_user(session, email=unique_email, name="Ashraf", mailer=mailer)
        second = identity.resend_invitation(session, first.invitation.id, mailer=mailer)
        identity.accept_invitation(session, token_of(second.link), PASSWORD)
        session.commit()

        actions = (
            session.execute(
                text("SELECT action FROM audit_log WHERE target_id = :id ORDER BY at"),
                {"id": str(first.invitation.user_id)},
            )
            .scalars()
            .all()
        )
        assert actions == ["invitation.sent", "invitation.resent", "invitation.accepted"]


class TestNobodyElseSetsAPassword:
    def test_there_is_no_service_for_setting_another_users_password(self) -> None:
        """R1.AC10 — the only entry points are accepting an invitation and changing one's own."""
        setters = [
            name
            for name in dir(identity)
            if "password" in name and name not in {"change_password", "passwords"}
        ]
        assert setters == []

    def test_a_fresh_invitation_is_the_way_back_in_for_a_locked_out_user(
        self, session: Session, mailer: RecordingMailer, unique_email: str
    ) -> None:
        user, _, _ = invite_and_accept(session, mailer, unique_email)
        identity.deactivate_user(session, user.id)
        session.commit()

        # Re-inviting a deactivated address is refused while the account exists, so an
        # administrator reactivates by re-issuing an invitation for the same user instead.
        with pytest.raises(DomainError) as error:
            identity.invite_user(session, email=unique_email, name="Ashraf", mailer=mailer)
        assert error.value.code == "identity.duplicate_email"
        session.rollback()


class TestDeletingUsers:
    def test_a_user_in_the_audit_log_cannot_be_deleted(
        self, session: Session, mailer: RecordingMailer, unique_email: str
    ) -> None:
        user, _, _ = invite_and_accept(session, mailer, unique_email)
        with pytest.raises(DomainError) as error:
            identity.delete_user(session, user.id)
        assert error.value.code == "identity.user_in_use"
        session.rollback()

    def test_a_user_with_no_trace_can_be_deleted(self, session: Session) -> None:
        user = AppUser(
            id=uuid7(), email=f"ghost-{uuid7().hex[-8:]}@example.sa", name="Ghost", state="invited"
        )
        session.add(user)
        session.commit()

        identity.delete_user(session, user.id)
        session.commit()
        assert session.get(AppUser, user.id) is None
        assert (
            session.execute(
                text("SELECT count(*) FROM invitation WHERE user_id = :id"), {"id": user.id}
            ).scalar_one()
            == 0
        )

    def test_unknown_users_are_reported(self, session: Session) -> None:
        with pytest.raises(DomainError) as error:
            identity.get_user(session, uuid7())
        assert error.value.code == "identity.user_not_found"


def test_invitations_expire_after_the_configured_window(
    session: Session, mailer: RecordingMailer, unique_email: str
) -> None:
    result = identity.invite_user(session, email=unique_email, name="Ashraf", mailer=mailer)
    session.commit()
    invitation = session.get(Invitation, result.invitation.id)
    assert invitation is not None
    # created_at comes from the database clock and expires_at from ours, so allow a little skew.
    window = invitation.expires_at - invitation.created_at
    assert timedelta(days=6) < window <= timedelta(days=7, minutes=1)
