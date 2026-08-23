"""Le garde-fou du build : ce qu'il doit prendre, et ce qu'il ne doit plus.

`public/scripts/verifier_build.mjs` refuse un build dont une page ne contient
que son attendeur — le défaut du 12/08/2026, où 20 routes sur 24 chargeaient
leurs données en `onMount` et ne livraient que « Chargement… » aux moteurs de
recherche et à Internet Archive.

Il cherchait le MOT. Le 23/08/2026, il a refusé tout le site de Saillans pour un
marché intitulé « Acquisition d'un véhicule de collecte benne à chargement
vertical » : trois pages bloquées, aucune vide, l'instance impubliable à cause
d'un mot venu d'une source publique. Le motif est donc la FORME d'un attendeur —
majuscule de début de phrase, points de suspension — jamais le mot seul.

Le test lit la règle dans le script lui-même : une réécriture qui la relâcherait
sans y penser le ferait échouer ici, là où le reste de la suite vit.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GARDE = ROOT / "public" / "scripts" / "verifier_build.mjs"


@pytest.fixture(scope="module")
def attente() -> re.Pattern:
    source = GARDE.read_text(encoding="utf-8")
    motif = re.search(r"^const ATTENTE = /(.+)/$", source, re.M)
    assert motif, "règle ATTENTE introuvable dans verifier_build.mjs"
    return re.compile(motif.group(1))


@pytest.mark.parametrize("rendu", [
    "<p>Chargement de la carte…</p>",
    "<p>Chargement des marchés...</p>",
    "<div><span>Chargement…</span></div>",
])
def test_un_attendeur_est_pris(attente, rendu):
    assert attente.search(rendu)


@pytest.mark.parametrize("rendu", [
    "<td>Acquisition d'une benne à chargement vertical (benne et grue)</td>",
    "<td>Chargement vertical de bennes ordures ménagères</td>",
    "<a>Quai de chargement du marché couvert</a>",
])
def test_une_donnee_qui_dit_chargement_passe(attente, rendu):
    """Une source publique a le droit de parler de chargement. Le contrôle ne
    doit pas confondre ce qu'une page RACONTE avec ce qu'elle ATTEND."""
    assert not attente.search(rendu)


def test_le_mot_seul_ne_suffit_plus(attente):
    """Le point de suspension est ce qui distingue les deux : sans lui, une
    page qui n'attend rien serait refusée — c'est le défaut qu'on corrige."""
    assert not attente.search("<p>Chargement</p>")
