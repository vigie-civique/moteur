"""Rattacher un acheteur BOAMP au territoire — sans SIREN, la source n'en donne pas.

Le BOAMP ne publie aucune immatriculation française : son schéma historique
donne un bloc `IDENTITE` (dénomination, CP, ville), son schéma eForms des
organisations dont le `cbc:CompanyID` porte un identifiant européen opaque.
Vérifié sur les deux le 23/08/2026. Le recoupement par SIREN vit donc dans les
trois chemins DECP, qui interrogent par SIREN d'acheteur ; ici, c'est l'ADRESSE
DÉCLARÉE qui rattache — ou non.

Ce qu'on répare : la recherche par jetons ramenait la France entière dès que le
nom de l'EPCI contenait un mot commun. « coeur » : 3 668 avis. Saillans avait
400 marchés `probable` hors sujet en base — Cœur Essonne, Cœur de Flandre,
Cœur du Var. Ils n'atteignaient pas le site, mais ils encombraient la file de
revue, qui est le goulot du dispositif.
"""
from __future__ import annotations

import json

import pytest

from collectors import marches_publics as mp


def avis_eforms(nom: str, cp: str, ville: str) -> dict:
    """Un avis au schéma eForms, réduit à ce que le rattachement lit."""
    return {"nomacheteur": nom, "donnees": json.dumps({"EFORMS": {"ContractAwardNotice": {
        "organisations": [{
            "cac:PartyName": {"cbc:Name": {"@languageID": "FRA", "#text": nom}},
            "cac:PostalAddress": {"cbc:PostalZone": cp,
                                  "cbc:CityName": {"#text": ville}},
        }]}}})}


def avis_historique(nom: str, cp: str, ville: str) -> dict:
    return {"nomacheteur": nom,
            "donnees": json.dumps({"IDENTITE": {"DENOMINATION": nom,
                                                "CP": cp, "VILLE": ville}})}


@pytest.mark.parametrize("fabrique", [avis_eforms, avis_historique])
def test_les_deux_schemas_livrent_la_meme_adresse(fabrique):
    """Un seul lecteur pour les deux schémas : celui qui n'est pas là ne produit
    rien, et le collecteur n'a pas à savoir lequel il tient."""
    assert mp.localite_acheteur(fabrique("Un acheteur", "26340", "Saillans")) \
        == ("26340", "Saillans")


def test_un_avis_sans_adresse_ne_dit_rien():
    """None, et non « hors territoire » : une source muette n'accuse pas."""
    assert mp.localite_acheteur({"nomacheteur": "X", "donnees": "{}"}) is None
    assert mp.acheteur_du_territoire(None) is None


def test_un_json_casse_ne_fait_pas_tomber_la_collecte():
    assert mp.localite_acheteur({"nomacheteur": "X", "donnees": "{pas du json"}) is None


def test_l_adresse_de_l_acheteur_est_preferee_a_celle_du_titulaire():
    """Un avis décrit plusieurs organisations — acheteur, titulaires, tribunal
    compétent. Prendre la première venue attribuerait au territoire un marché
    parisien gagné par une entreprise locale."""
    avis = {"nomacheteur": "CC du Crestois", "donnees": json.dumps({"orgs": [
        {"cac:PartyName": {"cbc:Name": "ETOILE METAL"},
         "cac:PostalAddress": {"cbc:PostalZone": "59000", "cbc:CityName": "Lille"}},
        {"cac:PartyName": {"cbc:Name": "CC du Crestois"},
         "cac:PostalAddress": {"cbc:PostalZone": "26400", "cbc:CityName": "Aouste sur Sye"}},
    ]})}
    assert mp.localite_acheteur(avis) == ("26400", "Aouste sur Sye")


# ── Le verdict : dedans, dehors, ou rien ─────────────────────────────────────
# Trois réponses et non deux. Une adresse absente n'est pas une adresse
# étrangère : le doute laisse la décision au nom de l'acheteur, l'autre indice.

def test_un_code_postal_du_perimetre_rattache():
    assert mp.acheteur_du_territoire(("99000", "Testonville")) is True


def test_une_commune_du_perimetre_rattache_meme_sans_code_postal():
    """Le CP d'un avis est parfois celui d'une boîte postale ou d'un service
    acheteur mutualisé. Le nom de la ville rattrape ce cas."""
    assert mp.acheteur_du_territoire(("", "Voisinbourg")) is True


def test_une_commune_du_perimetre_est_reconnue_malgre_accents_et_tirets():
    assert mp.acheteur_du_territoire(("", "LES ESSARTS D EPREUVE")) is True


def test_un_acheteur_domicilie_ailleurs_est_ecarte():
    """« Cœur de Flandre » à Hazebrouck (59190) : le nom contient le jeton de
    l'EPCI, l'adresse dit tout."""
    assert mp.acheteur_du_territoire(("59190", "HAZEBROUCK")) is False


def test_le_departement_de_l_avis_ne_vaut_pas_domicile():
    """Le SYDEO remonte d'une recherche bornée au 26 et siège au Pouzin (07) :
    `code_departement` est celui de l'avis, pas celui de l'acheteur."""
    assert mp.acheteur_du_territoire(("07250", "Le pouzin")) is False
