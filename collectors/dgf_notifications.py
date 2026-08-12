"""
dgf_notifications.py — Dotations de l'État notifiées (DGF) par commune.

Source : DGCL « Dotations en ligne » (http://www.dotations-dgcl.interieur.gouv.fr).
Il n'existe pas d'API per-commune pour les exercices récents (2025/2026) : ce
collecteur **ingère un fichier exporté du portail DGCL** (Excel .xlsx ou CSV), ou
un CSV pointé par URL. Il détecte la colonne INSEE et les composantes DGF, filtre
sur les communes collectées (config.COMMUNES_INSEE) et insère dans `dotations_etat`.

OFGL (collecteur ofgl.py) couvre déjà 2017-2024 (comptes exécutés) ; ce collecteur
sert aux exercices notifiés non encore dans OFGL.

Usage :
  # 1) Sur le portail DGCL, exporter le fichier « DGF par commune » de l'exercice
  #    (Excel ou CSV) :
  #    http://www.dotations-dgcl.interieur.gouv.fr/consultation/dotations_en_ligne.php
  # 2) Vérifier le mapping détecté (ne touche pas la base) :
  ~/venvs/agents/bin/python -m collectors.dgf_notifications --year 2026 --file ~/Downloads/dgf_2026.xlsx --inspect
  # 3) Ingestion :
  ~/venvs/agents/bin/python -m collectors.dgf_notifications --year 2026 --file ~/Downloads/dgf_2026.xlsx
  ~/venvs/agents/bin/python -m collectors.dgf_notifications --year 2025 --csv-url https://.../dgf_2025.csv
  ~/venvs/agents/bin/python -m collectors.dgf_notifications --stats
"""
import argparse
import csv
import io
import sqlite3
import unicodedata
import urllib.request
from pathlib import Path

from .archive import archive_fetch
from .config import COMMUNES, COMMUNES_INSEE, HEADERS

DB_PATH = Path(__file__).parent.parent / "db" / "lasalle.db"

# Composante DGF → mots-clés (sur en-tête normalisé sans accents) à reconnaître
COMPOSANTES = {
    "Dotation forfaitaire":             ["dotation forfaitaire", "dot forfaitaire"],
    "DSR (solidarité rurale)":          ["solidarite rurale", "dsr"],
    "DSU (solidarité urbaine)":         ["solidarite urbaine", "dsu"],
    "DNP (nationale de péréquation)":   ["nationale de perequation", "dnp"],
    "DGF totale":                       ["dotation globale de fonctionnement",
                                         "montant dgf", "total dgf", "dgf totale"],
}


def _norm(s) -> str:
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.lower().split())


def _to_float(v):
    """Parse un montant en format FR ('1 234,56', espaces insécables, '-' = vide)."""
    if v is None:
        return None
    s = str(v).replace("\xa0", "").replace(" ", "").replace(",", ".").strip()
    if s in ("", "-", "nd", "n/a", "null"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------- lecture fichier
def load_rows(path: Path | None, csv_url: str | None) -> list[dict]:
    """Retourne une liste de dict {header: valeur}, depuis .xlsx, .csv ou URL CSV."""
    if csv_url:
        req = urllib.request.Request(csv_url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=60) as r:
            raw_b = r.read()
        archive_fetch("dgcl-dgf", csv_url, raw_b, doc_type="csv")
        return _rows_from_csv(raw_b.decode("utf-8", errors="replace"))

    if not path or not path.exists():
        raise FileNotFoundError(f"Fichier introuvable : {path}")

    raw_b = path.read_bytes()
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        archive_fetch("dgcl-dgf", None, raw_b, doc_type="xlsx", title=path.name)
        return _rows_from_xlsx(path)
    archive_fetch("dgcl-dgf", None, raw_b, doc_type="csv", title=path.name)
    return _rows_from_csv(raw_b.decode("utf-8", errors="replace"))


def _rows_from_csv(text: str) -> list[dict]:
    # DGCL exporte souvent en ';'. Sniff sinon.
    sample = text[:4096]
    delim = ";" if sample.count(";") >= sample.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows = [r for r in reader if any(c.strip() for c in r)]
    hdr_idx = _find_header_row(rows)
    headers = [h.strip() for h in rows[hdr_idx]]
    return [dict(zip(headers, r)) for r in rows[hdr_idx + 1:]]


def _rows_from_xlsx(path: Path) -> list[dict]:
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    grid = [[("" if c is None else c) for c in row]
            for row in ws.iter_rows(values_only=True)]
    grid = [r for r in grid if any(str(c).strip() for c in r)]
    hdr_idx = _find_header_row(grid)
    headers = [str(h).strip() for h in grid[hdr_idx]]
    return [dict(zip(headers, r)) for r in grid[hdr_idx + 1:]]


def _find_header_row(rows: list[list]) -> int:
    """Ligne d'en-tête = 1ère ligne contenant 'insee' ou 'commune'/'departement'."""
    for i, r in enumerate(rows[:15]):
        cells = " ".join(_norm(c) for c in r)
        if "insee" in cells or ("commune" in cells and "departement" in cells) \
           or "code commune" in cells:
            return i
    return 0


# ---------------------------------------------------------------- mapping colonnes
def detect_columns(headers: list[str]) -> dict:
    """Repère colonne INSEE (ou dep+com) et colonnes composantes DGF."""
    norm_map = {h: _norm(h) for h in headers}
    info = {"insee": None, "dep": None, "com": None, "nom": None, "composantes": {}}

    for h, n in norm_map.items():
        if info["insee"] is None and ("insee" in n or "code insee" in n):
            info["insee"] = h
        if info["dep"] is None and ("departement" in n or n in ("dep", "code dep")):
            info["dep"] = h
        if info["com"] is None and ("code commune" in n or n == "com" or "code com" in n):
            info["com"] = h
        if info["nom"] is None and ("nom commune" in n or n in ("commune", "libelle", "nom")):
            info["nom"] = h

    # Composantes : on prend la 1ʳᵉ colonne dont l'en-tête contient un mot-clé
    for comp, keys in COMPOSANTES.items():
        for h, n in norm_map.items():
            if any(k in n for k in keys):
                info["composantes"][comp] = h
                break
    return info


def row_insee(row: dict, info: dict) -> str | None:
    if info["insee"]:
        v = str(row.get(info["insee"], "")).strip().split(".")[0]
        return v.zfill(5) if v.isdigit() else (v or None)
    if info["dep"] and info["com"]:
        dep = str(row.get(info["dep"], "")).strip().zfill(2)
        com = str(row.get(info["com"], "")).strip().split(".")[0].zfill(3)
        if dep.isdigit() and com.isdigit():
            return (dep + com)[:5]
    return None


# ---------------------------------------------------------------- base
def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dotations_etat (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            year        INTEGER NOT NULL,
            insee       TEXT NOT NULL,
            commune     TEXT,
            composante  TEXT NOT NULL,
            montant     REAL,
            source      TEXT DEFAULT 'DGCL',
            raw_label   TEXT,
            created_at  TEXT DEFAULT (datetime('now')),
            UNIQUE(year, insee, composante)
        )
    """)


def import_dgf(year: int, path: Path | None, csv_url: str | None,
               inspect: bool = False, only_insee: list[str] | None = None):
    rows = load_rows(path, csv_url)
    if not rows:
        print("[dgf] Aucune ligne lue."); return
    headers = list(rows[0].keys())
    info = detect_columns(headers)

    print(f"[dgf] {len(rows)} lignes, {len(headers)} colonnes")
    print(f"[dgf] INSEE → {info['insee'] or f'(dep={info['dep']} + com={info['com']})'}")
    print(f"[dgf] composantes détectées :")
    for comp, col in info["composantes"].items():
        print(f"        {comp:34} ← « {col} »")
    if not info["composantes"]:
        print("  [!] Aucune colonne DGF reconnue — vérifie les en-têtes ci-dessous :")
        for h in headers:
            print(f"        - {h}")
        return

    targets = only_insee or COMMUNES_INSEE
    found = {}
    for row in rows:
        ins = row_insee(row, info)
        if ins in targets:
            found[ins] = row

    if inspect:
        print(f"\n[dgf] --inspect : {len(found)}/{len(targets)} communes du périmètre trouvées")
        for ins in targets:
            row = found.get(ins)
            nom = COMMUNES.get(ins, {}).get("nom", ins)
            if not row:
                print(f"  {ins} {nom:32} — ABSENTE du fichier")
                continue
            vals = {c: _to_float(row.get(col)) for c, col in info["composantes"].items()}
            print(f"  {ins} {nom:32} " +
                  " | ".join(f"{c.split()[0]}={v}" for c, v in vals.items()))
        print("\n[dgf] inspection seule — rien écrit en base. Retire --inspect pour ingérer.")
        return

    conn = sqlite3.connect(str(DB_PATH))
    ensure_table(conn)
    n_ins = 0
    with conn:
        for ins in targets:
            row = found.get(ins)
            if not row:
                print(f"  [dgf] {ins} absente du fichier — ignorée")
                continue
            nom = COMMUNES.get(ins, {}).get("nom", ins)
            comp_vals = {c: _to_float(row.get(col)) for c, col in info["composantes"].items()}

            # DGF totale : explicite sinon somme des composantes connues
            if comp_vals.get("DGF totale") is None:
                parts = [comp_vals.get(k) for k in
                         ("Dotation forfaitaire", "DSR (solidarité rurale)",
                          "DSU (solidarité urbaine)", "DNP (nationale de péréquation)")]
                parts = [p for p in parts if p is not None]
                if parts:
                    comp_vals["DGF totale"] = round(sum(parts), 2)

            for comp, montant in comp_vals.items():
                if montant is None:
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO dotations_etat"
                    " (year,insee,commune,composante,montant,source,raw_label)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (year, ins, nom, comp, montant, "DGCL",
                     info["composantes"].get(comp))
                )
                n_ins += 1
            print(f"  [dgf] {ins} {nom} — {sum(1 for v in comp_vals.values() if v is not None)} composantes")

    print(f"[dgf] OK — {n_ins} lignes (year={year}) dans dotations_etat")


def show_stats():
    conn = sqlite3.connect(str(DB_PATH))
    ensure_table(conn)
    rows = conn.execute(
        "SELECT year, commune, composante, montant FROM dotations_etat"
        " ORDER BY year DESC, commune, composante"
    ).fetchall()
    if not rows:
        print("[dgf] Table dotations_etat vide."); return
    print(f"{'année':6} {'commune':32} {'composante':34} {'montant':>12}")
    for y, c, comp, m in rows:
        print(f"{y:<6} {c:32} {comp:34} {m:>12,.0f}")


def main():
    ap = argparse.ArgumentParser(description="Ingestion DGF notifiée DGCL (par commune)")
    ap.add_argument("--year", type=int, help="Exercice (ex: 2025, 2026)")
    ap.add_argument("--file", help="Fichier DGCL exporté (.xlsx ou .csv)")
    ap.add_argument("--csv-url", help="URL d'un CSV DGF à télécharger")
    ap.add_argument("--inspect", action="store_true",
                    help="Affiche le mapping + valeurs détectées sans rien écrire")
    ap.add_argument("--insee", help="Limiter à un/des INSEE (séparés par virgule)")
    ap.add_argument("--stats", action="store_true", help="Affiche le contenu en base")
    args = ap.parse_args()

    if args.stats:
        show_stats(); return
    if not args.year or (not args.file and not args.csv_url):
        ap.error("--year et (--file ou --csv-url) requis (ou --stats)")

    only = [s.strip() for s in args.insee.split(",")] if args.insee else None
    import_dgf(args.year, Path(args.file) if args.file else None,
               args.csv_url, inspect=args.inspect, only_insee=only)


if __name__ == "__main__":
    main()
