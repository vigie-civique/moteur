#!/usr/bin/env python3
"""Redonne leur date aux recueils des actes administratifs déjà collectés.

`_date_from_name` ne cherchait la date que dans le NOM du fichier, sous la forme
`du 05 01 2026`. C'est l'habitude du Gard ; ce n'est pas une règle. La Drôme
numérote ses recueils sans les dater — les 79 lus le 24/08/2026 sont entrés avec
`date_doc` vide, et les 16 événements qui en sont nés sont sans date. Le Gard
lui-même en perdait trois, pour un « DU » en majuscules.

`collectors.raa_prefecture.date_du_recueil` lit désormais la couverture en repli
(« PUBLIÉ LE 16 JANVIER 2026 »). Ce script applique la même règle à l'existant,
**sans rien retélécharger** : les recueils qui ont produit un événement sont
archivés dans `data/raw/prefecture-<dep>/`, et il suffit d'en relire la première
page.

    python3 scripts/redater_raa.py                 # simulation
    python3 scripts/redater_raa.py --appliquer

Sur une autre instance que le dépôt courant :

    VIGIE_INSTANCE=~/Claude/Saillans/config/instance.json \\
    VIGIE_DB=~/Claude/Saillans/db/26289.db \\
    python3 scripts/redater_raa.py --appliquer

Idempotent : une ligne déjà datée n'est pas relue. Ce script ne DÉDUIT rien —
il lit ce que la pièce affirme, et laisse sans date ce qui n'en porte pas.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collectors.config import DB_PATH, ROOT  # noqa: E402
from collectors.db import get_conn  # noqa: E402
from collectors.raa_prefecture import date_du_recueil, extract_pages  # noqa: E402


def chemin_archive(local_path: str) -> Path | None:
    """Le fichier archivé, cherché d'abord dans l'instance, puis dans le dépôt.

    `raw_documents.local_path` est relatif à la racine de l'instance qui a
    collecté. Lancé avec `VIGIE_DB`, ce script travaille sur une instance qui
    n'est pas le dépôt courant : c'est la base qui dit où chercher.
    """
    for racine in (DB_PATH.resolve().parent.parent, ROOT):
        chemin = racine / local_path
        if chemin.exists():
            return chemin
    return None


def lignes_a_redater(conn) -> list[dict]:
    """Les recueils sans date qui ont un fichier archivé.

    Jointure sur l'URL : c'est la clé que `raa_scans` et `raw_documents`
    partagent, et le seul lien sûr entre un scan et sa pièce.
    """
    return [dict(r) for r in conn.execute("""
        SELECT s.url, s.filename, d.local_path
        FROM raa_scans s
        JOIN raw_documents d ON d.url = s.url
        WHERE (s.date_doc IS NULL OR s.date_doc = '')
        ORDER BY s.filename
    """)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--appliquer", action="store_true",
                    help="écrit en base (sans l'option : simulation)")
    args = ap.parse_args()

    conn = get_conn()
    conn.row_factory = __import__("sqlite3").Row
    lignes = lignes_a_redater(conn)
    if not lignes:
        print("Aucun recueil sans date parmi les pièces archivées.")
        return 0

    print(f"{len(lignes)} recueil(s) sans date, archivés — relecture de la "
          f"couverture\n")
    dates, absents, muets = {}, 0, 0
    for ligne in lignes:
        chemin = chemin_archive(ligne["local_path"])
        if chemin is None:
            print(f"  ✖ fichier absent : {ligne['local_path']}")
            absents += 1
            continue
        date = date_du_recueil(ligne["filename"], extract_pages(chemin.read_bytes()))
        if not date:
            print(f"  — sans date lisible : {ligne['filename']}")
            muets += 1
            continue
        dates[ligne["url"]] = date
        print(f"  {date}  {ligne['filename']}")

    print(f"\n{len(dates)} datés, {muets} muets, {absents} fichiers absents")
    if not args.appliquer:
        print("\n[simulation] rien écrit — relancer avec --appliquer")
        return 0

    with conn:
        for url, date in dates.items():
            conn.execute("UPDATE raa_scans SET date_doc=? WHERE url=?", (date, url))
            conn.execute(
                "UPDATE events SET date=? WHERE type='raa_prefecture'"
                " AND source_url=? AND (date IS NULL OR date='')", (date, url))
    evenements = conn.execute(
        "SELECT COUNT(*) FROM events WHERE type='raa_prefecture'"
        " AND (date IS NULL OR date='')").fetchone()[0]
    print(f"✓ {len(dates)} recueil(s) datés. Événements RAA encore sans date : "
          f"{evenements}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
