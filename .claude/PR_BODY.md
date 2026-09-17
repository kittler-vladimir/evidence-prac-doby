## Description
Replaces the flat table on the daily presence overview ("Přítomnost", `reports:prehled_pritomnosti`) with a grouped view. A regular employee now sees their own Odbor's employees grouped section-by-section by Oddělení (empty Oddělení are skipped). An admin (`is_staff`) sees the full Sekce → Odbor → Oddělení hierarchy by default, with a cascading filter to narrow down to one section/division/department.

## Changes
- `reports/views.py`: added `_pk_z_get` (safe GET param parsing), `_seskup_podle_oddeleni` and `_seskup_hierarchicky` (grouping helpers), applied a cascading `sekce`/`odbor`/`oddeleni` filter for staff, and fixed queryset ordering to break ties on each level's `id` (name alone isn't unique, which could otherwise interleave two same-named units).
- `templates/reports/prehled_pritomnosti.html`: replaced the flat table with grouped sections (Oddělení-only for employees; Sekce/Odbor headings + Oddělení sections for staff), added 3 cascading `<select>` filters with JS that resets lower-level selects when a higher one changes (so switching Sekce doesn't leave a stale Oddělení filter silently in effect).

Underlying visibility rules (`accounts.viditelni_zamestnanci`) are unchanged — this is a display/grouping enhancement only.

## How to test
1. Log in as a regular employee with no `funkce` → "Přítomnost" shows one section per Oddělení in their Odbor (or just their own Oddělení if `Odbor.zamestnanci_vidi_cely_odbor=False`); Oddělení with no visible employees today are omitted.
2. Log in as admin → full Sekce → Odbor → Oddělení hierarchy is shown with 3 filter selects; picking a Sekce narrows the table, the summary badge counts, and the Odbor select's options to that Sekce.
3. With an Oddělení filter active, switch the Sekce select → verify the Oddělení/Odbor filters reset and the new Sekce's full data is shown (not the stale narrower filter).

## Issue
Closes #20

🤖 Generated with [Claude Code](https://claude.com/claude-code)
