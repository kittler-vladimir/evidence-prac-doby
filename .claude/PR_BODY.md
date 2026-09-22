## Description
The "Odpracováno" (worked time) cell in the dashboard's recent-days table concatenated `widthratio`'s rounded-to-whole-hours value with a raw, unformatted minutes number left over from debug template code — e.g. 470 minutes rendered as `"8h 470"` instead of `"7h 50min"`. Today's summary card on the dashboard had the same leftover debug junk (several dead `{% with %}`/`{{ }}` lines producing no useful output). The monthly Výkaz's "Odpracováno" column and its month total card used `widthratio` alone, which silently rounds to the nearest whole hour and drops the minutes entirely (no garbage text, but still wrong).

## Changes
- `templates/timetracking/dashboard.html`: today's card and the recent-days table's "Odpracováno" cell now use the `minuty_hm` filter (already used for Přesčas/Nedostatek in the same tables) instead of `widthratio`/`add:0` debug leftovers.
- `templates/timetracking/prehled_mesice.html`: daily "Odpracováno" column and the "Odpracováno celkem" month card also switched to `minuty_hm`, for the same reason and for consistency with the rest of the page.
- `timetracking/tests.py`: regression test reproducing the exact reported case (470 minutes) on both the dashboard and the Výkaz, asserting `"7h 50min"` renders and `"8h 470"` does not.

## How to test
1. `python manage.py test` — 77/77 pass (CI runs it too)
2. Log a work day with worked time that isn't a whole number of hours (e.g. 7h 50min) — the dashboard's today card, its recent-days table, and the monthly Výkaz all show `"7h 50min"`, not `"8h"` or garbled text

## Issue
None — reported directly as a bug, fixed inline (root cause: leftover debug template code, same fix as the already-existing `minuty_hm` formatter from #34/#35).
