"""Le contrôle d'étanchéité du snapshot publié.

Il est écrit comme un adversaire et ne partage aucun code avec le builder :
si les deux avaient le même bug, la fuite passerait. Ces tests portent donc sur
le contrôleur seul, en lui donnant des répertoires publiés fabriqués à la main.

L'invariant de périmètre est né du 14/08/2026 : un site de commune qui publiait
6 151 fiches d'une voisine pour 1 012 des siennes, sans qu'aucun contrôle ne
bronche.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Les chaînes que le contrôle du kit interdit sont assemblées à l'exécution :
# écrites en clair, elles feraient refuser l'archive qui contient ces tests —
# et à raison, puisque la règle est qu'aucun chemin personnel n'y figure. Le
# détecteur est bien exercé, il reçoit la même chaîne.
CHEMIN_PERSONNEL = "/" + "Users/quelquun"


@pytest.fixture(scope="module")
def vs():
    spec = importlib.util.spec_from_file_location(
        "verify_snapshot", ROOT / "scripts" / "verify_snapshot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _publier(dossier: Path, entites: list[dict]) -> Path:
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "entity_index.json").write_text(
        json.dumps({"entities": entites}, ensure_ascii=False), encoding="utf-8")
    return dossier


def _fiches(commune: str, n: int, depart: int = 0) -> list[dict]:
    return [{"id": depart + i, "n": f"Acteur {depart + i}", "t": "business",
             "c": commune} for i in range(n)]


# ── L'invariant de périmètre ─────────────────────────────────────────────────

def test_site_conforme_passe(vs, tmp_path, monkeypatch):
    monkeypatch.setitem(vs.RULES, "project", {"commune": "Testonville"})
    rep = vs.Report()
    vs.check_perimetre(_publier(tmp_path / "ok",
                                _fiches("Testonville", 94) + _fiches("Voisinbourg", 6, 100)),
                       rep)
    assert rep.errors == {} and rep.warnings == {}


def test_commune_minoritaire_bloque(vs, tmp_path, monkeypatch):
    """Le cas Saillans : 1 012 fiches de la commune, 6 151 d'une voisine."""
    monkeypatch.setitem(vs.RULES, "project", {"commune": "Testonville"})
    rep = vs.Report()
    vs.check_perimetre(_publier(tmp_path / "ko",
                                _fiches("Testonville", 10) + _fiches("Voisinbourg", 60, 100)),
                       rep)
    assert rep.errors, "un site publiant surtout une autre commune doit être refusé"


def test_commune_majoritaire_mais_diluee_bloque(vs, tmp_path, monkeypatch):
    """Le cas Lasalle-v3 : la commune reste première, mais à 24 %."""
    monkeypatch.setitem(vs.RULES, "project", {"commune": "Testonville"})
    rep = vs.Report()
    entites = (_fiches("Testonville", 24)
               + _fiches("Voisinbourg", 20, 100)
               + _fiches("Les Essarts-d'Épreuve", 20, 200)
               + _fiches("Ailleurs", 36, 300))
    vs.check_perimetre(_publier(tmp_path / "dilue", entites), rep)
    assert rep.errors, "être la commune la plus publiée ne suffit pas"


def test_derive_signalee_avant_de_bloquer(vs, tmp_path, monkeypatch):
    monkeypatch.setitem(vs.RULES, "project", {"commune": "Testonville"})
    rep = vs.Report()
    vs.check_perimetre(_publier(tmp_path / "warn",
                                _fiches("Testonville", 60) + _fiches("Voisinbourg", 40, 100)),
                       rep)
    assert not rep.errors
    assert rep.warnings, "60 % doit alerter sans interrompre la publication"


def test_index_absent_ne_fait_rien(vs, tmp_path):
    """Un répertoire sans index n'est pas une violation : c'est un autre dossier."""
    rep = vs.Report()
    (tmp_path / "vide").mkdir()
    vs.check_perimetre(tmp_path / "vide", rep)
    assert rep.errors == {} and rep.warnings == {}


# ── Les règles de fond ───────────────────────────────────────────────────────

def test_confidence_privee_refusee(vs, tmp_path):
    rep = vs.Report()
    fichier = tmp_path / "acteurs.json"
    fichier.write_text(json.dumps(
        {"entities": [{"name": "Piste", "confidence": "hypothesis"}]}), encoding="utf-8")
    vs.check_file(fichier, rep, tmp_path)
    assert any("confidence" in r for r in rep.errors)


def test_personne_avec_coordonnees_refusee(vs, tmp_path):
    rep = vs.Report()
    fichier = tmp_path / "acteurs.json"
    fichier.write_text(json.dumps(
        {"entities": [{"name": "Quelqu'un", "type": "person",
                       "lat": 45.0, "lng": 3.0}]}), encoding="utf-8")
    vs.check_file(fichier, rep, tmp_path)
    assert any("coordonnées" in r for r in rep.errors)


def test_date_de_naissance_refusee(vs, tmp_path):
    rep = vs.Report()
    fichier = tmp_path / "acteurs.json"
    fichier.write_text(json.dumps(
        {"entities": [{"name": "Quelqu'un", "birth_date": "1970-01-01"}]}),
        encoding="utf-8")
    vs.check_file(fichier, rep, tmp_path)
    assert any("clé interdite" in r for r in rep.errors)


def test_chemin_local_refuse(vs, tmp_path):
    rep = vs.Report()
    fichier = tmp_path / "actes.json"
    fichier.write_text(json.dumps(
        {"events": [{"title": "Acte",
                     "url": "file://" + CHEMIN_PERSONNEL + "/pv.pdf"}]}),
        encoding="utf-8")
    vs.check_file(fichier, rep, tmp_path)
    assert any("chaîne locale" in r for r in rep.errors)


def test_base_dans_le_repertoire_publie_refusee(vs, tmp_path):
    rep = vs.Report()
    (tmp_path / "99001.db").write_bytes(b"SQLite format 3\x00")
    vs.check_dir(tmp_path, rep)
    assert any("fichier interdit" in r for r in rep.errors)
