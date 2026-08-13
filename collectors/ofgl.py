"""
ofgl.py — Collecteur OFGL (Observatoire des Finances et de la Gestion publique Locales)

Importe les agrégats financiers pré-calculés de la commune depuis data.ofgl.fr :
- Recettes/dépenses fonctionnement et investissement
- Épargne brute, nette, CAF
- Encours de dette, annuité, DGF, fiscalité
- Euros par habitant (comparaison strate)

Source : https://data.ofgl.fr — API ODS, pas de clé requise.
Données disponibles : 2017-2024.

Usage :
  python3 -m collectors.ofgl              # toutes les années
  python3 -m collectors.ofgl --year 2024
  python3 -m collectors.ofgl --dry-run
  python3 -m collectors.ofgl --stats
"""

import argparse
import json
import time
import urllib.parse
import urllib.request
from datetime import date

from .archive import fetch_json
from .db import get_conn

from .config import COMMUNE_NAME, COMMUNE_SIREN as SIREN_COMMUNE, HEADERS
DATASET = "ofgl-base-communes"
API_BASE = "https://data.ofgl.fr/api/explore/v2.1/catalog/datasets"
# OFGL publie les comptes exécutés avec ~1 an de décalage. On balaie jusqu'à
# l'année courante : les millésimes non encore publiés renvoient 0 (sans erreur).
YEARS = list(range(2017, date.today().year + 1))


def fetch_year(year: int) -> list[dict]:
    params = urllib.parse.urlencode({
        "where": f'siren="{SIREN_COMMUNE}" AND year(exer)={year} AND type_de_budget="Budget principal"',
        "limit": 100,
    })
    url = f"{API_BASE}/{DATASET}/records?{params}"
    try:
        data = fetch_json(url, source="ofgl", timeout=30,
                          headers=HEADERS)
        return data.get("results", [])
    except Exception as e:
        print(f"  [erreur] {year} : {e}")
        return []


def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ofgl_agregats (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            year                INTEGER NOT NULL,
            agregat             TEXT NOT NULL,
            montant             REAL,
            euros_par_habitant  REAL,
            population          INTEGER,
            tranche_population  TEXT,
            rural               TEXT,
            source              TEXT DEFAULT 'ofgl',
            created_at          TEXT DEFAULT (datetime('now')),
            UNIQUE(year, agregat)
        )
    """)
    conn.commit()


def import_year(conn, year: int, dry_run: bool = False) -> int:
    records = fetch_year(year)
    if not records:
        print(f"  {year} : aucune donnée")
        return 0

    print(f"  {year} : {len(records)} agrégats")
    if dry_run:
        for r in sorted(records, key=lambda x: x["agregat"]):
            print(f"    {r['agregat']:50s} {r['montant']:>12,.0f} €  {r.get('euros_par_habitant', 0):>7.1f} €/hab")
        return len(records)

    return _insert_records(conn, year, records)


def _insert_records(conn, year: int, records: list[dict]) -> int:
    """Insert idempotent des agrégats d'une année (UNIQUE(year, agregat))."""
    inserted = 0
    for r in records:
        try:
            conn.execute(
                "INSERT OR REPLACE INTO ofgl_agregats"
                " (year, agregat, montant, euros_par_habitant, population, tranche_population, rural)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    year,
                    r["agregat"],
                    r.get("montant"),
                    r.get("euros_par_habitant"),
                    r.get("ptot"),
                    r.get("tranche_population"),
                    r.get("rural"),
                )
            )
            inserted += 1
        except Exception as e:
            print(f"    [erreur] {r.get('agregat')} : {e}")

    conn.commit()
    return inserted


def run(year: int | None = None, dry_run: bool = False, stats_only: bool = False):
    conn = get_conn()
    ensure_table(conn)

    if stats_only:
        years_db = conn.execute(
            "SELECT year, COUNT(*) FROM ofgl_agregats GROUP BY year ORDER BY year"
        ).fetchall()
        if not years_db:
            print("Aucune donnée OFGL en DB.")
            conn.close()
            return
        print("OFGL en DB :")
        for y, n in years_db:
            row = conn.execute(
                "SELECT montant FROM ofgl_agregats WHERE year=? AND agregat='Encours de dette'", (y,)
            ).fetchone()
            dette = f"{row[0]:,.0f} €" if row else "—"
            epargne = conn.execute(
                "SELECT montant FROM ofgl_agregats WHERE year=? AND agregat='Epargne brute'", (y,)
            ).fetchone()
            ep = f"{epargne[0]:,.0f} €" if epargne else "—"
            print(f"  {y} : {n} agrégats | dette {dette} | épargne brute {ep}")
        conn.close()
        return

    years = [year] if year else YEARS
    total = 0
    for y in years:
        total += import_year(conn, y, dry_run=dry_run)
        if not dry_run:
            time.sleep(0.3)

    print(f"\nOFGL : {total} agrégats insérés/mis à jour.")
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=f"Collecteur OFGL — {COMMUNE_NAME}")
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args()
    run(year=args.year, dry_run=args.dry_run, stats_only=args.stats)
