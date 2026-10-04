"""Le manifeste du snapshot : la preuve qu'une construction est allée au bout.

Le 04/10/2026, un plantage du builder a laissé un brouillon tronqué —
`stats.json` présent, `entite/` et `entity_index.json` absents — et l'atelier a
construit le site dessus. Le builder écrit désormais `manifeste.json` en
DERNIER ; `verify_snapshot.py` refuse un snapshot sans manifeste, un fichier
présent qu'il ne liste pas, un fichier listé absent, une empreinte qui ne
concorde pas.

Deux familles d'essais. Les premiers donnent au contrôleur des répertoires
fabriqués à la main, avec un manifeste calculé ICI — ni le builder ni son
module de manifeste ne sont importés : le contrôleur est un adversaire, ses
essais aussi. Les seconds construisent le vrai snapshot de la base de la CI et
l'abîment comme un plantage l'aurait fait.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture(scope="module")
def vs():
    spec = importlib.util.spec_from_file_location(
        "verify_snapshot", ROOT / "scripts" / "verify_snapshot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _manifester(dossier: Path, etape: str | None = "essai") -> None:
    fichiers = []
    for f in sorted(dossier.rglob("*")):
        rel = f.relative_to(dossier).as_posix()
        if f.is_file() and rel not in ("manifeste.json", "version.json"):
            brut = f.read_bytes()
            fichiers.append({"chemin": rel, "etape": etape, "objets": None,
                             "octets": len(brut), "sha256": hashlib.sha256(brut).hexdigest()})
    (dossier / "manifeste.json").write_text(json.dumps(
        {"format": "vigie-manifeste/1", "total": len(fichiers), "fichiers": fichiers}))


def _snapshot(dossier: Path) -> Path:
    (dossier / "entite").mkdir(parents=True)
    (dossier / "stats.json").write_text('{"generated_at": "2026-10-04T10:00:00"}')
    (dossier / "entite" / "1.json").write_text('{"id": 1}')
    return dossier


def _regles(vs, rep, base):
    vs.check_manifeste(base, rep)
    return sorted(rep.errors), sorted(rep.warnings)


def test_un_snapshot_complet_et_son_manifeste_passent(vs, tmp_path):
    base = _snapshot(tmp_path / "s")
    _manifester(base)
    assert _regles(vs, vs.Report(), base) == ([], [])


def test_un_snapshot_sans_manifeste_est_refuse(vs, tmp_path):
    """Le brouillon du 04/10 : `stats.json` est là, rien ne dit que le reste suit."""
    base = _snapshot(tmp_path / "s")
    erreurs, _ = _regles(vs, vs.Report(), base)
    assert erreurs == ["snapshot sans manifeste — construction interrompue ou incomplète"]


def test_un_repertoire_qui_n_est_pas_un_snapshot_n_exige_rien(vs, tmp_path):
    """Le build du site (`public/build`) n'a pas de `stats.json` à sa racine."""
    base = tmp_path / "build"
    base.mkdir()
    (base / "index.html").write_text("<html></html>")
    assert _regles(vs, vs.Report(), base) == ([], [])


def test_un_fichier_manquant_ajoute_ou_modifie_est_refuse(vs, tmp_path):
    base = _snapshot(tmp_path / "s")
    _manifester(base)
    (base / "entite" / "1.json").unlink()
    (base / "intrus.json").write_text("{}")
    (base / "stats.json").write_text('{"generated_at": "autre"}')
    erreurs, _ = _regles(vs, vs.Report(), base)
    assert erreurs == ["empreinte différente de celle du manifeste",
                       "fichier absent du manifeste",
                       "fichier du manifeste manquant"]


def test_version_json_et_les_rebuts_restent_hors_manifeste(vs, tmp_path):
    """La publication écrit `version.json` APRÈS le contrôle ; un `.DS_Store`
    est refusé par sa propre règle, pas deux fois."""
    base = _snapshot(tmp_path / "s")
    _manifester(base)
    (base / "version.json").write_text('{"empreinte": "x"}')
    (base / ".DS_Store").write_bytes(b"\0")
    assert _regles(vs, vs.Report(), base) == ([], [])


def test_un_fichier_qu_aucune_etape_n_a_ecrit_se_signale(vs, tmp_path):
    base = _snapshot(tmp_path / "s")
    _manifester(base, etape=None)
    erreurs, avertissements = _regles(vs, vs.Report(), base)
    assert erreurs == [] and avertissements == [
        "fichier qu'aucune étape de la construction n'a écrit"]


def test_un_manifeste_illisible_ou_incoherent_est_refuse(vs, tmp_path):
    base = _snapshot(tmp_path / "s")
    (base / "manifeste.json").write_text("{pas du json")
    assert _regles(vs, vs.Report(), base)[0] == ["manifeste illisible"]
    _manifester(base)
    m = json.loads((base / "manifeste.json").read_text())
    m["total"] += 1
    (base / "manifeste.json").write_text(json.dumps(m))
    assert _regles(vs, vs.Report(), base)[0] == ["manifeste incohérent"]


# ── Le vrai snapshot de la base de la CI ─────────────────────────────────────

@pytest.fixture(scope="module")
def construit(tmp_path_factory):
    from snapshot_reference import construire, horloge_de_reference
    travail = tmp_path_factory.mktemp("manifeste")
    out = construire(ROOT, travail, horloge_de_reference())
    return travail, out


def _verifier(travail: Path, out: Path) -> dict:
    env = {**os.environ, "VIGIE_RULES": str(travail / "moteur" / "db" / "ci.regles.json"),
           "VIGIE_INSTANCE": str(ROOT / "tests" / "instance_test.json")}
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_snapshot.py"),
                        str(out), "--json"], capture_output=True, text=True, env=env)
    return json.loads(r.stdout)


def _regles_en_erreur(rapport: dict) -> list[str]:
    return [g["regle"] for g in rapport["erreurs"]]


def test_le_builder_ecrit_un_manifeste_complet_en_dernier(construit):
    travail, out = construit
    m = json.loads((out / "manifeste.json").read_text())
    listes = {f["chemin"] for f in m["fichiers"]}
    presents = {f.relative_to(out).as_posix() for f in out.rglob("*") if f.is_file()}
    assert listes == presents - {"manifeste.json"}
    assert m["total"] == len(listes)
    assert all(f["etape"] for f in m["fichiers"]), "un fichier sans étape"
    assert {f["chemin"]: f["etape"] for f in m["fichiers"]}["stats.json"] == "stats"
    entites = {f["chemin"]: f["objets"] for f in m["fichiers"]}["entities.json"]
    assert entites == len(json.loads((out / "entities.json").read_text())["entities"])
    # Le dernier écrit : rien n'est plus récent que lui.
    quand = (out / "manifeste.json").stat().st_mtime_ns
    assert all(f.stat().st_mtime_ns <= quand for f in out.rglob("*") if f.is_file())
    assert _regles_en_erreur(_verifier(travail, out)) == []


def test_un_snapshot_tronque_comme_le_04_10_est_refuse(construit, tmp_path):
    """Le plantage du 04/10 : la construction s'arrête avant `entite/` et
    `entity_index.json`, et donc avant le manifeste."""
    import shutil
    travail, out = construit
    tronque = tmp_path / "tronque"
    shutil.copytree(out, tronque)
    shutil.rmtree(tronque / "entite")
    (tronque / "entity_index.json").unlink()
    (tronque / "manifeste.json").unlink()
    assert _regles_en_erreur(_verifier(travail, tronque)) == [
        "snapshot sans manifeste — construction interrompue ou incomplète"]


def test_une_reconstruction_retire_l_ancien_manifeste_avant_d_ecrire(construit, tmp_path):
    """Une construction qui plante dans un répertoire réutilisé ne garde pas le
    manifeste de la précédente, qui couvrirait des fichiers à moitié réécrits."""
    from scripts.snapshot.etapes import ETAPES
    noms = [e.nom for e in ETAPES]
    premiere_ecriture = next(i for i, e in enumerate(ETAPES) if "out" in e.lit)
    assert noms[premiere_ecriture] == "retirer_manifeste"
    assert noms[-1] == "manifeste"


def test_un_fichier_retire_du_registre_quitte_le_repertoire(tmp_path):
    """04/10/2026 : `event_links.json` et `croisement_foncier.json` ne sont plus
    écrits. Le répertoire de sortie gardait ceux d'une construction
    précédente, et la recopie vers le site les servait encore."""
    from scripts.build_public_snapshot import retirer_fichiers_non_declares
    (tmp_path / "event_links.json").write_text("{}")
    (tmp_path / "events.json").write_text("{}")
    (tmp_path / "version.json").write_text("{}")

    assert retirer_fichiers_non_declares(tmp_path) == ["event_links.json"]
    assert sorted(f.name for f in tmp_path.iterdir()) == ["events.json", "version.json"]
