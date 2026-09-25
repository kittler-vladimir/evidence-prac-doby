## Description
A `WorkSession` or `Pohyb` left open from a previous day (forgotten clock-out / return) could only be fixed in Django admin: nothing linked to `opravit_session`, there was no view to edit an existing `Pohyb` (and `WorkSession.clean()` refuses to close a block with an open movement), and the dashboard's one-click Odchod closed such a block with *today's* time. This makes these records visible and fixable where people work.

## Changes
- `timetracking/opravy.py` (new): single source for the `[AUTOMATICKY]` marker texts (now also imported by `close_open_sessions`), `zaznamy_k_oprave()` (open blocks/movements started before today's local midnight), `muze_opravovat()` (owner, `is_staff`, or a manager whose `spravovani_zamestnanci()` contains the employee — CRUD scope, never the read-only `viditelni_zamestnanci()`), `bezpecny_next()` (same-host redirect only).
- Dashboard: a block started before today shows a dated "Zapomenutý odchod" warning with "Opravit záznam" (or "Opravit pohyb" first if a movement is still open); Odchod and pohyb controls aren't rendered for it.
- Výkaz: "Záznamy k opravě" section (own records). Odbor report: "Záznamy k opravě v týmu" (managed scope; everyone for `is_staff`). Shared partial `_zaznamy_k_oprave.html`.
- `opravit_session`: widened permission (managers in scope), strips the marker when `konec` is saved, honours `next`. New `opravit_pohyb` view + `PohybOpravitForm` + template, same rules.
- `CLAUDE.md`: new "Forgotten clock-outs" section; quick-actions note updated.
- Tests: `OpravaZapomenutehoOdchoduTests` (11) — selection, dashboard (stale vs. today's block, open pohyb), Výkaz/Odbor sections and scope, 200/403 permissions for owner/manager/colleague/other manager, marker stripping, `next` redirect incl. rejected off-site URL, pohyb-then-block correction.

## Known limitation (not changed here)
`clock_out`'s default "now" path still accepts closing a previous-day block on a direct POST or from a dashboard tab left open across midnight — the restriction is UI-level. Blocking it server-side would reverse an earlier deliberate, tested decision; left for a separate decision.

## How to test
1. `venv/Scripts/python.exe manage.py test` — 138/138 pass
2. Create an open block for yesterday; dashboard shows the dated warning without Odchod, Výkaz and Odbor list it; fix it from Odbor → returns to Odbor, block closed, `[AUTOMATICKY]` note gone. (Verified in the browser on the test account; temporary data removed.)

## Issue
Closes #57

🤖 Generated with [Claude Code](https://claude.com/claude-code)
