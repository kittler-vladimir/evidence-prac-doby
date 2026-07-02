# Evidence pracovní doby — Django projekt

## Technologie
- **Django 5.0** + PostgreSQL
- **Celery** + Redis (nočí úlohy — označení zapomenutých odpíchnutí)
- **Bootstrap 5** (server-rendered šablony)
- **openpyxl** (export do Excelu)

## Struktura projektu

```
attendance_project/
├── config/             # settings, urls, celery
├── accounts/           # uživatelé, zaměstnanci, org. struktura, svátky
├── timetracking/       # docházka (příchod/odchod, souhrny)
├── leaves/             # dovolená, schvalování, zůstatky
├── reports/            # přehledy, export XLSX
└── templates/          # HTML šablony
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
# Vyplňte .env (DB, e-mail, Redis)

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

## Celery (nočí úlohy)

```bash
# V samostatném terminálu
celery -A config worker -l info
celery -A config beat -l info
```

Celery Beat spouští každou noc příkaz `close_open_sessions`,
který označí zapomenuté otevřené záznamy k ruční opravě.

## Organizační hierarchie

```
Sekce → Odbor → Oddělení → Zaměstnanec
```

Schvalovací řetěz dovolených kopíruje tuto hierarchii:
zaměstnanec → vedoucí oddělení → vedoucí odboru → ředitel sekce → admin.

## Klíčové byznys pravidla

| Pravidlo | Hodnota |
|----------|---------|
| Povinná přestávka po | 6 hodinách práce |
| Délka přestávky | 30 minut (neplatí do odpracované doby) |
| Přesčas | odpracováno nad rámec denního úvazku |
| Dovolená | evidována v hodinách (8h = 1 den plného úvazku) |
| Státní svátky | generovány z knihovny `holidays`, admin může upravit |

## Administrace

- Django admin (`/admin/`) — správa org. struktury, svátků, úvazků
- Vlastní web UI — zaměstnanci, přesuny, přehledy

## TODO (rozšíření)

- [ ] PDF export výkazu (WeasyPrint)
- [ ] Kalendářní zobrazení dovolené týmu
- [ ] Nastavení hesla při prvním přihlášení (e-mail s tokenem)
- [ ] 2FA pro přihlášení
- [ ] API pro terminálové docházkové čtečky (DRF)
