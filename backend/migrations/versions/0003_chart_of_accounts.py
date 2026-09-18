"""Chart of accounts: the rest of the company defaults, and the hierarchy trigger.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-18

The hierarchy rules follow the ledger's philosophy: the service checks them for a good
message, and the database refuses them whatever the caller is.
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


COLUMNS = """
ALTER TABLE ledger_settings
    ADD COLUMN receivable_account_id             uuid,
    ADD COLUMN payable_account_id                uuid,
    ADD COLUMN outstanding_receipts_account_id   uuid,
    ADD COLUMN outstanding_payments_account_id   uuid,
    ADD COLUMN suspense_account_id               uuid,
    ADD CONSTRAINT ledger_settings_receivable_fkey
        FOREIGN KEY (receivable_account_id, company_id) REFERENCES account (id, company_id),
    ADD CONSTRAINT ledger_settings_payable_fkey
        FOREIGN KEY (payable_account_id, company_id) REFERENCES account (id, company_id),
    ADD CONSTRAINT ledger_settings_outstanding_receipts_fkey
        FOREIGN KEY (outstanding_receipts_account_id, company_id)
        REFERENCES account (id, company_id),
    ADD CONSTRAINT ledger_settings_outstanding_payments_fkey
        FOREIGN KEY (outstanding_payments_account_id, company_id)
        REFERENCES account (id, company_id),
    ADD CONSTRAINT ledger_settings_suspense_fkey
        FOREIGN KEY (suspense_account_id, company_id) REFERENCES account (id, company_id);

CREATE INDEX account_tree ON account (company_id, parent_id, code);
"""


TRIGGER = r"""
-- A parent must be a group account of the same type, and the hierarchy must stay a tree.
CREATE FUNCTION account_hierarchy_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_parent_is_group  boolean;
    v_parent_type      text;
    v_depth            integer;
BEGIN
    IF NEW.parent_id IS NULL THEN
        RETURN NEW;
    END IF;

    IF NEW.parent_id = NEW.id THEN
        RAISE EXCEPTION 'coa.hierarchy_cycle: an account cannot be its own parent';
    END IF;

    SELECT is_group, type INTO v_parent_is_group, v_parent_type
    FROM account WHERE id = NEW.parent_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'coa.parent_not_found: parent account % does not exist', NEW.parent_id;
    END IF;

    IF NOT v_parent_is_group THEN
        RAISE EXCEPTION 'coa.parent_not_group: a parent account must be a group account';
    END IF;

    IF v_parent_type <> NEW.type THEN
        RAISE EXCEPTION 'coa.parent_type_mismatch: parent is % but the account is %',
            v_parent_type, NEW.type;
    END IF;

    -- Walk the ancestors: reaching this account again means a cycle.
    WITH RECURSIVE ancestors(id, parent_id, depth) AS (
        SELECT a.id, a.parent_id, 1 FROM account a WHERE a.id = NEW.parent_id
        UNION ALL
        SELECT a.id, a.parent_id, ancestors.depth + 1
        FROM account a JOIN ancestors ON a.id = ancestors.parent_id
        WHERE ancestors.depth < 20
    )
    SELECT max(depth) INTO v_depth FROM ancestors;

    IF EXISTS (
        WITH RECURSIVE ancestors(id, parent_id, depth) AS (
            SELECT a.id, a.parent_id, 1 FROM account a WHERE a.id = NEW.parent_id
            UNION ALL
            SELECT a.id, a.parent_id, ancestors.depth + 1
            FROM account a JOIN ancestors ON a.id = ancestors.parent_id
            WHERE ancestors.depth < 20
        )
        SELECT 1 FROM ancestors WHERE id = NEW.id
    ) THEN
        RAISE EXCEPTION 'coa.hierarchy_cycle: this parent would make a loop in the chart';
    END IF;

    IF v_depth >= 10 THEN
        RAISE EXCEPTION 'coa.hierarchy_too_deep: the chart is limited to 10 levels';
    END IF;

    RETURN NEW;
END $$;

CREATE TRIGGER account_hierarchy_guard BEFORE INSERT OR UPDATE ON account
    FOR EACH ROW EXECUTE FUNCTION account_hierarchy_guard();


-- An archived account keeps its history but takes no new lines (R3.AC1, R3.AC2).
CREATE FUNCTION journal_entry_line_active_account() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM account WHERE id = NEW.account_id AND NOT active) THEN
        RAISE EXCEPTION 'coa.account_archived: account % is archived', NEW.account_id;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER journal_entry_line_active_account
    BEFORE INSERT OR UPDATE ON journal_entry_line
    FOR EACH ROW EXECUTE FUNCTION journal_entry_line_active_account();
"""


# The catalogue lives in app/platform/access/permissions.py; seeding it here means a
# freshly migrated database is complete without waiting for the application to start.
PERMISSIONS = [
    ("account:read", "See the chart of accounts"),
    ("account:manage", "Create, change and archive accounts and company defaults"),
    ("journal:read", "See the journals"),
    ("journal:manage", "Create, change and archive journals"),
    ("rate:read", "See exchange rates"),
    ("rate:manage", "Enter and import exchange rates"),
    ("chart:load", "Load a ready-made chart of accounts"),
]

SEED = """
INSERT INTO permission (code, description) VALUES {values}
ON CONFLICT (code) DO NOTHING;

INSERT INTO role_permission (role_id, permission_code)
SELECT '019a0000-0000-7000-8000-000000000001', code
FROM permission
WHERE code IN ({codes})
ON CONFLICT DO NOTHING;
"""


def upgrade() -> None:
    op.execute(COLUMNS)
    op.execute(TRIGGER)
    values = ", ".join(
        "('{}', '{}')".format(code, description.replace("'", "''"))
        for code, description in PERMISSIONS
    )
    codes = ", ".join(f"'{code}'" for code, _ in PERMISSIONS)
    op.execute(SEED.format(values=values, codes=codes))


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permission WHERE permission_code IN
            ('account:read', 'account:manage', 'journal:read', 'journal:manage',
             'rate:read', 'rate:manage', 'chart:load');
        DELETE FROM permission WHERE code IN
            ('account:read', 'account:manage', 'journal:read', 'journal:manage',
             'rate:read', 'rate:manage', 'chart:load');
        DROP TRIGGER IF EXISTS journal_entry_line_active_account ON journal_entry_line;
        DROP FUNCTION IF EXISTS journal_entry_line_active_account;
        DROP TRIGGER IF EXISTS account_hierarchy_guard ON account;
        DROP FUNCTION IF EXISTS account_hierarchy_guard;
        DROP INDEX IF EXISTS account_tree;
        ALTER TABLE ledger_settings
            DROP COLUMN IF EXISTS receivable_account_id,
            DROP COLUMN IF EXISTS payable_account_id,
            DROP COLUMN IF EXISTS outstanding_receipts_account_id,
            DROP COLUMN IF EXISTS outstanding_payments_account_id,
            DROP COLUMN IF EXISTS suspense_account_id;
        """
    )
