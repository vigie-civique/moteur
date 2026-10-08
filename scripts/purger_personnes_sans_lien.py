#!/usr/bin/env python3
"""Retire les fiches de personnes que plus rien ne rattache à la vie publique.

Une personne entre en base au titre d'un mandat, d'une direction d'organisme,
d'argent public reçu ou d'une mention dans un acte. Une fiche de personne que
plus AUCUNE ligne ne désigne — ni relation, ni flux, ni acte, ni marché, ni
décision, ni note, ni écriture au journal — n'a plus de raison d'y être : c'est
un nom, parfois une année de naissance, et rien d'autre.

D'où elles viennent : le 11/08/2026 la collecte SIRENE de Lasalle a été élargie
aux quinze communes de l'intercommunalité, puis resserrée. Les entreprises sont
reparties, leurs liens avec elles ; les dirigeants sont restés. Relevé le
08/10/2026 : 2 859 fiches, toutes créées en août, toutes hors de la commune.

    python3 scripts/purger_personnes_sans_lien.py              # à blanc : compte et répartit
    python3 scripts/purger_personnes_sans_lien.py --appliquer  # sauvegarde, puis supprime

Le compte ne lit aucun nom : il dit combien, de quelles communes, et combien
portent une naissance. La suppression est précédée d'une sauvegarde de la base
(`audits/sauvegardes/`), et laisse une ligne au journal de l'atelier.

Ce que le script ne touche JAMAIS : une fiche qu'un humain a regardée (verdict,
note, correction, proposition — tout cela laisse une trace qui la retient), et
toute fiche qui n'est pas une personne.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collectors import db as _db  # noqa: E402
from collectors.config import ROOT  # noqa: E402
from collectors.sauvegarde import sauvegarder  # noqa: E402

#: Ce que la machine dérive d'une fiche, et qui part avec elle : ces lignes ne
#: prouvent pas qu'elle sert à quelque chose.
DERIVE = ("persons", "embeddings", "scrape_runs", "entity_enrichment")


def _colonnes_qui_designent_une_fiche(conn) -> list[tuple[str, str]]:
    """(table, colonne) de toute clé étrangère vers `entities`, lue dans le
    schéma : une table ajoutée demain retient ses fiches sans qu'on y pense."""
    trouvees = []
    for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                 "AND name NOT LIKE 'sqlite_%'").fetchall():
        for fk in conn.execute(f"PRAGMA foreign_key_list('{table}')").fetchall():
            if fk[2] == "entities":
                trouvees.append((table, fk[3]))
    return trouvees


def condition_sans_lien(conn) -> str:
    """Le WHERE qui désigne une personne que rien ne retient (alias `e`)."""
    retient = [f"NOT EXISTS (SELECT 1 FROM \"{t}\" x WHERE x.\"{c}\" = e.id)"
               for t, c in _colonnes_qui_designent_une_fiche(conn) if t not in DERIVE]
    # `annotations` désigne ses objets sans clé étrangère.
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "annotations" in tables:
        retient.append("NOT EXISTS (SELECT 1 FROM annotations a WHERE "
                       "a.object_type = 'entity' AND a.object_id = e.id)")
    return "e.type = 'person' AND " + " AND ".join(retient)


def releve(conn) -> dict:
    ou = condition_sans_lien(conn)
    un = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    return {
        "personnes": un("SELECT COUNT(*) FROM entities WHERE type = 'person'"),
        "sans_lien": un(f"SELECT COUNT(*) FROM entities e WHERE {ou}"),
        "avec_naissance": un(f"SELECT COUNT(*) FROM entities e JOIN persons p ON p.entity_id = e.id "
                             f"WHERE {ou} AND p.birth_year IS NOT NULL"),
        "par_perimetre": dict(conn.execute(
            f"SELECT COALESCE(e.perimetre, '—'), COUNT(*) FROM entities e WHERE {ou} "
            "GROUP BY 1 ORDER BY 2 DESC").fetchall()),
        "par_commune": conn.execute(
            f"SELECT COALESCE(e.commune, '—'), COUNT(*) FROM entities e WHERE {ou} "
            "GROUP BY 1 ORDER BY 2 DESC LIMIT 10").fetchall(),
        "par_mois_de_creation": dict(conn.execute(
            f"SELECT substr(e.created_at, 1, 7), COUNT(*) FROM entities e WHERE {ou} "
            "GROUP BY 1 ORDER BY 1").fetchall()),
    }


def purger(conn) -> int:
    """Supprime, dans la transaction de l'appelant. Rend le nombre de fiches."""
    ou = condition_sans_lien(conn)
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS a_retirer (id INTEGER PRIMARY KEY)")
    conn.execute("DELETE FROM a_retirer")
    conn.execute(f"INSERT INTO a_retirer SELECT e.id FROM entities e WHERE {ou}")
    n = conn.execute("SELECT COUNT(*) FROM a_retirer").fetchone()[0]
    designent = _colonnes_qui_designent_une_fiche(conn)
    for table in DERIVE:
        for t, c in designent:
            if t == table:
                conn.execute(f'DELETE FROM "{t}" WHERE "{c}" IN (SELECT id FROM a_retirer)')
    conn.execute("DELETE FROM entities WHERE id IN (SELECT id FROM a_retirer)")
    conn.execute("INSERT INTO audit_log(table_name, action, field, new_value) "
                 "VALUES('entities', 'purge', 'personnes sans lien', ?)",
                 (json.dumps({"fiches": n}),))
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--appliquer", action="store_true",
                    help="sauvegarder la base puis supprimer (sans lui : à blanc)")
    args = ap.parse_args()

    conn = _db.get_conn(read_only=not args.appliquer)
    try:
        r = releve(conn)
        print(f"{r['sans_lien']} fiche(s) de personne sans aucun lien, sur {r['personnes']} "
              f"({r['avec_naissance']} portent une année de naissance).")
        if r["sans_lien"]:
            print("  périmètre :", r["par_perimetre"])
            print("  créées en :", r["par_mois_de_creation"])
            print("  communes  :", ", ".join(f"{c} {n}" for c, n in r["par_commune"]))
        if not args.appliquer:
            print("À blanc : rien n'a été écrit. Relancer avec --appliquer pour supprimer.")
            return 0
        if not r["sans_lien"]:
            return 0
        horo = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        copie = sauvegarder(_db.DB_PATH, ROOT / "audits" / "sauvegardes"
                            / f"{_db.DB_PATH.stem}-{horo}-avant-purge-personnes{_db.DB_PATH.suffix}")
        print(f"  sauvegarde : {copie}")
        conn.execute("BEGIN IMMEDIATE")
        n = purger(conn)
        conn.commit()
        print(f"✔ {n} fiche(s) supprimée(s). Reste {releve(conn)['sans_lien']} sans lien.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
