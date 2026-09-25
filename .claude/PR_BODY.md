## Description
Two bugs in `close_open_sessions`, found while reviewing the 2026-09-25 nightly run:

1. **Output showed UTC instead of local time.** `{session.zacatek:%d.%m.%Y %H:%M}` formatted the stored (UTC-aware) datetime directly, so the log reported "session od 24.09.2026 08:00" for a clock-in entered at 10:00 local — same bug class as #41. Data was never affected, only the printed time.
2. **Not idempotent.** Every run prepended another `[AUTOMATICKY]` note to each still-open row past the threshold, so an uncorrected record gained a new copy every night (and two per night if Celery Beat and the Windows Task Scheduler job both ran).

## Changes
- `timetracking/management/commands/close_open_sessions.py`: times formatted via `timezone.localtime()`; rows whose `poznamka` already starts with the command's marker are skipped and only listed as "stále čeká na opravu (označena dříve)", so the log keeps reminding about them without stacking notes. Marker texts pulled into module constants.
- `timetracking/tests.py`: new `CloseOpenSessionsOznaceniTests` — second run doesn't re-flag a session or a pohyb, keeps the user's own note, lists the earlier-flagged row as still waiting, and prints local rather than UTC time.
- `CLAUDE.md`: Scheduled maintenance section updated (idempotency, local time; running both schedulers no longer double-flags).

## How to test
1. `venv/Scripts/python.exe manage.py test` — 127/127 pass (was 123; +4 new)
2. Run `close_open_sessions` twice against a DB with an open session older than 14h — the note appears once, the second run lists it as still awaiting correction.

## Issue
Closes #55

🤖 Generated with [Claude Code](https://claude.com/claude-code)
