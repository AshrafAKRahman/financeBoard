---
status: approved
approved_at: 2026-09-17T19:22:16Z
last_modified: 2026-09-17T20:12:41Z
source_design_approved_at: 2026-09-17T19:11:00Z
---

# Implementation Plan

A draft of much of this code already exists in `backend/` (written before the spec, see
`C6`). Every task below therefore reads "write or correct": the existing file is reviewed
against the approved design, fixed, and only counts as done when its verification passes.

All verification commands run from the repository root (`finance/`) and use
`sh -c "cd backend && …"`. Database tests read `TEST_DATABASE_URL`, which the test harness
loads from `backend/.env` (Neon branch `test`).

- [x] 1. Project setup and shared foundations
  - [x] 1.1 Backend project, dependency lock, lint and architecture gates
    - Requirements: `NFR6`, `C2`, `C7`
    - Design: Architecture (module boundaries); Testing Strategy (Architecture row)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv sync --group dev"]
      - command: ["sh", "-c", "cd backend && uv run ruff check ."]
      - command: ["sh", "-c", "cd backend && uv run lint-imports"]
  - [x] 1.2 Shared money, id and error helpers with unit tests
    - Requirements: `R7.AC4`, `R13.AC3`, `NFR2`
    - Design: Components And Interfaces (`app.shared`); Error Handling
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/unit/test_basics.py tests/unit/test_errors.py -q"]
        covers: ["R7.AC4", "R13.AC3"]
  - [x] 1.3 Engines, unit of work and env loading for Neon pooled and direct endpoints
    - Requirements: `R14.AC1`, `R14.AC2`, `R14.AC3`
    - Design: Components And Interfaces (`app.db`); Failure Modes (Neon suspend, PgBouncer)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/unit/test_engines.py -q"]
        covers: ["R14.AC1", "R14.AC3"]
      - command: ["sh", "-c", "cd backend && uv run python -c \"import app.db,app.config;print(app.config.get_settings().app_env)\""]

- [x] 2. Schema, invariants and test harness
  - [x] 2.1 Migration `0001`: tables, constraints, composite foreign keys, seeded currencies
    - Requirements: `R3.AC4`, `R3.AC5`, `R3.AC6`, `R6.AC5`, `R7.AC9`, `R7.AC10`, `R9.AC1`, `R9.AC2`, `R9.AC3`, `R10.AC3`, `R10.AC4`, `R12.AC1`, `C5`
    - Design: Data Models (table list)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/ledger/test_migrations.py -q"]
        covers: ["R14.AC2"]
  - [x] 2.2 Migration `0001`: guard triggers and the deferred balance check
    - Requirements: `R1.AC3`, `R3.AC1`, `R3.AC2`, `R3.AC3`, `R3.AC7`, `R3.AC8`, `R4.AC1`, `R4.AC2`, `R4.AC3`, `R4.AC4`, `R8.AC1`, `R9.AC4`, `R10.AC1`, `R10.AC2`
    - Design: Data Models (Trigger responsibilities); Error Handling
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/ledger/test_migrations.py -q"]
  - [x] 2.3 ORM models and a schema drift test against the migrated database
    - Requirements: `NFR1`, `NFR2`
    - Design: Data Models; Failure Modes (ORM drift)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/ledger/test_schema_drift.py -q"]
  - [x] 2.4 Test harness: per-worker Neon databases, factories, raw-SQL helpers, branch script
    - Requirements: `R15.AC1`, `R15.AC2`, `R15.AC3`, `R15.AC4`, `NFR7`
    - Design: Components And Interfaces (Test harness); Testing Strategy
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/ledger/test_harness.py -q"]
        covers: ["R15.AC1", "R15.AC2", "R15.AC3", "R15.AC4"]
      - command: ["sh", "-c", "test -x infra/scripts/neon-branch.sh"]

- [x] 3. Posting service
  - [x] 3.1 Currency precision and date-based exchange rate lookup
    - Requirements: `R7.AC2`, `R7.AC7`, `R7.AC8`
    - Design: Components And Interfaces (`app.ledger.rates`)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/ledger/test_rates.py -q"]
        covers: ["R7.AC2", "R7.AC7", "R7.AC8"]
  - [x] 3.2 Posting request validation (pure)
    - Requirements: `R2.AC4`, `R2.AC5`, `R2.AC6`, `R2.AC7`, `R2.AC8`, `R2.AC9`, `R12.AC2`
    - Design: Components And Interfaces (`app.ledger.posting`); Error Handling
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/unit/test_posting_rules.py -q -k validate"]
        covers: ["R2.AC4", "R2.AC5", "R2.AC6", "R2.AC7", "R2.AC8", "R2.AC9", "R12.AC2"]
  - [x] 3.3 Currency conversion and the rounding line (pure, property-tested)
    - Requirements: `R7.AC1`, `R7.AC3`, `R7.AC4`, `R7.AC5`, `R7.AC6`
    - Design: Overview (decision D8); Components And Interfaces (`convert_lines`)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/unit/test_posting_rules.py -q -k Convert"]
        covers: ["R7.AC1", "R7.AC3", "R7.AC5", "R7.AC6"]
  - [x] 3.4 Gapless numbering counter
    - Requirements: `R6.AC1`, `R6.AC2`, `R6.AC3`, `R6.AC4`
    - Design: Options Considered (Numbering sub-options); Components And Interfaces (`platform.sequence.api`)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/ledger/test_sequence.py -q"]
        covers: ["R6.AC2", "R6.AC4"]
  - [x] 3.5 `post()`: loaders, two-step draft to posted write, error translation
    - Requirements: `R1.AC1`, `R2.AC1`, `R2.AC2`, `R2.AC3`, `R2.AC10`, `R2.AC11`, `R2.AC12`, `R13.AC1`, `R13.AC2`
    - Design: Architecture (Posting sequence); Error Handling
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/ledger/test_posting.py -q"]
        covers: ["R1.AC1", "R2.AC1", "R2.AC2", "R2.AC3", "R2.AC10", "R2.AC11", "R2.AC12", "R6.AC1", "R6.AC3", "R13.AC1", "R13.AC2"]
  - [x] 3.6 `reverse()`: swapped lines, link to the original, refusal cases
    - Requirements: `R5.AC1`, `R5.AC2`, `R5.AC3`, `R5.AC4`, `R5.AC5`, `R5.AC6`, `R5.AC7`, `R5.AC8`
    - Design: Architecture (Reversal sequence)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/ledger/test_reversal.py -q"]
        covers: ["R5.AC1", "R5.AC2", "R5.AC3", "R5.AC4", "R5.AC5", "R5.AC6", "R5.AC7", "R5.AC8"]

- [x] 4. Invariant tests that bypass the application
  - [x] 4.1 Draft edits allowed, posted entries immutable, state transitions enforced
    - Requirements: `R1.AC2`, `R1.AC3`, `R4.AC1`, `R4.AC2`, `R4.AC3`, `R4.AC4`
    - Design: Data Models (Entry state machine); Testing Strategy (Invariants row)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/invariants/test_immutability.py -q"]
        covers: ["R1.AC2", "R1.AC3", "R4.AC1", "R4.AC2", "R4.AC3", "R4.AC4"]
  - [x] 4.2 Balance, rounding and line-level checks via raw SQL
    - Requirements: `R3.AC1`, `R3.AC2`, `R3.AC3`, `R3.AC4`, `R3.AC5`, `R3.AC6`, `R3.AC7`, `R3.AC8`, `R3.AC9`, `NFR1`
    - Design: Data Models (Trigger responsibilities); Error Handling
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/invariants/test_balance.py -q"]
        covers: ["R3.AC1", "R3.AC2", "R3.AC3", "R3.AC4", "R3.AC5", "R3.AC6", "R3.AC7", "R3.AC8", "R3.AC9"]
  - [x] 4.3 Company isolation, account safety, lock dates, numbering and source uniqueness
    - Requirements: `R6.AC5`, `R7.AC9`, `R7.AC10`, `R8.AC1`, `R9.AC1`, `R9.AC2`, `R9.AC3`, `R9.AC4`, `R10.AC1`, `R10.AC2`, `R10.AC3`, `R10.AC4`, `R12.AC1`
    - Design: Data Models (table rules); Error Handling
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/invariants/test_scoping.py -q"]
        covers: ["R6.AC5", "R7.AC9", "R7.AC10", "R8.AC1", "R9.AC1", "R9.AC2", "R9.AC3", "R9.AC4", "R10.AC1", "R10.AC2", "R10.AC3", "R10.AC4", "R12.AC1"]

- [x] 5. Concurrency proofs
  - [x] 5.1 Concurrent posting: gapless numbers, independent journals, rollback safety
    - Requirements: `R11.AC1`, `R11.AC2`, `R11.AC6`, `NFR3`, `NFR4`
    - Design: Architecture (step 4); Failure Modes (counter lock, deadlock order)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/concurrency/test_posting_races.py -q"]
        covers: ["R11.AC1", "R11.AC2", "R11.AC6"]
  - [x] 5.2 Line writes racing a posting, in both orders
    - Requirements: `R11.AC3`, `R11.AC4`
    - Design: Data Models (`journal_entry_line_guard` `FOR SHARE`); Failure Modes
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/concurrency/test_line_races.py -q"]
        covers: ["R11.AC3", "R11.AC4"]
  - [x] 5.3 Concurrent reversal of one entry, and posting racing a lock-date change
    - Requirements: `R11.AC5`, `R8.AC2`
    - Design: Architecture (Reversal sequence); Data Models (`journal_entry_guard` company `FOR SHARE`)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/concurrency/test_reversal_and_locks.py -q"]
        covers: ["R11.AC5", "R8.AC2"]

- [x] 6. Public surface
  - [x] 6.1 Health endpoint for both database states
    - Requirements: `R14.AC4`, `R14.AC5`
    - Design: Components And Interfaces (`app.main`)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/api/test_health.py -q"]
        covers: ["R14.AC4", "R14.AC5"]
  - [x] 6.2 Ledger public interface and a full gate run
    - Requirements: `NFR6`, `C3`
    - Design: Architecture (Module boundaries); Verification Plan
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run ruff check . && uv run lint-imports"]
      - command: ["sh", "-c", "cd backend && uv run pytest tests/unit tests/ledger tests/invariants tests/api -n 2 -q"]
      - command: ["sh", "-c", "cd backend && uv run pytest tests/concurrency -q"]

- [x] 7. Continuous integration and first push
  - [x] 7.1 GitHub Actions workflow for the backend gates
    - Requirements: `NFR6`, `R15.AC4`, `C7`
    - Design: Verification Plan; Testing Strategy (Architecture row)
    - Verification:
      - command: ["sh", "-c", "test -f .github/workflows/backend.yml && grep -q lint-imports .github/workflows/backend.yml && grep -q 'tests/unit' .github/workflows/backend.yml"]
        covers: ["R15.AC4"]
      - command: ["sh", "-c", "cd backend && uv run --with pyyaml python -c \"import yaml;yaml.safe_load(open('../.github/workflows/backend.yml'))\""]
  - [x] 7.2 Commit the spec, backend and infrastructure and push to GitHub
    - Requirements: `C6`
    - Design: Overview (spec-driven delivery)
    - Verification:
      - command: ["sh", "-c", "git status --porcelain | grep -q . && exit 1 || exit 0"]
      - command: ["sh", "-c", "git fetch origin && test \"$(git rev-parse HEAD)\" = \"$(git rev-parse origin/main)\""]
