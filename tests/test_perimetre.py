"""Le filtre de périmètre — ce qui décide si une fiche est publiée.

Ces tests existent à cause d'un défaut précis : `publiable_dans_perimetre`
traitait NULL comme C1, et une instance dont le classement n'avait pas tourné
publiait toute son intercommunalité. Mesuré le 14/08/2026 sur deux instances
neuves : 10 735 fiches dont 6 151 relevaient d'une commune voisine, et 4 944
au lieu de 1 807. Aucun test ne couvrait cette fonction.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _charger(nom: str):
    chemin = ROOT / "scripts" / f"{nom}.py"
    spec = importlib.util.spec_from_file_location(nom, chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bps = _charger("build_public_snapshot")


# ── Le défaut fermé ──────────────────────────────────────────────────────────

def test_non_classe_nest_pas_publiable():
    """NULL n'est pas C1. C'est LE test de ce fichier."""
    assert bps.publiable_dans_perimetre(None, "business", False) is False
    assert bps.publiable_dans_perimetre(None, "person", False) is False
    assert bps.publiable_dans_perimetre(None, "service", False) is False


def test_c1_et_lien_sont_publiables():
    assert bps.publiable_dans_perimetre("C1", "business", False) is True
    assert bps.publiable_dans_perimetre("lien", "business", False) is True


def test_hors_perimetre_nest_pas_publiable():
    assert bps.publiable_dans_perimetre("hors", "business", False) is False


def test_valeur_inconnue_nest_pas_publiable():
    """Une valeur qu'on n'a pas prévue ne doit pas ouvrir la porte."""
    assert bps.publiable_dans_perimetre("C4", "business", False) is False
    assert bps.publiable_dans_perimetre("", "business", False) is False


# ── C2/C3 : institutions et élus communautaires seulement ────────────────────

def test_c2_commerce_dune_commune_voisine_reste_prive():
    """Le cas qui a motivé la règle : la boulangerie d'à côté n'est pas ici."""
    assert bps.publiable_dans_perimetre("C2", "business", False) is False


def test_c2_institution_est_publiable():
    for type_ in bps.TYPES_INSTITUTIONNELS:
        assert bps.publiable_dans_perimetre("C2", type_, False) is True


def test_c2_personne_publiable_seulement_si_elle_siege():
    assert bps.publiable_dans_perimetre("C2", "person", False) is False
    assert bps.publiable_dans_perimetre("C2", "person", True) is True


def test_c3_suit_la_meme_regle_que_c2():
    assert bps.publiable_dans_perimetre("C3", "business", False) is False
    assert bps.publiable_dans_perimetre("C3", "service", False) is True


# ── Le garde-fou en amont ────────────────────────────────────────────────────

def test_base_jamais_classee_leve(base, entite):
    entite("Une entreprise", commune="Testonville")
    with pytest.raises(bps.PerimetreNonClasse) as e:
        bps.exiger_perimetre_classe(base)
    # Le message doit dire quoi faire : c'est un message d'exploitation.
    assert "classer_perimetre" in str(e.value)


def test_base_vide_ne_leve_pas(base):
    """Rien à publier n'est pas une erreur — c'est une instance qui démarre."""
    assert bps.exiger_perimetre_classe(base) == 0


def test_base_classee_passe_et_compte_les_trous(base, entite):
    entite("Classée", commune="Testonville", perimetre="C1")
    entite("Classée aussi", commune="Voisinbourg", perimetre="C2")
    entite("Pas classée", commune="Testonville")
    # Une entité non classée n'interrompt pas la publication : elle est écartée,
    # et comptée pour que la lacune se voie.
    assert bps.exiger_perimetre_classe(base) == 1
