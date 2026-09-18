"""Reporting: the basis a VAT return needs, and the permission to read reports.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-18

A tax line records how much tax was charged but not what it was charged on, and a
zero-rated supply records nothing at all — its tax line is worth 0.00 and is dropped to
respect the ledger's rule against empty lines. So ZATCA return boxes 3 to 5 could not be
built from posted entries, and boxes 1 and 7 could only be reverse-engineered by dividing
by the rate.

`tax_base` fixes that: the amount a tax was charged on, recorded beside the grid tag that
says which box it belongs to. Where a tax is worth nothing, posting puts the tag and the
basis on the base line instead, so the supply is still reportable.
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


PERMISSIONS = [
    ("report:read", "Read the financial reports"),
]


COLUMN = """
ALTER TABLE journal_entry_line
    ADD COLUMN tax_base numeric(20, 6),
    -- A basis with no tag belongs to no return box, so it could never be reported.
    ADD CONSTRAINT journal_entry_line_tax_base_tagged
        CHECK (tax_base IS NULL OR tax_grid_tag IS NOT NULL);

CREATE INDEX journal_entry_line_tax_grid ON journal_entry_line (company_id, tax_grid_tag)
    WHERE tax_grid_tag IS NOT NULL;
"""


# Books that already exist should report correctly. Where a tax has a rate, the basis
# follows from the amount; where it is zero-rated, nothing was recorded at posting time and
# nothing can be recovered — the return lists those as untagged rather than inventing them.
BACKFILL = """
UPDATE journal_entry_line l
SET tax_base = round(abs(l.debit - l.credit) * 100 / t.rate, 6)
FROM tax t
WHERE t.id = l.tax_id
  AND l.tax_grid_tag IS NOT NULL
  AND l.tax_base IS NULL
  AND t.rate > 0;
"""


SEED = """
INSERT INTO permission (code, description) VALUES {values}
ON CONFLICT (code) DO NOTHING;

INSERT INTO role_permission (role_id, permission_code)
SELECT '019a0000-0000-7000-8000-000000000001', code
FROM permission WHERE code IN ({codes})
ON CONFLICT DO NOTHING;
"""


def upgrade() -> None:
    op.execute(COLUMN)
    op.execute(BACKFILL)
    values = ", ".join(
        "('{}', '{}')".format(code, description.replace("'", "''"))
        for code, description in PERMISSIONS
    )
    codes = ", ".join(f"'{code}'" for code, _ in PERMISSIONS)
    op.execute(SEED.format(values=values, codes=codes))


def downgrade() -> None:
    codes = ", ".join(f"'{code}'" for code, _ in PERMISSIONS)
    op.execute(
        f"""
        DELETE FROM role_permission WHERE permission_code IN ({codes});
        DELETE FROM permission WHERE code IN ({codes});
        DROP INDEX IF EXISTS journal_entry_line_tax_grid;
        ALTER TABLE journal_entry_line
            DROP CONSTRAINT IF EXISTS journal_entry_line_tax_base_tagged,
            DROP COLUMN IF EXISTS tax_base;
        """
    )
