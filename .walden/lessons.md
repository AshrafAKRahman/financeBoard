# Walden Lessons

Review this file before non-trivial work when the current request matches past mistakes, rejections, or validation failures.

## Lessons

<!-- Append entries with: walden lesson log --feature <name> --phase <phase> --trigger "..." --lesson "..." --guardrail "..." -->
### 2026-09-17T15:39:43Z | core-ledger | requirements
- Trigger: User said they had asked for Walden; implementation of the core ledger had already started without a spec
- Lesson: Jumped from architecture doc straight into code, skipping the Requirements -> Design -> Tasks gate
- Guardrail: Before writing production code for a new module, check for .walden/ or the walden skill and confirm the spec workflow; implement only from an approved tasks.md

