## Description
`reports.prehled_tymu` ("Tým", now "Odbor") selected its employees via `Employee.muze_spravovat_zamestnance` / `spravovani_zamestnanci()` — the narrower CRUD-management scope — instead of the shared read-only `accounts.viditelni_zamestnanci()` that `reports.prehled_pritomnosti` ("Přítomnost") already uses, even though `CLAUDE.md` documented them as sharing scoping. A rank-and-file employee (`funkce=ZAMESTNANEC`) who already sees their whole odbor's presence status on "Přítomnost" saw an empty "Žádní podřízení zaměstnanci" here instead of their colleagues' monthly worked-hours/overtime.

## Changes
- `reports/views.py`: `prehled_tymu` now calls `viditelni_zamestnanci(request.user)`, the same call `prehled_pritomnosti` makes, replacing the `is_staff`/`muze_spravovat_zamestnance` branching; docstring updated
- `templates/base.html`, `templates/accounts/home.html`: nav link and dashboard card visibility gate widened to `user.employee or user.is_staff` (matching "Přítomnost") — otherwise the broadened page would stay undiscoverable behind the old CRUD-scope-only link
- Renamed "Tým" → "Odbor" across nav, page heading, dashboard card + subtitle, and the Reports index card (4 locations)
- `CLAUDE.md`: removed the now-resolved drift note from the `viditelni_zamestnanci` description
- `reports/tests.py`: new test asserting `prehled_tymu` and `prehled_pritomnosti` return the identical visible-employee set for a rank-and-file employee

## How to test
1. `python manage.py test` — 55/55 pass
2. Log in as an employee with no funkce (`ZAMESTNANEC`) — "Odbor" in the nav now shows the whole odbor's monthly hours instead of an empty page
3. Log in as `REDITEL_SEKCE` — page still renders empty (unchanged; they have their own `accounts:prehled_sekce`)
4. Log in as `is_staff` — full hierarchy + cascading filter, unchanged

## Issue
Closes #28
