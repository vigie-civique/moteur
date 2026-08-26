"""
Enrichissement des associations depuis le fichier Waldec RNA national (data.gouv.fr).
Fichier : https://object.files.data.gouv.fr/data-pipeline-open/rna/waldec.csv
Mis à jour mensuellement, ~1.2 GB, streamé ligne par ligne (filtre code postal).

Ce que ça apporte :
  - contacts.website  (champ siteweb du Waldec)
  - rna_id en format W (id → remplace l'ancien id_ex numérique)
  - siret croisé avec businesses table

Matching :
  - Primary  : rna_id DB (numérique) == id_ex Waldec
  - Secondary: rna_id DB (W-format)  == id Waldec
  - Fallback : nom normalisé (approximatif)

Usage :
    python3 -m collectors.rna_enrich              # toutes les assos sans website
    python3 -m collectors.rna_enrich --dry-run    # simulation
    python3 -m collectors.rna_enrich --all        # même celles déjà enrichies
    python3 -m collectors.rna_enrich --save-csv   # cache Waldec filtré dans data/rna_30460.csv
"""
import argparse
import csv
import io
import re
import sqlite3
import urllib.request
from pathlib import Path

from .archive import archive_fetch
from .config import cp_du_step

from .config import DB_PATH   # la base est nommée dans la config, pas ici
DATA_DIR   = Path(__file__).parent.parent / "data"
WALDEC_URL = "https://object.files.data.gouv.fr/data-pipeline-open/rna/waldec.csv"
from .config import CODE_POSTAL
from .config import HEADERS


# ── Download + filtre ─────────────────────────────────────────────────────────

def stream_waldec(code_postal: str = CODE_POSTAL,
                  cache_path: Path | None = None) -> list[dict]:
    """
    Stream le CSV Waldec national, filtre sur code_postal, retourne les lignes
    correspondantes. Utilise le cache si disponible.
    """
    if cache_path and cache_path.exists():
        print(f"  [rna_enrich] Cache trouvé : {cache_path}")
        with open(cache_path, encoding="utf-8") as f:
            return list(csv.DictReader(f))

    print(f"  [rna_enrich] Streaming Waldec RNA national (filtre {code_postal})…")
    req = urllib.request.Request(WALDEC_URL, headers=HEADERS)
    rows = []

    with urllib.request.urlopen(req, timeout=120) as resp:
        wrapper = io.TextIOWrapper(resp, encoding="utf-8", errors="replace")
        reader  = csv.DictReader(wrapper)
        count   = 0
        for row in reader:
            count += 1
            if count % 200_000 == 0:
                print(f"    … {count:,} lignes lues, {len(rows)} matchs 30460")
            if row.get("adrs_codepostal", "").strip() == code_postal:
                rows.append(row)

    print(f"  [rna_enrich] {len(rows)} associations trouvées pour {code_postal}")

    # Archive le sous-ensemble CP (le Waldec national ~1.2 GB est re-téléchargeable)
    if rows:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
        archive_fetch("rna-waldec", WALDEC_URL, buf.getvalue().encode("utf-8"),
                      doc_type="csv", title=f"waldec_{code_postal}.csv",
                      metadata={"cp": code_postal, "filtre": "adrs_codepostal"})

    if cache_path:
        DATA_DIR.mkdir(exist_ok=True)
        with open(cache_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys() if rows else [])
            writer.writeheader()
            writer.writerows(rows)
        print(f"  [rna_enrich] Cache sauvegardé : {cache_path}")

    return rows


# ── Matching ──────────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"['\-_.,;:!?()\"]", " ", s)
    s = re.sub(r"\b(l|le|la|les|de|du|des|un|une|d|l)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def build_waldec_index(rows: list[dict]) -> tuple[dict, dict, dict]:
    """
    Retourne trois index :
      by_idex  : {id_ex → row}          (ancien identifiant numérique)
      by_wid   : {id W-format → row}    (identifiant RNA actuel)
      by_name  : {nom_normalisé → row}  (fallback)
    """
    by_idex = {}
    by_wid  = {}
    by_name = {}
    for row in rows:
        idex  = row.get("id_ex", "").strip()
        wid   = row.get("id", "").strip()
        titre = _norm(row.get("titre", ""))
        if idex:
            by_idex[idex] = row
        if wid:
            by_wid[wid] = row
        if titre:
            by_name.setdefault(titre, row)  # garde la première occurrence
    return by_idex, by_wid, by_name


# ── DB helpers ────────────────────────────────────────────────────────────────

def upsert_contact(conn, entity_id: int, ctype: str, value: str) -> bool:
    value = value.strip().rstrip("/")
    if not value or len(value) < 5:
        return False
    if ctype == "website":
        # Normaliser les URLs Waldec mal formées (http:xxx → http://xxx)
        import re as _re
        value = _re.sub(r'^(https?):(?!//)(.)', r'\1://\2', value)
        if value.startswith("www."):
            value = "https://" + value
        elif not value.startswith("http"):
            return False   # valeur non-URL, ignorer
    existing = conn.execute(
        "SELECT 1 FROM contacts WHERE entity_id=? AND type=? AND value=?",
        (entity_id, ctype, value),
    ).fetchone()
    if existing:
        return False
    conn.execute(
        "INSERT INTO contacts (entity_id, type, value) VALUES (?,?,?)",
        (entity_id, ctype, value),
    )
    return True


# ── Collecteur principal ──────────────────────────────────────────────────────

def enrich(dry_run: bool = False, enrich_all: bool = False, save_csv: bool = False,
           cp: str = CODE_POSTAL):
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # Charger les associations cibles
    extra = "" if enrich_all else """
        AND NOT EXISTS (SELECT 1 FROM contacts c WHERE c.entity_id = e.id AND c.type='website')
    """
    db_assos = conn.execute(f"""
        SELECT e.id, e.name, a.rna_id, a.entity_id
        FROM entities e
        JOIN associations a ON a.entity_id = e.id
        WHERE e.type = 'association' {extra}
    """).fetchall()
    print(f"[rna_enrich] {len(db_assos)} associations à traiter")

    # Charger Waldec (streaming ou cache)
    cache = DATA_DIR / f"rna_{cp}.csv" if save_csv else None
    waldec_rows = stream_waldec(cp, cache_path=cache)
    by_idex, by_wid, by_name = build_waldec_index(waldec_rows)
    print(f"[rna_enrich] Index Waldec : {len(by_idex)} idex, {len(by_wid)} W-RNA, {len(by_name)} noms")

    stats = {
        "website_added": 0,
        "rna_updated":   0,
        "no_match":      0,
        "total_matched": 0,
    }

    for row in db_assos:
        eid    = row["id"]
        name   = row["name"] or ""
        rna_id = (row["rna_id"] or "").strip()

        # Trouver l'entrée Waldec correspondante
        wr = None
        if rna_id:
            if rna_id.startswith("W"):
                wr = by_wid.get(rna_id)
            else:
                wr = by_idex.get(rna_id)
        if not wr:
            wr = by_name.get(_norm(name))

        if not wr:
            stats["no_match"] += 1
            continue

        stats["total_matched"] += 1

        # ── Mettre à jour rna_id vers format W si nécessaire ──────────
        new_rna = wr.get("id", "").strip()
        if new_rna and new_rna.startswith("W") and rna_id != new_rna:
            if dry_run:
                print(f"  [DRY] eid={eid} {name[:40]} → rna_id: {rna_id} → {new_rna}")
            else:
                conn.execute(
                    "UPDATE associations SET rna_id=? WHERE entity_id=?",
                    (new_rna, eid),
                )
                if conn.execute("SELECT changes()").fetchone()[0]:
                    stats["rna_updated"] += 1

        # ── Website ───────────────────────────────────────────────────
        site = wr.get("siteweb", "").strip()
        if site:
            if dry_run:
                print(f"  [DRY] eid={eid} {name[:40]} → website: {site}")
                stats["website_added"] += 1
            else:
                if upsert_contact(conn, eid, "website", site):
                    stats["website_added"] += 1

    if not dry_run:
        conn.commit()
    conn.close()

    prefix = "[DRY-RUN] " if dry_run else ""
    print(f"\n{prefix}✅ Waldec RNA terminé")
    print(f"  matchés          : {stats['total_matched']} / {len(db_assos)}")
    print(f"  sans match       : {stats['no_match']}")
    print(f"  websites ajoutés : {stats['website_added']}")
    print(f"  rna_id → W-format: {stats['rna_updated']}")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Enrichit les associations depuis le fichier Waldec RNA national"
    )
    parser.add_argument("--dry-run",  action="store_true", help="Simulation sans écriture DB")
    parser.add_argument("--all",      action="store_true", help="Traiter toutes les assos")
    parser.add_argument("--save-csv", action="store_true",
                        help="Sauvegarder les assos du CP dans data/rna_<cp>.csv (cache)")
    parser.add_argument("--cp", default=None,
                        help="Code postal Waldec (défaut : tous les CP du périmètre)")
    args = parser.parse_args()
    cps = [args.cp] if args.cp else cp_du_step("rna")
    for cp in cps:
        enrich(dry_run=args.dry_run, enrich_all=args.all, save_csv=args.save_csv, cp=cp)
