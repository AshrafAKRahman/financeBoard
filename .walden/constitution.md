# Project Constitution

This file captures stable project-wide context that applies across all features. It is optional and does not participate in the approval workflow.

## Project Summary

A finance-centric ERP for companies in **Saudi Arabia**, functionally inspired by Odoo
(Accounting, Invoicing, Inventory, POS, Payroll, Studio) but built from scratch on
double-entry accounting. The **ledger is the only source of truth**: every financial
document posts exactly one journal entry, and every report reads posted journal entries
only. Delivered in four phases; Phase 1 is the core finance MVP (ledger, chart of accounts,
multi-currency, invoicing, VAT + ZATCA e-invoicing, payments and reconciliation, reports,
multi-company, CSV export, the Phase 1 screens, and document capture).

Sources of truth: `finance-erp-mvp-prompt.md` (brief) and `docs/architecture.md`
(architecture and decisions D1–D15).

## Tech Stack

- Backend: Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2.0 (sync sessions, psycopg 3), Alembic
- Database: PostgreSQL 18 on **Neon** (project `round-violet-29046436`, us-east-2) (pooled endpoint for API, direct endpoint for
  migrations, workers and concurrency tests); production later on Alibaba Cloud ApsaraDB
- Jobs: Procrastinate (Postgres-backed) via a transactional outbox
- Frontend: React + TypeScript + Vite, Ant Design (RTL), TanStack Query, react-i18next
- Hosting: Railway now (demo/test data only), Alibaba Cloud Saudi region for production
- Tooling: uv, ruff, import-linter, pytest + pytest-xdist + Hypothesis, Vitest, Playwright

## Conventions

- Modular monolith: `backend/app/<module>/`; other modules import only `<module>/api.py`.
  Layers enforced by import-linter (`app.main` → feature modules → `app.platform` → `app.shared`).
- Only `ledger` posting code creates journal entries; posting services never commit —
  callers own the transaction.
- Schema is defined by hand-written Alembic migrations (raw SQL, including triggers);
  ORM models must match them.
- Business rule errors use stable codes `<module>.<code>`; database triggers raise
  messages in the same `<module>.<code>: detail` shape.
- IDs are UUID v7. Money is `Decimal` / `NUMERIC(20,6)`, rounded half away from zero to
  the currency's decimal places. Never floats.
- Every business table carries `company_id`; cross-company references are blocked with
  composite foreign keys `(x_id, company_id)`.
- Files and identifiers in English; user-facing text bilingual (Arabic/English).

## Sanity Checks

```bash
cd backend
uv run ruff check .
uv run lint-imports
uv run pytest tests/unit -n 2
# Database tests (needs a Neon branch; never a local Postgres):
TEST_DATABASE_URL=<neon direct url> uv run pytest -n 2
```

## Key Files

- `finance-erp-mvp-prompt.md` — product brief and phase plan
- `docs/architecture.md` — architecture, data model, decisions D1–D15
- `backend/pyproject.toml` — dependencies, pytest, ruff, import-linter contracts
- `backend/migrations/versions/` — schema and invariant triggers
- `backend/app/db.py` — engines, Neon pooled vs direct, unit of work
- `backend/app/ledger/api.py` — public ledger interface

## Hard Rules

- Invariants are enforced in PostgreSQL, not only in application code: posted entries
  balance in company currency (and in transaction currency when single-currency), posted
  entries are immutable, corrections only via reversal entries, no posting on or before
  the company lock date.
- No report reads anything except posted journal entries.
- **Extracted data is never posted.** Reading a receipt's QR code or running a document
  through a vision model produces a draft for a person to confirm. Nothing reaches the
  ledger because a model was confident (D14).
- **Whoever may read a list may export it.** Exports add no permission of their own, obey
  the same company scoping and filters as the screen they came from, and are recorded in
  the audit log (D13).
- No floats for money.
- Statutory rates (VAT, withholding, GOSI, EOSB) are effective-dated data, never constants.
- ZATCA-issued invoices are immutable once cleared/reported; corrections via credit/debit notes.
- Nothing database-related runs on the developer's machine; use Neon branches.
- Railway and Neon hold demo/test data only — no real customer, employee or payroll data
  and no production ZATCA credentials until the Alibaba Cloud (Saudi region) move.
- Local test runs are memory-capped: `pytest -n 2`, `vitest --maxWorkers=2`.
- Ask before adding dependencies beyond those approved in `docs/architecture.md` §2.
- Every feature (backend, frontend, infrastructure) goes through the Walden gates:
  requirements → design → tasks, each approved before the next; code only from an approved,
  non-stale `tasks.md`. Iterating on a design or on an already-built feature means amending
  the earliest affected document, running `walden reconcile <feature>`, re-approving from
  that phase forward, and checking the amendment against the other approved specs and the
  shipped code for conflicts before implementing. (Mirrors the global rule in
  `~/.claude/CLAUDE.md`.)
