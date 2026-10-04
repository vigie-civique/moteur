"""Les unités systemd autorisent-elles ce que la publication écrit ?

`ProtectSystem=strict` rend tout l'arbre en lecture seule hors `ReadWritePaths`.
Deux défauts sont passés entre la publication et ses unités sans qu'aucun essai
ne parle des deux à la fois :

- l'atelier n'autorisait que `dashboard/static/api` (un ancien nom), la collecte
  rien sous `dashboard` : la promotion, qui remplace `dashboard/static/public_api`
  par renommage, tombait en lecture seule ;
- `publier-site.sh` régénérait aussi `dashboard/src/lib/instance.js`, que
  personne n'autorise en écriture : `Errno 30`, mise en ligne en échec.

Les chemins écrits sont lus dans `scripts/publication.py` lui-même (toute
constante `Path` sous la racine), pas recopiés ici : le prochain chemin qu'on y
ajoute est vérifié sans qu'il faille penser à ce fichier.

Ce que cet essai ne sait PAS dire : il lit les unités, il ne les fait pas
tourner. `systemd-analyze verify` et un `systemctl start` restent à jouer sur
le serveur (cf. la description de la PR qui l'a introduit).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import json
import os

import pytest

from montages import Montages, reloger

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Les modèles d'unité écrivent le chemin d'installation du serveur ; l'essai
# les ramène à la racine du dépôt pour comparer.
RACINE_SERVEUR = Path("/opt/vigie")
UNITES = ["atelier.service", "collecte.service"]


def _charger(nom: str, fichier: str):
    spec = importlib.util.spec_from_file_location(nom, ROOT / "scripts" / fichier)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def autorises(unite: str) -> list[Path]:
    """Les `ReadWritePaths` actifs d'une unité, ramenés sous la racine du dépôt.

    Les lignes commentées (`#ReadWritePaths=/srv/www/…`, la cible « local » à
    activer sur le serveur) n'autorisent rien : elles ne comptent pas. Le `-`
    initial rend un chemin facultatif, il n'en change pas la portée.
    """
    chemins = []
    for ligne in (ROOT / "deploy" / unite).read_text(encoding="utf-8").splitlines():
        if not ligne.startswith("ReadWritePaths="):
            continue
        for brut in ligne.split("=", 1)[1].split():
            chemin = Path(brut.lstrip("-"))
            if chemin.is_relative_to(RACINE_SERVEUR):
                chemins.append(ROOT / chemin.relative_to(RACINE_SERVEUR))
    return chemins


def couvert(chemin: Path, ouverts: list[Path]) -> bool:
    return any(chemin == o or chemin.is_relative_to(o) for o in ouverts)


@pytest.fixture(scope="module")
def publication():
    return _charger("publication_unites", "publication.py")


def chemins_ecrits(publication) -> dict[str, Path]:
    """Ce que la publication écrit, nommé par la constante qui le désigne."""
    ecrits = {nom: valeur for nom, valeur in vars(publication).items()
              if isinstance(valeur, Path) and nom != "ROOT"
              and valeur.is_relative_to(publication.ROOT)}
    # `basculer` met en service par renommage : écrire dans le PARENT de la
    # destination, sans quoi `rename` échoue en lecture seule. Ni un point de
    # montage ne se renomme, ni une unité n'a de raison de n'ouvrir que lui.
    for nom in ("PUBLIE", "SITE"):
        ecrits[f"parent de {nom}"] = ecrits[nom].parent
    return ecrits


@pytest.mark.parametrize("unite", UNITES)
def test_les_unites_autorisent_ce_que_la_publication_ecrit(publication, unite):
    ouverts = autorises(unite)
    refuses = {nom: str(chemin.relative_to(ROOT))
               for nom, chemin in chemins_ecrits(publication).items()
               if not couvert(chemin, ouverts)}
    assert not refuses, (
        f"deploy/{unite} : ReadWritePaths n'autorise pas {refuses} — sous "
        "ProtectSystem=strict, la publication y échouerait en lecture seule. "
        "Ajouter le chemin le plus étroit qui suffit, commenté par son pourquoi.")


def test_la_lecture_des_unites_trouve_bien_quelque_chose():
    """Garde de l'essai lui-même : un `ReadWritePaths` renommé ou un format
    changé feraient tout passer au vert en ne lisant rien."""
    for unite in UNITES:
        assert couvert(ROOT / "audits" / "x", autorises(unite)), unite


@pytest.mark.parametrize("unite", UNITES)
def test_le_code_du_tableau_de_bord_reste_en_lecture_seule(unite):
    """Ouvrir `dashboard/src` pour un `instance.js` a été la première réponse :
    elle laisse une faille de l'application réécrire le front de l'atelier."""
    code = ROOT / "dashboard" / "src" / "lib" / "instance.js"
    assert not couvert(code, autorises(unite))


def test_la_mise_en_ligne_ne_regenere_que_le_site():
    """`publier-site.sh` ne doit écrire que ce que son unité autorise."""
    gl = _charger("generer_libelles_unites", "generer_libelles.py")
    script = (ROOT / "deploy" / "publier-site.sh").read_text(encoding="utf-8")
    appels = [l for l in script.splitlines()
              if "generer_libelles.py" in l and not l.lstrip().startswith("#")]
    assert appels and all("--site" in l for l in appels), appels
    for unite in UNITES:
        ouverts = autorises(unite)
        assert all(couvert(c, ouverts) for c in gl.CIBLES_SITE), unite


def test_l_option_site_n_ecrit_pas_le_tableau_de_bord(tmp_path):
    """L'option doit tenir sa promesse, sinon l'unité refuse sans qu'on sache
    pourquoi : c'est le défaut d'origine. Les cibles sont redirigées vers un
    répertoire jetable ; la génération, elle, est la vraie."""
    gl = _charger("generer_libelles_option", "generer_libelles.py")
    site, atelier = tmp_path / "site.js", tmp_path / "atelier.js"
    gl.ROOT = tmp_path               # `main` affiche les chemins relativement à lui
    gl.CIBLES_SITE, gl.CIBLES = [site], [site, atelier]

    assert gl.main(["--site"]) == 0
    assert site.is_file() and not atelier.exists()

    assert gl.main([]) == 0          # sans option : les deux, comme à l'installation
    assert atelier.is_file()


@pytest.mark.parametrize("unite", UNITES)
def test_un_renommage_de_la_publication_ne_traverse_pas_deux_readwritepaths(
        publication, unite, tmp_path, monkeypatch):
    """Chaque `ReadWritePaths` est un montage « bind » à part : `rename(2)` de
    l'un à l'autre rend `EXDEV`, et hors de tous, `EROFS`. La promotion et le
    retour arrière sont joués sur un arbre dont les montages sont ceux de
    l'unité, les chemins ceux de `publication.py` : le renommage qui franchirait
    deux `ReadWritePaths` (le défaut du 04/10/2026) échoue ici, sans systemd.

    Ce que cet essai ne sait pas dire : il simule le code d'erreur du noyau, il
    ne monte rien — `test_bascule_entre_montages.py` joue de vrais montages
    quand l'exécuteur le permet, la commande `systemd-run` de la PR le joue
    sous l'unité."""
    racine = tmp_path / "vigie"
    lieux = reloger(publication, racine, monkeypatch)
    ouverts = [racine / o.relative_to(ROOT) for o in autorises(unite)]
    for o in ouverts:
        o.mkdir(parents=True, exist_ok=True)
    Montages(ouverts).installer(monkeypatch)

    def snap(dossier, marque, entites):
        (dossier / "entite").mkdir(parents=True)
        (dossier / "stats.json").write_text(json.dumps({"marque": marque}))
        for i in entites:
            (dossier / "entite" / f"{i}.json").write_text("{}")

    snap(lieux["BROUILLON"], "neuf", [1, 2])
    snap(lieux["PUBLIE"], "en ligne", [1])
    snap(lieux["SITE"], "en ligne", [1])
    ok = lambda cible: {"ok": True}

    with publication.verrou_de_publication():
        assert publication.basculer(lieux["BROUILLON"], lieux["PUBLIE"], ok)["ok"]
        assert publication.basculer(lieux["PUBLIE"], lieux["SITE"], ok)["ok"]
        for dest in (lieux["SITE"], lieux["PUBLIE"]):
            publication.revenir_a_la_version_precedente(dest)
    assert json.loads((lieux["SITE"] / "stats.json").read_text())["marque"] == "en ligne"
