#!/usr/bin/env python3
"""origine.py — d'où vient une ligne, et donc ce qu'on a le droit d'en faire.

Décidé le 20/08/2026, en ouvrant la saisie manuelle de l'atelier : « ne pas
corrompre tout ce qui est établi comme venant de collecteurs institutionnels ;
cela ne concerne que ce qui a été extrait de verbatims ou la collecte de sites ».

La frontière n'est PAS « administration ou pas » — le BOAMP et un procès-verbal
de conseil municipal sont tous deux publics, tous deux officiels. Elle est dans
QUI a structuré la donnée :

  institutionnel  la ligne reproduit une donnée déjà structurée par une
                  administration (API, CSV, JSON). Personne ici ne l'a
                  interprétée : le montant est celui que la source publie.
                  → ni saisie ni rectification à la main. On peut l'ÉCARTER de
                    la publication — c'est un jugement éditorial défendable —
                    jamais prétendre connaître un meilleur chiffre qu'elle.

  verbatim        la ligne est le produit d'une LECTURE : un PDF, une page HTML,
                  un scan passé à l'OCR, découpés par nos parsers. Le chiffre
                  est notre lecture d'une phrase, faillible par construction.
                  → rectifiable et complétable dans l'atelier.

  atelier         la ligne a été écrite à la main par un humain, source à
                  l'appui. → modifiable, exportable, signalée comme telle.

Cette colonne n'est pas cosmétique : c'est elle que l'API interroge avant
d'autoriser une écriture. Sans elle la règle n'existerait que dans la tête de
celui qui saisit — et les tables MÉLANGENT déjà les deux origines. Mesuré le
20/08 sur `financial_flows` de l'instance 30140 : 36 lignes OFGL et 2 lignes
DECP (institutionnelles) contre 150 lignes lues dans des comptes rendus, que
seul un libellé en texte libre distinguait.
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse

from collectors.config import (COMMUNE_URL, EPCI_URL, PORTAILS,
                               PREFECTURE_URL)

INSTITUTIONNEL = "institutionnel"
VERBATIM       = "verbatim"
ATELIER        = "atelier"

ORIGINES = (INSTITUTIONNEL, VERBATIM, ATELIER)

#: Tables portant la colonne `origine`. Ce sont celles où une ligne représente
#: un fait daté et chiffré — donc celles qu'un humain pourrait vouloir corriger
#: ou compléter. Les tables de référentiel (entities, businesses…) n'en ont pas :
#: leur origine se lit dans `confidence` et `validation_status`.
TABLES_ORIGINE = (
    "events",
    "financial_flows",
    "marches_publics",
    "budget_vote",
    "dotations_etat",
    "approbations_projets",
)

# ─── Registre ─────────────────────────────────────────────────────────────────
# Motifs cherchés dans `source`, ancrés en début de chaîne sauf mention. Ancrés
# volontairement : le 19/08, une attribution de marchés sur un mot commun cherché
# n'importe où dans le texte a rattaché 711 marchés sur 712 à la mauvaise entité.
# Un motif qui mord au milieu d'un libellé est un défaut, pas une souplesse.

_MOTIFS_INSTITUTIONNELS = (
    r"sirene",              # répertoire des entreprises
    r"rna\b",               # répertoire national des associations
    r"bodacc",              # annonces civiles et commerciales
    r"dvf",                 # demandes de valeurs foncières
    r"ofgl",                # observatoire des finances locales
    r"dgfip",
    r"dgcl",
    r"banatic",             # périmètres intercommunaux
    r"sitadel",             # permis de construire
    r"georisques",
    r"gaspar",
    r"insee",
    r"melodi",              # API statistique de l'INSEE
    r"decp\b",              # données essentielles de la commande publique
    r"boamp",               # avis de marchés
    r"interieur",           # résultats électoraux
    r"rne\b",               # répertoire national des élus
    r"pappers",             # agrégateur de sources légales
    r"hubeau",              # qualité de l'eau
    r"data\.gouv",
    r"data\.economie",
    r"api\.",
    r"subventions?[ _-]?etat",
    r"occitanie",           # open data régional
    r"elections?\b",
    r"qualite[ _-]?eau",
    r"fiscalite",
)

_MOTIFS_VERBATIM = (
    r"cm\b",                        # « CM 28/05/2026 », « CM vote subventions »
    r"cr\b",                        # « CR CM 2024 », « CR 2023-09-13 » — compte
                                    # rendu ; aucune source institutionnelle
                                    # connue ne commence par ces deux lettres
    r"pv\b",
    r"conseil[ _-]municipal",
    r"raa\b",                       # recueil des actes — un PDF qu'on découpe
    r"prefecture-\d+",              # RAA départemental, suffixé par le code
    r"urbanisme:",                  # relevés d'urbanisme tirés d'une séance
    r"web[ _-]?scraper",
    r"agenda",
    r"(?:web\.)?archive\.org",      # instantanés Wayback des PV disparus
)

_MOTIFS_ATELIER = (
    r"atelier",
)


def _norm(s: str) -> str:
    """Minuscules sans accents. La source est du texte libre écrit par des
    collecteurs différents à des années d'intervalle : « Préfecture » et
    « prefecture » désignent la même chose."""
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.lower().split())


def _hote(url: str) -> str:
    """Domaine nu d'une URL de configuration, sans `www.`. Les collecteurs de
    site écrivent tantôt le domaine seul en source (« lasalle.fr »), tantôt
    l'URL entière de la page."""
    hote = (urlparse(url or "").hostname or "").lower()
    return hote[4:] if hote.startswith("www.") else hote


def _domaines_locaux() -> tuple[str, ...]:
    """Les sites que NOUS lisons pour cette instance. Ils viennent de la
    configuration, jamais du code : c'est ce qui rend la règle transposable —
    à Saillans ou à Brassac ce sont d'autres domaines, et rien à modifier."""
    return tuple(d for d in (_hote(COMMUNE_URL), _hote(EPCI_URL),
                             _hote(PREFECTURE_URL),
                             *(_hote(u) for u in PORTAILS)) if d)


def origine_de(source: str | None) -> str | None:
    """Renvoie l'origine d'une ligne d'après sa source, ou None.

    None n'est PAS un repli : c'est un refus de deviner. Ranger au hasard
    reviendrait soit à protéger comme institutionnel une ligne que personne
    n'a vérifiée, soit à ouvrir à la réécriture un chiffre publié par une
    administration. `scripts/classer_origine.py` liste ce qui n'est pas reconnu
    et laisse la colonne vide, plutôt que de trancher à la place d'un humain.
    """
    s = _norm(source)
    if not s:
        return None

    for motif in _MOTIFS_ATELIER:
        if re.match(motif, s):
            return ATELIER

    # Les domaines de l'instance passent AVANT les motifs génériques : le site
    # d'une commune peut s'appeler « mairie-elections.fr » sans que ses pages
    # deviennent pour autant des résultats électoraux du ministère.
    for domaine in _domaines_locaux():
        if domaine and domaine in s:
            return VERBATIM

    for motif in _MOTIFS_VERBATIM:
        if re.match(motif, s):
            return VERBATIM

    for motif in _MOTIFS_INSTITUTIONNELS:
        if re.match(motif, s):
            return INSTITUTIONNEL

    return None


def modifiable(origine: str | None) -> bool:
    """Une valeur de cette ligne peut-elle être rectifiée ou complétée ?

    Écarter une ligne de la publication reste possible quelle que soit son
    origine : refuser de publier un chiffre qu'on juge faux n'exige pas d'en
    connaître un meilleur. Cette fonction ne gouverne que la RÉÉCRITURE.

    Une ligne non classée (origine NULL) est traitée comme institutionnelle :
    devant l'inconnu, ne rien casser.
    """
    return origine in (VERBATIM, ATELIER)
