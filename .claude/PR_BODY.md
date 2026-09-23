## Description
For employees on a `PEVNA` (fixed working hours) contract type, `WorkdaySummary.prepocitej()` used to count the full duration of every closed `WorkSession`, ignoring any configured schedule. This changes the calculation so that only the portion of each session falling inside a day-of-week-matched `CasovyBlokUvazku` block counts as worked time — everything outside the block is dropped entirely (not work, not overtime, not shortfall). `PRUZNA` (flex-time) behavior is unchanged.

## Changes
- `accounts/models.py`: `CasovyBlokUvazku` gains 7 `BooleanField`s (`pondeli`…`nedele`) plus a `DNY_V_TYDNU` ordering constant; updated `help_text` on `TypUvazku.druh_pracovni_doby` to reflect that fixed-hours blocks are now used by the calculation.
- `accounts/admin.py`: `CasovyBlokUvazkuFormSet.clean()` now rejects a `PEVNA` block with no day checked (dead configuration).
- `timetracking/models.py`: `WorkdaySummary.prepocitej()` branches on `druh_pracovni_doby`. For `PEVNA`: `hrube_minuty` sums each session's overlap with blocks flagged for `datum.weekday()` (0 if no block matches that day), and `pohyby_minuty` is always 0 — movements never subtract worked time for fixed hours, regardless of `TypPohybu.zapocitava_se_do_pracovni_doby`. `PRUZNA` keeps its existing full-session-span + core-block movement logic unchanged.
- Tests: `accounts/tests.py` (admin validation), `timetracking/tests.py` (new `PevnaPracovniDobaVypocetTests` — same-minute-style capping, missing-block day, the real Mon–Thu/Fri two-block scenario, movements never subtracted).
- Operational step done in dev `db.sqlite3` (not via migration, per spec — this is an admin/business decision): the two existing "Pevná pracovní doba" blocks (07:30–16:15, 07:30–15:00) now have Mon–Thu / Fri checked respectively, so the 3 employees already on this contract type keep getting correct totals instead of dropping to 0.

## How to test
1. `venv/Scripts/python.exe manage.py test` — 117/117 pass
2. In Django admin, open "Typ úvazku" → "Pevná pracovní doba": the inline block table now shows day-of-week checkboxes; unchecking all days on a block and saving shows "Blok pevné pracovní doby musí mít zaškrtnutý aspoň jeden den."
3. Výkaz for an employee on that typ_uvazku shows worked time capped to the block (verified against real data: 3 sessions on 2026-09-22 summed to 394 raw minutes, capped/broken down to 364 worked minutes after the 30min mandatory break).

## Issue
Closes #47

🤖 Generated with [Claude Code](https://claude.com/claude-code)
