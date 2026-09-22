## Description
Quick clock actions (Odchod / Start pohybu / Návrat) rejected a valid submission whenever the user changed the time to the same minute the record it follows was created in (e.g. clocking out in the same minute as clocking in). The `cas` field carries only `HH:MM`, while the default "now" path (`timezone.now()`) has microsecond precision — entering that same minute truncated to a value technically just before (or equal to) the fuller-precision reference, so `WorkSession.clean()`/`Pohyb.clean()` rejected it as out-of-order.

## Changes
- `timetracking/views.py`: `_cas_z_pozadavku`/`_cas_nebo_chyba` now accept an optional `navazuje_na` anchor. When the entered time lands in the same minute as its anchor but isn't strictly after it, it's nudged to `anchor + 1 microsecond` — staying valid without changing the minute the user entered.
- Added `_navazuje_na_konec_bloku(session)` (shared by `clock_out` and `start_pohyb`) returning the later of the block's start or the last closed pohyb's end, since either can be the relevant "must follow" anchor.
- `return_pohyb` anchors against the pohyb's own start.
- `timetracking/tests.py`: new `StejnaMinutaJakoNavazujiciZaznamTests` covering same-minute Odchod after Příchod (including the stricter case where both use an explicit `cas`), same-minute Start/Návrat, Odchod right after a same-minute Návrat, and a second pohyb starting in the same minute the first one ended — plus a regression test confirming a genuinely earlier time (5 minutes before) is still correctly rejected.

## How to test
1. `venv/Scripts/python.exe manage.py test timetracking` — 63/63 pass (full suite: 107/107)
2. On the dashboard: click "Změnit čas" for Příchod, submit immediately (same minute), then click "Změnit čas" for Odchod and submit immediately without changing the pre-filled time — should record successfully instead of showing "Konec musí být po začátku."

## Issue
Closes #43

🤖 Generated with [Claude Code](https://claude.com/claude-code)
