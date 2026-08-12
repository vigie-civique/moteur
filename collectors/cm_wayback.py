"""
cm_wayback.py — Collecteur CR du Conseil Municipal via la Wayback Machine
==========================================================================
Les CR anciens (2016-2023) ne sont plus sur lasalle.fr mais archivés sur
web.archive.org sous forme de PDF. Ce collecteur :
  1. liste les snapshots de la page d'archive /compte-rendus-des-conseils (CDX),
  2. extrait de chaque snapshot les liens vers les PDF de CR,
  3. télécharge chaque PDF (cache local data/cm_records_pdf/),
  4. extrait le texte (pdfplumber) + la date depuis le nom de fichier,
  5. stocke un event `conseil_municipal` par CM (contenu plein-texte → FTS),
     SANS écraser les CM déjà présents en base (enrichir, jamais écraser).

Usage :
  ~/venvs/agents/bin/python3 -m collectors.cm_wayback --dry-run        # liste sans stocker
  ~/venvs/agents/bin/python3 -m collectors.cm_wayback                  # ingère tout (2016+)
  ~/venvs/agents/bin/python3 -m collectors.cm_wayback --limit 5        # test sur 5 CR
"""
import argparse
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pdfplumber

from .db import get_conn

ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = ROOT / "data" / "cm_records_pdf"
LISTING_URL = "www.lasalle.fr/compte-rendus-des-conseils"
FICHIERS = "lasalle.fr/sites/default/files/medias/fichiers"
UA = {"User-Agent": "Mozilla/5.0 (LasalleOSINT)"}

MONTHS = {
    "janvier": 1, "janv": 1,
    "fevrier": 2, "février": 2, "fev": 2, "fév": 2,
    "mars": 3,
    "avril": 4, "avr": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7, "juil": 7,
    "aout": 8, "août": 8,
    "septembre": 9, "sept": 9, "sep": 9,
    "octobre": 10, "oct": 10,
    "novembre": 11, "nov": 11,
    "decembre": 12, "décembre": 12, "dec": 12, "déc": 12,
}
_MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))
_DATE_RE = re.compile(rf"(\d{{1,2}})\s*({_MONTH_ALT})\s*(20\d{{2}})", re.I)
_CR_NAME = re.compile(r"(cm|conseil|compte.?rendu|seance|séance)", re.I)


def _http(url: str, timeout=40, retries=3) -> bytes:
    last = None
    for attempt in range(retries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
        except Exception as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise last


def listing_snapshots() -> list[str]:
    """Timestamps des snapshots de la page d'archive CR (1 par mois max)."""
    url = ("https://web.archive.org/cdx/search/cdx?url=" + LISTING_URL +
           "&output=text&fl=timestamp&collapse=timestamp:6")
    for attempt in range(4):
        try:
            txt = _http(url).decode("utf-8", "replace")
            ts = [l.strip() for l in txt.splitlines() if l.strip().isdigit()]
            if ts:
                return ts
        except Exception as e:
            print(f"  [cdx retry {attempt}] {e}")
        time.sleep(2)
    return []


def pdf_links_from_snapshot(ts: str) -> dict[str, str]:
    """Retourne {url_pdf_original: timestamp} pour les PDF de CR d'un snapshot."""
    snap = f"https://web.archive.org/web/{ts}/https://{LISTING_URL}"
    try:
        html = _http(snap).decode("utf-8", "replace")
    except Exception as e:
        print(f"  [snapshot {ts}] {e}")
        return {}
    out = {}
    for m in re.finditer(r'href="([^"]+\.pdf)"', html, re.I):
        href = m.group(1)
        # normaliser : retirer le préfixe wayback, garder l'URL lasalle d'origine
        m2 = re.search(r"(https?://[^\s\"]*lasalle\.fr/sites/default/files/[^\s\"]+\.pdf)", href, re.I)
        orig = m2.group(1) if m2 else None
        if not orig and FICHIERS.split("lasalle.fr")[1] in href:
            orig = "https://www." + FICHIERS + href.split("fichiers")[-1]
        if not orig:
            continue
        name = urllib.parse.unquote(orig.rsplit("/", 1)[-1])
        if _CR_NAME.search(name) and _DATE_RE.search(urllib.parse.unquote(orig)):
            out.setdefault(orig, ts)
    return out


def parse_date(orig_url: str) -> str | None:
    name = urllib.parse.unquote(orig_url.rsplit("/", 1)[-1])
    m = _DATE_RE.search(name)
    if not m:
        return None
    day, mon, year = int(m.group(1)), MONTHS[m.group(2).lower()], int(m.group(3))
    if not (1 <= day <= 31 and 2000 <= year <= 2030):
        return None
    return f"{year:04d}-{mon:02d}-{day:02d}"


def download_pdf(orig_url: str, ts: str) -> Path | None:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", urllib.parse.unquote(orig_url.rsplit("/", 1)[-1]))
    dest = PDF_DIR / safe
    if dest.exists() and dest.stat().st_size > 1000:
        return dest
    wb = f"https://web.archive.org/web/{ts}id_/{orig_url}"
    try:
        data = _http(wb)
        if not data.startswith(b"%PDF"):
            return None
        dest.write_bytes(data)
        return dest
    except Exception as e:
        print(f"  [dl {safe}] {e}")
        return None


def pdf_text(path: Path) -> str:
    try:
        with pdfplumber.open(path) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception as e:
        print(f"  [pdf {path.name}] {e}")
        return ""


def existing_cm_dates(conn) -> set[str]:
    return {r[0] for r in conn.execute(
        "SELECT date FROM events WHERE type='conseil_municipal'")}


def collect(limit: int | None = None, dry_run: bool = False) -> dict:
    conn = get_conn()
    report = {"found": 0, "new": 0, "skipped_existing": 0, "no_date": 0, "errors": 0, "dates": []}
    try:
        have = existing_cm_dates(conn)
        # 1. énumérer les PDF sur tous les snapshots de la page d'archive
        pdfs: dict[str, str] = {}
        for ts in listing_snapshots():
            pdfs.update(pdf_links_from_snapshot(ts))
        # dédup par date (garde 1 PDF par date)
        by_date: dict[str, str] = {}
        for orig, ts in sorted(pdfs.items()):
            d = parse_date(orig)
            if not d:
                report["no_date"] += 1
                continue
            by_date.setdefault(d, orig)
        report["found"] = len(by_date)
        print(f"[cm_wayback] {len(pdfs)} liens PDF, {len(by_date)} CM datés distincts "
              f"(de {min(by_date) if by_date else '?'} à {max(by_date) if by_date else '?'})")

        todo = sorted(d for d in by_date if d not in have)
        report["skipped_existing"] = len(by_date) - len(todo)
        if limit:
            todo = todo[:limit]

        for d in todo:
            orig = by_date[d]
            ts = pdfs[orig]
            if dry_run:
                print(f"  [DRY] {d} ← {orig.rsplit('/',1)[-1]}")
                report["new"] += 1
                report["dates"].append(d)
                continue
            path = download_pdf(orig, ts)
            if not path:
                report["errors"] += 1
                continue
            text = pdf_text(path)
            if len(text) < 200:
                report["errors"] += 1
                continue
            meta = {"wayback": f"https://web.archive.org/web/{ts}id_/{orig}",
                    "ingested": "cm_wayback"}
            conn.execute(
                """INSERT INTO events (type, date, title, content, source, source_url, metadata)
                   VALUES ('conseil_municipal', ?, ?, ?, 'lasalle.fr (Wayback)', ?, ?)""",
                (d, f"CM du {d}", text, orig, json.dumps(meta, ensure_ascii=False)))
            report["new"] += 1
            report["dates"].append(d)
            print(f"  ✓ {d}  ({len(text)} car.)  {orig.rsplit('/',1)[-1]}")

        if not dry_run:
            conn.commit()
        return report
    finally:
        conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Ingestion CR du CM depuis la Wayback Machine")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    rep = collect(limit=args.limit, dry_run=args.dry_run)
    print("\n[cm_wayback] terminé :",
          {k: v for k, v in rep.items() if k != "dates"})
    if rep["dates"]:
        print("  dates traitées :", ", ".join(rep["dates"]))
