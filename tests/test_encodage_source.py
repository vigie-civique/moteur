"""Le mojibake livré par une source, défait sans rien deviner.

Le 23/08/2026, le fil d'accueil du site public de Lasalle affichait
« L'EUZIAÃÂRE ». Le collecteur n'y était pour rien : le CSV brut de Sitadel,
archivé sous `data/raw/sitadel/`, contient déjà les octets
`C3 83 C2 82 C3 82 C2 88`, et c'est de l'UTF-8 parfaitement valide. C'est le
CONTENU qui est abîmé, livré ainsi par DIDO.

Trois formes coexistent dans le corpus, et se défont différemment :

  « MickaÃ«l »        BODACC : une relecture latin-1, une seule couche
  « L'EUZIAÈRE »      Sitadel : deux couches, et l'octet de tête `C3` rabattu
                      sur « A » par un dépilage d'accents en amont
  « aujourdâ€™hui »   la variante cp1252, où l'octet 0x80 est devenu « € »

Ce que ces cas défendent surtout, c'est l'absence de faux positif : « CHÂTEAU »,
« THÉÂTRE », « Âne », « CAFÉ… » sont du français correct et abondent dans le
corpus. Une règle qui bloquerait sur « Â » ou « Ã » isolé refuserait de publier
la moitié des lieux-dits du Gard.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from collectors.nom_normalise import porte_du_mojibake, reparer_encodage

ROOT = Path(__file__).resolve().parent.parent

# Chacun vient de la base de Lasalle au 23/08/2026, sauf mention.
ABIMES = [
    # Sitadel : « Ã » dépilé en « A », octet de queue resté en contrôle C1.
    ("L'EUZIA\xc3\x82\xc2\x88RE", "L'EUZIÈRE"),
    ("37A DE TRA\xc3\x82\xc2\x88VES", "37A DE TRÈVES"),
    ("NA\xc3\x82\xc2\x8eMES", "NÎMES"),
    # BODACC : une seule couche de latin-1.
    ("Micka\xc3\xabl", "Mickaël"),
    ("prono\xc3\xa7ant la r\xc3\xa9solution", "pronoçant la résolution"),
    ("https://x/Auvergne-Rh\xc3\xb4ne-Alpes/63", "https://x/Auvergne-Rhône-Alpes/63"),
    # cp1252 : l'apostrophe courbe passée par Windows.
    ("aujourd\xe2€™hui", "aujourd’hui"),
]

# Du français correct, qui doit sortir intact.
CORRECTS = [
    "CHÂTEAU DE LA TOUR",
    "THÉÂTRE DE L'ÂNE",
    "Nîmes",
    "Sainte-Croix-de-Caderle",
    "L'Euzière",
    "Rue de Trèves",
    "CAFÉ… et thé",
    "coût prévisionnel : 162 724,13 €",
    "À l'unanimité — 15 voix pour",
    "l’année",
    "aujourd’hui",
]


@pytest.mark.parametrize("abime,attendu", ABIMES)
def test_la_reparation_rend_le_texte_dorigine(abime, attendu):
    assert reparer_encodage(abime) == attendu


@pytest.mark.parametrize("abime,_", ABIMES)
def test_rien_ne_reste_apres_reparation(abime, _):
    assert not porte_du_mojibake(reparer_encodage(abime))


@pytest.mark.parametrize("abime,_", ABIMES)
def test_la_reparation_est_idempotente(abime, _):
    """Une base réparée deux fois doit être identique à une base réparée une fois.

    Le script `reparer_encodage.py` est fait pour être relancé — sur une
    instance recollectée, sur une base restaurée — et une réparation qui
    grignote un caractère de plus à chaque passage abîmerait le texte.
    """
    une_fois = reparer_encodage(abime)
    assert reparer_encodage(une_fois) == une_fois


@pytest.mark.parametrize("correct", CORRECTS)
def test_le_francais_accentue_sort_intact(correct):
    assert reparer_encodage(correct) == correct
    assert not porte_du_mojibake(correct)


def test_valeurs_vides():
    assert reparer_encodage(None) is None
    assert reparer_encodage("") == ""
    assert not porte_du_mojibake(None)


class TestRegleDuControleur:
    """Le contrôleur du snapshot porte sa PROPRE copie de la règle.

    `verify_snapshot` ne doit jamais importer le code qu'il contrôle — sans
    quoi un défaut du builder se contrôlerait lui-même. La duplication est
    donc voulue, et c'est précisément pour ça qu'elle se teste : les deux
    copies doivent voir les mêmes textes.
    """

    @staticmethod
    def _controleur():
        spec = importlib.util.spec_from_file_location(
            "verify_snapshot", ROOT / "scripts" / "verify_snapshot.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @pytest.mark.parametrize("abime,_", ABIMES)
    def test_le_controleur_refuse_un_texte_abime(self, abime, _):
        assert self._controleur().MOJIBAKE.search(abime), abime

    @pytest.mark.parametrize("correct", CORRECTS)
    def test_le_controleur_laisse_passer_le_francais(self, correct):
        assert not self._controleur().MOJIBAKE.search(correct), correct
