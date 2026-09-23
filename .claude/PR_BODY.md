## Description
`close_open_sessions` has never actually run automatically, despite `CLAUDE.md` and the command's own docstring describing it as "intended to run nightly via Celery Beat" — the project had no `tasks.py` anywhere and zero `PeriodicTask` rows in the database. This wires it up: a Celery task calls the command, registered as a nightly `PeriodicTask` via an idempotent data migration, so it activates automatically once a Celery worker + beat process is deployed (not yet the case — dev only for now).

## Changes
- `timetracking/tasks.py`: new `@shared_task close_open_sessions()` that calls the existing management command via `call_command`.
- `timetracking/migrations/0006_schedule_close_open_sessions.py`: data migration creating a `django_celery_beat` `CrontabSchedule` (02:00 Europe/Prague) and `PeriodicTask` pointing at the new task, via `get_or_create` (safe to re-run), with a matching reverse operation.
- `timetracking/management/commands/close_open_sessions.py`: docstring corrected (was hinting "23:59", now matches the actual 02:00 schedule). Also fixes a **pre-existing bug**: the `⚠` emoji in the command's stdout output raised `UnicodeEncodeError` on a Windows console using cp1250 — this had never been caught because no test previously exercised the command with an actual stale session to flag. Replaced with a plain `!`.
- `CLAUDE.md`: "Scheduled maintenance" section updated to describe the actual registration instead of just an intention.
- `timetracking/tests.py`: 3 new tests — the `PeriodicTask` exists post-migration with the right schedule, the task flags a stale open session, and it leaves a fresh one alone.

## How to test
1. `venv/Scripts/python.exe manage.py test` — 120/120 pass
2. `venv/Scripts/python.exe manage.py shell -c "from timetracking.tasks import close_open_sessions; close_open_sessions()"` — runs cleanly against the dev DB, no crash

## Issue
Closes #49

🤖 Generated with [Claude Code](https://claude.com/claude-code)
