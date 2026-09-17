## Description
Applies the same organizational-hierarchy grouping and cascading filter that was added to the daily presence overview (#20/#21) to the monthly team overview (`reports:prehled_tymu`, "Tým" in the nav). This is a display-only change — who is included in the team overview is unchanged.

## Changes
- `reports/views.py`: `prehled_tymu` now groups results by `Sekce → Odbor → Oddělení` (admin) or by `Oddělení` (scoped manager), reusing the existing `_seskup_hierarchicky`/`_seskup_podle_oddeleni` helpers. Admin (`is_staff`) gets the same optional cascading `sekce`/`odbor`/`oddeleni` filter as `prehled_pritomnosti`. The filter-building logic and hierarchy `order_by` were extracted into shared `_filtr_podle_hierarchie()` / `SERAZENI_PODLE_HIERARCHIE`, now reused by both `prehled_tymu` and `prehled_pritomnosti`, removing ~50 lines of duplicated code flagged in review.
- `templates/reports/prehled_tymu.html`: flat table replaced with nested group cards (mirroring `prehled_pritomnosti.html`'s markup) plus the filter form; month/year (`rok`/`mesic`) is preserved across filter changes via hidden inputs.

## How to test
1. Log in as `test@example.com` / `testpass123` (`is_staff`) → open "Tým" → see the full `Sekce → Odbor → Oddělení` tree with 3 cascading filter selects; selecting a `Sekce` narrows the view and the `Odbor`/`Oddělení` options.
2. Log in as a single-`Oddělení` manager (`VEDOUCI_ODDELENI`) → see exactly one group for their `Oddělení`, no filter controls.
3. Log in as a multi-`Oddělení` manager (`REDITEL_ODBORU`/`SEKRETARIAT_ODBORU`) → see one group per managed `Oddělení`, no `Sekce`/`Odbor` headers, no filter.
4. Log in as an employee with no management scope → see "Žádní podřízení zaměstnanci."

Verified via `manage.py check`, browser screenshots (admin tree + filter), and Django test-client `force_login` across all the above roles — no change in who is included, only in grouping/display.

## Issue
Closes #22

🤖 Generated with [Claude Code](https://claude.com/claude-code)
