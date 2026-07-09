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

`Employee.funkce` (a `CharField` with choices, one per employee, blank = no role) grants scoped self-service access to the employee CRUD screens in `accounts` (`seznam_zamestnancu`, `pridat_zamestnance`, `upravit_zamestnance`, `presunout_zamestnance`) without making someone a full Django admin (`is_staff`):

| Funkce | CRUD scope | Can transfer between oddělení | Can appoint funkce |
|---|---|---|---|
| `VEDOUCI_ODDELENI` | own `Oddeleni` only | no (`muze_presouvat_zamestnance=False`) | no |
| `REDITEL_ODBORU` / `SEKRETARIAT_ODBORU` | all `Oddeleni` in own `Odbor` | yes | yes (`muze_menit_funkci=True`) |
| `REDITEL_SEKCE` | none — read-only `accounts:prehled_sekce` (odbory of own `Sekce` + their `REDITEL_ODBORU`/`VEDOUCI_ODDELENI` holders) | no | no |
| *(blank)* | none | no | no |

`Employee.save()` keeps `funkce` and the org-level `vedouci` FKs in sync (inside `transaction.atomic()`): assigning a unit-scoped funkce (`VEDOUCI_ODDELENI`→`Oddeleni.vedouci`, `REDITEL_ODBORU`→`Odbor.vedouci`, `REDITEL_SEKCE`→`Sekce.vedouci`) sets that FK and silently clears `funkce` on any other employee currently holding the same funkce on the same unit — at most one holder per funkce per org unit. `SEKRETARIAT_ODBORU` has no FK counterpart but still enforces the one-holder-per-`Odbor` rule. **Transferring an employee to a different `Oddeleni` clears their `funkce` entirely** (a funkce is bound to the unit it was granted on) unless the same `save()` call also sets a new funkce explicitly.

`accounts.viditelni_zamestnanci(user)` and `reports.prehled_pritomnosti`/`prehled_tymu` use the same funkce-based scoping (plus `Odbor.zamestnanci_vidi_cely_odbor` for employees with no funkce) for read-only visibility — kept as one shared helper so `accounts` and `reports` access rules can't drift apart.

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
