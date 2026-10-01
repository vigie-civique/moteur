"""Écoles et accueil du jeune enfant : lectures et publication, sans appel réseau.

Les lignes reproduites ont la forme que data.education.gouv.fr et data.caf.fr
ont rendue le 01/10/2026.

Ce que ces essais protègent :
  1. les deux jeux d'IPS ne s'accordent pas sur le type (nombre ici, chaîne
     là) : les deux sont lus ;
  2. l'historique et le courant de la CAF se recouvrent sur une année et ne
     s'y accordent pas : le courant prime ;
  3. une école se retrouve par la commune de l'ANNUAIRE, le jeu des effectifs
     portant un code commune faux ;
  4. le département et la France ne sont comparés qu'à année égale.
"""
from __future__ import annotations

import json

from collectors.enfance import (ecoles_suivies, ensure_tables, ligne_effectif, ligne_ips,
                                lignes_accueil)


def test_un_effectif_publie_en_decimal_est_un_entier():
    assert ligne_effectif({"numero_ecole": "0990001A", "rentree_scolaire": "2025",
                           "nombre_total_eleves": 125.0, "nombre_total_classes": 6.0,
                           "nombre_eleves_preelementaire_hors_ulis": 40.0}) == (
        "0990001A", 2025, 125, 40, 6)


def test_les_deux_jeux_d_ips_sont_lus():
    avant = ligne_ips({"uai": "0990001A", "rentree_scolaire": "2021-2022", "ips": 95.7})
    apres = ligne_ips({"uai": "0990001A", "rentree_scolaire": "2024-2025", "ips": "105.3",
                       "ips_national_public": "103.1", "ips_departemental_public": "100.8"})
    assert avant == ("0990001A", "2021-2022", 95.7, None, None)
    assert apres == ("0990001A", "2024-2025", 105.3, 103.1, 100.8)


def test_le_courant_de_la_caf_prime_sur_l_historique():
    courant = [{"annee": 2022, "txcouv_epci": 57.4}, {"annee": 2023, "txcouv_epci": 48.0}]
    historique = [{"annee": "2021", "txcouv_epci": 53.8}, {"annee": "2022", "txcouv_epci": 57.1}]
    places = [{"annee": 2023, "pl_eaje_epci": 35.0, "pl_am_ind_epci": 13, "pl_gad_ind_epci": 1,
               "pl_prescol_epci": 1, "tot_offre_epci": 50}]
    lignes = lignes_accueil("epci", "200000000", places, courant + historique, "epci")
    assert [(l[2], l[8]) for l in lignes] == [(2021, 53.8), (2022, 57.4), (2023, 48.0)]
    assert lignes[-1] == ("epci", "200000000", 2023, 35, 13, 1, 1, 50, 48.0)
    assert lignes[0][3] is None, "un taux sans places : les places restent vides, pas à zéro"


# ── La publication (`export_enfance`) ────────────────────────────────────────

def _ecole(base, entite, uai, commune, nom="Ecole primaire", type_="Ecole"):
    from collectors.education import ensure_table
    ensure_table(base)
    base.execute(
        "INSERT INTO etablissements_scolaires (entity_id, uai, secteur, etat, raw_data)"
        " VALUES (?,?,?,?,?)",
        (entite(f"École {uai}", "service"), uai, "Public", "OUVERT",
         json.dumps({"code_commune": commune, "type_etablissement": type_,
                     "nom_etablissement": nom})))


def _base_enfance(base, entite):
    ensure_tables(base)
    _ecole(base, entite, "0990001A", "99001")
    _ecole(base, entite, "0990002B", "99002")                       # l'école d'une voisine
    _ecole(base, entite, "0990003C", "99001", "Collège", "Collège")  # pas du premier degré
    base.executemany("INSERT INTO ecoles_effectifs VALUES (?,?,?,?,?)", [
        ("0990001A", 2024, 124, 42, 6), ("0990001A", 2025, 125, 40, 6),
        ("0990002B", 2025, 60, 20, 3)])
    base.execute("INSERT INTO ecoles_ips VALUES ('0990001A', '2024-2025', 105.3, 103.1, 100.8)")
    base.executemany("INSERT INTO accueil_petite_enfance VALUES (?,?,?,?,?,?,?,?,?)", [
        ("epci", "200000000", 2021, 28, 18, 4, 0, 50, 53.8),
        ("epci", "200000000", 2023, 35, 13, 1, 1, 50, 48.0),
        ("departement", "99", 2023, None, None, None, None, None, 54.7),
        ("france", "", 2023, None, None, None, None, None, 60.9)])
    base.commit()


def test_les_ecoles_suivies_sont_celles_du_premier_degre_dans_la_commune(base, entite):
    _base_enfance(base, entite)
    assert ecoles_suivies(base, ["99001"]) == ["0990001A"]


def test_la_publication_ne_compare_qu_a_annee_egale(base, entite):
    from scripts.build_public_snapshot import export_enfance
    _base_enfance(base, entite)

    e = export_enfance(base, "99001", "200000000", "99")

    [ecole] = e["ecoles"]
    assert (ecole["uai"], ecole["nom"]) == ("0990001A", "Ecole primaire")
    assert [s["rentree"] for s in ecole["serie"]] == [2024, 2025]
    assert ecole["ips"][0]["france_public"] == 103.1
    a2021, a2023 = e["accueil"]["serie"]
    assert (a2021["departement"], a2021["france"]) == (None, None), "aucun repère publié en 2021"
    assert (a2023["taux"], a2023["departement"], a2023["france"]) == (48.0, 54.7, 60.9)
    assert e["accueil"]["dernier"]["annee"] == 2023


def test_sans_ecole_ni_accueil_rien_ne_sort(base):
    from scripts.build_public_snapshot import export_enfance
    assert export_enfance(base, "99001", "200000000", "99") is None
