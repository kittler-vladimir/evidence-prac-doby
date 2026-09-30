## Description
Clarifies the wording for #68: the auto-close end time follows the time blocks of each employee's own fixed-hours contract type (there can be several PEVNA types), not a fixed 16:15 / 15:00, and the work block is only closed together with an auto-closed movement of a flagged type.

## Changes
- `CHANGELOG.md`, `README.md`, `CLAUDE.md`: reworded accordingly.
- `timetracking/tests.py`: a second PEVNA type with different blocks gets its own end time (14:30); an open work block with no movement is only flagged, never closed.

## Issue
Refs #68

🤖 Generated with [Claude Code](https://claude.com/claude-code)
