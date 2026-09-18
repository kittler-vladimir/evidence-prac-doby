# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

The project is runnable locally:
- `manage.py`, `config/wsgi.py`, `config/asgi.py` exist.
- `venv/` holds a local virtualenv with `requirements.txt` installed (Django 5.0.6). Activate it or call `venv/Scripts/python.exe` directly.
- `.env` exists (copied from `.env.example`) and is currently configured for **local dev with SQLite** (`DB_ENGINE=sqlite`) and console email — see below.
- Migrations exist and are applied against `db.sqlite3`, which is kept around intentionally as dev seed data (test user `test@example.com` / `testpass123`, a test `Sekce`/`Odbor`/`Oddeleni`, a leave request, a closed work session). Don't delete it without checking with the user first.
- All templates referenced by views exist under `templates/`.
- **Not yet a git repository.**
- **No automated tests exist.**

## Local dev database (SQLite vs PostgreSQL)

`config/settings.py` reads `DB_ENGINE` from `.env` (default `postgresql`, matching production). Set `DB_ENGINE=sqlite` to run against `BASE_DIR / "db.sqlite3"` without a PostgreSQL server — this is what `.env` currently has. Switch it back to `postgresql` (and fill in `DB_NAME`/`DB_USER`/`DB_PASSWORD`/`DB_HOST`/`DB_PORT`) when testing against real Postgres.

## Project overview

Django app for tracking employee attendance ("Evidence pracovní doby") for a Czech organization. All domain code — model/field names, view names, URL names, template names, user-facing strings — is written in **Czech**. Match this convention for any new code; do not introduce English domain terms into models/views/templates.

## Commands

```bash
venv/Scripts/python.exe manage.py migrate
venv/Scripts/python.exe manage.py createsuperuser
venv/Scripts/python.exe manage.py generuj_svatky <rok> [--zeme CZ] [--prepsat]   # generate CZ public holidays for a year
venv/Scripts/python.exe manage.py close_open_sessions [--hodiny 14]              # flag forgotten clock-outs
venv/Scripts/python.exe manage.py obnov_rocni_naroky [--rok <rok>]               # roll vacation/IV balances into a new year (run via Celery Beat every 1 January)
venv/Scripts/python.exe manage.py runserver

# Celery (separate terminals)
celery -A config worker -l info
celery -A config beat -l info
```

A dev-server launch config exists at `.claude/launch.json` (`django-dev-server`, port **8010** — not 8000, since another unrelated local project was found squatting on port 8000 on this machine).

## Architecture

Four Django apps under `config/` (settings/urls/celery root), wired together through `accounts.Employee`:

- **`accounts`** — custom `User` (email-based login, `AUTH_USER_MODEL = "accounts.User"`), `Employee` profile, org hierarchy (`Sekce` → `Odbor` → `Oddeleni`), `TypUvazku` (contract type: hours/day, hours/week), `HistoriePrislusenosti` (department transfer history). Also owns `holidays_model.py` (`Zeme`, `StatniSvatek`, generated via the `holidays` PyPI library).
- **`timetracking`** — `WorkSession` (one clock-in/clock-out block; overlap and end-after-start validated in `clean()`) and `WorkdaySummary` (per-employee-per-day rollup, recomputed via `WorkdaySummary.prepocitej()`).
- **`leaves`** — `TypStavu` (employee state type — dovolená, nemoc, indispoziční volno, home office, etc.; `vyzaduje_schvaleni` picks between the two workflows below, `je_pritomnost` marks presence-type states like home office), `ZustatekStavu` (yearly hour balance, only relevant for `odecita_ze_zustatku=True` types), `ZadostOStav` (a request — for `vyzaduje_schvaleni=True` types like dovolená/indispoziční volno, goes through an approval workflow: `schval()` / `zamitni()`; for `vyzaduje_schvaleni=False` types like nemoc/OČR/služební volno/home office, `save()` self-approves immediately with no approver and no email).
- **`reports`** — read-only views over the above: team overview (`prehled_tymu`) and XLSX export (`export_xlsx`, built with `openpyxl`).

URL namespaces are mounted in `config/urls.py`: `accounts` at `/`, `timetracking` at `/dochazka/`, `leaves` at `/dovolena/`, `reports` at `/reporty/`.

### Organizational hierarchy & approval chain

```
Sekce → Odbor → Oddeleni → Employee
```

Each level has an optional `vedouci` (manager) FK to `Employee`. `Employee.get_schvalovatel()` walks up this chain (department head → division head → section head) to find the direct approver; if no manager is set at any level, it returns `None` and an admin must approve manually. `ZadostOStav.save()` auto-assigns `schvalovatele` from this method if not already set — but only for `typ.vyzaduje_schvaleni=True` requests; self-recorded types skip this entirely.

### Employee funkce (roles) and access scoping

`Employee.funkce` is a `ForeignKey` to the `accounts.Funkce` číselník (not a hardcoded enum) — every employee always has a funkce, defaulting to `ZAMESTNANEC` ("Zaměstnanec", the rank-and-file role with no elevated rights; replaces the old blank/no-role state). A new role — with its own CRUD scope, org-unit binding, and deputy rules — can be added by an admin through Django admin (`FunkceAdmin`), without a code deploy. `Funkce` fields:

- `uroven_vazby` (`ZADNA`/`ODDELENI`/`ODBOR`/`SEKCE`) — the org level this funkce is scoped/deduped at (drives `Employee.spravovana_oddeleni()`, `moznosti_zastupce()`, and the "at most one holder per funkce per org unit" rule)
- `synchronizuje_vedouciho` — whether assigning this funkce writes the employee into the matching `Sekce`/`Odbor`/`Oddeleni.vedouci` FK (see below)
- `muze_spravovat_zamestnance` / `muze_presouvat_zamestnance` / `muze_menit_funkci` / `muze_mit_zastupce` / `bez_seznamu_zamestnancu` — the permission flags, read directly off the related `Funkce` row by `Employee`'s `muze_*` properties instead of hardcoded Python tuples

The 5 seeded rows reproduce the pre-refactor hardcoded behavior 1:1, and grant scoped self-service access to the employee CRUD screens in `accounts` (`seznam_zamestnancu`, `pridat_zamestnance`, `upravit_zamestnance`, `presunout_zamestnance`) without making someone a full Django admin (`is_staff`):

| Funkce | `uroven_vazby` | `synchronizuje_vedouciho` | CRUD scope | Can transfer between oddělení | Can appoint funkce |
|---|---|---|---|---|---|
| `VEDOUCI_ODDELENI` | `ODDELENI` | yes | own `Oddeleni` only | no (`muze_presouvat_zamestnance=False`) | no |
| `REDITEL_ODBORU` | `ODBOR` | yes | all `Oddeleni` in own `Odbor` | yes (`muze_menit_funkci=True`) | yes |
| `SEKRETARIAT_ODBORU` | `ODBOR` | **no** | all `Oddeleni` in own `Odbor` | yes | yes |
| `REDITEL_SEKCE` | `SEKCE` | yes | none — read-only `accounts:prehled_sekce` (odbory of own `Sekce` + their `REDITEL_ODBORU`/`VEDOUCI_ODDELENI` holders); `bez_seznamu_zamestnancu=True` | no | no |
| `ZAMESTNANEC` | `ZADNA` | no | none | no | no |

`Employee.save()` keeps `funkce` and the org-level `vedouci` FKs in sync (inside `transaction.atomic()`): assigning a `synchronizuje_vedouciho=True` funkce sets the `vedouci` FK at the level given by `uroven_vazby` (`ODDELENI`→`Oddeleni.vedouci`, `ODBOR`→`Odbor.vedouci`, `SEKCE`→`Sekce.vedouci`) and silently resets `funkce` back to `ZAMESTNANEC` on any other employee currently holding the same funkce on the same unit — at most one holder per funkce per org unit, scoped by `uroven_vazby` regardless of the sync flag (so `SEKRETARIAT_ODBORU`, with `synchronizuje_vedouciho=False`, still enforces one-holder-per-`Odbor` without ever touching `Odbor.vedouci`). **Transferring an employee to a different `Oddeleni` resets their `funkce` to `ZAMESTNANEC`** (a funkce is bound to the unit it was granted on) unless the same `save()` call also sets a new funkce explicitly.

`accounts.viditelni_zamestnanci(user)` derives read-only visibility from the same `Funkce` row (`bez_seznamu_zamestnancu` → no individual list; `uroven_vazby` in `ODBOR`/`SEKCE` → whole odbor/sekce; `ODDELENI`/`ZADNA` → whole odbor or just own `Oddeleni` per `Odbor.zamestnanci_vidi_cely_odbor`) — kept as one shared helper so `accounts` and `reports.prehled_pritomnosti` access rules can't drift apart. **Note**: `reports.prehled_tymu` does *not* actually share this scoping (it uses `Employee.spravovani_zamestnanci()`, the narrower CRUD scope, directly) — tracked as a separate drift in [issue #24](https://github.com/kittler-vladimir/evidence-prac-doby/issues/24).

`Employee.je_reditel_sekce` (gates `accounts:prehled_sekce`) additionally requires `uroven_vazby == SEKCE`, not just `bez_seznamu_zamestnancu` — otherwise a future admin-added funkce meant only to hide a lower-level role from the individual employee list would also, as a side effect, unlock the whole-`Sekce` overview.

`FunkceAdmin` protects the 5 seeded rows' `kod` (read-only once created, undeletable, including from the bulk "delete selected" action) since business logic (`Funkce.vychozi()` and others) resolves specific roles by `kod` — renaming or deleting one of these would crash employee creation/transfer app-wide. Everything else about a seeded row (flags, `nazev`, `aktivni`) stays editable, and admin-added custom roles have no such restriction.

**Known gap**: `Sekce`/`Odbor`/`Oddeleni.vedouci` remain directly editable in Django admin with no back-sync to `funkce` — setting `vedouci` there without also setting the matching employee's `funkce` leaves that manager without scoped access. Migration `accounts/0004_zpetne_dosazeni_funkce_z_vedouciho` backfilled `funkce` for `vedouci` assignments that existed before this feature, but any `vedouci` set afterward via the admin FK still needs `funkce` set to match.

### Recompute-on-save pattern

`WorkdaySummary` is never written directly by views — it's derived. `timetracking/signals.py` listens for `post_save`/`post_delete` on `WorkSession` and calls `WorkdaySummary.prepocitej(employee, date)`, which recalculates gross minutes, mandatory break deduction, net worked minutes, and overtime from scratch for that employee/day. When touching worked-time logic, edit `prepocitej()`, not the views.

### Business rules (from `config/settings.py` and model logic)

| Rule | Value |
|---|---|
| Mandatory break after | `BREAK_THRESHOLD_HOURS` = 6 hours worked |
| Break length | `MANDATORY_BREAK_MINUTES` = 30 min (not counted as worked time) |
| Overtime | worked minutes beyond `Employee.typ_uvazku.hodiny_denne × 60` for that day |
| Leave accounting | tracked in hours; `ZadostOStav.vypocitej_hodiny()` counts weekdays excluding `StatniSvatek` entries, × `hodiny_denne`, for both approval-based and self-recorded requests |
| Public holidays | generated per-year from the `holidays` library (`generuj_svatky_cr`), editable afterward in Django admin |

### Notifications

`leaves/signals.py` sends email on `ZadostOStav` `post_save`: new request → approver, approved/rejected → employee. This only fires for `vyzaduje_schvaleni=True` types (dovolená, indispoziční volno) — self-recorded types are created with `stav=SCHVALENO` directly and have no `schvalovatele`, so no email goes out. Templates live in `templates/leaves/emails/*.txt`. Emails are sent with `fail_silently=True`.

### Scheduled maintenance

`close_open_sessions` (intended to run nightly via Celery Beat) flags `WorkSession` rows still open (`konec__isnull=True`) past a threshold (default 14h) by prepending an `[AUTOMATICKY]` note — it does not close them, just marks them for manual correction.
