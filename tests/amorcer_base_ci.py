#!/usr/bin/env python3
"""Amorce une base minimale pour l'intégration continue.

Cinq entités, un acte, deux élus et une autorisation d'urbanisme, choisis pour
que la chaîne complète ait quelque chose à filtrer : une entreprise de la
commune qui doit sortir, une entreprise d'une commune membre qui ne doit pas,
une personne sans rôle civique qui ne doit pas non plus, et — depuis le
21/08/2026 — deux élus dont un seul a droit à une fiche, plus un permis dont le
demandeur n'en a pas. Le snapshot construit dessus vaut assertion de bout en bout — si le
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

from collectors.config import DB_PATH                     # noqa: E402
from collectors.rne import ensure_table as rne_ensure_table          # noqa: E402
from collectors.urbanisme_sitadel import ensure_table as sitadel_ensure_table  # noqa: E402


def main() -> int:
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))

    def entite(type_, nom, commune, perimetre, confidence="verified"):
        return conn.execute(
            "INSERT INTO entities (type, name, commune, perimetre, confidence) "
            "VALUES (?,?,?,?,?)", (type_, nom, commune, perimetre, confidence)
        ).lastrowid

    publiable = entite("business", "Boulangerie d'épreuve", "Testonville", "C1")
    voisin = entite("business", "Commerce de Voisinbourg", "Voisinbourg", "C2")
    entite("person", "Une habitante", "Testonville", "C1")

    # Un élu de la commune (fiche) et un conseiller d'une commune membre (pas de
    # fiche : `publiable_dans_perimetre` ne l'accorde à une personne C2 que si
    # elle siège au conseil communautaire). Sans ces deux lignes, la CI ne
    # traversait JAMAIS l'export des élus — `elus_rne` n'est pas dans
    # `db/schema.sql`, elle est créée par son collecteur, donc `table_exists()`
    # rendait faux et le bloc entier était sauté. C'est ce trou qui a laissé
    # passer 152 à 191 liens morts par instance jusqu'au 21/08/2026.
    mairie = entite("service", "Mairie d'épreuve", "Testonville", "C1")
    elu_publiable = entite("person", "Élue de Testonville", "Testonville", "C1")
    elu_sans_fiche = entite("person", "Conseiller de Voisinbourg", "Voisinbourg", "C2")
    # Le mandat rend l'élue publiable : une personne ne sort qu'au titre d'un
    # rôle civique (`people.publish_only_with_relation_types`). Sans lui, les
    # DEUX élus seraient sans fiche et la CI ne verrait jamais le cas passant —
    # un correctif qui mettrait `fiche: false` partout passerait le contrôle.
    conn.execute(
        "INSERT INTO relations (from_id, to_id, relation_type, confidence) "
        "VALUES (?,?,'maire','verified')", (elu_publiable, mairie))
    rne_ensure_table(conn)
    for mandat, insee, commune, nom, prenom, eid in (
            ("cm", "99001", "Testonville", "ÉPREUVE", "Élue", elu_publiable),
            ("cm", "99002", "Voisinbourg", "VOISIN", "Conseiller", elu_sans_fiche)):
        conn.execute(
            "INSERT INTO elus_rne (mandat, insee, commune, nom, prenom, "
            "date_debut_mandat, entity_id) VALUES (?,?,?,?,?,'2026-03-22',?)",
            (mandat, insee, commune, nom, prenom, eid))

    # Une autorisation dont le demandeur n'a pas de fiche : le builder doit
    # retirer le renvoi plutôt que de le laisser désigner un 404.
    sitadel_ensure_table(conn)
    conn.execute(
        "INSERT INTO urbanisme_autorisations (num_dau, insee, commune, categorie,"
        " type_dau, type_label, date_depot, demandeur_nom, demandeur_entity_id)"
        " VALUES ('99001260001','99001','Testonville','logements','PC',"
        "'Permis de construire','2026-01-01','Commerce de Voisinbourg',?)",
        (voisin,))

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
