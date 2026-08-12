"""
cm_ocr.py — Collecteur CR du Conseil Municipal diffusés en PDF SCANNÉ (image).

Certains comptes-rendus de lasalle.fr ne sont ni du HTML (→ cm_events / cm_parser)
ni un PDF avec couche texte (→ cm_wayback) : ce sont des PDF *scannés*. Ce collecteur
les traite de bout en bout :

  1. résout l'entrée en (PDF, url de CR, date) — page CR, url PDF, fichier local, ou --discover ;
  2. télécharge le PDF (cache data/cm_records_pdf/) ;
  3. OCR *conditionnel* : seulement si le PDF n'a pas de couche texte exploitable
     (ocrmypdf -l fra, cache .ocr.pdf) — un PDF déjà textuel est parsé tel quel ;
  4. extrait le texte (pdfplumber) et découpe en délibérations
     (marqueurs « N° DEL AAMM_XX », repli sur le splitter de cm_parser) ;
  5. upsert idempotent d'un event type='deliberation' par délib + un event
     ombrelle type='conseil_municipal' (titre + lien PDF).

Périmètre : on publie les TITRES des délibérations (la page publique n'affiche pas
le corps OCR). Les montants OCR — peu fiables — sont conservés en métadonnée
`montants_ocr` (flag `ocr:true`) pour validation atelier ; AUCUN financial_flow
n'est créé automatiquement (règle : ne jamais publier du non vérifié).

Prérequis système : ocrmypdf + tesseract + langue française. La langue FR doit être
installée dans le tessdata SYSTÈME (qui contient les configs hocr/txt), pas dans un
TESSDATA_PREFIX isolé. Vérifier : `tesseract --list-langs` doit lister `fra`.

Usage :
  python3 -m collectors.cm_ocr --url https://www.lasalle.fr/CR/cm-du-30-juin-2026-deliberations
  python3 -m collectors.cm_ocr --pdf-url https://.../CM.pdf --date 2026-06-30
  python3 -m collectors.cm_ocr --file data/cm_records_pdf/CM.pdf --date 2026-06-30 --commit
  python3 -m collectors.cm_ocr --discover                 # liste les CR PDF non parsés
  python3 -m collectors.cm_ocr --discover --commit --limit 3
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import pdfplumber

from .config import HEADERS
from .db import transaction, get_conn
from .cm_parser import (
    categorize, extract_vote, extract_amounts, extract_names,
    split_into_deliberations, _parse_french_date, _date_from_filename,
)

ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = ROOT / "data" / "cm_records_pdf"
LISTING_URL = "https://www.lasalle.fr/compte-rendus-des-conseils"

# En-dessous de ce nombre de caractères extraits, on considère le PDF « scanné » → OCR.
MIN_TEXT_CHARS = 400
# Découpe : « N° DEL 2606_02 », « DEL 2606_02 », etc. → capture l'identifiant AAMM_XX.
# Le séparateur est ce que l'OCR a bien voulu lire du trait d'union bas : le CM
# du 30/06/2026 sort « 2606.08 » et « 2606 _18 », et ces deux délibérations
# passaient au travers du découpage (l'ancien motif n'admettait qu'UN caractère
# de séparation). On tolère donc jusqu'à trois caractères parmi espace . _ -.
DEL_RE = re.compile(r"N[°ºo]?\s*DEL\s*(\d{4})[\s._-]{0,3}(\d{2})", re.I)
_HEADER = re.compile(
    r"DELIBERATION|REGISTRE|REPUBLIQUE|DEPARTEMENT|CONSEIL\s+MUNICIPAL|"
    r"^GARD$|EXTRAIT|SEANCE|SÉANCE|PRESIDENCE|CONVOCATION", re.I)
_TITLE_FIXES = [(r"Î\s*ERE|ÎERE|1ERE", "1ÈRE"), (r"\bSEIL\b", "CONSEIL"),
                (r"—\s*—", "—"), (r"\s{2,}", " ")]


# ── HTTP ──────────────────────────────────────────────────────────────────────

def _http(url: str, timeout: int = 60) -> bytes:
    return urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=timeout).read()


def _fetch_text(url: str) -> str:
    return _http(url).decode("utf-8", "replace")


def _pdf_link_from_cr(cr_url: str) -> str | None:
    """Extrait le lien .pdf d'une page CR lasalle.fr."""
    html = _fetch_text(cr_url)
    m = re.search(r'href="([^"]+\.pdf[^"]*)"', html, re.I)
    if not m:
        return None
    return urllib.parse.urljoin(cr_url, m.group(1))


# ── Téléchargement + OCR ───────────────────────────────────────────────────────

def _safe_name(url_or_path: str, date: str | None) -> str:
    base = Path(urllib.parse.urlparse(url_or_path).path).stem or "CM"
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)[:60]
    return f"{date + '_' if date else ''}{base}.pdf"


def download_pdf(pdf_url: str, date: str | None) -> Path:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    dest = PDF_DIR / _safe_name(pdf_url, date)
    if not dest.exists() or dest.stat().st_size == 0:
        dest.write_bytes(_http(pdf_url))
    return dest


def _extract_text(pdf: Path) -> str:
    with pdfplumber.open(pdf) as f:
        return "\n".join(p.extract_text() or "" for p in f.pages)


def _check_ocr_tooling(lang: str) -> None:
    if not shutil.which("ocrmypdf"):
        sys.exit("ocrmypdf introuvable — `brew install ocrmypdf` (installe aussi tesseract).")
    langs = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True).stdout
    if lang not in langs:
        sys.exit(f"Langue tesseract '{lang}' absente. Copier {lang}.traineddata dans le tessdata "
                 f"SYSTÈME (cf. `tesseract --list-langs`). Ex :\n"
                 f"  curl -sSL -o /tmp/{lang}.traineddata "
                 f"https://github.com/tesseract-ocr/tessdata_fast/raw/main/{lang}.traineddata\n"
                 f"  cp /tmp/{lang}.traineddata \"$(brew --prefix tesseract)/share/tessdata/\"")


def ensure_text(pdf: Path, lang: str = "fra") -> str:
    """Retourne le texte du PDF ; lance l'OCR si le PDF est scanné (peu/pas de texte)."""
    txt = _extract_text(pdf)
    if len(txt.strip()) >= MIN_TEXT_CHARS:
        return txt  # déjà textuel
    ocr_pdf = pdf.with_suffix(".ocr.pdf")
    if not ocr_pdf.exists():
        _check_ocr_tooling(lang)
        print(f"  OCR ({lang}) → {ocr_pdf.name} …")
        subprocess.run(
            ["ocrmypdf", "-l", lang, "--force-ocr", "--output-type", "pdf",
             "--optimize", "0", "--jobs", "4", str(pdf), str(ocr_pdf)],
            check=True, capture_output=True,
        )
    return _extract_text(ocr_pdf)


# ── Parsing des délibérations ──────────────────────────────────────────────────

def _clean_title(body: str) -> str:
    for line in body.splitlines():
        s = line.strip(" .:-—")
        if len(s) < 12:
            continue
        letters = s.replace(" ", "")
        if letters and sum(c.isupper() for c in letters) >= 0.7 * len(letters) \
           and re.search(r"[A-ZÉÈÀÂÊÎÔÛ]{5}", s) and not _HEADER.search(s):
            for pat, rep in _TITLE_FIXES:
                s = re.sub(pat, rep, s)
            return s.strip()
    return "(titre non reconnu)"


def _prefix_from_date(date: str | None) -> str | None:
    """« 2026-06-30 » → « 2606 » (préfixe AAMM des n° DEL de ce CM)."""
    m = re.match(r"\d{2}(\d{2})-(\d{2})-\d{2}", date or "")
    return (m.group(1) + m.group(2)) if m else None


def parse_deliberations(txt: str, expected_prefix: str | None = None) -> list[dict]:
    """Découpe par marqueurs « N° DEL AAMM_XX » ; repli sur cm_parser si absent.

    On ne garde que les délibérations DE CE CM : les n° DEL d'autres séances
    *cités* dans le corps sont ignorés en filtrant sur le préfixe AAMM courant
    (celui de la date, ou à défaut le préfixe majoritaire des marqueurs).
    """
    from collections import Counter
    marks = list(DEL_RE.finditer(txt))
    delibs: list[dict] = []
    if len(marks) >= 2:
        counts = Counter(m.group(1) for m in marks)
        target = expected_prefix if expected_prefix in counts else counts.most_common(1)[0][0]
        kept = [m for m in marks if m.group(1) == target]
        seen = set()
        for j, m in enumerate(kept):
            del_id = f"{m.group(1)}_{m.group(2)}"
            if del_id in seen:
                continue
            seen.add(del_id)
            end = kept[j + 1].start() if j + 1 < len(kept) else len(txt)
            body = txt[m.end(): end]
            title = _clean_title(body)
            delibs.append(_make_delib(f"DEL {del_id} — {title}", body, del_id))
    else:
        # Repli : splitter générique de cm_parser (sections en MAJUSCULES).
        for d in split_into_deliberations([l for l in txt.splitlines() if l.strip()]):
            body = "\n".join(d.get("paragraphes", []))
            delibs.append(_make_delib(d["titre"], body, None))
    return delibs


def _make_delib(titre: str, body: str, del_id: str | None) -> dict:
    cat, tags = categorize(titre)
    return {
        "titre": titre[:255],
        "texte": re.sub(r"\n{2,}", "\n", body).strip()[:6000],
        "categorie": cat, "tags": tags,
        "vote": extract_vote(body),
        "montants_ocr": [m["value"] for m in extract_amounts(body)][:8],
        "personnes_citees": list(dict.fromkeys(extract_names(body)))[:15],
        "del_id": del_id,
    }


def _derive_date(txt: str, url: str | None) -> str | None:
    return (_date_from_filename(url or "")
            or _parse_french_date(txt[:1500])
            or _parse_french_date(txt))


# ── Intégration DB ─────────────────────────────────────────────────────────────

def _upsert_delib(conn, date: str, cr_url: str, pdf_url: str, d: dict) -> str:
    import json
    meta = {
        "categorie": d["categorie"], "tags": d["tags"], "vote": d["vote"],
        "montants_ocr": d["montants_ocr"], "personnes_citees": d["personnes_citees"],
        "ocr": True, "del_id": d["del_id"], "pdf_url": pdf_url,
        "note": "Texte OCR (PDF scanné) — montants à valider avant publication de flux.",
    }
    c = conn.cursor()
    # Idempotence par n° de délibération, pas par titre : les titres sont
    # retouchés après coup (normalize_titres_ocr.py les passe en casse de
    # phrase, et met les fragments en quarantaine `fragment_ocr`). Rechercher
    # le titre brut ne retrouvait donc plus rien, et une seconde passe du
    # collecteur réinsérait tout le CM en double. Le n°, lui, ne bouge pas.
    # La recherche ignore le type : une délib mise en quarantaine doit être
    # mise à jour là où elle est, pas ressuscitée en double.
    row = None
    if d["del_id"]:
        row = c.execute(
            "SELECT id FROM events WHERE date=? AND source='lasalle.fr'"
            " AND json_extract(metadata,'$.del_id')=?",
            (date, d["del_id"])).fetchone()
    if row is None:
        row = c.execute("SELECT id FROM events WHERE date=? AND title=? AND type='deliberation'",
                        (date, d["titre"])).fetchone()
    if row:
        # `COALESCE(?, source_url)` : un retraitement local (--file, sans URL
        # publique) ne doit pas effacer l'URL officielle déjà enregistrée.
        c.execute("UPDATE events SET content=?, metadata=?, source='lasalle.fr', "
                  "source_url=COALESCE(?, source_url) WHERE id=?",
                  (d["texte"], json.dumps(meta, ensure_ascii=False), cr_url, row[0]))
        return "maj"
    c.execute("INSERT INTO events (type,date,title,content,source,source_url,metadata) "
              "VALUES ('deliberation',?,?,?,'lasalle.fr',?,?)",
              (date, d["titre"], d["texte"], cr_url, json.dumps(meta, ensure_ascii=False)))
    return "new"


def _upsert_umbrella(conn, date: str, cr_url: str, pdf_url: str, delibs: list[dict]) -> str:
    import json
    c = conn.cursor()
    if c.execute("SELECT id FROM events WHERE date=? AND type='conseil_municipal'", (date,)).fetchone():
        return "skip"
    content = f"Conseil municipal du {date} — {len(delibs)} délibérations (source lasalle.fr) :\n" + \
              "\n".join(f"- {d['titre']}" for d in delibs)
    meta = json.dumps({"pdf_url": pdf_url, "page_url": cr_url, "ocr": True}, ensure_ascii=False)
    c.execute("INSERT INTO events (type,date,title,content,source,source_url,metadata) "
              "VALUES ('conseil_municipal',?,?,?,'lasalle.fr',?,?)",
              (date, f"CM du {date}", content, cr_url, meta))
    return "new"


def _upsert_pv(conn, date: str, cr_url: str, pdf_url: str, txt: str) -> str:
    """Procès-verbal verbatim : un seul event conseil_municipal, texte intégral
    recherchable (FTS), SANS découpage en délibérations (structure non adaptée).

    Enrichit un event conseil_municipal *mince* déjà présent (stub d'un collecteur
    antérieur) en lui ajoutant le verbatim + le lien PDF, sans écraser son résumé.
    """
    import json
    body = txt.strip()[:60000]
    meta = json.dumps({"pdf_url": pdf_url, "page_url": cr_url, "ocr": True,
                       "note": "Procès-verbal verbatim — texte intégral, non découpé en délibérations."},
                      ensure_ascii=False)
    c = conn.cursor()
    row = c.execute(
        "SELECT id, content, metadata FROM events WHERE date=? AND type='conseil_municipal'", (date,)
    ).fetchone()
    if row:
        existing = (row["content"] or "").strip()
        already_rich = len(existing) >= 1500 or (row["metadata"] and "pdf_url" in row["metadata"])
        if already_rich:
            return "skip"
        merged = (existing + "\n\n— — —\n\n" if existing else "") + body
        c.execute("UPDATE events SET content=?, metadata=?, source_url=? WHERE id=?",
                  (merged[:60000], meta, cr_url, row["id"]))
        return "enrich"
    c.execute("INSERT INTO events (type,date,title,content,source,source_url,metadata) "
              "VALUES ('conseil_municipal',?,?,?,'lasalle.fr',?,?)",
              (date, f"PV du CM du {date}", body, cr_url, meta))
    return "new"


def _own_del_count(txt: str, prefix: str | None) -> int:
    """Nombre de n° DEL appartenant au CM courant (préfixe AAMM)."""
    from collections import Counter
    counts = Counter(m.group(1) for m in DEL_RE.finditer(txt))
    if not counts:
        return 0
    if prefix and prefix in counts:
        return counts[prefix]
    return 0  # aucun DEL du mois courant → ce n'est pas une liasse d'extraits


# ── Orchestration d'un CR ──────────────────────────────────────────────────────

def process_cr(*, cr_url: str | None, pdf_url: str | None, file: str | None,
               date: str | None, lang: str, umbrella: bool, commit: bool) -> dict:
    if file:
        pdf = Path(file).resolve()
        if not pdf.exists():
            sys.exit(f"Fichier introuvable : {file}")
        # PAS de `pdf.as_uri()` en repli : un `file:///Users/...` finissait en
        # `source_url` des délibérations, c'est-à-dire un lien mort côté public
        # et une fuite de l'arborescence personnelle. Le cas s'était déjà produit
        # (cf. scripts/fix_file_urls.py) et retraiter un PDF en cache avec
        # `--file` réécrasait la réparation. Sans URL publique, on n'en écrit pas.
        if not pdf_url:
            print("  ⚠ --file sans --pdf-url : aucune URL publique ne sera "
                  "enregistrée (préciser --url ou --pdf-url pour la source en ligne).")
    else:
        if cr_url and not pdf_url:
            pdf_url = _pdf_link_from_cr(cr_url)
            if not pdf_url:
                sys.exit(f"Aucun lien PDF trouvé sur {cr_url}")
        if not pdf_url:
            sys.exit("Fournir --url, --pdf-url ou --file.")
        print(f"  PDF : {pdf_url}")
        pdf = download_pdf(pdf_url, date)

    txt = ensure_text(pdf, lang)
    date = date or _derive_date(txt, cr_url or pdf_url)
    if not date:
        sys.exit("Date du CM introuvable — préciser --date AAAA-MM-JJ.")
    cr_url = cr_url or pdf_url
    prefix = _prefix_from_date(date)

    # Auto-détection : liasse d'extraits (≥2 n° DEL du mois courant) vs PV verbatim.
    is_pv = _own_del_count(txt, prefix) < 2
    if is_pv:
        print(f"  CM {date} : procès-verbal verbatim (pas de liasse d'extraits DEL) "
              f"→ 1 event conseil_municipal, texte intégral, pas de découpage.")
        if not commit:
            return {"date": date, "mode": "pv", "committed": False}
        with transaction() as conn:
            st = _upsert_pv(conn, date, cr_url, pdf_url, txt)
        print(f"  ✓ PV {st} (event conseil_municipal).")
        return {"date": date, "mode": "pv", "pv": st, "committed": True}

    delibs = parse_deliberations(txt, prefix)
    print(f"  CM {date} : {len(delibs)} délibérations")
    for d in delibs:
        v = "unanimité" if (d["vote"] or {}).get("unanimite") else \
            (f"{d['vote']['pour']} pour" if d["vote"] and d["vote"].get("pour") else "—")
        print(f"    [{d['categorie']:20}] {d['titre'][:64]}  · vote={v}")

    if not commit:
        return {"date": date, "mode": "delibs", "delibs": len(delibs), "committed": False}

    n_new = n_maj = 0
    with transaction() as conn:
        for d in delibs:
            st = _upsert_delib(conn, date, cr_url, pdf_url, d)
            n_new += st == "new"; n_maj += st == "maj"
        umb = _upsert_umbrella(conn, date, cr_url, pdf_url, delibs) if umbrella else "off"
    print(f"  ✓ {n_new} créées, {n_maj} MAJ, ombrelle={umb}")
    return {"date": date, "mode": "delibs", "delibs": len(delibs),
            "new": n_new, "maj": n_maj, "committed": True}


# ── Découverte des CR non encore parsés ────────────────────────────────────────

def discover(limit: int = 0) -> list[dict]:
    """Liste les CR de la page listing dont aucune délibération n'est en base."""
    html = _fetch_text(LISTING_URL)
    crs = sorted(set(re.findall(r'href="(/CR/[^"]+)"', html, re.I)))
    conn = get_conn(read_only=True)
    out = []
    for path in crs:
        url = urllib.parse.urljoin(LISTING_URL, path)
        date = _date_from_filename(path)
        if not date:
            continue
        # Déjà ingéré si des délibérations OU un PV/CM existent pour cette date.
        n = conn.execute(
            "SELECT COUNT(*) FROM events WHERE date=? AND type IN ('deliberation','conseil_municipal')",
            (date,),
        ).fetchone()[0]
        if n == 0:
            out.append({"cr_url": url, "date": date})
        if limit and len(out) >= limit:
            break
    conn.close()
    return out


# Découverte par balayage de slugs — les vieux CR sont délistés de la page listing
# mais restent en ligne à leur URL. Remplace cm_wayback (archive.org peu fiable).
_MOIS_SLUG = ["janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet",
              "aout", "septembre", "octobre", "novembre", "decembre"]


def discover_by_slug(year_from: int, year_to: int, skip_existing: bool = True) -> list[dict]:
    """Teste /CR/conseil-municipal-du-{jour}-{mois}-{année} sur toute la plage.
    Retourne les CR trouvés (HTTP 200), non encore en base si skip_existing."""
    conn = get_conn(read_only=True)

    def in_db(date):
        return conn.execute(
            "SELECT COUNT(*) FROM events WHERE date=? AND type IN ('deliberation','conseil_municipal')",
            (date,),
        ).fetchone()[0] > 0

    # Plusieurs motifs de slug observés sur lasalle.fr selon les époques.
    templates = [
        "conseil-municipal-du-{d}-{mo}-{y}",
        "cm-du-{d}-{mo}-{y}",
        "cm-{d}-{mo}-{y}",
        "compte-rendu-conseil-municipal-du-{d}-{mo}-{y}",
        "compte-rendu-du-conseil-municipal-du-{d}-{mo}-{y}",
        "compte-rendu-du-conseil-du-{d}-{mo}-{y}",
        "conseil-municipal-{d}-{mo}-{y}",
        "pv-du-conseil-municipal-du-{d}-{mo}-{y}",
        "conseil-municpal-du-{d}-{mo}-{y}",  # coquille présente dans certains slugs réels
    ]

    def hit(url):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=6).status == 200
        except Exception:
            return False

    out = []
    for year in range(year_from, year_to + 1):
        for mi, mo in enumerate(_MOIS_SLUG, 1):
            for day in range(1, 32):
                date = f"{year}-{mi:02d}-{day:02d}"
                if skip_existing and in_db(date):
                    continue
                for tmpl in templates:
                    url = "https://www.lasalle.fr/CR/" + tmpl.format(d=day, mo=mo, y=year)
                    if hit(url):
                        out.append({"cr_url": url, "date": date})
                        print(f"  ✓ {date}  {url}")
                        break  # un motif suffit
    conn.close()
    return out


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Collecteur CR CM en PDF scanné (OCR).")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--url", help="Page CR lasalle.fr (le PDF est détecté)")
    src.add_argument("--pdf-url", help="URL directe du PDF")
    src.add_argument("--file", help="Chemin d'un PDF local")
    src.add_argument("--discover", action="store_true",
                     help="Repère les CR non encore parsés (via la page listing)")
    src.add_argument("--scan-years", metavar="FROM-TO",
                     help="Balaye les slugs /CR/ sur une plage d'années (ex. 2013-2020) "
                          "pour retrouver les CR délistés — remplace archive.org")
    ap.add_argument("--date", help="Date du CM AAAA-MM-JJ (sinon auto)")
    ap.add_argument("--lang", default="fra", help="Langue OCR tesseract (défaut fra)")
    ap.add_argument("--no-umbrella", action="store_true", help="Ne pas créer l'event CM ombrelle")
    ap.add_argument("--limit", type=int, default=0, help="Max de CR en mode --discover")
    ap.add_argument("--commit", action="store_true", help="Écrit en base (sinon dry-run)")
    args = ap.parse_args()

    if args.scan_years:
        y1, y2 = (int(x) for x in args.scan_years.split("-"))
        print(f"[cm_ocr] balayage des slugs CR {y1}-{y2} …")
        cands = discover_by_slug(y1, y2)
        print(f"\n{len(cands)} CR délistés trouvés (non en base) :")
        for c in cands:
            print(f"\n→ {c['cr_url']}")
            process_cr(cr_url=c["cr_url"], pdf_url=None, file=None, date=c["date"],
                       lang=args.lang, umbrella=not args.no_umbrella, commit=args.commit)
        if not args.commit:
            print("\n(dry-run — ajouter --commit pour écrire)")
        return

    if args.discover:
        cands = discover(limit=args.limit)
        print(f"[cm_ocr] {len(cands)} CR sans délibération en base :")
        for c in cands:
            print(f"  {c['date']}  {c['cr_url']}")
        for c in cands:
            print(f"\n→ {c['cr_url']}")
            process_cr(cr_url=c["cr_url"], pdf_url=None, file=None, date=c["date"],
                       lang=args.lang, umbrella=not args.no_umbrella, commit=args.commit)
        if not args.commit:
            print("\n(dry-run — ajouter --commit pour écrire)")
        return

    process_cr(cr_url=args.url, pdf_url=args.pdf_url, file=args.file, date=args.date,
               lang=args.lang, umbrella=not args.no_umbrella, commit=args.commit)
    if not args.commit:
        print("(dry-run — ajouter --commit pour écrire)")


if __name__ == "__main__":
    main()
