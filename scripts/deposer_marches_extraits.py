#!/usr/bin/env python3
"""Dépose un rapport de marchés extraits des procès-verbaux, depuis le serveur.

Le même dépôt que l'atelier (`POST /api/atelier/marches-extraits`), pour qui
travaille en ligne de commande sur la machine de l'instance : chaque ligne dont
la citation se lit dans son acte devient une PROPOSITION, relue ensuite une à
une dans l'atelier (/atelier/propositions?nature=marche). Rien n'est publié.

    python3 scripts/deposer_marches_extraits.py rapport.json --compte vous@exemple.fr
    python3 scripts/deposer_marches_extraits.py rapport.json --compte … --simulation

Le compte doit être validateur : le dépôt fait entrer des dizaines de lignes
dans la file que les validateurs relisent. Format : docs/format-marches-extraits.md.
Rejouer le même rapport ne propose rien de plus.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collectors import marches_extraits as mx  # noqa: E402
from collectors.db import get_conn  # noqa: E402

ROLES_VALIDATEURS = ("validator", "admin")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rapport", type=Path)
    ap.add_argument("--compte", required=True, help="courriel d'un compte validateur")
    ap.add_argument("--simulation", action="store_true",
                    help="dit ce qui serait proposé, sans rien écrire")
    args = ap.parse_args()

    try:
        octets = args.rapport.read_bytes()
        rapport = json.loads(octets.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        print(f"✖ rapport illisible : {e}", file=sys.stderr)
        return 1

    conn = get_conn()
    try:
        compte = conn.execute("SELECT id, email, role, desactive_le FROM users "
                              "WHERE email=?", (args.compte.strip().lower(),)).fetchone()
        if not compte or compte["role"] not in ROLES_VALIDATEURS or compte["desactive_le"]:
            print(f"✖ {args.compte} n'est pas un compte validateur actif.", file=sys.stderr)
            return 1
        auteur = {"id": compte["id"], "email": compte["email"]}
        # La même forme que l'atelier (`POST /api/atelier/marches-extraits`) :
        # un même rapport porte la même empreinte, par où qu'il entre.
        octets = json.dumps(rapport, ensure_ascii=False, sort_keys=True).encode()
        empreinte = mx.empreinte(octets)[:16]
        try:
            bilan = mx.deposer(conn, rapport, auteur, empreinte)
        except mx.RapportRefuse as e:
            print(f"✖ {e}", file=sys.stderr)
            return 1
        if args.simulation:
            conn.rollback()
        else:
            # Comme l'atelier : le dépôt au journal, le rapport archivé.
            mx.journaliser(conn, auteur, empreinte, bilan)
            conn.commit()
            mx.archiver(octets)
    finally:
        conn.close()

    print(f"{bilan['lignes']} ligne(s) lue(s) : {bilan['proposees']} proposée(s) "
          f"{dict(sorted(bilan['par_portee'].items()))}, {bilan['deja_proposees']} déjà "
          f"proposée(s), {bilan['deja_importees']} déjà en base, "
          f"{len(bilan['refusees'])} refusée(s).")
    for r in bilan["refusees"]:
        print(f"  ligne {r['ligne']} : {r['motif']}")
    if bilan["cles_ignorees"]:
        print(f"  colonnes ignorées : {', '.join(bilan['cles_ignorees'])}")
    if args.simulation:
        print("Simulation : rien n'a été écrit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
