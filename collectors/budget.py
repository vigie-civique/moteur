"""
budget.py — Collecteur balances comptables communes (DGFiP via data.economie.gouv.fr)

Importe les agrégats budgétaires annuels de la commune depuis les fichiers
officiels de la DGFiP publiés sur data.gouv.fr.

Source : https://data.economie.gouv.fr (API ODS)
Pas de clé requise.

Usage :
  python3 -m collectors.budget              # toutes les années disponibles
  python3 -m collectors.budget --year 2023  # une année
  python3 -m collectors.budget --dry-run
  python3 -m collectors.budget --stats
"""

import argparse
import json
import time
import urllib.parse
import urllib.request

from .archive import fetch_json
from .db import get_conn

from .config import COMMUNE_NAME, COMMUNE_SIREN as SIREN_COMMUNE, HEADERS

# Datasets disponibles par année (dataset_id sur data.economie.gouv.fr)
DATASETS = {
    2019: "balances-comptables-des-communes-en-2019",
    2020: "balances-comptables-des-communes-en-2020",
    2021: "balances-comptables-des-communes-en-2021",
    2022: "balances-comptables-des-communes-en-2022",
    2023: "balances-comptables-des-communes-en-2023",
}

API_BASE = "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets"

# Comptes M14 clés → libellés lisibles
# Section fonctionnement : recettes 7xxx, dépenses 6xxx
# Section investissement : recettes 1xxx/2xxx, dépenses 2xxx
COMPTES_CLES = {
    # Recettes fonctionnement
    "70":   ("recettes_fonctionnement", "Produits des services"),
    "73":   ("recettes_fonctionnement", "Impôts et taxes"),
    "731":  ("recettes_fonctionnement", "Taxe foncière bâti"),
    "7311": ("recettes_fonctionnement", "Taxe foncière bâti (TFB)"),
    "7313": ("recettes_fonctionnement", "Taxe foncière non bâti (TFNB)"),
    "7315": ("recettes_fonctionnement", "Cotisation foncière entreprises (CFE)"),
    "74":   ("recettes_fonctionnement", "Dotations et participations (DGF...)"),
    "741":  ("recettes_fonctionnement", "DGF"),
    "75":   ("recettes_fonctionnement", "Autres recettes de gestion courante"),
    "77":   ("recettes_fonctionnement", "Produits exceptionnels"),
    # Dépenses fonctionnement
    "60":   ("depenses_fonctionnement", "Achats et charges ext."),
    "61":   ("depenses_fonctionnement", "Services ext."),
    "62":   ("depenses_fonctionnement", "Autres services ext."),
    "63":   ("depenses_fonctionnement", "Impôts et taxes (charges)"),
    "64":   ("depenses_fonctionnement", "Charges de personnel"),
    "65":   ("depenses_fonctionnement", "Autres charges de gestion courante"),
    "66":   ("depenses_fonctionnement", "Charges financières"),
    "67":   ("depenses_fonctionnement", "Charges exceptionnelles"),
    "68":   ("depenses_fonctionnement", "Dotations amortissements"),
    # Section investissement
    "16":   ("dette", "Emprunts et dettes"),
    "165":  ("dette", "Dépôts et cautionnements reçus"),
    "166":  ("dette", "Obligations"),
    "1641": ("dette", "Emprunts en euros"),
    "20":   ("investissement", "Immobilisations incorporelles"),
    "21":   ("investissement", "Immobilisations corporelles"),
    "23":   ("investissement", "Immobilisations en cours"),
}


def fetch_comptes(year: int) -> list[dict]:
    """Récupère toutes les lignes comptables de la commune pour une année."""
    dataset = DATASETS.get(year)
    if not dataset:
        return []

    all_records = []
    offset = 0
    page_size = 100

    while True:
        params = urllib.parse.urlencode({
            "where": f'siren="{SIREN_COMMUNE}"',
            "limit": page_size,
            "offset": offset,
        })
        url = f"{API_BASE}/{dataset}/records?{params}"
        try:
            data = fetch_json(url, source="budget-dgfip", timeout=30,
                              headers=HEADERS)
        except Exception as e:
            print(f"  [erreur] {year} offset={offset} : {e}")
            break

        records = data.get("results", [])
        all_records.extend(records)

        if len(all_records) >= data.get("total_count", 0):
            break
        offset += len(records)
        time.sleep(0.2)

    return all_records


def aggregate(records: list[dict]) -> dict:
    """Agrège les lignes comptables en indicateurs budgétaires clés."""
    agg = {}

    for rec in records:
        compte = str(rec.get("compte", ""))
        sd = float(rec.get("sd") or 0)  # solde débiteur
        sc = float(rec.get("sc") or 0)  # solde créditeur

        # Budget principal vs annexes
        cbudg = rec.get("cbudg", "1")

        for prefix, (categorie, libelle) in COMPTES_CLES.items():
            if compte.startswith(prefix):
                key = f"{categorie}__{prefix}"
                if key not in agg:
                    agg[key] = {"categorie": categorie, "libelle": libelle,
                                "compte": prefix, "montant": 0.0, "cbudg": cbudg}
                # Fonctionnement recettes → créditeur, dépenses → débiteur
                if categorie == "recettes_fonctionnement":
                    agg[key]["montant"] += sc
                else:
                    agg[key]["montant"] += sd
                break

    # Totaux synthétiques
    total_rec_fonct = sum(v["montant"] for v in agg.values()
                         if v["categorie"] == "recettes_fonctionnement")
    total_dep_fonct = sum(v["montant"] for v in agg.values()
                         if v["categorie"] == "depenses_fonctionnement")
    total_dette = sum(v["montant"] for v in agg.values()
                      if v["categorie"] == "dette")

    return {
        "lignes": list(agg.values()),
        "totaux": {
            "recettes_fonctionnement": round(total_rec_fonct, 2),
            "depenses_fonctionnement": round(total_dep_fonct, 2),
            "excedent_fonctionnement": round(total_rec_fonct - total_dep_fonct, 2),
            "encours_dette": round(total_dette, 2),
        }
    }


def ensure_budget_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS budget_annuel (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            year        INTEGER NOT NULL,
            categorie   TEXT NOT NULL,
            compte      TEXT NOT NULL,
            libelle     TEXT,
            montant     REAL,
            source      TEXT DEFAULT 'dgfip',
            created_at  TEXT DEFAULT (datetime('now')),
            UNIQUE(year, compte, categorie)
        )
    """)
    conn.commit()


def import_year(conn, year: int, dry_run: bool = False) -> int:
    records = fetch_comptes(year)
    if not records:
        print(f"  {year} : aucune donnée")
        return 0

    result = aggregate(records)
    totaux = result["totaux"]
    lignes = result["lignes"]

    print(f"  {year} : {len(records)} lignes brutes → {len(lignes)} agrégats")
    print(f"    Recettes fonct. : {totaux['recettes_fonctionnement']:,.0f} €")
    print(f"    Dépenses fonct. : {totaux['depenses_fonctionnement']:,.0f} €")
    print(f"    Excédent        : {totaux['excedent_fonctionnement']:,.0f} €")
    print(f"    Encours dette   : {totaux['encours_dette']:,.0f} €")

    if dry_run:
        return len(lignes)

    inserted = 0
    for ligne in lignes:
        try:
            conn.execute(
                "INSERT OR REPLACE INTO budget_annuel (year, categorie, compte, libelle, montant)"
                " VALUES (?, ?, ?, ?, ?)",
                (year, ligne["categorie"], ligne["compte"], ligne["libelle"], ligne["montant"])
            )
            inserted += 1
        except Exception as e:
            print(f"    [erreur insert] {e}")

    # Insérer aussi les totaux synthétiques
    for key, montant in totaux.items():
        try:
            conn.execute(
                "INSERT OR REPLACE INTO budget_annuel (year, categorie, compte, libelle, montant)"
                " VALUES (?, 'total', ?, ?, ?)",
                (year, key, key.replace("_", " "), montant)
            )
            inserted += 1
        except Exception as e:
            print(f"    [erreur total] {e}")

    conn.commit()
    return inserted


def run(year: int | None = None, dry_run: bool = False, stats_only: bool = False):
    conn = get_conn()
    ensure_budget_table(conn)

    if stats_only:
        try:
            rows = conn.execute(
                "SELECT year, COUNT(*), SUM(CASE WHEN compte='recettes_fonctionnement' THEN montant END)"
                " FROM budget_annuel WHERE categorie='total'"
                " GROUP BY year ORDER BY year"
            ).fetchall()
            print("Budget en DB :")
            for r in rows:
                print(f"  {r[0]} : {r[1]} lignes | recettes fonct. {r[2]:,.0f} €" if r[2] else f"  {r[0]} : {r[1]} lignes")
        except Exception:
            count = conn.execute("SELECT COUNT(*) FROM budget_annuel").fetchone()[0]
            print(f"Budget en DB : {count} lignes")
        conn.close()
        return

    years = [year] if year else sorted(DATASETS.keys())
    total = 0
    for y in years:
        print(f"\nAnnée {y} :")
        total += import_year(conn, y, dry_run=dry_run)

    print(f"\nTotal : {total} lignes insérées/mises à jour.")
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=f"Collecteur budget communal — {COMMUNE_NAME}")
    parser.add_argument("--year", type=int, default=None, help="Année (défaut: toutes)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args()
    run(year=args.year, dry_run=args.dry_run, stats_only=args.stats)
