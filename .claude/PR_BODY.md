## Description

Employees holding a CRUD-scoped `funkce` (VEDOUCI_ODDELENI, REDITEL_ODBORU, SEKRETARIAT_ODBORU) can now assign exactly one colleague from their own org unit as their deputy. The deputy permanently gains the same employee-management rights, and additionally stands in as leave-request approver whenever the principal is marked absent (either manually via `rucne_nepritomen` or automatically via approved leave covering that date).

## Changes

- **accounts/models.py** — Employee.zastupce FK + rucne_nepritomen flag; clean() validates cross-unit assignment; je_nepritomen() detects absence via approved leave or manual flag; CRUD scoping properties extended to include permanent deputized rights; get_schvalovatel() substitutes deputy when principal is absent; save() clears zastupce on funkce/oddeleni change to maintain invariants.
- **accounts/forms.py** — ZastupceForm for self-service deputy selection, restricted to same-unit colleagues.
- **accounts/views.py** — muj_zastupce view (self-service screen), funkce-gated access, view context optimization.
- **accounts/urls.py** — muj_zastupce route added.
- **templates/accounts/muj_zastupce.html** — new self-service form template.
- **templates/accounts/home.html** — new home menu tile for deputy management, visible only to users with appropriate funkce.
- **accounts/migrations/0005_...py** — schema: zastupce FK (self-referential, SET_NULL) + rucne_nepritomen boolean.
- **accounts/tests.py** — 6 tests covering CRUD-scoping, absence detection, transfer/funkce-change cleanup, and cross-unit validation on new employees.

## How to test

1. Log in as a VEDOUCI_ODDELENI/REDITEL_ODBORU/SEKRETARIAT_ODBORU holder.
2. Visit home → "Můj zástupce" → select a same-unit colleague as deputy.
3. Confirm deputy now sees the deputized unit under Zaměstnanci → seznam.
4. Create an approved absence for the principal covering today.
5. Submit a leave request from someone under them.
6. Verify schvalovatele resolves to the deputy (not the principal).
7. Confirm transfer/funkce-change clears the deputy assignment.

## Issue

Closes #18
