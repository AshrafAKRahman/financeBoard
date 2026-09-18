---
status: approved
approved_at: 2026-09-18T19:02:29Z
last_modified: 2026-09-18T19:02:29Z
source_design_approved_at: 2026-09-18T19:02:29Z
---

# Implementation Plan

Order: the pure arithmetic first (it needs no database and everything else depends on it),
then the schema, then partners and taxes, then documents and posting, then recurring, then
the API.

Verification commands run from the repository root as `sh -c "cd backend && …"`. Database
tests use the Neon `test` branch through `TEST_DATABASE_URL`.

- [x] 1. Tax arithmetic
  - [x] 1.1 Line and document totals, property-tested
    - Requirements: `R2.AC1`, `R2.AC2`, `R2.AC3`, `R2.AC4`, `R2.AC5`, `R2.AC6`, `R2.AC9`, `NFR2`
    - Design: Components And Interfaces (`app.billing.totals`); Sub-decisions (rounding)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/unit/test_totals.py -q"]
        covers: ["R2.AC1", "R2.AC2", "R2.AC3", "R2.AC4", "R2.AC5", "R2.AC6", "R2.AC9"]

- [x] 2. Schema
  - [x] 2.1 Migration `0004`: partners, taxes, documents, lines, recurring templates, permissions
    - Requirements: `R3.AC8`, `R4.AC3`, `R5.AC3`, `R9.AC2`, `R10.AC9`
    - Design: Data Models
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/billing/test_migration_invoicing.py -q"]
        covers: ["R3.AC8", "R4.AC3", "R5.AC3", "R9.AC2", "R10.AC9"]
  - [x] 2.2 The posted-document trigger, proven with raw SQL
    - Requirements: `R7.AC3`, `R7.AC4`, `NFR3`
    - Design: Data Models (`document_guard`)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/invariants/test_document_guard.py -q"]
        covers: ["R7.AC3", "R7.AC4"]

- [x] 3. Partners and taxes
  - [x] 3.1 Partners, including the Saudi VAT number shape
    - Requirements: `R9.AC1`, `R9.AC3`, `R9.AC4`, `R9.AC5`
    - Design: Components And Interfaces (`app.billing.partners`)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/billing/test_partners.py -q"]
        covers: ["R9.AC1", "R9.AC3", "R9.AC4", "R9.AC5"]
  - [x] 3.2 Taxes with effective dates, and `install_saudi_taxes` for a loaded chart
    - Requirements: `R1.AC1`, `R1.AC2`, `R1.AC3`, `R1.AC4`, `R1.AC5`, `R1.AC6`, `R1.AC7`, `R1.AC8`, `R1.AC9`, `R1.AC10`
    - Design: Components And Interfaces (`app.billing.taxes`); Data Models (Saudi taxes)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/billing/test_taxes.py -q"]
        covers: ["R1.AC1", "R1.AC2", "R1.AC3", "R1.AC4", "R1.AC5", "R1.AC6", "R1.AC7", "R1.AC8", "R1.AC9", "R1.AC10"]

- [x] 4. Documents
  - [x] 4.1 Drafting invoices and bills
    - Requirements: `R3.AC1`, `R3.AC2`, `R3.AC3`, `R3.AC5`, `R3.AC6`, `R3.AC7`, `R4.AC1`, `R4.AC2`, `R4.AC3`
    - Design: Components And Interfaces (`app.billing.documents`); Data Models (state machine)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/billing/test_documents.py -q"]
        covers: ["R3.AC1", "R3.AC2", "R3.AC3", "R3.AC5", "R3.AC6", "R3.AC7", "R4.AC1", "R4.AC2", "R4.AC3"]
  - [x] 4.2 Posting a document to the ledger
    - Requirements: `R3.AC4`, `R3.AC9`, `R4.AC4`, `R6.AC1`, `R6.AC2`, `R6.AC3`, `R6.AC4`, `R6.AC5`, `R6.AC6`, `R6.AC7`, `R6.AC8`, `R6.AC9`, `R6.AC10`, `R7.AC1`, `R7.AC2`, `R11.AC1`, `R11.AC4`, `NFR1`
    - Design: Architecture (Posting sequence); Error Handling
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/billing/test_posting.py -q"]
        covers: ["R3.AC4", "R3.AC9", "R4.AC4", "R6.AC1", "R6.AC2", "R6.AC3", "R6.AC4", "R6.AC5", "R6.AC6", "R6.AC7", "R6.AC8", "R6.AC9", "R6.AC10", "R7.AC1", "R7.AC2", "R11.AC1", "R11.AC4"]
  - [x] 4.3 Tax rules at posting time
    - Requirements: `R2.AC7`, `R2.AC8`
    - Design: Architecture (Posting sequence step 2); Error Handling
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/billing/test_posting.py -q -k tax"]
        covers: ["R2.AC7", "R2.AC8"]
  - [x] 4.4 Cancelling, and credit and debit notes
    - Requirements: `R5.AC1`, `R5.AC2`, `R5.AC4`, `R5.AC5`, `R5.AC6`, `R7.AC5`, `R7.AC6`, `R11.AC2`
    - Design: Components And Interfaces (`credit_note_from`); Failure Modes (credit note race)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/billing/test_corrections.py -q"]
        covers: ["R5.AC1", "R5.AC2", "R5.AC4", "R5.AC5", "R5.AC6", "R7.AC5", "R7.AC6", "R11.AC2"]

- [x] 5. Recurring invoices
  - [x] 5.1 Templates and idempotent generation
    - Requirements: `R8.AC1`, `R8.AC2`, `R8.AC3`, `R8.AC4`, `R8.AC5`, `R8.AC6`, `R8.AC7`
    - Design: Components And Interfaces (`app.billing.recurring`)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/billing/test_recurring.py -q"]
        covers: ["R8.AC1", "R8.AC2", "R8.AC3", "R8.AC4", "R8.AC5", "R8.AC6", "R8.AC7"]

- [x] 6. API
  - [x] 6.1 Document, partner, tax and recurring endpoints with their permissions
    - Requirements: `R10.AC1`, `R10.AC2`, `R10.AC3`, `R10.AC4`, `R10.AC5`, `R10.AC6`, `R10.AC7`, `R10.AC8`, `R11.AC3`, `NFR6`
    - Design: Components And Interfaces (endpoint table); Permission catalogue additions
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/api/test_billing.py tests/api/test_route_protection.py -q"]
        covers: ["R10.AC1", "R10.AC2", "R10.AC3", "R10.AC4", "R10.AC5", "R10.AC6", "R10.AC7", "R10.AC8", "R11.AC3"]

- [x] 7. Gates and delivery
  - [x] 7.1 Full gate run
    - Requirements: `NFR4`, `NFR5`
    - Design: Verification Plan
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run ruff check . && uv run lint-imports"]
      - command: ["sh", "-c", "cd backend && uv run pytest tests/unit tests/ledger tests/identity tests/coa tests/billing tests/invariants tests/api -n 2 -q"]
      - command: ["sh", "-c", "cd backend && uv run pytest tests/concurrency -q"]
  - [x] 7.2 Push, green CI, merge
    - Requirements: `C6`
    - Design: Verification Plan
    - Verification:
      - command: ["sh", "-c", "git status --porcelain -- backend .github | grep -q . && exit 1 || exit 0"]
      - command: ["sh", "-c", "git fetch origin && test \"$(git rev-parse HEAD)\" = \"$(git rev-parse origin/main)\""]
