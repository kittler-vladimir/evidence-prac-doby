## Description
Leave hours for employees on fixed working hours (`PEVNA`) are now counted per weekday from their contract type's time blocks instead of the flat `hodiny_denne`: with the current data a day of leave is 8.25 h Mon–Thu and 7 h on Friday, so a full week is 40 h. Flexible hours (`PRUZNA`) keep `hodiny_denne` (8 h) every Mon–Fri.

## Changes
- `accounts/models.py`: new `TypUvazku.norma_minut(datum)` — the single source of the daily norm (`PRUZNA`: `hodiny_denne` × 60; `PEVNA`: net time of that weekday's blocks, 0 without a block).
- `leaves/models.py`: `ZadostOStav.vypocitej_hodiny()` sums `norma_minut()` over non-holiday weekdays (all `TypStavu`), quantized to 2 decimals.
- `timetracking/models.py`: `WorkdaySummary.prepocitej()` uses the same helper instead of its own copy from #72 (results unchanged, existing tests pass).
- `leaves/tests.py`: PEVNA week = 40 h, Friday = 7 h, Monday = 8.25 h, holiday skipped, day without block = 0, range over a weekend, PRUZNA unchanged, saved request uses new hours.
- `CLAUDE.md`, `README.md`: document the rule.

Existing requests and balances are intentionally left untouched (no data migration).

## How to test
1. As a fixed-hours employee, create a leave request for a single Friday → 7 h; for Mon–Fri → 40 h.
2. As a flexible-hours employee, a Friday is still 8 h.

## Issue
Closes #74

🤖 Generated with [Claude Code](https://claude.com/claude-code)
