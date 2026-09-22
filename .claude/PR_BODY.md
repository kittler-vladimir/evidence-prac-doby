## Description
`WorkSessionOpravitForm`, `PohybRucneForm`, and `WorkSession`/`Pohyb.__str__` formatted stored UTC-aware datetimes directly with `.strftime()`, without converting to the active `Europe/Prague` timezone first. This made correction/backfill forms pre-fill with a time shifted by the UTC offset (1–2h) — and if a user resubmitted such a form without touching the time fields, the displayed-but-wrong value got re-parsed as local time, silently shifting the stored time in the database.

## Changes
- `timetracking/forms.py`: `WorkSessionOpravitForm.__init__` and `PohybRucneForm.__init__` now wrap `instance.zacatek`/`instance.konec` with `timezone.localtime()` before `.strftime()`
- `timetracking/models.py`: `WorkSession.__str__` and `Pohyb.__str__` do the same, fixing admin lists, FK dropdowns, and any message referencing a session/pohyb
- `timetracking/tests.py`: new `MistniCasOpravFormularuAStrTests` — form pre-fill in both CET and CEST, `__str__` output in both offsets, and a round-trip regression test proving an unchanged resubmission no longer drifts the stored UTC time

Repo-wide grep confirmed no other `.strftime()`/`.isoformat()` call sites need the same fix — templates and Django admin already localize automatically, and the dashboard quick-actions `cas` override already used `timezone.make_aware`/`timezone.localdate()` correctly.

## How to test
1. `venv/Scripts/python.exe manage.py test timetracking` — 56/56 pass (full suite: 100/100)
2. Open "Opravit záznam" on an existing work session and confirm the shown time matches the dashboard/Výkaz, not a time shifted by 1–2 hours

## Issue
Closes #41

🤖 Generated with [Claude Code](https://claude.com/claude-code)
