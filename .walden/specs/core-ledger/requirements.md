---
status: approved
approved_at: 2026-09-17T19:11:00Z
last_modified: 2026-09-17T19:11:00Z
---

# Requirements Document

## Introduction

The core ledger is the foundation of the finance ERP (Phase 1, module 1 of
`finance-erp-mvp-prompt.md`). It stores journal entries and journal entry lines, posts
balanced entries through a single posting service, numbers them without gaps, converts
foreign-currency amounts into company currency, and corrects mistakes only through
reversal entries. Every accounting invariant is enforced by PostgreSQL itself so that no
application bug or direct SQL write can corrupt the books.

Consumers of this feature are other backend modules (invoicing, payments, inventory,
payroll, POS), which post through the ledger's public service interface. Accountants
interact with it indirectly until later features add screens and endpoints.

<!-- assumed: this feature exposes a Python service interface only (plus a health endpoint); REST endpoints and screens for manual journal entries arrive with the chart-of-accounts feature -->
<!-- assumed: currency conversion at posting time is part of this feature because every line must store both amounts; exchange-rate management screens/imports and realized FX gain/loss are not -->
<!-- assumed: accounts and journals exist here only as the minimal tables the ledger needs; hierarchy management, the Saudi chart template and default-account settings belong to the chart-of-accounts feature -->

## Requirements

### R1 Draft journal entries

**User Story:** As a backend module, I want to build journal entries as drafts first, so that incomplete entries never affect the books.

#### Acceptance Criteria

1. `R1.AC1` The system SHALL create every journal entry in the `draft` state.
2. `R1.AC2` WHILE a journal entry is in the `draft` state, WHEN a caller updates or deletes the entry or its lines, the system SHALL apply the change.
3. `R1.AC3` IF a caller inserts a journal entry directly in the `posted` state, THEN the system SHALL reject the insert with error code `ledger.insert_posted`.

### R2 Posting requests

**User Story:** As a backend module, I want to submit a posting request and receive a posted journal entry, so that every financial document reaches the ledger through one validated path.

#### Acceptance Criteria

1. `R2.AC1` WHEN a module submits a valid posting request, the system SHALL create a journal entry in the `posted` state containing one line per requested line.
2. `R2.AC2` WHEN a module submits a valid posting request, the system SHALL record the posting timestamp on the entry.
3. `R2.AC3` The system SHALL leave committing or rolling back the transaction to the calling module.
4. `R2.AC4` IF a posting request has fewer than two lines, THEN the system SHALL reject it with error code `ledger.too_few_lines`.
5. `R2.AC5` IF a posting request line has a negative debit or credit, THEN the system SHALL reject it with error code `ledger.negative_amount`.
6. `R2.AC6` IF a posting request line has both a debit and a credit, THEN the system SHALL reject it with error code `ledger.two_sided_line`.
7. `R2.AC7` IF a posting request line has neither a debit nor a credit, THEN the system SHALL reject it with error code `ledger.zero_line`.
8. `R2.AC8` IF the debits and credits of a posting request differ in the request's currency, THEN the system SHALL reject it with error code `ledger.unbalanced`.
9. `R2.AC9` IF a posting request amount has more decimal places than the request's currency allows, THEN the system SHALL reject it with error code `ledger.unrounded`.
10. `R2.AC10` IF a posting request names a journal that does not belong to the request's company, THEN the system SHALL reject it with error code `ledger.journal_not_found`.
11. `R2.AC11` IF a posting request names an archived journal, THEN the system SHALL reject it with error code `ledger.journal_inactive`.
12. `R2.AC12` IF a posting request names a company that does not exist, THEN the system SHALL reject it with error code `ledger.company_not_found`.

### R3 Database-enforced balance

**User Story:** As a finance controller, I want the database to refuse unbalanced books, so that no code path or manual SQL can break double-entry accounting.

#### Acceptance Criteria

1. `R3.AC1` IF a transaction commits a posted entry whose company-currency debits and credits differ, THEN the system SHALL roll back the transaction with error code `ledger.unbalanced`.
2. `R3.AC2` IF a transaction commits a posted entry whose lines all share one currency and whose transaction-currency amounts do not sum to zero, THEN the system SHALL roll back the transaction with error code `ledger.unbalanced_currency`.
3. `R3.AC3` IF a transaction commits a posted entry with no lines or with zero total debits, THEN the system SHALL roll back the transaction with error code `ledger.empty_entry`.
4. `R3.AC4` IF a write stores a line with a negative debit or credit, THEN the system SHALL reject the write.
5. `R3.AC5` IF a write stores a line with both a non-zero debit and a non-zero credit, THEN the system SHALL reject the write.
6. `R3.AC6` IF a write stores a line whose transaction-currency amount points in the opposite direction to its company-currency amount, THEN the system SHALL reject the write.
7. `R3.AC7` IF a write stores a company-currency line whose transaction-currency amount differs from debit minus credit, THEN the system SHALL reject the write with error code `ledger.base_amount_mismatch`.
8. `R3.AC8` IF a write stores a line amount with more decimal places than its currency allows, THEN the system SHALL reject the write with error code `ledger.unrounded`.
9. `R3.AC9` The system SHALL apply every check in `R3` to writes made with raw SQL as well as through the posting service.

### R4 Immutable posted entries

**User Story:** As an auditor, I want posted entries to be unchangeable, so that the books show exactly what was recorded and every correction is visible.

#### Acceptance Criteria

1. `R4.AC1` IF a caller updates a posted journal entry, THEN the system SHALL reject the update with error code `ledger.posted_immutable`.
2. `R4.AC2` IF a caller deletes a posted journal entry, THEN the system SHALL reject the deletion with error code `ledger.posted_immutable`.
3. `R4.AC3` IF a caller inserts, updates, or deletes a line of a posted journal entry, THEN the system SHALL reject the write with error code `ledger.posted_immutable`.
4. `R4.AC4` IF a caller changes a posted journal entry back to the `draft` state, THEN the system SHALL reject the change with error code `ledger.posted_immutable`.

### R5 Reversal entries

**User Story:** As a backend module, I want to reverse a posted entry, so that mistakes are corrected with a new offsetting entry instead of an edit.

#### Acceptance Criteria

1. `R5.AC1` WHEN a module requests the reversal of a posted entry, the system SHALL post a new entry whose lines swap the debit and credit of every original line.
2. `R5.AC2` WHEN a module requests the reversal of a posted entry, the system SHALL negate the transaction-currency amount of every original line in the new entry.
3. `R5.AC3` WHEN a module requests the reversal of a posted entry, the system SHALL link the new entry to the original entry.
4. `R5.AC4` WHEN a module requests a reversal with a date, the system SHALL date the reversal entry on that date.
5. `R5.AC5` WHEN a module requests a reversal without a date, the system SHALL date the reversal entry on the original entry's date.
6. `R5.AC6` IF a module requests the reversal of a draft entry, THEN the system SHALL reject it with error code `ledger.reverse_unposted`.
7. `R5.AC7` IF a module requests the reversal of an entry that already has a reversal, THEN the system SHALL reject it with error code `ledger.already_reversed`.
8. `R5.AC8` IF a module requests the reversal of an entry that does not exist in the given company, THEN the system SHALL reject it with error code `ledger.entry_not_found`.

### R6 Gapless entry numbering

**User Story:** As a finance controller, I want posted entries numbered consecutively without gaps, so that missing or duplicated entries are detectable, as auditors and ZATCA expect.

#### Acceptance Criteria

1. `R6.AC1` WHEN an entry is posted, the system SHALL assign it a number formatted as `<journal code>/<fiscal year>/<5-digit sequence>`.
2. `R6.AC2` The system SHALL number posted entries consecutively from 1 within each company, journal, and fiscal year.
3. `R6.AC3` The system SHALL identify a fiscal year by the calendar year in which it starts, using the company's fiscal year start month.
4. `R6.AC4` IF a posting transaction rolls back, THEN the system SHALL give its number to the next entry posted in that journal and fiscal year.
5. `R6.AC5` IF a write gives two entries in the same journal the same number, THEN the system SHALL reject the write.

### R7 Currency amounts

**User Story:** As a backend module, I want every line to carry both its transaction-currency amount and its company-currency amount, so that foreign-currency documents are reported correctly in SAR.

#### Acceptance Criteria

1. `R7.AC1` WHEN a module submits a posting request in the company's base currency, the system SHALL store company-currency debits and credits equal to the requested amounts.
2. `R7.AC2` WHEN a module submits a posting request in a foreign currency, the system SHALL convert each line using the company's latest exchange rate dated on or before the entry date.
3. `R7.AC3` The system SHALL store each line's transaction-currency amount as debit minus credit in the line's currency.
4. `R7.AC4` The system SHALL round converted amounts half away from zero to the base currency's decimal places.
5. `R7.AC5` IF conversion leaves company-currency debits and credits unequal, THEN the system SHALL add a line for the difference on the company's rounding account with a zero transaction-currency amount.
6. `R7.AC6` IF conversion needs a rounding line and the company has no rounding account, THEN the system SHALL reject the posting request with error code `ledger.rounding_account_missing`.
7. `R7.AC7` IF no exchange rate exists on or before the entry date, THEN the system SHALL reject the posting request with error code `ledger.rate_missing`.
8. `R7.AC8` IF a posting request uses an unknown currency, THEN the system SHALL reject it with error code `ledger.currency_not_found`.
9. `R7.AC9` IF a write stores an exchange rate of zero or less, THEN the system SHALL reject the write.
10. `R7.AC10` IF a write stores a second exchange rate for the same company, currency, and date, THEN the system SHALL reject the write.

### R8 Lock dates

**User Story:** As a finance controller, I want to lock closed periods, so that filed VAT returns and closed months cannot change.

#### Acceptance Criteria

1. `R8.AC1` IF a caller posts an entry dated on or before the company's lock date, THEN the system SHALL reject the posting with error code `ledger.period_locked`.
2. `R8.AC2` WHILE a transaction is posting an entry, WHEN another transaction changes the same company's lock date, the system SHALL make the lock date change wait until the posting transaction ends.

### R9 Company isolation

**User Story:** As an administrator of several companies, I want each company's books kept strictly separate, so that no entry can mix companies.

#### Acceptance Criteria

1. `R9.AC1` IF a write stores a line on an account that belongs to a different company than the entry, THEN the system SHALL reject the write.
2. `R9.AC2` IF a write stores an entry in a journal that belongs to a different company, THEN the system SHALL reject the write.
3. `R9.AC3` IF a write links a reversal to an entry of a different company, THEN the system SHALL reject the write.
4. `R9.AC4` IF a caller changes the base currency of a company that has journal entries, THEN the system SHALL reject the change with error code `ledger.base_currency_locked`.

### R10 Account safety

**User Story:** As an accountant, I want the ledger to refuse postings to accounts that cannot hold them, so that reports group balances correctly.

#### Acceptance Criteria

1. `R10.AC1` IF a write stores a line on a group account, THEN the system SHALL reject the write with error code `ledger.group_account`.
2. `R10.AC2` IF a caller turns an account that has journal lines into a group account, THEN the system SHALL reject the change with error code `ledger.account_has_lines`.
3. `R10.AC3` IF a write stores an account whose subtype does not belong to its type, THEN the system SHALL reject the write.
4. `R10.AC4` IF a write stores a receivable or payable account that is not reconcilable, THEN the system SHALL reject the write.

### R11 Concurrent posting

**User Story:** As a finance controller, I want the ledger to stay correct when many users and background jobs post at the same time, so that load never produces bad numbers or unbalanced books.

#### Acceptance Criteria

1. `R11.AC1` WHILE several transactions post to the same journal at the same time, the system SHALL give every committed entry a unique number with no gaps.
2. `R11.AC2` WHILE several transactions post to different journals at the same time, the system SHALL commit every posting without waiting on the other journals.
3. `R11.AC3` WHILE a transaction is posting an entry, WHEN another transaction inserts a line into that entry, the system SHALL reject the insert with error code `ledger.posted_immutable` after the posting commits.
4. `R11.AC4` WHILE a transaction holds an uncommitted line on a draft entry, WHEN another transaction posts that entry, the system SHALL include that line in the balance check at commit.
5. `R11.AC5` WHILE two transactions reverse the same entry at the same time, the system SHALL commit exactly one reversal.
6. `R11.AC6` WHILE a posting transaction fails and rolls back, WHEN other transactions post to the same journal, the system SHALL keep the numbering gapless.

### R12 One entry per source document

**User Story:** As a finance controller, I want each source document to post exactly one journal entry, so that no invoice, bill, or payment is counted twice.

#### Acceptance Criteria

1. `R12.AC1` IF a write stores a second journal entry for the same source type and source ID, THEN the system SHALL reject the write.
2. `R12.AC2` IF a posting request gives a source type without a source ID or a source ID without a source type, THEN the system SHALL reject it with error code `ledger.invalid_source`.

### R13 Error translation

**User Story:** As a backend module, I want database rule violations reported as coded errors, so that I can show clear messages and handle each case.

#### Acceptance Criteria

1. `R13.AC1` WHEN a database trigger rejects a write during posting, the system SHALL raise a domain error carrying the trigger's `ledger.<code>`.
2. `R13.AC2` WHEN a deferred balance check rejects a commit inside a unit of work, the system SHALL raise a domain error carrying the check's `ledger.<code>`.
3. `R13.AC3` IF a database error carries no `<module>.<code>` prefix, THEN the system SHALL re-raise the original database error.

### R14 Database connectivity

**User Story:** As an operator, I want the backend to work reliably against Neon's pooled and direct endpoints, so that serverless suspends and connection pooling never break requests.

#### Acceptance Criteria

1. `R14.AC1` The system SHALL disable server-side prepared statements on connections to the pooled endpoint.
2. `R14.AC2` The system SHALL run migrations over the direct endpoint.
3. `R14.AC3` IF a pooled connection was closed while the database compute was suspended, THEN the system SHALL replace it before running the next statement.
4. `R14.AC4` WHEN a client requests `GET /api/v1/health` and the database answers, the system SHALL respond with HTTP 200 and status `ok`.
5. `R14.AC5` IF the database is unreachable when a client requests `GET /api/v1/health`, THEN the system SHALL respond with HTTP 503 and status `degraded`.

### R15 Test database provisioning

**User Story:** As a developer, I want database tests to run on a Neon branch with a fresh schema, so that invariants are proven against real PostgreSQL without a local database.

#### Acceptance Criteria

1. `R15.AC1` WHEN the test suite starts with a test database URL, the system SHALL create a separate empty database for each test worker.
2. `R15.AC2` WHEN a test worker's database is created, the system SHALL apply all migrations to it.
3. `R15.AC3` WHEN the test suite finishes, the system SHALL drop every database it created.
4. `R15.AC4` IF the test suite starts without a test database URL, THEN the system SHALL skip database tests with a message naming the missing variable.

## Non-Functional Requirements

- `NFR1` Integrity: every ledger invariant holds regardless of the application code path, including raw SQL (proven by `R3.AC9`, `R4`, `R9`, `R10`).
- `NFR2` Precision: monetary values are never floating point; stored as `NUMERIC(20,6)` and handled as `Decimal` (proven by `R2.AC9`, `R3.AC8`, `R7.AC4`).
- `NFR3` Concurrency: correctness holds under PostgreSQL `READ COMMITTED` with concurrent writers (proven by `R11`).
- `NFR4` Scalability: posting locks are scoped to one journal and fiscal year, never global (proven by `R11.AC2`).
- `NFR5` Auditability: posted data is never edited or deleted; corrections are traceable to the entry they reverse (proven by `R4`, `R5.AC3`).
- `NFR6` Maintainability: other modules use only the ledger's public interface, enforced by import-linter in CI.
- `NFR7` Developer environment: no PostgreSQL runs on developer machines; database tests use Neon branches (proven by `R15`).

## Constraints And Dependencies

- `C1` PostgreSQL 18 on Neon (project `round-violet-29046436`, region us-east-2): pooled endpoint (PgBouncer transaction mode) for request traffic, direct endpoint for migrations and concurrency tests.
- `C2` Python 3.13, SQLAlchemy 2.0 with psycopg 3, Alembic with hand-written SQL migrations.
- `C3` The posting service never commits; the calling module owns the transaction.
- `C4` Partner and tax tables do not exist yet, so line `partner_id` and `tax_id` are stored without foreign keys until those features add them.
- `C5` Currencies are seeded reference data (SAR, USD, EUR, GBP, AED, QAR, EGP, CNY, INR, KWD, BHD, OMR, JPY).
- `C6` An implementation draft already exists in `backend/`, written before this spec. It is treated as unapproved and must be verified and corrected by the approved tasks.
- `C7` Local test runs are capped at two pytest workers.

## Out Of Scope

- Chart-of-accounts management: hierarchy rules, the Saudi account template, default-account settings, account APIs.
- REST endpoints and screens for manual journal entries.
- Exchange-rate management screens, rate imports, and unrealized FX revaluation.
- Reconciliation, open residual amounts, and realized FX gain/loss entries.
- Users, permissions, row-level security, and the audit log.
- The transactional outbox and background jobs.
- Financial reports.
- Railway deployment.
