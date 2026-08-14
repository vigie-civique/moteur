"""
urbanisme.py — Statut urbanistique de la commune + mentions dans les CM

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

from .config import DB_PATH   # la base est nommée dans la config, pas ici
from .config import COMMUNE_INSEE, COMMUNE_NAME
from .db import pivot_ids

# Regex de détection dans le contenu des CM
RE_PLU     = re.compile(r'\bPLU\b|\bplan local d.urbanisme\b', re.I)
RE_PC      = re.compile(r'permis de construire', re.I)
RE_RNU     = re.compile(r'\bRNU\b|\brèglement national d.urbanisme\b', re.I)
RE_CARTE   = re.compile(r'carte communale', re.I)
RE_PADD    = re.compile(r'\bPADD\b|\bprojet d.aménagement et de développement', re.I)
RE_TAXE_AM = re.compile(r'taxe d.aménagement', re.I)

# Le statut urbanistique d'une commune se déclare dans config/seed_local.json
# (clé `urbanisme`), jamais ici : cf. _statuts_seed() et le commentaire de run().


def _event_exists(conn, source_ref: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM events WHERE source=? AND type='urbanisme' LIMIT 1",
        (source_ref,)
    ).fetchone() is not None


def _statuts_seed() -> list[tuple]:
    """Statut urbanistique déclaré à la main, s'il l'a été.

    Format attendu dans config/seed_local.json :
        "urbanisme": [{"ref": "RNU", "titre": "…", "metadata": {…}}]
    """
    import json as _json
    from pathlib import Path as _Path
    chemin = _Path(__file__).resolve().parent.parent / "config" / "seed_local.json"
    try:
        seed = _json.loads(chemin.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return []
    from .config import COMMUNE_NAME
    sorties = []
    for item in seed.get("urbanisme") or []:
        ref = f"urbanisme:{COMMUNE_NAME.lower()}:{item['ref']}"
        sorties.append((ref, item["titre"], item.get("metadata") or {}))
    return sorties


def run(dry_run: bool = False):
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    COMMUNE_ID = pivot_ids(conn)["commune"]

    inserted = 0

    # ── 1. Statut RNU / PLU en cours ─────────────────────────────────────────
    #
    # Ce bloc écrivait en dur « Lasalle est sous RNU, PLU en cours ». C'est un
    # FAIT sur une commune, pas une règle de collecte : rejoué ici, il aurait
    # inséré dans la base de Brassac le statut urbanistique d'une commune du
    # Gard, daté et sourcé comme s'il avait été vérifié. Le statut se déclare
    # donc dans `config/seed_local.json` (clé `urbanisme`), et sans déclaration
    # rien n'est écrit — une lacune vaut mieux qu'un fait importé d'ailleurs.
    print("\n[1] Enregistrement statut urbanistique…")
    statuts = _statuts_seed()
    if not statuts:
        print("  aucun statut déclaré dans seed_local.json → rien à enregistrer")
    for ref, title, meta in statuts:
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
    ref_synthese = f"urbanisme:{COMMUNE_NAME.lower()}:PLU_synthese_CM"
    if not _event_exists(conn, ref_synthese) and plu_mentions:
        title_s = (f"PLU {COMMUNE_NAME} — {len(plu_mentions)} mentions dans les "
                   f"délibérations du conseil municipal")
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
