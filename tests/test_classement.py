"""Le classement C1/C2/C3/lien, qui conditionne toute la publication.

Il tourne sur une base réelle au schéma réel : le classement lit
`entities.commune`, `relations` et `financial_flows`, et une base simulée
n'aurait pas les mêmes colonnes.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def cp():
    spec = importlib.util.spec_from_file_location(
        "classer_perimetre", ROOT / "scripts" / "classer_perimetre.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_la_commune_est_c1(cp, base, entite):
    eid = entite("Boulangerie", commune="Testonville")
    assert cp.classer(base)[eid] == "C1"


def test_une_commune_membre_est_c2(cp, base, entite):
    eid = entite("Boulangerie voisine", commune="Voisinbourg")
    assert cp.classer(base)[eid] == "C2"


def test_une_commune_deleguee_est_c2(cp, base, entite):
    """Ancienville a fusionné dans Voisinbourg : elle reste dans le périmètre."""
    eid = entite("Association d'Ancienville", commune="Ancienville")
    assert cp.classer(base)[eid] == "C2"


def test_lepci_est_c2(cp, base, entite):
    eid = entite("CC des Épreuves Réunies", type_="service")
    assert cp.classer(base)[eid] == "C2"


def test_lepci_sous_son_sigle_est_c2(cp, base, entite):
    """Les sources écrivent « CC X », « Communauté de communes X », « CC X »."""
    eid = entite("Communauté de communes des Épreuves Réunies", type_="service")
    assert cp.classer(base)[eid] == "C2"


def test_letat_est_c3(cp, base, entite):
    """Marqueur accentué comparé à du texte désaccentué : « État français »
    tombait en `lien` faute de normalisation des deux côtés."""
    eid = entite("État français", type_="service")
    assert cp.classer(base)[eid] == "C3"


def test_la_prefecture_est_c3(cp, base, entite):
    eid = entite("Préfecture de l'Épreuve", type_="service")
    assert cp.classer(base)[eid] == "C3"


def test_hors_territoire_sans_attache_est_hors(cp, base, entite):
    eid = entite("Entreprise lointaine", commune="Marseille")
    assert cp.classer(base)[eid] == "hors"


def test_hors_territoire_relie_devient_lien(cp, base, entite):
    """Une SCI d'élu, un titulaire de marché : matériau du graphe d'influence."""
    local = entite("Élu local", type_="person", commune="Testonville")
    lointain = entite("SCI ailleurs", commune="Marseille")
    base.execute(
        "INSERT INTO relations (from_id, to_id, relation_type, confidence) "
        "VALUES (?,?,?,?)", (local, lointain, "dirige", "verified"))
    base.commit()
    assert cp.classer(base)[lointain] == "lien"


def test_une_structure_dadhesion_devient_c2(cp, base, entite):
    """Un syndicat auquel la commune adhère décide à sa place."""
    commune = entite("Commune de Testonville", type_="service", commune="Testonville")
    syndicat = entite("Syndicat des eaux du Val", type_="service")
    base.execute(
        "INSERT INTO relations (from_id, to_id, relation_type, confidence) "
        "VALUES (?,?,?,?)", (commune, syndicat, "adhère_à", "verified"))
    base.commit()
    assert cp.classer(base)[syndicat] == "C2"


def test_aucune_entite_ne_reste_non_classee(cp, base, entite):
    """Toute entité reçoit une valeur : sinon elle serait écartée en silence."""
    for nom, commune in [("A", "Testonville"), ("B", "Voisinbourg"),
                         ("C", "Marseille"), ("D", None)]:
        entite(nom, commune=commune)
    classement = cp.classer(base)
    total = base.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    assert len(classement) == total
    assert all(v in ("C1", "C2", "C3", "lien", "hors") for v in classement.values())
