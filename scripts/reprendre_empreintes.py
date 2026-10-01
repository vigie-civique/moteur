#!/usr/bin/env python3
"""Reprise du 01/10/2026 : l'empreinte des textes relus, et le verdict des dossiers.

    cd <instance>
    python3 scripts/reprendre_empreintes.py              # à blanc : dit ce qu'il ferait
    python3 scripts/reprendre_empreintes.py --appliquer

À jouer UNE fois par instance, au passage au moteur qui exige l'empreinte
(`collectors/verdict.py::publiable_tel_quel`). Sans elle, plus rien de rédigé
ne sort : une feuille retenue sans empreinte n'est pas publiée.

Deux reprises :

1. Feuilles « en clair » déjà RETENUES. L'empreinte n'est posée que si le
   relevé n'a pas changé depuis la relecture (date du fichier ≤ date du
   verdict). Un relevé modifié APRÈS reste sans empreinte : il attend d'être
   retenu de nouveau, et ce script le nomme.

2. Dossiers. Ceux dont l'en-tête dit `statut: publie` (ou `a_developper`) et
   qui n'ont aucun verdict sont RETENUS d'office, sur leur texte d'aujourd'hui —
   décision de Julien le 01/10/2026 : ils étaient en ligne, il les avait
   validés. Les autres restent sans verdict, donc hors du site.

Ce script ne sert qu'à cette transition. Le rejouer plus tard ne retiendrait
rien de neuf sans qu'on le voie : il n'agit que sur des objets SANS verdict ou
sans empreinte, et il imprime chacun.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from collectors import dossiers as D  # noqa: E402
from collectors.config import DB_PATH  # noqa: E402
from collectors.en_clair.seances import releves, seance_id  # noqa: E402
from collectors.verdict import RETENU, empreinte, verdict_de  # noqa: E402

AUTEUR = "reprise du 01/10/2026"


def _date_utc(chemin: Path) -> str:
    return datetime.fromtimestamp(chemin.stat().st_mtime, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def reprendre(conn, racine: Path, appliquer: bool) -> dict:
    D.assurer_schema(conn)
    bilan = {"en_clair_poses": [], "en_clair_a_relire": [], "dossiers_retenus": [],
             "dossiers_sans_verdict": []}

    for chemin, r in releves(racine):
        sid = seance_id(conn, r)
        if sid is None:
            continue
        a = conn.execute("SELECT review_status, reviewed_at, empreinte FROM annotations "
                         "WHERE object_type='en_clair' AND object_id=?", (sid,)).fetchone()
        if not a or verdict_de(a[0]) != RETENU or a[2]:
            continue
        nom = chemin.parent.name
        if _date_utc(chemin) > (a[1] or ""):
            bilan["en_clair_a_relire"].append(nom)
            continue
        bilan["en_clair_poses"].append(nom)
        if appliquer:
            conn.execute("UPDATE annotations SET empreinte=? WHERE object_type='en_clair' "
                         "AND object_id=?", (empreinte(chemin.read_bytes()), sid))

    for slug, p in D.lister(racine):
        did = D.identifiant(conn, slug, creer=appliquer)
        if did is not None and D.verdict(conn, did):
            continue
        meta, _ = D.entete(p.read_text(encoding="utf-8"))
        if meta.get("statut") not in ("publie", "a_developper"):
            bilan["dossiers_sans_verdict"].append(slug)
            continue
        bilan["dossiers_retenus"].append(slug)
        if appliquer:
            conn.execute(
                "INSERT INTO annotations(object_type, object_id, review_status, note, "
                "reviewed_by, reviewed_at, updated_at, empreinte) "
                "VALUES('dossier', ?, ?, ?, ?, datetime('now'), datetime('now'), ?)",
                (did, RETENU, f"Retenu d'office : en ligne avec « statut: {meta['statut']} » "
                 "au passage à la relecture obligatoire.", AUTEUR, D.empreinte_de(p)))
            conn.execute("INSERT INTO audit_log(user_id, table_name, action, field, new_value) "
                         "VALUES(NULL, 'annotations', 'annotate', ?, ?)",
                         (f"dossier/{did}", RETENU))
    if appliquer:
        conn.commit()
    return bilan


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--appliquer", action="store_true", help="écrire (sinon : à blanc)")
    args = ap.parse_args()
    conn = sqlite3.connect(DB_PATH)
    try:
        b = reprendre(conn, ROOT, args.appliquer)
    finally:
        conn.close()
    mode = "" if args.appliquer else " (à blanc)"
    print(f"Reprise des empreintes — {ROOT.name}{mode}")
    print(f"  feuilles « en clair » : empreinte posée sur {len(b['en_clair_poses'])}")
    for n in b["en_clair_a_relire"]:
        print(f"    ⚠ {n} : relevé modifié après la relecture — à retenir de nouveau")
    print(f"  dossiers retenus d'office : {', '.join(b['dossiers_retenus']) or 'aucun'}")
    if b["dossiers_sans_verdict"]:
        print(f"  dossiers sans verdict (hors du site jusqu'à relecture) : "
              f"{', '.join(b['dossiers_sans_verdict'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
