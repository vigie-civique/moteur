"""Le registre des étapes : qui produit quoi, à partir de quoi, dans quel ordre.

`build_snapshot()` faisait 1 770 lignes d'une traite. Ce qu'une partie lisait
d'une autre passait par des variables locales : pour savoir d'où venait
`public_ids`, ou si une ligne pouvait remonter de vingt lignes sans rien
changer, il fallait tout relire.

Chaque étape est désormais une fonction qui reçoit par leur nom les faits dont
elle a besoin et rend ceux qu'elle produit. L'étape déclare les trois :

- `lit`      — les faits qu'elle consulte ;
- `complete` — ceux qu'elle MODIFIE en place. Ils sont rares, et c'est
  justement pour cela qu'ils sont nommés : une étape qui enrichit les fiches
  après qu'une autre les a copiées ne produit pas la même sortie que si elle
  passait avant (cf. `couches` et `citations`) ;
- `produit`  — les faits nouveaux qu'elle rend ;
- `ecrit`    — les fichiers du snapshot qu'elle écrit, en chemins relatifs au
  répertoire de sortie (`*` pour une famille : `entite/*.json`).

Rien n'est deviné : l'exécuteur appelle la fonction avec exactement `lit` et
`complete`, et refuse une étape qui rend autre chose que `produit`. Une
déclaration fausse casse la construction au lieu de mentir.

L'ordre est celui de la liste, et il n'y en a pas d'autre. C'est un registre,
pas un ordonnanceur : il ne réordonne rien et ne saute rien.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Etape:
    nom: str
    fonction: Callable[..., dict | None]
    lit: tuple[str, ...] = ()
    complete: tuple[str, ...] = ()
    produit: tuple[str, ...] = ()
    ecrit: tuple[str, ...] = ()


class RegistreIncoherent(RuntimeError):
    """Une étape lit ce que personne n'a produit, ou rend ce qu'elle ne déclare pas."""


def incoherences(etapes: list[Etape], fournis: set[str]) -> list[str]:
    """Ce qui ne tient pas dans le registre, sans rien exécuter.

    `fournis` : les faits donnés au départ (la connexion, le répertoire de
    sortie, l'horloge…). Une étape ne peut lire qu'un fait fourni ou produit
    par une étape PRÉCÉDENTE ; un fait n'est produit qu'une fois ; un fichier
    n'est écrit que par une étape — la dernière écriture d'un fichier écrit
    deux fois est la seule qui compte, et deux étapes ne le revendiquent pas.
    """
    problemes: list[str] = []
    connus = set(fournis)
    noms: set[str] = set()
    fichiers: dict[str, str] = {}
    for e in etapes:
        if e.nom in noms:
            problemes.append(f"{e.nom} : deux étapes portent ce nom")
        noms.add(e.nom)
        for fait in (*e.lit, *e.complete):
            if fait not in connus:
                problemes.append(f"{e.nom} : lit « {fait} », que rien ne produit avant elle")
        for fait in e.produit:
            if fait in connus:
                problemes.append(f"{e.nom} : produit « {fait} », déjà produit avant elle")
            connus.add(fait)
        for f in e.ecrit:
            if f in fichiers:
                problemes.append(f"{e.nom} : écrit {f}, que {fichiers[f]} écrit déjà")
            fichiers[f] = e.nom
    return problemes


def executer(etapes: list[Etape], faits: dict) -> dict:
    """Exécute les étapes dans l'ordre de la liste ; rend les faits enrichis."""
    for e in etapes:
        manquants = [f for f in (*e.lit, *e.complete) if f not in faits]
        if manquants:
            raise RegistreIncoherent(f"{e.nom} : faits absents {manquants}")
        rendu = e.fonction(**{f: faits[f] for f in (*e.lit, *e.complete)}) or {}
        if set(rendu) != set(e.produit):
            raise RegistreIncoherent(
                f"{e.nom} : rend {sorted(rendu)}, déclare {sorted(e.produit)}")
        faits.update(rendu)
    return faits
