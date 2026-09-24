# Evidence pracovní doby — Django projekt

## Technologie
- **Django 5.0** + PostgreSQL (lze spustit i proti SQLite pro lokální vývoj bez PostgreSQL serveru)
- **Celery** + Redis (noční úlohy — označení zapomenutých odpíchnutí)
- **Bootstrap 5** (server-rendered šablony)
- **openpyxl** (export do Excelu) — `weasyprint` je v `requirements.txt`, ale zatím ho nepoužívá žádný kód (žádný PDF export zatím neexistuje)

## Struktura projektu

```
config/             # settings, urls, celery
accounts/           # uživatelé, zaměstnanci, org. struktura, úvazky, svátky
timetracking/       # docházka (příchod/odchod, pohyby během směny, souhrny)
leaves/             # dovolená a další stavy, schvalování, zůstatky
reports/             # přehledy, export XLSX
templates/           # HTML šablony
```

## Instalace

```bash
# 1. Klonování a virtualenv
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 2. Závislosti
pip install -r requirements.txt

# 3. Prostředí
cp .env.example .env
# Vyplňte .env (DB, e-mail, Redis).
# Pro lokální vývoj bez PostgreSQL serveru nastavte DB_ENGINE=sqlite
# — poběží proti souboru db.sqlite3 v kořeni projektu.

# 4. Migrace
python manage.py migrate

# 5. Superuživatel (admin)
python manage.py createsuperuser

# 6. Vygenerovat státní svátky ČR
python manage.py generuj_svatky 2025
python manage.py generuj_svatky 2026

# 7. Spustit server
python manage.py runserver
```

Ve vývoji server běží na portu **8010** (viz `.claude/launch.json`), ne na výchozím 8000.

## Celery (noční úlohy)

```bash
# V samostatných terminálech
celery -A config worker -l info
celery -A config beat -l info
```

Celery Beat spouští pravidelně tyto příkazy:
- `close_open_sessions` — každou noc ve **2:00 (Europe/Prague)** označí zapomenuté otevřené záznamy (`[AUTOMATICKY]`) k ruční opravě, nezavírá je. Naplánováno jako `PeriodicTask` (`timetracking.tasks.close_open_sessions`), zaregistrováno migrací `timetracking/migrations/0006_schedule_close_open_sessions.py` — funguje automaticky, jakmile běží worker i beat, není potřeba nic nastavovat ručně v adminu.
- `obnov_rocni_naroky` — každý 1. leden převede zůstatky dovolené/indispozičního volna do nového roku.

### Ruční spuštění `close_open_sessions`

Bez čekání na noční běh (nebo bez rozeběhnutého Celery workeru/beatu vůbec) jde spustit přímo:

```bash
# přes management command (výchozí práh 14 hodin)
python manage.py close_open_sessions
python manage.py close_open_sessions --hodiny 12   # jiný práh

# nebo přes Celery task obal (stejný efekt)
python manage.py shell -c "from timetracking.tasks import close_open_sessions; close_open_sessions()"
```

> Na Windows může výstup s diakritikou vypadat rozbitě (`stdout` bere kódování z konzolové codepage, ne UTF-8) — pomůže `export PYTHONIOENCODING=utf-8` (Git Bash) před spuštěním.

## Organizační hierarchie

```
Sekce → Odbor → Oddělení → Zaměstnanec
```

Schvalovací řetěz kopíruje tuto hierarchii: zaměstnanec → vedoucí oddělení →
vedoucí odboru → ředitel sekce → admin (pokud vedoucí není na žádné úrovni
nastaven). Vypočítává `Employee.get_schvalovatel()`.

## Docházka a pohyby

- `WorkSession` — jeden blok příchod/odchod. Uvnitř probíhajícího bloku lze
  evidovat `Pohyb` (oběd, lékař, soukromá záležitost...) podle číselníku
  `TypPohybu`, který určuje, zda se doba pohybu započítává do odpracované
  doby, zda zaměstnanec zůstává veden jako přítomný na pracovišti, a zda se
  u pružné pracovní doby započítává jen v rámci jádrové doby.
- U **pevné pracovní doby** (`TypUvazku.druh_pracovni_doby = PEVNA`) se
  odpracovaná doba počítá jen v rámci časových bloků (`CasovyBlokUvazku`)
  zaškrtnutých pro daný den v týdnu — čas mimo blok se nezapočítá vůbec
  (ani jako práce, ani jako přesčas/nedostatek) a pohyby se u ní neodečítají.
  Den bez zaškrtnutého bloku dá 0 odpracovaných minut.
- `WorkdaySummary` je odvozený denní souhrn — nikdy se nezapisuje přímo,
  přepočítá se signálem po každé změně `WorkSession`/`Pohyb`.

## Stavy a dovolená

- `TypStavu` je obecný číselník stavů zaměstnance (dovolená, nemoc,
  indispoziční volno, služební volno, OČR, home office...).
- Typy s `vyzaduje_schvaleni=True` (dovolená, indispoziční volno) jdou přes
  žádost `ZadostOStav` a schvalovací workflow (e-mail žadateli i schvalovateli).
- Typy s `vyzaduje_schvaleni=False` (nemoc, OČR, služební volno, home office)
  si zaměstnanec zapisuje sám, rovnou schválené, bez e-mailu.
- Roční nároky (`NarokDovolene`, `NarokIndispozicnihoVolna`) a zůstatky
  (`ZustatekStavu`) se do nového roku převádí příkazem `obnov_rocni_naroky`.

## Klíčové byznys pravidla

| Pravidlo | Hodnota |
|----------|---------|
| Povinná přestávka po | 6 hodinách práce |
| Délka přestávky | 30 minut (neplatí do odpracované doby) |
| Přesčas / nedostatek | `prescos_minuty` je podepsaná bilance (odpracováno − denní norma); kladné dny se zobrazují jako přesčas, záporné jako nedostatek — vždy zvlášť, nikdy neseskládané do jednoho čísla |
| Dovolená a další stavy | evidovány v hodinách (dny × hodin denně dle úvazku) |
| Státní svátky | generovány z knihovny `holidays`, admin může upravit |

## Administrace

- Django admin (`/admin/`) — správa org. struktury, svátků, úvazků, číselníků;
  zaměstnance lze vytvořit i smazat přímo z formuláře uživatele. Pro `is_staff`
  uživatele je odkaz i v horní liště (dropdown se jménem).
- Vlastní web UI (namespace `accounts`, `timetracking`, `leaves`, `reports`,
  namontováno v `config/urls.py`) — zaměstnanci, docházka, žádosti, přehledy.

## TODO (rozšíření)

- [ ] Kalendářní zobrazení dovolené týmu
- [ ] Nastavení hesla při prvním přihlášení (e-mail s tokenem)
- [ ] 2FA pro přihlášení
- [ ] API pro terminálové docházkové čtečky (DRF)
- [ ] Upozornění/validace příchodu a odchodu proti časovým blokům úvazku — dnes bloky jen ovlivňují *výpočet* odpracované doby (ořezání u pevné pracovní doby, odečítání pohybů mimo jádro u pružné), příchod/odchod mimo blok systém nijak neomezí ani na něj neupozorní
