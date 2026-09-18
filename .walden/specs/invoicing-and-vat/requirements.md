---
status: approved
approved_at: 2026-09-18T11:57:16Z
last_modified: 2026-09-18T11:57:16Z
---

# Requirements Document

## Introduction

Invoicing is where the ERP starts earning its keep: customer invoices, vendor bills, credit
and debit notes, the VAT that Saudi Arabia charges on them, and the journal entry each one
posts when it is issued. It is Phase 1, modules 4 and 5 of `finance-erp-mvp-prompt.md`,
built on the core ledger, the chart of accounts and the identity layer that are already in
place.

<!-- decided 2026-09-18: ZATCA e-invoicing (UBL 2.1 XML, signing, QR, clearance and reporting) is a separate feature that follows this one. It needs Fatoora portal credentials, and keeping it apart means invoicing is not blocked waiting for them. This feature produces the documents ZATCA will later wrap. -->
<!-- assumed: tax is computed per line and rounded to two decimal places, then summed (decision D2 in docs/architecture.md) -->
<!-- assumed: prices are tax-exclusive by default, with a per-document flag for tax-inclusive pricing (decision D3) -->
<!-- assumed: withholding tax definitions exist here, but withholding is only applied when payments are made, which is the payments feature -->
<!-- assumed: an invoice's payment state stays "not paid" until the payments feature lands; it is derived, never stored -->

## Requirements

### R1 Tax definitions

**User Story:** As an accountant, I want to define the taxes my company charges, so that invoices calculate VAT without anyone typing a rate.

#### Acceptance Criteria

1. `R1.AC1` WHEN an accountant submits a tax with a name, rate, type and VAT category, the system SHALL create it for that company.
2. `R1.AC2` The system SHALL support the tax types `sale`, `purchase` and `withholding`.
3. `R1.AC3` The system SHALL support the VAT categories `standard`, `zero_rated`, `exempt` and `out_of_scope`.
4. `R1.AC4` WHERE a tax is zero-rated, exempt or out of scope, the system SHALL require a reason to print on the invoice.
5. `R1.AC5` WHEN an accountant submits a tax with an effective date range, the system SHALL apply it only to documents dated inside that range.
6. `R1.AC6` IF an accountant submits a tax rate below zero or above 100, THEN the system SHALL reject it with error code `tax.invalid_rate`.
7. `R1.AC7` IF an accountant submits a tax whose account belongs to another company, THEN the system SHALL reject it with error code `tax.account_not_found`.
8. `R1.AC8` IF an accountant changes the rate of a tax already used on a posted document, THEN the system SHALL reject it with error code `tax.tax_in_use`.
9. `R1.AC9` WHEN an accountant archives a tax, the system SHALL keep it on posted documents and offer it no longer on new ones.
10. `R1.AC10` WHEN the Saudi chart template is loaded, the system SHALL create the standard 15% sales and purchase taxes, a zero-rated tax and an exempt tax.

### R2 Tax calculation

**User Story:** As an accountant, I want VAT calculated the same way every time, so that my return reconciles to the ledger and to ZATCA.

#### Acceptance Criteria

1. `R2.AC1` The system SHALL calculate tax per line and round each line's tax to the currency's decimal places before summing.
2. `R2.AC2` WHEN a line has a discount, the system SHALL calculate tax on the amount after the discount.
3. `R2.AC3` WHERE a document is tax-inclusive, the system SHALL treat each line's price as including its taxes and derive the net amount from it.
4. `R2.AC4` WHEN a line carries several taxes, the system SHALL calculate each tax on the same net amount rather than compounding them.
5. `R2.AC5` The system SHALL group tax amounts by tax for the document's totals.
6. `R2.AC6` The system SHALL calculate the document total as the sum of line net amounts plus the sum of tax amounts.
7. `R2.AC7` IF a line uses a tax that is not effective on the document's date, THEN the system SHALL reject it with error code `tax.not_effective`.
8. `R2.AC8` IF a customer invoice uses a purchase tax, or a vendor bill uses a sales tax, THEN the system SHALL reject it with error code `tax.wrong_tax_type`.
9. `R2.AC9` The system SHALL calculate totals from the lines on every read, never from a stored figure that could drift.

### R3 Customer invoices

**User Story:** As an accountant, I want to raise customer invoices, so that customers can be billed and the revenue reaches the books.

#### Acceptance Criteria

1. `R3.AC1` WHEN an accountant creates an invoice with a customer, a date and lines, the system SHALL store it as a draft.
2. `R3.AC2` WHILE an invoice is a draft, WHEN an accountant changes its lines, dates, customer or currency, the system SHALL apply the change.
3. `R3.AC3` WHEN an accountant sets a due date, the system SHALL store it on the invoice.
4. `R3.AC4` IF an accountant creates an invoice with no lines, THEN the system SHALL allow it as a draft but refuse to post it with error code `invoicing.no_lines`.
5. `R3.AC5` IF an accountant submits a line with a negative quantity or price, THEN the system SHALL reject it with error code `invoicing.invalid_line`.
6. `R3.AC6` IF an accountant submits a line whose income account belongs to another company, THEN the system SHALL reject it with error code `invoicing.account_not_found`.
7. `R3.AC7` WHEN an accountant deletes a draft invoice, the system SHALL remove it and its lines.
8. `R3.AC8` The system SHALL record each line's description, quantity, unit price, discount, taxes and account.
9. `R3.AC9` WHEN an accountant posts an invoice with no due date, the system SHALL use the invoice date as the due date.

### R4 Vendor bills

**User Story:** As an accountant, I want to record vendor bills, so that costs and input VAT reach the books.

#### Acceptance Criteria

1. `R4.AC1` WHEN an accountant creates a bill with a vendor, a date and lines, the system SHALL store it as a draft.
2. `R4.AC2` WHEN an accountant records the vendor's own document number, the system SHALL store it alongside our number.
3. `R4.AC3` IF an accountant records a bill with a vendor document number already used by that vendor, THEN the system SHALL reject it with error code `invoicing.duplicate_vendor_reference`.
4. `R4.AC4` WHEN a bill is posted, the system SHALL credit the payable account and debit the expense accounts named on its lines.

### R5 Credit and debit notes

**User Story:** As an accountant, I want to correct an issued invoice with a credit note, so that the correction is visible rather than hidden by an edit.

#### Acceptance Criteria

1. `R5.AC1` WHEN an accountant creates a credit note from a posted invoice, the system SHALL copy its customer, currency and lines.
2. `R5.AC2` WHEN a credit note is posted, the system SHALL post the opposite entry to the invoice it corrects.
3. `R5.AC3` The system SHALL link every credit and debit note to the document it corrects.
4. `R5.AC4` IF an accountant creates a credit note from a draft document, THEN the system SHALL reject it with error code `invoicing.not_posted`.
5. `R5.AC5` WHERE a credit note is for part of an invoice, the system SHALL allow its lines to be reduced or removed before posting.
6. `R5.AC6` IF the total of a credit note would exceed the invoice it corrects, THEN the system SHALL reject posting it with error code `invoicing.exceeds_original`.

### R6 Posting to the ledger

**User Story:** As a finance controller, I want every issued document to hit the books exactly once, so that the ledger and the documents can never disagree.

#### Acceptance Criteria

1. `R6.AC1` WHEN an accountant posts a document, the system SHALL create exactly one journal entry for it.
2. `R6.AC2` WHEN a customer invoice is posted, the system SHALL debit the receivable account with the total and credit each line's income account with its net amount.
3. `R6.AC3` WHEN a document with tax is posted, the system SHALL post each tax amount to that tax's account.
4. `R6.AC4` WHEN a document is posted, the system SHALL record the partner on every receivable or payable line.
5. `R6.AC5` WHEN a document is posted, the system SHALL record its due date on the receivable or payable line.
6. `R6.AC6` WHEN a document is posted, the system SHALL set its state to posted and record the journal entry against it.
7. `R6.AC7` IF a document is posted twice, THEN the system SHALL reject the second attempt with error code `invoicing.already_posted`.
8. `R6.AC8` IF a document's company has no receivable or payable default account, THEN the system SHALL reject posting with error code `invoicing.default_account_missing`.
9. `R6.AC9` IF posting fails for any reason, THEN the system SHALL leave the document as a draft with no journal entry.
10. `R6.AC10` WHEN a foreign-currency document is posted, the system SHALL let the ledger convert it at the rate for the document's date.

### R7 Numbering and immutability

**User Story:** As an auditor, I want issued documents numbered without gaps and never edited, so that the sequence itself is evidence.

#### Acceptance Criteria

1. `R7.AC1` WHEN a document is posted, the system SHALL give it a gapless number from its journal.
2. `R7.AC2` The system SHALL leave a draft document without a number.
3. `R7.AC3` IF an accountant changes a posted document, THEN the system SHALL reject the change with error code `invoicing.posted_immutable`.
4. `R7.AC4` IF an accountant deletes a posted document, THEN the system SHALL reject it with error code `invoicing.posted_immutable`.
5. `R7.AC5` WHEN an accountant cancels a posted document, the system SHALL reverse its journal entry and mark the document cancelled.
6. `R7.AC6` IF an accountant cancels a document that is already cancelled, THEN the system SHALL reject it with error code `invoicing.already_cancelled`.

### R8 Recurring invoices

**User Story:** As an accountant billing the same customers monthly, I want invoices raised from a template, so that I check drafts rather than retype them.

#### Acceptance Criteria

1. `R8.AC1` WHEN an accountant creates a recurring template with a customer, lines and an interval, the system SHALL store it.
2. `R8.AC2` WHEN the generator runs on or after a template's next date, the system SHALL create a draft invoice from it.
3. `R8.AC3` WHEN a draft is generated, the system SHALL advance the template's next date by its interval.
4. `R8.AC4` The system SHALL create generated invoices as drafts, never posted.
5. `R8.AC5` IF the generator runs twice for the same due date, THEN the system SHALL create only one invoice.
6. `R8.AC6` WHEN an accountant pauses a template, the system SHALL generate nothing from it until it is resumed.
7. `R8.AC7` WHEN the generator runs, the system SHALL report how many invoices it created and from which templates.

### R9 Partners

**User Story:** As an accountant, I want customers and vendors on file, so that invoices carry the details a Saudi tax invoice needs.

#### Acceptance Criteria

1. `R9.AC1` WHEN an accountant creates a partner with a name and type, the system SHALL store it for that company.
2. `R9.AC2` The system SHALL record a partner's VAT number, commercial registration number, address and Arabic name.
3. `R9.AC3` IF an accountant submits a Saudi VAT number that is not fifteen digits starting and ending with 3, THEN the system SHALL reject it with error code `invoicing.invalid_vat_number`.
4. `R9.AC4` IF an accountant archives a partner with posted documents, THEN the system SHALL keep the partner and offer it no longer on new documents.
5. `R9.AC5` IF a document names a partner from another company, THEN the system SHALL reject it with error code `invoicing.partner_not_found`.

### R10 Document API

**User Story:** As an accountant, I want to work with invoices through the application, so that the whole cycle happens in one place.

#### Acceptance Criteria

1. `R10.AC1` WHEN a caller with `invoice:read` lists documents, the system SHALL return them newest first with their state, totals and partner.
2. `R10.AC2` WHEN a caller filters documents by state, type, partner or date range, the system SHALL return only matching documents.
3. `R10.AC3` WHEN a caller with `invoice:read` opens a document, the system SHALL return its lines, taxes and totals.
4. `R10.AC4` WHEN a caller with `invoice:manage` creates, changes or deletes a draft, the system SHALL apply it.
5. `R10.AC5` WHEN a caller with `invoice:post` posts or cancels a document, the system SHALL apply it.
6. `R10.AC6` IF a caller without the needed permission calls any of these, THEN the system SHALL refuse with HTTP 403.
7. `R10.AC7` WHEN a caller with `tax:manage` creates or changes a tax, the system SHALL apply it.
8. `R10.AC8` WHEN a caller with `partner:manage` creates or changes a partner, the system SHALL apply it.
9. `R10.AC9` The system SHALL scope every endpoint in this feature to a company named in its path.

### R11 Audit and traceability

**User Story:** As an auditor, I want to see who issued and cancelled documents, so that the paper trail matches the ledger.

#### Acceptance Criteria

1. `R11.AC1` WHEN a document is posted, the system SHALL append an audit record naming the document number and total.
2. `R11.AC2` WHEN a document is cancelled, the system SHALL append an audit record naming the document and the reversal entry.
3. `R11.AC3` WHEN a tax or partner is created or changed, the system SHALL append an audit record.
4. `R11.AC4` WHEN an accountant opens a posted document, the system SHALL report the journal entry it posted.

## Non-Functional Requirements

- `NFR1` Integrity: a document and its journal entry are created in one transaction, and the ledger's unique constraint guarantees at most one entry per document (proven by `R6.AC1`, `R6.AC9`).
- `NFR2` Precision: money is `Decimal` throughout, rounded per line to the currency's decimal places, and totals always recomputed from lines (proven by `R2.AC1`, `R2.AC9`).
- `NFR3` Auditability: posted documents are immutable and corrections are visible as credit notes or reversals (proven by `R7`).
- `NFR4` Maintainability: invoicing depends on the ledger only through `app.ledger.api` and on the chart only through `app.coa`, enforced by import-linter.
- `NFR5` Readiness for ZATCA: every posted invoice carries the fields a Saudi tax invoice needs — seller and buyer VAT numbers, per-line tax category and reason, and totals per tax — so the next feature can render them without schema changes.
- `NFR6` Consistency: endpoints use the same problem-details shape, session handling and origin check as the rest of the API.

## Constraints And Dependencies

- `C1` The ledger owns posting, numbering and immutability; this feature builds `PostingRequest`s and never writes journal lines itself.
- `C2` The chart of accounts owns accounts, journals and company defaults; invoicing reads them.
- `C3` Payments, reconciliation and the resulting payment states are a later feature; documents show "not paid" until then.
- `C4` ZATCA e-invoicing is the next feature; nothing here talks to ZATCA.
- `C5` Background jobs do not exist yet, so recurring invoices are generated by an endpoint or command rather than a scheduler.
- `C6` PostgreSQL 18 on Neon; local test runs capped at two pytest workers.

## Out Of Scope

- ZATCA XML, signing, QR codes, clearance and reporting — the `zatca-einvoicing` feature.
- Payments, reconciliation, and partial or full payment states.
- Inventory, products and stock valuation; lines carry a free-text description and an account.
- Reports, including the VAT return itself; this feature only tags lines so the return can be built.
- PDF rendering of invoices.
- Withholding tax deduction at payment time.
