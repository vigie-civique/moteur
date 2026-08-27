"""DECP et DVF partagent leurs gros téléchargements entre instances."""
from __future__ import annotations

import gzip
from datetime import date

import pytest


def test_decp_reutilise_le_fichier_du_magasin(tmp_path, monkeypatch):
    from collectors import marches_publics as marches

    monkeypatch.setattr(marches, "DECP_CACHE", tmp_path / "decp")
    appels = []

    class Reponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            appels.append(1)
            return b'{"marches":[]}'

    monkeypatch.setattr(marches.urllib.request, "urlopen", lambda *a, **k: Reponse())
    assert marches._telecharger_decp("https://example.test/decp", "decp-2025.json")
    assert marches._telecharger_decp("https://example.test/decp", "decp-2025.json")
    assert len(appels) == 1


def test_dvf_cerema_reutilise_la_reponse_du_magasin(tmp_path, monkeypatch):
    from collectors import dvf

    monkeypatch.setattr(dvf, "DVF_CACHE", tmp_path / "dvf")
    appels = []

    def fetch(*args, **kwargs):
        appels.append(1)
        return {"results": [{"date_mutation": "2025-01-01"}]}

    monkeypatch.setattr(dvf, "fetch_json", fetch)
    assert len(dvf.fetch_dvf_cerema("99001")) == 1
    assert len(dvf.fetch_dvf_cerema("99001")) == 1
    assert len(appels) == 1


def test_dvf_bulk_lit_les_departements_sans_reseau(tmp_path, monkeypatch):
    from collectors import dvf

    monkeypatch.setattr(dvf, "DVF_CACHE", tmp_path / "dvf")
    monkeypatch.setattr(dvf, "archive_fetch", lambda *a, **k: None)
    contenu = (
        "code_commune,date_mutation,valeur_fonciere,id_parcelle\n"
        "99001,2025-01-01,100000,99001000AB0001\n"
        "99002,2025-01-02,200000,99002000AB0002\n"
    ).encode()
    for annee in range(2020, date.today().year + 1):
        chemin = dvf.DVF_CACHE / "departements" / str(annee) / f"{dvf.DEPARTEMENT}.csv.gz"
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_bytes(gzip.compress(contenu))

    def reseau_interdit(*args, **kwargs):
        raise AssertionError("le magasin rempli ne doit pas appeler le réseau")

    monkeypatch.setattr(dvf.urllib.request, "urlopen", reseau_interdit)
    lignes = dvf.fetch_dvf_csv_bulk("99001")
    assert len(lignes) == date.today().year - 2019
    assert {ligne["code_commune"] for ligne in lignes} == {"99001"}


# ── Un magasin en lecture seule ne fait pas échouer une collecte ──────────────
#
# Le magasin est partagé : il peut appartenir à une autre instance, vivre sur un
# support monté en lecture seule, ou simplement avoir été rempli par quelqu'un
# d'autre. C'est un CACHE. Ne pas pouvoir y écrire n'enlève rien à ce qui vient
# d'être téléchargé.


@pytest.fixture
def magasin_en_lecture_seule(tmp_path):
    """Rend un dossier où rien ne peut être créé, et le rouvre après le test."""
    racine = tmp_path / "magasin"
    racine.mkdir()
    yield racine
    for chemin in [racine, *racine.rglob("*")]:
        try:
            chemin.chmod(0o700)
        except OSError:
            pass


def test_ecrire_atomiquement_rend_faux_au_lieu_de_lever(magasin_en_lecture_seule):
    from collectors.national_store import ecrire_atomiquement

    magasin_en_lecture_seule.chmod(0o500)
    assert ecrire_atomiquement(magasin_en_lecture_seule / "x" / "y.json", b"{}") is False


def test_decp_lit_un_cache_deja_rempli_dans_un_magasin_ferme(
    magasin_en_lecture_seule, monkeypatch
):
    """Lire un magasin qu'on ne peut pas écrire est le cas NORMAL du partage.

    Celui-ci passait déjà : ``mkdir(exist_ok=True)`` sur un dossier existant ne
    lève pas, même sous un parent fermé. Il reste ici parce que c'est la
    propriété que le magasin promet — une instance qui n'alimente pas doit
    quand même se servir, sans réseau.
    """
    from collectors import marches_publics as marches

    cache = magasin_en_lecture_seule / "decp"
    cache.mkdir()
    (cache / "decp-2025.json").write_bytes(b'{"marches":[]}')
    cache.chmod(0o500)
    magasin_en_lecture_seule.chmod(0o500)
    monkeypatch.setattr(marches, "DECP_CACHE", cache)

    def reseau_interdit(*args, **kwargs):
        raise AssertionError("le fichier est là : rien à télécharger")

    monkeypatch.setattr(marches.urllib.request, "urlopen", reseau_interdit)
    assert marches._telecharger_decp("https://example.test/decp", "decp-2025.json")


def test_decp_rend_le_contenu_que_le_magasin_refuse(
    magasin_en_lecture_seule, monkeypatch
):
    """Contenu en main + écriture refusée = collecte réussie, sans réessai."""
    from collectors import marches_publics as marches

    magasin_en_lecture_seule.chmod(0o500)
    monkeypatch.setattr(marches, "DECP_CACHE", magasin_en_lecture_seule / "decp")
    appels = []

    class Reponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            appels.append(1)
            return b'{"marches":[]}'

    monkeypatch.setattr(marches.urllib.request, "urlopen", lambda *a, **k: Reponse())
    monkeypatch.setattr(marches.time, "sleep", lambda *a: None)
    assert marches._telecharger_decp("https://example.test/decp", "decp-2025.json") == b'{"marches":[]}'
    assert len(appels) == 1


def test_dvf_cerema_rend_ses_mutations_quand_le_magasin_refuse(
    magasin_en_lecture_seule, monkeypatch
):
    """L'écriture qui levait renvoyait une liste VIDE : une perte silencieuse."""
    from collectors import dvf

    magasin_en_lecture_seule.chmod(0o500)
    monkeypatch.setattr(dvf, "DVF_CACHE", magasin_en_lecture_seule / "dvf")
    monkeypatch.setattr(
        dvf, "fetch_json", lambda *a, **k: {"results": [{"date_mutation": "2025-01-01"}]}
    )
    assert len(dvf.fetch_dvf_cerema("99001")) == 1


def test_dvf_bulk_ne_retelecharge_pas_quand_le_magasin_refuse(
    magasin_en_lecture_seule, monkeypatch
):
    """Un refus d'écriture relançait trois fois un fichier de plusieurs centaines de Mo."""
    from collectors import dvf

    magasin_en_lecture_seule.chmod(0o500)
    monkeypatch.setattr(dvf, "DVF_CACHE", magasin_en_lecture_seule / "dvf")
    monkeypatch.setattr(dvf, "archive_fetch", lambda *a, **k: None)
    monkeypatch.setattr(dvf.time, "sleep", lambda *a: None)
    contenu = (
        "code_commune,date_mutation,valeur_fonciere,id_parcelle\n"
        "99001,2025-01-01,100000,99001000AB0001\n"
    ).encode()
    appels = []

    class Reponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            appels.append(1)
            return gzip.compress(contenu)

    monkeypatch.setattr(dvf.urllib.request, "urlopen", lambda *a, **k: Reponse())
    lignes = dvf.fetch_dvf_csv_bulk("99001")
    annees = date.today().year - 2019
    assert len(lignes) == annees
    assert len(appels) == annees
