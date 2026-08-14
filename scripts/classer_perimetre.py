#!/usr/bin/env python3
"""
classer_perimetre.py — Renseigne `entities.perimetre` (C1 / C2 / C3 / lien / hors).

Sans ce classement, aucune entité n'est publiable : `publiable_dans_perimetre()`
refuse les valeurs NULL, et `build_public_snapshot` s'arrête net si la base n'a
jamais été classée. Le défaut inverse — NULL traité comme C1 — a tenu jusqu'au
14/08/2026 et publiait l'intercommunalité entière à la place de la commune.

Ce classement se périme : il dérive de `entities.commune` et des relations, que
chaque collecte modifie. Il est donc rejoué en fin de `run_all` (step
`perimetre`) et n'a pas à être lancé à la main dans le cours normal.

Le classement suit la définition de `collectors/config.PERIMETRES` :

  C1    l'entité est rattachée à la commune de collecte ;
  C2    elle est rattachée à une autre commune membre de l'EPCI, ou c'est
        l'EPCI lui-même / un syndicat auquel la commune adhère ;
  C3    autorité supra-communale (préfecture, département, région, État) ;
  lien  hors du territoire, mais reliée à un acteur C1 ou C2 par une relation,
        un marché ou un flux financier — le matériau du graphe d'influence ;
  hors  ni l'un ni l'autre.

Le rattachement se lit dans `entities.commune`, écrite par les collecteurs.
Une entité sans commune n'est pas devinée : elle tombe en `lien` si quelque
chose la relie au périmètre, en `hors` sinon.

Usage :
  venv/bin/python scripts/classer_perimetre.py --dry-run
  venv/bin/python scripts/classer_perimetre.py
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collectors.config import (COMMUNE_NAME, COMMUNES, COMMUNES_DELEGUEES,
                               EPCI_NOM, RELATIONS_ADHESION)
from collectors.db import get_conn

# Marqueurs d'une autorité supra-communale, cherchés dans le nom de l'entité.
SUPRA = ("préfecture", "prefecture", "sous-préfecture", "département", "departement",
         "conseil départemental", "conseil régional", "région occitanie",
         "état français", "etat français", "agence de l'eau", "ademe", "dreal",
         "ars ", "rectorat", "direction départementale", "trésorerie", "dgfip")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    for ch in "-'’":
        s = s.replace(ch, " ")
    return " ".join(s.lower().split())


# Les marqueurs sont comparés à un nom NORMALISÉ (sans accents, tirets défaits).
# Écrits accentués et comparés à du texte désaccentué, « état français » et
# « département » ne pouvaient jamais correspondre : l'État tombait en `lien`
# faute de mieux, et une préfecture écrite « Préfecture » aussi.
# L'espace final de « ars » est un délimiteur : sans lui, le marqueur attrape
# « Parsons » et « Mars ». `_norm` le mange, on le remet.
SUPRA = tuple(_norm(m) + (" " if m.endswith(" ") else "") for m in SUPRA)

_C1 = {_norm(COMMUNE_NAME)}
_C2_COMMUNES = {_norm(c["nom"]) for c in COMMUNES.values()} - _C1
_C2_COMMUNES |= {_norm(c["nom"]) for c in COMMUNES_DELEGUEES.values()}
_EPCI = _norm(EPCI_NOM)
# Le nom de l'EPCI sans son préfixe de forme juridique : les sources écrivent
# « CC Untel », « Communauté de communes Untel » ou « CC UNTEL » pour la même
# institution.
_EPCI_COURT = _norm(re.sub(r"^(CC|CA|CU|C\.C\.|communauté de communes|"
                           r"communaute de communes|communauté d'agglomération)\s+",
                           "", EPCI_NOM, flags=re.I))


def classer(conn) -> dict[int, str]:
    """Périmètre de chaque entité, par identifiant."""
    # 1) Rattachement géographique déclaré par les collecteurs.
    classement: dict[int, str] = {}
    for row in conn.execute("SELECT id, name, commune, type FROM entities"):
        commune = _norm(row["commune"])
        nom = _norm(row["name"])
        if commune in _C1:
            classement[row["id"]] = "C1"
        elif commune in _C2_COMMUNES:
            classement[row["id"]] = "C2"
        elif _EPCI and (nom == _EPCI or _EPCI_COURT and _EPCI_COURT in nom):
            classement[row["id"]] = "C2"
        elif any(m in nom for m in SUPRA):
            classement[row["id"]] = "C3"
        else:
            classement[row["id"]] = "hors"

    # 2) Structures auxquelles la commune adhère : syndicats mixtes, SPANC…
    #    Elles décident à la place de la commune, donc C2 — détectées par la
    #    relation d'adhésion et non par une liste en dur, faute de quoi le
    #    classement se périme au premier syndicat créé.
    marques = ",".join("?" * len(RELATIONS_ADHESION))
    for row in conn.execute(
        f"SELECT to_id FROM relations WHERE relation_type IN ({marques})",
        RELATIONS_ADHESION,
    ):
        if classement.get(row["to_id"]) in ("hors", None):
            classement[row["to_id"]] = "C2"

    # 3) « lien » : hors territoire, mais rattachée à un acteur du périmètre.
    #    Trois attaches possibles — une relation, un marché, un flux financier.
    dedans = {i for i, p in classement.items() if p in ("C1", "C2")}
    lies: set[int] = set()
    for a, b in conn.execute("SELECT from_id, to_id FROM relations"):
        if a in dedans and b not in dedans:
            lies.add(b)
        if b in dedans and a not in dedans:
            lies.add(a)
    for (eid,) in conn.execute(
        "SELECT titulaire_id FROM marches_publics WHERE titulaire_id IS NOT NULL"
    ):
        lies.add(eid)
    for a, b in conn.execute(
        "SELECT from_id, to_id FROM financial_flows"
    ):
        for eid in (a, b):
            if eid is not None and eid not in dedans:
                lies.add(eid)

    for eid in lies:
        if classement.get(eid) == "hors":
            classement[eid] = "lien"

    return classement


def run(dry_run: bool = False) -> dict[str, int]:
    """Classe et écrit. Point d'entrée du step `perimetre` de run_all.

    Le classement dérive de l'état de la base : il doit donc être rejoué APRÈS
    chaque collecte, sinon les entités créées entre-temps restent NULL et le
    snapshot les écarte. C'est pour ça qu'il est un step et plus un script
    qu'on se rappelle de lancer.
    """
    conn = get_conn()
    classement = classer(conn)
    repartition = Counter(classement.values())

    print(f"[perimetre] {len(classement)} entités classées")
    for p in ("C1", "C2", "C3", "lien", "hors"):
        print(f"  {p:5} {repartition.get(p, 0):6}")

    if dry_run:
        print("\n(dry-run — rien écrit)")
        conn.close()
        return dict(repartition)

    conn.executemany("UPDATE entities SET perimetre=? WHERE id=?",
                     [(p, i) for i, p in classement.items()])
    conn.commit()
    conn.close()
    print("\n[perimetre] écrit en base")
    return dict(repartition)


def main() -> None:
    ap = argparse.ArgumentParser(description="Classe les entités par périmètre")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
