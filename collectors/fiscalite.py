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

**Situer un taux.** « 19,92 % » ne dit rien seul. Pour les indicateurs de
`REPERES`, la même API rend la médiane des communes qui lèvent la taxe et le
nombre de celles dont le taux est au moins aussi élevé — en France et dans le
département — pour chaque commune suivie en profondeur (`fiscalite_reperes`).
Une commune sans taux (la redevance remplace alors la taxe) n'a pas de repère :
l'absence de ligne n'est pas un rang.

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
from .config import COMMUNES, COMMUNES_FOND_INSEE, COMMUNES_INSEE
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

# Les indicateurs qu'on situe parmi les autres communes. La taxe d'enlèvement
# des ordures ménagères d'abord : c'est le seul taux de la page qu'aucune part
# communale n'explique, et le premier qu'un habitant compare.
REPERES = ("TEOM",)


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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fiscalite_reperes (
            insee           TEXT NOT NULL,
            annee           INTEGER NOT NULL,
            indicateur      TEXT NOT NULL,
            portee          TEXT NOT NULL,   -- france | departement
            code            TEXT NOT NULL DEFAULT '',
            taux            REAL NOT NULL,   -- celui de la commune, tel que comparé
            communes        INTEGER,         -- celles qui lèvent la taxe (taux > 0)
            mediane         REAL,
            au_moins_autant INTEGER,         -- dont le taux est ≥ celui de la commune
            PRIMARY KEY (insee, annee, indicateur, portee)
        )
    """)
    conn.commit()


def fetch_dataset(dataset: str, insee_list: list[str]) -> list[dict]:
    """Enregistrements d'un jeu pour les communes visées (filtre côté serveur)."""
    where = " or ".join(f'insee_com="{c}"' for c in insee_list)
    url = f"{ODS_BASE}/{dataset}/records?" + urllib.parse.urlencode(
        {"where": where, "limit": 100, "order_by": "exercice desc"})
    data = fetch_json(url, source="data.economie-fiscalite", timeout=60)
    return data.get("results", [])


def import_records(conn, dataset: str, records: list[dict]) -> int:
    """Insert idempotent — rejouable sans dupliquer."""
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


def _agregat(dataset: str, select: str, where: str) -> dict:
    url = f"{ODS_BASE}/{dataset}/records?" + urllib.parse.urlencode(
        {"select": select, "where": where})
    return (fetch_json(url, source="data.economie-fiscalite", timeout=60)
            .get("results") or [{}])[0]


def releve_reperes(conn, communes: list[str]) -> int:
    """Situe le dernier taux connu de chaque commune parmi celles qui lèvent la
    même taxe, la même année. Se joue après `import_records` : il lit la base."""
    # Tout lire, puis écrire : `fetch_json` archive chaque réponse par sa propre
    # connexion, et une écriture laissée ouverte ici la ferait renoncer.
    reperes = []
    for indicateur in REPERES:
        dataset, colonne = next((d, c) for d, c, ind, *_ in INDICATEURS if ind == indicateur)
        for insee in communes:
            r = conn.execute(
                "SELECT annee, taux FROM fiscalite_taux WHERE insee=? AND indicateur=?"
                " AND taux > 0 ORDER BY annee DESC LIMIT 1", (insee, indicateur)).fetchone()
            if not r:
                continue
            annee, taux = r["annee"], r["taux"]
            base = f"{colonne}>0 and exercice='{annee}'"
            for portee, code, filtre in (("france", "", ""),
                                         ("departement", insee[:2], f" and dep='{insee[:2]}'")):
                a = _agregat(dataset, f"count(*) as communes, median({colonne}) as mediane",
                             base + filtre)
                autant = _agregat(dataset, "count(*) as n", f"{base}{filtre} and {colonne}>={taux}")
                if not a.get("communes"):
                    continue
                reperes.append((insee, annee, indicateur, portee, code, taux, a["communes"],
                                a.get("mediane"), autant.get("n")))
    conn.executemany("INSERT OR REPLACE INTO fiscalite_reperes VALUES (?,?,?,?,?,?,?,?,?)",
                     reperes)
    conn.commit()
    return len(reperes)


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
        try:
            n = releve_reperes(conn, [c for c in COMMUNES_FOND_INSEE if c in cibles])
            print(f"  [fiscalite] {n} repère(s) : {', '.join(REPERES)}")
        except Exception as e:
            print(f"  [fiscalite] repères : erreur — {e}")
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
