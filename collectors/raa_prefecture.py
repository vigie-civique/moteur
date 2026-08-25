"""
raa_prefecture.py — RAA de la préfecture : mentions des communes du périmètre.

Scanne les recueils des actes administratifs (PDF) : téléchargement, extraction
texte (pdftotext, fallback pdfplumber), détection des mentions des communes du
registre et de l'EPCI. Seuls les recueils avec mention sont archivés
(raw_documents) + un event 'raa_prefecture' avec les extraits (page + contexte).
La table raa_scans trace tous les PDF scannés : un recueil sans mention n'est
jamais re-téléchargé.

Adapté du collecteur écrit pour gard.gouv.fr. L'arborescence n'est PAS la même
d'une préfecture à l'autre : le Gard listait ses PDF sur la page de l'année (ou
d'un mois), le Tarn ajoute un niveau — année → mois → page de l'acte — et
pagine les mois par tranches de dix. Le parcours est donc devenu récursif, ce
qui couvre les deux formes. C'est le genre de détail qui décide du temps de
portage : la logique de détection, elle, n'a pas bougé d'une ligne.

Usage :
  python3 -m collectors.raa_prefecture --year 2026 --limit 5   # test
  python3 -m collectors.raa_prefecture                          # année courante
  python3 -m collectors.raa_prefecture --stats
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
from .connecteurs.base import date_fr
from .config import (COMMUNES, DEPARTEMENT, EPCI_NOM, PREFECTURE_RAA_PATH,
                     PREFECTURE_URL)
from .db import get_conn

BASE = PREFECTURE_URL
YEAR_PATH = PREFECTURE_RAA_PATH
SOURCE = f"prefecture-{DEPARTEMENT}"
# Profondeur d'exploration sous la page de l'année (mois, puis actes).
MAX_NIVEAUX = 3
# Le site de la préfecture du Tarn coupe les connexions quand on enchaîne les
# requêtes, et le blocage porte sur l'adresse IP : une exploration trop rapide
# rend le site injoignable pour plusieurs minutes, curl compris. L'arborescence
# à trois niveaux demandant plus de deux cents pages par année, la politesse
# n'est pas optionnelle ici — elle conditionne le fait d'obtenir quoi que ce soit.
DELAI_PAGE = 1.5
MAX_PAGES = 400
UA = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36")}

# Termes déclencheurs : les communes du registre et le nom de l'EPCI. Construit
# depuis la config plutôt que saisi — une liste en dur ici se serait décorrélée
# du périmètre au premier changement de registre.
_TERMES = sorted({c["nom"] for c in COMMUNES.values()}
                 | {mot for mot in re.split(r"[\s'’-]+", EPCI_NOM)
                    if len(mot) > 5 and mot.lower() not in
                    ("communaute", "communauté", "communes", "agglomeration",
                     "agglomération")},
                 key=len, reverse=True)
MENTION_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in _TERMES) + r")\b", re.IGNORECASE)

# Termes thématiques (eau / assainissement / urbanisme coercitif) : relevés
# uniquement sur les pages qui mentionnent déjà une commune du périmètre.
THEME_RE = re.compile(
    r"\b(assainissement|SPANC|loi sur l'eau|police de l'eau|pollution"
    r"|qualité de l'eau|mise en demeure|infraction[s]? d'urbanisme"
    r"|habitat léger|camping)\b", re.IGNORECASE)

CONTEXT = 150  # caractères de contexte autour d'une mention


# Définie dans `erreurs` depuis le 25/08/2026 : `wayback` avait le même défaut,
# et deux collecteurs ne peuvent pas porter deux exceptions du même nom sans que
# l'un rattrape mal celle de l'autre. Réexportée ici, c'est le nom sous lequel
# elle est levée et attrapée depuis le début.
from .erreurs import SourceInterrompue  # noqa: E402,F401 — réexport


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


def _get(url: str, timeout: int = 60, tentatives: int = 3) -> bytes:
    """GET avec réessais.

    Le site du Tarn ferme la connexion sans réponse quand on enchaîne les
    pages : l'arborescence à trois niveaux fait passer d'une dizaine de
    requêtes par année (Gard) à plus de deux cents. Sans réessai, un quart des
    recueils manquait à l'appel — et rien ne le signalait, puisque chaque échec
    ne coûtait qu'une ligne de log.
    """
    dernier = None
    for essai in range(tentatives):
        req = urllib.request.Request(url, headers=UA)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            dernier = e
            time.sleep(1.5 * (essai + 1))
    raise dernier


def list_pdfs(year: int) -> list[str]:
    """URLs absolues des PDF du RAA de l'année.

    Descend récursivement sous la page de l'année : les préfectures découpent
    par mois, parfois par acte, et paginent avec `/(offset)/N`. On explore donc
    tout ce qui reste sous le chemin de l'année, en s'arrêtant à MAX_NIVEAUX.
    """
    racine = YEAR_PATH.format(year=year)
    a_visiter = [(BASE + racine, 0)]
    vues, pdfs = set(), []

    while a_visiter and len(vues) < MAX_PAGES:
        page_url, niveau = a_visiter.pop(0)
        if page_url in vues:
            continue
        vues.add(page_url)
        try:
            html = _get(page_url).decode("utf-8", errors="replace")
        except Exception as e:
            print(f"  [raa][erreur] {page_url} → {e}")
            continue

        for m in re.finditer(r'"(/contenu/telechargement/[^"]*\.pdf)"', html):
            url = BASE + urllib.parse.quote(m.group(1))
            if url not in pdfs:
                pdfs.append(url)

        if niveau < MAX_NIVEAUX:
            for m in re.finditer(r'href="(%s/[^"#?]+)"' % re.escape(racine), html):
                sous = BASE + m.group(1)
                if sous not in vues:
                    a_visiter.append((sous, niveau + 1))
        time.sleep(DELAI_PAGE)
    return pdfs


# La date dans le NOM du fichier : « recueil-30-2026-001-special du 05 01 2026 ».
# `re.I` parce que la même préfecture écrit aussi « DU 03 03 2026 » — trois
# recueils du Gard restaient sans date pour une majuscule.
_DATE_NOM = re.compile(r"\bdu[ ._-](\d{2})[ ._-](\d{2})[ ._-](\d{4})", re.I)

# La date sur la COUVERTURE, quand le nom du fichier ne la porte pas. C'est le
# cas de départements entiers : la Drôme numérote ses recueils sans les dater
# (« RAA SPECIAL N°26-2026-016.pdf »), et les 79 recueils lus le 24/08/2026 sont
# entrés sans une seule date. Leur première page, elle, dit « PUBLIÉ LE 16
# JANVIER 2026 » — c'est la mention réglementaire de publication, et elle est
# donc au moins aussi sûre qu'un nom de fichier.
_PUBLIE_LE = re.compile(r"PUBLI[ÉE]E?\s+LE\s+([^\n]{6,40})", re.I)


def _date_from_name(name: str) -> str | None:
    m = _DATE_NOM.search(name or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def date_du_recueil(nom: str, pages: list[str] | None = None) -> str | None:
    """La date d'un recueil : son nom de fichier s'il la porte, sa couverture sinon.

    L'ordre n'est pas indifférent. Le nom de fichier est ce que la préfecture a
    saisi à la mise en ligne ; la couverture est ce que le recueil affirme de
    lui-même. Les deux se sont toujours accordés là où les deux existent, et le
    nom vient en premier parce qu'il ne coûte pas de lecture.
    """
    date = _date_from_name(nom)
    if date:
        return date
    m = _PUBLIE_LE.search((pages or [""])[0] or "")
    return date_fr(m.group(1)) if m else None


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
    date_doc = date_du_recueil(fname, pages)

    if mentions and not dry_run:
        archive_fetch(SOURCE, url, raw, doc_type="pdf", title=fname,
                      metadata={"mentions": len(mentions)})
        exists = conn.execute(
            "SELECT id FROM events WHERE source=? AND source_url=?",
            (SOURCE, url)
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
                " VALUES ('raa_prefecture', ?, ?, ?, ?, ?, ?)",
                (date_doc, f"RAA {DEPARTEMENT} {fname.removesuffix('.pdf')} — "
                           f"{len(mentions)} mention(s) : {', '.join(communes)}",
                 content, SOURCE, url,
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
        conn.close()
        raise SourceInterrompue(
            f"index des recueils {year} injoignable ({e}) — la préfecture limite "
            f"les rafales, réessayer plus tard") from e
    done = {r[0] for r in conn.execute("SELECT url FROM raa_scans")}
    todo = [u for u in pdfs if u not in done]
    print(f"[raa] {len(pdfs)} PDFs en ligne, {len(todo)} à scanner"
          + (f" (limit {limit})" if limit else ""))

    lot = todo[:limit] if limit else todo
    scanned = hits = absents = interrompus = 0
    for url in lot:
        fname = urllib.parse.unquote(url.rsplit("/", 1)[-1])
        try:
            n = scan_pdf(conn, url, dry_run=dry_run)
        except Exception as e:
            # Deux échecs qui n'ont rien à voir. Un 4xx dit que le recueil n'est
            # plus là : c'est une lacune, elle est connue, la collecte reste
            # complète. Une connexion coupée ne dit rien du tout — on ignore ce
            # qu'on n'a pas lu, et c'est cela qui rend le passage incomplet.
            if isinstance(e, urllib.error.HTTPError) and 400 <= e.code < 500:
                absents += 1
                print(f"  [raa] retiré du site ({e.code}) : {fname}")
            else:
                interrompus += 1
                print(f"  [raa] sans réponse : {fname} → {e}")
            continue
        scanned += 1
        if n:
            hits += 1
            print(f"  ✓ {fname} — {n} mention(s)")
        time.sleep(delay)  # la préfecture coupe les connexions après ~90 fetchs rapprochés

    print(f"[raa] {scanned} recueils lus sur {len(lot)}, {hits} avec mention"
          + (f", {absents} retiré(s) du site" if absents else "")
          + (f", {interrompus} sans réponse" if interrompus else ""))
    conn.close()

    if interrompus:
        # Ce qui a été lu est en base : l'exception ne défait rien, elle refuse
        # seulement d'appeler « ok » une collecte tronquée. La reprise est
        # incrémentale — `raa_scans` retient ce qui a été scanné.
        raise SourceInterrompue(
            f"{interrompus} recueil(s) sur {len(lot)} n'ont pas répondu — la "
            f"source a cessé de répondre en cours de collecte. {scanned} lus et "
            f"enregistrés ; relancer le step reprendra les autres, en espaçant "
            f"davantage (--delay).")


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
    ap = argparse.ArgumentParser(
        description="Recueils des actes administratifs de la préfecture — "
                    "mentions des communes du périmètre")
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
