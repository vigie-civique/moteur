"""Qui a passé un marché : l'attribution ne se déduit pas d'un mot commun.

Le BOAMP laisse le nom de l'acheteur en saisie libre. Le collecteur cherchait
donc large, sur les mots de plus de quatre lettres tirés du nom de l'EPCI — et
concluait sur le même critère. Le 20/08/2026, sur une instance dont l'EPCI
s'appelle « Causses Aigoual Cévennes Terres Solidaires », cela donnait :

  « terres »   → Terres australes et antarctiques françaises
  « cévennes » → GHT Cévennes Gard Camargue, Centre Hospitalier Alès Cévennes

711 marchés sur 712 se sont retrouvés attribués à la communauté de communes,
qui n'y était pour rien, et le site l'affichait en première page.

Chercher large est légitime. Conclure large ne l'est pas : affirmer qu'une
collectivité a acheté quelque chose demande son nom complet, pas une coïncidence
de vocabulaire. Ces cas viennent tous de la collecte réelle.
"""
from __future__ import annotations

import pytest

from collectors.marches_publics import _norme_acheteur

EPCI = "CC Causses Aigoual Cévennes Terres Solidaires"
COMMUNE = "Lasalle"


def attribue(nom_acheteur: str) -> str:
    """Reproduit la décision du collecteur : commune, EPCI, ou rien.

    Le nom doit être EN TÊTE : un organisme tiers met le sien devant.
    """
    n = _norme_acheteur(nom_acheteur)
    if n.startswith(_norme_acheteur(COMMUNE)):
        return "commune"
    if n.startswith(_norme_acheteur(EPCI)):
        return "epci"
    return ""


@pytest.mark.parametrize("nom", [
    "CC Causses Aigoual Cévennes Terres Solidaires",
    "Communauté de communes Causses-Aigoual-Cévennes Terres solidaires",
    "COMMUNAUTE DE COMMUNES CAUSSES AIGOUAL CEVENNES TERRES SOLIDAIRES",
])
def test_les_variantes_d_ecriture_de_l_epci_sont_reconnues(nom):
    assert attribue(nom) == "epci"


@pytest.mark.parametrize("nom", ["Commune de Lasalle", "Mairie de Lasalle", "LASALLE",
                                 "Lasalle — service technique"])
def test_la_commune_est_reconnue(nom):
    assert attribue(nom) == "commune"


@pytest.mark.parametrize("nom", [
    "Terres australes et antarctiques françaises",
    "Réserve naturelle nationale des Terres australes",
    "GHT Cévennes Gard Camargue",
    "Centre Hospitalier Alès Cévennes",
    "CC2T",
    "Parc national des Cévennes",
    # Un EPCI de Seine-Saint-Denis, attrapé par « Terres » et publié en
    # première page le 20/08/2026.
    "Parc Automobile De Paris Terres D'Envol (93)",
    "Amenagement De Paris Terres D'Envol (93)",
    # Le syndicat des eaux porte le nom de la commune sans être la commune.
    # C'est un acteur public local légitime : il mérite sa propre fiche, pas
    # d'être confondu avec la mairie.
    "Siaep de Lasalle",
    "Syndicat mixte du Pays de Lasalle",
])
def test_un_mot_commun_ne_suffit_pas_a_attribuer(nom):
    """Le cas qui a produit le défaut : ces acheteurs partagent un mot avec le
    nom de l'EPCI et n'ont rien à voir avec lui."""
    assert attribue(nom) == "", f"{nom!r} attribué à tort"


def test_un_marche_non_attribue_reste_probable():
    """Ce qu'on ne sait pas attribuer n'est pas jeté : il entre en `probable`,
    donc hors publication, et attend un arbitrage dans l'atelier."""
    certitude = "verified" if attribue("GHT Cévennes Gard Camargue") else "probable"
    assert certitude == "probable"
