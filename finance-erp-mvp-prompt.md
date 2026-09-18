# Prompt: Build a Finance ERP for Saudi Arabia (Odoo-style), in Phases

You are building a standalone finance-centric ERP, functionally inspired by Odoo's
Accounting, Inventory, Point of Sale, Payroll and Studio apps, but implemented from
scratch as an original system (do not copy Odoo's UI, branding, or source code —
build the functionality from first principles of double-entry accounting).

The system is delivered in **four phases**. Phase 1 is the MVP. Each phase must be
complete — tests passing, ledger postings correct — before the next one starts.

## Target market: Saudi Arabia

Localization is not an add-on; it shapes Phase 1.

- **Base currency**: SAR (2 decimal places / halalas). Multi-currency still required.
- **VAT**: standard 15%, plus zero-rated, exempt and out-of-scope categories.
  Rates and categories must be data, not code.
- **ZATCA e-invoicing (FATOORA)**: tax invoices must be issued in ZATCA-compliant
  form — UBL 2.1 XML, cryptographic stamp, QR code, invoice hash chain, and
  onboarding of each issuing device/solution (CSID). Standard (B2B) invoices go
  through **clearance** before being shared with the buyer; simplified (B2C)
  invoices are **reported** within 24 hours. Credit and debit notes follow the
  same rules.
- **Language**: Arabic and English, full RTL support in the UI. Tax invoices must
  carry the required Arabic content.
- **Calendar**: Gregorian for transactions and ZATCA; fiscal year start configurable
  per company; Hijri date display as an option.
- **Withholding tax** on payments to non-residents (rate depends on payment type).
- **Zakat** (and corporate income tax for foreign-owned share) reporting.
- **Payroll**: GOSI contributions (Saudi vs non-Saudi rules), End-of-Service
  Benefit accruals per Saudi Labor Law, and WPS salary files via Mudad.

All statutory rates (VAT, withholding, GOSI, EOSB) change over time — store them as
effective-dated configuration and verify current values against official sources
(ZATCA, GOSI, MHRSD) at build time. Do not hard-code them.

## Payments landscape

- **Moyasar** — online payments (mada, Visa/Mastercard, Apple Pay, STC Pay):
  payment links on invoices, webhooks, refunds, settlement reconciliation.
- **Geidea** — in-store card terminals. Each terminal is identified by its
  **TID** (Terminal ID) and **MID** (Merchant ID), printed at the top of every slip.
  Register terminals by TID/MID per company/branch; use them to match terminal
  transactions and settlement reports to POS sessions and bank deposits.
  Confirm the terminal integration method (ECR / cloud API) with Geidea before
  building the POS link.
- **Bank feeds** — provider not yet chosen. Start with statement file import
  (CSV / MT940 / OFX as supported by Saudi banks). In Phase 2, evaluate
  SAMA-licensed open-banking providers (e.g. Lean Technologies, Tarabut) and
  present a recommendation before integrating.

## Phase 1 — Core finance MVP (ledger-first)

Do not start with invoicing UI or dashboards — the ledger and the documents that post
into it come first, and the screens come once there is something correct to show. Build in
this order:

1. **Core ledger engine**: `accounts`, `journals`, `journal_entries`,
   `journal_entry_lines`. Enforce double-entry invariants at the data layer, not
   just in application code (e.g. deferred constraint triggers in PostgreSQL).
2. **Chart of accounts**: account types plus subtypes (bank/cash, receivable,
   payable, current/non-current asset & liability, etc. — needed by reports),
   parent/child hierarchy, default accounts per company. Ship a default Saudi
   chart of accounts template.
3. **Multi-currency**: currency table, company-scoped exchange rates with
   date-based lookup. Every line stores the transaction-currency amount and the
   company-currency amount at the rate on the posting date. Realized FX
   gain/loss entries on settlement at a different rate.
4. **Invoicing/billing**: customer invoices, vendor bills, credit notes and debit
   notes as documents that generate a journal entry on posting. Gapless numbering
   per journal. Recurring billing as a scheduler that spawns draft invoices from
   a template.
5. **Taxes & ZATCA**: tax definitions (rate, type — sales, purchase, withholding;
   VAT category; effective dates), applied per invoice line, generating tax
   journal lines automatically. ZATCA e-invoicing: XML generation, signing, QR,
   hash chain, clearance/reporting API with retry queue, sandbox onboarding.
6. **Payments & reconciliation**: manual payments, bank statement file import,
   and a reconciliation flow that matches payments to open invoices/bills,
   partially or fully, posting the corresponding journal entries.
7. **Reporting**: P&L, Balance Sheet, Cash Flow, Aged Receivables/Payables, and
   the VAT return — read-only queries over posted journal entries, never
   separately maintained data. If a report doesn't reconcile to the ledger,
   that's a bug.
8. **Multi-company**: company as a first-class entity; every record scoped to a
   company.
9. **Data export**: every list a person can read, they can also take away as CSV —
   invoices, bills, payments, journal entries, statement lines, open items and every
   report. Exporting needs no new permission: whoever may read the list may export it,
   and the export obeys the same company scoping and filters as the screen it came
   from. An export is recorded in the audit log, because a file of customer data
   leaving the system is worth knowing about.
10. **Frontend — Phase 1 screens**: the ERP is not delivered until a person can use it
   without curl. Chart of accounts, partners, invoices and bills, payments, the
   matching screen, bank reconciliation, and the reports with basic charts (revenue
   over time, receivables ageing). Arabic/English and RTL from the first screen, not
   retrofitted. Money is formatted, never recomputed, in the browser.
11. **Document capture**: attach the source document to what it records, and stop
   retyping it.
   - Attachments on any document, stored in object storage, never in the database.
   - **Saudi receipts and simplified invoices are read from their ZATCA QR code**,
     which carries seller name, VAT number, timestamp, total and VAT amount as
     TLV-encoded fields. That is exact data, not a guess, and it is the primary path.
   - A vision model is the fallback for foreign and non-compliant documents, and for
     the line detail a QR does not carry.
   - Extraction always produces a **draft** for a person to confirm before it posts.
     Nothing reaches the ledger because a model was confident.
12. **Foundations for later phases** (designed now, built minimally):
   - Role-based permissions model with company scoping (single admin role is
     acceptable for Phase 1 UI, but every API goes through the permission layer).
   - Document state machine with a pluggable "to approve" hook.
   - Metadata/extension layer so custom fields and custom record types can be
     added in Phase 3 without schema rewrites.
   - Arabic/English i18n and RTL in the frontend from the first screen.

## Phase 2 — Operations & integrations

1. **Detailed permissions**: roles, record rules (e.g. by company/branch/owner),
   field-level restrictions, audit log of sensitive actions.
2. **Approval workflows**: multi-level approvals on bills, payments, purchase
   documents and journal entries, configurable by amount, document type, and role.
3. **Inventory**: products, warehouses/locations, stock moves, receipts and
   deliveries. Stock valuation (FIFO and average cost) posting to inventory,
   goods-received-not-invoiced and COGS accounts.
4. **Moyasar integration**: payment links on invoices, webhook-driven payment
   recording, refunds, fees posted to an expense account, clearing account for
   pending settlements, settlement reconciliation.
5. **Geidea settlement reconciliation**: terminal registry (TID/MID), import of
   terminal transactions/settlements, matching to bank deposits, fee posting.
6. **Live bank feeds**: provider evaluation + integration; feeds replace file
   import as the source of statement lines, reconciliation logic unchanged.
7. **Advanced reporting dashboards**: KPIs, drill-down from any figure to the
   underlying journal lines, filters by company/branch/period. Any cached or
   pre-aggregated data must be fully rebuildable from posted entries.
8. **Zakat** computation support report.

## Phase 3 — POS, payroll, studio

1. **Point of Sale (online)**: sessions per register, cash control, Geidea
   terminal integration for card payments (tagged with TID/MID), ZATCA simplified
   invoices with QR on receipts, returns. One journal entry per session close;
   cash differences to a configured account.
2. **Payroll (Saudi)**: employees, contracts, salary structures and allowances,
   payslips posting salary expense and liabilities, GOSI contributions,
   End-of-Service Benefit accruals and settlements, WPS/Mudad salary file export.
3. **Studio / customization**:
   - Custom fields on existing models.
   - **User-defined record types** (new models with their own fields, views,
     lists and forms).
   - **Automations**: triggers (on create/update/state change/schedule),
     conditions, and actions (update fields, create records, send notifications,
     call webhooks).
   - Customizations run through the same permission and service layer as core
     code and can never bypass ledger invariants (e.g. cannot edit a posted entry
     or write journal lines directly).

## Phase 4 — Enhancements

1. **Offline POS**: local queue of orders and payments when the connection drops,
   sync and conflict handling on reconnect, simplified-invoice QR generated
   offline and reported to ZATCA within the 24-hour window.
2. **Inter-company transactions** with automatic mirrored entries.

## Core data model requirements

- `company` (id, name, base_currency, fiscal_year_start, vat_number, cr_number)
- `currency` + `exchange_rate` (company_id, currency_id, rate_date, rate_to_base)
- `account` (id, company_id, code, name, type [asset/liability/equity/income/expense],
  subtype, parent_id, is_reconcilable)
- `journal` (id, company_id, name, type [sales/purchases/bank/cash/general])
- `journal_entry` (id, company_id, journal_id, date, ref, state [draft/posted],
  currency_id, reversed_entry_id)
- `journal_entry_line` (id, entry_id, account_id, debit, credit, currency_id,
  amount_currency, partner_id, reconciled_flag)
- `partner` (customers/vendors — id, company_id, name, type, vat_number, address
  fields required by ZATCA)
- `invoice` (id, company_id, partner_id, type [customer_invoice/vendor_bill/
  credit_note/debit_note], zatca_type [standard/simplified], date, due_date,
  currency_id, state [draft/posted/cancelled], payment_state (derived from
  reconciliation), zatca_status, journal_entry_id when posted)
- `invoice_line` (invoice_id, product/description, quantity, unit_price,
  tax_ids, account_id)
- `tax` (id, company_id, name, rate, type, vat_category, effective_from,
  effective_to, account_id)
- `payment` (id, company_id, partner_id, amount, currency_id, date,
  journal_id, journal_entry_id, provider [manual/moyasar/geidea/bank_feed],
  provider_ref)
- `reconciliation` (links payment lines to invoice/bill lines, tracks
  matched amount)
- `payment_terminal` (id, company_id, branch, provider, tid, mid)

Later phases add their own models (products, stock moves, POS sessions,
employees, payslips, custom model/field metadata, automation rules) — define them
in the architecture doc for the phase before building it.

State transitions (draft → posted, etc.) must be explicit and enforced — never
allow editing a posted journal entry; corrections go through reversal entries.

## Non-negotiable invariants

- A posted journal entry's lines must always balance (debits = credits) in company
  base currency. When all lines share one transaction currency, they must also
  balance in that currency.
- Only draft documents are editable. Posting is one-way (reversible only via a new
  offsetting entry, never an in-place edit).
- Every financial document (invoice, bill, payment, POS session, payslip, stock
  valuation) that hits the books has exactly one corresponding journal entry — no
  report may read from anywhere except posted journal entries.
- All monetary values stored with explicit currency + precision; no floats for
  money — use decimal/fixed-point types.
- ZATCA-issued invoices are immutable once cleared/reported; corrections only via
  credit/debit notes.

## Tech stack

Propose a stack and confirm before scaffolding, but default to:

- **Backend**: Node.js/TypeScript (NestJS) or Python (FastAPI) with PostgreSQL
- **ORM**: one with strong transaction support and easy raw-SQL migrations for
  constraint triggers (TypeORM or SQLAlchemy/Alembic preferred over Prisma)
- **Job queue**: needed for recurring billing, ZATCA submission retries, webhooks,
  bank feed sync and automations
- **Frontend**: React + TypeScript with Arabic/RTL support; simple and functional
  over polished
- **API**: REST or GraphQL, your call — but document the choice

Check that the chosen backend has solid libraries for ZATCA's cryptographic
requirements (ECDSA secp256k1 keys/CSR, XML canonicalization and signing) before
committing to it.

## Deliverables

Phase 1:
1. Architecture doc (data model diagram, module boundaries, permission model,
   extension/metadata layer, ZATCA flow) before writing code.
2. Ledger engine + chart of accounts, with tests proving the debit/credit
   invariant, gapless numbering, and reconciliation amounts hold under
   concurrent posting.
3. Invoicing + VAT + ZATCA e-invoicing (against the ZATCA sandbox) + payment/
   reconciliation flows, each posting correctly to the ledger.
4. The core reports and VAT return, each demonstrably reconciling to ledger totals.
5. Seed data for a demo Saudi company with sample transactions so the whole flow
   can be verified end to end.

Phases 2–4: for each phase, an architecture addendum first, then modules with
tests proving their ledger postings, and extended seed data covering the new flows.

## Working style

- Work phase by phase and module by module in the order above; don't move on
  until the current module's tests pass and its ledger postings are correct.
- Flag any judgment call on accounting or compliance semantics rather than silently
  picking one. Known ones to resolve up front:
  - Tax rounding: per line vs per invoice total.
  - Tax-inclusive vs tax-exclusive prices.
  - Partial payments in a foreign currency and realized FX gain/loss.
  - Unrealized FX revaluation at period end.
  - Cash Flow method (direct vs indirect).
  - Period lock dates and year-end close to retained earnings.
  - Storage approach for user-defined record types (JSONB vs runtime-generated
    tables).
- Ask before introducing new major dependencies or changing the proposed stack.
