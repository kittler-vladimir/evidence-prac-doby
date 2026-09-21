## Description
The help text of `TypUvazku.druh_pracovni_doby` said working-time blocks are "nowhere enforced, groundwork for future validation". That is only half true: `WorkdaySummary.prepocitej()` reads the core block (`CasovyBlokUvazku`) of a flexible contract when counting movements flagged "counts for flexible working time". Clock-in/clock-out times are still not validated against blocks, and blocks of fixed working time are used by no calculation.

## Changes
- `accounts/models.py`: help text now says where the core block is used and what is still evidence-only.
- `accounts/migrations/0008_typuvazku_help_text.py`: metadata-only `AlterField` (Django tracks `help_text`); no database schema change.

## How to test
1. `python manage.py makemigrations --check` — no changes; `python manage.py test` — 56/56 pass (CI runs both)
2. Django admin → Typy úvazků → open one: "Druh pracovní doby" shows the new help text

## Issue
None — follow-up to #32 (same kind of stale help text).
