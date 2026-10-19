# Nasazení na produkční server

Aplikace běží na **http://app.dochazka.mv.cz:8010/** (poprvé nasazeno ručně 14.–15. 10. 2026).
Tento dokument popisuje, jak je server zařízený, jak nasadit novou verzi (`deploy.sh`), jak
se vrátit ke starší verzi a jak server postavit znovu od nuly.

> Na stejném serveru běží na portu **80 v Apache stará PHP aplikace docházky**. Apache ani
> jeho konfigurace se nikdy nemění — nová aplikace má vlastní nginx na portu 8010.

## Přehled

```
prohlížeč ──► nginx :8010 ──► /static/  → /srv/evidence-prac-doby/app/staticfiles/
                         └──► gunicorn 127.0.0.1:8001 (3 workery, uživatel evidence)
                                         └──► PostgreSQL 18 na db-main-ctx.mv.cz:5432 (TLS, heslo z .pgpass)

Apache :80 — stará PHP aplikace (nesahat)
```

Databáze je od 19. 10. 2026 na samostatném serveru `db-main-ctx.mv.cz` (předtím lokální
PostgreSQL 17 na aplikačním serveru — viz [Původní lokální databáze](#původní-lokální-databáze)).

| Co | Hodnota |
|---|---|
| Server | `app.dochazka.mv.cz` (= `app-web-ctx.mv.cz`), Debian 13, Python 3.13 |
| SSH | alias `dochazka-app` (uživatel `kittler`, klíč `~/.ssh/id_rsa_afrodite`, `sudo` bez hesla) |
| Systémový uživatel aplikace | `evidence` (home `/srv/evidence-prac-doby`, shell `nologin`) |
| Kód | `/srv/evidence-prac-doby/app` (vlastník `evidence`), nasazený commit v `app/REVISION` |
| Virtualenv | `/srv/evidence-prac-doby/venv` |
| Konfigurace | `/srv/evidence-prac-doby/app/.env` (`root:evidence`, `640`) — obsahuje tajné hodnoty, nevypisovat |
| Databáze | PostgreSQL 18 na `db-main-ctx.mv.cz:5432` (10.74.34.173), DB `dochazka`, role `evidence` (vlastník DB, bez superuser). Heslo role `evidence` je jen v `/srv/evidence-prac-doby/.pgpass` (`evidence:evidence`, `600`) — čte ho aplikace, cron i `deploy.sh`; `DB_PASSWORD` v `.env` je prázdné. Pro čtení zvenku role `dochazka_ro` (viz [Přístup k databázi jen pro čtení](#přístup-k-databázi-jen-pro-čtení-jdbc-dbeaver-)) |
| Klient PostgreSQL | `postgresql-client-18` z repozitáře PGDG (`/etc/apt/sources.list.d/pgdg.sources`, pin 100 v `/etc/apt/preferences.d/pgdg.pref`, takže z PGDG jde jen to, co se výslovně vyžádá — dnes `postgresql-client-18` a `libpq5`). `pg_dump` 17 z Debianu zálohu ze serveru 18 odmítne; `pg_dump -h …` přes `pg_wrapper` použije automaticky nejnovější klient |
| Zálohy DB | `/srv/evidence-prac-doby/backups` (denní `pg_dump` z `db-main-ctx`, 14 dní) |
| Logy | `/var/log/evidence-prac-doby/` (cron), `journalctl -u evidence-prac-doby` (gunicorn), `/var/log/nginx/evidence-prac-doby.*.log` |
| Internet ze serveru | jen přes proxy `http://10.254.8.41:3128` (pip); GitHub není dostupný, kód se nahrává z vývojového počítače |

Do SSH konfigurace (`~/.ssh/config`) vývojového počítače patří:

```
Host dochazka-app
    HostName app.dochazka.mv.cz
    User kittler
    IdentityFile ~/.ssh/id_rsa_afrodite
```

### `.env` na serveru

Klíče jako v `.env.example`. Neveřejné hodnoty pro orientaci:

- `DEBUG=False`, `ALLOWED_HOSTS=app.dochazka.mv.cz,localhost` (`localhost` kvůli kontrolám přímo na serveru)
- `DB_ENGINE=postgresql`, `DB_NAME=dochazka`, `DB_USER=evidence`, `DB_HOST=db-main-ctx.mv.cz`, `DB_PORT=5432`, `DB_PASSWORD=` (prázdné — Django pak heslo nepředá a libpq ho vezme z `~evidence/.pgpass`; systemd i cron nastavují `HOME=/srv/evidence-prac-doby`)
- `EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend` — testovací fáze, e-maily jdou jen do logu gunicornu. Před ostrým provozem přepnout na SMTP a nastavit skutečný `DEFAULT_FROM_EMAIL`.
- V `.env` zůstaly zakomentované staré řádky pro `db-main-ctx.mv.cz` z doby PostgreSQL 13 (role `kittler`) — neplatí, aplikace používá roli `evidence`.
- `CELERY_*` musí být vyplněné (čte je `config/settings.py`), ale Celery na serveru neběží.

Před každou ruční úpravou udělat zálohu (`sudo cp -p .env .env.bak-$(date +%Y%m%d-%H%M%S)`).

### Služby

**gunicorn** — `/etc/systemd/system/evidence-prac-doby.service` (enabled):

```ini
[Unit]
Description=Evidence pracovni doby (gunicorn)
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=evidence
Group=evidence
WorkingDirectory=/srv/evidence-prac-doby/app
Environment=PYTHONIOENCODING=utf-8
ExecStart=/srv/evidence-prac-doby/venv/bin/gunicorn config.wsgi:application --workers 3 --bind 127.0.0.1:8001 --access-logfile - --error-logfile -
ExecReload=/bin/kill -s HUP $MAINPID
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`systemctl reload evidence-prac-doby` (HUP) nahradí workery novými bez výpadku — po nasazení
nového kódu stačí reload, restart není potřeba.

**nginx** — `/etc/nginx/sites-available/evidence-prac-doby`, symlink v `sites-enabled/`
(výchozí site `default` je vypnutá):

```nginx
server {
    listen 8010;
    listen [::]:8010;
    server_name app.dochazka.mv.cz;

    client_max_body_size 10m;
    access_log /var/log/nginx/evidence-prac-doby.access.log;
    error_log  /var/log/nginx/evidence-prac-doby.error.log;

    location /static/ {
        alias /srv/evidence-prac-doby/app/staticfiles/;
        expires 7d;
    }

    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
```

Kontrola přímo na serveru musí poslat hlavičku `Host` z `ALLOWED_HOSTS` — bez ní Django vrátí 400:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: app.dochazka.mv.cz' http://127.0.0.1:8010/prihlaseni/
```

**cron** — `/etc/cron.d/evidence-prac-doby` (Celery worker/beat na serveru neběží, noční úlohy
pouští cron):

```
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
# 02:00 - oznacit zapomenute odchody/pohyby
0 2 * * *   evidence  cd /srv/evidence-prac-doby/app && PYTHONIOENCODING=utf-8 /srv/evidence-prac-doby/venv/bin/python manage.py close_open_sessions >> /var/log/evidence-prac-doby/close_open_sessions.log 2>&1
# 02:30 - zaloha databaze (db-main-ctx.mv.cz, heslo z ~evidence/.pgpass), uchovat 14 dni
30 2 * * *  evidence  pg_dump -h db-main-ctx.mv.cz -U evidence -w -Fc dochazka > /srv/evidence-prac-doby/backups/dochazka-$(date +\%Y\%m\%d).dump && find /srv/evidence-prac-doby/backups -name 'dochazka-*.dump' -mtime +14 -delete
# 1. ledna 03:00 - zalozit zustatky dovolene/IV na novy rok (po nocni zaloze 02:30)
0 3 1 1 *   evidence  cd /srv/evidence-prac-doby/app && PYTHONIOENCODING=utf-8 /srv/evidence-prac-doby/venv/bin/python manage.py obnov_rocni_naroky >> /var/log/evidence-prac-doby/obnov_rocni_naroky.log 2>&1
```

`obnov_rocni_naroky` (převod zůstatků dovolené a IV do nového roku) běží 1. ledna ve 3:00 —
po noční záloze a bezpečně po půlnoci UTC, protože příkaz bere rok z `timezone.now().year`
(UTC). Je idempotentní, ruční opakování nic nezdvojí. Svátky na další rok
(`manage.py generuj_svatky <rok>`) se zatím generují ručně.

### Známá varování `check --deploy`

Aplikace zatím běží jen přes HTTP, proto `manage.py check --deploy` hlásí čtyři varování
(`security.W004` HSTS, `W008` SSL redirect, `W012` `SESSION_COOKIE_SECURE`, `W016`
`CSRF_COOKIE_SECURE`). Jsou očekávaná, nasazení nezastaví (zastaví ho jen chyba) a vyřeší se
až s HTTPS.

## Nasazení nové verze (`deploy.sh`)

Z vývojového počítače v Git Bash, z kořene repozitáře. Nasazuje se vždy **`origin/main`** —
tedy jen to, co prošlo PR a je na GitHubu:

```bash
./deploy.sh --check   # jen kontroly a seznam nových commitů, na serveru nic nemění
./deploy.sh           # nasazení; před první změnou na serveru se zeptá
```

Skript se zastaví na první chybě. Postupně:

1. Odmítne pokračovat, když pracovní strom není čistý (kromě `.claude/`) nebo když se místní
   `main` liší od `origin/main` (po `git fetch`).
2. Na serveru ověří `sudo`, adresáře, `.env` a běžící službu; vypíše nasazenou revizi a commity,
   které přibudou; zkontroluje soubory smazané z gitu (viz níže).
3. Udělá zálohu databáze z `db-main-ctx` do `backups/dochazka-predeploy-<datum>-<commit>.dump`
   (smaže ji cron po 14 dnech jako ostatní zálohy).
4. Nahraje `origin/main` přes `git archive` (bez `.claude/`, s konci řádků LF) a rozbalí ho přes
   stávající kód; zapíše `REVISION` a vlastníka `evidence` (jen u nahraných souborů — `.env`
   zůstane `root:evidence`).
5. Jako `evidence`: `pip install -r requirements.txt` přes proxy, `migrate --noinput`,
   `collectstatic --noinput`, `check --deploy`.
6. `systemctl reload evidence-prac-doby` a kontrola, že `/prihlaseni/` vrací 200; vypíše nasazenou
   revizi.

Mezi nahráním kódu (krok 4) a reloadem (krok 6) běží staré workery nad novými soubory na disku
— obvykle desítky sekund. Pokud skript skončí chybou v krocích 4–6, je na disku už nový kód,
ale gunicorn může dál běžet se starým: opravte příčinu a spusťte skript znovu, nebo viz Rollback.

`-y` přeskočí potvrzovací otázku (nutné, když skript nemá terminál). SSH alias jde změnit
proměnnou `DEPLOY_SSH_HOST`.

### Soubory smazané z gitu

`tar` jen přepisuje — soubor smazaný nebo přejmenovaný v gitu zůstane na serveru. Skript proto
porovná soubory v `app/` (mimo `.env*`, `REVISION`, `staticfiles/` a `__pycache__/`) s nasazovaným
commitem a nadbytečné vypíše. Většinou nevadí (nikdo je nenačítá), **migrace ale ano** — `migrate`
by ji použil. Když je mezi nadbytečnými soubory migrace, skript skončí ještě před zálohou a
nahráním. Pak je potřeba soubor na serveru smazat ručně (po kontrole, že opravdu v gitu není):

```bash
ssh dochazka-app 'sudo rm -v /srv/evidence-prac-doby/app/<app>/migrations/<soubor>.py'
```

Skript sám na serveru nic nemaže.

## Rollback

**Běžná cesta — oprava dopředu:** chybný PR revertovat (`git revert`, nový PR), sloučit do `main`
a nasadit obvyklým `./deploy.sh`. Migrace se tak řeší normálně dopředu.

**Nouzově — starší commit:** `./deploy.sh --rev <commit>` nasadí libovolný commit z historie
`origin/main` (místní `main` musí být i tak srovnaný s `origin/main`). Kód se vrátí, **databáze
ne**:

- Pokud mezi verzemi nepřibyla žádná migrace, stačí to.
- Pokud přibyla, je potřeba ji nejdřív vrátit, dokud je na serveru ještě nový kód
  (`manage.py migrate <app> <poslední_stará_migrace>`), pak ručně smazat soubor nové migrace
  (skript by jinak skončil kvůli nadbytečné migraci, viz výše) a teprve potom `--rev`.
- Když vrácení migrace nejde (ztrátová změna), obnovit databázi ze zálohy `dochazka-predeploy-…`,
  kterou skript udělal těsně před nasazením (viz níže).

## Zálohy a obnova databáze

Denní záloha ve 2:30 a záloha před každým nasazením jsou v `/srv/evidence-prac-doby/backups`
(`pg_dump -Fc` z `db-main-ctx`, čitelné jen pro `evidence`). Obnova (přepíše data v DB
`dochazka` na `db-main-ctx`, v jedné transakci — při chybě se nezmění nic):

```bash
ssh dochazka-app
sudo systemctl stop evidence-prac-doby
sudo -u evidence -H pg_restore --clean --if-exists --no-owner --no-acl --single-transaction --exit-on-error \
    -h db-main-ctx.mv.cz -U evidence -d dochazka /srv/evidence-prac-doby/backups/<soubor>.dump
sudo systemctl start evidence-prac-doby
```

`--no-acl` vynechá práva, takže po obnově je potřeba znovu dát `dochazka_ro` čtení na tabulky
(`GRANT USAGE …` a dva `GRANT SELECT …` z kapitoly níže, jako `evidence`). Výchozí práva
(`ALTER DEFAULT PRIVILEGES`) obnova nesmaže.

### Původní lokální databáze

Do 19. 10. 2026 běžela databáze lokálně na aplikačním serveru (PostgreSQL 17, peer autentizace).
Přesun: zastavení gunicornu, `pg_dump` lokální DB (`backups/dochazka-premigrace-20261019-090340.dump`),
obnova na `db-main-ctx` jako výše, porovnání počtu řádků všech tabulek a sekvencí, změna
`DB_HOST`/`DB_PORT` v `.env` (záloha `.env.bak-20261019-090444`), start. Lokální cluster 17
běží dál jako záloha, DB `dochazka` v něm je nastavená jen pro čtení
(`ALTER DATABASE dochazka SET default_transaction_read_only = on`); až nebude potřeba, lze ho
zrušit (pak i `After=`/`Wants=postgresql.service` v systemd unitu).

Návrat na lokální DB (data zapsaná mezitím do `db-main-ctx` je potřeba přenést zpět zálohou):
vypnout read-only (`ALTER DATABASE dochazka RESET default_transaction_read_only` jako `postgres`),
vrátit `.env` ze zálohy a `systemctl restart evidence-prac-doby`.

## Přístup k databázi jen pro čtení (JDBC, DBeaver, …)

Pro dotazy a reporty mimo aplikaci je role **`dochazka_ro`**: smí jen číst (SELECT na všechny
tabulky a sekvence ve schématu `public`, i na tabulky z budoucích migrací),
`default_transaction_read_only = on`, nejvýš 5 spojení. Ve schématu `public` nesmí nic
vytvářet (schéma patří `pg_database_owner`, `PUBLIC` má jen `USAGE`), takže ani vypnutí
read-only v sezení jí nedovolí nic založit. `CONNECT` do DB `dochazka` mají jen `evidence` a
`dochazka_ro` (`PUBLIC` ho nemá).

Heslo si nastaví ten, kdo přístup potřebuje (interaktivně, `\password` posílá jen hash), přes
účet s právy na `db-main-ctx` (např. `kittler`):

```bash
ssh -t dochazka-app "psql -h db-main-ctx.mv.cz -U kittler -d dochazka -c '\password dochazka_ro'"
```

Připojení přímo (`pg_hba.conf` na `db-main-ctx` dnes pouští spojení z celé sítě):

```
URL:     jdbc:postgresql://db-main-ctx.mv.cz:5432/dochazka
Driver:  org.postgresql.Driver
User:    dochazka_ro
```

Když přímé spojení z PC nejde (síť, firewall), tunel přes aplikační server:
`ssh -N -L 5433:db-main-ctx.mv.cz:5432 dochazka-app` a pak `jdbc:postgresql://localhost:5433/dochazka`.

Založení role při nové instalaci (jako `kittler` na `db-main-ctx`, v DB `dochazka`, po prvním
`migrate`):

```sql
CREATE ROLE dochazka_ro LOGIN CONNECTION LIMIT 5;
ALTER ROLE dochazka_ro SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE dochazka TO dochazka_ro;
GRANT USAGE ON SCHEMA public TO dochazka_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO dochazka_ro;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO dochazka_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE evidence IN SCHEMA public GRANT SELECT ON TABLES TO dochazka_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE evidence IN SCHEMA public GRANT SELECT ON SEQUENCES TO dochazka_ro;
```

## První instalace od nuly

Postup odpovídající tomu, jak je server zařízený (sestavený zpětně z jeho současného stavu — pro případ přeinstalace nebo druhého serveru). Vše přes SSH
jako `kittler` se `sudo`; proxy je potřeba pro `apt`/`pip`, pokud na serveru není nastavená
globálně.

1. Balíčky: `python3`, `python3-venv`, `nginx`, `curl` a klient PostgreSQL ve verzi serveru
   databáze (dnes `postgresql-client-18` z PGDG — zdroj a pin viz tabulka v Přehledu;
   `apt-get install --no-install-recommends postgresql-client-18 libpq5/trixie-pgdg`). Apache nechat být.
2. Uživatel a adresáře:
   ```bash
   sudo adduser --system --group --home /srv/evidence-prac-doby --shell /usr/sbin/nologin evidence
   sudo install -d -o evidence -g evidence /srv/evidence-prac-doby/app
   sudo install -d -o evidence -g evidence -m 700 /srv/evidence-prac-doby/backups
   sudo install -d -o evidence -g evidence -m 750 /var/log/evidence-prac-doby
   sudo -u evidence python3 -m venv /srv/evidence-prac-doby/venv
   ```
3. Databáze na `db-main-ctx` (jako `kittler`, DB `dochazka` už existuje):
   ```sql
   CREATE ROLE evidence LOGIN;
   ALTER DATABASE dochazka OWNER TO evidence;
   REVOKE CONNECT ON DATABASE dochazka FROM PUBLIC;
   ALTER SCHEMA public OWNER TO pg_database_owner;  -- DB převzatá ze starší verze měla vlastníka postgres
   REVOKE CREATE ON SCHEMA public FROM PUBLIC;
   ```
   Heslo nastaví člověk (`\password evidence`) a sám ho zapíše do `.pgpass` uživatele `evidence`
   (jeden řádek `db-main-ctx.mv.cz:5432:dochazka:evidence:<heslo>`, `:` a `\` v hesle jako `\:`
   a `\\`):
   ```bash
   ssh -t dochazka-app 'sudo -u evidence sh -c "umask 077; nano /srv/evidence-prac-doby/.pgpass"'
   ```
   Pokud PostgreSQL hlásí *collation version mismatch* (DB vytvořená před upgradem systému),
   u prázdné DB stačí `ALTER DATABASE dochazka REFRESH COLLATION VERSION`.
4. Kód: z vývojového počítače
   ```bash
   git -c core.autocrlf=false archive --format=tar origin/main -- . ':(exclude).claude' | ssh dochazka-app 'sudo -n tar -x -C /srv/evidence-prac-doby/app'
   ssh dochazka-app 'sudo chown -R evidence:evidence /srv/evidence-prac-doby/app'
   ```
5. `.env`: vytvořit `/srv/evidence-prac-doby/app/.env` podle `.env.example` a sekce `.env` výše
   (nový `SECRET_KEY`), `sudo chown root:evidence .env && sudo chmod 640 .env`.
6. Závislosti a databáze (v `/srv/evidence-prac-doby/app`):
   ```bash
   sudo -u evidence -H env https_proxy=http://10.254.8.41:3128 http_proxy=http://10.254.8.41:3128 ../venv/bin/pip install -r requirements.txt
   sudo -u evidence ../venv/bin/python manage.py migrate
   sudo -u evidence ../venv/bin/python manage.py collectstatic --noinput
   sudo -u evidence ../venv/bin/python manage.py createsuperuser
   sudo -u evidence ../venv/bin/python manage.py generuj_svatky 2026
   ```
7. systemd unit, nginx site a cron podle sekce Služby výše:
   ```bash
   sudo systemctl daemon-reload && sudo systemctl enable --now evidence-prac-doby
   sudo ln -s /etc/nginx/sites-available/evidence-prac-doby /etc/nginx/sites-enabled/
   sudo nginx -t && sudo systemctl reload nginx
   ```
8. Kontrola: `curl` z kapitoly nginx výše vrací 200 a `http://app.dochazka.mv.cz:8010/` se otevře
   z prohlížeče. Další verze už jen přes `./deploy.sh`.
