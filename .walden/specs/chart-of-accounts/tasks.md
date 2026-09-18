---
status: approved
approved_at: 2026-09-18T09:41:50Z
last_modified: 2026-09-18T11:47:17Z
source_design_approved_at: 2026-09-18T09:41:03Z
---

# Implementation Plan

Order: schema and the hierarchy trigger first, then the `app.coa` services, then the API on
top. The permission codes land with the services so the API cannot be written against a
permission that does not exist.

Verification commands run from the repository root as `sh -c "cd backend && …"`. Database
tests use the Neon `test` branch through `TEST_DATABASE_URL`.

- [x] 1. Schema and hierarchy rules
  - [x] 1.1 Migration `0003`: default-account columns, chart index
    - Requirements: `R5.AC2`
    - Design: Data Models (table changes)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/coa/test_migration_chart.py -q"]
        covers: ["R5.AC2"]
  - [x] 1.2 Migration `0003`: the hierarchy trigger, proven with raw SQL
    - Requirements: `R2.AC3`, `R2.AC4`, `R2.AC5`
    - Design: Data Models (hierarchy trigger); Sub-decisions (cycle detection)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/invariants/test_hierarchy.py -q"]
        covers: ["R2.AC3", "R2.AC4", "R2.AC5"]

- [x] 2. Chart services
  - [x] 2.1 Accounts: create, edit, and the rules that guard them
    - Requirements: `R1.AC1`, `R1.AC2`, `R1.AC3`, `R1.AC4`, `R1.AC5`, `R1.AC6`, `R1.AC7`, `R1.AC8`
    - Design: Components And Interfaces (`app.coa.accounts`); Error Handling
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/coa/test_accounts.py -q"]
        covers: ["R1.AC1", "R1.AC2", "R1.AC3", "R1.AC4", "R1.AC5", "R1.AC6", "R1.AC7", "R1.AC8"]
  - [x] 2.2 Hierarchy and chart listing
    - Requirements: `R2.AC1`, `R2.AC2`, `R2.AC6`, `R2.AC7`, `R2.AC8`
    - Design: Components And Interfaces (`list_chart`)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/coa/test_hierarchy.py -q"]
        covers: ["R2.AC1", "R2.AC2", "R2.AC6", "R2.AC7", "R2.AC8"]
  - [x] 2.3 Archiving instead of deleting
    - Requirements: `R3.AC1`, `R3.AC2`, `R3.AC3`, `R3.AC4`, `R3.AC5`, `R3.AC6`, `NFR2`
    - Design: Failure Modes (archiving); Error Handling
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/coa/test_archiving.py -q"]
        covers: ["R3.AC1", "R3.AC2", "R3.AC3", "R3.AC4", "R3.AC5", "R3.AC6"]
  - [x] 2.4 Journals
    - Requirements: `R4.AC1`, `R4.AC2`, `R4.AC3`, `R4.AC4`, `R4.AC5`, `R4.AC6`, `R4.AC7`
    - Design: Components And Interfaces (`app.coa.journals`)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/coa/test_journals.py -q"]
        covers: ["R4.AC1", "R4.AC2", "R4.AC3", "R4.AC4", "R4.AC5", "R4.AC6", "R4.AC7"]
  - [x] 2.5 Company default accounts
    - Requirements: `R5.AC1`, `R5.AC3`, `R5.AC4`, `R5.AC5`, `R5.AC6`, `R5.AC7`
    - Design: Data Models (defaults table); Components And Interfaces (`app.coa.defaults`)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/coa/test_defaults.py tests/unit/test_default_subtypes.py -q"]
        covers: ["R5.AC1", "R5.AC3", "R5.AC4", "R5.AC5", "R5.AC6", "R5.AC7"]
  - [x] 2.6 Saudi template as data, with an all-or-nothing loader
    - Requirements: `R6.AC1`, `R6.AC2`, `R6.AC3`, `R6.AC4`, `R6.AC5`, `R6.AC6`, `R6.AC7`, `NFR3`, `NFR5`
    - Design: Components And Interfaces (`app.coa.templates`); Failure Modes (template load)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/unit/test_template_data.py tests/coa/test_templates.py -q"]
        covers: ["R6.AC1", "R6.AC2", "R6.AC3", "R6.AC4", "R6.AC5", "R6.AC6", "R6.AC7"]
  - [x] 2.7 Exchange rates, including bulk import
    - Requirements: `R7.AC1`, `R7.AC2`, `R7.AC3`, `R7.AC4`, `R7.AC5`, `R7.AC6`
    - Design: Components And Interfaces (`app.coa.rates`); Sub-decisions (rate import)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/coa/test_rates.py -q"]
        covers: ["R7.AC1", "R7.AC2", "R7.AC3", "R7.AC4", "R7.AC5", "R7.AC6"]
  - [x] 2.8 Chart readiness check
    - Requirements: `R8.AC1`, `R8.AC2`, `R8.AC3`, `R8.AC4`, `R8.AC5`
    - Design: Components And Interfaces (`app.coa.readiness`)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/coa/test_readiness.py -q"]
        covers: ["R8.AC1", "R8.AC2", "R8.AC3", "R8.AC4", "R8.AC5"]

- [x] 3. HTTP surface
  - [x] 3.1 New permissions and the company-scoped router skeleton
    - Requirements: `R14.AC1`, `R14.AC2`, `R14.AC3`, `R14.AC4`, `R14.AC5`, `R14.AC6`, `NFR6`
    - Design: Permission catalogue additions; Security Considerations
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/api/test_chart_access.py tests/api/test_route_protection.py -q"]
        covers: ["R14.AC1", "R14.AC2", "R14.AC3", "R14.AC4", "R14.AC5", "R14.AC6"]
  - [x] 3.2 Account endpoints
    - Requirements: `R9.AC1`, `R9.AC2`, `R9.AC3`, `R9.AC4`, `R9.AC5`, `R9.AC6`, `R9.AC7`, `R9.AC8`
    - Design: Components And Interfaces (`app.api.routes.chart` endpoint table)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/api/test_chart_accounts.py -q"]
        covers: ["R9.AC1", "R9.AC2", "R9.AC3", "R9.AC4", "R9.AC5", "R9.AC6", "R9.AC7", "R9.AC8"]
  - [x] 3.3 Journal, defaults, template and rate endpoints
    - Requirements: `R10.AC1`, `R10.AC2`, `R10.AC3`, `R10.AC4`, `R10.AC5`, `R11.AC1`, `R11.AC2`, `R11.AC3`, `R11.AC4`, `R12.AC1`, `R12.AC2`, `R12.AC3`, `R12.AC4`, `R13.AC1`, `R13.AC2`, `R13.AC3`, `R13.AC4`
    - Design: Components And Interfaces (endpoint table)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/api/test_chart_setup.py -q"]
        covers: ["R10.AC1", "R10.AC2", "R10.AC3", "R10.AC4", "R10.AC5", "R11.AC1", "R11.AC2", "R11.AC3", "R11.AC4", "R12.AC1", "R12.AC2", "R12.AC3", "R12.AC4", "R13.AC1", "R13.AC2", "R13.AC3", "R13.AC4"]

- [ ] 4. Gates and delivery
  - [x] 4.1 Architecture contract for the new module and a full gate run
    - Requirements: `NFR1`, `NFR4`
    - Design: Architecture (layering); Verification Plan
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run ruff check . && uv run lint-imports"]
      - command: ["sh", "-c", "cd backend && uv run pytest tests/unit tests/ledger tests/identity tests/coa tests/invariants tests/api -n 2 -q"]
      - command: ["sh", "-c", "cd backend && uv run pytest tests/concurrency -q"]
  - [ ] 4.2 Push the branch, green CI, merge
    - Requirements: `C5`
    - Design: Verification Plan
    - Verification:
      - command: ["sh", "-c", "git status --porcelain | grep -q . && exit 1 || exit 0"]
      - command: ["sh", "-c", "git fetch origin && test \"$(git rev-parse HEAD)\" = \"$(git rev-parse origin/main)\""]
