"""DECP et DVF partagent leurs gros téléchargements entre instances."""
from __future__ import annotations

import gzip
import io
import json
from datetime import date

import pytest


class ReponseFactice(io.BytesIO):
    """Une réponse HTTP se lit en flux et se ferme : `copier_atomiquement` la
    consomme par blocs, elle n'est jamais rendue d'un bloc."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_decp_reutilise_le_fichier_du_magasin(tmp_path, monkeypatch):
    pytest.importorskip("ijson", reason="job « tests-deps »")
    from collectors import marches_publics as marches

    monkeypatch.setattr(marches, "DECP_CACHE", tmp_path / "decp")
    appels = []

    def urlopen(*a, **k):
        appels.append(1)
        return ReponseFactice(b'{"marches":[]}')

    monkeypatch.setattr(marches.urllib.request, "urlopen", urlopen)
    for _ in range(2):
        with marches._consolide_decp("https://example.test/decp", "decp-2025.json") as chemin:
            assert chemin is not None and chemin.read_bytes() == b'{"marches":[]}'
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
    pytest.importorskip("ijson", reason="job « tests-deps »")
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
    with marches._consolide_decp("https://example.test/decp", "decp-2025.json") as chemin:
        assert chemin is not None and chemin.read_bytes() == b'{"marches":[]}'


def test_decp_rend_le_contenu_que_le_magasin_refuse(
    magasin_en_lecture_seule, monkeypatch
):
    """Contenu en main + écriture refusée = collecte réussie, sans réessai."""
    pytest.importorskip("ijson", reason="job « tests-deps »")
    from collectors import marches_publics as marches

    magasin_en_lecture_seule.chmod(0o500)
    monkeypatch.setattr(marches, "DECP_CACHE", magasin_en_lecture_seule / "decp")
    appels = []

    def urlopen(*a, **k):
        appels.append(1)
        return ReponseFactice(b'{"marches":[]}')

    monkeypatch.setattr(marches.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(marches.time, "sleep", lambda *a: None)
    with marches._consolide_decp("https://example.test/decp", "decp-2025.json") as chemin:
        assert chemin is not None and chemin.read_bytes() == b'{"marches":[]}'
        # Le fichier vit hors du magasin fermé : ailleurs, mais lisible.
        temporaire = chemin
    assert not temporaire.exists(), "le temporaire doit disparaître à la sortie"
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


# ── Un consolidé DECP se lit en flux, jamais d'un bloc ───────────────────────
#
# `decp-2019.json` pèse 944 Mo pour 803 487 marchés. `json.loads` en demandait
# 5,31 Go — 5,6 fois le fichier — ce qui faisait du step `marches` le poste le
# plus gourmand d'une collecte entière, devant le build du site. Sur un serveur
# à 4 Go, la collecte échouait faute de mémoire.


CONSOLIDE_TABLEAU = b"""{"marches": [
  {"id": "A", "acheteur": {"id": "21300140700011", "nom": "Commune"}, "montant": 1000.5},
  {"id": "B", "acheteur": {"id": "99999999900011", "nom": "Ailleurs"}, "montant": 2000}
]}"""

CONSOLIDE_OBJET = b"""{"marches": {"marche": [
  {"id": "C", "acheteur": {"id": "21300140700011", "nom": "Commune"}, "montant": 3000},
  {"id": "D", "acheteur": {"id": "99999999900011", "nom": "Ailleurs"}, "montant": 4000}
]}}"""


@pytest.mark.parametrize("contenu,attendu", [
    (CONSOLIDE_TABLEAU, "A"),
    (CONSOLIDE_OBJET, "C"),
])
def test_les_deux_formes_de_consolide_sont_lues(tmp_path, monkeypatch, contenu, attendu):
    """`{"marches": [...]}` en 2019, `{"marches": {"marche": [...]}}` depuis 2024.

    Le préfixe ijson diffère : une seule forme reconnue, et le collecteur rendrait
    zéro marché sans rien signaler — le pire des résultats.
    """
    pytest.importorskip("ijson", reason="job « tests-deps »")
    from collectors import marches_publics as marches

    cache = tmp_path / "decp"
    cache.mkdir()
    (cache / "decp.json").write_bytes(contenu)
    monkeypatch.setattr(marches, "DECP_CACHE", cache)
    monkeypatch.setattr(marches, "COMMUNE_SIREN", "213001407")
    monkeypatch.setattr(marches, "CAC_SIREN", "200070316")
    monkeypatch.setattr(marches, "ACHETEUR_JETONS", ())

    trouves = marches.extract_marches_from_file("https://example.test/x", "decp.json")
    assert [m["id"] for m in trouves] == [attendu]


def test_les_montants_restent_des_nombres_ordinaires(tmp_path, monkeypatch):
    """ijson rend des Decimal par défaut : ni SQLite ni json.dumps n'en veulent.

    Le défaut ne se verrait pas ici mais beaucoup plus loin, à l'écriture.
    """
    pytest.importorskip("ijson", reason="job « tests-deps »")
    from collectors import marches_publics as marches

    cache = tmp_path / "decp"
    cache.mkdir()
    (cache / "decp.json").write_bytes(CONSOLIDE_TABLEAU)
    monkeypatch.setattr(marches, "DECP_CACHE", cache)
    monkeypatch.setattr(marches, "COMMUNE_SIREN", "213001407")
    monkeypatch.setattr(marches, "CAC_SIREN", "200070316")
    monkeypatch.setattr(marches, "ACHETEUR_JETONS", ())

    montant = marches.extract_marches_from_file("https://example.test/x", "decp.json")[0]["montant"]
    assert isinstance(montant, float)
    json.dumps({"montant": montant})     # ce que fait la suite du collecteur


def test_la_memoire_ne_suit_pas_la_taille_du_fichier(tmp_path, monkeypatch):
    """La propriété qui justifie tout le changement : lire 100 fois plus gros ne
    coûte pas 100 fois plus de mémoire.

    Mesuré par `tracemalloc` sur le tas Python, seul endroit où vivaient les
    5,31 Go : les tampons `bytes`/`str` du fichier entier, puis son arbre
    d'objets. Le seuil est large — on vérifie un ORDRE DE GRANDEUR, pas un
    chiffre : ce test doit rougir si quelqu'un rétablit un `read()` global, pas
    parce qu'une version d'ijson garde quelques kilo-octets de plus.
    """
    pytest.importorskip("ijson", reason="job « tests-deps »")
    import tracemalloc
    from collectors import marches_publics as marches

    cache = tmp_path / "decp"
    cache.mkdir()
    remplissage = [
        {"id": f"X{i}", "acheteur": {"id": "99999999900011", "nom": "Ailleurs"},
         "objet": "libellé de remplissage " * 20}
        for i in range(20_000)
    ]
    gros = {"marches": [
        {"id": "A", "acheteur": {"id": "21300140700011", "nom": "Commune"}},
        *remplissage,
    ]}
    fichier = cache / "decp.json"
    fichier.write_text(json.dumps(gros), encoding="utf-8")
    taille = fichier.stat().st_size
    assert taille > 5_000_000, "l'épreuve n'a de sens que sur un gros fichier"

    monkeypatch.setattr(marches, "DECP_CACHE", cache)
    monkeypatch.setattr(marches, "COMMUNE_SIREN", "213001407")
    monkeypatch.setattr(marches, "CAC_SIREN", "200070316")
    monkeypatch.setattr(marches, "ACHETEUR_JETONS", ())

    tracemalloc.start()
    trouves = marches.extract_marches_from_file("https://example.test/x", "decp.json")
    _, pic = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert [m["id"] for m in trouves] == ["A"]
    assert pic < taille / 4, (
        f"pic de {pic / 1e6:.1f} Mo pour un fichier de {taille / 1e6:.1f} Mo : "
        "le consolidé est de nouveau chargé d'un bloc"
    )
