#!/usr/bin/env python3
"""Rattache aux actes les bénéficiaires que leurs flux désignent déjà.

Un flux financier porte `event_id` (la délibération qui l'a voté) et `to_id`
(qui l'a reçu). Le lien entre les deux existe donc en base — mais il n'était
jamais inscrit dans `event_entities`, la table que lit « cités dans un acte ».

Conséquence, mesurée sur Lasalle : **aucune association** n'apparaissait comme
citée dans un acte. Pas une sur quarante-quatre bénéficiaires de subventions
communales. Le rôle `sujet` n'est posé que par le BODACC (entreprises),
l'urbanisme (demandeurs), les commissions et les élections ; rien ne couvrait
la vie associative, qui est pourtant le premier objet des délibérations d'une
petite commune.

Le point d'écriture est corrigé (`collectors/cm_finances.py`). Ce script répare
les bases déjà collectées, sans attendre une recollecte complète.

    python3 scripts/relier_beneficiaires.py            # ce qui serait fait
    python3 scripts/relier_beneficiaires.py --appliquer
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collectors.config import DB_PATH  # noqa: E402

REQUETE = """
    SELECT f.event_id, f.to_id, e.name, e.type, COUNT(*) AS flux,
           SUM(f.amount) AS total
    FROM financial_flows f
    JOIN entities e ON e.id = f.to_id
    WHERE f.event_id IS NOT NULL
      AND f.to_id IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM event_entities ee
                      WHERE ee.event_id = f.event_id AND ee.entity_id = f.to_id)
    GROUP BY f.event_id, f.to_id
    ORDER BY e.type, e.name
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--appliquer", action="store_true")
    ap.add_argument("--db", default=str(DB_PATH))
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    manquants = conn.execute(REQUETE).fetchall()
    if not manquants:
        print("Rien à relier : tout bénéficiaire d'un flux est déjà cité dans son acte.")
        return 0

    par_type: dict[str, set[str]] = {}
    for r in manquants:
        par_type.setdefault(r["type"], set()).add(r["name"])
    print(f"{len(manquants)} lien(s) à poser, "
          f"{sum(len(v) for v in par_type.values())} entité(s) concernée(s) :")
    for t, noms in sorted(par_type.items()):
        exemples = ", ".join(sorted(noms)[:3])
        print(f"  {t:12} {len(noms):3} — {exemples}"
              f"{'…' if len(noms) > 3 else ''}")

    if not args.appliquer:
        print("\n(relancer avec --appliquer pour écrire)")
        return 0

    with conn:
        conn.executemany(
            "INSERT OR IGNORE INTO event_entities (event_id, entity_id, role)"
            " VALUES (?,?,'bénéficiaire')",
            [(r["event_id"], r["to_id"]) for r in manquants])
    reste = len(conn.execute(REQUETE).fetchall())
    print(f"\n{len(manquants)} lien(s) posé(s). Reste à relier : {reste}.")
    print("Enchaîner `--step perimetre` : un lien nouveau ne classe pas l'entité.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
