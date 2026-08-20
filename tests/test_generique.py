"""Le contrôle qui interdit au moteur de connaître une commune.

Il sert d'admission au kit : s'il se trompe, une particularité locale part dans
l'archive distribuée. Il s'est déjà trompé — jusqu'au 15/08/2026 il ne cherchait
que les communes de l'instance COURANTE, et annonçait donc « aucune
particularité locale » sur deux instances dont le code nommait 96 fois la
commune d'origine.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def vg():
    spec = importlib.util.spec_from_file_location(
        "verifier_generique", ROOT / "scripts" / "verifier_generique.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _analyser(vg, tmp_path, source: str, communes=frozenset()):
    f = tmp_path / "collecteur.py"
    f.write_text(source, encoding="utf-8")
    monkey = vg.ROOT
    vg.ROOT = tmp_path
    try:
        return vg.analyser(f, set(communes))
    finally:
        vg.ROOT = monkey


# ── Le moteur ne doit pas dépendre de l'instance courante ────────────────────

def test_les_communes_de_reference_sont_toujours_refusees(vg):
    """Même sur une instance qui ne les connaît pas."""
    noms = vg.communes_locales()
    assert "Lasalle" in noms, "la commune d'origine doit rester refusée partout"
    assert "Testonville" in noms, "celles de l'instance courante aussi"


def test_commune_supplementaire_prise_en_compte(vg):
    assert "Quelquepart" in vg.communes_locales({"Quelquepart"})


# ── Les formes interdites (exhaustives, indépendantes des noms) ──────────────

def test_code_insee_litteral_detecte(vg, tmp_path):
    c = _analyser(vg, tmp_path, 'URL = "https://api.example.org/communes/30140"\n'
                                'INSEE = "30140"\n')
    assert any(x["motif"] == "code_insee" for x in c)


def test_siren_litteral_detecte(vg, tmp_path):
    c = _analyser(vg, tmp_path, 'SIREN = "213001407"\n')
    assert any(x["motif"] == "siren_siret" for x in c)


def test_identifiant_de_ligne_detecte(vg, tmp_path):
    """`COMMUNE_ID = 63` : un numéro de ligne pris pour une constante."""
    c = _analyser(vg, tmp_path, "COMMUNE_ID = 63\n")
    assert any(x["motif"] == "identifiant_fige" for x in c)


def test_base_nommee_detectee(vg, tmp_path):
    c = _analyser(vg, tmp_path, 'CHEMIN = "db/lasalle.db"\n')
    assert any(x["motif"] == "base_nommee" for x in c)


def test_site_officiel_detecte(vg, tmp_path):
    c = _analyser(vg, tmp_path, 'SITE = "https://mairie-quelquepart.fr/actes"\n')
    assert any(x["motif"] == "site_officiel" for x in c)


def test_api_nationale_toleree(vg, tmp_path):
    """Nommer data.gouv.fr, c'est le propre du moteur."""
    c = _analyser(vg, tmp_path, 'API = "https://geo.api.gouv.fr/communes"\n')
    assert not any(x["motif"] == "site_officiel" for x in c)


def test_extension_db_seule_toleree(vg, tmp_path):
    """`".db"` figure légitimement dans une liste de suffixes à exclure."""
    c = _analyser(vg, tmp_path, 'SUFFIXES = (".db", ".pyc")\n')
    assert not any(x["motif"] == "base_nommee" for x in c)


# ── Docstrings : documenter un piège n'est pas le commettre ──────────────────

def test_nom_en_docstring_ignore(vg, tmp_path):
    source = '"""Ce module a longtemps nommé Lasalle en dur."""\nX = 1\n'
    assert _analyser(vg, tmp_path, source, {"Lasalle"}) == []


def test_nom_dans_une_chaine_executee_detecte(vg, tmp_path):
    source = 'ETIQUETTE = "Commune de Lasalle"\n'
    c = _analyser(vg, tmp_path, source, {"Lasalle"})
    assert any(x["motif"] == "nom_commune" for x in c)


# ── Le moteur réel doit rester propre ────────────────────────────────────────

def test_le_moteur_ne_nomme_aucune_commune(vg):
    """Le test qui garde l'acquis : 40 occurrences le 15/08/2026, 0 depuis."""
    communes = vg.communes_locales()
    constats = [c for f in vg._fichiers(vg.MOTEUR) for c in vg.analyser(f, communes)]
    constats += [c for f in vg._fichiers_texte() for c in vg.analyser_texte(f, communes)]
    assert constats == [], "\n".join(
        f"{c['fichier']}:{c['ligne']} {c['explication']}" for c in constats[:20])


def test_un_identifiant_fige_est_refuse_aussi_hors_python(tmp_path):
    """La règle 5 ne s'appliquait qu'au Python : le site y échappait.

    `const COMMUNE_ID = 63` vivait dans la page des flux financiers. Sur toute
    base où la commune ne porte pas ce numéro — c'est-à-dire toutes sauf celle
    d'origine — la page affichait « reçu 0 € / versé 0 € » avec des données
    pourtant publiées, et sans erreur pour le signaler.
    """
    from scripts.verifier_generique import analyser_texte

    f = tmp_path / "page.svelte"
    f.write_text("<script>\n  const COMMUNE_ID = 63\n</script>\n", encoding="utf-8")
    constats = analyser_texte(f, set())
    assert any(c["motif"] == "identifiant_fige" for c in constats), \
        "un identifiant de ligne figé dans un composant doit être refusé"


def test_une_constante_metier_n_est_pas_prise_pour_un_identifiant(tmp_path):
    """Le seuil est bas exprès, mais il ne doit pas mordre à tort : une année,
    un seuil en euros ou un délai ne s'appellent pas `_ID`."""
    from scripts.verifier_generique import analyser_texte

    f = tmp_path / "page.svelte"
    f.write_text("<script>\n  const ANNEE_MIN = 2018\n  const SEUIL_EUROS = 40000\n"
                 "  const TTL = 300\n</script>\n", encoding="utf-8")
    assert not [c for c in analyser_texte(f, set()) if c["motif"] == "identifiant_fige"]
