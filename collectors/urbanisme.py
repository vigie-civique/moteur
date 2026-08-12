"""
urbanisme.py — Statut urbanistique de Lasalle + mentions CM

Sources :
  1. Faits connus (RNU, PLU en cours) → events + metadata structurée
  2. CM délibérations → extractions des mentions PLU, PC, taxe aménagement
  3. GPU/IGN → zones d'urbanisme via bbox (best-effort)

Usage :
  python3 -m collectors.urbanisme
  python3 -m collectors.urbanisme --dry-run
"""

import argparse
import json
import re
import sqlite3
from pathlib import Path

DB_PATH     = Path(__file__).parent.parent / "db" / "lasalle.db"
COMMUNE_ID  = 63
COMMUNE_INSEE = "30140"

# Regex de détection dans le contenu des CM
RE_PLU     = re.compile(r'\bPLU\b|\bplan local d.urbanisme\b', re.I)
RE_PC      = re.compile(r'permis de construire', re.I)
RE_RNU     = re.compile(r'\bRNU\b|\brèglement national d.urbanisme\b', re.I)
RE_CARTE   = re.compile(r'carte communale', re.I)
RE_PADD    = re.compile(r'\bPADD\b|\bprojet d.aménagement et de développement', re.I)
RE_TAXE_AM = re.compile(r'taxe d.aménagement', re.I)

# Statut PLU connu au moment du dernier scraping
PLU_STATUS = {
    "statut":       "en_cours",
    "document":     "PLU",
    "doc_precedent": "RNU",
    "commission_responsable": "Commission Urbanisme – PLU",
    "responsable_elu": "M. Alain SERRE",
    "bureau_etudes": "Stéphane GAZABRE",
    "avancement":   "PADD en cours de finalisation",
    "reunion_publique": "2024-06-07",
    "note": "Commune sous RNU en attente d'approbation du PLU. Travaux engagés depuis 2023, ralentissements signalés. Réunion publique PADD tenue le 7 juin 2024.",
}


def _event_exists(conn, source_ref: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM events WHERE source=? AND type='urbanisme' LIMIT 1",
        (source_ref,)
    ).fetchone() is not None


def run(dry_run: bool = False):
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    inserted = 0

    # ── 1. Statut RNU / PLU en cours ─────────────────────────────────────────
    print("\n[1] Enregistrement statut urbanistique…")
    ref_rnu = "urbanisme:lasalle:RNU"
    ref_plu = "urbanisme:lasalle:PLU_en_cours"

    for ref, title, meta in [
        (ref_rnu,
         "Lasalle — Commune sous Règlement National d'Urbanisme (RNU)",
         {"type": "statut_urbanistique", "document": "RNU",
          "note": "Lasalle ne dispose pas de PLU approuvé. S'applique à titre supplétif le RNU (R111-1 et s. du code de l'urbanisme)."}),
        (ref_plu,
         "Lasalle — PLU en cours d'élaboration",
         PLU_STATUS),
    ]:
        if _event_exists(conn, ref):
            print(f"  déjà présent: {title[:60]}")
            continue
        if dry_run:
            print(f"  [DRY] {title[:70]}")
            inserted += 1
            continue
        conn.execute(
            "INSERT INTO events (type, date, title, source, metadata)"
            " VALUES ('urbanisme', '2026-01-01', ?, ?, ?)",
            (title, ref, json.dumps(meta, ensure_ascii=False))
        )
        ev_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT OR IGNORE INTO event_entities (event_id, entity_id, role)"
            " VALUES (?, ?, 'sujet')",
            (ev_id, COMMUNE_ID)
        )
        inserted += 1

    # ── 2. Extraction mentions CM ─────────────────────────────────────────────
    print("\n[2] Analyse des délibérations CM…")

    cm_events = conn.execute(
        """SELECT id, date, title, content FROM events
           WHERE type='deliberation' AND content IS NOT NULL AND content != ''
           ORDER BY date"""
    ).fetchall()

    print(f"  {len(cm_events)} délibérations avec contenu à analyser")

    plu_mentions   = []
    pc_mentions    = []
    taxe_mentions  = []

    for ev in cm_events:
        content = ev["content"] or ""
        title   = ev["title"] or ""

        has_plu   = bool(RE_PLU.search(content) or RE_PLU.search(title) or RE_PADD.search(content))
        has_pc    = bool(RE_PC.search(content) or RE_PC.search(title))
        has_taxe  = bool(RE_TAXE_AM.search(content) or RE_TAXE_AM.search(title))

        if has_plu:
            # Extraire les contextes PLU les plus informatifs
            snippets = []
            for m in RE_PLU.finditer(content):
                start = max(0, m.start() - 80)
                end   = min(len(content), m.end() + 200)
                snippets.append(content[start:end].replace("\n", " ").strip())
            plu_mentions.append({
                "event_id": ev["id"],
                "date":     ev["date"],
                "title":    title,
                "snippets": snippets[:3],
            })

        if has_pc:
            pc_snippets = []
            for m in RE_PC.finditer(content):
                start = max(0, m.start() - 60)
                end   = min(len(content), m.end() + 200)
                pc_snippets.append(content[start:end].replace("\n", " ").strip())
            pc_mentions.append({
                "event_id": ev["id"],
                "date":     ev["date"],
                "title":    title,
                "snippets": pc_snippets[:2],
            })

        if has_taxe:
            taxe_mentions.append({
                "event_id": ev["id"],
                "date":     ev["date"],
                "title":    title,
            })

    print(f"  → PLU mentionné dans {len(plu_mentions)} délibérations")
    print(f"  → Permis de construire mentionné dans {len(pc_mentions)} délibérations")
    print(f"  → Taxe d'aménagement mentionnée dans {len(taxe_mentions)} délibérations")

    # ── 3. Événement synthèse PLU ─────────────────────────────────────────────
    ref_synthese = "urbanisme:lasalle:PLU_synthese_CM"
    if not _event_exists(conn, ref_synthese) and plu_mentions:
        title_s = f"PLU Lasalle — {len(plu_mentions)} mentions dans les délibérations CM (2023-2025)"
        meta_s = {
            "type":             "synthese_plu",
            "nb_deliberations": len(plu_mentions),
            "periode":          "2023-2025",
            "statut":           "en_cours",
            "evenements_source": [m["event_id"] for m in plu_mentions],
            "extraits_cles": [
                {"date": m["date"], "titre": m["title"][:60], "extrait": m["snippets"][0][:200] if m["snippets"] else ""}
                for m in plu_mentions[:5]
            ],
        }
        if dry_run:
            print(f"  [DRY] synthèse PLU: {title_s[:70]}")
            inserted += 1
        else:
            conn.execute(
                "INSERT INTO events (type, date, title, source, metadata)"
                " VALUES ('urbanisme', ?, ?, ?, ?)",
                (plu_mentions[-1]["date"], title_s, ref_synthese,
                 json.dumps(meta_s, ensure_ascii=False))
            )
            ev_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                "INSERT OR IGNORE INTO event_entities (event_id, entity_id, role)"
                " VALUES (?, ?, 'sujet')",
                (ev_id, COMMUNE_ID)
            )
            inserted += 1

    # ── 4. Affichage résumé ───────────────────────────────────────────────────
    if dry_run or True:
        print("\n  PLU — extraits clés:")
        for m in plu_mentions:
            print(f"    [{m['date']}] {m['title'][:55]}")
            for s in m["snippets"][:1]:
                print(f"       → {s[:120]}")

        print("\n  Permis de construire mentionnés:")
        for m in pc_mentions:
            print(f"    [{m['date']}] {m['title'][:55]}")
            for s in m["snippets"][:1]:
                print(f"       → {s[:120]}")

    if not dry_run:
        conn.commit()
    conn.close()

    prefix = "[DRY-RUN] " if dry_run else ""
    print(f"\n{prefix}✅ Urbanisme terminé — {inserted} événements insérés")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
