## Description
The "Měsíc celkem" (month total) row at the bottom of the monthly Výkaz was rendered with Bootstrap's `table-dark` (black background, white text). It now uses a white background with bold black text.

## Changes
- `templates/timetracking/prehled_mesice.html`: `table-dark fw-bold` → `bg-white fw-bold text-dark` on the month total row.

## How to test
1. Open Výkaz (`/dochazka/mesic/`) for a month with records.
2. The last table row "Měsíc celkem" has a white background and bold black text.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
