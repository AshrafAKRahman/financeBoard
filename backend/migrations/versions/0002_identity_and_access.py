"""Identity and access: users, sessions, invitations, roles, grants, attempts, audit log.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-18

The audit log is append-only in the database, the same way the ledger's posted entries are:
a trigger refuses every UPDATE and DELETE.
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


# The catalogue lives in app/platform/access/permissions.py; these are the codes that
# existed when this migration was written. The application syncs new ones on start-up.
PERMISSIONS = [
    ("user:invite", "Invite people and manage their invitations"),
    ("user:read", "See the list of users"),
    ("user:manage", "Deactivate users and end their sessions"),
    ("role:grant", "Grant and revoke roles in a company"),
    ("role:manage", "Change what a role may do"),
    ("audit:read", "Read a company's audit log"),
]


TABLES = """
CREATE TABLE app_user (
    id                 uuid PRIMARY KEY,
    email              text NOT NULL,
    name               text NOT NULL,
    password_hash      text,
    state              text NOT NULL DEFAULT 'invited'
                       CHECK (state IN ('invited', 'active', 'deactivated')),
    email_verified_at  timestamptz,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (email),
    CHECK (email = lower(btrim(email))),
    CHECK (email <> ''),
    CHECK (name <> ''),
    -- An active account always has a password; an invited one never does yet.
    CHECK (state <> 'active' OR password_hash IS NOT NULL),
    CHECK (state <> 'invited' OR password_hash IS NULL)
);

CREATE TABLE user_session (
    id            uuid PRIMARY KEY,
    user_id       uuid NOT NULL REFERENCES app_user (id),
    token_hash    text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_used_at  timestamptz NOT NULL DEFAULT now(),
    expires_at    timestamptz NOT NULL,
    ended_at      timestamptz,
    user_agent    text,
    ip            inet,
    UNIQUE (token_hash),
    CHECK (expires_at > created_at)
);

CREATE INDEX user_session_open ON user_session (user_id) WHERE ended_at IS NULL;

CREATE TABLE invitation (
    id             uuid PRIMARY KEY,
    user_id        uuid NOT NULL REFERENCES app_user (id),
    token_hash     text NOT NULL,
    created_by     uuid REFERENCES app_user (id),
    created_at     timestamptz NOT NULL DEFAULT now(),
    expires_at     timestamptz NOT NULL,
    accepted_at    timestamptz,
    revoked_at     timestamptz,
    superseded_at  timestamptz,
    UNIQUE (token_hash),
    CHECK (expires_at > created_at)
);

-- At most one invitation per user is open: not accepted, not revoked, not superseded.
CREATE UNIQUE INDEX invitation_one_open ON invitation (user_id)
    WHERE accepted_at IS NULL AND revoked_at IS NULL AND superseded_at IS NULL;

CREATE TABLE permission (
    code         text PRIMARY KEY CHECK (code ~ '^[a-z_]+:[a-z_]+$'),
    description  text NOT NULL
);

CREATE TABLE role (
    id           uuid PRIMARY KEY,
    name         text NOT NULL,
    description  text NOT NULL DEFAULT '',
    is_system    boolean NOT NULL DEFAULT false,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (name)
);

CREATE TABLE role_permission (
    role_id          uuid NOT NULL REFERENCES role (id) ON DELETE CASCADE,
    permission_code  text NOT NULL REFERENCES permission (code),
    PRIMARY KEY (role_id, permission_code)
);

CREATE TABLE user_company_role (
    user_id     uuid NOT NULL REFERENCES app_user (id),
    company_id  uuid NOT NULL REFERENCES company (id),
    role_id     uuid NOT NULL REFERENCES role (id),
    granted_at  timestamptz NOT NULL DEFAULT now(),
    granted_by  uuid REFERENCES app_user (id),
    PRIMARY KEY (user_id, company_id, role_id)
);

CREATE INDEX user_company_role_by_user ON user_company_role (user_id);

CREATE TABLE login_attempt (
    id            uuid PRIMARY KEY,
    email         text NOT NULL,
    attempted_at  timestamptz NOT NULL DEFAULT now(),
    succeeded     boolean NOT NULL,
    ip            inet
);

CREATE INDEX login_attempt_by_email ON login_attempt (email, attempted_at DESC);

CREATE TABLE audit_log (
    id             uuid PRIMARY KEY,
    at             timestamptz NOT NULL DEFAULT now(),
    actor_user_id  uuid REFERENCES app_user (id),
    actor_email    text,
    company_id     uuid REFERENCES company (id),
    action         text NOT NULL CHECK (action <> ''),
    target_type    text,
    target_id      text,
    detail         jsonb NOT NULL DEFAULT '{}'
);

CREATE INDEX audit_log_by_company ON audit_log (company_id, at DESC);
CREATE INDEX audit_log_by_action ON audit_log (action, at DESC);
"""


TRIGGERS = r"""
-- The audit log only ever grows.
CREATE FUNCTION audit_log_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit.append_only: audit records cannot be %d', lower(TG_OP);
END $$;

CREATE TRIGGER audit_log_guard BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_guard();
"""


SEED = """
INSERT INTO permission (code, description) VALUES {values};

INSERT INTO role (id, name, description, is_system)
VALUES (
    '019a0000-0000-7000-8000-000000000001',
    'Administrator',
    'Every permission in the system',
    true
);

INSERT INTO role_permission (role_id, permission_code)
SELECT '019a0000-0000-7000-8000-000000000001', code FROM permission;
"""


def upgrade() -> None:
    op.execute(TABLES)
    op.execute(TRIGGERS)
    # Descriptions may contain apostrophes, so double them for the literal.
    values = ", ".join(
        "('{}', '{}')".format(code, description.replace("'", "''"))
        for code, description in PERMISSIONS
    )
    op.execute(SEED.format(values=values))


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS audit_log, login_attempt, user_company_role, role_permission,
            role, permission, invitation, user_session, app_user CASCADE;
        DROP FUNCTION IF EXISTS audit_log_guard;
        """
    )
