# Walden Lessons

Review this file before non-trivial work when the current request matches past mistakes, rejections, or validation failures.

## Lessons

<!-- Append entries with: walden lesson log --feature <name> --phase <phase> --trigger "..." --lesson "..." --guardrail "..." -->
### 2026-09-17T15:39:43Z | core-ledger | requirements
- Trigger: User said they had asked for Walden; implementation of the core ledger had already started without a spec
- Lesson: Jumped from architecture doc straight into code, skipping the Requirements -> Design -> Tasks gate
- Guardrail: Before writing production code for a new module, check for .walden/ or the walden skill and confirm the spec workflow; implement only from an approved tasks.md

### 2026-09-17T20:12:58Z | core-ledger | execute
- Trigger: Three test-authoring bugs surfaced during execution: SET lock_timeout before connection.begin() raised InvalidRequestError, 'from app.main import app' shadowed the app package, and a downgrade test asserted zero tables while alembic_version remains
- Lesson: Harness and test scaffolding failed for mechanical reasons unrelated to the ledger logic under test
- Guardrail: In SQLAlchemy tests: call connection.begin() before any statement and use SET LOCAL; never bind the name 'app' when importing from the app package; expect alembic_version to survive downgrade

### 2026-09-17T20:12:58Z | core-ledger | execute
- Trigger: walden repo init shipped a CI workflow calling scripts/validate_walden_spec.py and a PR template running 'go test ./...', neither of which exists in this Python project
- Lesson: Scaffolded repo files were taken as correct and would have failed CI on the first PR touching .walden/**
- Guardrail: After any tool scaffolds CI or templates, read every generated file and reconcile it with the project's real stack before the first push

