"""
events_scraper.py — Événements locaux Lasalle (lasalle.fr + sites assos)

Scrape les pages d'actualités et d'agenda de lasalle.fr ainsi que les sites
des associations locales pour alimenter la table `events` (type='local_event').

Usage :
  python3 -m collectors.events_scraper --dry-run
  python3 -m collectors.events_scraper
  python3 -m collectors.events_scraper --limit 50
  python3 -m collectors.events_scraper --source lasalle      # seulement lasalle.fr
  python3 -m collectors.events_scraper --source associations # seulement les assos
"""

import argparse
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from html.parser import HTMLParser

from .config import LASALLE_URL, HEADERS, REQUEST_DELAY
from .archive import archive_fetch
from .db import transaction

# ── Helpers HTTP ──────────────────────────────────────────────────────────────

def fetch(url: str, timeout: int = 15) -> str | None:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            encoding = r.headers.get_content_charset("utf-8")
            archive_fetch("lasalle.fr", url, raw, r.headers.get_content_type(), r.status)
            return raw.decode(encoding, errors="replace")
    except (urllib.error.URLError, TimeoutError, Exception) as e:
        print(f"  [erreur] {url} → {e}")
        return None

# ── Parseurs HTML minimalistes ────────────────────────────────────────────────

class ArticleListParser(HTMLParser):
    """
    Extrait les liens d'articles depuis les pages d'actualités/agenda lasalle.fr.
    Cherche les <a href> contenant des slugs d'événements ou d'actualités.
    """
    def __init__(self):
        super().__init__()
        self.links: list[dict] = []
        self._current_href = None
        self._current_text = []
        self._in_link = False

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            attrs_dict = dict(attrs)
            href = attrs_dict.get("href", "")
            if href and not href.startswith(("#", "mailto:", "tel:")):
                self._current_href = href
                self._in_link = True
                self._current_text = []

    def handle_endtag(self, tag):
        if tag == "a" and self._in_link:
            text = " ".join(self._current_text).strip()
            if self._current_href and len(text) > 10:
                self.links.append({"href": self._current_href, "text": text})
            self._in_link = False
            self._current_href = None

    def handle_data(self, data):
        if self._in_link:
            stripped = data.strip()
            if stripped:
                self._current_text.append(stripped)


class AgendaStreamParser(HTMLParser):
    """Extrait les items d'agenda (thème Drupal lasalle.fr).

    Chaque événement porte un titre dans un heading `.title`/`.post-title`
    (<a href="/actualites/…">) et une ou deux balises <time datetime="ISO">
    (début, et fin si événement récurrent/multi-jours). L'ordre titre/date
    varie selon la page (date APRÈS le titre sur /agendas, AVANT sur les pages
    /structures/…) : on associe donc chaque titre aux <time> adjacents non
    encore consommés, quel que soit l'ordre.
    """

    def __init__(self):
        super().__init__()
        self.items: list[dict] = []
        self._pending_times: list[str] = []   # <time> vus depuis le dernier titre
        self._awaiting = None                 # titre en attente de <time> suivants
        self._in_title_head = False           # dans un heading .title / .post-title
        self._in_title_a = False              # dans le <a> du titre
        self._title_buf: list[str] = []

    @staticmethod
    def _iso(dt: str) -> str | None:
        m = re.match(r"(\d{4}-\d{2}-\d{2})", dt or "")
        return m.group(1) if m else None

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        cls = d.get("class", "")
        if tag in ("h1", "h2", "h3", "h4") and ("title" in cls):
            self._in_title_head = True
        elif tag == "a" and self._in_title_head and not self._in_title_a:
            self._begin_title(d.get("href", ""))
        elif tag == "time":
            iso = self._iso(d.get("datetime", ""))
            if iso:
                self._add_time(iso)

    def handle_endtag(self, tag):
        if tag == "a" and self._in_title_a:
            self._end_title()
        elif tag in ("h1", "h2", "h3", "h4") and self._in_title_head:
            self._in_title_head = False

    def handle_data(self, data):
        if self._in_title_a:
            s = data.strip()
            if s:
                self._title_buf.append(s)

    # ── association titre ↔ dates ────────────────────────────────────────────
    def _begin_title(self, href):
        self._in_title_a = True
        self._title_buf = []
        self._href = href

    def _end_title(self):
        self._in_title_a = False
        title = " ".join(self._title_buf).strip()
        if not title:
            return
        item = {"title": title, "url": self._href, "date": None, "date_end": None}
        if self._pending_times:                 # dates AVANT le titre (pages /structures)
            item["date"] = self._pending_times[0]
            if len(self._pending_times) > 1:
                item["date_end"] = self._pending_times[-1]
            self._pending_times = []
            self._awaiting = None
        else:                                    # dates APRÈS le titre (page /agendas)
            self._awaiting = item
        self.items.append(item)

    def _add_time(self, iso):
        if self._awaiting is not None:
            if not self._awaiting["date"]:
                self._awaiting["date"] = iso
            else:
                self._awaiting["date_end"] = iso
        else:
            self._pending_times.append(iso)


# ── Normalisation dates ───────────────────────────────────────────────────────

_MOIS = {
    "janvier": "01", "février": "02", "fevrier": "02", "mars": "03", "avril": "04",
    "mai": "05", "juin": "06", "juillet": "07", "août": "08", "aout": "08",
    "septembre": "09", "octobre": "10", "novembre": "11", "décembre": "12", "decembre": "12",
    # abréviations affichées par le thème (fallback texte)
    "janv": "01", "févr": "02", "fevr": "02", "avr": "04", "juil": "07",
    "sept": "09", "oct": "10", "nov": "11", "déc": "12", "dec": "12", "aoû": "08",
}

def normalize_date(raw: str) -> str | None:
    """Tente de normaliser une date texte en ISO YYYY-MM-DD."""
    if not raw:
        return None
    raw = raw.strip()
    # Format ISO direct
    m = re.match(r"(\d{4}-\d{2}-\d{2})", raw)
    if m:
        return m.group(1)
    # Format "12 novembre 2024" ou "12 novembre"
    m = re.match(r"(\d{1,2})\s+(\w+)\s+(\d{4})", raw.lower())
    if m:
        jour, mois, an = m.group(1), m.group(2), m.group(3)
        num = _MOIS.get(mois)
        if num:
            return f"{an}-{num}-{int(jour):02d}"
    return None


# ── Scraper lasalle.fr ────────────────────────────────────────────────────────

# Pages d'actualités et d'agenda à explorer sur lasalle.fr
LASALLE_PAGES = [
    "/agendas",         # agenda officiel (était /agenda — corrigé 07/04/2026)
    "/actu_municipale", # rubriques municipales
]

def is_event_slug(href: str, text: str) -> bool:
    """Heuristique : l'URL ou le texte ressemble à un événement."""
    text_lower = text.lower()
    event_keywords = [
        "fête", "festival", "feria", "marché", "concert", "spectacle",
        "exposition", "randonnée", "repas", "soirée", "bal", "tournoi",
        "vide-grenier", "brocante", "forum", "journée", "nuit", "semaine",
        "châtaigne", "chataigne", "noël", "noel", "bastille", "feu",
        "animation", "sortie", "rencontre", "conférence", "conférence",
        "assemblée", "assemblée générale",
    ]
    return any(kw in text_lower for kw in event_keywords)


def _abs_url(base: str, href: str) -> str:
    """URL absolue à partir d'un href relatif et de la page de base."""
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        # Toujours rattacher au domaine de la page de base (lasalle.fr ou site asso).
        m = re.match(r"(https?://[^/]+)", base)
        root = m.group(1) if m else LASALLE_URL
        return root + href
    return base.rstrip("/") + "/" + href.lstrip("/")


def _source_from_url(url: str) -> str:
    """Source = domaine réel de l'événement (pour l'allowlist de publication).
    Les pages /structures/… d'assos sont hébergées par lasalle.fr → source lasalle.fr."""
    host = urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")
    return "lasalle.fr" if host.endswith("lasalle.fr") else (host or "lasalle.fr")


def scrape_lasalle_events(dry_run: bool = False, limit: int = 0) -> list[dict]:
    events, seen = [], set()

    for page_path in LASALLE_PAGES:
        url = LASALLE_URL + page_path
        print(f"  → {url}")
        html = fetch(url)
        if not html:
            continue
        time.sleep(REQUEST_DELAY)

        parser = AgendaStreamParser()
        parser.feed(html)

        for it in parser.items:
            full_url = _abs_url(url, it["url"])
            key = (it["title"], it.get("date"))
            if key in seen:
                continue
            seen.add(key)
            events.append({
                "url": full_url,
                "title": it["title"],
                "date": it.get("date"),
                "date_end": it.get("date_end"),
                "source": "lasalle.fr",
                "content": "",
            })
            if limit and len(events) >= limit:
                break
        if limit and len(events) >= limit:
            break

    if dry_run:
        dated = sum(1 for e in events if e.get("date"))
        print(f"\n  [dry-run] {len(events)} événements lasalle.fr ({dated} datés)")
        for e in events[:12]:
            span = e["date"] + (f" → {e['date_end']}" if e.get("date_end") else "")
            print(f"    {span or 'sans date':<24} {e['title'][:55]}")
    return events


# ── Sites associations locales ────────────────────────────────────────────────

# Sites d'associations et entités locales à scraper pour leurs événements
ASSO_SITES = [
    {"name": "ADYCT",             "url": "https://dev.adyct.org",                                                                   "type": "association"},
    {"name": "Art Scène",         "url": "https://www.lasalle.fr/categories-de-structures/artistique",                             "type": "association"},
    {"name": "Champ Contrechamp", "url": "https://champcontrechamp.com",                                                           "type": "association"},
    {"name": "Comité des Fêtes",  "url": "https://www.lasalle.fr/structures/comite-des-fetes-de-lasalle",                         "type": "association"},
    {"name": "Mandragora",        "url": "https://www.lasalle.fr/structures/association-mandragora",                               "type": "association"},
    {"name": "Médiathèque Alice Guy", "url": "https://www.lasalle.fr/structures/mediatheque-intercommunale-alice-guy",             "type": "association"},
]

def scrape_asso_events(dry_run: bool = False, limit: int = 0) -> list[dict]:
    events = []
    for asso in ASSO_SITES:
        if limit and len(events) >= limit:
            break
        print(f"  → {asso['name']} ({asso['url']})")
        html = fetch(asso["url"])
        if not html:
            continue
        time.sleep(REQUEST_DELAY)

        # 1) Parseur structuré (pages /structures/… lasalle.fr : titre + <time datetime>).
        agenda = AgendaStreamParser()
        agenda.feed(html)
        dated = [it for it in agenda.items if it.get("date")]
        for it in dated:
            full_url = _abs_url(asso["url"], it["url"])
            events.append({
                "title": it["title"],
                "url": full_url,
                "source": _source_from_url(full_url),
                "organizer": asso["name"],
                "date": it["date"],
                "date_end": it.get("date_end"),
                "content": "",
            })

        # 2) Repli (sites externes sans <time> structuré) : liens + heuristique événement,
        #    date tentée depuis le texte du lien. Évite les doublons déjà captés en 1).
        if not dated:
            seen_titles = {e["title"] for e in events}
            parser = ArticleListParser()
            parser.feed(html)
            for link in parser.links:
                href, text = link["href"], link["text"]
                if len(text) < 8 or not is_event_slug(href, text) or text in seen_titles:
                    continue
                full_url = _abs_url(asso["url"], href)
                events.append({
                    "title": text,
                    "url": full_url,
                    "source": _source_from_url(full_url),
                    "organizer": asso["name"],
                    "date": normalize_date(text),
                    "date_end": None,
                    "content": "",
                })

    if dry_run:
        dated = sum(1 for e in events if e.get("date"))
        print(f"\n  [dry-run] {len(events)} événements assos ({dated} datés)")
        for e in events[:12]:
            span = (e.get("date") or "sans date") + (f" → {e['date_end']}" if e.get("date_end") else "")
            print(f"    {span:<24} {e['source']} | {e['title'][:45]}")

    return events


# ── Insertion DB ──────────────────────────────────────────────────────────────

def insert_event(conn, ev: dict) -> int | None:
    """Insère un événement local, ou ENRICHIT une ligne existante sans date.

    Idempotent et auto-réparateur : si le même titre existe déjà sans date
    (résidu d'une collecte antérieure sans extraction de date) et qu'on dispose
    maintenant d'une date, on remplit le champ vide plutôt que de dupliquer.
    """
    title = ev.get("title", "").strip()
    if not title:
        return None
    date = ev.get("date")
    metadata = json.dumps({
        "source_name": ev.get("source", ""),
        "organizer": ev.get("organizer", ""),   # asso/structure organisatrice (affichage)
        "date_end": ev.get("date_end"),          # fin d'un événement multi-jours (pour « À venir »)
        "content_preview": (ev.get("content") or "")[:500],
    }, ensure_ascii=False)

    if date:
        # Doublon exact (même titre + date) → rien à faire.
        if conn.execute(
            "SELECT 1 FROM events WHERE type='local_event' AND date=? AND title=?",
            (date, title),
        ).fetchone():
            return None
        # Ligne sans date, même titre → enrichir (remplir un champ vide, pas d'écrasement).
        row = conn.execute(
            "SELECT id FROM events WHERE type='local_event' AND (date IS NULL OR date='') AND title=? LIMIT 1",
            (title,),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE events SET date=?, metadata=?, "
                "source_url=CASE WHEN source_url IS NULL OR source_url='' THEN ? ELSE source_url END "
                "WHERE id=?",
                (date, metadata, ev.get("url", ""), row[0]),
            )
            return row[0]
    else:
        # Sans date : ne pas insérer si le titre existe déjà (datée ou non).
        if conn.execute(
            "SELECT 1 FROM events WHERE type='local_event' AND title=? LIMIT 1", (title,)
        ).fetchone():
            return None

    cur = conn.execute(
        "INSERT INTO events (type, date, title, source, source_url, metadata)"
        " VALUES ('local_event', ?, ?, ?, ?, ?)",
        (date, title, ev.get("source", ""), ev.get("url", ""), metadata),
    )
    return cur.lastrowid


# ── Point d'entrée ────────────────────────────────────────────────────────────

def main(dry_run: bool = False, limit: int = 0, source: str = "all") -> None:
    print(f"\n[events_scraper] dry_run={dry_run} limit={limit} source={source}")

    all_events: list[dict] = []

    if source in ("all", "lasalle"):
        print("\nScraping lasalle.fr …")
        all_events += scrape_lasalle_events(dry_run=dry_run, limit=limit)

    if source in ("all", "associations"):
        print("\nScraping sites associations …")
        all_events += scrape_asso_events(dry_run=dry_run, limit=limit)

    if dry_run:
        print(f"\n[dry-run] Total : {len(all_events)} événements trouvés")
        return

    inserted = 0
    with transaction() as conn:
        for ev in all_events:
            eid = insert_event(conn, ev)
            if eid:
                inserted += 1
                print(f"  [+] {ev['title'][:60]} ({ev.get('date', 'sans date')})")

    print(f"\n[events_scraper] {inserted}/{len(all_events)} événements insérés")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scraper événements locaux Lasalle")
    parser.add_argument("--dry-run",    action="store_true", help="Affiche sans insérer")
    parser.add_argument("--limit",  "-n", type=int, default=0, help="Nombre max d'événements")
    parser.add_argument("--source", "-s", default="all",
                        choices=["all", "lasalle", "associations"],
                        help="Source à scraper")
    args = parser.parse_args()
    main(dry_run=args.dry_run, limit=args.limit, source=args.source)
