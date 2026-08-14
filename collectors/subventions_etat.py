"""
subventions_etat.py — Subventions d'État reçues par la commune et son EPCI

Sources :
  1. ofgl_agregats → DGF, Concours de l'État, Autres dotations (agrégés annuels)
  2. events CM → demandes DETR/DSIL/Fonds Vert/FPIC identifiées dans les délibérations

Usage :
  python3 -m collectors.subventions_etat
  python3 -m collectors.subventions_etat --dry-run
"""

import argparse
import json
import re
import sqlite3
from pathlib import Path

from .config import DB_PATH   # la base est nommée dans la config, pas ici
from .db import pivot_ids

# Entités structurantes — résolues par leur nom à l'exécution (cf. db.pivot_ids).

# Mots-clés pour détection dans les délibérations CM
KEYWORDS_DETR       = re.compile(r'\bDETR\b', re.I)
KEYWORDS_DSIL       = re.compile(r'\bDSIL\b', re.I)
KEYWORDS_FONDS_VERT = re.compile(r'fonds\s+vert', re.I)
KEYWORDS_FPIC       = re.compile(r'\bFPIC\b', re.I)
KEYWORDS_DETR_ALL   = re.compile(r'\b(DETR|DSIL|fonds\s+vert|FPIC|FNADT|LEADER)\b', re.I)

# Agrégats OFGL → types financial_flows
OFGL_MAPPING = {
    "Dotation globale de fonctionnement": "DGF",
    "Autres dotations de fonctionnement": "dotation_fonctionnement",
    "Concours de l'Etat":                 "concours_etat",
    "Subventions reçues et participations": "subventions_recues",
    "Autres dotations et subventions":    "dotations_subventions",
}


def run(dry_run: bool = False):
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    ids = pivot_ids(conn)
    COMMUNE_ID, ETAT_ID = ids["commune"], ids["etat"]
    PREFET_ID, CAC_ID   = ids["prefecture"], ids["epci"]

    inserted_ofgl = 0
    inserted_cm   = 0

    # ── 1. OFGL → financial_flows annuels ────────────────────────────────────
    print("\n[1] Import dotations OFGL → financial_flows…")

    ofgl_rows = conn.execute(
        "SELECT year, agregat, montant FROM ofgl_agregats WHERE agregat IN ({}) ORDER BY year".format(
            ",".join("?" * len(OFGL_MAPPING))
        ),
        list(OFGL_MAPPING.keys())
    ).fetchall()

    print(f"  {len(ofgl_rows)} lignes OFGL à traiter")

    for row in ofgl_rows:
        flow_type = OFGL_MAPPING[row["agregat"]]
        description = f"{row['agregat']} {row['year']}"

        existing = conn.execute(
            "SELECT id FROM financial_flows WHERE type=? AND year=? AND from_id=? AND to_id=?",
            (flow_type, row["year"], ETAT_ID, COMMUNE_ID)
        ).fetchone()

        if existing:
            continue

        if dry_run:
            print(f"  [DRY] {row['year']} {flow_type} {row['montant']:,.0f} €")
            inserted_ofgl += 1
            continue

        conn.execute(
            "INSERT INTO financial_flows (type, year, amount, from_id, to_id, description, source, confidence)"
            " VALUES (?, ?, ?, ?, ?, ?, 'OFGL', 'verified')",
            (flow_type, row["year"], row["montant"], ETAT_ID, COMMUNE_ID, description)
        )
        inserted_ofgl += 1

    # ── 1b. DGF notifiée (DGCL) → financial_flows ────────────────────────────
    # Pour les exercices non encore couverts par OFGL (2025/2026), on reconstitue
    # la DGF totale depuis dotations_etat (portail DGCL). On somme les grandes
    # composantes en évitant le double-compte DSR (agrégat OU sous-parts) et en
    # excluant tout ce qui est « hors DGF » (dotation élu local, etc.).
    print("\n[1b] DGF notifiée DGCL → financial_flows…")
    inserted_dgf = 0
    try:
        dgf_years = [r["year"] for r in conn.execute(
            "SELECT DISTINCT year FROM dotations_etat ORDER BY year"
        ).fetchall()]
    except sqlite3.OperationalError:
        dgf_years = []

    for year in dgf_years:
        rows = conn.execute(
            "SELECT composante, montant FROM dotations_etat WHERE year=?", (year,)
        ).fetchall()
        base = 0.0
        dsr_agg = None
        dsr_parts = 0.0
        for r in rows:
            comp = (r["composante"] or "").lower()
            montant = r["montant"] or 0
            if "hors dgf" in comp or "élu local" in comp or "elu local" in comp:
                continue
            if comp.startswith("dsr (solidarit"):          # agrégat DSR total
                dsr_agg = montant
            elif comp.startswith("dsr "):                   # sous-parts (BC/péréq/cible)
                dsr_parts += montant
            elif comp.startswith("dotation forfaitaire") \
                    or comp.startswith("dnp") or comp.startswith("dsu"):
                base += montant
        dgf_total = base + (dsr_agg if dsr_agg is not None else dsr_parts)
        if dgf_total <= 0:
            continue

        existing = conn.execute(
            "SELECT id FROM financial_flows WHERE type='DGF' AND year=? AND from_id=? AND to_id=?",
            (year, ETAT_ID, COMMUNE_ID)
        ).fetchone()
        if existing:
            continue
        if dry_run:
            print(f"  [DRY] {year} DGF {dgf_total:,.0f} € (DGCL notifiée)")
            inserted_dgf += 1
            continue
        conn.execute(
            "INSERT INTO financial_flows (type, year, amount, from_id, to_id, description, source, confidence)"
            " VALUES ('DGF', ?, ?, ?, ?, ?, 'DGCL', 'verified')",
            (year, dgf_total, ETAT_ID, COMMUNE_ID, f"DGF notifiée {year} (DGCL)")
        )
        inserted_dgf += 1

    # ── 2. CM délibérations → demandes DETR/DSIL/Fonds Vert ─────────────────
    print("\n[2] Extraction demandes subventions État depuis CM…")

    cm_events = conn.execute(
        """SELECT id, title, date, metadata FROM events
           WHERE type='deliberation'
           AND (title LIKE '%DETR%' OR title LIKE '%DSIL%'
                OR title LIKE '%Fonds Vert%' OR title LIKE '%fonds vert%'
                OR title LIKE '%FPIC%' OR title LIKE '%FNADT%' OR title LIKE '%LEADER%')
           ORDER BY date"""
    ).fetchall()

    print(f"  {len(cm_events)} délibérations avec mots-clés subvention État")

    for ev in cm_events:
        meta = json.loads(ev["metadata"] or "{}")
        title = ev["title"] or ""
        year_str = (ev["date"] or "")[:4]
        year = int(year_str) if year_str.isdigit() else None

        # Détecter le dispositif
        if KEYWORDS_DETR.search(title):
            flow_type = "DETR_demande"
        elif KEYWORDS_DSIL.search(title):
            flow_type = "DSIL_demande"
        elif KEYWORDS_FONDS_VERT.search(title):
            flow_type = "Fonds_Vert_demande"
        elif KEYWORDS_FPIC.search(title):
            flow_type = "FPIC"
        else:
            flow_type = "subvention_etat_demande"

        # Trouver le montant demandé dans les metadata
        montant = None
        montants = meta.get("montants", [])
        # Chercher le montant le plus petit (généralement la part demandée, pas le coût total)
        if isinstance(montants, list) and montants:
            vals = [m.get("value") for m in montants if isinstance(m, dict) and m.get("value")]
            if vals:
                montant = min(float(v) for v in vals if v)

        # Aussi tenter montant_ht direct (CC CAC events)
        if not montant and meta.get("montant_ht"):
            montant = float(meta["montant_ht"])

        # Déterminer bénéficiaire / acheteur
        to_id = COMMUNE_ID  # par défaut la commune
        if "cc cac" in title.lower() or "communauté de communes" in title.lower():
            to_id = CAC_ID

        # Vérifier doublon (même event_id)
        existing = conn.execute(
            "SELECT id FROM financial_flows WHERE event_id=? AND type=?",
            (ev["id"], flow_type)
        ).fetchone()
        if existing:
            continue

        if dry_run:
            print(f"  [DRY] ev={ev['id']} {flow_type} | {title[:60]} | {montant} €")
            inserted_cm += 1
            continue

        conn.execute(
            "INSERT INTO financial_flows (type, year, amount, from_id, to_id, event_id, description, source, confidence)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 'CM', 'probable')",
            (flow_type, year, int(montant) if montant else None,
             PREFET_ID, to_id, ev["id"], title[:200])
        )
        inserted_cm += 1

    if not dry_run:
        conn.commit()
    conn.close()

    prefix = "[DRY-RUN] " if dry_run else ""
    print(f"\n{prefix}✅ Subventions État terminé")
    print(f"  OFGL insérés : {inserted_ofgl}")
    print(f"  DGF DGCL     : {inserted_dgf}")
    print(f"  CM insérés   : {inserted_cm}")
    print(f"  Total        : {inserted_ofgl + inserted_dgf + inserted_cm}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
