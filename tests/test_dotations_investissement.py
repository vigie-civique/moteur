"""Les dotations d'investissement ACCORDÉES par l'État, opération par opération.

`subventions_etat` lit les titres des délibérations et y reconnaît une DEMANDE.
Une demande n'est pas une attribution : le conseil décide de solliciter, l'État
décide d'accorder, et entre les deux il y a le refus, le rabotage et l'abandon.
Ces deux registres-ci publient ce qui a été accordé.

Les cas éprouvés ici sont ceux que le corpus réel impose — les libellés de
dispositif qui changent d'une année sur l'autre, et l'exercice du Fonds vert
qui ne vit que dans le nom du fichier.
"""
from __future__ import annotations

import pytest

# Ces deux collecteurs sortent sur le réseau, donc importent `requests`, que le
# job « tests » de la CI n'installe pas : il n'installe que pytest, pour
# démontrer que le cœur du moteur se teste sans réseau ni collecteur. Ce fichier
# y est donc SAUTÉ, et joué par le job « tests-deps », qui refuse le moindre
# test sauté. Même convention que `tests/test_dematdoc.py` pour pdfplumber.
pytest.importorskip("requests",
                    reason="job « tests-deps » : pip install -r requirements.txt")

from collectors.dotations_investissement import (_annee_du_titre, _famille,
                                                 _nombre)  # noqa: E402


# ── La famille de dotation, et sa variante de l'année ────────────────────────

def test_les_quatre_dotations_sont_reconnues():
    for nom in ("DETR", "DSIL", "DSID", "DPV"):
        assert _famille(nom) == (nom, "")


def test_une_variante_garde_la_famille_pour_type():
    """2020 ajoute « DSIL Exceptionnelle », 2021 « DSIL RT » et « DSID RT »,
    puis ces libellés disparaissent. Les prendre pour type produisait un
    `dotation_dsil exceptionnelle` — un type avec une espace dedans, et une
    DSIL que rien ne rattachait aux autres DSIL."""
    assert _famille("DSIL Exceptionnelle") == ("DSIL", "DSIL Exceptionnelle")
    assert _famille("DSIL RT") == ("DSIL", "DSIL RT")
    assert _famille("DSID RT") == ("DSID", "DSID RT")


def test_la_casse_et_les_espaces_de_la_source_ne_comptent_pas():
    assert _famille("  detr ")[0] == "DETR"


def test_une_dotation_inconnue_se_voit_au_lieu_de_disparaitre():
    """Un dispositif que la DGCL créerait demain doit apparaître en base sous
    son propre nom — ni rangé dans un fourre-tout, ni cause d'un échec."""
    type_, variante = _famille("Fonds Friches")
    assert type_ == "dotation_fonds_friches"
    assert variante == "Fonds Friches"


def test_un_dispositif_vide_ne_fait_pas_echouer():
    assert _famille("")[0] == "dotation_inconnue"


# ── L'exercice du Fonds vert ─────────────────────────────────────────────────

def test_lexercice_se_lit_dans_le_nom_du_fichier():
    """Le Fonds vert ne porte l'année dans aucune colonne. Un flux sans année
    est rangé hors de toute période, et le total d'un exercice l'ignore."""
    assert _annee_du_titre("fonds-vert-2025-export.csv") == 2025


def test_un_numero_de_programme_nest_pas_une_annee():
    """« p113 » est le programme budgétaire, pas un millésime."""
    assert _annee_du_titre("fonds-vert-p113-2024-export.csv") == 2024


def test_un_titre_sans_annee_ne_lit_rien():
    assert _annee_du_titre("fonds-vert-export.csv") is None


# ── Les montants tels que la source les écrit ────────────────────────────────

def test_les_montants_se_lisent_avec_virgule_ou_point():
    assert _nombre("2023,0") == 2023
    assert _nombre("49736.58") == 49737


def test_une_case_vide_ne_devient_pas_zero():
    """Un montant absent et un montant nul ne disent pas la même chose."""
    assert _nombre("") is None
    assert _nombre(None) is None
