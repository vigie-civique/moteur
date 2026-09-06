"""Le statut d'une instance : ce que le site DIT de lui-même.

Trois sites servis par le même moteur n'ont pas le même statut — l'un est tenu
sur place, les deux autres sont des portages de démonstration que personne ne
relit — et jusqu'au 06/09/2026 aucune de leurs pages ne le disait. Un lecteur
arrivé par un moteur de recherche lisait les manques d'un portage comme la
qualité du dispositif.

Deux invariants sont éprouvés ici, et ils tirent dans le même sens :
  - un type inconnu retombe sur le plus MODESTE, jamais sur le plus flatteur ;
  - un snapshot qui ne déclare pas son statut ne se publie pas.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def statut():
    spec = importlib.util.spec_from_file_location(
        "statut", ROOT / "collectors" / "statut.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def vs():
    spec = importlib.util.spec_from_file_location(
        "verify_snapshot", ROOT / "scripts" / "verify_snapshot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stats(dossier: Path, statut_publie) -> Path:
    dossier.mkdir(parents=True, exist_ok=True)
    charge = {"generated_at": "2026-09-06T10:00:00"}
    if statut_publie is not None:
        charge["statut"] = statut_publie
    (dossier / "stats.json").write_text(
        json.dumps(charge, ensure_ascii=False), encoding="utf-8")
    return dossier


# ── Le vocabulaire ───────────────────────────────────────────────────────────

def test_les_trois_etats_ont_un_libelle_et_un_texte(statut):
    for type_ in statut.TYPES:
        n = statut.normaliser({"type": type_})
        assert n["libelle"] and n["texte"]
        assert n["type"] == type_


def test_un_type_inconnu_retombe_sur_le_plus_modeste(statut):
    """Annoncer « tenue » sur une faute de frappe serait la seule erreur
    vraiment coûteuse : elle promettrait une relecture qui n'existe pas."""
    for absurde in ("tenu", "vivante", "en cours", "", None, 42, {"x": 1}):
        assert statut.normaliser({"type": absurde})["type"] == "demonstration"
    assert statut.normaliser(None)["type"] == "demonstration"
    assert statut.normaliser("une chaîne")["type"] == "demonstration"


def test_la_casse_et_les_espaces_sont_tolerés(statut):
    """« TENUE » n'est pas une valeur inconnue : c'est la même, mal tapée. Le
    repli protège d'un état qu'on n'a pas prévu, pas d'une majuscule."""
    assert statut.normaliser({"type": " TENUE "})["type"] == "tenue"
    assert statut.normaliser({"type": "Constitution"})["type"] == "constitution"


def test_aucun_texte_ne_nomme_de_commune(statut):
    """Le module vit dans le moteur : il ne connaît que des états."""
    tout = " ".join(list(statut.TEXTES.values())
                    + list(statut.LIBELLES.values())
                    + [statut.MENTION_COMMUNE])
    assert "Lasalle" not in tout and "Saillans" not in tout and "Brassac" not in tout


def test_le_portage_dit_que_personne_ne_le_tient(statut):
    """C'est la seule information qui compte pour le lecteur : les données sont
    les mêmes registres publics partout, ce qui change est qui relit."""
    texte = statut.normaliser({"type": "demonstration"})["texte"]
    assert "aucun collectif local ne tient ce site" in texte


# ── L'invariant de publication ───────────────────────────────────────────────

def test_snapshot_sans_statut_refuse(vs, tmp_path):
    rep = vs.Report()
    vs.check_statut(_stats(tmp_path / "muet", None), rep)
    assert rep.errors, "un snapshot qui ne dit pas ce qu'il est ne se publie pas"


def test_snapshot_au_statut_inconnu_refuse(vs, tmp_path):
    rep = vs.Report()
    vs.check_statut(_stats(tmp_path / "faux", {"type": "vivante"}), rep)
    assert rep.errors


def test_tenue_sans_titulaire_refuse(vs, tmp_path):
    """Une promesse de relecture humaine sans personne pour la porter."""
    rep = vs.Report()
    vs.check_statut(_stats(tmp_path / "orpheline",
                           {"type": "tenue", "tenue_par": "  ",
                            "derniere_collecte": "2026-09-03"}), rep)
    assert rep.errors


def test_statut_complet_passe(vs, tmp_path):
    rep = vs.Report()
    vs.check_statut(_stats(tmp_path / "ok",
                           {"type": "constitution",
                            "derniere_collecte": "2026-09-03"}), rep)
    assert rep.errors == {} and rep.warnings == {}


def test_statut_sans_date_avertit_sans_bloquer(vs, tmp_path):
    """Un statut sans date est une promesse invérifiable — mais la collecte
    peut n'avoir jamais tourné sur une instance neuve : on ne bloque pas."""
    rep = vs.Report()
    vs.check_statut(_stats(tmp_path / "sans_date", {"type": "demonstration"}), rep)
    assert not rep.errors
    assert rep.warnings


def test_repertoire_sans_stats_est_ignore(vs, tmp_path):
    """`public/build/` est contrôlé lui aussi, et n'a pas de stats.json à sa
    racine : le contrôle doit s'y taire plutôt que d'inventer une violation."""
    vide = tmp_path / "build"
    vide.mkdir()
    rep = vs.Report()
    vs.check_statut(vide, rep)
    assert rep.errors == {} and rep.warnings == {}
