## Description
`leaves.TypStavu` was missing a "Nemoc" (sick leave) record — `CLAUDE.md` and the existing `TypStavu.KategoriePrehled.NEMOC` enum choice both already assumed it existed as a standard self-recorded type alongside OČR/služební volno/home office, but the row itself was never seeded.

## Changes
- `leaves/migrations/0008_seed_nemoc.py`: idempotent data migration (`get_or_create`) creating `TypStavu(nazev="Nemoc", zkratka="NEM", vyzaduje_schvaleni=False, je_pritomnost=False, odecita_ze_zustatku=False, kategorie_pro_prehled="NEMOC", barva="#DC3545")`. Reverse is a no-op, matching the existing `0003_seed_and_backfill_typ.py` pattern, so a downgrade never deletes a type that might already be referenced by a real `ZadostOStav`.

## How to test
1. `venv/Scripts/python.exe manage.py test` — 120/120 pass
2. `venv/Scripts/python.exe manage.py migrate leaves` then check `leaves.TypStavu.objects.get(zkratka="NEM")` exists with the fields above

## Issue
Closes #51

🤖 Generated with [Claude Code](https://claude.com/claude-code)
