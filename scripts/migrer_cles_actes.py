#!/usr/bin/env python3
"""
migrer_cles_actes.py — Pose la clé datée de chaque acte et de chaque séance (03/10/2026).

La collecte écrit `events.cle_acte` depuis le 03/10/2026 (`collectors/cle_acte.py`).
Les lignes collectées avant n'en ont pas : ce script la calcule pour elles, avec
la MÊME fonction, et la pose. Rejouable : une clé déjà juste n'est pas réécrite.

Ce qu'il ne fait PAS : départager deux lignes qui reçoivent la même clé. Une
collision dit soit que la même délibération a deux fiches (un rejeu passé à
côté du dédoublonnage), soit que deux actes distincts ne se distinguent par
rien de ce que la collecte a lu. Dans les deux cas, choisir à la place de
quelqu'un effacerait un acte ou en fusionnerait deux. Les lignes en collision
sont donc LISTÉES et laissées sans clé : la collecte retombe pour elles sur
son ancienne recherche, et le site garde leur ancre `#a{id}`.

À blanc par défaut : il dit ce qu'il poserait, et les collisions.

Usage :
  venv/bin/python scripts/migrer_cles_actes.py              # à blanc
  venv/bin/python scripts/migrer_cles_actes.py --appliquer
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collectors.cle_acte import (TYPES_ACTES, TYPES_SEANCES,  # noqa: E402
                                 a_la_colonne, assurer_colonne, cle_de_ligne)


def calculer(conn) -> dict:
    """{a_poser: [(id, cle)], collisions: {cle: [lignes]}, faibles, sans_cle}.

    Aucune écriture : c'est aussi ce que rend la version à blanc.
    """
    types = TYPES_ACTES + TYPES_SEANCES
    marques = ",".join("?" for _ in types)
    actuelle = "cle_acte" if a_la_colonne(conn) else "NULL AS cle_acte"
    par_cle: dict[str, list[dict]] = defaultdict(list)
    sans_cle, faibles = [], Counter()
    for eid, type_, date, titre, meta, deja in conn.execute(
            f"SELECT id, type, date, title, metadata, {actuelle} FROM events "
            f"WHERE type IN ({marques}) ORDER BY id", types):
        try:
            metadata = json.loads(meta or "{}")
        except json.JSONDecodeError:
            metadata = {}
        cle = cle_de_ligne(type_, date, metadata, titre)
        if cle is None:
            sans_cle.append({"id": eid, "type": type_, "date": date})
            continue
        if cle.faible:
            faibles[type_] += 1
        par_cle[cle.valeur].append({"id": eid, "type": type_, "date": date,
                                    "titre": (titre or "")[:90], "deja": deja})
    collisions = {c: l for c, l in par_cle.items() if len(l) > 1}
    a_poser = [(l[0]["id"], c) for c, l in par_cle.items()
               if len(l) == 1 and l[0]["deja"] != c]
    # Une ligne qui porte DÉJÀ une clé et entre maintenant en collision (une
    # seconde fiche est apparue depuis) perd sa clé : la garder ferait choisir
    # la collecte entre deux fiches sur un ordre d'identifiants.
    a_vider = [ligne["id"] for l in collisions.values() for ligne in l if ligne["deja"]]
    return {"a_poser": a_poser, "a_vider": a_vider, "collisions": collisions,
            "faibles": dict(faibles), "sans_cle": sans_cle,
            "total": sum(len(l) for l in par_cle.values()) + len(sans_cle)}


def appliquer(conn, bilan: dict) -> None:
    assurer_colonne(conn)
    conn.executemany("UPDATE events SET cle_acte=? WHERE id=?",
                     [(c, i) for i, c in bilan["a_poser"]])
    conn.executemany("UPDATE events SET cle_acte=NULL WHERE id=?",
                     [(i,) for i in bilan["a_vider"]])
    conn.commit()


def rapport(bilan: dict, applique: bool) -> None:
    verbe = "posées" if applique else "à poser"
    print(f"[cles] {bilan['total']} actes et séances examinés")
    print(f"   {len(bilan['a_poser']):6}  clés {verbe}")
    for type_, n in sorted(bilan["faibles"].items()):
        print(f"   {n:6}  clés FAIBLES ({type_}) : ni numéro d'acte ni numéro de "
              f"séance, le titre fait l'identité")
    if bilan["sans_cle"]:
        print(f"   {len(bilan['sans_cle']):6}  sans clé possible (pas de date)")
    if not bilan["collisions"]:
        print("   aucune collision")
        return
    n = sum(len(l) for l in bilan["collisions"].values())
    print(f"\n[cles] {len(bilan['collisions'])} COLLISIONS, {n} lignes laissées sans clé :")
    for cle, lignes in sorted(bilan["collisions"].items()):
        print(f"   {cle}")
        for l in lignes:
            print(f"      #{l['id']:<7} {l['date'] or '—':10}  {l['titre']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--appliquer", action="store_true",
                    help="écrire les clés (par défaut : à blanc)")
    args = ap.parse_args()
    from collectors.db import get_conn
    conn = get_conn()
    try:
        bilan = calculer(conn)
        if args.appliquer:
            appliquer(conn, bilan)
        rapport(bilan, args.appliquer)
        if not args.appliquer:
            print("\n(à blanc — rien n'est écrit ; --appliquer pour poser les clés)")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
