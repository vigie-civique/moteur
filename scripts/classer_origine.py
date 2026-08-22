#!/usr/bin/env python3
"""
classer_origine.py — Renseigne `origine` sur les tables de faits datés.

Trois valeurs, définies dans `collectors/origine.py` : `institutionnel` (une
administration a structuré la donnée), `verbatim` (nous l'avons lue dans un PDF
ou une page), `atelier` (un humain l'a saisie). C'est cette colonne que l'API
interroge avant d'autoriser une rectification : sans elle, la règle « ne pas
corriger ce qui vient d'un collecteur institutionnel » n'aurait aucun effet.

Le classement dérive de `source`, que les collecteurs écrivent. Il est donc
rejoué en fin de collecte, comme `perimetre` — step `origine` de run_all, placé
juste avant lui.

CE SCRIPT NE DEVINE PAS. Une source non reconnue laisse la colonne vide et
apparaît dans le rapport. C'est voulu : classer au hasard, ce serait soit
protéger comme institutionnelle une ligne que personne n'a vérifiée, soit ouvrir
à la réécriture un chiffre publié par une administration. Les deux erreurs sont
silencieuses, et c'est exactement le genre de défaut qui a tenu des mois ici.

Les lignes déjà classées `atelier` ne sont JAMAIS reclassées : elles portent une
signature humaine (`saisi_par`), et une collecte ultérieure n'a pas à la défaire.

Usage :
  venv/bin/python scripts/classer_origine.py --dry-run
  venv/bin/python scripts/classer_origine.py
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collectors.db import get_conn  # noqa: E402
from collectors.origine import (ATELIER, TABLES_ORIGINE,  # noqa: E402
                                origine_de)


def _tables_presentes(conn) -> list[str]:
    """Une instance jeune n'a pas encore toutes les tables : `budget_vote` et
    `dotations_etat` n'existent qu'après le premier passage des collecteurs
    correspondants. Les ignorer vaut mieux qu'échouer."""
    existantes = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    return [t for t in TABLES_ORIGINE if t in existantes]


def classer(conn) -> tuple[dict[str, dict[int, str]], dict[str, Counter]]:
    """Renvoie ({table: {id: origine}}, {table: Counter(sources non reconnues)}).

    Ne touche ni les lignes déjà classées `atelier`, ni celles dont la source
    n'est pas reconnue.
    """
    a_ecrire: dict[str, dict[int, str]] = {}
    inconnues: dict[str, Counter] = {}

    for table in _tables_presentes(conn):
        decisions: dict[int, str] = {}
        non_reconnues: Counter = Counter()
        for row in conn.execute(
                f"SELECT id, source, origine FROM {table}"):
            if row["origine"] == ATELIER:
                continue
            origine = origine_de(row["source"])
            if origine is None:
                non_reconnues[(row["source"] or "(vide)")[:80]] += 1
                continue
            if origine != row["origine"]:
                decisions[row["id"]] = origine
        a_ecrire[table] = decisions
        inconnues[table] = non_reconnues

    return a_ecrire, inconnues


def run(dry_run: bool = False) -> dict[str, int]:
    """Classe et écrit. Point d'entrée du step `origine` de run_all."""
    conn = get_conn()
    a_ecrire, inconnues = classer(conn)

    total_ecrit = 0
    repartition: Counter = Counter()
    print("[origine] classement des tables de faits")
    for table, decisions in a_ecrire.items():
        # État final, pas seulement le delta : ce qui compte pour l'humain qui
        # lit le rapport, c'est la composition de la table, pas le nombre de
        # lignes que ce passage a changées.
        etat = defaultdict(int)
        for orig, n in conn.execute(
                f"SELECT origine, COUNT(*) FROM {table} GROUP BY origine"):
            etat[orig] = n
        for i, o in decisions.items():
            etat[o] += 1
            etat[None] = max(0, etat.get(None, 0) - 1)
        resume = "  ".join(f"{o or 'non classé'}={n}" for o, n in sorted(
            etat.items(), key=lambda kv: (kv[0] is None, kv[0] or "")) if n)
        print(f"  {table:22} {len(decisions):5} à écrire   {resume}")
        total_ecrit += len(decisions)
        for o in decisions.values():
            repartition[o] += 1

    restant = {t: c for t, c in inconnues.items() if c}
    if restant:
        print("\n[origine] sources NON RECONNUES — colonne laissée vide,"
              " ces lignes ne seront ni protégées ni ouvertes à la saisie :")
        for table, compteur in restant.items():
            for source, n in compteur.most_common(10):
                print(f"  {table:22} {n:6}  « {source} »")
        print("  → ajouter le motif dans collectors/origine.py, puis rejouer.")

    if dry_run:
        print("\n(dry-run — rien écrit)")
        conn.close()
        return dict(repartition)

    for table, decisions in a_ecrire.items():
        if decisions:
            conn.executemany(f"UPDATE {table} SET origine=? WHERE id=?",
                             [(o, i) for i, o in decisions.items()])
    conn.commit()
    conn.close()
    print(f"\n[origine] {total_ecrit} lignes écrites")
    return dict(repartition)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Classe les faits par origine (institutionnel/verbatim/atelier)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
