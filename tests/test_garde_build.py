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


# ── Le fond de carte ne vient jamais d'un tiers ─────────────────────────────
#
# Le 29/08/2026, /carte a cessé d'appeler CARTO ; /urbanisme et /entite ont
# continué d'appeler `tile.openstreetmap.org` un jour de plus, et rien ne
# pouvait le dire — la correction avait été jugée faite. Le contrôle ci-dessous
# est ce qui manquait : il lit ses deux règles dans le script, si bien qu'une
# réécriture qui les relâcherait échouerait ici.

@pytest.fixture(scope="module")
def fonds_tiers() -> re.Pattern:
    source = GARDE.read_text(encoding="utf-8")
    motif = re.search(r"^const FONDS_TIERS = /(.+)/$", source, re.M)
    assert motif, "règle FONDS_TIERS introuvable dans verifier_build.mjs"
    return re.compile(motif.group(1).replace("\\\\", "\\"))


@pytest.fixture(scope="module")
def ext_servies() -> re.Pattern:
    source = GARDE.read_text(encoding="utf-8")
    motif = re.search(r"^const EXT_SERVIES = /(.+)/$", source, re.M)
    assert motif, "règle EXT_SERVIES introuvable dans verifier_build.mjs"
    return re.compile(motif.group(1).replace("\\\\", "\\"))


@pytest.mark.parametrize("appel", [
    "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    "https://a.tile.openstreetmap.org/1/2/3.png",
    "https://tile.openstreetmap.org/1/2/3.png",
    "https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
    "https://tiles.stadiamaps.com/tiles/alidade_smooth/{z}/{x}/{y}.png",
    "https://api.mapbox.com/styles/v1/mapbox/streets-v11/tiles/1/2/3",
])
def test_un_fond_tiers_est_pris(fonds_tiers, appel):
    assert fonds_tiers.search(appel)


@pytest.mark.parametrize("legitime", [
    # L'attribution ODbL EXIGE ce lien : le refuser rendrait le site impubliable.
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    # Une fiche a le droit de citer sa source. Un lien n'est pas une requête.
    '<a href="https://www.openstreetmap.org/node/2649841">Voir dans OSM</a>',
    '"source_url": "https://openstreetmap.org/way/12345"',
    # Le fond du site, servi depuis son propre domaine.
    "const url = `${base}/carte/fond.pmtiles`",
])
def test_ce_qui_n_est_pas_une_tuile_passe(fonds_tiers, legitime):
    """Un lien est une chose que le lecteur clique ; une tuile est une requête
    que son navigateur fait sans lui demander. Seule la seconde est refusée."""
    assert not fonds_tiers.search(legitime)


@pytest.mark.parametrize("fichier", [
    "_app/immutable/nodes/19.-b79t_5X.js",
    "urbanisme.html",
    "_app/immutable/assets/0.CqO6XeeC.css",
])
def test_le_controle_regarde_au_dela_du_html(ext_servies, fichier):
    """Le fond tiers ne vit pas dans le HTML mais dans le bundle que la page
    charge : c'est pour ça que le site du 29/08 paraissait propre."""
    assert ext_servies.search(fichier)


@pytest.mark.parametrize("fichier", ["carte/fond.pmtiles", "data/events.json"])
def test_les_donnees_ne_sont_pas_relues_pour_rien(ext_servies, fichier):
    assert not ext_servies.search(fichier)
