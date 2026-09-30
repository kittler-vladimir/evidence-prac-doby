## Description
For employees on fixed working hours (`PEVNA`), the nightly `close_open_sessions` run now closes a forgotten movement (`Pohyb`) of a configured type — together with its work block — at the end of that weekday's working block (16:15 Mon–Thu, 15:00 Fri in current data), instead of only flagging it for manual correction. Which movement types this applies to is a new admin checkbox on `TypPohybu`.

## Changes
- `timetracking/models.py`, `admin.py`: new `TypPohybu.ukoncit_na_konec_bloku` flag ("Ukončit na konci pracovního bloku"), shown in the admin list.
- `timetracking/migrations/0007_typpohybu_ukoncit_na_konec_bloku.py`: adds the field and turns it on for `SluzCesta` and `Lekar`.
- `timetracking/opravy.py`: `ZNACKA_AUTO_UKONCENI` audit note, `konec_bloku_pevne_doby()` (end of the last PEVNA block for a weekday) and `ukonci_na_konec_bloku()` (closes pohyb then session atomically with `full_clean()`, strips earlier `[AUTOMATICKY]` flags, falls back on any validation error).
- `close_open_sessions`: new auto-close pass before flagging, driven by "started before today's local midnight" rather than the `--hodiny` threshold; lists auto-closed rows with `+`.
- Tests: 11 new cases (Mon–Thu 16:15, Fri 15:00, summary recompute, idempotency, earlier flag stripped, fallbacks: flag off, PRUZNA, weekend, pohyb after block end, session from another day, today's pohyb).
- `CLAUDE.md`, `README.md`: document the rule.

## How to test
1. As a PEVNA employee, leave a "Lékař" movement open on a Thursday.
2. Run `python manage.py close_open_sessions` the next day.
3. Both the movement and the work block end at Thursday 16:15 (Friday: 15:00) with the `[AUTOMATICKY] Ukončeno automaticky…` note; an "Oběd" movement or a PRUZNA employee is only flagged as before.

## Issue
Closes #68

🤖 Generated with [Claude Code](https://claude.com/claude-code)
