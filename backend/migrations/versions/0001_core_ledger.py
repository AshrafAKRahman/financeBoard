"""Core ledger: currencies, companies, numbering, accounts, journals, entries, invariants.

Revision ID: 0001
Revises:
Create Date: 2026-09-17

Every trigger raises messages shaped "<module>.<code>: detail" so the application can
translate them into DomainError codes.
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


TABLES = """
CREATE TABLE currency (
    code            char(3) PRIMARY KEY CHECK (code ~ '^[A-Z]{3}$'),
    name            text NOT NULL,
    decimal_places  smallint NOT NULL CHECK (decimal_places BETWEEN 0 AND 4),
    active          boolean NOT NULL DEFAULT true
);

INSERT INTO currency (code, name, decimal_places) VALUES
    ('SAR', 'Saudi Riyal', 2),
    ('USD', 'US Dollar', 2),
    ('EUR', 'Euro', 2),
    ('GBP', 'Pound Sterling', 2),
    ('AED', 'UAE Dirham', 2),
    ('QAR', 'Qatari Riyal', 2),
    ('EGP', 'Egyptian Pound', 2),
    ('CNY', 'Chinese Yuan', 2),
    ('INR', 'Indian Rupee', 2),
    ('KWD', 'Kuwaiti Dinar', 3),
    ('BHD', 'Bahraini Dinar', 3),
    ('OMR', 'Omani Rial', 3),
    ('JPY', 'Japanese Yen', 0);

CREATE TABLE company (
    id                       uuid PRIMARY KEY,
    name                     text NOT NULL,
    base_currency            char(3) NOT NULL REFERENCES currency (code),
    fiscal_year_start_month  smallint NOT NULL DEFAULT 1
                             CHECK (fiscal_year_start_month BETWEEN 1 AND 12),
    vat_number               text,
    cr_number                text,
    lock_date                date,
    x_data                   jsonb NOT NULL DEFAULT '{}',
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sequence_counter (
    company_id   uuid NOT NULL REFERENCES company (id),
    scope        text NOT NULL,
    period       text NOT NULL,
    next_number  bigint NOT NULL CHECK (next_number >= 1),
    PRIMARY KEY (company_id, scope, period)
);

CREATE TABLE exchange_rate (
    id             uuid PRIMARY KEY,
    company_id     uuid NOT NULL REFERENCES company (id),
    currency_code  char(3) NOT NULL REFERENCES currency (code),
    rate_date      date NOT NULL,
    rate           numeric(24, 12) NOT NULL CHECK (rate > 0),
    created_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (company_id, currency_code, rate_date)
);

CREATE TABLE account (
    id               uuid PRIMARY KEY,
    company_id       uuid NOT NULL REFERENCES company (id),
    code             text NOT NULL,
    name             text NOT NULL,
    name_ar          text,
    type             text NOT NULL
                     CHECK (type IN ('asset', 'liability', 'equity', 'income', 'expense')),
    subtype          text NOT NULL,
    parent_id        uuid,
    is_reconcilable  boolean NOT NULL DEFAULT false,
    is_group         boolean NOT NULL DEFAULT false,
    cash_flow_tag    text CHECK (cash_flow_tag IN ('operating', 'investing', 'financing')),
    active           boolean NOT NULL DEFAULT true,
    x_data           jsonb NOT NULL DEFAULT '{}',
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (company_id, code),
    UNIQUE (id, company_id),
    FOREIGN KEY (parent_id, company_id) REFERENCES account (id, company_id),
    CHECK (parent_id IS NULL OR parent_id <> id),
    CHECK (
        (type = 'asset' AND subtype IN
            ('bank_cash', 'receivable', 'current_asset', 'non_current_asset', 'prepayment'))
        OR (type = 'liability' AND subtype IN
            ('payable', 'current_liability', 'non_current_liability'))
        OR (type = 'equity' AND subtype IN ('equity', 'current_year_earnings'))
        OR (type = 'income' AND subtype IN ('income', 'other_income'))
        OR (type = 'expense' AND subtype IN ('cost_of_revenue', 'expense', 'depreciation'))
    ),
    CHECK (subtype NOT IN ('receivable', 'payable') OR is_reconcilable)
);

CREATE TABLE journal (
    id                  uuid PRIMARY KEY,
    company_id          uuid NOT NULL REFERENCES company (id),
    code                text NOT NULL CHECK (code ~ '^[A-Z0-9]{1,8}$'),
    name                text NOT NULL,
    type                text NOT NULL
                        CHECK (type IN ('sales', 'purchases', 'bank', 'cash', 'general')),
    currency_code       char(3) REFERENCES currency (code),
    default_account_id  uuid,
    active              boolean NOT NULL DEFAULT true,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (company_id, code),
    UNIQUE (id, company_id),
    FOREIGN KEY (default_account_id, company_id) REFERENCES account (id, company_id)
);

CREATE TABLE ledger_settings (
    company_id           uuid PRIMARY KEY REFERENCES company (id),
    rounding_account_id  uuid,
    fx_gain_account_id   uuid,
    fx_loss_account_id   uuid,
    FOREIGN KEY (rounding_account_id, company_id) REFERENCES account (id, company_id),
    FOREIGN KEY (fx_gain_account_id, company_id) REFERENCES account (id, company_id),
    FOREIGN KEY (fx_loss_account_id, company_id) REFERENCES account (id, company_id)
);

CREATE TABLE journal_entry (
    id                 uuid PRIMARY KEY,
    company_id         uuid NOT NULL REFERENCES company (id),
    journal_id         uuid NOT NULL,
    number             text,
    date               date NOT NULL,
    ref                text,
    narration          text,
    state              text NOT NULL DEFAULT 'draft' CHECK (state IN ('draft', 'posted')),
    currency_code      char(3) NOT NULL REFERENCES currency (code),
    reversed_entry_id  uuid,
    source_type        text,
    source_id          uuid,
    posted_at          timestamptz,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, company_id),
    FOREIGN KEY (journal_id, company_id) REFERENCES journal (id, company_id),
    FOREIGN KEY (reversed_entry_id, company_id) REFERENCES journal_entry (id, company_id),
    CHECK (state = 'draft' OR (number IS NOT NULL AND posted_at IS NOT NULL)),
    CHECK ((source_type IS NULL) = (source_id IS NULL)),
    CHECK (reversed_entry_id IS NULL OR reversed_entry_id <> id)
);

CREATE UNIQUE INDEX journal_entry_number_uniq
    ON journal_entry (journal_id, number) WHERE number IS NOT NULL;
CREATE UNIQUE INDEX journal_entry_one_reversal
    ON journal_entry (reversed_entry_id) WHERE reversed_entry_id IS NOT NULL;
CREATE UNIQUE INDEX journal_entry_one_per_source
    ON journal_entry (source_type, source_id) WHERE source_id IS NOT NULL;
CREATE INDEX journal_entry_company_date ON journal_entry (company_id, date);

CREATE TABLE journal_entry_line (
    id               uuid PRIMARY KEY,
    entry_id         uuid NOT NULL,
    company_id       uuid NOT NULL,
    line_no          integer NOT NULL,
    account_id       uuid NOT NULL,
    partner_id       uuid,
    name             text,
    debit            numeric(20, 6) NOT NULL DEFAULT 0,
    credit           numeric(20, 6) NOT NULL DEFAULT 0,
    currency_code    char(3) NOT NULL REFERENCES currency (code),
    amount_currency  numeric(20, 6) NOT NULL DEFAULT 0,
    due_date         date,
    tax_id           uuid,
    tax_grid_tag     text,
    x_data           jsonb NOT NULL DEFAULT '{}',
    created_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (entry_id, line_no),
    FOREIGN KEY (entry_id, company_id)
        REFERENCES journal_entry (id, company_id) ON DELETE CASCADE,
    FOREIGN KEY (account_id, company_id) REFERENCES account (id, company_id),
    CHECK (debit >= 0 AND credit >= 0),
    CHECK (debit = 0 OR credit = 0),
    -- the transaction-currency amount never points the opposite way to the company amount
    CHECK ((debit - credit) * amount_currency >= 0)
);

CREATE INDEX journal_entry_line_account ON journal_entry_line (company_id, account_id);
"""


TRIGGERS = r"""
-- Company: base currency is fixed once the company has journal entries.
CREATE FUNCTION company_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.base_currency <> OLD.base_currency
       AND EXISTS (SELECT 1 FROM journal_entry WHERE company_id = OLD.id) THEN
        RAISE EXCEPTION 'ledger.base_currency_locked: company % already has journal entries',
            OLD.id;
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END $$;

CREATE TRIGGER company_guard BEFORE UPDATE ON company
    FOR EACH ROW EXECUTE FUNCTION company_guard();


-- Account: an account that already has journal lines cannot become a group account.
CREATE FUNCTION account_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.is_group AND NOT OLD.is_group
       AND EXISTS (SELECT 1 FROM journal_entry_line WHERE account_id = OLD.id) THEN
        RAISE EXCEPTION 'ledger.account_has_lines: account % has journal lines', OLD.code;
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END $$;

CREATE TRIGGER account_guard BEFORE UPDATE ON account
    FOR EACH ROW EXECUTE FUNCTION account_guard();


-- Journal entry: created as draft, only draft -> posted, posted is immutable.
CREATE FUNCTION journal_entry_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_lock_date date;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.state <> 'draft' THEN
            RAISE EXCEPTION 'ledger.insert_posted: entries are created as draft, then posted';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.state = 'posted' THEN
        RAISE EXCEPTION 'ledger.posted_immutable: posted entry % cannot be %d',
            OLD.number, lower(TG_OP);
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;

    IF NEW.state = 'posted' THEN
        -- FOR SHARE: a concurrent lock-date change waits for this posting (and vice versa).
        SELECT lock_date INTO v_lock_date FROM company WHERE id = NEW.company_id FOR SHARE;
        IF v_lock_date IS NOT NULL AND NEW.date <= v_lock_date THEN
            RAISE EXCEPTION 'ledger.period_locked: entry date % is on or before lock date %',
                NEW.date, v_lock_date;
        END IF;

        IF NEW.reversed_entry_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM journal_entry WHERE id = NEW.reversed_entry_id AND state = 'posted'
        ) THEN
            RAISE EXCEPTION 'ledger.reverse_unposted: only posted entries can be reversed';
        END IF;
    END IF;

    NEW.updated_at := now();
    RETURN NEW;
END $$;

CREATE TRIGGER journal_entry_guard BEFORE INSERT OR UPDATE OR DELETE ON journal_entry
    FOR EACH ROW EXECUTE FUNCTION journal_entry_guard();


-- Journal entry lines: only on draft entries; amounts rounded; base-currency lines consistent.
CREATE FUNCTION journal_entry_line_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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

CREATE TRIGGER journal_entry_line_guard
    BEFORE INSERT OR UPDATE OR DELETE ON journal_entry_line
    FOR EACH ROW EXECUTE FUNCTION journal_entry_line_guard();


-- Balance: checked at COMMIT for every entry that is posted in the transaction.
CREATE FUNCTION journal_entry_balance_check() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_state   text;
    v_lines   bigint;
    v_debit   numeric;
    v_credit  numeric;
    v_ncur    bigint;
    v_amount  numeric;
BEGIN
    SELECT state INTO v_state FROM journal_entry WHERE id = NEW.id;
    IF v_state IS DISTINCT FROM 'posted' THEN
        RETURN NULL;
    END IF;

    SELECT count(*), coalesce(sum(debit), 0), coalesce(sum(credit), 0),
           count(DISTINCT currency_code), coalesce(sum(amount_currency), 0)
    INTO v_lines, v_debit, v_credit, v_ncur, v_amount
    FROM journal_entry_line WHERE entry_id = NEW.id;

    IF v_lines = 0 OR v_debit = 0 THEN
        RAISE EXCEPTION 'ledger.empty_entry: posted entry % has no amounts', NEW.number;
    END IF;

    IF v_debit <> v_credit THEN
        RAISE EXCEPTION 'ledger.unbalanced: entry % debit % credit %',
            NEW.number, v_debit, v_credit;
    END IF;

    IF v_ncur = 1 AND v_amount <> 0 THEN
        RAISE EXCEPTION 'ledger.unbalanced_currency: entry % is off by % in its currency',
            NEW.number, v_amount;
    END IF;

    RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER journal_entry_balance
    AFTER INSERT OR UPDATE ON journal_entry
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION journal_entry_balance_check();
"""


DOWN = """
DROP TABLE IF EXISTS journal_entry_line, journal_entry, ledger_settings, journal, account,
    exchange_rate, sequence_counter, company, currency CASCADE;
DROP FUNCTION IF EXISTS company_guard, account_guard, journal_entry_guard,
    journal_entry_line_guard, journal_entry_balance_check;
"""


def upgrade() -> None:
    op.execute(TABLES)
    op.execute(TRIGGERS)


def downgrade() -> None:
    op.execute(DOWN)
