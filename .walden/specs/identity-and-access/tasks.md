---
status: approved
approved_at: 2026-09-18T07:32:42Z
last_modified: 2026-09-18T09:15:38Z
source_design_approved_at: 2026-09-18T07:18:17Z
---

# Implementation Plan

Build order: primitives that need no database, then the schema, then services, then the HTTP
layer on top. Nothing is exposed over HTTP until the route check and the CSRF middleware are
in place, so there is never a commit where an endpoint is reachable unprotected.

Verification commands run from the repository root and use `sh -c "cd backend && …"`.
Database tests use the Neon `test` branch through `TEST_DATABASE_URL`.

- [x] 1. Primitives
  - [x] 1.1 Argon2id password hashing behind one seam
    - Requirements: `R1.AC5`, `R2.AC1`, `R2.AC4`, `R2.AC5`, `C1`
    - Design: Components And Interfaces (`platform.identity.passwords`); Security Considerations
    - Verification:
      - command: ["sh", "-c", "cd backend && uv add argon2-cffi && uv run pytest tests/unit/test_passwords.py -q"]
        covers: ["R1.AC5", "R2.AC1", "R2.AC4", "R2.AC5"]
  - [x] 1.2 Opaque token minting and hashing
    - Requirements: `R4.AC2`, `R11.AC4`
    - Design: Components And Interfaces (`platform.identity.tokens`)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/unit/test_tokens.py -q"]
        covers: ["R4.AC2", "R11.AC4"]
  - [x] 1.3 Mailer interface with SMTP, log and recording backends, bilingual invitation
    - Requirements: `R11.AC11`, `R11.AC14`, `R11.AC15`, `C3`
    - Design: Components And Interfaces (`platform.mail`)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/unit/test_mail.py -q"]
        covers: ["R11.AC11", "R11.AC14", "R11.AC15"]
  - [x] 1.4 Problem-details error responses for domain errors
    - Requirements: `R2.AC3`
    - Design: Error Handling
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/unit/test_problem_details.py -q"]
        covers: ["R2.AC3"]

- [x] 2. Schema
  - [x] 2.1 Migration `0002`: users, sessions, invitations, roles, grants, attempts, audit
    - Requirements: `R1.AC2`, `R1.AC3`, `R5.AC1`, `R11.AC8`
    - Design: Data Models (table list)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/identity/test_migration_identity.py -q"]
        covers: ["R1.AC2", "R1.AC3", "R5.AC1", "R11.AC8"]
  - [x] 2.2 Append-only audit trigger, permission catalogue seed, Administrator role
    - Requirements: `R5.AC8`, `R8.AC3`
    - Design: Data Models (`audit_log`); Options Considered (permission catalogue)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/identity/test_migration_identity.py -q -k 'audit or catalogue or administrator'"]
        covers: ["R5.AC8", "R8.AC3"]
  - [x] 2.3 ORM models for the new tables, kept honest by the existing drift test
    - Requirements: `NFR3`, `NFR5`
    - Design: Data Models; Failure Modes
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/ledger/test_schema_drift.py -q"]

- [x] 3. Identity services
  - [x] 3.1 Users and invitations: invite, accept, resend, revoke
    - Requirements: `R1.AC1`, `R1.AC4`, `R1.AC10`, `R11.AC1`, `R11.AC2`, `R11.AC5`, `R11.AC6`, `R11.AC7`, `R11.AC8`, `R11.AC9`, `R11.AC10`, `R11.AC12`, `R11.AC13`
    - Design: Architecture (Invitation path); Components And Interfaces (`platform.identity`)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/identity/test_users_invitations.py -q"]
        covers: ["R1.AC1", "R1.AC4", "R1.AC10", "R11.AC1", "R11.AC2", "R11.AC5", "R11.AC6", "R11.AC7", "R11.AC8", "R11.AC9", "R11.AC10", "R11.AC12", "R11.AC13"]
  - [x] 3.2 Authentication with lockout and constant work for unknown addresses
    - Requirements: `R3.AC3`, `R3.AC4`, `R3.AC5`, `R3.AC6`, `R3.AC8`, `R3.AC9`
    - Design: Overview; Options Considered (lockout state); Security Considerations
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/identity/test_authenticate.py -q"]
        covers: ["R3.AC3", "R3.AC4", "R3.AC5", "R3.AC6", "R3.AC8", "R3.AC9"]
  - [x] 3.3 Sessions: create, load, expire, revoke; password change and deactivation
    - Requirements: `R1.AC6`, `R1.AC7`, `R1.AC8`, `R1.AC9`, `R4.AC1`, `R4.AC4`, `R4.AC5`, `R4.AC6`, `R4.AC7`, `R4.AC8`
    - Design: Data Models (session lifetimes, user state machine)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/identity/test_sessions.py -q"]
        covers: ["R1.AC6", "R1.AC7", "R1.AC8", "R1.AC9", "R4.AC1", "R4.AC4", "R4.AC5", "R4.AC6", "R4.AC7", "R4.AC8"]
  - [x] 3.4 Audit writer with a secret deny-list
    - Requirements: `R8.AC1`, `R8.AC2`, `R8.AC4`
    - Design: Components And Interfaces (`platform.audit`)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/identity/test_audit.py -q"]
        covers: ["R8.AC1", "R8.AC2", "R8.AC4"]

- [x] 4. Access control
  - [x] 4.1 Permission catalogue, roles, grants and the authorize check
    - Requirements: `R5.AC2`, `R5.AC3`, `R5.AC4`, `R5.AC5`, `R5.AC6`, `R5.AC7`, `R6.AC5`
    - Design: Components And Interfaces (`platform.access`)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/identity/test_access.py tests/unit/test_authorize.py -q"]
        covers: ["R5.AC2", "R5.AC3", "R5.AC4", "R5.AC5", "R5.AC6", "R5.AC7", "R6.AC5"]
  - [x] 4.2 Company scoping: grants decide reachability, unknown and forbidden look alike
    - Requirements: `R6.AC1`, `R6.AC2`, `R6.AC3`, `R6.AC4`
    - Design: Architecture (Request path step 2); Security Considerations (enumeration)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/identity/test_scoping.py -q"]
        covers: ["R6.AC1", "R6.AC2", "R6.AC3", "R6.AC4"]

- [x] 5. HTTP layer
  - [x] 5.1 Request dependencies: current user, current company, required permission
    - Requirements: `R4.AC3`, `R7.AC3`, `R7.AC4`
    - Design: Architecture (Request path); Components And Interfaces (HTTP layer)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/api/test_dependencies.py -q"]
        covers: ["R4.AC3", "R7.AC3", "R7.AC4"]
  - [x] 5.2 Start-up check that every route declares a permission or is public
    - Requirements: `R7.AC1`, `R7.AC2`, `R7.AC5`, `NFR2`
    - Design: Components And Interfaces (Start-up route check)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/api/test_route_protection.py -q"]
        covers: ["R7.AC1", "R7.AC2", "R7.AC5"]
  - [x] 5.3 CSRF middleware: accepted origins, audited rejections, safe methods untouched
    - Requirements: `R12.AC1`, `R12.AC2`, `R12.AC3`, `R12.AC4`, `R12.AC5`, `R12.AC6`, `R12.AC7`, `R12.AC8`, `R12.AC9`
    - Design: Security Considerations (CSRF); Failure Modes
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/api/test_csrf.py -q"]
        covers: ["R12.AC1", "R12.AC2", "R12.AC3", "R12.AC4", "R12.AC5", "R12.AC6", "R12.AC7", "R12.AC8", "R12.AC9"]
  - [x] 5.4 Auth endpoints: login, logout, profile, password change
    - Requirements: `R2.AC2`, `R3.AC1`, `R3.AC2`, `R3.AC7`, `R10.AC1`, `R10.AC2`, `R10.AC3`
    - Design: Components And Interfaces (HTTP layer endpoint table)
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/api/test_auth.py -q"]
        covers: ["R2.AC2", "R3.AC1", "R3.AC2", "R3.AC7", "R10.AC1", "R10.AC2", "R10.AC3"]
  - [x] 5.5 Invitation endpoints, including acceptance that logs the person in
    - Requirements: `R11.AC3`
    - Design: Architecture (Invitation path); HTTP layer endpoint table
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/api/test_invitations.py -q"]
        covers: ["R11.AC3"]
  - [x] 5.6 Administration endpoints: users, role grants, session revocation, audit log
    - Requirements: `R8.AC5`
    - Design: HTTP layer endpoint table
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/api/test_admin.py -q"]
        covers: ["R8.AC5"]

- [x] 6. Bootstrap and gates
  - [x] 6.1 `bootstrap-admin` command for a fresh system
    - Requirements: `R9.AC1`, `R9.AC2`, `R9.AC3`, `R9.AC4`
    - Design: Components And Interfaces (Bootstrap command); Verification Plan
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/identity/test_bootstrap.py -q"]
        covers: ["R9.AC1", "R9.AC2", "R9.AC3", "R9.AC4"]
  - [x] 6.2 Hardening tests and a full gate run
    - Requirements: `NFR1`, `NFR2`, `NFR5`, `NFR6`
    - Design: Testing Strategy; Verification Plan
    - Verification:
      - command: ["sh", "-c", "cd backend && uv run pytest tests/api/test_hardening.py -q"]
      - command: ["sh", "-c", "cd backend && uv run ruff check . && uv run lint-imports"]
      - command: ["sh", "-c", "cd backend && uv run pytest tests/unit tests/ledger tests/identity tests/invariants tests/api -n 2 -q"]
      - command: ["sh", "-c", "cd backend && uv run pytest tests/concurrency -q"]
