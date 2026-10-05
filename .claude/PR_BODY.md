## Description
The Výkaz showed a shortfall on Fridays (e.g. Kittler, 2 Oct 2026) for fixed-hours (`PEVNA`) employees who worked their full block. `WorkdaySummary.prepocitej()` compared worked time against the flat `TypUvazku.hodiny_denne` (8 h), while the Friday block 7:30–15:00 is 7 h net (and Mon–Thu 7:30–16:15 is 8 h 15 min net, which showed +15 min overtime). For `PEVNA` the daily norm is now the net time of that weekday's blocks.

## Changes
- `timetracking/models.py`: for `PEVNA`, norm = summed length of the blocks flagged for the weekday minus the mandatory break (same threshold rule as worked time); 0 for a day without a block. `PRUZNA` still uses `hodiny_denne`.
- `timetracking/tests.py`: full Mon block and full Fri block give balance 0, shorter work is a shortfall, a full week of blocks nets 0 and 40 h, a day without a block has norm 0, `PRUZNA` unchanged.
- `CLAUDE.md`, `README.md`: document the per-day norm for fixed hours.

Stored `WorkdaySummary` rows are not recomputed by this change; the local dev DB's PEVNA rows were recomputed manually.

## How to test
1. Open Výkaz for an employee on fixed hours who worked a full Friday block.
2. The day shows no shortfall and no overtime; Mon–Thu full blocks no longer show +15 min.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
