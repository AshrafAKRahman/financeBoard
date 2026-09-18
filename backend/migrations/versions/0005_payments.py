"""Payments, matching and bank statements.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-18

Two things here belong to the ledger's own table. Posted lines on reconcilable accounts
carry what is still open (`residual`, `residual_currency`, `reconciled`), and a new
`reconciliation` table says which debit settles which credit and by how much. The ledger's
line guard refuses every change to a posted line, so it is replaced with a version that
allows an update touching only those three columns — nothing else about a posted line moves.

A deferred constraint trigger checks at COMMIT that every touched line's open amount is
exactly its amount less what has been matched against it, so raw SQL cannot pay an invoice
twice.
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


PERMISSIONS = [
    ("payment:read", "See payments and what they settle"),
    ("payment:manage", "Record and change draft payments"),
    ("payment:post", "Post, cancel, match and reconcile"),
    ("statement:read", "See imported bank statements"),
    ("statement:import", "Import bank statement files"),
]


LEDGER_COLUMNS = """
ALTER TABLE journal_entry_line
    ADD COLUMN residual           numeric(20, 6),
    ADD COLUMN residual_currency  numeric(20, 6),
    ADD COLUMN reconciled         boolean NOT NULL DEFAULT false,
    -- what reconciliation's composite foreign keys need; the ledger table had no such key
    ADD CONSTRAINT journal_entry_line_id_company_key UNIQUE (id, company_id),
    ADD CONSTRAINT journal_entry_line_residual_sign
        CHECK (residual IS NULL OR residual >= 0),
    ADD CONSTRAINT journal_entry_line_residual_bounds
        CHECK (residual IS NULL OR residual <= abs(debit - credit)),
    ADD CONSTRAINT journal_entry_line_residual_pair
        CHECK ((residual IS NULL) = (residual_currency IS NULL)),
    -- a line with nothing open is reconciled, and only an open-item line can be either
    ADD CONSTRAINT journal_entry_line_reconciled_shape
        CHECK (NOT reconciled OR (residual = 0 AND residual_currency = 0));

CREATE INDEX journal_entry_line_open ON journal_entry_line (company_id, account_id, partner_id)
    WHERE residual IS NOT NULL AND NOT reconciled;
"""


TABLES = """
CREATE TABLE reconciliation (
    id                      uuid PRIMARY KEY,
    company_id              uuid NOT NULL REFERENCES company (id),
    debit_line_id           uuid NOT NULL,
    credit_line_id          uuid NOT NULL,
    -- One match takes a different company-currency amount off each side whenever the rate
    -- moved between the invoice and the payment; the gap is the exchange difference.
    debit_amount            numeric(20, 6) NOT NULL CHECK (debit_amount > 0),
    credit_amount           numeric(20, 6) NOT NULL CHECK (credit_amount > 0),
    debit_amount_currency   numeric(20, 6) NOT NULL DEFAULT 0,
    credit_amount_currency  numeric(20, 6) NOT NULL DEFAULT 0,
    fx_entry_id             uuid,
    matched_at              timestamptz NOT NULL DEFAULT now(),
    matched_by              uuid REFERENCES app_user (id),
    FOREIGN KEY (debit_line_id, company_id)
        REFERENCES journal_entry_line (id, company_id),
    FOREIGN KEY (credit_line_id, company_id)
        REFERENCES journal_entry_line (id, company_id),
    FOREIGN KEY (fx_entry_id, company_id) REFERENCES journal_entry (id, company_id),
    CHECK (debit_line_id <> credit_line_id)
);

CREATE INDEX reconciliation_by_debit ON reconciliation (debit_line_id);
CREATE INDEX reconciliation_by_credit ON reconciliation (credit_line_id);

CREATE TABLE payment (
    id                  uuid PRIMARY KEY,
    company_id          uuid NOT NULL REFERENCES company (id),
    direction           text NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    partner_id          uuid NOT NULL,
    journal_id          uuid NOT NULL,
    number              text,
    date                date NOT NULL,
    amount              numeric(20, 6) NOT NULL CHECK (amount > 0),
    currency_code       char(3) NOT NULL REFERENCES currency (code),
    state               text NOT NULL DEFAULT 'draft'
                        CHECK (state IN ('draft', 'posted', 'cancelled')),
    withholding_tax_id  uuid,
    withheld_amount     numeric(20, 6) NOT NULL DEFAULT 0 CHECK (withheld_amount >= 0),
    reference           text,
    memo                text,
    journal_entry_id    uuid,
    posted_at           timestamptz,
    cancelled_at        timestamptz,
    cancel_reason       text,
    x_data              jsonb NOT NULL DEFAULT '{}',
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, company_id),
    FOREIGN KEY (partner_id, company_id) REFERENCES partner (id, company_id),
    FOREIGN KEY (journal_id, company_id) REFERENCES journal (id, company_id),
    FOREIGN KEY (withholding_tax_id, company_id) REFERENCES tax (id, company_id),
    FOREIGN KEY (journal_entry_id, company_id) REFERENCES journal_entry (id, company_id),
    CHECK (state <> 'posted' OR (number IS NOT NULL AND journal_entry_id IS NOT NULL)),
    CHECK (state = 'draft' OR posted_at IS NOT NULL),
    CHECK (withheld_amount < amount OR withheld_amount = 0)
);

CREATE UNIQUE INDEX payment_number_uniq ON payment (company_id, number)
    WHERE number IS NOT NULL;
CREATE INDEX payment_by_date ON payment (company_id, date DESC);
CREATE INDEX payment_by_partner ON payment (company_id, partner_id);

CREATE TABLE bank_statement (
    id               uuid PRIMARY KEY,
    company_id       uuid NOT NULL REFERENCES company (id),
    bank_account_id  uuid NOT NULL,
    name             text NOT NULL CHECK (name <> ''),
    source_format    text NOT NULL CHECK (source_format IN ('csv', 'mt940', 'ofx')),
    file_name        text,
    opening_balance  numeric(20, 6),
    closing_balance  numeric(20, 6),
    imported_at      timestamptz NOT NULL DEFAULT now(),
    imported_by      uuid REFERENCES app_user (id),
    UNIQUE (id, company_id),
    FOREIGN KEY (bank_account_id, company_id) REFERENCES account (id, company_id)
);

CREATE INDEX bank_statement_by_account ON bank_statement (company_id, bank_account_id);

CREATE TABLE bank_statement_line (
    id                uuid PRIMARY KEY,
    statement_id      uuid NOT NULL,
    company_id        uuid NOT NULL,
    line_no           integer NOT NULL,
    date              date NOT NULL,
    amount            numeric(20, 6) NOT NULL CHECK (amount <> 0),
    currency_code     char(3) NOT NULL REFERENCES currency (code),
    description       text,
    counterparty      text,
    bank_reference    text,
    import_hash       text NOT NULL,
    -- Which occurrence of an identical row this is: two identical payments on one day are
    -- two transactions, but the same file imported twice is not (R7.AC4).
    occurrence        integer NOT NULL DEFAULT 1 CHECK (occurrence >= 1),
    journal_entry_id  uuid,
    payment_id        uuid,
    reconciled_at     timestamptz,
    created_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (statement_id, line_no),
    UNIQUE (id, company_id),
    FOREIGN KEY (statement_id, company_id)
        REFERENCES bank_statement (id, company_id) ON DELETE CASCADE,
    FOREIGN KEY (journal_entry_id, company_id) REFERENCES journal_entry (id, company_id),
    FOREIGN KEY (payment_id, company_id) REFERENCES payment (id, company_id),
    CHECK ((journal_entry_id IS NULL) = (reconciled_at IS NULL))
);

-- Re-importing an overlapping file is normal, so a repeat has to be cheap and certain.
CREATE UNIQUE INDEX bank_statement_line_import_uniq
    ON bank_statement_line (company_id, import_hash, occurrence);
CREATE INDEX bank_statement_line_unreconciled
    ON bank_statement_line (company_id, date) WHERE reconciled_at IS NULL;
"""


TRIGGERS = r"""
-- Replaces the core-ledger guard. Same rules, with one door: a posted line may have its
-- open amount updated, and nothing else.
CREATE OR REPLACE FUNCTION journal_entry_line_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_state        text;
    v_base         char(3);
    v_base_places  smallint;
    v_line_places  smallint;
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        SELECT state INTO v_state FROM journal_entry WHERE id = OLD.entry_id FOR SHARE;
        IF v_state = 'posted' THEN
            IF TG_OP = 'UPDATE'
               AND (NEW.id, NEW.entry_id, NEW.company_id, NEW.line_no, NEW.account_id,
                    NEW.partner_id, NEW.name, NEW.debit, NEW.credit, NEW.currency_code,
                    NEW.amount_currency, NEW.due_date, NEW.tax_id, NEW.tax_grid_tag,
                    NEW.x_data, NEW.created_at)
                   IS NOT DISTINCT FROM
                   (OLD.id, OLD.entry_id, OLD.company_id, OLD.line_no, OLD.account_id,
                    OLD.partner_id, OLD.name, OLD.debit, OLD.credit, OLD.currency_code,
                    OLD.amount_currency, OLD.due_date, OLD.tax_id, OLD.tax_grid_tag,
                    OLD.x_data, OLD.created_at)
            THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'ledger.posted_immutable: lines of posted entry % cannot be changed',
                OLD.entry_id;
        END IF;
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
    END IF;

    -- FOR SHARE conflicts with the UPDATE that posts the entry, so a line can never slip
    -- into an entry that a concurrent transaction is posting.
    SELECT state INTO v_state FROM journal_entry WHERE id = NEW.entry_id FOR SHARE;
    IF v_state = 'posted' THEN
        RAISE EXCEPTION 'ledger.posted_immutable: lines of posted entry % cannot be changed',
            NEW.entry_id;
    END IF;

    SELECT c.base_currency, cur.decimal_places INTO v_base, v_base_places
    FROM company c JOIN currency cur ON cur.code = c.base_currency
    WHERE c.id = NEW.company_id;

    SELECT decimal_places INTO v_line_places FROM currency WHERE code = NEW.currency_code;

    IF NEW.debit <> round(NEW.debit, v_base_places)
       OR NEW.credit <> round(NEW.credit, v_base_places) THEN
        RAISE EXCEPTION 'ledger.unrounded: debit/credit must have at most % decimal places',
            v_base_places;
    END IF;

    IF NEW.amount_currency <> round(NEW.amount_currency, v_line_places) THEN
        RAISE EXCEPTION 'ledger.unrounded: amount_currency must have at most % decimal places',
            v_line_places;
    END IF;

    IF NEW.currency_code = v_base AND NEW.amount_currency <> NEW.debit - NEW.credit THEN
        RAISE EXCEPTION
            'ledger.base_amount_mismatch: amount_currency must equal debit - credit for %', v_base;
    END IF;

    IF EXISTS (SELECT 1 FROM account WHERE id = NEW.account_id AND is_group) THEN
        RAISE EXCEPTION 'ledger.group_account: cannot post to group account %', NEW.account_id;
    END IF;

    RETURN NEW;
END $$;


-- What is open on a line is its amount less what has been matched against it. Checked at
-- COMMIT, so a service may work in any order, and raw SQL cannot over-match.
CREATE FUNCTION check_line_residual(p_line_id uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    v_line             record;
    v_matched          numeric;
    v_matched_currency numeric;
    v_amount           numeric;
    v_amount_currency  numeric;
BEGIN
    SELECT debit, credit, amount_currency, residual, residual_currency, reconciled
    INTO v_line FROM journal_entry_line WHERE id = p_line_id;

    IF NOT FOUND OR v_line.residual IS NULL THEN
        RETURN;
    END IF;

    SELECT coalesce(sum(CASE WHEN debit_line_id = p_line_id
                             THEN debit_amount ELSE credit_amount END), 0),
           coalesce(sum(CASE WHEN debit_line_id = p_line_id
                             THEN debit_amount_currency ELSE credit_amount_currency END), 0)
    INTO v_matched, v_matched_currency
    FROM reconciliation
    WHERE debit_line_id = p_line_id OR credit_line_id = p_line_id;

    v_amount := abs(v_line.debit - v_line.credit);
    v_amount_currency := abs(v_line.amount_currency);

    IF v_matched > v_amount OR v_matched_currency > v_amount_currency THEN
        RAISE EXCEPTION 'payments.over_matched: line % is matched % of %',
            p_line_id, v_matched, v_amount;
    END IF;

    IF v_line.residual <> v_amount - v_matched THEN
        RAISE EXCEPTION 'payments.residual_mismatch: line % is open % but should be %',
            p_line_id, v_line.residual, v_amount - v_matched;
    END IF;

    IF v_line.residual_currency <> v_amount_currency - v_matched_currency THEN
        RAISE EXCEPTION
            'payments.residual_mismatch: line % is open % in its currency but should be %',
            p_line_id, v_line.residual_currency, v_amount_currency - v_matched_currency;
    END IF;

    IF v_line.reconciled <> (v_line.residual = 0 AND v_line.residual_currency = 0) THEN
        RAISE EXCEPTION 'payments.residual_mismatch: line % is flagged % with % open',
            p_line_id, v_line.reconciled, v_line.residual;
    END IF;
END $$;


CREATE FUNCTION reconciliation_residual_check() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        PERFORM check_line_residual(OLD.debit_line_id);
        PERFORM check_line_residual(OLD.credit_line_id);
    END IF;

    IF TG_OP <> 'DELETE' THEN
        PERFORM check_line_residual(NEW.debit_line_id);
        PERFORM check_line_residual(NEW.credit_line_id);
    END IF;

    RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER reconciliation_residual
    AFTER INSERT OR UPDATE OR DELETE ON reconciliation
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION reconciliation_residual_check();


-- The other way in: an open amount changed without a match to justify it.
CREATE FUNCTION line_residual_check() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM check_line_residual(NEW.id);
    RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER journal_entry_line_residual
    AFTER INSERT OR UPDATE ON journal_entry_line
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW
    WHEN (NEW.residual IS NOT NULL)
    EXECUTE FUNCTION line_residual_check();


-- A posted payment is evidence, the same way an issued invoice is: only cancelling changes it.
CREATE FUNCTION payment_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.state <> 'draft' THEN
            RAISE EXCEPTION 'payments.posted_immutable: payment % cannot be deleted', OLD.number;
        END IF;
        RETURN OLD;
    END IF;

    IF OLD.state = 'draft' THEN
        NEW.updated_at := now();
        RETURN NEW;
    END IF;

    IF NEW.state = 'draft' THEN
        RAISE EXCEPTION 'payments.posted_immutable: payment % cannot go back to draft', OLD.number;
    END IF;

    IF (NEW.direction, NEW.partner_id, NEW.journal_id, NEW.number, NEW.date, NEW.amount,
        NEW.currency_code, NEW.withholding_tax_id, NEW.withheld_amount, NEW.journal_entry_id,
        NEW.posted_at)
       IS DISTINCT FROM
       (OLD.direction, OLD.partner_id, OLD.journal_id, OLD.number, OLD.date, OLD.amount,
        OLD.currency_code, OLD.withholding_tax_id, OLD.withheld_amount, OLD.journal_entry_id,
        OLD.posted_at)
    THEN
        RAISE EXCEPTION 'payments.posted_immutable: payment % cannot be changed', OLD.number;
    END IF;

    NEW.updated_at := now();
    RETURN NEW;
END $$;

CREATE TRIGGER payment_guard BEFORE UPDATE OR DELETE ON payment
    FOR EACH ROW EXECUTE FUNCTION payment_guard();
"""


# A database with history must be consistent the moment this migration finishes: every
# posted line on a reconcilable account starts fully open.
BACKFILL = """
UPDATE journal_entry_line l
SET residual = abs(l.debit - l.credit),
    residual_currency = abs(l.amount_currency),
    reconciled = (abs(l.debit - l.credit) = 0)
FROM journal_entry e, account a
WHERE e.id = l.entry_id
  AND e.state = 'posted'
  AND a.id = l.account_id
  AND a.is_reconcilable;
"""


SEED = """
INSERT INTO permission (code, description) VALUES {values}
ON CONFLICT (code) DO NOTHING;

INSERT INTO role_permission (role_id, permission_code)
SELECT '019a0000-0000-7000-8000-000000000001', code
FROM permission WHERE code IN ({codes})
ON CONFLICT DO NOTHING;
"""


ORIGINAL_LINE_GUARD = r"""
CREATE OR REPLACE FUNCTION journal_entry_line_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_state        text;
    v_base         char(3);
    v_base_places  smallint;
    v_line_places  smallint;
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        SELECT state INTO v_state FROM journal_entry WHERE id = OLD.entry_id FOR SHARE;
        IF v_state = 'posted' THEN
            RAISE EXCEPTION 'ledger.posted_immutable: lines of posted entry % cannot be changed',
                OLD.entry_id;
        END IF;
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
    END IF;

    SELECT state INTO v_state FROM journal_entry WHERE id = NEW.entry_id FOR SHARE;
    IF v_state = 'posted' THEN
        RAISE EXCEPTION 'ledger.posted_immutable: lines of posted entry % cannot be changed',
            NEW.entry_id;
    END IF;

    SELECT c.base_currency, cur.decimal_places INTO v_base, v_base_places
    FROM company c JOIN currency cur ON cur.code = c.base_currency
    WHERE c.id = NEW.company_id;

    SELECT decimal_places INTO v_line_places FROM currency WHERE code = NEW.currency_code;

    IF NEW.debit <> round(NEW.debit, v_base_places)
       OR NEW.credit <> round(NEW.credit, v_base_places) THEN
        RAISE EXCEPTION 'ledger.unrounded: debit/credit must have at most % decimal places',
            v_base_places;
    END IF;

    IF NEW.amount_currency <> round(NEW.amount_currency, v_line_places) THEN
        RAISE EXCEPTION 'ledger.unrounded: amount_currency must have at most % decimal places',
            v_line_places;
    END IF;

    IF NEW.currency_code = v_base AND NEW.amount_currency <> NEW.debit - NEW.credit THEN
        RAISE EXCEPTION
            'ledger.base_amount_mismatch: amount_currency must equal debit - credit for %', v_base;
    END IF;

    IF EXISTS (SELECT 1 FROM account WHERE id = NEW.account_id AND is_group) THEN
        RAISE EXCEPTION 'ledger.group_account: cannot post to group account %', NEW.account_id;
    END IF;

    RETURN NEW;
END $$;
"""


def upgrade() -> None:
    op.execute(LEDGER_COLUMNS)
    op.execute(TABLES)
    op.execute(TRIGGERS)
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
        DROP TRIGGER IF EXISTS payment_guard ON payment;
        DROP FUNCTION IF EXISTS payment_guard;
        DROP TRIGGER IF EXISTS reconciliation_residual ON reconciliation;
        DROP TRIGGER IF EXISTS journal_entry_line_residual ON journal_entry_line;
        DROP FUNCTION IF EXISTS reconciliation_residual_check, line_residual_check,
            check_line_residual;
        DROP TABLE IF EXISTS bank_statement_line, bank_statement, reconciliation, payment CASCADE;
        DROP INDEX IF EXISTS journal_entry_line_open;
        ALTER TABLE journal_entry_line
            DROP CONSTRAINT IF EXISTS journal_entry_line_reconciled_shape,
            DROP CONSTRAINT IF EXISTS journal_entry_line_residual_pair,
            DROP CONSTRAINT IF EXISTS journal_entry_line_residual_bounds,
            DROP CONSTRAINT IF EXISTS journal_entry_line_residual_sign,
            DROP CONSTRAINT IF EXISTS journal_entry_line_id_company_key,
            DROP COLUMN IF EXISTS reconciled,
            DROP COLUMN IF EXISTS residual_currency,
            DROP COLUMN IF EXISTS residual;
        """
    )
    op.execute(ORIGINAL_LINE_GUARD)
