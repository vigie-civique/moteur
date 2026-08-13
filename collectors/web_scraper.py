"""
web_scraper.py — Scraper générique des sites web des entités locales

Scrape ~100 sites d'associations, entreprises et lieux locaux pour :
- Confirmer/enrichir les données DB (adresse, téléphone, email, description)
- Détecter de nouvelles entités ou relations
- Alimenter la table `events` pour les annonces sur les sites

Usage :
  python3 -m collectors.web_scraper --dry-run
  python3 -m collectors.web_scraper
  python3 -m collectors.web_scraper --limit 20
  python3 -m collectors.web_scraper --type association
  python3 -m collectors.web_scraper --entity-id 123  # une seule entité
"""

import argparse
import json
import re
import sqlite3
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser

from .config import COMMUNE_NAME, COMMUNE_URL, DEPARTEMENT, HEADERS, REQUEST_DELAY, ROOT
from .db import transaction, get_conn
from .archive import archive_fetch

SITES_CONFIG = ROOT / "config" / "sites_locaux.json"  # legacy — remplacé par entity_websites

# ── Helpers HTTP ──────────────────────────────────────────────────────────────

# Bilan réseau du run. L'avalage site par site est voulu (un site associatif
# mort ne doit pas arrêter les 100 autres), mais un échec TOTAL est une panne
# réseau, pas un « rien de nouveau » — même leçon que bodacc (10/08/2026).
_reseau = {"ok": 0, "err": 0, "derniere_erreur": ""}


def fetch(url: str, timeout: int = 15) -> str | None:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            encoding = r.headers.get_content_charset("utf-8")
            from urllib.parse import urlparse
            archive_fetch(f"web:{urlparse(url).netloc}", url, raw,
                          r.headers.get_content_type(), r.status)
            _reseau["ok"] += 1
            return raw.decode(encoding, errors="replace")
    except Exception as e:
        print(f"  [erreur] {url} → {e}")
        _reseau["err"] += 1
        _reseau["derniere_erreur"] = f"{url} → {e}"
        return None


# ── Parseur de page générique ─────────────────────────────────────────────────

# Patterns d'extraction d'informations de contact
_RE_TEL   = re.compile(r"\b0[1-9](?:[\s.\-]?\d{2}){4}\b")
_RE_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b", re.IGNORECASE)
_RE_SIREN = re.compile(r"\bSIREN\s*:?\s*(\d{9})\b", re.IGNORECASE)
_RE_SIRET = re.compile(r"\bSIRET\s*:?\s*(\d{14})\b", re.IGNORECASE)

# Mots-clés indiquant un conflit d'intérêt potentiel
_CONFLICT_KEYWORDS = [
    "mairie", "commune", "conseil municipal", "subvention", "marché public",
    "élu", "adjoint", "maire", "délibération", "budget communal",
]


class PageInfoParser(HTMLParser):
    """
    Extrait les informations utiles d'une page web :
    - Titre et meta description
    - Texte visible (paragraphes, listes)
    - Liens sortants
    """
    def __init__(self):
        super().__init__()
        self.title = ""
        self.meta_desc = ""
        self.text_blocks: list[str] = []
        self.outlinks: list[str] = []
        self._in_title = False
        self._in_p = False
        self._in_li = False
        self._buf = []
        self._skip_tags = {"script", "style", "nav", "footer", "header"}
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag in self._skip_tags:
            self._skip_depth += 1
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = True
            self._buf = []
        elif tag == "meta":
            name = attrs_dict.get("name", "").lower()
            if name in ("description", "og:description"):
                self.meta_desc = attrs_dict.get("content", "")
        elif tag == "a":
            href = attrs_dict.get("href", "")
            if href and href.startswith("http") and href not in self.outlinks:
                self.outlinks.append(href)
        elif tag == "p":
            self._in_p = True
            self._buf = []
        elif tag == "li":
            self._in_li = True
            self._buf = []

    def handle_endtag(self, tag):
        if tag in self._skip_tags and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title" and self._in_title:
            self.title = " ".join(self._buf).strip()
            self._in_title = False
        elif tag == "p" and self._in_p:
            text = " ".join(self._buf).strip()
            if len(text) > 20:
                self.text_blocks.append(text)
            self._in_p = False
        elif tag == "li" and self._in_li:
            text = " ".join(self._buf).strip()
            if len(text) > 5:
                self.text_blocks.append(text)
            self._in_li = False

    def handle_data(self, data):
        if self._skip_depth:
            return
        if self._in_title or self._in_p or self._in_li:
            stripped = data.strip()
            if stripped:
                self._buf.append(stripped)

    @property
    def full_text(self) -> str:
        return " ".join(self.text_blocks)


# ── Extraction de données structurées ─────────────────────────────────────────

def extract_contact_info(text: str) -> dict:
    """Extrait téléphones, emails, SIREN/SIRET depuis du texte brut."""
    phones = list(set(_RE_TEL.findall(text)))
    emails = list(set(_RE_EMAIL.findall(text)))
    sirens = list(set(_RE_SIREN.findall(text)))
    sirets = list(set(_RE_SIRET.findall(text)))
    return {
        "phones": phones[:3],
        "emails": emails[:3],
        "sirens": sirens[:2],
        "sirets": sirets[:2],
    }


def gemma_analyze(entity_name: str, entity_type: str, text: str) -> str | None:
    """
    Analyse le texte scrapé avec Gemma 4 pour extraire des informations non structurées :
    personnes mentionnées, événements, liens avec d'autres entités locales, signaux notables.
    Retourne une synthèse textuelle ou None si échec.
    """
    import subprocess
    if not text or len(text) < 100:
        return None
    prompt = (
        f"Tu analyses le site web de '{entity_name}' ({entity_type}, {COMMUNE_NAME}, "
        f"département {DEPARTEMENT}, France).\n"
        f"Voici un extrait du texte de la page :\n\n{text[:2000]}\n\n"
        f"En 3-5 phrases maximum, identifie :\n"
        f"- Les personnes nommées (dirigeants, contacts, partenaires)\n"
        f"- Les événements ou activités mentionnés\n"
        f"- Les liens avec d'autres entités locales (mairie, associations, entreprises)\n"
        f"- Tout signal notable (conflit d'intérêt, subvention, marché public, élu)\n"
        f"Si rien de notable, réponds 'Rien de notable.'"
    )
    try:
        result = subprocess.run(
            ["ollama", "run", "gemma4:26b", prompt],
            capture_output=True, text=True, timeout=180
        )
        output = result.stdout
        # Supprimer les codes ANSI
        import re as _re
        output = _re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', output)
        # Extraire uniquement la réponse finale (après le bloc de réflexion)
        if "...done thinking." in output:
            output = output.split("...done thinking.")[-1]
        output = output.strip()
        if output:
            return output
    except Exception as e:
        print(f"    [Gemma erreur] {e}")
    return None


def detect_conflict_signals(text: str) -> list[str]:
    """Détecte les mentions de liens possibles avec la mairie."""
    text_lower = text.lower()
    return [kw for kw in _CONFLICT_KEYWORDS if kw in text_lower]


# Mots-clés dans les textes d'ancre ou hrefs indiquant une sous-page pertinente
_SUBPAGE_KEYWORDS = [
    "contact", "nous contacter", "coordonnées",
    "agenda", "événement", "evenement", "calendrier", "actualité", "actu", "news",
    "association", "présentation", "qui sommes", "à propos", "about",
    "membres", "bureau", "équipe", "adhérer", "adhésion",
    "activité", "programme", "projet",
]


class LinkParser(HTMLParser):
    """Parse les liens d'une page avec leur texte d'ancre."""
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.links: list[tuple[str, str]] = []  # (url, anchor_text)
        self._current_href: str = ""
        self._buf: list[str] = []
        self._in_a = False

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            if href:
                # Résoudre les URLs relatives
                if href.startswith("http"):
                    self._current_href = href
                elif href.startswith("/"):
                    from urllib.parse import urlparse
                    p = urlparse(self.base_url)
                    self._current_href = f"{p.scheme}://{p.netloc}{href}"
                else:
                    self._current_href = ""
                self._buf = []
                self._in_a = True

    def handle_endtag(self, tag):
        if tag == "a" and self._in_a:
            anchor = " ".join(self._buf).strip().lower()
            if self._current_href and anchor:
                self.links.append((self._current_href, anchor))
            self._in_a = False
            self._current_href = ""
            self._buf = []

    def handle_data(self, data):
        if self._in_a:
            stripped = data.strip()
            if stripped:
                self._buf.append(stripped)


def find_relevant_subpages(html: str, base_url: str, max_pages: int = 4) -> list[str]:
    """
    Identifie les sous-pages pertinentes à visiter (contact, agenda, présentation…).
    Ne retourne que des URLs du même domaine, dédupliquées, max max_pages.
    """
    from urllib.parse import urlparse
    base_domain = urlparse(base_url).netloc

    parser = LinkParser(base_url)
    parser.feed(html)

    seen = {base_url}
    relevant = []
    for url, anchor in parser.links:
        if urlparse(url).netloc != base_domain:
            continue
        if url in seen:
            continue
        url_lower = url.lower()
        anchor_lower = anchor.lower()
        if any(kw in anchor_lower or kw in url_lower for kw in _SUBPAGE_KEYWORDS):
            seen.add(url)
            relevant.append(url)
            if len(relevant) >= max_pages:
                break
    return relevant


# ── Récupération des entités à scraper depuis la DB ──────────────────────────

def get_entities_with_urls(
    entity_type: str | None = None,
    entity_id: int | None = None,
    limit: int = 0,
) -> list[dict]:
    """
    Récupère les entités ayant une URL ou un nom scrappable depuis la DB.
    Cherche les notes/metadata contenant des URLs.
    """
    conn = get_conn()
    try:
        base_query = """
            SELECT e.id, e.type, e.name, e.short_name, e.address,
                   e.lat, e.lng
            FROM entities e
            WHERE e.type IN ('association', 'business', 'place', 'service')
        """
        params: list = []
        if entity_type:
            base_query += " AND e.type = ?"
            params.append(entity_type)
        if entity_id:
            base_query += " AND e.id = ?"
            params.append(entity_id)
        base_query += " ORDER BY e.name"
        if limit:
            base_query += f" LIMIT {limit}"

        rows = conn.execute(base_query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_entity_urls(conn, entity_id: int) -> list[str]:
    """Récupère les URLs associées à une entité (notes, relations)."""
    urls = []

    # Chercher dans les notes/metadata (table events liée à l'entité)
    rows = conn.execute(
        "SELECT source_url FROM events WHERE metadata LIKE ? AND source_url != ''",
        (f'%"entity_id": {entity_id}%',)
    ).fetchall()
    for r in rows:
        if r["source_url"]:
            urls.append(r["source_url"])

    return list(set(urls))


# ── Chargement du catalogue depuis sites_locaux.json ─────────────────────────

def load_validated_websites(
    entity_type: str | None = None,
    entity_id: int | None = None,
    limit: int = 0,
) -> list[dict]:
    """Charge les URLs validées depuis entity_websites (status='validated')."""
    conn = get_conn()
    try:
        q = """
            SELECT e.id AS entity_id, e.type, e.name, e.short_name, e.address, e.lat, e.lng,
                   ew.url AS _url, ew.id AS ew_id
            FROM entity_websites ew
            JOIN entities e ON e.id = ew.entity_id
            WHERE ew.status = 'validated'
        """
        params: list = []
        if entity_type:
            q += " AND e.type = ?"
            params.append(entity_type)
        if entity_id:
            q += " AND e.id = ?"
            params.append(entity_id)
        q += " ORDER BY e.name"
        if limit:
            q += f" LIMIT {limit}"
        return [dict(r) for r in conn.execute(q, params).fetchall()]
    finally:
        conn.close()


def load_sites_catalogue() -> list[dict]:
    """Legacy : charge config/sites_locaux.json. Utilisé en fallback si entity_websites vide."""
    if not SITES_CONFIG.exists():
        return []
    data = json.loads(SITES_CONFIG.read_text(encoding="utf-8"))
    entries = []
    _section_type = {"associations": "association", "businesses": "business", "places": "place"}
    for section in ("associations", "businesses", "places"):
        for item in data.get(section, []):
            url = item.get("url")
            if url and item.get("entity_id"):
                item = dict(item)
                item.setdefault("_section", _section_type[section])
                entries.append(item)
    return entries


def find_url_for_entity(entity: dict) -> str | None:
    """Fallback : cherche une URL dans le catalogue JSON pour une entité DB."""
    catalogue = load_sites_catalogue()
    eid = entity.get("id") or entity.get("entity_id")
    for item in catalogue:
        if item.get("entity_id") == eid:
            return item["url"]
    return None


def list_missing_urls() -> None:
    """Affiche les entités du catalogue sans URL (pour complétion manuelle)."""
    if not SITES_CONFIG.exists():
        print(f"Catalogue absent : {SITES_CONFIG}")
        return
    data = json.loads(SITES_CONFIG.read_text(encoding="utf-8"))
    missing = []
    for section in ("associations", "businesses", "places"):
        for item in data.get(section, []):
            if not item.get("url"):
                missing.append(item)
    print(f"\n{len(missing)} entrées sans URL dans le catalogue :\n")
    for m in missing:
        notes = f"  → {m['notes']}" if m.get("notes") else ""
        print(f"  [{m['type']}] id={m.get('entity_id')} {m['name']}{notes}")


# ── Scrape d'une entité ───────────────────────────────────────────────────────

def scrape_entity(entity: dict, dry_run: bool = False, use_gemma: bool = False) -> dict | None:
    import datetime
    url = entity.get("_url") or find_url_for_entity(entity)
    if not url:
        return None

    eid = entity.get("id") or entity.get("entity_id")
    print(f"  → [{entity['type']}] {entity['name']} | {url}")
    if dry_run:
        return {"entity_id": eid, "url": url, "dry_run": True}

    started_at = datetime.datetime.utcnow().isoformat()
    html = fetch(url)
    if not html:
        return None
    time.sleep(REQUEST_DELAY)

    parser = PageInfoParser()
    parser.feed(html)

    # Visiter les sous-pages pertinentes (contact, agenda, présentation…)
    subpages = find_relevant_subpages(html, url)
    all_text = parser.full_text
    if subpages:
        print(f"    [+] {len(subpages)} sous-pages : {', '.join(s.split('/')[-1] or s.split('/')[-2] for s in subpages)}")
    for sub_url in subpages:
        sub_html = fetch(sub_url)
        if sub_html:
            sub_parser = PageInfoParser()
            sub_parser.feed(sub_html)
            all_text += " " + sub_parser.full_text
            time.sleep(REQUEST_DELAY)

    contact = extract_contact_info(all_text)
    conflicts = detect_conflict_signals(all_text)

    gemma_note = None
    if use_gemma and all_text:
        print(f"    [Gemma] analyse en cours…", end=" ", flush=True)
        gemma_note = gemma_analyze(entity["name"], entity["type"], all_text)
        print("ok" if gemma_note else "rien")

    result = {
        "entity_id": eid,
        "entity_name": entity["name"],
        "started_at": started_at,
        "http_status": 200,
        "url": url,
        "page_title": parser.title,
        "description": parser.meta_desc or (parser.text_blocks[0] if parser.text_blocks else ""),
        "contact": contact,
        "conflict_signals": conflicts,
        "outlinks": [l for l in parser.outlinks
                     if COMMUNE_NAME.lower() in l.lower()][:10],
        "text_preview": all_text[:1000],
        "gemma_note": gemma_note,
    }

    if conflicts:
        print(f"    [!] Signaux conflit d'intérêt : {conflicts}")

    return result


# ── Mise à jour DB ────────────────────────────────────────────────────────────

def record_scrape_run(conn, entity_id: int, url: str,
                      started_at: str, http_status: int | None,
                      items_found: int = 0) -> None:
    import hashlib, datetime
    conn.execute(
        "INSERT INTO scrape_runs (entity_id, url, started_at, finished_at, http_status, items_found)"
        " VALUES (?, ?, ?, datetime('now'), ?, ?)",
        (entity_id, url, started_at, http_status, items_found)
    )
    conn.execute(
        "UPDATE entity_websites SET last_scraped=datetime('now'), http_status=?"
        " WHERE entity_id=? AND url=?",
        (http_status, entity_id, url)
    )


def update_entity_from_scrape(conn, result: dict) -> None:
    """Enrichit l'entité DB avec les données scrapées (email, tel dans notes)."""
    eid = result["entity_id"]
    contact = result.get("contact", {})

    metadata = json.dumps({
        "scraped_url":       result["url"],
        "page_title":        result["page_title"],
        "emails":            contact.get("emails", []),
        "phones":            contact.get("phones", []),
        "sirens":            contact.get("sirens", []),
        "conflict_signals":  result.get("conflict_signals", []),
        "outlinks":          result.get("outlinks", []),
        "entity_id":         eid,
    }, ensure_ascii=False)

    conn.execute(
        "INSERT INTO events (type, title, source, source_url, metadata)"
        " VALUES ('scrape', ?, 'web_scraper', ?, ?)",
        (result["entity_name"], result["url"], metadata)
    )

    if result.get("gemma_note"):
        conn.execute(
            "INSERT INTO entity_notes (entity_id, date, note, source, confidence)"
            " VALUES (?, date('now'), ?, 'gemma_web', 'unverified')",
            (eid, result["gemma_note"])
        )

    if result.get("description"):
        conn.execute(
            "UPDATE entities SET updated_at=datetime('now')"
            " WHERE id=? AND (short_name IS NULL OR short_name='')",
            (eid,)
        )

    record_scrape_run(conn, eid, result["url"],
                      result.get("started_at", ""),
                      result.get("http_status"),
                      items_found=1 if result.get("gemma_note") else 0)


# ── Point d'entrée ────────────────────────────────────────────────────────────

def main(
    dry_run: bool = False,
    limit: int = 0,
    entity_type: str | None = None,
    entity_id: int | None = None,
    missing: bool = False,
    use_gemma: bool = False,
) -> None:
    if missing:
        list_missing_urls()
        return

    print(f"\n[web_scraper] dry_run={dry_run} limit={limit} "
          f"type={entity_type} entity_id={entity_id} gemma={use_gemma}")

    # Priorité : entity_websites (validated) → fallback JSON legacy
    scrapable = load_validated_websites(entity_type=entity_type, entity_id=entity_id, limit=limit)

    if not scrapable:
        print("  Aucune URL validée dans entity_websites — fallback JSON legacy")
        catalogue = load_sites_catalogue()
        if entity_type:
            catalogue = [c for c in catalogue if c.get("_section") == entity_type or c.get("type") == entity_type]
        if entity_id:
            catalogue = [c for c in catalogue if c.get("entity_id") == entity_id]
        if limit:
            catalogue = catalogue[:limit]
        conn_tmp = get_conn()
        for item in catalogue:
            row = conn_tmp.execute(
                "SELECT id, type, name, short_name, address, lat, lng FROM entities WHERE id=?",
                (item["entity_id"],)
            ).fetchone()
            if row:
                e = dict(row)
                e["_url"] = item["url"]
                scrapable.append(e)
        conn_tmp.close()

    print(f"  {len(scrapable)} entités à scraper")

    results = []
    for entity in scrapable:
        r = scrape_entity(entity, dry_run=dry_run, use_gemma=use_gemma)
        if r:
            results.append(r)

    if dry_run:
        print(f"\n[dry-run] {len(results)} entités seraient scrapées")
        _bilan_reseau()
        return

    updated = 0
    with transaction() as conn:
        for r in results:
            update_entity_from_scrape(conn, r)
            updated += 1

    print(f"\n[web_scraper] {updated} entités enrichies en DB")

    # Rapport des signaux d'alerte
    alerts = [r for r in results if r.get("conflict_signals")]
    if alerts:
        print(f"\n  [!] {len(alerts)} entités avec signaux conflit d'intérêt :")
        for r in alerts:
            print(f"    • {r['entity_name']} : {r['conflict_signals']}")

    _bilan_reseau()


def _bilan_reseau() -> None:
    """Relève une panne réseau totale ; signale les échecs partiels dans le log."""
    ok, err = _reseau["ok"], _reseau["err"]
    if err and not ok:
        raise RuntimeError(
            f"réseau indisponible : {err} requête(s), toutes en échec — "
            f"dernière : {_reseau['derniere_erreur']}"
        )
    if err:
        print(f"  [erreur] {err} requête(s) en échec sur {ok + err} — "
              f"dernière : {_reseau['derniere_erreur']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scraper des sites web des entités locales")
    parser.add_argument("--dry-run",     action="store_true", help="Affiche sans modifier la DB")
    parser.add_argument("--limit",  "-n", type=int,  default=0, help="Nombre max d'entités")
    parser.add_argument("--type",   "-t", default=None,
                        choices=["association", "business", "place", "service"],
                        help="Filtrer par type d'entité")
    parser.add_argument("--entity-id", type=int, default=None,
                        help="Scraper une seule entité par son ID DB")
    parser.add_argument("--missing", action="store_true",
                        help="Lister les entités sans URL dans le catalogue")
    parser.add_argument("--gemma", action="store_true",
                        help="Analyse Gemma 4 post-scrape (lent, ~2min/entité)")
    args = parser.parse_args()
    main(
        dry_run=args.dry_run,
        limit=args.limit,
        entity_type=args.type,
        entity_id=args.entity_id,
        missing=args.missing,
        use_gemma=args.gemma,
    )
