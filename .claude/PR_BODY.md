## Description
`WorkdaySummary.prescos_minuty` is a signed balance against the daily norm (17 of 22 rows in the dev DB are negative), but every screen labeled it "Přesčas" and formatted it with `//`/`%`, which is wrong for negative minutes (`-90` rendered as `"-2h 30min"`). This shows overtime and shortfall as two separate values everywhere, with totals only per ISO week and per month (never per day), and leaves a day with only an open work block out of both totals.

## Changes
- `timetracking/bilance.py` (new): `format_minut()` (absolute-value `"Xh Ymin"`, optional signed `−`), `Bilance`/`secti()`, `rozdel_na_tydny()` (ISO-week grouping clipped to the displayed month, week label + range)
- `timetracking/models.py`: `WorkdaySummary.je_zapocitan` / `denni_prescas_minuty` / `denni_nedostatek_minuty` — derived properties, no stored field, no migration
- `timetracking/templatetags/timetracking_extras.py` (new): `minuty_hm` / `minuty_hm_znamenko` filters wrapping the formatter
- `timetracking/views.py` + `templates/timetracking/prehled_mesice.html`: Přesčas/Nedostatek/Bilance month cards, per-day two-column table, week subtotal rows
- `templates/timetracking/dashboard.html`: today's card and the recent-days table use the two values and the "not counted while only an open block" rule
- `reports/views.py::prehled_tymu` + `templates/reports/prehled_tymu.html`: per-employee month overtime/shortfall columns
- `reports/views.py::export_xlsx`: separate Přesčas/Nedostatek columns, a bold subtotal row per ISO week (reusing `rozdel_na_tydny()` — same grouping as the Výkaz), a bold month total row with the net Bilance
- **Also fixes a pre-existing bug**: `export_xlsx`'s sheet title was `f"Výkaz {mesic:02d}/{rok}"` — `/` is invalid in an Excel sheet name, so every export request crashed. Found while adding a test that actually opens the exported file; changed to `{mesic:02d}-{rok}`.
- `reports/tests.py`, `timetracking/tests.py`: 18 new tests — formatter edge cases (0/59/60/61/90/-90/-60/-1), week grouping incl. month/year boundaries, Výkaz/dashboard/Odbor/XLSX view tests, and an explicit regression assertion that no rendered or exported value contains `"-2h"`
- `CLAUDE.md`: rewrote the overtime/balance row to describe the derived display values and where they're used

## How to test
1. `python manage.py test` — 74/74 pass (CI runs it too)
2. Open the monthly Výkaz on a month with both overtime and shortfall days — check the weekly subtotal rows and the three month cards
3. Download the XLSX export — check the Přesčas/Nedostatek columns and the weekly/monthly subtotal rows (this used to 500 on every request)

## Issue
Closes #34
