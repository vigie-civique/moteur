"""L'emprise du fond de carte : ce qu'elle doit couvrir.

Le site porte TROIS cartes — les acteurs (/carte), les mutations DVF
(/urbanisme) et le repère d'une fiche (/entite) — et l'emprise ne se déduisait
que de la première. Tant que les deux autres chargeaient leurs tuiles chez un
tiers, ça ne se voyait pas : le tiers a le monde entier. Le jour où elles
passent sur le fond local (30/08/2026), une mutation hors emprise devient un
carré blanc.

Mesuré sur les trois instances réelles ce jour-là : les mutations DVF débordent
du cadre des calques — 0,005° au nord à Saillans, autant au sud à Brassac. Elles
tombaient dans le fichier par la seule grâce de la marge de 35 %. Une source qui
n'entre pas dans le calcul n'y entre pas « le plus souvent » : elle n'y entre
pas.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def fond():
    spec = importlib.util.spec_from_file_location(
        "carte_fond", ROOT / "scripts" / "carte_fond.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def snapshot(fond, tmp_path, monkeypatch):
    """Un répertoire `data` comme en écrit `build_public_snapshot.py`."""
    def _ecrire(calques: list[tuple[float, float]], dvf=None):
        donnees = tmp_path / "data"
        (donnees / "layers").mkdir(parents=True)
        (donnees / "layers" / "places.geojson").write_text(json.dumps({
            "type": "FeatureCollection",
            "features": [{"type": "Feature",
                          "geometry": {"type": "Point", "coordinates": [lon, lat]},
                          "properties": {}} for lat, lon in calques],
        }), encoding="utf-8")
        if dvf is not None:
            (donnees / "dvf.json").write_text(
                json.dumps({"dvf": dvf, "total": len(dvf)}), encoding="utf-8")
        monkeypatch.setattr(fond, "DONNEES", donnees)
        monkeypatch.setattr(fond, "LAYERS", donnees / "layers")
        monkeypatch.setattr(fond, "DVF", donnees / "dvf.json")
        return donnees
    return _ecrire


def test_les_mutations_dvf_entrent_dans_l_emprise(fond, snapshot):
    """Le cas réel : une vente au nord du dernier acteur cartographié."""
    snapshot(calques=[(44.00, 3.80), (44.05, 3.85)],
             dvf=[{"lat": 44.20, "lng": 3.82, "price": 100000}])
    lat_min, lon_min, lat_max, lon_max = fond.emprise_du_snapshot()
    assert lat_min <= 44.20 <= lat_max
    assert lon_min <= 3.82 <= lon_max


def test_une_mutation_lointaine_elargit_vraiment_le_cadre(fond, snapshot):
    """Sans DVF dans le calcul, la marge de 35 % suffisait « souvent ». Le test
    prend un point qu'elle ne rattrape pas : c'est la différence entre couvrir
    et avoir de la chance."""
    calques = [(44.00, 3.80), (44.05, 3.85)]
    snapshot(calques=calques, dvf=[{"lat": 44.30, "lng": 3.82}])
    avec = fond.emprise_du_snapshot()
    marge = max(44.05 - 44.00, 0.02) * 0.35
    sans_dvf = 44.05 + marge
    assert sans_dvf < 44.30, "le point choisi doit être hors de portée de la marge"
    assert avec[2] >= 44.30


def test_une_instance_sans_foncier_reste_valide(fond, snapshot):
    """DVF absent n'est pas une anomalie : sans mutation publiée, /urbanisme
    n'affiche pas de carte, et il n'y a rien de plus à couvrir."""
    snapshot(calques=[(44.00, 3.80), (44.05, 3.85)], dvf=None)
    lat_min, _, lat_max, _ = fond.emprise_du_snapshot()
    assert lat_min < 44.00 and lat_max > 44.05


def test_une_mutation_sans_coordonnees_est_ignoree(fond, snapshot):
    """DVF publie des ventes sans géolocalisation : elles n'ont pas de repère
    sur la carte, donc rien à couvrir."""
    snapshot(calques=[(44.00, 3.80), (44.05, 3.85)],
             dvf=[{"lat": None, "lng": None}, {"price": 1}])
    assert len(fond.points_cartographies()) == 2


def test_un_snapshot_vide_refuse_de_conclure(fond, snapshot):
    """Aucun point du tout : construire un fond « du monde entier » ferait un
    fichier de plusieurs gigaoctets. On s'arrête, on le dit."""
    snapshot(calques=[], dvf=None)
    with pytest.raises(SystemExit):
        fond.emprise_du_snapshot()
