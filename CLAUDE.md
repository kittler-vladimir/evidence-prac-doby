# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

The project is runnable locally:
- `manage.py`, `config/wsgi.py`, `config/asgi.py` exist.
- `venv/` holds a local virtualenv with `requirements.txt` installed (Django 5.0.6). Activate it or call `venv/Scripts/python.exe` directly.
- `.env` exists (copied from `.env.example`) and is currently configured for **local dev with SQLite** (`DB_ENGINE=sqlite`) and console email — see below.
- Migrations exist and are applied against `db.sqlite3`, which is kept around intentionally as dev seed data (an `is_staff` test account `test@example.com`, a test `Sekce`/`Odbor`/`Oddeleni`, real org data, leave requests, work sessions). Don't delete it without checking with the user first. `test@example.com` currently has no usable password (`set_unusable_password()`) — reset it via `manage.py changepassword` or Django admin before using it to log in.
- All templates referenced by views exist under `templates/`.
- **Is a git repository**, hosted on GitHub (`origin` remote) — work happens on feature branches with PRs (`issue-N-*` branch naming), issues tracked via `gh issue`.
- **Automated tests exist** — run with `venv/Scripts/python.exe manage.py test`, covering `accounts`, `reports`, `leaves`, `timetracking`. A GitHub Actions workflow (`.github/workflows/tests.yml`) runs the same suite (sqlite, dummy env vars — no secrets needed) on every push to `main` and every PR.

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

**Console encoding on this Windows machine**: Python's `sys.stdout.encoding` defaults to `cp1250` (the console codepage), not UTF-8. Czech diacritics in `manage.py` output show up as mojibake in Git Bash, and any character outside cp1250 (e.g. an emoji in a management command's `self.stdout.write()`) crashes the command with `UnicodeEncodeError` — this is what broke `close_open_sessions` until #49. Prefix commands with `PYTHONIOENCODING=utf-8` (also exported in `~/.bashrc`, but a non-interactive shell may not source it), and keep management-command output to cp1250-safe characters.

## Architecture

Four Django apps under `config/` (settings/urls/celery root), wired together through `accounts.Employee`:

- **`accounts`** — custom `User` (email-based login, `AUTH_USER_MODEL = "accounts.User"`), `Employee` profile, org hierarchy (`Sekce` → `Odbor` → `Oddeleni`), `TypUvazku` (contract type: hours/day, hours/week), `HistoriePrislusenosti` (department transfer history). Also owns `holidays_model.py` (`Zeme`, `StatniSvatek`, generated via the `holidays` PyPI library).
- **`timetracking`** — `WorkSession` (one clock-in/clock-out block; overlap, end-after-start, and konec-not-before-last-closed-Pohyb's-konec validated in `clean()`), `TypPohybu` + `Pohyb` (a movement nested inside a `WorkSession` — lunch, doctor, business trip, private errand; see "Pohyby" below) and `WorkdaySummary` (per-employee-per-day rollup, recomputed via `WorkdaySummary.prepocitej()`).
- **`leaves`** — `TypStavu` (employee state type — dovolená, nemoc, indispoziční volno, home office, etc.; `vyzaduje_schvaleni` picks between the two workflows below, `je_pritomnost` marks presence-type states like home office), `ZustatekStavu` (yearly hour balance, only relevant for `odecita_ze_zustatku=True` types), `NarokDovolene` / `NarokIndispozicnihoVolna` (global yearly entitlements in hours with a `platne_od` date, editable in admin — see the entitlements row in "Business rules"), `ZadostOStav` (a request — for `vyzaduje_schvaleni=True` types like dovolená/indispoziční volno, goes through an approval workflow: `schval()` / `zamitni()`; for `vyzaduje_schvaleni=False` types like nemoc/OČR/služební volno/home office, `save()` self-approves immediately with no approver and no email).
- **`reports`** — read-only views over the above: daily presence overview (`prehled_pritomnosti`, UI "Přítomnost"), monthly hours overview (`prehled_tymu`, UI label "Odbor"), company-wide employee search (`vyhledat_zamestnance` — deliberately not limited to the viewer's odbor) and XLSX export (`export_xlsx`, built with `openpyxl`). The daily overview derives each employee's state in `reports/services.py::stavy_zamestnancu` with this priority: approved presence-type record (`TypStavu.je_pritomnost`, e.g. home office) > Přítomen (open `WorkSession` today, any `WorkSession` on other dates) > approved absence record > Nepřítomen. The count legend at the top uses the same badge class/color as the per-employee badges.

URL namespaces are mounted in `config/urls.py`: `accounts` at `/`, `timetracking` at `/dochazka/`, `leaves` at `/dovolena/`, `reports` at `/reporty/`.

### Organizational hierarchy & approval chain

```
Sekce → Odbor → Oddeleni → Employee
```

Each level has an optional `vedouci` (manager) FK to `Employee`. `Employee.get_schvalovatel()` walks up this chain (department head → division head → section head) to find the direct approver; if no manager is set at any level, it returns `None` and an admin must approve manually. `ZadostOStav.save()` auto-assigns `schvalovatele` from this method if not already set — but only for `typ.vyzaduje_schvaleni=True` requests; self-recorded types skip this entirely.

**Deputy (`Employee.zastupce`)**: a holder of a funkce with `muze_mit_zastupce` picks a permanent deputy from the same org unit on `accounts:muj_zastupce`. The deputy (a) permanently gets the same CRUD rights as the holder — `Employee._ma_pravo()` / `spravovana_oddeleni()` union the deputy's own funkce with everyone they deputize for — and (b) takes over approvals while the holder is absent: `get_schvalovatel()` returns the deputy when the approver `je_nepritomen()` (`rucne_nepritomen=True`, or an approved non-presence absence covering today). The approver is resolved **once, when the request is created** (`ZadostOStav.save()`), so a request already waiting on someone stays with them even if they become absent later. `Employee.save()` clears `zastupce` when the holder transfers to another `Oddeleni` or their funkce changes.

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

`accounts.viditelni_zamestnanci(user)` derives read-only visibility from the same `Funkce` row (`bez_seznamu_zamestnancu` → no individual list; `uroven_vazby` in `ODBOR`/`SEKCE` → whole odbor/sekce; `ODDELENI`/`ZADNA` → whole odbor or just own `Oddeleni` per `Odbor.zamestnanci_vidi_cely_odbor`) — kept as one shared helper so `accounts`, `reports.prehled_pritomnosti`, and `reports.prehled_tymu` ("Odbor" — a monthly worked-hours/overtime výkaz, not a CRUD screen) all read the exact same scope and can't drift apart.

`Employee.je_reditel_sekce` (gates `accounts:prehled_sekce`) additionally requires `uroven_vazby == SEKCE`, not just `bez_seznamu_zamestnancu` — otherwise a future admin-added funkce meant only to hide a lower-level role from the individual employee list would also, as a side effect, unlock the whole-`Sekce` overview.

`FunkceAdmin` protects the 5 seeded rows' `kod` (read-only once created, undeletable, including from the bulk "delete selected" action) since business logic (`Funkce.vychozi()` and others) resolves specific roles by `kod` — renaming or deleting one of these would crash employee creation/transfer app-wide. Everything else about a seeded row (flags, `nazev`, `aktivni`) stays editable, and admin-added custom roles have no such restriction.

**Known gap**: `Sekce`/`Odbor`/`Oddeleni.vedouci` remain directly editable in Django admin with no back-sync to `funkce` — setting `vedouci` there without also setting the matching employee's `funkce` leaves that manager without scoped access. Migration `accounts/0004_zpetne_dosazeni_funkce_z_vedouciho` backfilled `funkce` for `vedouci` assignments that existed before this feature, but any `vedouci` set afterward via the admin FK still needs `funkce` set to match.

### Recompute-on-save pattern

`WorkdaySummary` is never written directly by views — it's derived. `timetracking/signals.py` listens for `post_save`/`post_delete` on `WorkSession` and calls `WorkdaySummary.prepocitej(employee, date)`, which recalculates gross minutes, mandatory break deduction, net worked minutes, and overtime from scratch for that employee/day. When touching worked-time logic, edit `prepocitej()`, not the views.

### Quick clock actions and the optional `cas` override

The dashboard's four one-click actions (`clock_in`/`clock_out`/`start_pohyb`/`return_pohyb`, all in `timetracking/views.py`) accept an optional POST field `cas` ("HH:MM", always today's date — parsed by `_cas_z_pozadavku`/`_cas_nebo_chyba`) behind a "Změnit čas" UI toggle, letting an employee correct a late click without leaving the dashboard. Blank/absent `cas` is the default and behaves exactly like the old hardcoded `timezone.now()`. Three things a future edit here must preserve:
- All four views now call `full_clean()` before saving (`_uloz_nebo_chybu`) — `clock_in`/`clock_out` didn't before this feature existed, so don't reintroduce a bare `.create()`/`.save()`.
- The same-day check in `_stejny_den_nebo_chyba` (used by `clock_out`/`return_pohyb`) only applies when `cas` was **explicitly entered** (`byl_zadan=True`), never to the default "now" path — otherwise a plain one-click Odchod/Návrat for a session or pohyb left open from a previous day (overnight shift, `close_open_sessions` candidate) would start failing.
- `cas` only carries minute precision, while the default "now" path (and any earlier same-day record it must follow) carries full microsecond precision from `timezone.now()`. `_cas_z_pozadavku` takes an optional `navazuje_na` anchor (the record's zacatek/konec this action must land after — computed via `_navazuje_na_konec_bloku()` for `clock_out`/`start_pohyb`, or `pohyb.zacatek` for `return_pohyb`) and nudges the entered time to `navazuje_na + 1 microsecond` whenever it falls in the same minute but isn't strictly after it — otherwise a same-minute Odchod/Start/Návrat (e.g. leaving "Změnit čas"'s prefilled current time unchanged) gets minute-truncated to just before its anchor and `WorkSession`/`Pohyb.clean()` reject it as out-of-order (Closes #43).

### Pohyby (movements during a work block)

A `Pohyb` lives inside exactly one `WorkSession` (it can't start before it, end after it, or overlap another `Pohyb` in the same block — validated in `clean()`). Employees start/return via `timetracking:start_pohyb` / `return_pohyb` or add one afterwards via `pridat_pohyb`. Behavior is driven by three flags on `TypPohybu` (admin-editable číselník):

- `zapocitava_se_do_pracovni_doby` (default off) — off: the movement's duration is subtracted from worked time (lunch, private errand); on: work keeps running (paid break).
- `zapocitava_se_u_pruzne_pracovni_doby` (only meaningful together with `zapocitava_se_do_pracovni_doby` on) — for employees whose `TypUvazku.druh_pracovni_doby` is `PRUZNA`, a counted movement only stays counted inside the core block (`CasovyBlokUvazku`); the part outside it is subtracted like a normal movement.
- `zobrazuje_se_na_pracovisti` — **stored only**: no report reads it yet (the presence overview does not consult `Pohyb`), so it does not currently affect anything.

`WorkdaySummary.prepocitej()` only counts *finished* movements inside *closed* work blocks; an in-progress movement or block is picked up when it closes and triggers the recompute again.

**Fixed working hours (`PEVNA`)**: `CasovyBlokUvazku` also carries 7 day-of-week `BooleanField`s (`pondeli`…`nedele`, `CasovyBlokUvazku.DNY_V_TYDNU` gives the `date.weekday()`-ordered field names). For a `PEVNA`-typ employee, `WorkdaySummary.prepocitej()` sums each closed `WorkSession`'s overlap with every block flagged for that date's weekday — time outside those blocks is dropped entirely (not worked time, not overtime, not shortfall), and a day with no matching block gives 0 worked minutes even if a session exists. Movements (`Pohyb`) never subtract from worked time for `PEVNA`, regardless of `TypPohybu.zapocitava_se_do_pracovni_doby` — presence within the block is what defines worked time, not time spent away from the desk inside it. `PRUZNA` is unaffected — its own core-block-vs-movements logic (above) is unchanged, and it ignores the day-of-week flags entirely. `CasovyBlokUvazkuFormSet` (admin) requires a `PEVNA` block to have at least one day checked. Adding day-of-week flags to existing blocks (or a newly-added `PEVNA` `TypUvazku`) is a manual admin step, not something a migration backfills — a block with no day checked contributes nothing.

### Business rules (from `config/settings.py` and model logic)

| Rule | Value |
|---|---|
| Mandatory break after | `BREAK_THRESHOLD_HOURS` = 6 hours worked |
| Break length | `MANDATORY_BREAK_MINUTES` = 30 min (not counted as worked time) |
| Movements (pohyby) | for `PRUZNA`: finished `Pohyb` minutes are subtracted from worked time (same as the mandatory break) unless the `TypPohybu` has `zapocitava_se_do_pracovni_doby` — see "Pohyby" above for the flex-time exception. For `PEVNA`: movements are never subtracted — see "Fixed working hours" above |
| Overtime / balance | `WorkdaySummary.prescos_minuty` (stored) = worked minutes − `Employee.typ_uvazku.hodiny_denne × 60` for that day — a **signed balance against the daily norm**, not clamped overtime. `timetracking/bilance.py` derives overtime and shortfall from it for display: `denni_prescas_minuty` = `max(prescos_minuty, 0)`, `denni_nedostatek_minuty` = `max(-prescos_minuty, 0)`, both 0 when `WorkdaySummary.je_zapocitan` is false (`hrube_minuty == 0` — a day with only an open block, e.g. today, contributes neither). `rozdel_na_tydny()` groups a month's rows by ISO week (clipped to the displayed month) for weekly/monthly subtotals; `format_minut()` renders `"Xh Ymin"` from the absolute value, with a `−` sign only for an explicitly signed net balance; the same filter (`minuty_hm`) also formats plain, always-non-negative `odpracovane_minuty` (worked time) everywhere it's shown. Used consistently by the Výkaz, Odbor, XLSX export and dashboard — no `//`/`%`/`widthratio` formatting of minutes anywhere (that either produced values like "-2h 30min" for -90 minutes, or silently rounded worked time to whole hours / dropped it into leftover debug template code, e.g. "8h 470") |
| Leave entitlements | `NarokDovolene` / `NarokIndispozicnihoVolna` are global (same for everyone); `aktivni_hodnota(datum)` returns the row with the newest `platne_od <= datum`. `TypStavu.vychozi_narok(datum)` supplies the default balance when no `ZustatekStavu` exists yet. `obnov_rocni_naroky`: dovolená = last year's leftover (min 0) + the yearly entitlement, indispoziční volno = the current value with no carry-over. Changing an entitlement does not recompute existing `ZustatekStavu` rows |
| Leave accounting | tracked in hours; `ZadostOStav.vypocitej_hodiny()` counts weekdays excluding `StatniSvatek` entries, × `hodiny_denne`, for both approval-based and self-recorded requests |
| Public holidays | generated per-year from the `holidays` library (`generuj_svatky_cr`), editable afterward in Django admin |

### Notifications

`leaves/signals.py` sends email on `ZadostOStav` `post_save`: new request → approver, approved/rejected → employee. This only fires for `vyzaduje_schvaleni=True` types (dovolená, indispoziční volno) — self-recorded types are created with `stav=SCHVALENO` directly and have no `schvalovatele`, so no email goes out. Templates live in `templates/leaves/emails/*.txt`. Emails are sent with `fail_silently=True`.

### Scheduled maintenance

`close_open_sessions` flags `WorkSession` rows still open (`konec__isnull=True`) past a threshold (default 14h) by prepending an `[AUTOMATICKY]` note and setting `opraveno=False`. It does the same for open `Pohyb` rows past the threshold (an `[AUTOMATICKY]` note about the missing return time). It never closes anything — it only marks them for manual correction.

It **is** registered as a nightly Celery Beat `PeriodicTask` (02:00 Europe/Prague) — migration `timetracking/migrations/0006_schedule_close_open_sessions.py` creates the `CrontabSchedule`/`PeriodicTask` rows (idempotently, via `get_or_create`) pointing at `timetracking.tasks.close_open_sessions`, a thin `@shared_task` wrapper that just calls the management command. This makes the schedule active automatically as soon as a Celery worker + beat process actually runs against the database — as of now that's not yet deployed anywhere (dev only), so the task sits registered but idle until it is.

On this dev machine the command **does** run nightly by other means: a Windows Task Scheduler job ("EvidencePracDoby - close_open_sessions", daily 02:00, current user, runs only while logged on, missed runs fire at next opportunity) calls `close_open_sessions.bat` in the repo root, which logs to `logs\close_open_sessions.log` with `PYTHONIOENCODING=utf-8`. The `.bat` and `logs/` are gitignored (`*.bat`, `*.log`), so they're not visible in the repo. If a Celery worker + beat is ever deployed against this same database, disable one of the two schedulers — the command prepends a fresh `[AUTOMATICKY]` note on every run, so both firing would double-flag each forgotten session.
