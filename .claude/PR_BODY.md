## Description
On the daily presence overview, the legend counts at the top ("Přítomen: 1", "Dovolená: 2", "Nepřítomen: 5", ...) were all rendered as neutral grey badges, while the same states are colored per employee row. The legend now uses the same badge class and color as the row badges, so absence states are recognizable at a glance.

## Changes
- `reports/views.py`: `prehled_pritomnosti` now passes the full `StavZamestnance` (label, `badge_trida`, `barva`) in each `pocty` entry instead of just a label and count; category ordering (first occurrence, Přítomen first, Nepřítomen last) is unchanged.
- `templates/reports/prehled_pritomnosti.html`: legend badge uses `{{ p.stav.badge_trida }}` / `p.stav.barva`, the same markup as the row badges.
- `reports/tests.py`: regression test asserting the legend state carries the type's color and that the colored badge renders in both the legend and the employee row.

## How to test
1. `python manage.py test` — 56/56 pass (CI runs the same)
2. Open the daily presence overview on a day with an approved absence (e.g. dovolená or home office) — the legend badge for that state has the same color as the badge next to the employee

## Issue
None — small visual fix.
