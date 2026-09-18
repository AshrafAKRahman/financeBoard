---
status: approved
approved_at: 2026-09-18T09:39:32Z
last_modified: 2026-09-18T09:39:32Z
---

# Requirements Document

## Introduction

The chart of accounts is Phase 1, module 2 of the Saudi finance ERP: the layer accountants
actually manage on top of the core ledger. It covers creating and organising accounts,
their parent/child hierarchy, the journals that group entries, the default accounts each
company posts to automatically, exchange rates, and a ready-made Saudi chart so a new
company can start keeping books the day it is created.

The core ledger (`.walden/specs/core-ledger`) already owns the `account`, `journal`,
`ledger_settings` and `exchange_rate` tables and every posting invariant. This feature adds
the rules and operations around them; it changes no posting behaviour.

It is also the first feature people reach through the API. `identity-and-access` is built,
so every endpoint here is company-scoped, states the permission it needs, and inherits
session handling, the origin check and problem-details errors from that layer.

<!-- decided 2026-09-18: this feature now includes its HTTP API, because identity-and-access shipped first and provides sessions, permissions, company scoping and the origin check -->
<!-- assumed: every endpoint is company-scoped under /api/v1/companies/{company_id}/… so identity's company rules apply unchanged -->
<!-- assumed: hierarchy stays parent/child on account with group accounts that cannot be posted to, as the ledger schema and docs/architecture.md §6.3 already establish -->
<!-- assumed: the Saudi chart template is a starter set covering what Phase 1 needs (receivables, payables, bank and cash, VAT input/output, withholding tax payable, Zakat and end-of-service provisions, GOSI payable, revenue, cost of revenue, expenses, FX gain/loss, rounding, retained and current-year earnings), bilingual Arabic/English, and is editable after loading rather than locked -->
<!-- assumed: archiving (active = false) replaces deletion for accounts that have been used, matching the ledger's no-hard-deletes rule -->

## Requirements

### R1 Account creation and editing

**User Story:** As an accountant, I want to create and edit accounts, so that the chart matches how my company reports.

#### Acceptance Criteria

1. `R1.AC1` WHEN an accountant submits a new account with a code, name, type and subtype, the system SHALL create it for that company.
2. `R1.AC2` WHEN an accountant submits an account without an Arabic name, the system SHALL create it with the Arabic name empty.
3. `R1.AC3` WHEN an accountant renames an account, the system SHALL keep its code, type and subtype unchanged.
4. `R1.AC4` IF an accountant submits an account code that another account in the same company already uses, THEN the system SHALL reject it with error code `coa.duplicate_code`.
5. `R1.AC5` IF an accountant submits an account whose subtype does not belong to its type, THEN the system SHALL reject it with error code `coa.invalid_subtype`.
6. `R1.AC6` IF an accountant submits an account with an empty code or name, THEN the system SHALL reject it with error code `coa.missing_field`.
7. `R1.AC7` IF an accountant changes the type or subtype of an account that has posted journal lines, THEN the system SHALL reject the change with error code `coa.account_in_use`.
8. `R1.AC8` WHERE an account has no posted journal lines, the system SHALL allow its type and subtype to be changed.

### R2 Account hierarchy

**User Story:** As a finance controller, I want accounts grouped under parent accounts, so that reports roll up into readable sections.

#### Acceptance Criteria

1. `R2.AC1` WHEN an accountant sets an account's parent, the system SHALL record the account under that parent.
2. `R2.AC2` The system SHALL allow postings only to accounts that are not group accounts.
3. `R2.AC3` IF an accountant sets a parent that is not a group account, THEN the system SHALL reject it with error code `coa.parent_not_group`.
4. `R2.AC4` IF an accountant sets a parent whose type differs from the account's type, THEN the system SHALL reject it with error code `coa.parent_type_mismatch`.
5. `R2.AC5` IF an accountant sets a parent that would create a cycle, THEN the system SHALL reject it with error code `coa.hierarchy_cycle`.
6. `R2.AC6` IF an accountant sets a parent that belongs to another company, THEN the system SHALL reject it with error code `coa.parent_not_found`.
7. `R2.AC7` WHEN an accountant requests the chart of accounts, the system SHALL return the accounts in code order within each parent, with their depth.
8. `R2.AC8` IF an accountant turns an account that has child accounts into a posting account, THEN the system SHALL reject it with error code `coa.has_children`.

### R3 Archiving instead of deleting

**User Story:** As an auditor, I want used accounts kept forever, so that historical entries always resolve to a real account.

#### Acceptance Criteria

1. `R3.AC1` WHEN an accountant archives an account, the system SHALL keep it and its journal lines and mark it inactive.
2. `R3.AC2` IF an accountant posts to an archived account, THEN the system SHALL reject the posting with error code `coa.account_archived`.
3. `R3.AC3` IF an accountant deletes an account that has journal lines, THEN the system SHALL reject it with error code `coa.account_in_use`.
4. `R3.AC4` WHERE an account has no journal lines and is not referenced as a default account, the system SHALL allow it to be deleted.
5. `R3.AC5` IF an accountant archives an account that is set as a company default, THEN the system SHALL reject it with error code `coa.account_is_default`.
6. `R3.AC6` WHEN an accountant requests the chart of accounts without asking for archived accounts, the system SHALL return only active accounts.

### R4 Journals

**User Story:** As an accountant, I want to manage journals, so that sales, purchases, bank, cash and manual entries are numbered and grouped separately.

#### Acceptance Criteria

1. `R4.AC1` WHEN an accountant submits a new journal with a code, name and type, the system SHALL create it for that company.
2. `R4.AC2` WHERE a journal is a bank or cash journal, the system SHALL require a default account whose subtype is `bank_cash`.
3. `R4.AC3` IF an accountant submits a journal code that another journal in the same company already uses, THEN the system SHALL reject it with error code `coa.duplicate_code`.
4. `R4.AC4` IF an accountant submits a journal code that is not one to eight upper-case letters or digits, THEN the system SHALL reject it with error code `coa.invalid_journal_code`.
5. `R4.AC5` IF an accountant changes the code of a journal that has posted entries, THEN the system SHALL reject the change with error code `coa.journal_in_use`.
6. `R4.AC6` WHEN an accountant archives a journal, the system SHALL keep its posted entries and refuse new postings to it.
7. `R4.AC7` IF an accountant sets a journal default account belonging to another company, THEN the system SHALL reject it with error code `coa.account_not_found`.

### R5 Company default accounts

**User Story:** As an accountant, I want the company's default accounts configured once, so that invoices, payments and currency conversion post to the right places without being told each time.

#### Acceptance Criteria

1. `R5.AC1` WHEN an accountant sets a company default account, the system SHALL record it against that company.
2. `R5.AC2` The system SHALL keep defaults for receivables, payables, currency rounding, exchange gain, exchange loss, outstanding receipts, outstanding payments and suspense.
3. `R5.AC3` IF an accountant sets a default account whose subtype does not suit that default, THEN the system SHALL reject it with error code `coa.default_subtype_mismatch`.
4. `R5.AC4` IF an accountant sets a default account that is archived, THEN the system SHALL reject it with error code `coa.account_archived`.
5. `R5.AC5` IF an accountant sets a default account belonging to another company, THEN the system SHALL reject it with error code `coa.account_not_found`.
6. `R5.AC6` IF an accountant sets a group account as a default, THEN the system SHALL reject it with error code `coa.group_account`.
7. `R5.AC7` WHEN an accountant requests a company's defaults, the system SHALL report which of them are not yet set.

### R6 Saudi chart template

**User Story:** As a new customer in Saudi Arabia, I want a ready-made chart of accounts, so that I can issue invoices and file VAT without building a chart from scratch.

#### Acceptance Criteria

1. `R6.AC1` WHEN an accountant loads the Saudi template into a company, the system SHALL create its accounts with Arabic and English names.
2. `R6.AC2` WHEN the Saudi template is loaded, the system SHALL set the company default accounts named by the template.
3. `R6.AC3` WHEN the Saudi template is loaded, the system SHALL create the sales, purchases, bank, cash and general journals.
4. `R6.AC4` The system SHALL include accounts for VAT input, VAT output, withholding tax payable, Zakat provision, end-of-service provision and GOSI payable.
5. `R6.AC5` IF an accountant loads a template into a company that already has accounts, THEN the system SHALL reject it with error code `coa.chart_not_empty`.
6. `R6.AC6` WHEN the template has been loaded, the system SHALL allow every account it created to be renamed, re-parented or archived.
7. `R6.AC7` IF loading a template fails part way through, THEN the system SHALL leave the company with no accounts from that template.

### R7 Exchange rates

**User Story:** As an accountant, I want to maintain exchange rates, so that foreign-currency documents convert at the rate I control.

#### Acceptance Criteria

1. `R7.AC1` WHEN an accountant submits a rate for a currency and date, the system SHALL record it for that company.
2. `R7.AC2` WHEN an accountant submits a rate for a currency and date that already has one, the system SHALL replace the existing rate.
3. `R7.AC3` IF an accountant submits a rate of zero or less, THEN the system SHALL reject it with error code `coa.invalid_rate`.
4. `R7.AC4` IF an accountant submits a rate for the company's own base currency, THEN the system SHALL reject it with error code `coa.base_currency_rate`.
5. `R7.AC5` WHEN an accountant requests rates for a currency, the system SHALL return them in date order.
6. `R7.AC6` WHEN an accountant imports several rates at once, the system SHALL record every valid row and report each rejected row with its reason.

### R8 Chart integrity reporting

**User Story:** As a finance controller, I want to see whether the chart is ready to keep books, so that gaps are found before the first invoice rather than during a filing.

#### Acceptance Criteria

1. `R8.AC1` WHEN an accountant requests a chart readiness check, the system SHALL report any company default account that is not set.
2. `R8.AC2` WHEN an accountant requests a chart readiness check, the system SHALL report any bank or cash journal without a default account.
3. `R8.AC3` WHEN an accountant requests a chart readiness check, the system SHALL report any group account that has no children.
4. `R8.AC4` WHEN an accountant requests a chart readiness check, the system SHALL report any active currency that has no exchange rate.
5. `R8.AC5` WHILE a company has no accounts, WHEN an accountant requests a chart readiness check, the system SHALL report that the chart is empty.

### R9 Chart of accounts API

**User Story:** As an accountant, I want to manage the chart from the application, so that I do not need a developer to add an account.

#### Acceptance Criteria

1. `R9.AC1` WHEN a caller with `account:read` requests a company's chart, the system SHALL return its accounts with their hierarchy and depth.
2. `R9.AC2` WHEN a caller requests the chart with a search term, the system SHALL return only accounts whose code or name matches it.
3. `R9.AC3` WHEN a caller with `account:manage` submits a new account, the system SHALL create it and return it with its id.
4. `R9.AC4` WHEN a caller with `account:manage` submits changes to an account, the system SHALL apply them and return the updated account.
5. `R9.AC5` WHEN a caller with `account:manage` archives an account, the system SHALL mark it inactive and return no content.
6. `R9.AC6` IF a caller without `account:manage` submits an account change, THEN the system SHALL refuse it with HTTP 403.
7. `R9.AC7` IF a caller requests an account that belongs to another company, THEN the system SHALL answer as though it does not exist.
8. `R9.AC8` WHEN a caller creates or changes an account, the system SHALL append an audit record naming the account code.

### R10 Journals API

**User Story:** As an accountant, I want to manage journals from the application, so that new bank accounts and document types can be set up without a deployment.

#### Acceptance Criteria

1. `R10.AC1` WHEN a caller with `journal:read` requests a company's journals, the system SHALL return them with their type and default account.
2. `R10.AC2` WHEN a caller with `journal:manage` submits a new journal, the system SHALL create it and return it with its id.
3. `R10.AC3` WHEN a caller with `journal:manage` archives a journal, the system SHALL mark it inactive and return no content.
4. `R10.AC4` IF a caller without `journal:manage` submits a journal change, THEN the system SHALL refuse it with HTTP 403.
5. `R10.AC5` WHEN a caller creates or changes a journal, the system SHALL append an audit record naming the journal code.

### R11 Company defaults API

**User Story:** As an accountant, I want to see and set the company's default accounts, so that posting works before the first invoice.

#### Acceptance Criteria

1. `R11.AC1` WHEN a caller with `account:read` requests the company's defaults, the system SHALL return each default with the account it points at, or nothing where it is unset.
2. `R11.AC2` WHEN a caller with `account:manage` sets a default account, the system SHALL record it and return the updated defaults.
3. `R11.AC3` IF a caller without `account:manage` sets a default, THEN the system SHALL refuse it with HTTP 403.
4. `R11.AC4` WHEN a caller changes a default, the system SHALL append an audit record naming the default and the account.

### R12 Template API

**User Story:** As a new customer, I want to load the Saudi chart with one action, so that setup takes a moment rather than a day.

#### Acceptance Criteria

1. `R12.AC1` WHEN a caller with `chart:load` loads the Saudi template into an empty company, the system SHALL create its accounts, journals and defaults and return a summary of what was created.
2. `R12.AC2` IF a caller without `chart:load` loads a template, THEN the system SHALL refuse it with HTTP 403.
3. `R12.AC3` WHEN a caller lists the available templates, the system SHALL return each template's key, name and description.
4. `R12.AC4` WHEN a template is loaded, the system SHALL append an audit record naming the template.

### R13 Exchange rates API

**User Story:** As an accountant, I want to enter exchange rates, so that foreign-currency documents convert at the rate I control.

#### Acceptance Criteria

1. `R13.AC1` WHEN a caller with `rate:read` requests a currency's rates, the system SHALL return them in date order.
2. `R13.AC2` WHEN a caller with `rate:manage` submits a rate, the system SHALL record it and return it.
3. `R13.AC3` WHEN a caller with `rate:manage` submits several rates at once, the system SHALL return how many were recorded and a reason for each rejected row.
4. `R13.AC4` IF a caller without `rate:manage` submits a rate, THEN the system SHALL refuse it with HTTP 403.

### R14 Access control for this module

**User Story:** As a security reviewer, I want these endpoints held to the same rules as the rest of the system, so that the chart cannot be read or changed by the wrong person.

#### Acceptance Criteria

1. `R14.AC1` The system SHALL add the permissions `account:read`, `account:manage`, `journal:read`, `journal:manage`, `rate:read`, `rate:manage` and `chart:load` to the catalogue.
2. `R14.AC2` The system SHALL grant every new permission to the Administrator role.
3. `R14.AC3` The system SHALL scope every endpoint in this feature to a company named in its path.
4. `R14.AC4` IF an unauthenticated caller requests any endpoint in this feature, THEN the system SHALL refuse it with HTTP 401.
5. `R14.AC5` IF a caller requests a company they hold no role in, THEN the system SHALL refuse it with HTTP 403, identically to a company that does not exist.
6. `R14.AC6` The system SHALL report every refusal in this feature as problem details carrying a `coa.*` or `identity.*` code.

## Non-Functional Requirements

- `NFR1` Integrity: the ledger's own invariants stay untouched; this feature adds rules above them and never weakens a database constraint (proven by re-running the core-ledger invariant tests).
- `NFR2` Auditability: nothing that has been used in the books is ever hard-deleted (proven by `R3`).
- `NFR3` Localization: every account the Saudi template creates carries an Arabic and an English name (proven by `R6.AC1`).
- `NFR4` Maintainability: chart-of-accounts code depends on the ledger only through `app.ledger.api`, and on identity only through the API layer's dependencies, enforced by import-linter.
- `NFR6` Consistency: these endpoints use the same problem-details shape, session handling and origin check as `identity-and-access`, with no new error conventions (proven by `R14.AC6`).
- `NFR5` Atomicity: multi-record operations (template load, rate import) either complete or leave nothing behind (proven by `R6.AC7`).

## Constraints And Dependencies

- `C1` The `account`, `journal`, `ledger_settings` and `exchange_rate` tables already exist from the core ledger; changes to them come as new Alembic migrations.
- `C2` The ledger already enforces: subtype belongs to type, receivable and payable accounts are reconcilable, group accounts cannot hold lines, an account with lines cannot become a group, and accounts cannot cross companies. This feature adds the rules the database does not cover.
- `C3` "An accountant" means a caller holding the stated permission in the company named in the path; sessions, the origin check and error shape come from `identity-and-access`.
- `C4` Statutory rates and Zakat rules are out of scope; the template only creates the accounts they will post to.
- `C5` Local test runs stay capped at two pytest workers, against the Neon `test` branch.

## Out Of Scope

- Users, login, roles and permissions — delivered by `identity-and-access`.
- Invoicing, taxes, payments, reconciliation and reports.
- Importing a chart of accounts from a spreadsheet or another system.
- Chart templates for countries other than Saudi Arabia.
- Automatic exchange-rate feeds from a rate provider.
- Frontend screens.
