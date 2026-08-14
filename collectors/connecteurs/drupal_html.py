"""
Connecteur Drupal sans API — lecture du HTML rendu.

Certains sites de mairie tournent sous Drupal sans que JSON:API soit activé :
`/jsonapi` répond 404, et il ne reste que les pages. C'est le cas de
l'instance de référence du dispositif, et c'est le cas le plus coûteux :
là où un site qui expose son API rend des objets typés (date ISO, catégories,
lien canonique), il faut ici deviner une structure de thème.

Ce que ce connecteur suppose du site, et qu'un autre thème Drupal ne respectera
pas forcément :

  - une page qui LISTE les comptes rendus, chacun sur sa propre page, chaque
    page portant un lien vers le PDF de la séance. Deux requêtes par séance,
    donc, au lieu d'une lecture de catalogue ;
  - un agenda dont chaque élément associe un titre dans un `<h*>` de classe
    `title` et une ou deux balises `<time datetime="…">`. L'ORDRE varie selon
    la page : la date suit le titre sur l'agenda, le précède sur les pages de
    structure. Le parseur associe donc chaque titre aux `<time>` adjacents non
    encore consommés, quel que soit le sens.

Ces deux hypothèses ont tenu trois ans sur ce site. Elles ne sont pas
« Drupal » : elles sont « ce thème-là ». Un autre site sous le même CMS
demandera un autre connecteur, et c'est la mesure honnête du coût de portage.

Déclaration dans `config/instance.json` :

    "connecteur": "drupal_html",
    "pages": {
      "commune": {"conseil": "/compte-rendus-des-conseils",
                  "agenda": ["/agendas", "/actu_municipale"]},
      "epci":    {"conseil": "/pv/", "agenda": ["/actualites/"]}
    }

Les chemins sont ici des CHEMINS de page, pas des slugs : un site sans API
n'a pas de notion de « slug » interrogeable.
"""
from __future__ import annotations

import re
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from .base import (Article, Connecteur, DocumentPublie, Portee, date_fr,
                   texte_brut)
from .datation import date_evenement

# Mois en toutes lettres dans les adresses de page : « …-du-05-fevrier-2026 ».
MOIS_SLUG = {
    "janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "aout": 8, "août": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "decembre": 12, "décembre": 12,
}
DATE_SLUG = re.compile(
    r"(\d{1,2})-(" + "|".join(MOIS_SLUG) + r")-(\d{4})", re.I)
DATE_SLUG_NUM = re.compile(r"(\d{1,2})[-.](\d{1,2})[-.](\d{4})")


class AgendaParser(HTMLParser):
    """Titres et dates d'un flux d'agenda Drupal.

    Chaque événement porte un titre dans un heading de classe `title` ou
    `post-title` et une ou deux balises `<time datetime>` (début, et fin pour un
    événement sur plusieurs jours). L'ordre titre/date change d'une page à
    l'autre : on rattache chaque titre aux `<time>` voisins non consommés.
    """

    def __init__(self):
        super().__init__()
        self.items: list[dict] = []
        self._attente: list[str] = []      # <time> vus depuis le dernier titre
        self._en_cours = None              # titre attendant ses <time> suivants
        self._dans_titre = False
        self._dans_lien = False
        self._tampon: list[str] = []
        self._href = ""

    @staticmethod
    def _iso(valeur: str) -> str | None:
        m = re.match(r"(\d{4}-\d{2}-\d{2})", valeur or "")
        return m.group(1) if m else None

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag in ("h1", "h2", "h3", "h4") and "title" in d.get("class", ""):
            self._dans_titre = True
        elif tag == "a" and self._dans_titre and not self._dans_lien:
            self._dans_lien = True
            self._tampon = []
            self._href = d.get("href", "")
        elif tag == "time":
            iso = self._iso(d.get("datetime", ""))
            if iso:
                self._ajouter_date(iso)

    def handle_endtag(self, tag):
        if tag == "a" and self._dans_lien:
            self._finir_titre()
        elif tag in ("h1", "h2", "h3", "h4") and self._dans_titre:
            self._dans_titre = False

    def handle_data(self, data):
        if self._dans_lien and data.strip():
            self._tampon.append(data.strip())

    def _finir_titre(self):
        self._dans_lien = False
        titre = " ".join(self._tampon).strip()
        if not titre:
            return
        item = {"titre": titre, "url": self._href, "date": None, "date_fin": None}
        if self._attente:                      # dates AVANT le titre
            item["date"] = self._attente[0]
            if len(self._attente) > 1:
                item["date_fin"] = self._attente[-1]
            self._attente = []
            self._en_cours = None
        else:                                   # dates APRÈS le titre
            self._en_cours = item
        self.items.append(item)

    def _ajouter_date(self, iso: str):
        if self._en_cours is not None:
            if not self._en_cours["date"]:
                self._en_cours["date"] = iso
            else:
                self._en_cours["date_fin"] = iso
        else:
            self._attente.append(iso)


class ConnecteurDrupal(Connecteur):
    nom = "drupal_html"

    def __init__(self):
        from ..config import COMMUNE_URL, EPCI_URL, PAGES
        self.pages = PAGES or {}
        self.bases = {"commune": (COMMUNE_URL or "").rstrip("/"),
                      "epci": (EPCI_URL or "").rstrip("/")}

    # ── transport ────────────────────────────────────────────────────────────
    def _html(self, url: str) -> str | None:
        from ..archive import archive_fetch
        from ..config import HEADERS, REQUEST_DELAY

        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                brut = r.read()
                archive_fetch(_domaine(url), url, brut,
                              r.headers.get_content_type(), r.status)
                return brut.decode(r.headers.get_content_charset("utf-8"),
                                   errors="replace")
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            print(f"  [drupal][erreur] {url} → {e}")
            return None
        finally:
            time.sleep(REQUEST_DELAY)

    def _url(self, portee: Portee, chemin: str) -> str:
        base = self.bases.get(portee, "")
        return chemin if chemin.startswith("http") else base + "/" + chemin.lstrip("/")

    # ── documents ────────────────────────────────────────────────────────────
    def catalogue_pv(self, portee: Portee = "commune") -> list[DocumentPublie]:
        chemin = (self.pages.get(portee) or {}).get("conseil")
        if not chemin or not self.bases.get(portee):
            return []
        listing = self._url(portee, chemin)
        html = self._html(listing)
        if not html:
            return []

        # Les liens de la page de listing qui mènent à une séance. On ne retient
        # que ceux dont l'adresse porte une date : le reste est de la navigation.
        liens, vus = [], set()
        for href in re.findall(r'href="([^"#?]+)"', html):
            absolu = urllib.parse.urljoin(listing, href)
            if not absolu.startswith(self.bases[portee]) or absolu in vus:
                continue
            date = _date_depuis_adresse(absolu)
            if not date:
                continue
            vus.add(absolu)
            liens.append((date, absolu))

        documents = []
        for date, page in sorted(liens, reverse=True):
            # Le PDF de la séance est SUR la page, pas dans le listing : une
            # requête de plus par séance, et c'est irréductible ici.
            if page.lower().endswith(".pdf"):
                documents.append(DocumentPublie(date=date, url=page,
                                                libelle=_libelle(page),
                                                source=_domaine(page)))
                continue
            interne = self._html(page)
            if not interne:
                continue
            pdf = re.search(r'href="([^"]+\.pdf[^"]*)"', interne, re.I)
            if not pdf:
                print(f"  [drupal] aucun PDF sur {page}")
                continue
            documents.append(DocumentPublie(
                date=date, url=urllib.parse.urljoin(page, pdf.group(1)),
                libelle=_libelle(page), source=_domaine(page)))
        return documents

    # ── articles ─────────────────────────────────────────────────────────────
    def articles(self, portee: Portee = "commune",
                 depuis: str | None = None) -> list[Article]:
        chemins = (self.pages.get(portee) or {}).get("agenda") or []
        if not self.bases.get(portee):
            return []
        sorties, vus = [], set()
        for chemin in chemins:
            url = self._url(portee, chemin)
            html = self._html(url)
            if not html:
                continue
            parseur = AgendaParser()
            parseur.feed(html)
            for item in parseur.items:
                cle = (item["titre"], item.get("date"))
                if cle in vus:
                    continue
                vus.add(cle)
                lien = urllib.parse.urljoin(url, item["url"] or "")
                publie = item.get("date") or ""
                if depuis and publie and publie < depuis:
                    continue
                # Un agenda donne la date de l'événement : c'est le cas rare
                # où elle ne s'infère pas. À défaut, on retombe sur la datation
                # commune, qui le dira.
                if publie:
                    date, origine = publie, "texte"
                else:
                    date, origine = date_evenement(item["titre"], "", "")
                sorties.append(Article(
                    titre=item["titre"], url=lien, date=date,
                    date_publication=publie or date, date_source=origine,
                    contenu="", rubriques=[chemin.strip("/")],
                    source=_domaine(lien or url)))
        return sorties

    # ── marchés ──────────────────────────────────────────────────────────────
    def avis_marches(self) -> list[dict]:
        avis = []
        for portee in ("epci", "commune"):
            chemin = (self.pages.get(portee) or {}).get("marches")
            if not chemin or not self.bases.get(portee):
                continue
            url = self._url(portee, chemin)
            html = self._html(url)
            if not html:
                continue
            # Sans API, l'unité d'information est le PDF d'avis lui-même : les
            # blocs d'article du thème ne sont pas assez réguliers pour être
            # découpés sans risque.
            for href in sorted(set(re.findall(r'href="([^"]+\.pdf[^"]*)"', html, re.I))):
                lien = urllib.parse.urljoin(url, href)
                nom = _libelle(lien)
                if any(x in nom.lower() for x in
                       ("guide", "notice", "dematerialisation", "reglement-consultation")):
                    continue
                avis.append({
                    "source": _domaine(lien), "portee": portee,
                    "objet": nom, "date_pub": _date_depuis_adresse(lien) or "",
                    "pdf_url": lien, "raw_id": lien,
                })
        return avis

    def pages_annuaire(self, portee: Portee = "commune") -> list[str]:
        chemins = (self.pages.get(portee) or {}).get("annuaires") or []
        textes = []
        for chemin in chemins:
            html = self._html(self._url(portee, chemin))
            if html:
                textes.append(texte_brut(html))
        return textes


def _date_depuis_adresse(url: str) -> str | None:
    """Date portée par l'adresse d'une page ou d'un fichier."""
    chemin = urllib.parse.unquote(urllib.parse.urlparse(url).path)
    m = DATE_SLUG.search(chemin)
    if m:
        return f"{m.group(3)}-{MOIS_SLUG[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    m = DATE_SLUG_NUM.search(chemin)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return date_fr(chemin.replace("-", " "))


def _libelle(url: str) -> str:
    nom = urllib.parse.unquote(urllib.parse.urlparse(url).path).rstrip("/")
    return nom.rsplit("/", 1)[-1].replace("-", " ").replace("_", " ")


def _domaine(url: str) -> str:
    return urllib.parse.urlparse(url or "").netloc.removeprefix("www.")


CONNECTEUR = ConnecteurDrupal
