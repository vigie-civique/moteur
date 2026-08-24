"""
wayback.py — les procès-verbaux que le site ne sert plus, et que l'archive garde.

Une refonte de site municipal efface les anciens comptes rendus. À Lasalle, les
séances de 2017 à 2019 ne sont plus sur `lasalle.fr` : elles n'existent que dans
les instantanés de la Wayback Machine. Ce n'est pas un cas particulier — c'est
ce qui arrive à toute commune qui change de CMS, et la mémoire des délibérations
est précisément ce qu'un dispositif de veille ne peut pas laisser disparaître.

Comment on retrouve un PV disparu
---------------------------------
Pas en devinant des adresses : en relisant la PAGE DE LISTE telle qu'elle était.

    1. l'API CDX donne les instantanés de la page des comptes rendus
       (`collapse=timestamp:6` : un par mois au plus, sinon des centaines de
       captures identiques) ;
    2. chaque instantané contient les liens PDF **tels qu'ils étaient ce
       jour-là**, réécrits par l'archive — l'adresse d'origine s'y lit encore ;
    3. l'adresse de rejeu (`…/<horodatage>id_/<adresse d'origine>`) rend les
       octets d'origine, sans l'habillage de l'archive. Elle redirige vers la
       capture la plus proche du PDF, ce que suit `urllib`.

Ce module ne fait que CATALOGUER : il rend des `DocumentPublie` que
`conseils.traiter` télécharge, lit et découpe comme n'importe quel autre PV.
Un PV retrouvé dans l'archive n'est pas une pièce de seconde zone : il passe par
les mêmes analyseurs, donne les mêmes délibérations, les mêmes présences.

Ce que la source vaut, et ce qu'elle ne vaut pas
-----------------------------------------------
**La commune reste l'éditeur.** `source` porte donc son domaine, pas celui de
l'archive : c'est elle qui a publié le procès-verbal, l'archive n'est que le
chemin par lequel on le récupère. C'est aussi ce qui permet à la pièce d'être
publiée comme les autres — une allowlist qui ne connaîtrait pas
« web.archive.org » écarterait des actes authentiques (cf. les marchés DECP,
collectés partout et publiés nulle part). L'origine archivistique est consignée
dans la métadonnée de la séance, et `source_url` pointe vers le rejeu, seule
adresse qui réponde encore.

**L'archive n'a que ce qu'elle a capturé.** Elle ne garantit rien : une page
jamais visitée par le robot n'a jamais existé pour elle. Ce collecteur comble,
il ne prouve pas l'exhaustivité.

Déclaration dans `config/instance.json` — rien à écrire dans le cas courant, la
page de liste est celle que le connecteur utilise déjà :

    "pages": {"commune": {"conseil": "/compte-rendus-des-conseils"}}

Et si les anciens PV étaient listés ailleurs que la page actuelle :

    "pages": {"commune": {"archives": ["/archives-conseils", "/vie-municipale"]}}
"""
from __future__ import annotations

import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import COMMUNE_URL, EPCI_URL, HEADERS, PAGES
from .connecteurs.base import DocumentPublie, date_fr

CDX = "https://web.archive.org/cdx/search/cdx"
# `id_` : les octets d'origine, sans la barre de navigation de l'archive. Sans
# ce suffixe on télécharge une page HTML habillée à la place du PDF.
REJEU = "https://web.archive.org/web/{ts}id_/{url}"

# Un lien de PV, reconnu à son nom de fichier. La date, elle, est exigée
# séparément : un « reglement-interieur.pdf » de la même page n'est pas une
# séance, et un PV sans date n'est de toute façon pas rattachable.
MOTIF_PV = r"(cm|conseil|compte.?rendu|s[ée]ance|pv|deliberation|délibération)"

# L'archive est un service gratuit tenu par une association : on l'interroge
# lentement, et on ne redemande jamais ce qu'on a déjà.
DELAI = 1.5
MAX_INSTANTANES = 60


def _get(url: str, timeout: int = 60, tentatives: int = 3) -> bytes:
    dernier = None
    for essai in range(tentatives):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:                      # noqa: BLE001 — journalisé
            dernier = e
            time.sleep(2 * (essai + 1))
    raise dernier


def instantanes(page: str, limite: int = MAX_INSTANTANES) -> list[str]:
    """Horodatages des captures d'une page, au plus une par mois.

    `collapse=timestamp:6` regroupe sur les six premiers chiffres — l'année et
    le mois. Une page de mairie capturée chaque semaine donnerait sinon des
    centaines d'instantanés pour le même contenu.
    """
    adresse = page.split("://", 1)[-1]
    url = (f"{CDX}?url={urllib.parse.quote(adresse)}&output=text"
           f"&fl=timestamp,statuscode&collapse=timestamp:6")
    try:
        texte = _get(url).decode("utf-8", "replace")
    except Exception as e:                          # noqa: BLE001
        print(f"  [wayback][erreur] index de {adresse} → {e}")
        return []
    horodatages = []
    for ligne in texte.splitlines():
        parts = ligne.split()
        # Une capture d'erreur (404, 301) ne contient pas la liste des PV.
        if len(parts) >= 2 and parts[0].isdigit() and parts[1] == "200":
            horodatages.append(parts[0])
    return horodatages[-limite:] if limite else horodatages


# Dans un instantané, chaque lien porte l'adresse d'origine après l'horodatage :
#   /web/20190722114724/https://www.lasalle.fr/…/cm%2026juin2019.pdf
_LIEN_ARCHIVE = re.compile(
    r'href="(?:https?://web\.archive\.org)?/web/(\d{14})[a-z_]*/'
    r'(https?://[^"]+?\.pdf)"', re.I)


def liens_pdf(html: str) -> dict[str, str]:
    """{adresse d'origine: horodatage} des PDF d'un instantané."""
    trouves: dict[str, str] = {}
    for ts, origine in _LIEN_ARCHIVE.findall(html or ""):
        trouves.setdefault(urllib.parse.unquote(origine), ts)
    return trouves


def documents(page: str, source: str, motif: str = MOTIF_PV,
              limite_instantanes: int = MAX_INSTANTANES) -> list[DocumentPublie]:
    """Les PV catalogués dans les instantanés d'une page de liste.

    Un seul document par date : la même séance revient dans tous les
    instantanés postérieurs à sa mise en ligne, et parfois sous deux noms
    (`CM 22 mai 2019.pdf` et `CM 22 mai 2019_0.pdf`, la seconde version d'un
    dépôt). Le premier trouvé fait foi, l'archive rendant les captures de la
    plus ancienne à la plus récente.
    """
    reconnu = re.compile(motif, re.I)
    par_date: dict[str, DocumentPublie] = {}
    captures = instantanes(page, limite_instantanes)
    print(f"  [wayback] {len(captures)} instantané(s) de {page}")

    for ts in captures:
        rejeu = f"https://web.archive.org/web/{ts}/{page}"
        try:
            html = _get(rejeu).decode("utf-8", "replace")
        except Exception as e:                      # noqa: BLE001
            print(f"  [wayback][erreur] instantané {ts} → {e}")
            continue
        for origine, ts_pdf in liens_pdf(html).items():
            nom = urllib.parse.unquote(origine.rsplit("/", 1)[-1])
            if not reconnu.search(nom):
                continue
            date = date_fr(nom)
            if not date or date in par_date:
                continue
            par_date[date] = DocumentPublie(
                date=date,
                url=REJEU.format(ts=ts_pdf, url=origine),
                libelle=nom,
                source=source,
                meta={"archive": "web.archive.org", "archive_horodatage": ts_pdf,
                      "url_origine": origine},
            )
        time.sleep(DELAI)

    return sorted(par_date.values(), key=lambda d: d.date, reverse=True)


# Une adresse de rejeu porte l'adresse d'origine après l'horodatage :
#   https://web.archive.org/web/20211229003601id_/https://www.lasalle.fr/…/cm.pdf
_REJEU = re.compile(r"^https?://web\.archive\.org/web/(\d{14})[a-z_]*/(https?://.+)$", re.I)


def document_archive(url: str, date: str) -> DocumentPublie | None:
    """Un `DocumentPublie` pour une adresse de rejeu, ou None si ce n'en est pas une.

    L'éditeur d'un procès-verbal reste la commune, même repris dans l'archive :
    sans cette lecture, une reprise à la main entrait sous la source
    « web.archive.org », que l'allowlist de publication ne connaît pas — la
    séance et ses délibérations restaient invisibles, collectées pour rien.
    """
    m = _REJEU.match(url or "")
    if not m:
        return None
    ts, origine = m.group(1), m.group(2)
    return DocumentPublie(
        date=date,
        url=url,
        libelle=urllib.parse.unquote(origine.rsplit("/", 1)[-1]),
        source=_domaine(origine),
        meta={"archive": "web.archive.org", "archive_horodatage": ts,
              "url_origine": origine},
    )


def _base(portee: str) -> str:
    return (COMMUNE_URL if portee == "commune" else EPCI_URL).rstrip("/")


def _domaine(url: str) -> str:
    return urllib.parse.urlparse(url or "").netloc.removeprefix("www.")


def catalogue_archive(portee: str = "commune") -> list[DocumentPublie]:
    """Les PV archivés des pages de liste déclarées par l'instance.

    Par défaut, la page des comptes rendus que le connecteur lit déjà : c'est
    elle que l'archive a capturée, et il n'y a aucune raison d'en déclarer une
    seconde tant que la commune n'a pas déménagé ses PV.
    """
    reglages = PAGES.get(portee) or {}
    base = _base(portee)
    if not base:
        return []
    chemins = reglages.get("archives") or [reglages.get("conseil")]
    motif = reglages.get("archives_motif") or MOTIF_PV

    sorties: dict[str, DocumentPublie] = {}
    for chemin in [c for c in chemins if c]:
        page = chemin if chemin.startswith("http") else base + "/" + chemin.lstrip("/")
        for doc in documents(page, _domaine(base), motif):
            sorties.setdefault(doc.date, doc)
    return sorted(sorties.values(), key=lambda d: d.date, reverse=True)
