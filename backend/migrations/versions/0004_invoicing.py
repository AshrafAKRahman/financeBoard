"""Invoicing and VAT: partners, taxes, documents, lines and recurring templates.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-18

Posted documents are immutable, the same way posted journal entries are: a trigger refuses
edits and deletions, so an issued invoice cannot be quietly rewritten.
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


PERMISSIONS = [
    ("partner:read", "See customers and vendors"),
    ("partner:manage", "Create and change customers and vendors"),
    ("tax:read", "See tax definitions"),
    ("tax:manage", "Create and change tax definitions"),
    ("invoice:read", "See invoices, bills and notes"),
    ("invoice:manage", "Create and change draft documents"),
    ("invoice:post", "Issue and cancel documents"),
]


TABLES = """
CREATE TABLE partner (
    id          uuid PRIMARY KEY,
    company_id  uuid NOT NULL REFERENCES company (id),
    name        text NOT NULL CHECK (name <> ''),
    name_ar     text,
    type        text NOT NULL CHECK (type IN ('customer', 'vendor', 'both')),
    vat_number  text,
    cr_number   text,
    address     jsonb NOT NULL DEFAULT '{}',
    email       text,
    phone       text,
    active      boolean NOT NULL DEFAULT true,
    x_data      jsonb NOT NULL DEFAULT '{}',
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, company_id)
);

CREATE UNIQUE INDEX partner_vat_number_uniq ON partner (company_id, vat_number)
    WHERE vat_number IS NOT NULL;
CREATE INDEX partner_by_name ON partner (company_id, name);

CREATE TABLE tax (
    id                uuid PRIMARY KEY,
    company_id        uuid NOT NULL REFERENCES company (id),
    name              text NOT NULL CHECK (name <> ''),
    name_ar           text,
    rate              numeric(6, 3) NOT NULL CHECK (rate >= 0 AND rate <= 100),
    type              text NOT NULL CHECK (type IN ('sale', 'purchase', 'withholding')),
    vat_category      text NOT NULL DEFAULT 'standard'
                      CHECK (vat_category IN ('standard', 'zero_rated', 'exempt', 'out_of_scope')),
    exemption_reason  text,
    account_id        uuid,
    grid_tag          text,
    effective_from    date,
    effective_to      date,
    active            boolean NOT NULL DEFAULT true,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, company_id),
    UNIQUE (company_id, name),
    FOREIGN KEY (account_id, company_id) REFERENCES account (id, company_id),
    -- Anything but a standard rate must say why, because the invoice has to print it.
    CHECK (vat_category = 'standard' OR exemption_reason IS NOT NULL),
    CHECK (effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from)
);

CREATE TABLE document (
    id                   uuid PRIMARY KEY,
    company_id           uuid NOT NULL REFERENCES company (id),
    type                 text NOT NULL
                         CHECK (type IN ('out_invoice', 'in_bill', 'out_credit', 'in_debit')),
    partner_id           uuid NOT NULL,
    journal_id           uuid NOT NULL,
    number               text,
    date                 date NOT NULL,
    due_date             date,
    currency_code        char(3) NOT NULL REFERENCES currency (code),
    state                text NOT NULL DEFAULT 'draft'
                         CHECK (state IN ('draft', 'posted', 'cancelled')),
    tax_inclusive        boolean NOT NULL DEFAULT false,
    origin_document_id   uuid,
    vendor_reference     text,
    narration            text,
    journal_entry_id     uuid,
    posted_at            timestamptz,
    cancelled_at         timestamptz,
    cancel_reason        text,
    x_data               jsonb NOT NULL DEFAULT '{}',
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, company_id),
    FOREIGN KEY (partner_id, company_id) REFERENCES partner (id, company_id),
    FOREIGN KEY (journal_id, company_id) REFERENCES journal (id, company_id),
    FOREIGN KEY (origin_document_id, company_id) REFERENCES document (id, company_id),
    FOREIGN KEY (journal_entry_id, company_id)
        REFERENCES journal_entry (id, company_id),
    CHECK (state <> 'posted' OR (number IS NOT NULL AND journal_entry_id IS NOT NULL)),
    CHECK (state = 'draft' OR posted_at IS NOT NULL),
    CHECK (due_date IS NULL OR due_date >= date)
);

CREATE UNIQUE INDEX document_number_uniq ON document (company_id, type, number)
    WHERE number IS NOT NULL;
CREATE UNIQUE INDEX document_vendor_reference_uniq ON document (partner_id, vendor_reference)
    WHERE vendor_reference IS NOT NULL;
CREATE INDEX document_by_date ON document (company_id, date DESC);
CREATE INDEX document_by_partner ON document (company_id, partner_id);

CREATE TABLE document_line (
    id                uuid PRIMARY KEY,
    document_id       uuid NOT NULL,
    company_id        uuid NOT NULL,
    line_no           integer NOT NULL,
    description       text NOT NULL CHECK (description <> ''),
    description_ar    text,
    quantity          numeric(20, 6) NOT NULL CHECK (quantity >= 0),
    unit_price        numeric(20, 6) NOT NULL CHECK (unit_price >= 0),
    discount_percent  numeric(6, 3) NOT NULL DEFAULT 0
                      CHECK (discount_percent >= 0 AND discount_percent <= 100),
    account_id        uuid NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, line_no),
    UNIQUE (id, company_id),
    FOREIGN KEY (document_id, company_id)
        REFERENCES document (id, company_id) ON DELETE CASCADE,
    FOREIGN KEY (account_id, company_id) REFERENCES account (id, company_id)
);

CREATE TABLE document_line_tax (
    line_id     uuid NOT NULL,
    tax_id      uuid NOT NULL,
    company_id  uuid NOT NULL,
    PRIMARY KEY (line_id, tax_id),
    FOREIGN KEY (line_id, company_id)
        REFERENCES document_line (id, company_id) ON DELETE CASCADE,
    FOREIGN KEY (tax_id, company_id) REFERENCES tax (id, company_id)
);

CREATE TABLE recurring_template (
    id                  uuid PRIMARY KEY,
    company_id          uuid NOT NULL REFERENCES company (id),
    name                text NOT NULL CHECK (name <> ''),
    partner_id          uuid NOT NULL,
    journal_id          uuid NOT NULL,
    currency_code       char(3) NOT NULL REFERENCES currency (code),
    tax_inclusive       boolean NOT NULL DEFAULT false,
    interval_months     integer NOT NULL CHECK (interval_months BETWEEN 1 AND 12),
    next_date           date NOT NULL,
    last_generated_for  date,
    lines               jsonb NOT NULL DEFAULT '[]',
    active              boolean NOT NULL DEFAULT true,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (partner_id, company_id) REFERENCES partner (id, company_id),
    FOREIGN KEY (journal_id, company_id) REFERENCES journal (id, company_id)
);

CREATE INDEX recurring_template_due ON recurring_template (company_id, next_date)
    WHERE active;
"""


TRIGGERS = r"""
-- An issued document is evidence: only its state may change after posting.
CREATE FUNCTION document_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.state <> 'draft' THEN
            RAISE EXCEPTION 'invoicing.posted_immutable: document % cannot be deleted', OLD.number;
        END IF;
        RETURN OLD;
    END IF;

    IF OLD.state = 'draft' THEN
        NEW.updated_at := now();
        RETURN NEW;
    END IF;

    IF NEW.state = 'draft' THEN
        RAISE EXCEPTION 'invoicing.posted_immutable: document % cannot go back to draft',
            OLD.number;
    END IF;

    -- Cancelling is the only change an issued document accepts.
    IF (NEW.type, NEW.partner_id, NEW.journal_id, NEW.number, NEW.date, NEW.due_date,
        NEW.currency_code, NEW.tax_inclusive, NEW.origin_document_id, NEW.vendor_reference,
        NEW.journal_entry_id, NEW.posted_at)
       IS DISTINCT FROM
       (OLD.type, OLD.partner_id, OLD.journal_id, OLD.number, OLD.date, OLD.due_date,
        OLD.currency_code, OLD.tax_inclusive, OLD.origin_document_id, OLD.vendor_reference,
        OLD.journal_entry_id, OLD.posted_at)
    THEN
        RAISE EXCEPTION 'invoicing.posted_immutable: document % cannot be changed', OLD.number;
    END IF;

    NEW.updated_at := now();
    RETURN NEW;
END $$;

CREATE TRIGGER document_guard BEFORE UPDATE OR DELETE ON document
    FOR EACH ROW EXECUTE FUNCTION document_guard();


-- Lines of an issued document are frozen with it.
CREATE FUNCTION document_line_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_state text;
BEGIN
    SELECT state INTO v_state FROM document
    WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.document_id ELSE NEW.document_id END
    FOR SHARE;

    IF v_state IS NOT NULL AND v_state <> 'draft' THEN
        RAISE EXCEPTION 'invoicing.posted_immutable: lines of an issued document are fixed';
    END IF;

    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END $$;

CREATE TRIGGER document_line_guard BEFORE INSERT OR UPDATE OR DELETE ON document_line
    FOR EACH ROW EXECUTE FUNCTION document_line_guard();
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
    op.execute(TABLES)
    op.execute(TRIGGERS)
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
        DROP TRIGGER IF EXISTS document_line_guard ON document_line;
        DROP FUNCTION IF EXISTS document_line_guard;
        DROP TRIGGER IF EXISTS document_guard ON document;
        DROP FUNCTION IF EXISTS document_guard;
        DROP TABLE IF EXISTS recurring_template, document_line_tax, document_line, document,
            tax, partner CASCADE;
        """
    )
