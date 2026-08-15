"""`public_entity` — la fonction qui décide, fiche par fiche.

Elle applique quatre règles dans l'ordre : niveau de confiance, rôle civique
pour les personnes, périmètre, puis pertinence. Chacune a son motif de rejet,
consigné dans les statistiques du snapshot pour que les exclusions se comptent
au lieu de se deviner.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def bps():
    spec = importlib.util.spec_from_file_location(
        "build_public_snapshot", ROOT / "scripts" / "build_public_snapshot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fiche(**kw) -> dict:
    base = {"id": 1, "type": "business", "name": "Une entreprise",
            "confidence": "verified", "perimetre": "C1", "commune": "Testonville"}
    base.update(kw)
    return base


# ── Niveau de confiance ──────────────────────────────────────────────────────

@pytest.mark.parametrize("niveau", ["probable", "hypothesis", "unverified", "retracted"])
def test_confidence_privee_rejetee(bps, niveau):
    publiee, motifs = bps.public_entity(fiche(confidence=niveau), [], set())
    assert publiee is None
    assert motifs == ["private_confidence"]


@pytest.mark.parametrize("niveau", ["verified", "confirmed"])
def test_confidence_publique_acceptee(bps, niveau):
    publiee, _ = bps.public_entity(fiche(confidence=niveau), [], set())
    assert publiee is not None


# ── Personnes : jamais sans rôle civique ─────────────────────────────────────

def test_personne_sans_role_civique_rejetee(bps):
    publiee, motifs = bps.public_entity(
        fiche(type="person", name="Un particulier"), [], set())
    assert publiee is None
    assert motifs == ["person_without_public_civic_role"]


def test_personne_avec_role_civique_publiee(bps):
    publiee, _ = bps.public_entity(
        fiche(id=7, type="person", name="Une élue"), [], {7})
    assert publiee is not None


# ── Périmètre ────────────────────────────────────────────────────────────────

def test_entite_non_classee_rejetee(bps):
    publiee, motifs = bps.public_entity(fiche(perimetre=None), [], set())
    assert publiee is None
    assert motifs == ["hors_fiche_perimetre_None"]


def test_commerce_de_commune_voisine_rejete(bps):
    publiee, motifs = bps.public_entity(fiche(perimetre="C2"), [], set())
    assert publiee is None
    assert "perimetre" in motifs[0]


def test_institution_intercommunale_publiee(bps):
    publiee, _ = bps.public_entity(
        fiche(type="service", name="CC des Épreuves Réunies", perimetre="C2"),
        [], set())
    assert publiee is not None


def test_elu_communautaire_publie(bps):
    """Il vote le budget qui s'applique à la commune : le masquer amputerait la
    chaîne de décision de sa moitié intercommunale."""
    publiee, _ = bps.public_entity(
        fiche(id=9, type="person", name="Un délégué", perimetre="C2"),
        [], {9}, ids_conseil_communautaire={9})
    assert publiee is not None


# ── L'ordre des règles est lui-même une garantie ─────────────────────────────

def test_une_personne_privee_c1_reste_privee(bps):
    """Le bon périmètre n'ouvre aucun droit : les règles s'additionnent."""
    publiee, _ = bps.public_entity(
        fiche(type="person", name="Un habitant", perimetre="C1"), [], set())
    assert publiee is None


def test_une_piste_c1_reste_privee(bps):
    publiee, _ = bps.public_entity(
        fiche(perimetre="C1", confidence="hypothesis"), [], set())
    assert publiee is None
