## Description
`Employee.funkce` was a hardcoded `CharField` enum (`FunkceChoices` + two Python permission tuples). This replaces it with a proper `Funkce` reference table (`ForeignKey`) whose CRUD scope, org-unit binding, and deputy-rights are data-driven flags — a new role can be added by an admin through Django admin, without a code deploy. Adds an explicit `ZAMESTNANEC` ("Zaměstnanec") role replacing the old implicit blank/no-role state, so every employee always has a funkce.

## Changes
- `accounts/models.py`: new `Funkce` model (`uroven_vazby`, `synchronizuje_vedouciho`, and the 5 permission flags); `Employee.funkce` is now a `ForeignKey`; `viditelni_zamestnanci()`, `spravovana_oddeleni()`, `moznosti_zastupce()`, `_jednotka_pro_funkci()`, `_drzitele_stejne_funkce()`, `Employee.save()`'s vedouci-sync, and the `muze_*` properties all read from the related `Funkce` row instead of hardcoded Python tuples
- `accounts/migrations/0006_funkce.py`, `0007_employee_funkce_fk.py`: creates `Funkce`, seeds 5 rows reproducing the prior hardcoded behavior 1:1, and backfills every existing `Employee` (blank → `ZAMESTNANEC`, else by matching code) via a safe add-column → backfill → drop → rename → tighten sequence
- `accounts/admin.py`: new `FunkceAdmin` (číselník pattern); protects the 5 seeded rows' `kod` from rename/delete (including bulk delete) since business logic resolves them by code
- `accounts/forms.py`: `EmployeeUpdateForm`'s funkce dropdown always includes the employee's own current funkce even if since deactivated, so submitting an unrelated form change can't silently reassign their role
- `accounts/tests.py`, `reports/tests.py`: updated to the new FK-based model
- `CLAUDE.md`: rewrote the "Employee funkce (roles) and access scoping" section for the new data-driven model

## How to test
1. `python manage.py test` — 54/54 pass
2. `python manage.py migrate` against the existing dev `db.sqlite3` seed data — verified the backfill maps every employee correctly and `Employee.objects.filter(funkce__isnull=True, aktivni=True).count() == 0`
3. In Django admin → Funkce, confirm you can add a brand-new role (e.g. a department-level "Auditor") and it becomes selectable on an employee's edit form immediately
4. Confirm the 5 seeded roles' `kod` field is read-only and undeletable in admin, while other fields (flags, `nazev`, `aktivni`) stay editable

## Issue
Closes #26
