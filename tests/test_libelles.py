"""Les formes grammaticales du nom de commune.

« de Lasalle » ne se dérive pas mécaniquement en « de Alès », ni « à Le Bez ».
Une chaîne « de {COMMUNE} » écrite à la main finit toujours par produire une
faute sur la commune suivante — d'où un module généré plutôt que des libellés
dans le code.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def gl():
    spec = importlib.util.spec_from_file_location(
        "generer_libelles", ROOT / "scripts" / "generer_libelles.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("nom, de, a", [
    ("Brassac",        "de Brassac",        "à Brassac"),
    ("Alès",           "d'Alès",            "à Alès"),
    ("Le Bez",         "du Bez",            "au Bez"),
    ("Les Plantiers",  "des Plantiers",     "aux Plantiers"),
    ("La Salvetat",    "de La Salvetat",    "à La Salvetat"),
    ("Uzès",           "d'Uzès",            "à Uzès"),
])
def test_formes_grammaticales(gl, nom, de, a):
    f = gl.formes(nom)
    assert f["de"] == de
    assert f["a"] == a


def test_les_deux_applications_recoivent_le_module(gl):
    """Le site public ET l'atelier : l'atelier a été oublié pendant des mois,
    et nommait donc la commune d'origine dans ses 21 pages."""
    cibles = {c.parent.parent.parent.name for c in gl.CIBLES}
    assert cibles == {"public", "dashboard"}
    assert all(c.name == "instance.js" for c in gl.CIBLES)


def test_le_module_genere_nest_pas_versionne():
    """Il décrit une commune : il n'a rien à faire dans un dépôt public."""
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "public/src/lib/instance.js" in ignore
    assert "dashboard/src/lib/instance.js" in ignore
