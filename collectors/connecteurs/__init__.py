"""
Connecteurs de sites officiels — la partie irréductible du dispositif.

Les collecteurs nationaux (SIRENE, RNA, BODACC, DVF, OFGL, RNE, Sitadel, DECP,
Géorisques, INSEE, fiscalité, élections, BANATIC) interrogent des référentiels
indexés par code INSEE ou SIREN : ils fonctionnent pour n'importe quelle commune
française sans une ligne à écrire. Les sites de mairie, eux, n'ont aucun format
commun — et c'est là, et seulement là, que le portage d'une commune à l'autre
demande du travail.

Un connecteur répond à trois questions, et à rien d'autre :

    catalogue_pv(portee)      quels procès-verbaux sont publiés, à quelle date,
                              à quelle adresse ?
    articles(portee, depuis)  quels articles de vie locale, publiés quand ?
    avis_marches()            quels avis de publicité ?

L'interface s'arrête là parce que c'est tout ce dont le reste du moteur a
besoin. Elle a été dessinée après deux portages réels, pas avant : la tentation
d'un « adaptateur universel » couvrant tous les CMS de France serait un dessin
sur un échantillon de deux. Tant qu'une troisième commune n'a pas été rejouée,
cette interface reste volontairement mince.

Le connecteur d'une instance se déclare dans `config/instance.json` :

    "connecteur": "wordpress_rest",
    "pages": {"commune": {"conseil": "conseil-municipal"}, …}

Et, quand l'intercommunalité publie ailleurs et autrement — un portail d'actes
là où la mairie tient un WordPress —, un second connecteur pour cette portée :

    "connecteur_epci": "dematdoc",
    "pages": {"epci": {"portail": "https://exemple.dematdoc.eu/public/14"}}

Écrire un connecteur pour un site qui n'entre dans aucun des cas existants,
c'est hériter de `Connecteur` et implémenter ces trois méthodes. La première
question à se poser n'est pas « quel CMS ? » mais « ce site expose-t-il un point
d'accès en lecture ? » : une API déclarée bat toujours une structure devinée
(cf. docs/portage-brassac.md).
"""
from __future__ import annotations

import importlib

from .base import Connecteur, Article, DocumentPublie

__all__ = ["Connecteur", "Article", "DocumentPublie", "charger"]

_cache: dict[str, Connecteur] = {}


def charger(nom: str | None = None, portee: str = "commune") -> Connecteur:
    """Le connecteur déclaré par l'instance pour cette portée, instancié une fois.

    L'EPCI retombe sur le connecteur de la commune tant que
    `connecteur_epci` n'est pas déclaré : c'est le cas le plus fréquent, une
    intercommunalité tenant souvent le même genre de site que ses communes.
    """
    from ..config import CONNECTEUR, CONNECTEUR_EPCI

    if nom is None and portee == "epci" and CONNECTEUR_EPCI:
        nom = CONNECTEUR_EPCI
    nom = nom or CONNECTEUR
    if nom not in _cache:
        try:
            module = importlib.import_module(f".{nom}", __package__)
        except ModuleNotFoundError as e:
            disponibles = ", ".join(_disponibles())
            raise SystemExit(
                f"Connecteur « {nom} » introuvable ({e}).\n"
                f"Disponibles : {disponibles}\n"
                "Il se déclare dans config/instance.json, clé « connecteur »."
            ) from e
        _cache[nom] = module.CONNECTEUR()
    return _cache[nom]


def _disponibles() -> list[str]:
    from pathlib import Path
    return sorted(f.stem for f in Path(__file__).parent.glob("*.py")
                  if f.stem not in ("__init__", "base"))
