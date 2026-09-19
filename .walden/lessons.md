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

### 2026-09-18T09:27:10Z | identity-and-access | execute
- Trigger: CI failed three times on things the local run could not catch: Settings required database URLs so the no-database unit job could not import the app; two tests back-dated a timestamp past a CHECK constraint
- Lesson: Local runs always had backend/.env and pre-existing rows, so environment-free and constraint-edge paths were never exercised
- Guardrail: Before pushing: run the unit suite with an empty environment (env -i) and, when a test back-dates a timestamp, move every column the row's CHECK constraints compare

### 2026-09-18T11:53:56Z | chart-of-accounts | execute
- Trigger: Seven identity tests failed after adding permission codes only in Python; a freshly migrated database lacked them until the app started
- Lesson: Treated the start-up catalogue sync as sufficient, so 'migrate then run tests' produced a database that did not match the code
- Guardrail: When adding a permission or other reference data, seed it in the migration as well as the code sync, so a migrated database is complete on its own

### 2026-09-18T14:53:29Z | payments-and-reconciliation | design
- Trigger: Design claimed the ledger's line guard already allowed residual updates on posted lines; reading 0001 showed it refuses every update
- Lesson: A design that builds on another feature's trigger must quote the trigger's actual text, not its remembered intent
- Guardrail: Before designing on top of an existing database guard, read its function body in the migration and paste the relevant branch into the design

### 2026-09-18T15:50:52Z | payments-and-reconciliation | execute
- Trigger: A statement line reconciled, undone and reconciled again hit the core ledger's journal_entry_one_per_source unique index
- Lesson: An entry's source is a claim that the source document causes exactly one entry for ever; anything that can be undone and redone cannot use it
- Guardrail: Before setting source_type/source_id on a posted entry, check whether the feature allows the action to be undone and repeated; if it does, link from the source row instead

### 2026-09-18T18:22:37Z | financial-reports | requirements
- Trigger: The user asked whether there would be an interface to upload receipts, export CSV and see graphs; the brief named reporting and dashboards but never named the frontend, exports or document capture as deliverables
- Lesson: A phased brief can specify every engine and still omit the things a user reaches for first — the screen, getting data out, and getting data in from paper
- Guardrail: When a brief is organised by phase, check each phase names its user-facing deliverable and its data in/out paths, not only its engine; a phase whose only output is an API is not shippable to a person

### 2026-09-18T23:47:37Z | financial-reports | execute
- Trigger: The two-second performance bound failed at 2.25s; profiling showed five round trips to a hosted database, not a slow query
- Lesson: Against a hosted database the cost of a report is the number of queries, not the number of rows — and a design claiming 'one query' is worth checking against the code that implements it
- Guardrail: When a report or endpoint misses a latency budget, count its round trips before optimising SQL; fold conditional sums into one query rather than asking the database the same question with different dates

### 2026-09-19T07:53:58Z | web-shell-and-reports | execute
- Trigger: A task's verification command ran `npm run test`, whose script was bare `vitest`; the run never exited and the proof hung until it was killed.
- Lesson: A script named `test` that watches by default cannot be a verification command, and hangs CI rather than failing it. The default mode of a command is part of its contract.
- Guardrail: `npm run test` runs once and exits; watching is a separate `test:watch` script.

### 2026-09-19T07:53:58Z | web-shell-and-reports | execute
- Trigger: `--maxWorkers=2`, required by the project's memory rule, was rejected by vitest as conflicting with a minimum worker count taken from the core count.
- Lesson: A cap passed on the command line can conflict with a floor the tool derives from the machine. The cap belongs in the configuration, where it applies to every run, not only the ones that remember the flag.
- Guardrail: Worker limits live in `vite.config.ts` (`minWorkers: 1, maxWorkers: 2`), so no run can go uncapped.

### 2026-09-19T07:53:58Z | web-shell-and-reports | execute
- Trigger: axe-core found two accessibility violations on every report screen, both originating in Ant Design's own markup rather than in code written here.
- Lesson: A component library's markup is not automatically accessible. Disabling the rule that caught it would have hidden every future instance too; replacing the component fixed the class of defect.
- Guardrail: An axe rule is disabled only when the test environment cannot judge it (colour contrast in jsdom); a real violation is fixed at the call site.

### 2026-09-19T08:23:06Z | web-shell-and-reports | execute
- Trigger: A test suite piped to `tail` showed no output and sat at 0% CPU; it was called hung and killed three times. It had in fact reached 33% and was waiting on network round trips to Neon.
- Lesson: Silence is not evidence of a hang. A pipe to `tail` or `head` buffers everything until the process exits, and 0% CPU is what I/O-bound waiting looks like — both symptoms of a healthy slow run are identical to a stuck one.
- Guardrail: A long run writes to a file and is watched incrementally; before declaring a hang, confirm there is no progress in unbuffered output.

