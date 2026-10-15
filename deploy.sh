#!/usr/bin/env bash
# Nasazení aplikace na produkční server (app.dochazka.mv.cz) z vývojového počítače.
# Popis serveru, první instalace a rollback: DEPLOY.md.
#
# Použití (Git Bash, z kořene repozitáře):
#   ./deploy.sh              nasadí origin/main (před změnou na serveru se zeptá)
#   ./deploy.sh --check      jen kontroly a přehled, na serveru nic nemění
#   ./deploy.sh -y           bez potvrzovací otázky
#   ./deploy.sh --rev <sha>  nasadí starší commit z historie origin/main (nouzový rollback)
#
# Zastaví se na první chybě. Na serveru nic nemaže — jen přepíše soubory, které jsou
# v nahrávaném commitu (soubory smazané z gitu tam zůstanou — skript je vypíše, viz DEPLOY.md).

set -euo pipefail

SSH_HOST="${DEPLOY_SSH_HOST:-dochazka-app}"
ROOT=/srv/evidence-prac-doby
APP=$ROOT/app
VENV=$ROOT/venv
BACKUPS=$ROOT/backups
SERVICE=evidence-prac-doby
APP_USER=evidence
DB_NAME=dochazka
PROXY=http://10.254.8.41:3128
HEALTH_URL=http://127.0.0.1:8010/prihlaseni/
HEALTH_HOST=app.dochazka.mv.cz
# Adresář z gitu, který se na server nenahrává (git archive / status: pathspec, ls-tree: grep).
EXCLUDE_DIR=.claude
EXCLUDE=":(exclude)$EXCLUDE_DIR"

SSH=(ssh -T -o BatchMode=yes -o ConnectTimeout=15 "$SSH_HOST")

info() { printf '\n==> %s\n' "$*"; }
warn() { printf 'POZOR: %s\n' "$*" >&2; }
die() { printf 'CHYBA: %s\n' "$*" >&2; exit 1; }

usage() { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; }

# Soubory (-r) nebo položky nejvyšší úrovně revize $1 bez $EXCLUDE_DIR (ls-tree neumí :(exclude)).
git_paths() { git ls-tree "$@" --name-only | grep -v -e "^$EXCLUDE_DIR/" -e "^$EXCLUDE_DIR\$" || true; }

ASSUME_YES=0
CHECK_ONLY=0
REV_ARG=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        -y|--yes) ASSUME_YES=1 ;;
        --check) CHECK_ONLY=1 ;;
        --rev) [[ $# -ge 2 ]] || die "--rev potřebuje commit"; REV_ARG=$2; shift ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; die "neznámý parametr: $1" ;;
    esac
    shift
done

cd "$(git rev-parse --show-toplevel)"

# --- 1. Místní kontroly -----------------------------------------------------------

info "Kontrola místního repozitáře"
git fetch --quiet origin

# .claude/ se nenahrává a mění ho i Claude Code, proto ji kontrola čistoty přeskakuje.
dirty=$(git status --porcelain -- . "$EXCLUDE")
if [[ -n "$dirty" ]]; then
    printf '%s\n' "$dirty" >&2
    die "pracovní strom není čistý — commitněte nebo zahoďte změny"
fi

local_main=$(git rev-parse --verify --quiet refs/heads/main) || die "chybí místní větev main"
remote_main=$(git rev-parse --verify origin/main)
[[ "$local_main" == "$remote_main" ]] \
    || die "místní main ($(git rev-parse --short "$local_main")) se liší od origin/main ($(git rev-parse --short "$remote_main")) — srovnejte je (git pull / git push)"

if [[ -n "$REV_ARG" ]]; then
    REV=$(git rev-parse --verify --quiet "$REV_ARG^{commit}") || die "neznámý commit: $REV_ARG"
    git merge-base --is-ancestor "$REV" origin/main || die "$REV_ARG není v historii origin/main"
else
    REV=$remote_main
fi
SHORT=$(git rev-parse --short=7 "$REV")

# --- 2. Kontroly na serveru (jen čtení) -------------------------------------------

info "Kontrola serveru $SSH_HOST"
"${SSH[@]}" "set -e
    sudo -n true || { echo 'sudo -n nefunguje' >&2; exit 1; }
    for d in $APP $VENV $BACKUPS; do [ -d \"\$d\" ] || { echo \"chybí \$d\" >&2; exit 1; }; done
    sudo -n test -f $APP/.env || { echo 'chybí $APP/.env' >&2; exit 1; }
    systemctl is-active --quiet $SERVICE || { echo 'služba $SERVICE neběží' >&2; exit 1; }" \
    || die "server neodpovídá očekávanému stavu (viz výše)"

deployed=$("${SSH[@]}" "cat $APP/REVISION 2>/dev/null || true")
deployed=${deployed//$'\r'/}
printf 'Na serveru:  %s\n' "${deployed:-(neznámá revize)}"
printf 'K nasazení:  %s  %s\n' "$SHORT" "$(git log -1 --format=%s "$REV")"
if [[ -n "$deployed" ]] && git cat-file -e "$deployed^{commit}" 2>/dev/null; then
    if [[ "$(git rev-parse "$deployed")" == "$REV" ]]; then
        echo "Tato revize už na serveru je — proběhne znovu (pip, migrate, collectstatic, reload)."
    elif git merge-base --is-ancestor "$deployed" "$REV"; then
        echo "Nové commity:"
        git log --oneline "$deployed..$REV" | sed 's/^/  /'
    else
        warn "nasazovaná revize není novější než ta na serveru (rollback?)"
    fi
fi

# Soubory na serveru, které v nasazované revizi nejsou (smazané nebo přejmenované v gitu).
# tar je nesmaže; staré migrace by ale migrate použil, proto u nich skript skončí.
# Mimo git jsou na serveru jen .env, jeho zálohy, REVISION, staticfiles/ a __pycache__/.
server_files=$("${SSH[@]}" "cd $APP && sudo -n find . \\( -path ./staticfiles -o -name __pycache__ \\) -prune \
    -o -type f ! -name .env ! -name '.env.bak*' ! -name REVISION -print" | sed -e 's/\r$//' -e 's|^\./||' | LC_ALL=C sort)
git_files=$(git_paths -r "$REV" | LC_ALL=C sort)
stale=$(LC_ALL=C comm -23 <(printf '%s\n' "$server_files") <(printf '%s\n' "$git_files") | sed '/^$/d')
if [[ -n "$stale" ]]; then
    warn "na serveru zůstaly soubory, které v $SHORT nejsou (skript je nemaže):"
    printf '%s\n' "$stale" | sed 's/^/  /' >&2
    stale_migrations=$(printf '%s\n' "$stale" | grep -E '/migrations/[^/]+\.py$' || true)
    if [[ -n "$stale_migrations" ]]; then
        die "mezi nimi jsou migrace — migrate by je použil. Postup je v DEPLOY.md (Soubory smazané z gitu)."
    fi
fi

if [[ $CHECK_ONLY -eq 1 ]]; then
    info "Jen kontrola (--check): na serveru se nic nezměnilo"
    exit 0
fi

if [[ $ASSUME_YES -eq 0 ]]; then
    [[ -t 0 ]] || die "není terminál pro potvrzení — spusťte s -y"
    read -r -p "Nasadit $SHORT na $SSH_HOST? [a/N] " answer
    [[ "$answer" == [aAyY] ]] || die "zrušeno"
fi

trap 'warn "nasazení selhalo — kód na serveru může být jen zčásti aktualizovaný. Opravte příčinu a spusťte skript znovu, případně viz Rollback v DEPLOY.md."' ERR

# --- 3. Nasazení ------------------------------------------------------------------

stamp=$(date +%Y%m%d-%H%M%S)
backup="$BACKUPS/dochazka-predeploy-$stamp-$SHORT.dump"
info "Záloha databáze → $backup"
"${SSH[@]}" "sudo -n -u $APP_USER sh -c 'cd $BACKUPS && pg_dump -Fc $DB_NAME > $backup || { rm -f $backup; exit 1; }'"

info "Nahrání $SHORT (git archive → tar)"
# core.autocrlf=false: na server jdou soubory s LF, ne s CRLF z Windows checkoutu.
git -c core.autocrlf=false archive --format=tar "$REV" -- . "$EXCLUDE" \
    | "${SSH[@]}" "sudo -n tar -x --no-same-owner -C $APP"

# Položky nejvyšší úrovně z archivu — chown jen na ně, ať se nesáhne na .env (root:evidence 640).
mapfile -t ENTRIES < <(git_paths "$REV")

{
    declare -p APP VENV SERVICE APP_USER PROXY HEALTH_URL HEALTH_HOST SHORT ENTRIES
    cat <<'REMOTE'
# Celý skript je ve funkci: bash -s ho tak načte celý dřív, než cokoli spustí,
# a žádný příkaz (pip, sudo, manage.py) nemůže ze stdin sníst zbytek skriptu.
main() {
set -euo pipefail
cd "$APP"
as_app() { sudo -n -u "$APP_USER" -H env PYTHONIOENCODING=utf-8 "$@"; }

echo; echo "==> REVISION = $SHORT, vlastník $APP_USER"
printf '%s\n' "$SHORT" | sudo -n tee REVISION >/dev/null
sudo -n chown -R "$APP_USER:$APP_USER" -- "${ENTRIES[@]}" REVISION

echo; echo "==> pip install -r requirements.txt"
as_app https_proxy="$PROXY" http_proxy="$PROXY" "$VENV/bin/pip" install \
    --disable-pip-version-check --progress-bar off -r requirements.txt

echo; echo "==> migrate"
as_app "$VENV/bin/python" manage.py migrate --noinput

echo; echo "==> collectstatic"
as_app "$VENV/bin/python" manage.py collectstatic --noinput

echo; echo "==> check --deploy"
as_app "$VENV/bin/python" manage.py check --deploy

echo; echo "==> reload $SERVICE"
sudo -n systemctl reload "$SERVICE"

echo; echo "==> kontrola $HEALTH_URL"
code=000
for _ in $(seq 1 15); do
    sleep 2
    code=$(curl -s -o /dev/null -m 10 -w '%{http_code}' -H "Host: $HEALTH_HOST" "$HEALTH_URL" || true)
    [ "$code" = 200 ] && break
done
systemctl is-active --quiet "$SERVICE" || { echo "služba $SERVICE po reloadu neběží" >&2; exit 1; }
[ "$code" = 200 ] || { echo "$HEALTH_URL vrací $code místo 200" >&2; exit 1; }
echo "HTTP $code"
echo "Nasazená revize: $(cat REVISION)"
}
main </dev/null
REMOTE
} | "${SSH[@]}" 'bash -s'

trap - ERR
info "Hotovo: $SHORT je nasazeno na $SSH_HOST (http://$HEALTH_HOST:8010/)"
