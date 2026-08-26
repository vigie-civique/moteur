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

from collectors.marches_publics import attribution_acheteur

EPCI = "CC Causses Aigoual Cévennes Terres Solidaires"
COMMUNE = "Lasalle"
# Deux communes membres du même périmètre, pour la règle d'ambiguïté.
HOMONYMES = ("Saint-André-de-Valborgne", "Saint-André-de-Majencoules",
             "Val-d'Aigoual", "Lasalle")


def attribue(nom_acheteur: str) -> str:
    """La décision du collecteur — la VRAIE, pas une copie.

    Ce fichier en tenait une reproduction, et vérifiait donc sa propre copie :
    la règle a changé le 26/08/2026 sans que rien ici ne bronche.
    """
    return attribution_acheteur(nom_acheteur, commune=COMMUNE, epci=EPCI,
                                homonymes=HOMONYMES)


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


# ── La source TRONQUE le nom officiel — 26/08/2026 ───────────────────────────
#
# Le cas symétrique du précédent, et il manquait. L'intercommunalité s'appelle
# « CC Causses Aigoual Cévennes Terres Solidaires » ; le BOAMP l'écrit sans son
# qualificatif final. Le nom déclaré est un préfixe du nom OFFICIEL — l'inverse
# de ce qui était testé. Résultat mesuré sur la base de production : 45 marchés
# BOAMP sans acheteur, dont la construction d'une crèche dans la commune, et
# 7 marchés publiés sur 53. Les deux instances voisines en publiaient 58 et 45.

def test_le_nom_tronque_par_la_source_designe_l_epci():
    assert attribue("CC Causses Aigoual Cévennes") == "epci"
    assert attribue("Communauté de communes Causses Aigoual Cévennes") == "epci"


def test_com_communes_est_une_communaute_de_communes():
    """Trois lettres qui coûtaient dix-huit marchés.

    « com » n'était pas dans les mots de structure : il restait collé en tête
    de la forme normalisée, et aucun rapprochement n'était possible.
    """
    assert attribue("COM COMMUNES CAUSSES AIGOUAL CEVENNES") == "epci"


def test_un_fragment_trop_court_ne_designe_personne():
    """« CC » se normalise en chaîne vide, « Saint » est le préfixe d'un département."""
    assert attribue("CC") == ""
    assert attribue("Causses") == ""


def test_une_troncature_ambigue_est_refusee():
    """Deux communes membres commencent pareil : le fragment ne tranche pas.

    « Saint-André-de-Valborgne » et « Saint-André-de-Majencoules » sont dans le
    même périmètre. Accepter « Saint-André » attribuerait à l'une ce que l'autre
    a acheté — et le nom seul ne permet pas de savoir laquelle.
    """
    assert attribue("Saint-André") == ""


def test_une_troncature_reste_refusee_a_un_tiers():
    """La règle n'ouvre rien à ce que le préfixe étranger interdisait."""
    assert attribue("Siaep de Lasalle") == ""
    assert attribue("Régie eau et assainissement Causses Aigoual Cévennes") == ""
    assert attribue("Terres australes et antarctiques françaises") == ""


def test_le_suffixe_reste_accepte():
    """L'acquis d'avant : « CC Machin — service eau » est bien la CC."""
    assert attribue("CC Causses Aigoual Cévennes Terres Solidaires — service eau") == "epci"
