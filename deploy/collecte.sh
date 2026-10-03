#!/bin/bash
# La passe de collecte d'une instance hébergée sur un serveur, puis sa
# republication si elle a trouvé du neuf. Lancée par `deploy/collecte.timer`.
#
# Le pendant, sur serveur, de la passe quotidienne qu'un poste de travail lance
# par launchd ou cron — mêmes trois temps, même règle de publication :
#
#   1. les sources PÉRIMÉES seulement (`scripts/collect_loop.py`, qui lit la
#      cadence de chaque collecteur dans `collector_runs`), jusqu'à stabilité ;
#   2. ce que la passe a ajouté, compté dans `collector_runs` ;
#   3. s'il y a du neuf : aperçu, contrôle d'étanchéité, promotion, build, mise
#      en ligne, constat — `deploy/publier-site.sh --deployer`, le même chemin
#      que le bouton de l'atelier. Une violation du contrôle arrête tout : une
#      passe automatique publie sans relecture, la garde reste devant la porte.
#
#   VIGIE_SANS_PUBLIER=1 deploy/collecte.sh     # collecter sans publier
#
# Les collecteurs ne joignent que l'internet public (`collectors/reseau.py`,
# posé par `collect_loop.py`) : un serveur porte d'autres services sur sa boucle
# locale.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY=${PY:-$ROOT/venv/bin/python3}
[ -x "$PY" ] || PY="$(command -v python3)"

echo "════ $(basename "$ROOT") — $(date '+%Y-%m-%d %H:%M %Z')"

# Repère en heure de la base (UTC, comme `datetime('now')`) : ce qui est ajouté
# APRÈS lui décide de la republication.
depart="$("$PY" -c "import datetime;print(datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%d %H:%M:%S'))")"

echo "1/3 — Sources périmées"
statut=0
"$PY" scripts/collect_loop.py --run --loop || statut=$?
[ "$statut" -eq 0 ] || echo "   ⚠ au moins un collecteur en échec (détail ci-dessus)"

echo "2/3 — Ce que la passe a ajouté"
ajouts="$("$PY" - "$depart" <<'PY'
import sys, pathlib
sys.path.insert(0, str(pathlib.Path.cwd()))
from collectors.db import get_conn
conn = get_conn()
lignes = conn.execute(
    "SELECT collector, items_added FROM collector_runs"
    " WHERE finished_at >= ? AND COALESCE(items_added,0) > 0"
    " ORDER BY items_added DESC", (sys.argv[1],)).fetchall()
for r in lignes:
    print(f"   + {r['items_added']:>5}  {r['collector']}", file=sys.stderr)
print(sum(r["items_added"] for r in lignes))
PY
)"
echo "   total : ${ajouts:-0} élément(s) neufs"

if [ "${VIGIE_SANS_PUBLIER:-0}" = "1" ]; then
    echo "3/3 — Publication passée (VIGIE_SANS_PUBLIER=1)"
elif [ "${ajouts:-0}" -eq 0 ]; then
    echo "3/3 — Rien de neuf : pas de republication."
else
    echo "3/3 — Aperçu, contrôle, promotion, build, mise en ligne, constat"
    PY="$PY" deploy/publier-site.sh --deployer || {
        echo "   ✖ publication interrompue — le site sert toujours sa version précédente"
        exit 1
    }
fi
exit "$statut"
