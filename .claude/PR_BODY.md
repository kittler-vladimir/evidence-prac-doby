## Description

Implement issue #12: mid-day movements (Pohyby) during work sessions. Employees can now log breaks, doctor's appointments, personal errands, and other movements during the workday. Each movement type determines whether its duration counts toward worked time or gets deducted. Includes flexible/fixed working hours infrastructure, with core-hours (jádrová doba) accounting for flexible schedules now enforced in the daily recalculation.

## Changes

- **accounts/models.py, accounts/admin.py**: Add `TypUvazku.druh_pracovni_doby` (flexible/fixed), new `CasovyBlokUvazku` model for time blocks with admin inline validation (1 block for flexible type)
- **timetracking/models.py**: Add `TypPohybu` (movement type catalog) and `Pohyb` (movement nested in WorkSession with bounds and overlap validation); extend `WorkdaySummary` with `pohyby_minuty` field and recalculation logic (deducts only movements in closed sessions). Add `TypPohybu.zobrazuje_se_na_pracovisti` (presence-overview display flag) and `TypPohybu.zapocitava_se_u_pruzne_pracovni_doby`; for employees on flexible (pružná) hours, `WorkdaySummary.prepocitej()` now counts such movements as worked time only within the employee's core (jádrová) time block and deducts the portion outside it
- **timetracking/admin.py**: Expose the two new `TypPohybu` fields in `list_display`
- **timetracking/signals.py**: Trigger `prepocitej()` on movement save/delete
- **timetracking/views.py**: Add `start_pohyb`, `return_pohyb`, `pridat_pohyb` (live logging + retrospective entry); block clock-out when open movement exists
- **timetracking/forms.py**: Add `PohybRucneForm` for retrospective movement entry with auto-parent-session resolution
- **timetracking/urls.py**: Wire new routes
- **templates/timetracking/dashboard.html, pridat_pohyb.html**: Movement controls and today's movements list
- **timetracking/management/commands/close_open_sessions.py**: Flag stale open movements alongside forgotten sessions
- **timetracking/tests.py**: 14 regression tests covering validation, recalculation, blocking, null-handling, and core-hours clipping for flexible schedules

## Bug fixes from code review

1. **WorkdaySummary premature deduction**: Movements in still-open sessions now don't reduce time from already-closed sessions that day
2. **start_pohyb input validation**: Now gracefully rejects missing/non-numeric typ_id instead of crashing with ValueError
3. **Orphaned open movements**: Clock-out blocking moved to model level, so admin path can't orphan a movement

## How to test

1. Log in as test user, click Příchod (clock in)
2. Select movement type from dropdown, click Start
3. UI shows "Na pohybu: [type] od [time]" with "Návrat" button; Odchod button is hidden
4. Try clicking Odchod (blocked) — see warning "Nejprve zapište návrat"
5. Click Návrat (return) — movement closed, Odchod button re-appears
6. In daily summary, new "Dnešní pohyby" section shows logged movements and whether they count
7. Run `python manage.py test` — all tests pass (14 regression tests in `timetracking`)
8. Admin: TypPohybu → manage movement types; Pohyb → view/edit individual movements
9. Admin: TypUvazku → edit a type, add >1 block to flexible type → validation error
10. Admin: TypUvazku → set `druh_pracovni_doby` to Pružná and add one `CasovyBlokUvazku` (e.g. 9:00–14:00); TypPohybu → enable `zapocitava_se_do_pracovni_doby` and `zapocitava_se_u_pruzne_pracovni_doby` on a movement type
11. Log a movement of that type partly outside the core block → verify only the portion inside 9:00–14:00 stays counted as worked time in the daily summary (`pohyby_minuty` reflects the deducted, out-of-core portion)

## Issue

Closes #12
