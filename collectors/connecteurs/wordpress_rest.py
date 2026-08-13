"""
Connecteur WordPress — lecture par l'API REST publique (`/wp-json/wp/v2/`).

WordPress expose par défaut, en lecture anonyme, des objets typés : date ISO,
catégories, lien canonique, contenu rendu. Sur le territoire du premier portage,
les deux sites officiels — mairie et intercommunalité — l'exposaient : 1 889
articles, 38 pages et 5 947 médias d'un côté, 141 et 71 de l'autre. Il n'y avait
donc rien à scraper au sens HTML, là où le connecteur de la commune d'origine
devait deviner la structure d'un thème Drupal à coups de HTMLParser.

Ce connecteur ne s'applique qu'au CONTENU des pages (`content.rendered`), jamais
à leur habillage : c'est ce qui le rend indifférent au thème installé.

Déclaration dans `config/instance.json` :

    "connecteur": "wordpress_rest",
    "pages": {
      "commune": {
        "conseil": "conseil-municipal",
        "annuaires": ["associations-sportives", "annuaire"],
        "categories": ["animations", "evenements-culturels", "culture"]
      },
      "epci": {
        "conseil": "conseil-de-communaute",
        "categories": ["actu", "culture"],
        "marches": "appel-doffres"
      }
    }

Les slugs sont propres à chaque site : ce sont eux, et non du code, qui portent
la particularité. Un site WordPress sans page « conseil municipal » rendra un
catalogue vide, ce qui est une lacune à publier, pas une erreur à masquer.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from .base import (Article, Connecteur, DocumentPublie, Portee, date_fr,
                   liens_pdf, texte_brut)

# Plafond dur de pagination : une API qui répond toujours « il y a une page de
# plus » ne doit pas pouvoir faire tourner un collecteur indéfiniment.
MAX_PAGES = 60
PER_PAGE = 100


class Site:
    """Un site WordPress interrogé par son API REST publique."""

    def __init__(self, base: str, source: str):
        self.base = (base or "").rstrip("/")
        self.source = source

    def __bool__(self) -> bool:
        return bool(self.base)

    def _get(self, chemin: str, params: dict | None = None,
             timeout: int = 20) -> tuple[object | None, dict]:
        from ..archive import archive_fetch
        from ..config import HEADERS, REQUEST_DELAY

        if not self.base:
            return None, {}
        url = f"{self.base}/wp-json/wp/v2/{chemin}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                archive_fetch(self.source, url, raw,
                              r.headers.get_content_type(), r.status)
                entetes = {k.lower(): v for k, v in r.headers.items()}
                return json.loads(raw.decode("utf-8", errors="replace")), entetes
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            print(f"  [wp][erreur] {url} → {e}")
            return None, {}
        finally:
            time.sleep(REQUEST_DELAY)

    def _paginer(self, chemin: str, params: dict):
        page = 1
        while page <= MAX_PAGES:
            data, entetes = self._get(chemin, {**params, "page": page,
                                               "per_page": PER_PAGE})
            if not data:
                return
            yield from data
            if page >= int(entetes.get("x-wp-totalpages") or 1):
                return
            page += 1

    def posts(self, apres: str | None = None, categories: list[int] | None = None):
        """Articles publiés, du plus récent au plus ancien.

        `apres` filtre côté serveur : sur près de deux mille articles, ramener
        toute la collection à chaque exécution pour n'en garder que trois est le
        genre de détail qui fait qu'un collecteur finit par ne plus être lancé.
        """
        params = {"orderby": "date", "order": "desc", "status": "publish"}
        if apres:
            params["after"] = f"{apres}T00:00:00"
        if categories:
            params["categories"] = ",".join(str(c) for c in categories)
        return self._paginer("posts", params)

    def page(self, slug: str) -> dict | None:
        data, _ = self._get("pages", {"slug": slug, "status": "publish"})
        return data[0] if data else None

    def categories(self) -> dict[str, dict]:
        data, _ = self._get("categories", {"per_page": PER_PAGE})
        return {c["slug"]: c for c in (data or [])}


class ConnecteurWordPress(Connecteur):
    nom = "wordpress_rest"

    def __init__(self):
        from ..config import COMMUNE_URL, EPCI_URL, PAGES
        self.pages = PAGES or {}
        self.sites = {
            "commune": Site(COMMUNE_URL, _domaine(COMMUNE_URL)),
            "epci": Site(EPCI_URL, _domaine(EPCI_URL)),
        }

    # ── documents ────────────────────────────────────────────────────────────
    def catalogue_pv(self, portee: Portee = "commune") -> list[DocumentPublie]:
        site = self.sites[portee]
        slug = (self.pages.get(portee) or {}).get("conseil")
        if not site or not slug:
            return []
        page = site.page(slug)
        if not page:
            print(f"  [wp] page /{slug}/ introuvable sur {site.base}")
            return []

        documents, vus = [], set()
        for lien in liens_pdf(page["content"]["rendered"]):
            date = date_fr(lien["libelle"]) or date_fr(lien["url"])
            if not date or lien["url"] in vus:
                continue
            vus.add(lien["url"])
            documents.append(DocumentPublie(date=date, url=lien["url"],
                                            libelle=lien["libelle"],
                                            source=site.source))
        documents.sort(key=lambda d: d.date, reverse=True)
        return documents

    # ── articles ─────────────────────────────────────────────────────────────
    def articles(self, portee: Portee = "commune",
                 depuis: str | None = None) -> list[Article]:
        from .datation import date_evenement

        site = self.sites[portee]
        slugs = (self.pages.get(portee) or {}).get("categories") or []
        if not site or not slugs:
            return []

        cats = site.categories()
        ids = [cats[s]["id"] for s in slugs if s in cats]
        manquants = [s for s in slugs if s not in cats]
        if manquants:
            print(f"  [{site.source}] catégories absentes : {', '.join(manquants)}")
        if not ids:
            return []

        sorties = []
        for post in site.posts(apres=depuis, categories=ids):
            titre = texte_brut(post["title"]["rendered"])
            if not titre:
                continue
            contenu = texte_brut(post.get("content", {}).get("rendered", ""))
            publie = post.get("date", "")[:10]
            date, origine = date_evenement(titre, contenu, publie)
            sorties.append(Article(
                titre=titre, url=post.get("link", ""), date=date,
                date_publication=publie, date_source=origine, contenu=contenu,
                rubriques=[s for s in slugs if s in cats
                           and cats[s]["id"] in post.get("categories", [])],
                source=site.source, identifiant=str(post.get("id") or ""),
            ))
        return sorties

    # ── marchés ──────────────────────────────────────────────────────────────
    def avis_marches(self) -> list[dict]:
        """Avis de publicité de l'intercommunalité, puis de la commune.

        Ce ne sont pas des marchés attribués : ni montant, ni titulaire, ni date
        de notification. Ils disent qu'une consultation a été ouverte — c'est la
        seule chose qu'on en publie.
        """
        avis = []
        for portee in ("epci", "commune"):
            site = self.sites[portee]
            slug = (self.pages.get(portee) or {}).get("marches")
            if not site or not slug:
                continue
            cat = site.categories().get(slug)
            if not cat:
                print(f"  [{site.source}] catégorie « {slug} » absente")
                continue
            for post in site.posts(categories=[cat["id"]]):
                objet = texte_brut(post["title"]["rendered"])
                if len(objet) < 6:
                    continue
                pdfs = liens_pdf(post.get("content", {}).get("rendered", ""))
                avis.append({
                    "source": site.source,
                    "portee": portee,
                    "objet": objet,
                    "date_pub": post.get("date", "")[:10],
                    "pdf_url": pdfs[0]["url"] if pdfs else post.get("link", ""),
                    "raw_id": post.get("link") or f"{site.source}-{post.get('id')}",
                })
        return avis

    # ── annuaires ────────────────────────────────────────────────────────────
    def pages_annuaire(self, portee: Portee = "commune") -> list[str]:
        site = self.sites[portee]
        slugs = (self.pages.get(portee) or {}).get("annuaires") or []
        textes = []
        for slug in slugs:
            page = site.page(slug) if site else None
            if not page:
                print(f"  [wp] page /{slug}/ absente")
                continue
            textes.append(texte_brut(page["content"]["rendered"]))
        return textes


def _domaine(url: str) -> str:
    return urllib.parse.urlparse(url or "").netloc.removeprefix("www.")


CONNECTEUR = ConnecteurWordPress
