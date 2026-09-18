---
status: approved
approved_at: 2026-09-18T20:12:28Z
last_modified: 2026-09-18T21:11:22Z
source_design_approved_at: 2026-09-18T20:12:28Z
---

# Implementation Plan

Order: the ledger change first, because the VAT return cannot be written until posting records
what a tax was charged on. Then the pure parts (periods, the account tree, the box map), then
the one balance query everything else reads, then each report, then the reconciliations that
tie them together, then the API.

Verification commands run from the repository root as `sh -c "cd backend && …"`. Database
tests use the Neon `test` branch through `TEST_DATABASE_URL`.

- [x] 1. The basis a VAT return needs
  - [x] 1.1 Migration `0006`: `tax_base`, its check constraint, the backfill, `report:read`
    - Requirements: `R6.AC1`, `R9.AC1`
    - Design: Migration `0006_reporting`; Data Models
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/reporting/test_migration_reporting.py -q"]
        covers: ["R6.AC1", "R9.AC1"]
      - command: ["sh", "-c", "cd backend && uv run pytest tests/invariants/test_tax_base.py -q"]
        covers: ["R6.AC1"]
  - [x] 1.2 Posting records the basis, including for zero-rated supplies
    - Requirements: `R6.AC2`, `R6.AC5`, `R6.AC7`
    - Design: The VAT return's missing basis
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/billing/test_tax_basis.py -q"]
        covers: ["R6.AC2", "R6.AC5", "R6.AC7"]
      - command: ["sh", "-c", "cd backend && uv run pytest tests/billing tests/ledger -q -n 2"]
        covers: ["R6.AC2"]

- [x] 2. The pure parts
  - [x] 2.1 Periods, fiscal years and named ranges
    - Requirements: `R1.AC7`, `R3.AC5`, `R8.AC2`, `R8.AC3`
    - Design: Components And Interfaces (`app.reporting.periods`)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/unit/test_periods.py -q"]
        covers: ["R1.AC7", "R3.AC5", "R8.AC2", "R8.AC3"]
  - [x] 2.2 The account tree and its subtotals
    - Requirements: `R2.AC4`, `R3.AC7`
    - Design: Components And Interfaces (`app.reporting.balances`, `tree`)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/unit/test_account_tree.py -q"]
        covers: ["R2.AC4", "R3.AC7"]
  - [x] 2.3 The ZATCA box map
    - Requirements: `R6.AC3`, `R6.AC5`
    - Design: Sub-decisions (VAT box map)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/unit/test_vat_boxes.py -q"]
        covers: ["R6.AC3", "R6.AC5"]

- [x] 3. The balance query and the three statements
  - [x] 3.1 `account_balances`: opening, debit, credit, closing
    - Requirements: `R1.AC1`, `R1.AC2`, `R1.AC3`, `R1.AC4`, `R1.AC5`, `R1.AC6`, `R1.AC8`, `R8.AC6`
    - Design: Data Models (the balance query); Option A
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/reporting/test_trial_balance.py -q"]
        covers: ["R1.AC1", "R1.AC2", "R1.AC3", "R1.AC4", "R1.AC5", "R1.AC6", "R1.AC8", "R8.AC6"]
  - [x] 3.2 Profit and loss, with an optional comparison period
    - Requirements: `R2.AC1`, `R2.AC2`, `R2.AC3`, `R2.AC5`, `R2.AC6`, `R2.AC7`, `R2.AC8`
    - Design: Components And Interfaces (`statements.profit_and_loss`)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/reporting/test_profit_and_loss.py -q"]
        covers: ["R2.AC1", "R2.AC2", "R2.AC3", "R2.AC5", "R2.AC6", "R2.AC7", "R2.AC8"]
  - [x] 3.3 Balance sheet, with earnings computed rather than posted
    - Requirements: `R3.AC1`, `R3.AC2`, `R3.AC3`, `R3.AC4`, `R3.AC6`
    - Design: Components And Interfaces (`statements.balance_sheet`)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/reporting/test_balance_sheet.py -q"]
        covers: ["R3.AC1", "R3.AC2", "R3.AC3", "R3.AC4", "R3.AC6"]

- [x] 4. The reports with their own shapes
  - [x] 4.1 Cash flow from non-cash counterpart lines
    - Requirements: `R4.AC1`, `R4.AC2`, `R4.AC3`, `R4.AC4`, `R4.AC5`, `R4.AC6`
    - Design: Sub-decisions (cash flow classification); `app.reporting.cash_flow`
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/reporting/test_cash_flow.py -q"]
        covers: ["R4.AC1", "R4.AC2", "R4.AC3", "R4.AC4", "R4.AC5", "R4.AC6"]
  - [x] 4.2 Aged receivables and payables, today and as of a past date
    - Requirements: `R5.AC1`, `R5.AC2`, `R5.AC3`, `R5.AC4`, `R5.AC6`, `R5.AC7`, `R5.AC8`
    - Design: Components And Interfaces (`app.reporting.aged`); Sub-decisions (aged as of a past date)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/reporting/test_aged.py -q"]
        covers: ["R5.AC1", "R5.AC2", "R5.AC3", "R5.AC4", "R5.AC6", "R5.AC7", "R5.AC8"]
  - [x] 4.3 The VAT return by ZATCA box
    - Requirements: `R6.AC1`, `R6.AC4`, `R6.AC6`, `R6.AC7`
    - Design: Components And Interfaces (`app.reporting.vat_return`)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/reporting/test_vat_return.py -q"]
        covers: ["R6.AC1", "R6.AC4", "R6.AC6", "R6.AC7"]
  - [x] 4.4 Account detail with a running balance
    - Requirements: `R7.AC1`, `R7.AC2`, `R7.AC3`, `R7.AC5`, `R7.AC6`
    - Design: Components And Interfaces (`app.reporting.detail`)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/reporting/test_detail.py -q"]
        covers: ["R7.AC1", "R7.AC2", "R7.AC3", "R7.AC5", "R7.AC6"]

- [x] 5. The reports agree
  - [x] 5.1 Every reconciliation, on books built by hand
    - Requirements: `R10.AC1`, `R10.AC2`, `R10.AC3`, `R10.AC4`, `R10.AC5`, `R10.AC6`, `R10.AC7`, `R10.AC8`, `R7.AC4`, `R5.AC5`
    - Design: Testing Strategy (Reconciliation)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/reporting/test_reconciles.py -q"]
        covers: ["R10.AC1", "R10.AC2", "R10.AC3", "R10.AC4", "R10.AC5", "R10.AC6", "R10.AC7", "R10.AC8", "R7.AC4", "R5.AC5"]
  - [x] 5.2 Every reconciliation, on books nobody designed
    - Requirements: `R10.AC1`, `R10.AC2`, `R10.AC3`, `R10.AC4`, `NFR1`
    - Design: Testing Strategy (Property); Verification Plan
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/reporting/test_properties.py -q"]
        covers: ["R10.AC1", "R10.AC2", "R10.AC3", "R10.AC4"]

- [x] 6. API
  - [x] 6.1 Seven endpoints, one permission, one envelope
    - Requirements: `R8.AC1`, `R8.AC4`, `R8.AC5`, `R9.AC1`, `R9.AC2`, `R9.AC3`, `R9.AC4`, `R9.AC5`, `R9.AC6`, `NFR5`
    - Design: Components And Interfaces (`app.api.routes.reports`); Error Handling
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/api/test_reports.py -q"]
        covers: ["R8.AC1", "R8.AC4", "R8.AC5", "R9.AC1", "R9.AC2", "R9.AC3", "R9.AC4", "R9.AC5", "R9.AC6"]
      - command: ["sh", "-c", "cd backend && uv run lint-imports"]
        covers: ["NFR4"]
  - [x] 6.2 A report writes nothing, and returns inside two seconds
    - Requirements: `NFR2`, `NFR3`, `NFR6`
    - Design: Security Considerations; Failure Modes And Tradeoffs
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/reporting/test_read_only.py -q"]
        covers: ["NFR2", "NFR3", "NFR6"]

- [ ] 7. Delivery
  - [ ] 7.1 Full gate: format, lint, layers, whole suite
    - Requirements: `NFR1`, `NFR4`, `NFR5`, `C1`, `C2`, `C3`, `C4`, `C5`, `C6`, `C7`
    - Design: Verification Plan
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run ruff format --check . && uv run ruff check . && uv run lint-imports"]
        covers: ["NFR4"]
      - command: ["sh", "-c", "cd backend && uv run pytest tests -q -n 2 --ignore=tests/concurrency"]
        covers: ["NFR1", "NFR2"]
      - command: ["sh", "-c", "cd backend && uv run pytest tests/concurrency -q"]
        covers: ["C1"]
  - [ ] 7.2 Push, green CI, merge
    - Requirements: `C7`
    - Design: Verification Plan
    - Verification:
      - command: ["sh", "-c", "git status --porcelain -- backend .github | grep -q . && exit 1 || exit 0"]
      - command: ["sh", "-c", "git fetch origin && test \"$(git rev-parse HEAD)\" = \"$(git rev-parse origin/main)\""]
