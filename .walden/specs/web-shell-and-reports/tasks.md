---
status: approved
approved_at: 2026-09-19T07:07:19Z
last_modified: 2026-09-19T09:16:54Z
source_design_approved_at: 2026-09-19T07:05:54Z
---

# Implementation Plan

Order: the project and the generated client first, because nothing can be typed without them;
then the pure parts (money, periods, charts) which need no browser; then the shell that owns
sign-in and language; then the seven screens; then accessibility and the budget; then CI.

Frontend commands run from the repository root as `sh -c "cd frontend && …"`. Test runs are
memory-capped per the project's rule (`vitest --maxWorkers=2`).

- [x] 1. The project and its client
  - [x] 1.1 Scaffold `frontend/`: Vite, React, TypeScript strict, Ant Design, TanStack Query, the `/api` dev proxy
    - Requirements: `R10.AC3`, `NFR4`, `C1`, `C2`, `C3`
    - Design: Serving one origin; Architecture
    - Verification:
      - command: ["sh", "-c", "cd frontend && npm ci && npx tsc --noEmit"]
        covers: ["NFR4"]
      - command: ["sh", "-c", "cd frontend && npm run build"]
        covers: ["C1"]
  - [x] 1.2 Generate the API client from the API's own schema, and fail the build on drift
    - Requirements: `R10.AC1`, `R10.AC2`
    - Design: Components And Interfaces (`api/`)
    - Verification:
      - command: ["sh", "-c", "cd frontend && npm run check:client"]
        covers: ["R10.AC1", "R10.AC2"]
  - [x] 1.3 The fetch client: same-origin, typed errors, 401 becomes a sign-out
    - Requirements: `R1.AC6`, `R9.AC1`, `R9.AC2`, `R9.AC3`, `R9.AC4`, `R9.AC5`, `R9.AC6`, `R10.AC3`, `R10.AC4`, `R10.AC5`
    - Design: Components And Interfaces (`api/`); Error Handling
    - Verification:
      - command: ["sh", "-c", "cd frontend && npm run test -- --maxWorkers=2 src/api"]
        covers: ["R1.AC6", "R9.AC1", "R9.AC2", "R9.AC3", "R9.AC4", "R9.AC5", "R10.AC3", "R10.AC4", "R10.AC5"]

- [x] 2. The pure parts
  - [x] 2.1 Money and dates: strings in, strings out, never a float
    - Requirements: `R4.AC1`, `R4.AC2`, `R4.AC3`, `R4.AC4`, `R4.AC5`, `R4.AC6`, `R4.AC7`, `R10.AC6`
    - Design: Components And Interfaces (`money/`); Sub-decisions (money formatting)
    - Verification:
      - command: ["sh", "-c", "cd frontend && npm run test -- --maxWorkers=2 src/money"]
        covers: ["R4.AC1", "R4.AC2", "R4.AC3", "R4.AC4", "R4.AC5", "R4.AC6", "R4.AC7", "R10.AC6"]
  - [x] 2.2 Periods: the URL is the state
    - Requirements: `R6.AC1`, `R6.AC2`, `R6.AC3`, `R6.AC4`, `R6.AC5`, `R2.AC5`
    - Design: Components And Interfaces (`periods/`)
    - Verification:
      - command: ["sh", "-c", "cd frontend && npm run test -- --maxWorkers=2 src/periods"]
        covers: ["R6.AC1", "R6.AC2", "R6.AC3", "R6.AC4", "R6.AC5", "R2.AC5"]
  - [x] 2.3 Two charts, drawn to the scale, with a text alternative
    - Requirements: `R7.AC1`, `R7.AC2`, `R7.AC3`, `R7.AC4`, `R7.AC5`, `R7.AC6`, `R11.AC4`
    - Design: Components And Interfaces (`charts/`); Sub-decisions (charts)
    - Verification:
      - command: ["sh", "-c", "cd frontend && npm run test -- --maxWorkers=2 src/charts"]
        covers: ["R7.AC1", "R7.AC2", "R7.AC3", "R7.AC4", "R7.AC5", "R7.AC6", "R11.AC4"]

- [x] 3. The shell
  - [x] 3.1 Signing in and out, and where a person was going
    - Requirements: `R1.AC1`, `R1.AC2`, `R1.AC3`, `R1.AC4`, `R1.AC5`, `R1.AC7`, `R1.AC8`, `R1.AC9`
    - Design: Components And Interfaces (`app/`, `shell/`)
    - Verification:
      - command: ["sh", "-c", "cd frontend && npm run test -- --maxWorkers=2 src/shell/signin"]
        covers: ["R1.AC1", "R1.AC2", "R1.AC3", "R1.AC4", "R1.AC5", "R1.AC7", "R1.AC8", "R1.AC9"]
  - [x] 3.2 The frame: navigation, the company being viewed, switching company
    - Requirements: `R2.AC1`, `R2.AC2`, `R2.AC3`, `R2.AC4`, `R2.AC6`, `R2.AC7`
    - Design: Components And Interfaces (`shell/`)
    - Verification:
      - command: ["sh", "-c", "cd frontend && npm run test -- --maxWorkers=2 src/shell/app-shell"]
        covers: ["R2.AC1", "R2.AC2", "R2.AC3", "R2.AC4", "R2.AC6", "R2.AC7"]
  - [x] 3.3 Arabic and right-to-left, with the figures still reading left to right
    - Requirements: `R3.AC1`, `R3.AC2`, `R3.AC3`, `R3.AC4`, `R3.AC5`, `R3.AC6`, `R3.AC7`, `R3.AC8`
    - Design: Components And Interfaces (`shell/LanguageSwitcher`); Failure Modes (mirrored figures)
    - Verification:
      - command: ["sh", "-c", "cd frontend && npm run test -- --maxWorkers=2 src/i18n"]
        covers: ["R3.AC1", "R3.AC2", "R3.AC6", "R3.AC7", "R3.AC8"]
      - command: ["sh", "-c", "cd frontend && npm run test -- --maxWorkers=2 src/shell/direction"]
        covers: ["R3.AC3", "R3.AC4", "R3.AC5"]

- [x] 4. The seven screens
  - [x] 4.1 The shared pieces: header, amount cell, collapsible hierarchy
    - Requirements: `R5.AC2`, `R5.AC3`, `R5.AC4`, `R5.AC8`, `R5.AC9`
    - Design: Components And Interfaces (`reports/`)
    - Verification:
      - command: ["sh", "-c", "cd frontend && npm run test -- --maxWorkers=2 src/reports/shared"]
        covers: ["R5.AC2", "R5.AC3", "R5.AC4", "R5.AC8", "R5.AC9"]
  - [x] 4.2 Trial balance, profit and loss, balance sheet
    - Requirements: `R5.AC1`, `R5.AC5`, `R5.AC6`, `R6.AC6`, `R7.AC1`
    - Design: Components And Interfaces (`reports/`)
    - Verification:
      - command: ["sh", "-c", "cd frontend && npm run test -- --maxWorkers=2 src/reports/statements"]
        covers: ["R5.AC1", "R5.AC5", "R5.AC6", "R6.AC6", "R7.AC1"]
  - [x] 4.3 Cash flow, aged receivables and payables, the VAT return
    - Requirements: `R5.AC1`, `R5.AC7`, `R7.AC2`
    - Design: Components And Interfaces (`reports/`)
    - Verification:
      - command: ["sh", "-c", "cd frontend && npm run test -- --maxWorkers=2 src/reports/others"]
        covers: ["R5.AC1", "R5.AC7", "R7.AC2"]
  - [x] 4.4 Clicking a figure through to the entries behind it
    - Requirements: `R8.AC1`, `R8.AC2`, `R8.AC3`, `R8.AC4`, `R8.AC5`
    - Design: Components And Interfaces (`reports/AccountDetail`)
    - Verification:
      - command: ["sh", "-c", "cd frontend && npm run test -- --maxWorkers=2 src/reports/detail"]
        covers: ["R8.AC1", "R8.AC2", "R8.AC3", "R8.AC4", "R8.AC5"]

- [x] 5. Reachable, readable, and inside its budget
  - [x] 5.1 Keyboard and assistive technology on every screen
    - Requirements: `R11.AC1`, `R11.AC2`, `R11.AC3`, `R11.AC5`, `NFR3`, `NFR5`
    - Design: Testing Strategy (Accessibility)
    - Verification:
      - command: ["sh", "-c", "cd frontend && npm run test -- --maxWorkers=2 src/a11y"]
        covers: ["R11.AC1", "R11.AC2", "R11.AC3", "R11.AC5", "NFR3", "NFR5"]
  - [x] 5.2 Nothing financial in storage, and the bundle inside 400 KB
    - Requirements: `NFR1`, `NFR2`, `NFR6`
    - Design: Failure Modes (Ant Design's weight); Security Considerations
    - Verification:
      - command: ["sh", "-c", "cd frontend && npm run test -- --maxWorkers=2 src/storage"]
        covers: ["NFR6"]
      - command: ["sh", "-c", "cd frontend && npm run build && npm run check:size"]
        covers: ["NFR1", "NFR2"]

- [x] 6. One origin, and the gate
  - [x] 6.1 The API serves the built application in production
    - Requirements: `R10.AC3`, `C3`, `C4`
    - Design: Serving one origin; Backend: two small additions
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/api/test_spa.py -q"]
        covers: ["R10.AC3", "C3", "C4"]
  - [x] 6.2 A frontend job in CI, beside the backend's
    - Requirements: `C6`, `C7`, `NFR4`
    - Design: Verification Plan
    - Verification:
      - command: ["sh", "-c", "cd frontend && npx tsc --noEmit && npm run lint && npm run test -- --maxWorkers=2 --run && npm run check:client && npm run build && npm run check:size"]
        covers: ["C6", "C7", "NFR4"]

- [x] 7. Delivery
  - [x] 7.1 Full gate: both sides, format, lint, types, tests
    - Requirements: `C1`, `C2`, `C5`, `C7`
    - Design: Verification Plan
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run ruff format --check . && uv run ruff check . && uv run lint-imports"]
        covers: ["C7"]
      - command: ["sh", "-c", "cd frontend && npx tsc --noEmit && npm run lint && npm run test -- --maxWorkers=2 --run"]
        covers: ["C1", "C6"]
      - command: ["sh", "-c", "cd backend && uv run pytest tests/api tests/unit -q -n 2"]
        covers: ["C5"]
  - [x] 7.2 Push, green CI, merge
    - Requirements: `C7`
    - Design: Verification Plan
    - Verification:
      - command: ["sh", "-c", "git status --porcelain -- backend frontend .github | grep -q . && exit 1 || exit 0"]
      - command: ["sh", "-c", "git fetch origin && test \"$(git rev-parse HEAD)\" = \"$(git rev-parse origin/main)\""]
