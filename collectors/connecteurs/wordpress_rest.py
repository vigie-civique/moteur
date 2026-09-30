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
import re
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
        """Une page, par l'API si elle est ouverte, sinon par son adresse.

        Un plugin de sécurité peut fermer le seul endpoint `pages` en laissant
        `posts` ouvert : constaté sur une commune où 877 articles sont lisibles
        et où `/wp-json/wp/v2/pages` répond 401. Le repli lit la page à son
        adresse publique et rend la même structure, ce qui laisse le reste du
        connecteur indifférent au refus.
        """
        data, _ = self._get("pages", {"slug": slug, "status": "publish"})
        if data:
            return data[0]
        return self._page_html(slug)

    def _page_html(self, slug: str) -> dict | None:
        from ..archive import archive_fetch
        from ..config import HEADERS, REQUEST_DELAY

        url = f"{self.base}/{slug.strip('/')}/"
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                brut = r.read()
                archive_fetch(self.source, url, brut,
                              r.headers.get_content_type(), r.status)
                html = brut.decode(r.headers.get_content_charset("utf-8"),
                                   errors="replace")
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            print(f"  [wp][erreur] {url} → {e}")
            return None
        finally:
            time.sleep(REQUEST_DELAY)
        print(f"  [wp] page « {slug} » lue en HTML (API fermée)")
        return {"content": {"rendered": html}, "link": url,
                "title": {"rendered": slug}}

    def categories(self) -> dict[str, dict]:
        data, _ = self._get("categories", {"per_page": PER_PAGE})
        return {c["slug"]: c for c in (data or [])}

    def pdf_deposes(self):
        """Tous les PDF de la médiathèque, du plus récent au plus ancien."""
        return self._paginer("media", {"mime_type": "application/pdf",
                                       "orderby": "date", "order": "desc"})


# ── La médiathèque ───────────────────────────────────────────────────────────
#
# Une page « conseil » ne liste que ce que la collectivité a pensé à y lier. Sa
# médiathèque garde TOUT ce qui a été déposé. Relevé le 30/09/2026 sur le site
# de l'intercommunalité du premier portage : la page des procès-verbaux ne liait
# ni les recueils de février, du 3 juin et du 9 juillet 2026, ni les deux seules
# délibérations signées de la séance du 4 mars — dont celle qui porte la grille
# des tarifs de l'eau, absente du procès-verbal.
#
# Ce qui s'ajoute ainsi est un COMPLÉMENT : une pièce déjà cataloguée par la
# page n'est pas reprise, et la séance reste identifiée par sa date
# (`conseils.enregistrer_seance`), donc une pièce de plus ne fait pas une séance
# de plus.

# Ce qui rapporte une décision. Le nom de fichier est tout ce que la
# médiathèque sait d'une pièce : on le lit, faute de mieux, mais on ne lui fait
# dire que sa nature et sa date.
_PIECE_DE_CONSEIL = re.compile(
    r"d[ée]lib|proc[eè]s[\s-]*verbal|(?<![a-z])pv(?![a-z])"
    r"|compte[\s-]*rendu.{0,40}conseil", re.I)
# Ce qui l'annonce ou la résume sans la rapporter : la convocation et l'ordre du
# jour précèdent la séance, la « liste des délibérations » ne donne que des
# intitulés. Les lire comme des procès-verbaux fabriquait des délibérations.
# Un comité de pilotage ou une commission rend compte, mais ne délibère pas :
# le premier essai réel en ramenait six comptes rendus de COPIL.
_HORS_CATALOGUE = re.compile(
    r"convocation|ordre[\s-]*du[\s-]*jour|liste[\s-]*des[\s-]*d[ée]lib"
    r"|copil|comit[ée]|commission|r[ée]union[\s-]*publique", re.I)
# « Deliberation-N°41-du-4-mars-2026-… » : une pièce qui EST un acte, publiée
# seule. Elle passe par `conseils.traiter_acte`, qui ne découpe rien.
_ACTE_SEUL = re.compile(
    r"d[ée]lib(?:[ée]ration)?[\s.-]*n\s*[°o]?\s*(\d{1,4})\b", re.I)
# Jour, mois, année séparés par un point, un tiret ou une ESPACE : le libellé
# a perdu ses tirets (« PV 28 05 2014 »), et un nom de fichier colle parfois la
# date au mot qui précède (« PV du8.02.2023 »).
_DATE_NUMERIQUE = re.compile(r"(?<!\d)(\d{1,2})[ .-](\d{1,2})[ .-](\d{4}|\d{2})(?!\d)")


def _libelles(media: dict) -> tuple[str, str]:
    """Le titre donné dans la médiathèque, et le nom du fichier déposé.

    Les deux se lisent : le titre est souvent réécrit à la main (« PV tampon »)
    et perd la date que le nom de fichier portait encore.
    """
    def propre(t: str) -> str:
        return re.sub(r"[_-]+", " ", t).strip()
    titre = texte_brut((media.get("title") or {}).get("rendered", ""))
    nom = urllib.parse.unquote(urllib.parse.urlparse(
        media.get("source_url", "")).path.rsplit("/", 1)[-1]).rsplit(".", 1)[0]
    return propre(titre or nom), propre(nom)


def _date_de_piece(libelle: str, depose_le: str) -> str | None:
    """La date de la séance lue dans le libellé.

    `date_fr` refuse une année à deux chiffres, et il a raison en général. Ici,
    le dépôt donne un témoin : « 09.07.26 » déposé en juillet 2026 ne peut être
    que 2026. L'année courte n'est acceptée que si elle est celle du dépôt, ou
    la précédente (une séance de décembre publiée en janvier) — sinon la pièce
    reste non datée, et elle est annoncée comme telle.
    """
    if date := date_fr(libelle):
        return date
    for m in _DATE_NUMERIQUE.finditer(libelle):
        jour, mois, an = int(m.group(1)), int(m.group(2)), m.group(3)
        if not (1 <= jour <= 31 and 1 <= mois <= 12):
            continue
        if len(an) == 2:
            if not depose_le[:4].isdigit():
                continue
            annee = 2000 + int(an)
            if annee not in (int(depose_le[:4]), int(depose_le[:4]) - 1):
                continue
        else:
            annee = int(an)
        return f"{annee}-{mois:02d}-{jour:02d}"
    return None


def catalogue_mediatheque(base: str, deja: set[str]) -> list[DocumentPublie]:
    """Les pièces de conseil déposées sur un site WordPress, hors celles de `deja`.

    Déclaré par portée dans `config/instance.json`, indépendamment du connecteur
    qui lit les pages — un site WordPress peut être lu en HTML (`drupal_html`)
    et exposer quand même sa médiathèque :

        "pages": {"epci": {"conseil": "/pv/", "mediatheque": true}}
    """
    site = Site(base, _domaine(base))
    if not site:
        return []
    vus = {urllib.parse.unquote(u) for u in deja}
    documents, non_dates = [], []
    for media in site.pdf_deposes():
        url = media.get("source_url") or ""
        libelle, nom = _libelles(media)
        lu = f"{libelle} {nom}"
        if (not url or urllib.parse.unquote(url) in vus
                or not _PIECE_DE_CONSEIL.search(lu)
                or _HORS_CATALOGUE.search(lu)):
            continue
        vus.add(urllib.parse.unquote(url))
        depose = media.get("date") or ""
        date = _date_de_piece(libelle, depose) or _date_de_piece(nom, depose)
        if not date:
            non_dates.append(libelle)
            continue
        acte = None
        if m := _ACTE_SEUL.search(lu):
            acte = {"numero": m.group(1), "objet": libelle,
                    "type": "Délibération", "date_teletransmission": ""}
        documents.append(DocumentPublie(
            date=date, url=url, libelle=libelle, source=site.source,
            meta={"depuis_mediatheque": True,
                  "depose_le": (media.get("date") or "")[:10]},
            acte=acte))
    if non_dates:
        print(f"  [wp] médiathèque : {len(non_dates)} pièce(s) sans date lisible, "
              f"non reprises — {'; '.join(non_dates[:3])}")
    return documents


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
