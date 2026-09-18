"""Migration 0002: tables, constraints, the append-only audit trigger, and the seed
(R1.AC2, R1.AC3, R5.AC1, R5.AC8, R8.AC3, R11.AC8).
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.platform.access.models import ADMINISTRATOR_ROLE_NAME
from app.platform.access.permissions import CODES
from app.shared.ids import uuid7
from tests.invariants.helpers import CHECK_VIOLATION, UNIQUE_VIOLATION, rejects

pytestmark = pytest.mark.db

TABLES = [
    "app_user",
    "user_session",
    "invitation",
    "permission",
    "role",
    "role_permission",
    "user_company_role",
    "login_attempt",
    "audit_log",
]


def make_user(connection, email: str = "owner@example.sa", **overrides) -> object:
    values = {
        "id": uuid7(),
        "email": email,
        "name": "Owner",
        "password_hash": None,
        "state": "invited",
    }
    values.update(overrides)
    connection.execute(
        text(
            "INSERT INTO app_user (id, email, name, password_hash, state) "
            "VALUES (:id, :email, :name, :password_hash, :state)"
        ),
        values,
    )
    return values["id"]


@pytest.mark.parametrize("table", TABLES)
def test_tables_exist(session: Session, table: str) -> None:
    assert session.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar() is not None


class TestUserConstraints:
    def test_email_must_already_be_lower_cased_and_trimmed(self, engine: Engine) -> None:
        """R1.AC2 — the service normalises, and the database refuses anything else."""
        for bad in ("Owner@Example.sa", " owner@example.sa", "owner@example.sa "):
            with rejects(sqlstate=CHECK_VIOLATION), engine.begin() as connection:
                make_user(connection, bad)

    def test_email_is_unique(self, engine: Engine) -> None:
        email = f"dup-{uuid7().hex[-8:]}@example.sa"
        with engine.begin() as connection:
            make_user(connection, email)
        with rejects(sqlstate=UNIQUE_VIOLATION), engine.begin() as connection:
            make_user(connection, email)

    def test_an_active_user_must_have_a_password(self, engine: Engine) -> None:
        with rejects(sqlstate=CHECK_VIOLATION), engine.begin() as connection:
            make_user(connection, f"a-{uuid7().hex[-8:]}@example.sa", state="active")

    def test_an_invited_user_must_not_have_a_password(self, engine: Engine) -> None:
        with rejects(sqlstate=CHECK_VIOLATION), engine.begin() as connection:
            make_user(
                connection,
                f"b-{uuid7().hex[-8:]}@example.sa",
                state="invited",
                password_hash="$argon2id$whatever",
            )

    @pytest.mark.parametrize("state", ["unknown", "", "Active"])
    def test_state_is_restricted(self, engine: Engine, state: str) -> None:
        with rejects(sqlstate=CHECK_VIOLATION), engine.begin() as connection:
            make_user(connection, f"c-{uuid7().hex[-8:]}@example.sa", state=state)


class TestInvitationConstraints:
    def test_only_one_open_invitation_per_user(self, engine: Engine) -> None:
        """R11.AC8 — resending must supersede, not pile up."""
        expires = datetime.now(UTC) + timedelta(days=7)
        with engine.begin() as connection:
            user_id = make_user(connection, f"inv-{uuid7().hex[-8:]}@example.sa")
            connection.execute(
                text(
                    "INSERT INTO invitation (id, user_id, token_hash, expires_at) "
                    "VALUES (:id, :user, :hash, :expires)"
                ),
                {"id": uuid7(), "user": user_id, "hash": uuid7().hex, "expires": expires},
            )

        with rejects(sqlstate=UNIQUE_VIOLATION), engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO invitation (id, user_id, token_hash, expires_at) "
                    "VALUES (:id, :user, :hash, :expires)"
                ),
                {"id": uuid7(), "user": user_id, "hash": uuid7().hex, "expires": expires},
            )

    def test_a_superseded_invitation_makes_room_for_a_new_one(self, engine: Engine) -> None:
        expires = datetime.now(UTC) + timedelta(days=7)
        with engine.begin() as connection:
            user_id = make_user(connection, f"inv2-{uuid7().hex[-8:]}@example.sa")
            first = uuid7()
            connection.execute(
                text(
                    "INSERT INTO invitation (id, user_id, token_hash, expires_at) "
                    "VALUES (:id, :user, :hash, :expires)"
                ),
                {"id": first, "user": user_id, "hash": uuid7().hex, "expires": expires},
            )
            connection.execute(
                text("UPDATE invitation SET superseded_at = now() WHERE id = :id"), {"id": first}
            )
            connection.execute(
                text(
                    "INSERT INTO invitation (id, user_id, token_hash, expires_at) "
                    "VALUES (:id, :user, :hash, :expires)"
                ),
                {"id": uuid7(), "user": user_id, "hash": uuid7().hex, "expires": expires},
            )


class TestPermissionCatalogue:
    def test_permission_codes_follow_resource_action(self, session: Session) -> None:
        """R5.AC1 — the format is a constraint, not a convention."""
        codes = session.execute(text("SELECT code FROM permission")).scalars().all()
        assert codes
        assert all(":" in code for code in codes)

    @pytest.mark.parametrize("bad", ["userinvite", "User:invite", "user:", ":invite", "user:1"])
    def test_malformed_codes_are_refused(self, engine: Engine, bad: str) -> None:
        with rejects(sqlstate=CHECK_VIOLATION), engine.begin() as connection:
            connection.execute(
                text("INSERT INTO permission (code, description) VALUES (:c, 'x')"), {"c": bad}
            )

    def test_catalogue_in_the_database_matches_the_code(self, session: Session) -> None:
        stored = set(session.execute(text("SELECT code FROM permission")).scalars())
        assert stored == set(CODES)

    def test_administrator_role_holds_every_permission(self, session: Session) -> None:
        """R5.AC8"""
        granted = set(
            session.execute(
                text(
                    "SELECT rp.permission_code FROM role_permission rp JOIN role r "
                    "ON r.id = rp.role_id WHERE r.name = :name"
                ),
                {"name": ADMINISTRATOR_ROLE_NAME},
            ).scalars()
        )
        assert granted == set(CODES)

    def test_administrator_role_is_marked_as_a_system_role(self, session: Session) -> None:
        is_system = session.execute(
            text("SELECT is_system FROM role WHERE name = :name"),
            {"name": ADMINISTRATOR_ROLE_NAME},
        ).scalar_one()
        assert is_system is True

    def test_a_role_cannot_be_granted_an_unknown_permission(self, engine: Engine) -> None:
        with rejects(), engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO role_permission (role_id, permission_code) "
                    "SELECT id, 'typo:permission' FROM role WHERE name = :name"
                ),
                {"name": ADMINISTRATOR_ROLE_NAME},
            )


class TestAuditLogIsAppendOnly:
    def write_record(self, connection, action: str = "test.event") -> object:
        record_id = uuid7()
        connection.execute(
            text("INSERT INTO audit_log (id, action, actor_email) VALUES (:id, :a, :e)"),
            {"id": record_id, "a": action, "e": "owner@example.sa"},
        )
        return record_id

    def test_records_can_be_appended(self, engine: Engine) -> None:
        with engine.begin() as connection:
            record_id = self.write_record(connection)
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT action FROM audit_log WHERE id = :id"), {"id": record_id}
                ).scalar_one()
                == "test.event"
            )

    def test_records_cannot_be_changed(self, engine: Engine) -> None:
        with engine.begin() as connection:
            record_id = self.write_record(connection)
        with rejects("audit.append_only"), engine.begin() as connection:
            connection.execute(
                text("UPDATE audit_log SET action = 'tampered' WHERE id = :id"), {"id": record_id}
            )

    def test_records_cannot_be_deleted(self, engine: Engine) -> None:
        with engine.begin() as connection:
            record_id = self.write_record(connection)
        with rejects("audit.append_only"), engine.begin() as connection:
            connection.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": record_id})

    def test_an_action_is_required(self, engine: Engine) -> None:
        with rejects(sqlstate=CHECK_VIOLATION), engine.begin() as connection:
            connection.execute(
                text("INSERT INTO audit_log (id, action) VALUES (:id, '')"), {"id": uuid7()}
            )
