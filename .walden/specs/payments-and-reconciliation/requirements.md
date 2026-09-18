---
status: approved
approved_at: 2026-09-18T14:46:18Z
last_modified: 2026-09-18T14:46:18Z
---

# Requirements Document

## Introduction

Payments close the invoicing loop: money received and paid, bank statements imported, and
each payment matched to the invoices or bills it settles — fully or in part. It is Phase 1,
module 6 of `finance-erp-mvp-prompt.md`, and it turns an invoice from "issued" into "paid",
which the reports in module 7 then rely on.

It also finishes two things the core ledger deliberately deferred: the open amount
(residual) on every receivable and payable line, and the realised exchange gain or loss
when a foreign-currency invoice is settled at a different rate.

<!-- assumed: a payment posts through the company's outstanding receipts/payments account, and the bank account itself is only touched when a bank statement line is matched — the pattern in docs/architecture.md §10.1 -->
<!-- assumed: a document's payment state is derived from its lines' residuals on every read, never stored, so it cannot drift from the ledger -->
<!-- assumed: bank statement files are CSV, MT940 and OFX; live bank feeds are Phase 2 -->
<!-- assumed: matching suggestions are offered but a person confirms them; automatic rules come later -->

## Requirements

### R1 Recording a payment

**User Story:** As an accountant, I want to record money received or paid, so that the ledger and the customer's balance reflect it.

#### Acceptance Criteria

1. `R1.AC1` WHEN an accountant records a payment with a partner, a date, an amount, a currency and a bank or cash journal, the system SHALL store it as a draft.
2. `R1.AC2` The system SHALL support inbound payments from customers and outbound payments to vendors.
3. `R1.AC3` WHILE a payment is a draft, WHEN an accountant changes its amount, date, partner or journal, the system SHALL apply the change.
4. `R1.AC4` IF an accountant records a payment of zero or less, THEN the system SHALL reject it with error code `payments.invalid_amount`.
5. `R1.AC5` IF an accountant records a payment against a journal that is not a bank or cash journal, THEN the system SHALL reject it with error code `payments.wrong_journal_type`.
6. `R1.AC6` IF an accountant records a payment for a partner of another company, THEN the system SHALL reject it with error code `payments.partner_not_found`.
7. `R1.AC7` WHEN an accountant deletes a draft payment, the system SHALL remove it.
8. `R1.AC8` The system SHALL record an optional reference and memo on each payment.

### R2 Posting a payment

**User Story:** As a finance controller, I want every posted payment in the books exactly once, so that cash and customer balances are always explainable.

#### Acceptance Criteria

1. `R2.AC1` WHEN an accountant posts an inbound payment, the system SHALL debit the company's outstanding receipts account and credit the receivable account.
2. `R2.AC2` WHEN an accountant posts an outbound payment, the system SHALL credit the company's outstanding payments account and debit the payable account.
3. `R2.AC3` WHEN a payment is posted, the system SHALL create exactly one journal entry for it.
4. `R2.AC4` WHEN a payment is posted, the system SHALL record the partner and the payment date on the receivable or payable line.
5. `R2.AC5` WHEN a payment is posted, the system SHALL give it a gapless number from its journal.
6. `R2.AC6` IF a payment is posted twice, THEN the system SHALL reject the second attempt with error code `payments.already_posted`.
7. `R2.AC7` IF the company has no outstanding receipts or payments default account, THEN the system SHALL reject posting with error code `payments.default_account_missing`.
8. `R2.AC8` IF posting fails for any reason, THEN the system SHALL leave the payment as a draft with no journal entry.
9. `R2.AC9` IF an accountant changes a posted payment, THEN the system SHALL reject the change with error code `payments.posted_immutable`.
10. `R2.AC10` WHEN an accountant cancels a posted payment, the system SHALL reverse its journal entry, undo its matches and mark it cancelled.

### R3 Open amounts on ledger lines

**User Story:** As a finance controller, I want each receivable and payable line to carry what is still open, so that "who owes what" is a fact in the ledger rather than a calculation somewhere else.

#### Acceptance Criteria

1. `R3.AC1` WHEN a reconcilable line is posted, the system SHALL set its open amount to its full amount in both company and transaction currency.
2. `R3.AC2` WHEN lines are matched, the system SHALL reduce each line's open amount by the matched amount.
3. `R3.AC3` WHEN a line's open amount reaches zero in both currencies, the system SHALL mark the line reconciled.
4. `R3.AC4` IF a write would match more than a line's open amount, THEN the system SHALL reject it with error code `payments.over_matched`.
5. `R3.AC5` The system SHALL keep each line's open amount equal to its amount minus the sum of its matches, whatever the caller does.
6. `R3.AC6` The system SHALL leave open amounts empty on lines that are not reconcilable.

### R4 Matching payments to documents

**User Story:** As an accountant, I want to match a payment to the invoices it settles, so that each invoice shows what is still outstanding.

#### Acceptance Criteria

1. `R4.AC1` WHEN an accountant matches a payment line to an invoice line, the system SHALL record the matched amount against both.
2. `R4.AC2` WHERE a payment covers only part of an invoice, the system SHALL match the lesser amount and leave the rest open.
3. `R4.AC3` WHERE a payment covers several invoices, the system SHALL allow it to be matched to each in turn until it is used up.
4. `R4.AC4` IF an accountant matches two lines of the same sign, THEN the system SHALL reject it with error code `payments.same_side`.
5. `R4.AC5` IF an accountant matches lines of different partners, THEN the system SHALL reject it with error code `payments.partner_mismatch`.
6. `R4.AC6` IF an accountant matches lines on accounts that are not reconcilable, THEN the system SHALL reject it with error code `payments.not_reconcilable`.
7. `R4.AC7` IF an accountant matches lines of different companies, THEN the system SHALL reject it with error code `payments.company_mismatch`.
8. `R4.AC8` WHEN an accountant unmatches a reconciliation, the system SHALL restore both lines' open amounts.
9. `R4.AC9` WHEN an accountant requests matching suggestions for a payment, the system SHALL return that partner's open documents, closest amount first.

### R5 Realised exchange differences

**User Story:** As an accountant, I want the gain or loss from a changed exchange rate recorded when an invoice is settled, so that the books reflect what the money was actually worth.

#### Acceptance Criteria

1. `R5.AC1` WHEN matching closes a foreign-currency line whose company-currency amounts differ, the system SHALL post the difference as an exchange gain or loss.
2. `R5.AC2` WHEN the settlement was worth more in company currency than the invoice, the system SHALL post the difference to the exchange gain account.
3. `R5.AC3` WHEN the settlement was worth less, the system SHALL post the difference to the exchange loss account.
4. `R5.AC4` The system SHALL link the exchange difference entry to the reconciliation that caused it.
5. `R5.AC5` IF the company has no exchange gain or loss account and a difference arises, THEN the system SHALL reject the match with error code `payments.fx_account_missing`.
6. `R5.AC6` WHEN a reconciliation with an exchange difference is undone, the system SHALL reverse that difference entry.
7. `R5.AC7` WHILE the transaction currency equals the company currency, the system SHALL post no exchange difference.

### R6 Payment state of a document

**User Story:** As an accountant chasing debtors, I want each invoice to show whether it is paid, so that I can see what to chase without opening the ledger.

#### Acceptance Criteria

1. `R6.AC1` The system SHALL derive a document's payment state from its receivable or payable lines' open amounts on every read.
2. `R6.AC2` WHILE a document's open amount equals its total, the system SHALL report it as not paid.
3. `R6.AC3` WHILE a document's open amount is between zero and its total, the system SHALL report it as partly paid.
4. `R6.AC4` WHILE a document's open amount is zero, the system SHALL report it as paid.
5. `R6.AC5` WHEN a document is cancelled, the system SHALL report it as cancelled rather than paid.
6. `R6.AC6` WHEN an accountant opens a document, the system SHALL report the payments matched to it and the amount each contributed.

### R7 Bank statements

**User Story:** As an accountant, I want to import the bank's statement, so that the bank account in the books matches the bank.

#### Acceptance Criteria

1. `R7.AC1` WHEN an accountant imports a CSV statement with a column mapping, the system SHALL create a statement with one line per row.
2. `R7.AC2` The system SHALL import MT940 and OFX files without a column mapping.
3. `R7.AC3` WHEN a statement is imported, the system SHALL record each line's date, amount, description, counterparty and the bank's own reference.
4. `R7.AC4` IF an imported row repeats a line already in the system, THEN the system SHALL skip it and report it as a duplicate.
5. `R7.AC5` IF a file cannot be read, THEN the system SHALL reject the import with error code `payments.unreadable_file` and import nothing.
6. `R7.AC6` WHEN an import finishes, the system SHALL report how many lines were created, how many were duplicates, and any rows it could not read.
7. `R7.AC7` The system SHALL leave imported lines out of the ledger until they are matched.
8. `R7.AC8` WHEN an accountant requests a bank account's unmatched statement lines, the system SHALL return them oldest first.

### R8 Reconciling a statement line

**User Story:** As an accountant, I want to reconcile each statement line, so that the bank balance in the books is the bank's balance.

#### Acceptance Criteria

1. `R8.AC1` WHEN an accountant matches a statement line to a posted payment, the system SHALL post an entry debiting the bank account and crediting outstanding receipts, or the reverse for money out.
2. `R8.AC2` WHEN an accountant matches a statement line directly to an invoice, the system SHALL post the bank entry and match it to that invoice in one step.
3. `R8.AC3` WHEN a statement line is reconciled, the system SHALL mark it reconciled and record the entry it posted.
4. `R8.AC4` IF an accountant reconciles a statement line twice, THEN the system SHALL reject it with error code `payments.already_reconciled`.
5. `R8.AC5` WHEN an accountant requests suggestions for a statement line, the system SHALL return candidate payments and open documents, ranked by amount, reference and date closeness.
6. `R8.AC6` WHEN an accountant undoes a statement line's reconciliation, the system SHALL reverse its entry and mark the line unmatched.
7. `R8.AC7` IF a statement line's amount does not match what it is reconciled against, THEN the system SHALL reject it with error code `payments.amount_mismatch`.

### R9 Withholding tax on payments

**User Story:** As an accountant paying a non-resident supplier, I want withholding tax deducted on the payment, so that the amount withheld is owed to ZATCA rather than to the supplier.

#### Acceptance Criteria

1. `R9.AC1` WHERE a payment carries a withholding tax, the system SHALL reduce the amount paid to the partner by the withheld amount.
2. `R9.AC2` WHEN a payment with withholding tax is posted, the system SHALL credit the withholding tax account with the withheld amount.
3. `R9.AC3` WHEN a payment with withholding tax is posted, the system SHALL settle the payable at its full amount, not the reduced one.
4. `R9.AC4` IF a payment carries a tax that is not a withholding tax, THEN the system SHALL reject it with error code `payments.wrong_tax_type`.

### R10 Payments API

**User Story:** As an accountant, I want the whole payment cycle in the application, so that recording, matching and reconciling happen in one place.

#### Acceptance Criteria

1. `R10.AC1` WHEN a caller with `payment:read` lists payments, the system SHALL return them newest first with their state, partner and amount.
2. `R10.AC2` WHEN a caller with `payment:manage` creates, changes or deletes a draft payment, the system SHALL apply it.
3. `R10.AC3` WHEN a caller with `payment:post` posts or cancels a payment, the system SHALL apply it.
4. `R10.AC4` WHEN a caller with `payment:post` matches or unmatches lines, the system SHALL apply it.
5. `R10.AC5` WHEN a caller with `statement:import` imports a statement, the system SHALL apply it.
6. `R10.AC6` IF a caller without the needed permission calls any of these, THEN the system SHALL refuse it with HTTP 403.
7. `R10.AC7` The system SHALL scope every endpoint in this feature to a company named in its path.
8. `R10.AC8` WHEN a caller opens an invoice, the system SHALL include its payment state and matched payments.

### R11 Audit and concurrency

**User Story:** As an auditor, I want every match and payment recorded and safe under load, so that cash cannot be double-counted.

#### Acceptance Criteria

1. `R11.AC1` WHEN a payment is posted or cancelled, the system SHALL append an audit record naming its number and amount.
2. `R11.AC2` WHEN lines are matched or unmatched, the system SHALL append an audit record naming the amount and both lines.
3. `R11.AC3` WHEN a statement is imported, the system SHALL append an audit record naming the file and the counts.
4. `R11.AC4` WHILE two transactions match the same line at the same time, the system SHALL let at most the line's open amount be matched in total.
5. `R11.AC5` WHILE two transactions reconcile the same statement line at the same time, the system SHALL post exactly one entry for it.

## Non-Functional Requirements

- `NFR1` Integrity: open amounts are maintained by the database as amount minus matches, so no code path can leave them wrong (proven by `R3.AC5`, `R11.AC4`).
- `NFR2` Precision: matched amounts are `Decimal`, rounded to the currency's decimal places, and an exchange difference is posted rather than a rounding fudge (proven by `R5`).
- `NFR3` Auditability: posted payments are immutable, corrections are reversals, and every match is recorded (proven by `R2.AC9`, `R2.AC10`, `R11`).
- `NFR4` Maintainability: payments depend on the ledger through `app.ledger.api`, on the chart through `app.coa`, and on documents through `app.billing`, enforced by import-linter.
- `NFR5` Consistency: endpoints use the same problem-details shape, session handling and origin check as the rest of the API.
- `NFR6` Report readiness: after this feature, aged receivables and payables can be built purely from posted lines and their open amounts, with no new tables.

## Constraints And Dependencies

- `C1` The ledger owns posting, numbering, balance and immutability; this feature builds `PostingRequest`s and adds the open-amount columns the ledger's design reserved for it.
- `C2` Company default accounts (outstanding receipts, outstanding payments, exchange gain, exchange loss) come from the chart of accounts feature.
- `C3` Documents and their totals come from the invoicing feature; this feature adds their payment state.
- `C4` Live bank feeds, Moyasar and Geidea are Phase 2; this feature reads files.
- `C5` Withholding tax rates are defined by the invoicing feature's tax table; this feature applies them at payment time.
- `C6` PostgreSQL 18 on Neon; local test runs capped at two pytest workers.

## Out Of Scope

- Live bank feeds from an open-banking provider, and the Moyasar and Geidea integrations.
- Automatic matching rules that reconcile without a person confirming.
- Unrealised exchange revaluation at period end (decision D9, a later feature).
- Customer statements, dunning letters and payment reminders.
- Cheque printing and payment files for banks.
- Aged receivables and payables reports themselves — the next feature, which this one makes possible.
