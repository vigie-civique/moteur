"""
Interface d'un connecteur de site officiel, et outils communs de lecture.

Les types échangés sont volontairement pauvres : un document publié, un article.
Ce que le connecteur renvoie doit pouvoir être produit par n'importe quel site,
y compris une page HTML plate relue à la main — pas seulement par une API.
"""
from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field
from typing import Iterable, Literal

Portee = Literal["commune", "epci"]


@dataclass
class DocumentPublie:
    """Une pièce déposée sur le site : procès-verbal, avis, rapport.

    `date` est celle du document, pas celle de sa mise en ligne — elle provient
    du libellé du lien quand il en porte une, jamais du nom de fichier tant
    qu'un libellé existe : sur le site de la commune portée, le même mois
    s'écrit `PV_05_JUIN_2026.pdf`, `C-R_JUIN_2025.pdf` ou
    `pv_seance_11juillet_23.pdf` selon l'année, tandis que le libellé, lui, est
    régulier depuis 2004.
    """
    date: str
    url: str
    libelle: str = ""
    source: str = ""


@dataclass
class Article:
    """Un article de vie locale.

    `date_publication` est un fait ; `date` est une inférence, et le connecteur
    doit dire laquelle des deux il a retenue via `date_source`. Un agenda qui
    affiche une date de publication comme une date d'événement ment sur son
    contenu.
    """
    titre: str
    url: str
    date: str
    date_publication: str
    date_source: Literal["texte", "publication"] = "publication"
    contenu: str = ""
    rubriques: list[str] = field(default_factory=list)
    source: str = ""
    identifiant: str | None = None


class Connecteur:
    """À implémenter pour un site qui n'entre dans aucun cas existant."""

    nom = "abstrait"

    def catalogue_pv(self, portee: Portee = "commune") -> list[DocumentPublie]:
        """Procès-verbaux publiés, du plus récent au plus ancien."""
        raise NotImplementedError

    def articles(self, portee: Portee = "commune",
                 depuis: str | None = None) -> Iterable[Article]:
        """Articles de vie locale."""
        raise NotImplementedError

    def avis_marches(self) -> list[dict]:
        """Avis de publicité publiés par la collectivité."""
        return []

    def pages_annuaire(self, portee: Portee = "commune") -> list[str]:
        """Contenus texte des pages d'annuaire (associations, commerces).

        Optionnel : tous les sites n'en publient pas.
        """
        return []


# ── Outils de lecture, communs à tous les connecteurs ────────────────────────

_BALISE = re.compile(r"<[^>]+>")
_ESPACES = re.compile(r"[ \t ]+")


def texte_brut(rendu: str) -> str:
    """HTML → texte lisible, sauts de ligne conservés aux blocs."""
    if not rendu:
        return ""
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", rendu)
    t = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h[1-6])>", "\n", t)
    t = _BALISE.sub("", t)
    t = _html.unescape(t)
    t = _ESPACES.sub(" ", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


_LIEN_PDF = re.compile(r'<a[^>]+href="([^"]+\.(?:pdf|PDF))"[^>]*>(.*?)</a>', re.S)


def liens_pdf(rendu: str) -> list[dict]:
    """Liens PDF d'un contenu, avec leur libellé d'ancrage."""
    sorties = []
    for url, interne in _LIEN_PDF.findall(rendu or ""):
        libelle = _ESPACES.sub(" ", _html.unescape(_BALISE.sub("", interne)).strip())
        sorties.append({"url": _html.unescape(url), "libelle": libelle})
    return sorties


MOIS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
    "janv": 1, "févr": 2, "fevr": 2, "avr": 4, "juil": 7, "sept": 9,
    "oct": 10, "nov": 11, "déc": 12, "dec": 12,
}
_DATE_FR = re.compile(
    r"(\d{1,2})\s*(?:er)?\s+([a-zàâçéèêëîïôûùüÿ]+)\.?\s+(\d{4})", re.I)
_DATE_NUM = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})\b")


def date_fr(texte: str) -> str | None:
    """Première date française d'un texte → ISO, ou None.

    Tolère « Lundi 1 juin 2026 », « 1er septembre 2020 », « 05/06/2026 ». Une
    année à deux chiffres est refusée plutôt qu'interprétée : un nom de fichier
    comme `CR-0804.pdf` a déjà coûté assez cher à deviner.
    """
    if not texte:
        return None
    m = _DATE_FR.search(texte)
    if m:
        mois = MOIS.get(m.group(2).lower())
        if mois:
            return f"{m.group(3)}-{mois:02d}-{int(m.group(1)):02d}"
    m = _DATE_NUM.search(texte)
    if m and len(m.group(3)) == 4:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return None
