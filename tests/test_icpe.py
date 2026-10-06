"""Les installations classées : une société est nommée et située, un particulier non.

Le registre des ICPE donne l'exploitant, son adresse et ses coordonnées. Pour un
éleveur en nom propre, c'est le nom d'un particulier et son domicile : ils
sortaient tels quels dans `environnement.json`.
"""
from __future__ import annotations

import json

import pytest

from scripts.snapshot.territoire import exploitant_designe, export_icpe


@pytest.mark.parametrize("nom", [
    "SARL CARRIERES DU BOUSQUET", "GAEC DE SAINT PIERRE", "EARL GILLOUIN",
    "BRASSAC  Industrie SAS", "SA GOUT", "CC DES ÉPREUVES RÉUNIES",
    "Société des Eaux de Testonville",
])
def test_une_forme_juridique_designe_lexploitant(nom):
    assert exploitant_designe(nom, None, {})


@pytest.mark.parametrize("nom", [
    "PIEGEPART GASTON", "Mr PIEGEPART Gaston", "[NC] PIEGEPART Arlette",
    "EIRL PIEGEPART GASTON", "PIEGEPART Gaston (élevage)",
    # Une société, peut-être — mais rien ne le dit : on ne devine pas.
    "BOULANGERIE PIEGEPART", None, "",
])
def test_sans_forme_juridique_lexploitant_nest_pas_designe(nom):
    assert not exploitant_designe(nom, None, {})


def test_le_siren_connu_tranche_dans_les_deux_sens():
    formes = {"123456789": "5710", "987654321": "1000"}
    assert exploitant_designe("FROMAGERIE DE TESTONVILLE", "12345678900011", formes)
    assert not exploitant_designe("SARL DE FAÇADE", "98765432100011", formes)


def _installation(base, code, nom, siret=None):
    base.execute(
        "INSERT INTO icpe_installations (code_aiot, raison_sociale, insee, commune, adresse,"
        " regime, seveso, etat_activite, lat, lng, raw_data) VALUES (?,?,'99001','Testonville',"
        " '5 rue des Lilas','Enregistrement','Non Seveso','En exploitation',44.1,3.9,?)",
        (code, nom, json.dumps({"siret": siret})))
    base.commit()


def test_un_particulier_ne_garde_que_sa_commune_et_son_regime(base):
    _installation(base, "A1", "PIEGEPART Gaston (élevage)")
    _installation(base, "A2", "SARL CARRIERES D'ÉPREUVE")
    icpe, masques = export_icpe(base)
    assert masques == 1
    particulier = next(i for i in icpe if i.get("exploitant_masque"))
    assert particulier == {"raison_sociale": None, "exploitant_masque": True,
                           "commune": "Testonville", "regime": "Enregistrement",
                           "seveso": "Non Seveso", "etat_activite": "En exploitation"}
    societe = next(i for i in icpe if not i.get("exploitant_masque"))
    assert (societe["raison_sociale"], societe["adresse"], societe["lat"], societe["code_aiot"]) == (
        "SARL CARRIERES D'ÉPREUVE", "5 rue des Lilas", 44.1, "A2")
    assert "PIEGEPART" not in json.dumps(icpe, ensure_ascii=False)


def test_sans_table_rien_ne_sort(base):
    base.execute("DROP TABLE icpe_installations")
    assert export_icpe(base) == ([], 0)
