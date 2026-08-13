"""
occitanie_region.py — Subventions Région Occitanie à la CC CAC

Source : data.laregion.fr — dataset subventions-du-conseil-regional
  Bénéficiaire : COMMUNAUTE DE COMMUNES CAUSSES AIGOUAL CEVENNES (SIREN 200034601)
  Note : Lasalle commune absente (trop petite), subventions transitent par l'EPCI

Usage :
  python3 -m collectors.occitanie_region
  python3 -m collectors.occitanie_region --dry-run
"""

import argparse
import json
import sqlite3
import time
from pathlib import Path

import requests

from .archive import archive_fetch

from .config import DB_PATH   # la base est nommée dans la config, pas ici
from .config import EPCI_NOM, HEADERS
from .db import pivot_ids, upsert_entity

# Nom de l'EPCI tel qu'il apparaît dans le fichier des subventions régionales :
# la Région écrit les bénéficiaires en capitales et sans article.
CAC_NAME    = EPCI_NOM.upper().replace("CC ", "COMMUNAUTE DE COMMUNES ")

API_BASE    = "https://data.laregion.fr/api/explore/v2.1/catalog/datasets"
DATASET     = "subventions-du-conseil-regional"


def _fetch_all_cac(session: requests.Session) -> list[dict]:
    """Récupère toutes les subventions Occitanie → CC CAC."""
    results = []
    limit = 100
    offset = 0
    while True:
        r = session.get(
            f"{API_BASE}/{DATASET}/records",
            params={
                "limit":  limit,
                "offset": offset,
                "where":  f'nombeneficiaire LIKE "%Causses Aigoual%"',
                "order_by": "date_de_decision ASC",
            },
            timeout=20,
        )
        r.raise_for_status()
        archive_fetch("occitanie-region", r.url, r.content,
                      content_type=r.headers.get("Content-Type"),
                      http_status=r.status_code)
        data = r.json()
        batch = data.get("results", [])
        results.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
        time.sleep(0.3)
    return results


def _flow_exists(conn, year: int, ref: str) -> bool:
    row = conn.execute(
        "SELECT id FROM financial_flows WHERE source='occitanie_region' AND year=? AND description LIKE ? LIMIT 1",
        (year, f"%{ref}%")
    ).fetchone()
    return row is not None


def _import_records(conn, records: list[dict], dry_run: bool = False) -> tuple[int, int]:
    # Les deux parties du flux sont résolues par leur nom : les identifiants en
    # dur de l'instance d'origine désignaient d'autres entités dans cette base.
    REGION_ID = upsert_entity(conn, type="service",
                              name="Conseil régional Occitanie",
                              confidence="verified")
    CAC_ID = pivot_ids(conn)["epci"]
    """Insert dédupliqué (referencedecision) — réutilisé par scripts/reparse.py."""
    inserted = 0
    skipped  = 0

    for rec in records:
        ref      = rec.get("referencedecision") or ""
        objet    = rec.get("objet") or ""
        date     = rec.get("date_de_decision") or ""
        year_str = rec.get("annee_decision") or date[:4]
        year     = int(year_str) if year_str and year_str.isdigit() else None
        montant  = rec.get("montant_vote")

        description = f"[{ref}] {objet}"[:250]

        if year and _flow_exists(conn, year, ref or description[:40]):
            skipped += 1
            continue

        if dry_run:
            print(f"  [DRY] {date} | {montant:>10,.0f}€ | {objet[:70]}")
            inserted += 1
            continue

        conn.execute(
            "INSERT INTO financial_flows (type, year, amount, from_id, to_id, description, source, confidence)"
            " VALUES ('subvention_region', ?, ?, ?, ?, ?, 'occitanie_region', 'verified')",
            (year, int(montant) if montant else None, REGION_ID, CAC_ID, description)
        )
        inserted += 1

    return inserted, skipped


def run(dry_run: bool = False):
    session = requests.Session()
    session.headers.update(HEADERS)

    print("\n[1] Récupération subventions Région Occitanie → CC CAC…")
    records = _fetch_all_cac(session)
    print(f"  {len(records)} subventions trouvées")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    inserted, skipped = _import_records(conn, records, dry_run=dry_run)

    if not dry_run:
        conn.commit()
    conn.close()

    prefix = "[DRY-RUN] " if dry_run else ""
    print(f"\n{prefix}✅ Occitanie terminé — {inserted} insérés, {skipped} déjà présents")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
