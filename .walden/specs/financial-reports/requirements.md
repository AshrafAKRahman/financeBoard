---
status: approved
approved_at: 2026-09-18T18:55:33Z
last_modified: 2026-09-18T18:55:33Z
---

# Requirements Document

## Introduction

The reports are where the ledger stops being a database and starts being accounting. A
company files its VAT return from one, chases its customers from another, and shows its
bank a third. If a report disagrees with the ledger, the report is wrong — there is no
second set of numbers to consult.

So every report here is a read-only query over posted journal entry lines. Nothing is
cached, nothing is maintained alongside, and each report is tested against the trial
balance, which is tested against zero.

Phase 1 scope: trial balance, profit and loss, balance sheet, cash flow, aged receivables
and payables, the VAT return, and the account detail that every one of them drills into.

<!-- assumed: account detail (the general ledger behind a figure) is included, because a
report nobody can check is a report nobody should trust. The brief lists it only under
Phase 2 dashboards; it is proposed here as the seventh report. -->

## Requirements

### R1 Trial balance

**User Story:** As a finance controller, I want every account's debits, credits and balance for a period, so that I can prove the books balance before I publish anything else.

#### Acceptance Criteria

1. `R1.AC1` WHEN a controller requests a trial balance for a date range, the system SHALL return each account's opening balance, total debits, total credits and closing balance.
2. `R1.AC2` The system SHALL include only lines of journal entries in the `posted` state.
3. `R1.AC3` The system SHALL report every amount in the company's base currency.
4. `R1.AC4` The system SHALL ensure total debits equal total credits across the whole report.
5. `R1.AC5` WHEN a controller requests a trial balance, the system SHALL compute each opening balance from every posted line dated before the range starts.
6. `R1.AC6` WHERE a controller asks to hide unused accounts, the system SHALL omit accounts whose opening balance and movements are all zero.
7. `R1.AC7` IF the range ends before it starts, THEN the system SHALL reject the request with error code `reporting.invalid_period`.
8. `R1.AC8` The system SHALL exclude group accounts from the account rows, because nothing posts to them.

### R2 Profit and loss

**User Story:** As an owner, I want to see what the business earned and spent over a period, so that I know whether it made money.

#### Acceptance Criteria

1. `R2.AC1` WHEN an owner requests a profit and loss statement for a period, the system SHALL return income and expense accounts with their movement in that period.
2. `R2.AC2` The system SHALL present income as a positive figure when the business earned it, rather than as the credit balance the ledger stores.
3. `R2.AC3` The system SHALL group accounts by their subtype, so cost of revenue is separated from operating expense.
4. `R2.AC4` The system SHALL nest accounts under their parents in the chart hierarchy, subtotalling each group.
5. `R2.AC5` WHEN a profit and loss statement is produced, the system SHALL state gross profit, being income less cost of revenue.
6. `R2.AC6` WHEN a profit and loss statement is produced, the system SHALL state the net result for the period.
7. `R2.AC7` The system SHALL exclude balance sheet accounts from this report.
8. `R2.AC8` WHERE an owner asks for a comparison period, the system SHALL return the same figures for the preceding period of equal length alongside.

### R3 Balance sheet

**User Story:** As an owner, I want what the business owns and owes on a given date, so that I can show a lender or an auditor where it stands.

#### Acceptance Criteria

1. `R3.AC1` WHEN an owner requests a balance sheet as of a date, the system SHALL return asset, liability and equity balances accumulated from the beginning of time to that date.
2. `R3.AC2` The system SHALL compute current-year earnings from income and expense accounts within the fiscal year containing the requested date.
3. `R3.AC3` The system SHALL compute retained earnings from income and expense accounts of every fiscal year before that one.
4. `R3.AC4` The system SHALL ensure assets equal liabilities plus equity, with the two computed earnings figures included in equity.
5. `R3.AC5` The system SHALL take the fiscal year boundary from the company's configured fiscal year start month, not from January.
6. `R3.AC6` The system SHALL present liabilities and equity as positive figures when the business owes them.
7. `R3.AC7` The system SHALL nest accounts under their parents, subtotalling each group.

### R4 Cash flow

**User Story:** As an owner, I want to see the cash that actually moved, so that I can tell profit from money in the bank.

#### Acceptance Criteria

1. `R4.AC1` WHEN an owner requests a cash flow statement for a period, the system SHALL return movements on bank and cash accounts classified as operating, investing or financing.
2. `R4.AC2` The system SHALL classify each movement by the cash flow tag of the account on the other side of its journal entry.
3. `R4.AC3` IF a counterpart account carries no cash flow tag, THEN the system SHALL classify the movement as operating and list it separately as unclassified.
4. `R4.AC4` WHEN a cash flow statement is produced, the system SHALL state opening cash, net movement and closing cash.
5. `R4.AC5` The system SHALL ensure opening cash plus the net movement equals closing cash.
6. `R4.AC6` The system SHALL derive the statement from cash account movements directly, rather than by adjusting the net result.

### R5 Aged receivables and payables

**User Story:** As a credit controller, I want to know who owes us what and for how long, so that I can chase the right customers today.

#### Acceptance Criteria

1. `R5.AC1` WHEN a controller requests aged receivables as of a date, the system SHALL return each partner's open items grouped into current, 1–30, 31–60, 61–90 and over 90 days overdue.
2. `R5.AC2` The system SHALL age each open item by its due date, falling back to the entry date where no due date was set.
3. `R5.AC3` WHEN aged receivables are requested as of today, the system SHALL take each line's open amount from the amount the ledger already holds.
4. `R5.AC4` WHEN aged receivables are requested as of a past date, the system SHALL reconstruct each open amount by subtracting only those matches whose settling entry is dated on or before that date.
5. `R5.AC5` The system SHALL ensure the total of an aged receivables report equals the balance of the receivable accounts on the same date.
6. `R5.AC6` The system SHALL produce aged payables by the same rules, reading payable accounts instead.
7. `R5.AC7` The system SHALL include a partner's credit notes and unmatched payments as negative open items, so a partner who has overpaid reads as such.
8. `R5.AC8` WHERE a controller asks for one partner, the system SHALL return that partner's open items individually rather than only the totals.

### R6 VAT return

**User Story:** As an accountant, I want the figures for the ZATCA VAT return for a filing period, so that I can file without rebuilding them in a spreadsheet.

#### Acceptance Criteria

1. `R6.AC1` WHEN an accountant requests a VAT return for a period, the system SHALL return the net amount and the tax amount for each ZATCA return box.
2. `R6.AC2` The system SHALL assign each amount to a box using the tax grid tag recorded on the journal line when it was posted.
3. `R6.AC3` The system SHALL separate output tax on sales from input tax on purchases.
4. `R6.AC4` WHEN a VAT return is produced, the system SHALL state the net tax due as output tax less input tax.
5. `R6.AC5` The system SHALL report zero-rated and exempt supplies as their own boxes, with tax of zero rather than omitted.
6. `R6.AC6` The system SHALL ensure the tax totals equal the movements on the VAT accounts for the same period.
7. `R6.AC7` IF a posted line carries a tax but no grid tag, THEN the system SHALL list it as untagged rather than silently dropping it from the return.

### R7 Account detail

**User Story:** As anyone reading a report, I want to see the individual entries behind a figure, so that I can check it rather than take it on faith.

#### Acceptance Criteria

1. `R7.AC1` WHEN a reader requests the detail of an account for a period, the system SHALL return its posted lines with date, entry number, partner, description and a running balance.
2. `R7.AC2` The system SHALL order the lines by entry date and then entry number.
3. `R7.AC3` The system SHALL start the running balance from the account's opening balance for the period.
4. `R7.AC4` The system SHALL ensure the closing running balance equals the account's balance in the trial balance for the same period.
5. `R7.AC5` WHERE a reader asks for one partner, the system SHALL return only that partner's lines on the account.
6. `R7.AC6` The system SHALL name the document behind each line where one exists, so an invoice number leads back to the invoice.

### R8 Periods and scope

**User Story:** As a controller of several companies, I want every report scoped and dated exactly, so that figures from one company never appear in another's accounts.

#### Acceptance Criteria

1. `R8.AC1` The system SHALL scope every report to the company named in the request.
2. `R8.AC2` WHEN a report is requested without a period, the system SHALL use the current fiscal year to date.
3. `R8.AC3` WHERE a reader asks for a named period such as a quarter, the system SHALL resolve it against the company's fiscal year start month.
4. `R8.AC4` IF a report is requested for a company the caller has no role in, THEN the system SHALL refuse it with HTTP 403.
5. `R8.AC5` The system SHALL state, on every report, the company, the period and the moment the figures were read.
6. `R8.AC6` WHERE a reader restricts a report to one journal, the system SHALL include only lines from entries in that journal.

### R9 Reports API

**User Story:** As a developer of the frontend, I want each report behind one predictable endpoint, so that screens and exports read the same figures.

#### Acceptance Criteria

1. `R9.AC1` WHEN a caller with `report:read` requests any report, the system SHALL return it.
2. `R9.AC2` IF a caller without `report:read` requests any report, THEN the system SHALL refuse it with HTTP 403.
3. `R9.AC3` The system SHALL return every report as a structure of rows with their subtotals, rather than as pre-rendered text.
4. `R9.AC4` The system SHALL return the account identifier on every row, so a screen can link a figure to its detail.
5. `R9.AC5` IF a report is requested with an unparseable date, THEN the system SHALL reject it with error code `reporting.invalid_period`.
6. `R9.AC6` The system SHALL scope every report endpoint to a company named in its path.

### R10 Reports agree with the ledger

**User Story:** As an auditor, I want the reports to agree with each other and with the ledger, so that I can rely on any one of them.

#### Acceptance Criteria

1. `R10.AC1` The system SHALL ensure the net result of the profit and loss statement equals the change in current-year earnings on the balance sheet for the same period.
2. `R10.AC2` The system SHALL ensure the balance sheet balances for any date in any company.
3. `R10.AC3` The system SHALL ensure opening cash plus cash flow movements equals the closing balance of the bank and cash accounts.
4. `R10.AC4` The system SHALL ensure aged receivables as of a date total the receivable account balances on that date.
5. `R10.AC5` The system SHALL ensure the VAT return's tax figures equal the movements on the VAT accounts for the period.
6. `R10.AC6` The system SHALL ensure an account's detail closes at the same balance the trial balance gives it.
7. `R10.AC7` WHILE a journal entry is still a draft, the system SHALL leave it out of every report.
8. `R10.AC8` WHEN an entry is reversed, the system SHALL let both the entry and its reversal appear, so the reports show the correction rather than hiding the mistake.

## Non-Functional Requirements

- `NFR1` The system SHALL derive every report from posted journal entry lines, with no cached, pre-aggregated or separately maintained figures.
- `NFR2` The system SHALL hold and return money as decimal values in the company's base currency, never as floating point.
- `NFR3` The system SHALL return any Phase 1 report over a fiscal year of a company with 10,000 posted entries within two seconds.
- `NFR4` The system SHALL keep `app.reporting` above `app.treasury` in the module layering, enforced by import-linter.
- `NFR5` The system SHALL answer a refused report with a problem-details body carrying a stable `reporting.*` code.
- `NFR6` The system SHALL write nothing while producing a report, so a reader can never change the books.

## Constraints And Dependencies

- `C1` PostgreSQL 18 on Neon; reports are SQL over `journal_entry_line`, `journal_entry` and `account`.
- `C2` Company base currency only; consolidating companies with different base currencies is out of scope for Phase 1.
- `C3` Decision D5: the cash flow statement uses the direct method.
- `C4` Decision D6: no closing entries; retained earnings and current-year earnings are computed.
- `C5` Aged reports depend on the `residual` columns and the `reconciliation` table delivered by `payments-and-reconciliation`.
- `C6` The VAT return depends on the grid tags written by `invoicing-and-vat` when a document posts.
- `C7` Every feature goes through the Walden gates, and CI must pass before merge.

## Out Of Scope

- Dashboards, KPI tiles and charts (Phase 2, and the frontend feature for basic charts).
- The `ledger_daily_balance` cache that Phase 2 dashboards will read.
- CSV, Excel and PDF output — a separate export feature per decision D13.
- Zakat computation (Phase 2) and corporate income tax.
- Budget versus actual, and any forecast.
- The indirect cash flow method (Phase 2 view).
- Consolidation across companies, and any group elimination.
- Unrealised foreign exchange revaluation (decision D9).
