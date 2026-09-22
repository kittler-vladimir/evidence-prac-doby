## Description
The dashboard's four one-click actions — Příchod, Odchod, Start (pohyb), Návrat z pohybu — always recorded `timezone.now()` with no way to correct it in the moment (e.g. clicking a few minutes late). This adds an optional, same-day time field to all four, hidden behind a "Změnit čas" toggle so the default one-click flow stays exactly as fast as today.

## Changes
- `timetracking/views.py`: new `_cas_z_pozadavku`/`_cas_nebo_chyba` helpers parse an optional `cas` (HH:MM) POST field into today's aware datetime, rejecting malformed input and future times; `_uloz_nebo_chybu` wraps `full_clean()`+`save()` with a Czech error message on failure (existing pattern from `leaves/views.py`). All 4 views (`clock_in`, `clock_out`, `start_pohyb`, `return_pohyb`) now use these instead of a hardcoded `timezone.now()`.
- **Validation gap closed**: `clock_in`/`clock_out` previously skipped `full_clean()` entirely (`WorkSession.objects.create()` / `.save()` directly), so overlap/ordering rules were never enforced on these paths — now they are, same as the rest of the app.
- `timetracking/models.py`: new `WorkSession.clean()` rule — a block's `konec` can't be set earlier than the `konec` of an already-finished `Pohyb` inside it (previously only held implicitly because `konec` was always "now").
- `templates/timetracking/dashboard.html`: each of the 4 forms gets a "Změnit čas" toggle revealing a `<input type="time" name="cas">`; vanilla JS, no new dependency. The field carries no value until explicitly revealed (and is cleared again on hide or bfcache page restore), so a plain click never silently submits a stale time.
- `_stejny_den_nebo_chyba` (views.py): Odchod/Návrat z pohybu reject an explicitly-entered `cas` that lands on a different calendar day than the record it's closing (the field has no date picker) — but only when the user actually typed a time; the default "now" path still works unchanged for a session/pohyb left open from a previous day (e.g. overnight shifts, `close_open_sessions` candidates).
- `timetracking/tests.py`: 22 new tests, including explicit regressions for two bugs a multi-round code review caught during implementation: (1) the hidden time input silently resubmitting a stale value even when untouched, and (2) an earlier fix's same-day guard accidentally blocking the plain one-click flow for overnight sessions.

## How to test
1. `python manage.py test` — 94/94 pass (CI runs it too)
2. Click "Změnit čas" next to any of the 4 quick actions, adjust the time, submit — the record uses the chosen time
3. Without touching "Změnit čas", all 4 actions behave exactly as before, including for a session/pohyb open from a previous day

## Issue
Closes #39
