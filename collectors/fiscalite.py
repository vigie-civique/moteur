"""
fiscalite.py — Taux d'imposition locaux votés (data.economie.gouv.fr, ODS).

**Pourquoi.** La base connaissait le budget (DGFiP) et les comparatifs (OFGL),
mais pas les **taux votés** ni la pression fiscale — alors que « de combien ont
augmenté mes impôts locaux, et comment on se situe » est la première question
que se pose un habitant. Le chiffre existe, gratuit, à la commune, depuis 2021.

Deux jeux ODS complémentaires, 174 668 enregistrements chacun :
  - `fiscalite-locale-des-particuliers` : TFB, TFNB, TH résiduelle, TEOM
  - `fiscalite-locale-des-entreprises`  : CFE (hors zone / ZAE / éolien)

**Voie écartée.** Le fichier REI (Recensement des Éléments d'Imposition) est la
source primaire mais n'est diffusé qu'en **ZIP annuels** à colonnes codées, à
parser intégralement. Ces deux jeux ODS en sont l'exposition exploitable, sur la
même API que `budget.py` — et ils portent déjà les taux *globaux* (commune +
EPCI + syndicats), qui sont ce que le contribuable paie réellement.

Distinction à ne jamais perdre à l'affichage :
  - `*_vote`  = la part votée par la commune → sa responsabilité politique
  - `taux_global_*` = ce que paie le contribuable, EPCI et syndicats inclus
Attribuer le taux global au conseil municipal serait une erreur factuelle.

Usage :
  python3 -m collectors.fiscalite
  python3 -m collectors.fiscalite --insee 30140
  python3 -m collectors.fiscalite --stats
"""
from __future__ import annotations

import argparse
import json
import urllib.parse

from .archive import fetch_json
from .config import COMMUNES, COMMUNES_INSEE
from .db import get_conn

ODS_BASE = "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets"

# (dataset, colonne ODS, indicateur, libellé, portée)
# portee : 'commune' = part votée par le conseil municipal ;
#          'global'  = total acquitté par le contribuable (commune+EPCI+syndicats).
INDICATEURS = [
    ("fiscalite-locale-des-particuliers", "e12vote",         "TFB_VOTE",   "Taxe foncière bâti — taux voté par la commune", "commune"),
    ("fiscalite-locale-des-particuliers", "taux_global_tfb", "TFB_GLOBAL", "Taxe foncière bâti — taux global acquitté",     "global"),
    ("fiscalite-locale-des-particuliers", "b12vote",         "TFNB_VOTE",  "Taxe foncière non bâti — taux voté par la commune", "commune"),
    ("fiscalite-locale-des-particuliers", "taux_global_tfnb","TFNB_GLOBAL","Taxe foncière non bâti — taux global acquitté",  "global"),
    ("fiscalite-locale-des-particuliers", "taux_plein_teom", "TEOM",       "Taxe d'enlèvement des ordures ménagères — taux plein", "global"),
    ("fiscalite-locale-des-particuliers", "h12vote",         "TH_VOTE",    "Taxe d'habitation (résidences secondaires) — taux voté", "commune"),
    ("fiscalite-locale-des-particuliers", "taux_global_th",  "TH_GLOBAL",  "Taxe d'habitation (résidences secondaires) — taux global", "global"),
    ("fiscalite-locale-des-entreprises",  "taux_global_cfe_hz",  "CFE_GLOBAL", "Cotisation foncière des entreprises — taux global", "global"),
    ("fiscalite-locale-des-entreprises",  "taux_global_cfe_zae", "CFE_ZAE",    "CFE en zone d'activité économique", "global"),
]

DATASETS = sorted({d for d, *_ in INDICATEURS})


def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fiscalite_taux (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            insee       TEXT NOT NULL,
            commune     TEXT,
            annee       INTEGER NOT NULL,
            indicateur  TEXT NOT NULL,
            libelle     TEXT,
            portee      TEXT,            -- commune | global
            taux        REAL,
            epci        TEXT,
            source      TEXT DEFAULT 'data.economie-fiscalite',
            created_at  TEXT DEFAULT (datetime('now')),
            UNIQUE(insee, annee, indicateur)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fisc_insee"
                 " ON fiscalite_taux(insee, annee)")
    conn.commit()


def fetch_dataset(dataset: str, insee_list: list[str]) -> list[dict]:
    """Enregistrements d'un jeu pour les communes visées (filtre côté serveur)."""
    where = " or ".join(f'insee_com="{c}"' for c in insee_list)
    url = f"{ODS_BASE}/{dataset}/records?" + urllib.parse.urlencode(
        {"where": where, "limit": 100, "order_by": "exercice desc"})
    data = fetch_json(url, source="data.economie-fiscalite", timeout=60)
    return data.get("results", [])


def import_records(conn, dataset: str, records: list[dict]) -> int:
    """Insert idempotent — réutilisable par scripts/reparse.py."""
    cols = [(c, ind, lib, portee) for d, c, ind, lib, portee in INDICATEURS if d == dataset]
    inserted = 0
    for rec in records:
        insee = str(rec.get("insee_com") or "").strip()
        annee = rec.get("exercice")
        if not insee or annee is None:
            continue
        commune = COMMUNES.get(insee, {}).get("nom") or rec.get("libcom")
        for col, ind, libelle, portee in cols:
            taux = rec.get(col)
            if taux is None:
                continue        # taux non applicable (ex. pas de ZAE) — pas un zéro
            conn.execute(
                "INSERT OR REPLACE INTO fiscalite_taux"
                " (insee, commune, annee, indicateur, libelle, portee, taux, epci)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (insee, commune, int(annee), ind, libelle, portee,
                 float(taux), rec.get("q03")))
            inserted += 1
    conn.commit()
    return inserted


def run(insee_list: list[str] | None = None) -> int:
    conn = get_conn()
    ensure_table(conn)
    cibles = insee_list or COMMUNES_INSEE
    total = 0
    try:
        for dataset in DATASETS:
            try:
                records = fetch_dataset(dataset, cibles)
            except Exception as e:
                print(f"  [fiscalite] {dataset} : erreur — {e}")
                continue
            n = import_records(conn, dataset, records)
            total += n
            annees = sorted({r.get("exercice") for r in records if r.get("exercice")})
            print(f"  [fiscalite] {dataset}: {len(records)} enregistrements → "
                  f"{n} taux ({annees[0] if annees else '?'}–{annees[-1] if annees else '?'})")
        print(f"[fiscalite] {total} taux en base")
    finally:
        conn.close()
    return total


def stats():
    conn = get_conn()
    try:
        total = conn.execute("SELECT COUNT(*) FROM fiscalite_taux").fetchone()[0]
        print(f"fiscalite_taux : {total} taux\n")
        annee = conn.execute("SELECT MAX(annee) FROM fiscalite_taux").fetchone()[0]
        if not annee:
            return
        print(f"Taux votés par la commune — exercice {annee} "
              f"(part communale, hors EPCI et syndicats) :")
        print(f"  {'commune':<32}{'TFB':>8}{'TFNB':>8}{'TH 2e rés.':>12}{'TEOM':>8}")
        for r in conn.execute("""
            SELECT commune,
                   MAX(CASE WHEN indicateur='TFB_VOTE'  THEN taux END) tfb,
                   MAX(CASE WHEN indicateur='TFNB_VOTE' THEN taux END) tfnb,
                   MAX(CASE WHEN indicateur='TH_VOTE'   THEN taux END) th,
                   MAX(CASE WHEN indicateur='TEOM'      THEN taux END) teom
            FROM fiscalite_taux WHERE annee=? GROUP BY commune
            ORDER BY tfb DESC
        """, (annee,)):
            f = lambda v: f"{v:.2f}" if v is not None else "—"
            print(f"  {(r['commune'] or '?'):<32}{f(r['tfb']):>8}{f(r['tfnb']):>8}"
                  f"{f(r['th']):>12}{f(r['teom']):>8}")
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--insee", action="append", help="limiter à un code INSEE (répétable)")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()
    if args.stats:
        stats()
        return
    run(insee_list=args.insee)


if __name__ == "__main__":
    main()
