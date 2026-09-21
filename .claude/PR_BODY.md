## Description
Two admin help texts on `TypPohybu` described behavior that didn't match the code, which is misleading for whoever configures movement types in Django admin:

- `zobrazuje_se_na_pracovisti` said it keeps the employee shown as on-site in the daily presence overview — but no report reads this flag; it is stored only.
- `zapocitava_se_u_pruzne_pracovni_doby` said "evidence only, logic isn't enforced anywhere" — but `WorkdaySummary.prepocitej()` does apply it for flex-time employees (only the part inside the core block stays counted).

## Changes
- `timetracking/models.py`: rewrote both `help_text`s to match the code. The first now says it is evidence-only and states the intended meaning; the second drops the false "evidence only" sentence and notes it only matters together with `zapocitava_se_do_pracovni_doby`.
- `timetracking/migrations/0005_typpohybu_help_texty.py`: metadata-only `AlterField` migration (Django tracks `help_text`); no database schema change.

## How to test
1. `python manage.py makemigrations --check` — no changes; `python manage.py test` — 56/56 pass (CI runs both)
2. Django admin → Typy pohybu → open one: the two fields show the new help text

## Issue
None — documentation-in-code fix found while updating CLAUDE.md.
