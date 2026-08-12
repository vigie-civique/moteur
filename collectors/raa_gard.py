"""
raa_gard.py — RAA de la préfecture du Gard : mentions du vallon de la Salindrenque.

Scanne les recueils des actes administratifs (PDF, gard.gouv.fr) : téléchargement,
extraction texte (pdftotext, fallback pdfplumber), détection des mentions des
7 communes / CC CAC / Salindrenque. Seuls les recueils avec mention sont
archivés (raw_documents, source prefecture-gard) + un event 'raa_prefecture'
avec les extraits (page + contexte). La table raa_scans trace tous les PDFs
scannés : un recueil sans mention n'est jamais re-téléchargé.

Usage :
  python3 -m collectors.raa_gard --year 2026 --limit 5   # test
  python3 -m collectors.raa_gard                          # année courante
  python3 -m collectors.raa_gard --stats
"""
import argparse
import json
import re
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from .archive import archive_fetch
from .db import get_conn

BASE = "https://www.gard.gouv.fr"
YEAR_PATH = "/Publications/Recueil-des-Actes-Administratifs/Recueil-des-actes-administratifs-{year}"
UA = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36")}

MENTION_RE = re.compile(
    r"\b(Lasalle|Salindrenque|Salendrinque|Soudorgues|Colognac|Thoiras|Corb[èe]s"
    r"|Vabres|Sainte-Croix-de-Caderle|Saint-Bonnet-de-Salendrinque"
    r"|Causses\s+Aigoual|Nivoul[èe]de)\b", re.IGNORECASE)

# Termes thématiques (eau / assainissement / urbanisme coercitif) : relevés
# uniquement sur les pages qui mentionnent déjà une commune du vallon.
THEME_RE = re.compile(
    r"\b(assainissement|SPANC|loi sur l'eau|police de l'eau|pollution"
    r"|qualité de l'eau|mise en demeure|infraction[s]? d'urbanisme"
    r"|habitat léger|camping)\b", re.IGNORECASE)

CONTEXT = 150  # caractères de contexte autour d'une mention


def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS raa_scans (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            url        TEXT NOT NULL UNIQUE,
            filename   TEXT,
            date_doc   TEXT,
            pages      INTEGER,
            mentions   INTEGER DEFAULT 0,
            scanned_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()


def _get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def list_pdfs(year: int) -> list[str]:
    """URLs absolues des PDFs RAA de l'année (page année + sous-pages mois)."""
    year_url = BASE + YEAR_PATH.format(year=year)
    pages = [year_url]
    html = _get(year_url).decode("utf-8", errors="replace")
    # Sous-pages (certaines années sont découpées par mois)
    for m in re.finditer(r'href="(%s/[^"]+)"' % re.escape(YEAR_PATH.format(year=year)), html):
        sub = BASE + m.group(1)
        if sub not in pages:
            pages.append(sub)

    pdfs: list[str] = []
    for i, page_url in enumerate(pages):
        page_html = html if i == 0 else _get(page_url).decode("utf-8", errors="replace")
        for m in re.finditer(r'"(/contenu/telechargement/[^"]*\.pdf)"', page_html):
            url = BASE + urllib.parse.quote(m.group(1))
            if url not in pdfs:
                pdfs.append(url)
        time.sleep(0.3)
    return pdfs


def _date_from_name(name: str) -> str | None:
    m = re.search(r"du (\d{2}) (\d{2}) (\d{4})", name)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def extract_pages(raw: bytes) -> list[str]:
    """Texte du PDF, une entrée par page (pdftotext, fallback pdfplumber)."""
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(raw)
        tmp.flush()
        try:
            out = subprocess.run(
                ["pdftotext", "-q", tmp.name, "-"],
                capture_output=True, timeout=180, check=True
            ).stdout.decode("utf-8", errors="replace")
            return out.split("\f")
        except (FileNotFoundError, subprocess.SubprocessError):
            import pdfplumber
            with pdfplumber.open(tmp.name) as pdf:
                return [p.extract_text() or "" for p in pdf.pages]


def find_mentions(pages: list[str]) -> list[dict]:
    mentions = []
    for num, text in enumerate(pages, 1):
        page_hit = False
        for m in MENTION_RE.finditer(text):
            page_hit = True
            excerpt = " ".join(
                text[max(0, m.start() - CONTEXT):m.end() + CONTEXT].split())
            mentions.append({"page": num, "terme": m.group(1), "extrait": excerpt})
        if page_hit:
            for m in THEME_RE.finditer(text):
                excerpt = " ".join(
                    text[max(0, m.start() - CONTEXT):m.end() + CONTEXT].split())
                mentions.append({"page": num, "terme": f"THEME:{m.group(1)}",
                                 "extrait": excerpt})
    return mentions


def scan_pdf(conn, url: str, dry_run: bool = False) -> int:
    """Télécharge, scanne, archive/évente si mention. Retourne le nb de mentions."""
    fname = urllib.parse.unquote(url.rsplit("/", 1)[-1])
    raw = _get(url)
    pages = extract_pages(raw)
    mentions = find_mentions(pages)
    date_doc = _date_from_name(fname)

    if mentions and not dry_run:
        archive_fetch("prefecture-gard", url, raw, doc_type="pdf", title=fname,
                      metadata={"mentions": len(mentions)})
        exists = conn.execute(
            "SELECT id FROM events WHERE source='prefecture-gard' AND source_url=?",
            (url,)
        ).fetchone()
        if not exists:
            communes = sorted({m["terme"].title() for m in mentions
                               if not m["terme"].startswith("THEME:")})
            themes = sorted({m["terme"][6:].lower() for m in mentions
                             if m["terme"].startswith("THEME:")})
            if themes:
                communes.append("thèmes : " + ", ".join(themes))
            content = "\n".join(
                f"p.{m['page']} [{m['terme']}] …{m['extrait']}…" for m in mentions[:40])
            conn.execute(
                "INSERT INTO events (type, date, title, content, source, source_url, metadata)"
                " VALUES ('raa_prefecture', ?, ?, ?, 'prefecture-gard', ?, ?)",
                (date_doc, f"RAA Gard {fname.removesuffix('.pdf')} — "
                           f"{len(mentions)} mention(s) : {', '.join(communes)}",
                 content, url,
                 json.dumps({"mentions": mentions[:40]}, ensure_ascii=False))
            )
    if not dry_run:
        conn.execute(
            "INSERT OR REPLACE INTO raa_scans (url, filename, date_doc, pages, mentions)"
            " VALUES (?,?,?,?,?)",
            (url, fname, date_doc, len(pages), len(mentions))
        )
        conn.commit()
    return len(mentions)


def run(year: int, limit: int | None = None, dry_run: bool = False,
        delay: float = 2.0):
    conn = get_conn()
    ensure_table(conn)
    print(f"[raa] Liste des recueils {year}…")
    try:
        pdfs = list_pdfs(year)
    except Exception as e:
        print(f"[raa] index injoignable ({e}) — gard.gouv.fr limite les rafales, réessayer plus tard")
        conn.close()
        return
    done = {r[0] for r in conn.execute("SELECT url FROM raa_scans")}
    todo = [u for u in pdfs if u not in done]
    print(f"[raa] {len(pdfs)} PDFs en ligne, {len(todo)} à scanner"
          + (f" (limit {limit})" if limit else ""))

    scanned = hits = 0
    for url in (todo[:limit] if limit else todo):
        fname = urllib.parse.unquote(url.rsplit("/", 1)[-1])
        try:
            n = scan_pdf(conn, url, dry_run=dry_run)
        except Exception as e:
            print(f"  [raa] échec {fname} → {e}")
            continue
        scanned += 1
        if n:
            hits += 1
            print(f"  ✓ {fname} — {n} mention(s)")
        time.sleep(delay)  # gard.gouv.fr coupe les connexions après ~90 fetchs rapprochés

    print(f"[raa] OK — {scanned} scannés, {hits} avec mentions vallon")
    conn.close()


def show_stats():
    conn = get_conn(read_only=True)
    total, hits = conn.execute(
        "SELECT COUNT(*), SUM(mentions > 0) FROM raa_scans").fetchone()
    print(f"raa_scans : {total or 0} recueils scannés, {hits or 0} avec mentions")
    for r in conn.execute(
        "SELECT date_doc, filename, mentions FROM raa_scans"
        " WHERE mentions > 0 ORDER BY date_doc DESC LIMIT 20"):
        print(f"  {r[0]} {r[1][:60]:60} {r[2]:>3}")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="RAA préfecture du Gard — mentions vallon")
    ap.add_argument("--year", type=int, default=date.today().year)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true", help="Scan sans écrire")
    ap.add_argument("--delay", type=float, default=2.0,
                    help="Pause entre PDFs (s, défaut 2)")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()
    if args.stats:
        show_stats()
    else:
        run(args.year, limit=args.limit, dry_run=args.dry_run, delay=args.delay)
