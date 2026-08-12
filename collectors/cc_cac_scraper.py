"""
cc_cac_scraper.py — Collecteur CC Causses Aigoual Cévennes Terres Solidaires

Scrape caussesaigoualcevennes.fr pour :
  - Procès-verbaux des conseils communautaires (/pv/)
  - Liste des élus CC et délégués des communes membres (/organisation/)
  - Marchés publics AAPC (/marches-publics/) → délégué à marches_publics.py
  - Actualités et projets (/actualites/, /grands-projets/)

Données insérées :
  - entities (service) : CC CAC elle-même, communes membres
  - entities (person)  : élus délégués (si non existants)
  - relations          : élu_cc entre persons et CC CAC
  - events             : délibérations CC, type='délibération_cc'
  - events             : actualités CC, type='actualité_cc'

Source : caussesaigoualcevennes.fr (données publiques)
SIREN CC CAC : 200034601  (confirmé SIRENE API — valeur dans config.py EPCI_SIREN)

Usage :
  python3 -m collectors.cc_cac_scraper --dry-run
  python3 -m collectors.cc_cac_scraper
  python3 -m collectors.cc_cac_scraper --section pv        # PV uniquement
  python3 -m collectors.cc_cac_scraper --section elus      # élus uniquement
  python3 -m collectors.cc_cac_scraper --section actu      # actualités
"""

import argparse
import json
import re
import time
from html.parser import HTMLParser
import urllib.request
import urllib.error

from .config import EPCI_COMMUNES, EPCI_SIREN, HEADERS, REQUEST_DELAY
from .archive import archive_fetch
from .db import transaction, upsert_entity, upsert_relation

# ── Constantes ────────────────────────────────────────────────────────────────

CAC_SIREN    = EPCI_SIREN   # "243000809"
CAC_BASE     = "https://caussesaigoualcevennes.fr"
CAC_SECTIONS = {
    "pv":           CAC_BASE + "/pv/",
    "organisation": CAC_BASE + "/organisation/",
    "actualites":   CAC_BASE + "/actualites/",
    "grands-projets": CAC_BASE + "/grands-projets/",
    "communes":     CAC_BASE + "/les-communes/",
}

# Communes membres de l'EPCI — lues dans la config, jamais recopiées.
# La liste en dur qui vivait ici jusqu'au 12/08/2026 était FAUSSE : elle
# contenait Aulas, Ganges, Sumène, Montdardier, Roquedur, Saint-Bresson…, qui
# relèvent d'autres intercommunalités, et manquait Les Plantiers, Revens,
# Trèves, Soudorgues, Peyrolles. Un élu de Ganges cité dans un PV se serait vu
# attribuer une commune membre. `EPCI_COMMUNES` est la seule liste de
# référence, sourcée de geo.api.gouv.fr — cf. collectors/config.py.
COMMUNES_CAC = sorted(c["nom"] for c in EPCI_COMMUNES.values())


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def fetch(url: str, timeout: int = 15) -> str | None:
    req = urllib.request.Request(url, headers={
        **HEADERS,
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 Chrome/122.0 Safari/537.36"
        )
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            archive_fetch("cc-cac", url, raw, r.headers.get_content_type(), r.status)
            return raw.decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  [erreur] {url[:60]} → {e}")
        return None


# ── Parseurs HTML ─────────────────────────────────────────────────────────────

class LinkParser(HTMLParser):
    """Extrait tous les liens (<a href>) d'une page."""
    def __init__(self, base_url: str = ""):
        super().__init__()
        self.links: list[dict] = []
        self.base_url = base_url
        self._in_a = False
        self._buf  = []
        self._href = ""

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            d = dict(attrs)
            href = d.get("href", "")
            if href and not href.startswith(("#", "mailto:", "tel:", "javascript:")):
                if href.startswith("/"):
                    href = self.base_url + href
                self._href = href
                self._in_a = True
                self._buf  = []

    def handle_endtag(self, tag):
        if tag == "a" and self._in_a:
            text = " ".join(self._buf).strip()
            if text:
                self.links.append({"href": self._href, "text": text})
            self._in_a = False

    def handle_data(self, data):
        if self._in_a:
            s = data.strip()
            if s:
                self._buf.append(s)


class ArticleParser(HTMLParser):
    """Extrait titre, date et contenu d'un article WordPress."""
    def __init__(self):
        super().__init__()
        self.title       = ""
        self.date_iso    = ""
        self.paragraphs  : list[str] = []
        self._in_h1      = False
        self._in_p       = False
        self._in_article = False
        self._skip       = 0
        self._buf        = []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        cls = d.get("class", "")
        if tag in ("script", "style", "nav", "footer"):
            self._skip += 1
            return
        if tag == "article":
            self._in_article = True
        elif tag == "h1" and self._in_article:
            self._in_h1 = True
            self._buf   = []
        elif tag == "time":
            dt = d.get("datetime", "")
            if dt:
                self.date_iso = dt[:10]
        elif tag == "p" and self._in_article:
            self._in_p = True
            self._buf  = []

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer") and self._skip:
            self._skip -= 1
        if tag == "h1" and self._in_h1:
            self.title   = " ".join(self._buf).strip()
            self._in_h1  = False
        elif tag == "p" and self._in_p:
            text = " ".join(self._buf).strip()
            if text:
                self.paragraphs.append(text)
            self._in_p = False

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_h1 or self._in_p:
            s = data.strip()
            if s:
                self._buf.append(s)


# ── Normalisation ─────────────────────────────────────────────────────────────

_MOIS_FR = {
    "janvier": "01", "février": "02", "mars": "03", "avril": "04",
    "mai": "05", "juin": "06", "juillet": "07", "août": "08",
    "septembre": "09", "octobre": "10", "novembre": "11", "décembre": "12",
}

def normalize_date(raw: str) -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    # ISO direct
    m = re.match(r"(\d{4}-\d{2}-\d{2})", raw)
    if m:
        return m.group(1)
    # "12 novembre 2024"
    m = re.match(r"(\d{1,2})\s+(\w+)\s+(\d{4})", raw.lower())
    if m:
        num = _MOIS_FR.get(m.group(2))
        if num:
            return f"{m.group(3)}-{num}-{int(m.group(1)):02d}"
    # "2024"
    m = re.match(r"(\d{4})", raw)
    if m:
        return m.group(1) + "-01-01"
    return None


# ── Scraper PV / délibérations ────────────────────────────────────────────────

_DATE_DDMMYYYY = re.compile(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](20\d{2})")

def _parse_date_ddmmyyyy(text: str) -> str | None:
    """Convertit DD.MM.YYYY (ou variantes) en ISO YYYY-MM-DD."""
    m = _DATE_DDMMYYYY.search(text)
    if m:
        d, mo, y = m.group(1), m.group(2), m.group(3)
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    return None


def scrape_pv_list() -> list[dict]:
    """
    Récupère la liste des PV et délibérations du conseil communautaire CC CAC.
    Extrait les liens <a href="...pdf">TITRE</a> depuis la page /pv/.
    Format des titres : 'PV du 04.02.2026.pdf', 'Délibérations du 04.03.2026.pdf'
    """
    html = fetch(CAC_SECTIONS["pv"])
    if not html:
        return []

    # Extraire directement les couples (URL, texte du lien) avec PDFs wp-content
    # Le texte du lien contient le nom du fichier avec la date
    pattern = re.compile(
        r'href=["\']('
        + re.escape(CAC_BASE)
        + r'/wp-content/uploads/[^"\']+\.pdf)["\'][^>]*>'
        r'\s*([^<]{5,100})\s*<',
        re.I
    )
    seen_urls: set[str] = set()
    pvs: list[dict] = []

    for m in pattern.finditer(html):
        url  = m.group(1).strip()
        text = m.group(2).strip()

        if url in seen_urls:
            continue
        seen_urls.add(url)

        # Catégoriser : PV, délibérations, convocation
        fname = url.split("/")[-1].lower()
        if any(x in fname for x in ["convoc", "ordre-du-jour", "ordre_du_jour"]):
            continue  # ignorer les convocations

        is_deliber = any(x in fname for x in ["deliber", "delib"])
        doc_type   = "délibérations_cc" if is_deliber else "pv_cc"

        # Date depuis le texte du lien (le plus fiable : "PV du 04.02.2026.pdf")
        date_str = _parse_date_ddmmyyyy(text) or _parse_date_ddmmyyyy(fname)

        # Si toujours pas de date, extraire depuis l'URL (année/mois dans le chemin)
        if not date_str:
            path_m = re.search(r"/uploads/(\d{4})/(\d{2})/", url)
            if path_m:
                date_str = f"{path_m.group(1)}-{path_m.group(2)}-01"

        pvs.append({
            "url":   url,
            "title": text.replace(".pdf", "").replace("-", " ").strip(),
            "date":  date_str,
            "type":  doc_type,
        })

    print(f"  [PV] {len(pvs)} documents trouvés (PV + délibérations)")
    return pvs


def scrape_pv_content(pv: dict) -> dict:
    """Enrichit un PV avec son contenu (si page HTML, pas PDF)."""
    if pv["url"].lower().endswith(".pdf"):
        return pv  # PDF : pas de parsing ici

    html = fetch(pv["url"])
    if not html:
        return pv

    parser = ArticleParser()
    parser.feed(html)
    if parser.title:
        pv["title"] = parser.title
    if parser.date_iso:
        pv["date"] = parser.date_iso
    pv["content"] = " ".join(parser.paragraphs[:8])
    time.sleep(REQUEST_DELAY)
    return pv


# ── Scraper élus CC ───────────────────────────────────────────────────────────

_CIVILITY_RE = re.compile(
    r"\b(M\.?|Mme\.?|Monsieur|Madame)\s+([A-ZÀ-Ü][a-zà-ü]+(?:\s+[A-ZÀ-Ü][a-zà-ü]+){0,3})",
    re.UNICODE
)

# (inutilisé — conservé pour compatibilité)

def _clean_html_text(html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
    text = re.sub(r"<style[^>]*>.*?</style>",  "", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&[a-z#0-9]+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def scrape_elus_cc() -> list[dict]:
    """
    Récupère la liste des élus CC CAC depuis /fonctionnement/.
    Format de la page :
      "Vice-Président au X : NOM Prénom (Titre commune)"
      "Gilles BEAUMANOIR ... Président ..."
    """
    html = fetch(CAC_BASE + "/fonctionnement/")
    if not html:
        return []

    text = _clean_html_text(html)
    elus = []
    seen: set[str] = set()

    # ── Extraction ciblée sur le format réel de la page ──────────────────────
    # Format 1 : "FONCTION : NOM_MAJ Prénom (Titre commune)"
    # ex: "Vice-Président au Tourisme : VALGALIER Frédéric (Maire de Trèves)"
    # ex: "Vice-Président à la Culture : DE LATOUR Henri (Maire de Lasalle)"
    vp_re = re.compile(
        r"((?:\d+[eèéème]*\s+)?Vice-Pr[eé]sident[e]?\s+[^:]{2,50}?)\s*:\s*"
        r"((?:DE |DU |D')?[A-ZÀÂÉÈÊËÎÏÔÙÛÜ][A-ZÀÂÉÈÊËÎÏÔÙÛÜ\-]+\s+"
        r"[A-ZÀ-Ü][a-zà-ü]+(?:[- ][A-ZÀ-Ü][a-zà-ü]+)?)"
        r"(?:\s*\(([^)]{5,60})\))?",
        re.I | re.UNICODE
    )
    for m in vp_re.finditer(text):
        fonction_raw = m.group(1).strip()
        nom_raw      = m.group(2).strip()
        contexte     = m.group(3) or ""

        # Normaliser : "DE LATOUR Henri" → "Henri DE LATOUR"
        # Pattern : NOM_MAJ Prénom → Prénom NOM_MAJ
        nom_m = re.match(
            r"((?:DE |DU |D')?[A-ZÀÂÉÈÊËÎÏÔÙÛÜ][A-ZÀÂÉÈÊËÎÏÔÙÛÜ\-]+)\s+"
            r"([A-ZÀ-Ü][a-zà-ü]+(?:[- ][A-ZÀ-Ü][a-zà-ü]+)?)",
            nom_raw, re.UNICODE
        )
        if nom_m:
            nom_complet = f"{nom_m.group(2)} {nom_m.group(1)}"
        else:
            nom_complet = nom_raw

        if nom_complet in seen:
            continue
        seen.add(nom_complet)

        # Commune depuis le contexte "(Maire de Lasalle)" etc.
        # Normaliser pour la comparaison (apostrophes, tirets, casse)
        def _norm(s: str) -> str:
            return re.sub(r"['\u2019\-]", " ", s).lower().strip()

        contexte_norm = _norm(contexte)
        commune = ""
        for c in COMMUNES_CAC:
            if _norm(c) in contexte_norm:
                commune = c
                break
        if not commune:
            cm = re.search(r"(?:de\s+|d['\u2019]?\s*)([A-ZÀ-Ü][a-zà-ü\-\u2019']+(?:\s+[A-ZÀ-Ü][a-zà-ü]+)?)",
                           contexte, re.I)
            if cm:
                commune = cm.group(1)

        # Numéro VP depuis "1er Vice-Président au..."
        num_m = re.match(r"(\d+[eèéème]*)\s+Vice", fonction_raw, re.I)
        rang  = num_m.group(1) if num_m else ""
        domaine_m = re.search(r"Vice-Pr[eé]sident[e]?\s+(?:au?x?\s+|à\s+(?:la\s+)?|de\s+)?(.{4,35})",
                              fonction_raw, re.I)
        domaine = domaine_m.group(1).strip().rstrip(":").strip() if domaine_m else ""
        fonction = f"vice-président {rang} {domaine}".strip()

        elus.append({
            "nom":       nom_complet,
            "commune":   commune,
            "fonction":  fonction,
            "mandature": "2020-2026",
        })

    # Format 2 : Président — chercher "Prénom NOM ... élu ... Président"
    # Structure connue : "Gilles BEAUMANOIR ... il a été élu le 15 juillet Président"
    pres_re = re.compile(
        r"([A-ZÀ-Ü][a-zà-ü]{3,})\s+([A-ZÀÂÉÈÊËÎÏÔÙÛÜ]{4,})"
        r"[^.]{10,300}(?:a été élu|est élu|élu\b)[^.]{0,80}Pr[eé]sident",
        re.I | re.UNICODE
    )
    for m in pres_re.finditer(text):
        prenom, nom = m.group(1), m.group(2)
        if nom in {"VICE", "CAC", "CC", "COMMUNAUTE", "COMMUNES"}:
            continue
        nom_complet = f"{prenom} {nom}"
        if nom_complet in seen:
            continue
        seen.add(nom_complet)
        ctx = text[max(0, m.start()-50):m.end()+200]
        commune = ""
        for c in COMMUNES_CAC:
            if c.lower() in ctx.lower():
                commune = c
                break
        elus.append({
            "nom":       nom_complet,
            "commune":   commune,
            "fonction":  "président",
            "mandature": "2020-2026",
        })

    # Format 3 : membres bureau non maires (déjà capturés comme VP si applicable)
    # ex: "Dominique Roland conseillère municipale de Lasalle" (déjà VP Communication)
    # ex: "Patrick Bénéfice 1er adjoint de Lasalle" (déjà VP Actions Sociales)
    # → pas besoin de les extraire à nouveau ; skipped pour éviter les doublons

    print(f"  [élus CC] {len(elus)} élus extraits")
    return elus


# ── Scraper actualités ────────────────────────────────────────────────────────

def scrape_actualites(limit: int = 20) -> list[dict]:
    """Récupère les dernières actualités de la CC CAC."""
    html = fetch(CAC_SECTIONS["actualites"])
    if not html:
        return []

    parser = LinkParser(CAC_BASE)
    parser.feed(html)

    actu_links = [
        l for l in parser.links
        if CAC_BASE in l["href"]
        and "/wp-content/" not in l["href"]
        and len(l["text"]) > 15
        and l["href"] != CAC_SECTIONS["actualites"]
    ][:limit]

    actus = []
    for link in actu_links:
        date_m = re.search(r"(\d{4}/\d{2}/\d{2})", link["href"])
        date_str = date_m.group(1).replace("/", "-") if date_m else None
        actus.append({
            "url":     link["href"],
            "title":   link["text"],
            "date":    date_str,
            "type":    "actualité_cc",
            "content": "",
        })

    print(f"  [actus] {len(actus)} articles trouvés")
    return actus


# ── Insertion DB ──────────────────────────────────────────────────────────────

def _get_cac_entity_id(conn) -> int:
    row = conn.execute(
        "SELECT id FROM entities WHERE name LIKE '%Causses Aigoual%' OR name LIKE '%CC CAC%' LIMIT 1"
    ).fetchone()
    if row:
        return row["id"]
    eid = upsert_entity(
        conn, type="service",
        name="CC Causses Aigoual Cévennes Terres Solidaires",
        short_name="CC CAC",
        confidence="verified"
    )
    conn.execute(
        "INSERT OR IGNORE INTO businesses (entity_id, siren) VALUES (?,?)",
        (eid, CAC_SIREN)
    )
    return eid


def insert_pv(conn, pv: dict, cac_eid: int) -> bool:
    title = pv.get("title", "").strip()
    url   = pv.get("url", "")
    if not title:
        return False

    existing = conn.execute(
        "SELECT id FROM events WHERE type=? AND (source_url=? OR title=?) LIMIT 1",
        (pv["type"], url, title)
    ).fetchone()
    if existing:
        return False

    ev_id = conn.execute(
        "INSERT INTO events (type, date, title, source, source_url, metadata)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            pv["type"],
            pv.get("date"),
            title,
            "caussesaigoualcevennes.fr",
            url,
            json.dumps({"content": pv.get("content", "")[:500]}, ensure_ascii=False)
        )
    ).lastrowid

    conn.execute(
        "INSERT OR IGNORE INTO event_entities (event_id, entity_id, role)"
        " VALUES (?, ?, 'sujet')",
        (ev_id, cac_eid)
    )
    return True


def insert_elu_cc(conn, elu: dict, cac_eid: int) -> bool:
    nom = elu["nom"].strip()
    if not nom:
        return False

    # Créer ou retrouver la personne
    # Note : upsert_entity peut retourner un lastrowid incorrect si l'entité
    # existe déjà (lastrowid est le dernier INSERT réussi, pas l'entity existante).
    # On vérifie donc l'ID réel après upsert.
    upsert_entity(conn, type="person", name=nom, confidence="verified")
    row = conn.execute(
        "SELECT id FROM entities WHERE type='person' AND name=?", (nom,)
    ).fetchone()
    if not row:
        return False
    pers_eid = row["id"]

    # Relation élu_cc avec CC CAC
    upsert_relation(
        conn,
        from_id=pers_eid,
        to_id=cac_eid,
        rel_type="élu_cc",
        source="cc_cac_site",
        confidence="verified",
        metadata=json.dumps({
            "fonction": elu.get("fonction", "délégué"),
            "commune":  elu.get("commune", ""),
        }, ensure_ascii=False)
    )

    # Si commune connue, chercher si l'élu est aussi dans la DB Lasalle
    commune = elu.get("commune", "")
    if commune.lower() == "lasalle":
        # Vérifier si cette personne est déjà dans la DB comme élu_cm
        row = conn.execute(
            "SELECT r.id FROM relations r "
            "JOIN entities e ON e.id=r.from_id "
            "WHERE e.name=? AND r.relation_type='élu_cm' LIMIT 1",
            (nom,)
        ).fetchone()
        if row:
            # Ajouter annotation dans les notes
            conn.execute(
                "INSERT OR IGNORE INTO entity_notes (entity_id, note, source, confidence)"
                " VALUES (?, ?, 'cc_cac_site', 'verified')",
                (pers_eid,
                 f"Délégué CC CAC (fonction: {elu.get('fonction','')}) — double mandat CM+CC")
            )
    return True


def insert_actu(conn, actu: dict, cac_eid: int) -> bool:
    title = actu.get("title", "").strip()
    url   = actu.get("url", "")
    if not title:
        return False

    existing = conn.execute(
        "SELECT id FROM events WHERE type='actualité_cc' AND source_url=? LIMIT 1",
        (url,)
    ).fetchone()
    if existing:
        return False

    ev_id = conn.execute(
        "INSERT INTO events (type, date, title, source, source_url)"
        " VALUES ('actualité_cc', ?, ?, 'caussesaigoualcevennes.fr', ?)",
        (actu.get("date"), title, url)
    ).lastrowid
    conn.execute(
        "INSERT OR IGNORE INTO event_entities (event_id, entity_id, role)"
        " VALUES (?, ?, 'sujet')",
        (ev_id, cac_eid)
    )
    return True


# ── Main ──────────────────────────────────────────────────────────────────────

def main(
    dry_run: bool = False,
    section: str = "all",
) -> None:
    print(f"\n[cc_cac_scraper] dry_run={dry_run} section={section}")
    print(f"  Source : {CAC_BASE}")
    print(f"  SIREN  : {CAC_SIREN}")

    pvs: list[dict]    = []
    elus: list[dict]   = []
    actus: list[dict]  = []

    if section in ("all", "pv"):
        pvs = scrape_pv_list()
        # Enrichir les pages HTML (pas les PDFs)
        for i, pv in enumerate(pvs):
            if not pv["url"].lower().endswith(".pdf"):
                pvs[i] = scrape_pv_content(pv)
                time.sleep(REQUEST_DELAY)

    if section in ("all", "elus"):
        elus = scrape_elus_cc()

    if section in ("all", "actu"):
        actus = scrape_actualites()

    total = len(pvs) + len(elus) + len(actus)
    print(f"\n  Total : {len(pvs)} PV, {len(elus)} élus, {len(actus)} actus")

    if dry_run:
        print("\n--- PV ---")
        for pv in pvs[:5]:
            print(f"  {pv.get('date','?')} | {pv['title'][:60]}")
        print("\n--- Élus ---")
        for elu in elus[:10]:
            print(f"  {elu['nom']} [{elu['commune']}] — {elu['fonction']}")
        print("\n--- Actus ---")
        for a in actus[:5]:
            print(f"  {a.get('date','?')} | {a['title'][:60]}")
        return

    inserted_pv = inserted_elus = inserted_actu = 0
    with transaction() as conn:
        cac_eid = _get_cac_entity_id(conn)

        for pv in pvs:
            if insert_pv(conn, pv, cac_eid):
                inserted_pv += 1

        for elu in elus:
            if insert_elu_cc(conn, elu, cac_eid):
                inserted_elus += 1

        for actu in actus:
            if insert_actu(conn, actu, cac_eid):
                inserted_actu += 1

    print(f"\n[cc_cac_scraper] Inséré : {inserted_pv} PV, "
          f"{inserted_elus} élus CC, {inserted_actu} actus")
    if inserted_elus > 0:
        print("  → Vérifier les élus Lasalle avec double mandat CM+CC dans entity_notes")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collecteur CC Causses Aigoual Cévennes Terres Solidaires")
    parser.add_argument("--dry-run",  action="store_true")
    parser.add_argument("--section",  default="all",
                        choices=["all", "pv", "elus", "actu"])
    args = parser.parse_args()
    main(dry_run=args.dry_run, section=args.section)
