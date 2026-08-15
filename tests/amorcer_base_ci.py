#!/usr/bin/env python3
"""Amorce une base minimale pour l'intégration continue.

Trois entités et un acte, choisis pour que la chaîne complète ait quelque chose
à filtrer : une entreprise de la commune qui doit sortir, une entreprise d'une
commune membre qui ne doit pas, une personne sans rôle civique qui ne doit pas
non plus. Le snapshot construit dessus vaut assertion de bout en bout — si le
filtre se relâche, le compte publié change et le contrôle d'étanchéité le voit.

Une base vide ne suffisait pas : SvelteKit refuse de terminer un build où une
route dynamique déclarée prérendable ne produit aucune page. C'est un contrôle
utile en production, on ne le désactive pas pour arranger la CI.

    VIGIE_DB=db/ci.db python3 tests/amorcer_base_ci.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("VIGIE_INSTANCE", str(Path(__file__).parent / "instance_test.json"))
sys.path.insert(0, str(ROOT))

from collectors.config import DB_PATH   # noqa: E402


def main() -> int:
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))

    def entite(type_, nom, commune, perimetre, confidence="verified"):
        return conn.execute(
            "INSERT INTO entities (type, name, commune, perimetre, confidence) "
            "VALUES (?,?,?,?,?)", (type_, nom, commune, perimetre, confidence)
        ).lastrowid

    publiable = entite("business", "Boulangerie d'épreuve", "Testonville", "C1")
    entite("business", "Commerce de Voisinbourg", "Voisinbourg", "C2")
    entite("person", "Une habitante", "Testonville", "C1")

    # La source doit figurer dans l'allowlist des règles d'EXEMPLE, qui ne
    # connaît que les sources nationales : les sources locales (« CM »,
    # « CR CM ») se déclarent instance par instance. Un acte publié avec la
    # source « CM » serait donc écarté ici, et la CI construirait un site sans
    # aucun acte — or c'est justement ce parcours qu'elle doit vérifier.
    conn.execute(
        "INSERT INTO events (type, date, title, content, source) "
        "VALUES ('election','2026-01-15','Scrutin d''épreuve',"
        "'Résultats publiés par le ministère.','interieur')")
    conn.execute(
        "INSERT INTO event_entities (event_id, entity_id, role) VALUES (?,?,'sujet')",
        (conn.execute("SELECT MAX(id) FROM events").fetchone()[0], publiable))
    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    conn.close()
    print(f"[ci] {DB_PATH} amorcée — {total} entités, dont 1 seule publiable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
