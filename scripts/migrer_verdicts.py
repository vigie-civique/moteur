#!/usr/bin/env python3
"""
migrer_verdicts.py — Passe une base au vocabulaire du verdict (21/09/2026).

Deux gestes, tous deux rejouables sans effet la seconde fois :

1. `annotations.review_status` : les anciens mots deviennent les nouveaux —
   pending → jamais_relu, validated → retenu, rejected → ecarte. Équivalence
   stricte : la publication et l'API lisent déjà les deux (collectors/verdict.py),
   ce geste ne change donc RIEN au site. Il met la base d'accord avec l'écran.

2. `entities.validation_status` → une décision sur la fiche. C'est le geste
   qui PEUT changer le site : jusqu'ici ce champ n'était lu par aucune étape de
   publication, et une fiche marquée `rejected` restait en ligne. Devenue
   décision `ecarte`, elle en sort. Le rapport dit combien, et lesquelles.
   - verified / published → retenu ; reviewing → a_revoir ; rejected → ecarte
   - unverified / draft   → rien : l'absence de décision vaut « jamais relu »
   - validated            → PAS un verdict. Seul `collectors/saisies.py`
     écrivait ce mot (l'API le refusait) : il disait « créée à la main ». Il
     devient `origine = atelier`, pas une signature que personne n'a posée.
   Une fiche qui porte déjà une décision n'est pas touchée. L'auteur est repris
   du journal quand il y figure.

`validation_status` n'est ni vidée ni supprimée : elle est GELÉE, et reste
lisible comme trace de ce qui a été fait avant.

Relevé le 21/09/2026 sur les trois instances : `annotations` vide, 22 783
fiches `unverified` — le script n'y a rien à faire. Il existe pour les autres
installations du moteur, qui est public.

Usage :
  venv/bin/python scripts/migrer_verdicts.py              # à blanc
  venv/bin/python scripts/migrer_verdicts.py --appliquer
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collectors.db import get_conn  # noqa: E402
from collectors.origine import ATELIER  # noqa: E402
from collectors.verdict import (A_REVOIR, ECARTE, RETENU,  # noqa: E402
                                VERDICTS, verdict_de)

#: Ce que voulait dire chaque ancien état d'une fiche. `validated` et les états
#: « jamais tranché » n'y sont pas : ils ne produisent aucune décision.
_STATUT_VERS_VERDICT = {
    "verified":  RETENU,
    "published": RETENU,
    "reviewing": A_REVOIR,
    "rejected":  ECARTE,
}
MIGRATION = "migration du 21/09/2026 (validation_status)"


def _colonnes(conn, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def mots_anciens(conn) -> Counter:
    """Counter{(ancien, nouveau): n} des annotations à réécrire."""
    c: Counter = Counter()
    for (mot,) in conn.execute("SELECT review_status FROM annotations"):
        if mot in VERDICTS:
            continue
        neuf = verdict_de(mot)
        c[(mot, neuf)] += 1
    return c


def statuts_de_fiche(conn) -> tuple[list[tuple], list[int]]:
    """([(entity_id, nom, ancien, verdict, auteur, le)], [ids créés à la main])."""
    if "validation_status" not in _colonnes(conn, "entities"):
        return [], []
    deja = {oid for (oid,) in conn.execute(
        "SELECT object_id FROM annotations WHERE object_type='entity'")}
    decisions, a_la_main = [], []
    for eid, nom, statut in conn.execute(
            "SELECT id, name, validation_status FROM entities "
            "WHERE validation_status IS NOT NULL"):
        if statut == "validated":
            a_la_main.append(eid)
            continue
        verdict = _STATUT_VERS_VERDICT.get(statut)
        if verdict is None or eid in deja:
            continue
        auteur = conn.execute(
            "SELECT u.email, a.at FROM audit_log a LEFT JOIN users u ON u.id = a.user_id "
            "WHERE a.entity_id = ? AND a.field = 'validation_status' "
            "ORDER BY a.id DESC LIMIT 1", (eid,)).fetchone()
        decisions.append((eid, nom, statut, verdict,
                          (auteur[0] if auteur and auteur[0] else MIGRATION),
                          auteur[1] if auteur else None))
    return decisions, a_la_main


def run(appliquer: bool) -> dict:
    conn = get_conn()
    try:
        mots = mots_anciens(conn)
        decisions, a_la_main = statuts_de_fiche(conn)
        avec_origine = "origine" in _colonnes(conn, "entities")

        print("[verdicts] 1. mots des décisions existantes")
        if mots:
            for (ancien, neuf), n in sorted(mots.items(), key=lambda kv: -kv[1]):
                print(f"   {n:6}  {ancien!r:14} → {neuf or 'INCONNU — laissé tel quel'}")
        else:
            print("   rien : toutes les décisions sont déjà dans le vocabulaire neuf")

        print("[verdicts] 2. statuts de fiche → décisions")
        par_verdict = Counter(d[3] for d in decisions)
        if decisions:
            for v, n in par_verdict.most_common():
                print(f"   {n:6}  → {v}")
            sortantes = [d for d in decisions if d[3] == ECARTE]
            if sortantes:
                print(f"   ⚠ {len(sortantes)} fiche(s) marquée(s) `rejected` SORTIRONT "
                      f"du site à la prochaine publication :")
                for d in sortantes[:20]:
                    print(f"       #{d[0]:<6} {d[1][:60]}")
                if len(sortantes) > 20:
                    print(f"       … et {len(sortantes) - 20} autre(s)")
        else:
            print("   rien : aucune fiche n'a jamais été tranchée")
        if a_la_main:
            cible = "origine = atelier" if avec_origine else \
                "origine à poser (colonne absente : lancer d'abord init_db)"
            print(f"   {len(a_la_main):6}  `validated` (créées à la main) → {cible}")

        if not appliquer:
            print("\n(à blanc — rien écrit ; --appliquer pour écrire)")
            return {"mots": sum(mots.values()), "decisions": len(decisions),
                    "a_la_main": len(a_la_main)}

        conn.execute("BEGIN IMMEDIATE")
        for (ancien, neuf), _ in mots.items():
            if neuf:
                conn.execute("UPDATE annotations SET review_status=? WHERE review_status=?",
                             (neuf, ancien))
        for eid, _nom, _ancien, verdict, auteur, le in decisions:
            conn.execute(
                "INSERT OR IGNORE INTO annotations(object_type, object_id, review_status, "
                "note, reviewed_by, reviewed_at) VALUES('entity', ?, ?, ?, ?, "
                "COALESCE(?, datetime('now')))",
                (eid, verdict, f"repris de validation_status « {_ancien} »", auteur, le))
        if a_la_main and avec_origine:
            conn.executemany("UPDATE entities SET origine=? WHERE id=? AND origine IS NULL",
                             [(ATELIER, eid) for eid in a_la_main])
        conn.commit()
        print(f"\n[verdicts] écrit : {sum(mots.values())} mot(s), "
              f"{len(decisions)} décision(s), {len(a_la_main) if avec_origine else 0} origine(s)")
        return {"mots": sum(mots.values()), "decisions": len(decisions),
                "a_la_main": len(a_la_main)}
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--appliquer", action="store_true", help="écrit en base")
    run(ap.parse_args().appliquer)


if __name__ == "__main__":
    main()
