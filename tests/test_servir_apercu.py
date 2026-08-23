"""L'aperçu sert l'artefact publiable, avec les règles de l'hébergeur.

Deux défauts d'un même geste, relevés le 23/08/2026.

L'aperçu de l'atelier lançait `vite dev` : rendu à la volée, modules non
groupés, aucun prérendu. Ce qui part en ligne est un build statique de 1 449
pages écrites par `adapter-static`, et c'est là que se logent les défauts qui
restent — une page qui rend bien en dev et se retrouve vide dans le HTML livré.
On prévisualisait la seule version du site qui ne sera jamais publiée.

Servir ce build demande les règles de résolution d'un hébergeur statique, et
l'ORDRE de ces règles n'est pas un détail : `adapter-static` écrit à la fois
`finances.html` (la page, 84 Ko) et `finances/__data.json` (ses données de
navigation). Un serveur qui regarde le répertoire d'abord trouve `finances/`,
n'y voit pas d'`index.html`, et sert un listing de 321 octets. Mesuré : c'est ce
qui s'est passé au premier essai, sur les six pages principales.
"""
from __future__ import annotations

import importlib.util
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def servir():
    spec = importlib.util.spec_from_file_location(
        "servir_apercu", ROOT / "scripts" / "servir_apercu.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def build(tmp_path):
    """Un build tel qu'`adapter-static` l'écrit, en miniature."""
    racine = tmp_path / "apercu_build"
    racine.mkdir()
    (racine / "index.html").write_text("<title>Accueil</title>", encoding="utf-8")
    (racine / "404.html").write_text("<title>Page introuvable</title>", encoding="utf-8")
    # La page ET son répertoire de données, comme sur le vrai build.
    (racine / "finances.html").write_text(
        "<title>Flux financiers</title>" + "x" * 5000, encoding="utf-8")
    (racine / "finances").mkdir()
    (racine / "finances" / "__data.json").write_text('{"type":"data"}', encoding="utf-8")
    (racine / "data").mkdir()
    (racine / "data" / "stats.json").write_text('{"entities_public": 3}', encoding="utf-8")
    (racine / "entite").mkdir()
    (racine / "entite" / "42.html").write_text("<title>Fiche 42</title>", encoding="utf-8")
    return racine


@pytest.fixture
def adresse(servir, build):
    """Le serveur, sur un port libre, arrêté à la fin du test."""
    import socketserver
    import functools

    handler = functools.partial(servir.Handler, directory=str(build))
    httpd = servir.Serveur(("127.0.0.1", 0), handler)
    fil = threading.Thread(target=httpd.serve_forever, daemon=True)
    fil.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def lire(url: str):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def test_une_url_sans_extension_sert_la_page(adresse):
    """Le cas qui tombait : `finances/` existe, `finances.html` aussi, et c'est
    la PAGE qu'il faut servir."""
    code, corps = lire(f"{adresse}/finances")
    assert code == 200
    assert "<title>Flux financiers</title>" in corps
    assert len(corps) > 4000, "un listing de répertoire a été servi à la place"


def test_la_racine_sert_laccueil(adresse):
    code, corps = lire(f"{adresse}/")
    assert code == 200 and "<title>Accueil</title>" in corps


def test_une_page_de_sous_repertoire(adresse):
    code, corps = lire(f"{adresse}/entite/42")
    assert code == 200 and "Fiche 42" in corps


def test_les_donnees_restent_accessibles(adresse):
    """Le site lit `/data/*.json` côté client : les servir en fait partie."""
    code, corps = lire(f"{adresse}/data/stats.json")
    assert code == 200 and json.loads(corps)["entities_public"] == 3


def test_le_repertoire_de_donnees_dune_page_reste_lisible(adresse):
    """`finances/__data.json` sert la navigation côté client de SvelteKit.
    Préférer la page ne doit pas rendre ce fichier inatteignable."""
    code, corps = lire(f"{adresse}/finances/__data.json")
    assert code == 200 and json.loads(corps)["type"] == "data"


def test_une_url_inconnue_rend_la_page_404_du_site(adresse):
    """Montrer la page d'erreur de Python laisserait croire à une panne du
    serveur là où il n'y a qu'un lien mort — et cacherait la vraie page 404,
    qui est du contenu comme un autre."""
    code, corps = lire(f"{adresse}/nexiste-pas")
    assert code == 404
    assert "<title>Page introuvable</title>" in corps


def test_aucun_listing_de_repertoire(adresse):
    """Un hébergeur statique n'en sert pas. En servir un donnerait un aperçu
    qui ne ressemble pas au site, et exposerait l'arborescence du build."""
    code, corps = lire(f"{adresse}/entite/")
    assert code == 404
    assert "42.html" not in corps
