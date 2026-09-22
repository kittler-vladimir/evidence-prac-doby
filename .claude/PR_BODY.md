## Description
The dashboard's "Poslední záznamy" table greyed out weekend rows but never public holidays, because the row-highlighting condition checked a typo'd field name (`s.je_saint`) that doesn't exist on `WorkdaySummary`. Django templates silently resolve an unknown attribute to an empty string, so the condition was always false. The "Svátek" badge on the same row already used the correct field, so the badge showed while the row stayed un-greyed.

## Changes
- `templates/timetracking/dashboard.html`: `s.je_saint` → `s.je_svatek`, matching the badge condition two lines below.
- `timetracking/tests.py`: regression test asserting a holiday row gets `table-secondary` — verified it fails against the old code before the fix.

## How to test
1. `python manage.py test` — 75/75 pass (CI runs it too)
2. Log a work session on a day flagged as a public holiday — its row in "Poslední záznamy" on the dashboard is greyed out like a weekend row

## Issue
Closes #36
