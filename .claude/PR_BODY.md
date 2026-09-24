## Description
The user flagged that CLAUDE.md's wording for `obnov_rocni_naroky`'s handling of indispoziční volno ("the current value with no carry-over") was ambiguous — it could be misread as "the balance stays unchanged from last year" rather than what actually happens.

## Investigation
`leaves/management/commands/obnov_rocni_naroky.py` already behaves correctly: `narok_hodin = narok_iv` (the current `NarokIndispozicnihoVolna` entitlement), with no leftover from the previous year carried over at all — unlike dovolená, which does carry the leftover forward. This was confirmed by writing and running new tests (previously `obnov_rocni_naroky` had zero test coverage). No code bug — the fix is a documentation clarification plus the missing regression tests.

## Changes
- `CLAUDE.md`: reworded the Business Rules table entry to be unambiguous.
- `leaves/tests.py`: new `ObnovRocniNarokyTests` (3 tests) — IV resets to the current entitlement regardless of last year's leftover, dovolená carries the leftover forward and adds the new entitlement, and the command is idempotent (skips an already-existing `ZustatekStavu` row).

## How to test
`venv/Scripts/python.exe manage.py test` — 123/123 pass (was 120; +3 new)

## Issue
Closes #53

🤖 Generated with [Claude Code](https://claude.com/claude-code)
