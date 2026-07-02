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
- **`leaves`** — `TypDovolene` (leave type), `ZustatekDovolene` (yearly hour balance), `ZadostODovolenou` (leave request with an approval workflow: `schval()` / `zamitni()`).
- **`reports`** — read-only views over the above: team overview (`prehled_tymu`) and XLSX export (`export_xlsx`, built with `openpyxl`).

URL namespaces are mounted in `config/urls.py`: `accounts` at `/`, `timetracking` at `/dochazka/`, `leaves` at `/dovolena/`, `reports` at `/reporty/`.

### Organizational hierarchy & approval chain

```
Sekce → Odbor → Oddeleni → Employee
```

Each level has an optional `vedouci` (manager) FK to `Employee`. `Employee.get_schvalovatel()` walks up this chain (department head → division head → section head) to find the direct approver; if no manager is set at any level, it returns `None` and an admin must approve manually. `ZadostODovolenou.save()` auto-assigns `schvalovatele` from this method if not already set.

### Recompute-on-save pattern

`WorkdaySummary` is never written directly by views — it's derived. `timetracking/signals.py` listens for `post_save`/`post_delete` on `WorkSession` and calls `WorkdaySummary.prepocitej(employee, date)`, which recalculates gross minutes, mandatory break deduction, net worked minutes, and overtime from scratch for that employee/day. When touching worked-time logic, edit `prepocitej()`, not the views.

### Business rules (from `config/settings.py` and model logic)

| Rule | Value |
|---|---|
| Mandatory break after | `BREAK_THRESHOLD_HOURS` = 6 hours worked |
| Break length | `MANDATORY_BREAK_MINUTES` = 30 min (not counted as worked time) |
| Overtime | worked minutes beyond `Employee.typ_uvazku.hodiny_denne × 60` for that day |
| Leave accounting | tracked in hours; `ZadostODovolenou.vypocitej_hodiny()` counts weekdays excluding `StatniSvatek` entries, × `hodiny_denne` |
| Public holidays | generated per-year from the `holidays` library (`generuj_svatky_cr`), editable afterward in Django admin |

### Notifications

`leaves/signals.py` sends email on `ZadostODovolenou` `post_save`: new request → approver, approved/rejected → employee. Templates live in `templates/leaves/emails/*.txt`. Emails are sent with `fail_silently=True`.

### Scheduled maintenance

`close_open_sessions` (intended to run nightly via Celery Beat) flags `WorkSession` rows still open (`konec__isnull=True`) past a threshold (default 14h) by prepending an `[AUTOMATICKY]` note — it does not close them, just marks them for manual correction.
