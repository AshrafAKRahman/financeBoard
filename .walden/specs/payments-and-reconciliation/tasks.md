---
status: approved
approved_at: 2026-09-18T16:04:36Z
last_modified: 2026-09-18T16:16:40Z
source_design_approved_at: 2026-09-18T16:04:36Z
---

# Implementation Plan

Order: the schema and its invariants first, because everything else writes through them;
then the pure exchange-difference arithmetic and the statement parsers (no database); then
payments, matching, statements; then the API; then the races; then delivery.

Verification commands run from the repository root as `sh -c "cd backend && …"`. Database
tests use the Neon `test` branch through `TEST_DATABASE_URL`; concurrency tests use
`DATABASE_URL_DIRECT`.

- [x] 1. Schema and invariants
  - [x] 1.1 Migration `0005`: residual columns, the replaced line guard, `reconciliation`, `payment`, statements, permissions
    - Requirements: `R3.AC1`, `R3.AC6`, `R7.AC3`, `R10.AC7`
    - Design: Data Models; Migration `0005_payments`; Overview (open amounts)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/treasury/test_migration_payments.py -q"]
        covers: ["R3.AC1", "R3.AC6", "R7.AC3", "R10.AC7"]
  - [x] 1.2 The residual trigger and the payment guard, proven with raw SQL
    - Requirements: `R3.AC4`, `R3.AC5`, `R2.AC9`, `NFR1`, `NFR3`
    - Design: Data Models (`reconciliation_residual_check`, `payment_guard`)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/invariants/test_residuals.py -q"]
        covers: ["R3.AC4", "R3.AC5", "R2.AC9"]

- [x] 2. Pure arithmetic and parsing
  - [x] 2.1 Exchange differences, both directions
    - Requirements: `R5.AC1`, `R5.AC2`, `R5.AC3`, `R5.AC7`, `NFR2`
    - Design: Components And Interfaces (`app.treasury.exchange`)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/unit/test_exchange.py -q"]
        covers: ["R5.AC1", "R5.AC2", "R5.AC3", "R5.AC7"]
  - [x] 2.2 CSV, MT940 and OFX sources, and a stable import hash
    - Requirements: `R7.AC1`, `R7.AC2`, `R7.AC5`
    - Design: Components And Interfaces (`app.treasury.statements`); Sub-decisions (parsing, duplicates)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/unit/test_statement_parsers.py -q"]
        covers: ["R7.AC1", "R7.AC2", "R7.AC5"]

- [x] 3. Payments
  - [x] 3.1 Recording, editing and deleting a draft payment
    - Requirements: `R1.AC1`, `R1.AC2`, `R1.AC3`, `R1.AC4`, `R1.AC5`, `R1.AC6`, `R1.AC7`, `R1.AC8`
    - Design: Components And Interfaces (`app.treasury.payments`); Data Models (state machine)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/treasury/test_payments.py -q"]
        covers: ["R1.AC1", "R1.AC2", "R1.AC3", "R1.AC4", "R1.AC5", "R1.AC6", "R1.AC7", "R1.AC8"]
  - [x] 3.2 Posting a payment through the outstanding accounts, and cancelling it
    - Requirements: `R2.AC1`, `R2.AC2`, `R2.AC3`, `R2.AC4`, `R2.AC5`, `R2.AC6`, `R2.AC7`, `R2.AC8`, `R2.AC10`, `R3.AC2`
    - Design: Overview (posting a customer receipt); Components And Interfaces (`post_payment`)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/treasury/test_payment_posting.py -q"]
        covers: ["R2.AC1", "R2.AC2", "R2.AC3", "R2.AC4", "R2.AC5", "R2.AC6", "R2.AC7", "R2.AC8", "R2.AC10", "R3.AC2"]
  - [x] 3.3 Withholding tax withheld at payment
    - Requirements: `R9.AC1`, `R9.AC2`, `R9.AC3`, `R9.AC4`
    - Design: Overview (with withholding tax)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/treasury/test_withholding.py -q"]
        covers: ["R9.AC1", "R9.AC2", "R9.AC3", "R9.AC4"]

- [x] 4. Matching
  - [x] 4.1 Matching and unmatching open lines
    - Requirements: `R3.AC3`, `R4.AC1`, `R4.AC2`, `R4.AC3`, `R4.AC4`, `R4.AC5`, `R4.AC6`, `R4.AC7`, `R4.AC8`
    - Design: Components And Interfaces (`app.treasury.matching`); Sub-decisions (granularity)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/treasury/test_matching.py -q"]
        covers: ["R3.AC3", "R4.AC1", "R4.AC2", "R4.AC3", "R4.AC4", "R4.AC5", "R4.AC6", "R4.AC7", "R4.AC8"]
  - [x] 4.2 Suggestions for a payment, and open items for a partner
    - Requirements: `R4.AC9`, `NFR6`
    - Design: Components And Interfaces (`suggest_for_payment`, `open_lines`)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/treasury/test_suggestions.py -q"]
        covers: ["R4.AC9"]
  - [x] 4.3 Exchange differences posted on matching and reversed on unmatching
    - Requirements: `R5.AC4`, `R5.AC5`, `R5.AC6`
    - Design: Components And Interfaces (`post_difference`); Failure Modes And Tradeoffs
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/treasury/test_exchange_posting.py -q"]
        covers: ["R5.AC4", "R5.AC5", "R5.AC6"]
  - [x] 4.4 The payment state of a document, derived
    - Requirements: `R6.AC1`, `R6.AC2`, `R6.AC3`, `R6.AC4`, `R6.AC5`, `R6.AC6`
    - Design: Components And Interfaces (`app.treasury.state`); Sub-decisions (payment state)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/treasury/test_payment_state.py -q"]
        covers: ["R6.AC1", "R6.AC2", "R6.AC3", "R6.AC4", "R6.AC5", "R6.AC6"]

- [x] 5. Bank statements
  - [x] 5.1 Importing a statement, with duplicates and rejected rows reported
    - Requirements: `R7.AC4`, `R7.AC6`, `R7.AC7`, `R7.AC8`
    - Design: Components And Interfaces (`import_statement`); Failure Modes And Tradeoffs (re-import)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/treasury/test_statement_import.py -q"]
        covers: ["R7.AC4", "R7.AC6", "R7.AC7", "R7.AC8"]
  - [x] 5.2 Reconciling a statement line to the bank account, and undoing it
    - Requirements: `R8.AC1`, `R8.AC2`, `R8.AC3`, `R8.AC4`, `R8.AC5`, `R8.AC6`, `R8.AC7`
    - Design: Overview (then the bank statement line); Components And Interfaces (`reconcile_line`)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/treasury/test_statement_reconcile.py -q"]
        covers: ["R8.AC1", "R8.AC2", "R8.AC3", "R8.AC4", "R8.AC5", "R8.AC6", "R8.AC7"]

- [x] 6. API
  - [x] 6.1 Endpoints, permissions and problem details
    - Requirements: `R10.AC1`, `R10.AC2`, `R10.AC3`, `R10.AC4`, `R10.AC5`, `R10.AC6`, `R10.AC8`, `NFR5`
    - Design: Components And Interfaces (`app.api.routes.treasury`); Error Handling
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/api/test_treasury.py -q"]
        covers: ["R10.AC1", "R10.AC2", "R10.AC3", "R10.AC4", "R10.AC5", "R10.AC6", "R10.AC8"]
      - command: ["sh", "-c", "cd backend && uv run lint-imports"]
        covers: ["NFR4"]
  - [x] 6.2 Audit records for every money movement
    - Requirements: `R11.AC1`, `R11.AC2`, `R11.AC3`, `R11.AC5`
    - Design: Security Considerations; Requirement Coverage (`R11`)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/treasury/test_audit.py -q"]
        covers: ["R11.AC1", "R11.AC2", "R11.AC3", "R11.AC5"]

- [x] 7. Races
  - [x] 7.1 Two clerks, one invoice; two threads, one statement line
    - Requirements: `R3.AC4`, `R11.AC4`, `NFR1`
    - Design: Failure Modes And Tradeoffs (double payment)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/concurrency/test_matching_races.py -q"]
        covers: ["R11.AC4"]

- [ ] 8. Delivery
  - [ ] 8.1 Full gate: format, lint, layers, whole suite
    - Requirements: `NFR2`, `NFR4`, `NFR5`, `NFR6`, `C1`, `C2`, `C3`, `C4`, `C5`
    - Design: Verification Plan
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run ruff format --check . && uv run ruff check . && uv run lint-imports"]
        covers: ["NFR4"]
      - command: ["sh", "-c", "cd backend && uv run pytest tests -q -n 2 --ignore=tests/concurrency"]
        covers: ["NFR2", "NFR6"]
      - command: ["sh", "-c", "cd backend && uv run pytest tests/concurrency -q"]
        covers: ["NFR1"]
  - [ ] 8.2 An end-to-end pass: foreign-currency invoice, payment, match, statement
    - Requirements: `R5.AC4`, `R6.AC3`, `NFR6`
    - Design: Verification Plan (operational evidence)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/treasury/test_end_to_end.py -q"]
        covers: ["R5.AC4", "R6.AC3", "NFR6"]
  - [ ] 8.3 Push, green CI, merge
    - Requirements: `C6`
    - Design: Verification Plan
    - Verification:
      - command: ["sh", "-c", "git status --porcelain -- backend .github | grep -q . && exit 1 || exit 0"]
      - command: ["sh", "-c", "git fetch origin && test \"$(git rev-parse HEAD)\" = \"$(git rev-parse origin/main)\""]
