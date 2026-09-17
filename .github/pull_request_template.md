## Summary

- [ ] Describe the change

## Walden

- Feature:
- Phase:
- Status:

## Verification

- [ ] `cd backend && uv run ruff check . && uv run lint-imports`
- [ ] `cd backend && uv run pytest tests/unit -n 2`
- [ ] `cd backend && uv run pytest tests/ledger tests/invariants tests/api -n 2` (needs the Neon `test` branch)
- [ ] `cd backend && uv run pytest tests/concurrency`

## Notes

- [ ] Call out risks or follow-up work
