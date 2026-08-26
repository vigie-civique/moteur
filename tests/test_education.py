"""Les établissements scolaires manquaient au répertoire.

Signalé le 26/08/2026 : le complexe scolaire du Colombier fait l'objet d'une
délibération d'attribution de maîtrise d'œuvre en février 2025, et
l'équipement n'existait comme entité nulle part. Un acte qui porte sur un
bâtiment public ne peut se rattacher à rien tant que le bâtiment n'est pas
recensé — et l'école est, avec la mairie, le premier équipement public d'une
commune rurale.
"""
from __future__ import annotations

import json

import pytest

from collectors import education


LASALLE = {
    "identifiant_de_l_etablissement": "0301674G",
    "nom_etablissement": "Ecole primaire",
    "type_etablissement": "Ecole",
    "libelle_nature": "ECOLE DE NIVEAU ELEMENTAIRE",
    "statut_public_prive": "Public",
    "adresse_1": "Place Robert Francisque",
    "code_postal": "30460",
    "nom_commune": "Lasalle",
    "latitude": "44.04564316658195",
    "longitude": "3.8549395672159927",
    "etat": "OUVERT",
    "date_ouverture": "2002-09-01",
    "ministere_tutelle": "MINISTERE DE L'EDUCATION NATIONALE",
    "nombre_d_eleves": 61,
}


@pytest.fixture
def base_scolaire(base, monkeypatch):
    monkeypatch.setattr(education, "upsert_entity", _upsert_direct(base))
    education.ensure_table(base)
    return base


def _upsert_direct(base):
    def _u(conn, *, type, name, short_name=None, lat=None, lng=None,
           address=None, confidence="verified", commune=None):
        row = conn.execute("SELECT id FROM entities WHERE type=? AND name=?",
                           (type, name)).fetchone()
        if row:
            return row["id"]
        return conn.execute(
            "INSERT INTO entities (type,name,name_norm,short_name,lat,lng,"
            "address,commune,confidence) VALUES (?,?,?,?,?,?,?,?,?)",
            (type, name, name.lower(), short_name, lat, lng, address,
             commune, confidence)).lastrowid
    return _u


class TestLeNomDoitDesignerLEtablissement:
    """L'annuaire nomme « Ecole primaire » la plupart des écoles publiques.

    Tel quel, le répertoire d'une intercommunalité de quinze communes
    contiendrait quinze « Ecole primaire » indiscernables — et l'index unique
    (type, name) n'en garderait qu'UNE SEULE.
    """

    def test_la_commune_est_accolee_a_un_nom_generique(self):
        assert education._nom_lisible(LASALLE) == "Ecole primaire — Lasalle"

    def test_un_nom_qui_porte_deja_la_commune_reste_intact(self):
        assert education._nom_lisible(
            {"nom_etablissement": "Collège de Lasalle", "nom_commune": "Lasalle"}
        ) == "Collège de Lasalle"

    def test_sans_nom_l_etablissement_reste_nommable(self):
        assert education._nom_lisible({"nom_commune": "Lasalle"}) \
            == "Établissement scolaire — Lasalle"


class TestLUaiEstLaCle:
    """`uai` est le SIREN de l'école : stable, opposable, national."""

    def test_deux_ecoles_homonymes_de_communes_voisines_coexistent(self, base_scolaire):
        voisine = {**LASALLE, "identifiant_de_l_etablissement": "0301675H",
                   "nom_commune": "Soudorgues"}
        a, _ = education._importer(base_scolaire, LASALLE, "Lasalle")
        b, _ = education._importer(base_scolaire, voisine, "Soudorgues")
        assert a != b
        assert base_scolaire.execute(
            "SELECT COUNT(*) FROM etablissements_scolaires").fetchone()[0] == 2

    def test_une_recollecte_ne_duplique_pas(self, base_scolaire):
        a, cree1 = education._importer(base_scolaire, LASALLE, "Lasalle")
        b, cree2 = education._importer(base_scolaire, LASALLE, "Lasalle")
        assert (a, cree1, cree2) == (b, True, False)
        assert base_scolaire.execute(
            "SELECT COUNT(*) FROM entities").fetchone()[0] == 1

    def test_une_recollecte_ne_renomme_pas(self, base_scolaire):
        """L'atelier a pu corriger le libellé ; l'annuaire ne le saura pas."""
        eid, _ = education._importer(base_scolaire, LASALLE, "Lasalle")
        base_scolaire.execute(
            "UPDATE entities SET name='École du Colombier' WHERE id=?", (eid,))
        education._importer(base_scolaire, LASALLE, "Lasalle")
        assert base_scolaire.execute(
            "SELECT name FROM entities WHERE id=?", (eid,)).fetchone()[0] \
            == "École du Colombier"


class TestCeQuiChangeDUneRentreeALAutre:
    """L'état et les effectifs sont les deux seuls champs qu'on rafraîchit."""

    def test_une_fermeture_est_reprise(self, base_scolaire):
        eid, _ = education._importer(base_scolaire, LASALLE, "Lasalle")
        ferme = {**LASALLE, "etat": "FERME", "date_fermeture": "2027-07-04",
                 "nombre_d_eleves": 0}
        education._importer(base_scolaire, ferme, "Lasalle")
        r = base_scolaire.execute(
            "SELECT etat, fermeture, eleves FROM etablissements_scolaires"
            " WHERE entity_id=?", (eid,)).fetchone()
        assert (r["etat"], r["fermeture"], r["eleves"]) == ("FERME", "2027-07-04", 0)

    def test_l_etablissement_ferme_est_collecte_quand_meme(self, base_scolaire):
        """Une école fermée en 2019 apparaît dans les délibérations qui l'ont
        fermée : sa fiche est ce qui rend ces actes lisibles. C'est la
        publication qui décide de son sort, pas la collecte."""
        ferme = {**LASALLE, "identifiant_de_l_etablissement": "0300001A",
                 "etat": "FERME"}
        eid, cree = education._importer(base_scolaire, ferme, "Lasalle")
        assert cree and eid


class TestLaFicheEstUnServicePublic:

    def test_l_entite_est_un_service_de_categorie_education(self, base_scolaire):
        eid, _ = education._importer(base_scolaire, LASALLE, "Lasalle")
        assert base_scolaire.execute(
            "SELECT type FROM entities WHERE id=?", (eid,)).fetchone()[0] == "service"
        assert base_scolaire.execute(
            "SELECT category FROM services WHERE entity_id=?",
            (eid,)).fetchone()[0] == "education"

    def test_la_source_est_conservee_entiere(self, base_scolaire):
        eid, _ = education._importer(base_scolaire, LASALLE, "Lasalle")
        brut = json.loads(base_scolaire.execute(
            "SELECT raw_data FROM etablissements_scolaires WHERE entity_id=?",
            (eid,)).fetchone()[0])
        assert brut["identifiant_de_l_etablissement"] == "0301674G"

    def test_une_coordonnee_illisible_ne_perd_pas_l_etablissement(self, base_scolaire):
        bancal = {**LASALLE, "latitude": "", "longitude": "n/a"}
        eid, _ = education._importer(base_scolaire, bancal, "Lasalle")
        r = base_scolaire.execute(
            "SELECT lat, lng FROM entities WHERE id=?", (eid,)).fetchone()
        assert (r["lat"], r["lng"]) == (None, None)
