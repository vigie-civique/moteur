"""Le flux de publication en deux temps : aperçu, contrôle, publication.

Ce que ces tests protègent tient en une phrase : **générer ne publie pas**.
Avant le 22/08/2026, un seul bouton construisait par-dessus le répertoire servi
puis synchronisait ; le contrôle d'étanchéité arrivait après l'écrasement, si
bien qu'un refus laissait en place non pas « l'ancien », comme l'annonçait le
message, mais le nouveau, non contrôlé.

Le builder et le contrôleur ont chacun leur suite (`test_publication.py`,
`test_verify_snapshot.py`) et leur épreuve de bout en bout (le job `site` de la
CI, qui construit un vrai snapshot depuis une vraie base). Ici on éprouve
l'ORCHESTRATION : quel répertoire est touché, à quel moment, et qui a le droit.
Le builder et le contrôleur y sont donc des fonctions passées en argument — ce
sont les points de contrôle du flux, pas son objet.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def publication():
    sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location(
        "publication_sous_test", ROOT / "scripts" / "publication.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def emplacements(publication, tmp_path, monkeypatch):
    """Les trois emplacements du flux, jetables.

    Aucun test ne doit pouvoir écrire dans le vrai `dashboard/static/public_api` :
    une suite qui publie pour de bon est une suite qu'on finit par ne plus lancer.
    """
    brouillon = tmp_path / "brouillon"
    publie = tmp_path / "publie"
    site = tmp_path / "site" / "public" / "static" / "data"
    for d in (brouillon, publie, site):
        d.mkdir(parents=True)
    monkeypatch.setattr(publication, "BROUILLON", brouillon)
    monkeypatch.setattr(publication, "PUBLIE", publie)
    monkeypatch.setattr(publication, "SITE", site)
    monkeypatch.setattr(publication, "ETAT", tmp_path / "etat.json")
    return {"brouillon": brouillon, "publie": publie, "site": site}


def snapshot(dossier: Path, entites: list[int], marque: str = "neuf") -> dict:
    """Un snapshot minimal mais réaliste : un index, des fiches, des stats."""
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "entite").mkdir(exist_ok=True)
    (dossier / "entities.json").write_text(json.dumps(
        {"entities": [{"id": i, "name": f"Acteur {i}", "confidence": "verified"}
                      for i in entites]}), encoding="utf-8")
    stats = {"entities_public": len(entites), "marque": marque, "exclusions": {}}
    (dossier / "stats.json").write_text(json.dumps(stats), encoding="utf-8")
    for i in entites:
        (dossier / "entite" / f"{i}.json").write_text(
            json.dumps({"entity": {"id": i}}), encoding="utf-8")
    return stats


def builder(entites: list[int], marque: str = "neuf"):
    return lambda out: snapshot(out, entites, marque)


def controle(ok: bool, violations: int = 0) -> dict:
    return {"ok": ok, "compte_erreurs": 0 if ok else violations,
            "compte_avertissements": 0, "erreurs": [], "avertissements": [],
            "fichiers": 3, "rapport": "OK" if ok else "ÉCHEC — ne pas publier."}


def empreinte(dossier: Path) -> dict[str, str]:
    return {str(f.relative_to(dossier)): f.read_text(encoding="utf-8")
            for f in sorted(dossier.rglob("*")) if f.is_file()}


# ── Générer un aperçu ne publie rien ─────────────────────────────────────────

def test_apercu_n_ecrit_que_dans_le_brouillon(publication, emplacements):
    """Le cœur du dispositif : après une génération, ce qui est servi est
    exactement ce qui l'était avant — au fichier près, au contenu près."""
    snapshot(emplacements["publie"], [1, 2], marque="en ligne")
    snapshot(emplacements["site"], [1, 2], marque="en ligne")
    avant_publie = empreinte(emplacements["publie"])
    avant_site = empreinte(emplacements["site"])

    publication.generer_apercu(auteur="essai",
                               builder=builder([1, 2, 3], marque="brouillon"),
                               controleur=lambda cible: controle(True))

    assert empreinte(emplacements["publie"]) == avant_publie
    assert empreinte(emplacements["site"]) == avant_site
    brouillon = json.loads((emplacements["brouillon"] / "stats.json").read_text())
    assert brouillon["marque"] == "brouillon" and brouillon["entities_public"] == 3


def test_apercu_n_ecrit_rien_dans_le_depot(publication, emplacements):
    """« Générer un aperçu » ne touche pas non plus au CODE du site.

    Une première version régénérait au passage `public/src/lib/instance.js`,
    les libellés de l'instance — hors du brouillon, dans le dépôt. La suite de
    tests s'est mise à réécrire les fichiers du dépôt en tournant, ce qui a
    signalé le vrai problème : une propriété assortie d'une exception n'est plus
    une propriété, et « l'aperçu ne touche à rien » doit se vérifier partout.
    """
    surveilles = [ROOT / "public" / "src" / "lib", ROOT / "dashboard" / "src" / "lib"]
    avant = {f: f.read_bytes() for d in surveilles for f in d.rglob("*.js")}

    publication.generer_apercu(builder=builder([1, 2]),
                               controleur=lambda cible: controle(True))

    assert {f: f.read_bytes() for d in surveilles for f in d.rglob("*.js")} == avant


def test_apercu_refuse_de_construire_dans_un_repertoire_servi(publication, emplacements):
    """La garantie ne repose pas sur la bonne volonté de l'appelant."""
    for servi in (emplacements["publie"], emplacements["site"]):
        with pytest.raises(publication.PublicationRefusee):
            publication.generer_apercu(cible=servi, builder=builder([1]),
                                       controleur=lambda cible: controle(True))


def test_apercu_rouge_reste_un_apercu(publication, emplacements):
    """Un contrôle en échec ne fait pas échouer la génération : l'aperçu existe,
    c'est son verdict qui est rouge — et c'est précisément ce qu'on voulait
    pouvoir regarder avant de publier."""
    resume = publication.generer_apercu(builder=builder([1]),
                                        controleur=lambda cible: controle(False, 12))
    assert resume["controle"]["ok"] is False
    assert publication.etape(publication.lire_etat()) == "controles_en_echec"


# ── Le contrôle commande la publication ──────────────────────────────────────

def test_controle_rouge_bloque_la_publication(publication, emplacements):
    snapshot(emplacements["publie"], [1], marque="en ligne")
    avant = empreinte(emplacements["publie"])
    publication.generer_apercu(builder=builder([1, 2], marque="brouillon"),
                               controleur=lambda cible: controle(False, 3))

    with pytest.raises(publication.PublicationRefusee) as refus:
        publication.publier(auteur="admin@exemple", role="admin",
                            controleur=lambda cible: controle(False, 3))

    assert "rien n'a été publié" in str(refus.value).lower()
    assert refus.value.detail["controle"]["compte_erreurs"] == 3
    assert empreinte(emplacements["publie"]) == avant


def test_controle_vert_autorise_la_publication_admin(publication, emplacements):
    snapshot(emplacements["publie"], [1], marque="en ligne")
    publication.generer_apercu(auteur="admin@exemple",
                               builder=builder([1, 2, 3], marque="brouillon"),
                               controleur=lambda cible: controle(True))

    publie = publication.publier(auteur="admin@exemple", role="admin",
                                 controleur=lambda cible: controle(True))

    assert publie["publie_par"] == "admin@exemple"
    assert publie["stats"]["marque"] == "brouillon"
    assert publie["differences"] == {}          # une copie ne change rien
    # Les deux emplacements servis portent le brouillon, à l'identique.
    for servi in ("publie", "site"):
        stats = json.loads((emplacements[servi] / "stats.json").read_text())
        assert stats["entities_public"] == 3
    assert publication.etape(publication.lire_etat()) == "publie"


def test_publier_retire_ce_qui_ne_doit_plus_sortir(publication, emplacements):
    """Publier est un MIROIR. Une fiche retirée de la publication disparaît des
    répertoires servis — c'est la fuite du 19/08/2026, où deux sites en ligne
    servaient encore les fiches d'entités écartées par le filtre."""
    snapshot(emplacements["publie"], [1, 2, 3], marque="en ligne")
    snapshot(emplacements["site"], [1, 2, 3], marque="en ligne")
    publication.generer_apercu(builder=builder([1], marque="brouillon"),
                               controleur=lambda cible: controle(True))

    publication.publier(auteur="admin@exemple", role="admin",
                        controleur=lambda cible: controle(True))

    for servi in ("publie", "site"):
        restantes = sorted(f.name for f in (emplacements[servi] / "entite").glob("*.json"))
        assert restantes == ["1.json"]


def test_publier_sans_apercu_refuse(publication, emplacements):
    with pytest.raises(publication.PublicationRefusee) as refus:
        publication.publier(auteur="admin@exemple", role="admin")
    assert "aucun aperçu" in str(refus.value).lower()


# ── Qui publie ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("role", ["validator", "contributor", None, "", "Admin"])
def test_non_admin_ne_publie_pas(publication, emplacements, role):
    snapshot(emplacements["publie"], [1], marque="en ligne")
    avant = empreinte(emplacements["publie"])
    publication.generer_apercu(builder=builder([1, 2], marque="brouillon"),
                               controleur=lambda cible: controle(True))

    with pytest.raises(publication.PublicationRefusee) as refus:
        publication.publier(auteur="quelquun", role=role,
                            controleur=lambda cible: controle(True))

    assert "admin" in str(refus.value).lower()
    assert empreinte(emplacements["publie"]) == avant


def test_le_role_est_declare_une_fois(publication):
    """L'API lit cette liste, elle ne la redéfinit pas : un droit écrit à deux
    endroits finit par diverger."""
    assert publication.ROLES_QUI_PUBLIENT == frozenset({"admin"})
    assert publication.peut_publier("admin") and not publication.peut_publier("validator")


# ── L'aperçu montre bien le brouillon ────────────────────────────────────────

@pytest.fixture
def port_libre(publication, monkeypatch):
    """Un numéro de port que personne n'occupe encore.

    Réservé puis relâché : le flux refuse de démarrer sur un port qui répond
    déjà, et un test qui garderait la socket ouverte éprouverait ce refus au
    lieu du démarrage.
    """
    import socket
    with socket.socket() as sonde:
        sonde.bind(("127.0.0.1", 0))
        port = sonde.getsockname()[1]
    monkeypatch.setattr(publication, "APERCU_PORT", port)
    return port


class FauxVite:
    """Un Vite qui écoute vraiment sur le port — ou qui vient de mourir.

    Le flux n'annonce un aperçu qu'une fois le port joignable ; un faux
    processus sans socket éprouverait l'inverse de ce qui est écrit.
    """

    def __init__(self, port=None, vivant=True):
        import socket
        self.vivant = vivant
        self.socket = None
        if vivant and port:
            self.socket = socket.socket()
            self.socket.bind(("127.0.0.1", port))
            self.socket.listen(1)

    def poll(self):
        return None if self.vivant else 1

    def terminate(self):
        self.vivant = False
        if self.socket:
            self.socket.close()
            self.socket = None

    def wait(self, timeout=None):
        return 0


def test_le_serveur_d_apercu_pointe_sur_le_brouillon(publication, emplacements,
                                                     port_libre, tmp_path, monkeypatch):
    """Le site public est lancé sur le BROUILLON, par la seule variable qui
    décide d'où il lit. Un aperçu branché sur le snapshot publié montrerait
    fidèlement... ce qui est déjà en ligne."""
    snapshot(emplacements["brouillon"], [1])
    snapshot(emplacements["publie"], [1, 2])
    lance = {}

    def faux_popen(cmd, cwd=None, env=None, **kw):
        lance.update(cmd=cmd, cwd=cwd, env=env)
        return FauxVite(port=port_libre)

    faux_vite = tmp_path / "vite"
    faux_vite.write_text("", encoding="utf-8")
    monkeypatch.setattr(publication.subprocess, "Popen", faux_popen)
    monkeypatch.setattr(publication, "_vite", lambda: faux_vite)

    etat = publication.demarrer_serveur_apercu()
    try:
        assert lance["env"]["VIGIE_DATA_DIR"] == str(emplacements["brouillon"])
        assert lance["env"]["VIGIE_DATA_DIR"] != str(emplacements["publie"])
        assert lance["cwd"].endswith("public")
        assert lance["cmd"][1] == "dev"
        assert etat["actif"] and etat["url"]
    finally:
        assert publication.arreter_serveur_apercu()["actif"] is False


def test_un_apercu_qui_ne_demarre_pas_se_dit(publication, emplacements, port_libre,
                                             tmp_path, monkeypatch):
    """Port déjà pris, dépendances cassées : Vite sort en une seconde. Rendre
    la main sur « c'est parti » afficherait une prévisualisation en marche
    devant un cadre vide."""
    snapshot(emplacements["brouillon"], [1])
    faux_vite = tmp_path / "vite"
    faux_vite.write_text("", encoding="utf-8")
    monkeypatch.setattr(publication, "_vite", lambda: faux_vite)
    monkeypatch.setattr(publication.subprocess, "Popen",
                        lambda *a, **kw: FauxVite(vivant=False))

    with pytest.raises(publication.PublicationRefusee) as refus:
        publication.demarrer_serveur_apercu()
    assert "n'a pas démarré" in str(refus.value)
    assert publication.etat_serveur_apercu()["actif"] is False


def test_un_port_deja_occupe_se_dit_avant_de_lancer_quoi_que_ce_soit(
        publication, emplacements, tmp_path, monkeypatch):
    """Une machine de collecte porte plusieurs instances, et leurs serveurs Vite
    s'empilent à partir de 5173. Lancer quand même afficherait dans l'atelier un
    aperçu qui montre le site d'à côté."""
    import socket
    snapshot(emplacements["brouillon"], [1])
    faux_vite = tmp_path / "vite"
    faux_vite.write_text("", encoding="utf-8")
    monkeypatch.setattr(publication, "_vite", lambda: faux_vite)
    monkeypatch.setattr(publication.subprocess, "Popen",
                        lambda *a, **kw: pytest.fail("rien ne devait être lancé"))
    with socket.socket() as occupant:
        occupant.bind(("127.0.0.1", 0))
        occupant.listen(1)
        monkeypatch.setattr(publication, "APERCU_PORT", occupant.getsockname()[1])
        with pytest.raises(publication.PublicationRefusee) as refus:
            publication.demarrer_serveur_apercu()
    assert "déjà occupé" in str(refus.value)


def test_le_serveur_d_apercu_refuse_de_montrer_un_repertoire_servi(
        publication, emplacements, tmp_path, monkeypatch):
    faux_vite = tmp_path / "vite"
    faux_vite.write_text("", encoding="utf-8")
    monkeypatch.setattr(publication, "_vite", lambda: faux_vite)
    snapshot(emplacements["publie"], [1])
    with pytest.raises(publication.PublicationRefusee):
        publication.demarrer_serveur_apercu(cible=emplacements["publie"])


def test_le_site_public_ne_code_plus_son_repertoire_de_donnees_en_dur(publication):
    """Chaque page prérendue lisait `join(process.cwd(), 'static', 'data')`, écrit
    trente fois. Une seule qui y revient, et l'aperçu montre un mélange de deux
    snapshots sans le dire — ce qui est pire que pas d'aperçu : on croirait
    avoir vérifié."""
    fautifs = [str(f.relative_to(ROOT))
               for f in (ROOT / "public" / "src" / "routes").rglob("*.js")
               if re.search(r"process\.cwd\(\)\s*,\s*'static'\s*,\s*'data'",
                            f.read_text(encoding="utf-8"))]
    assert fautifs == []


# ── Les cinq états, nommés ───────────────────────────────────────────────────

@pytest.mark.parametrize("etat,attendu", [
    ({}, "aucun_apercu"),
    ({"brouillon": {"genere_le": "t", "controle": {"ok": False}}}, "controles_en_echec"),
    ({"brouillon": {"genere_le": "t", "controle": {"ok": True}}}, "pret_a_publier"),
    ({"brouillon": {"genere_le": "t", "controle": {"ok": True}},
      "publie": {"apercu_genere_le": "t"}}, "publie"),
    ({"brouillon": {"genere_le": "t2", "controle": {"ok": True}},
      "publie": {"apercu_genere_le": "t1"}}, "pret_a_publier"),
])
def test_etapes(publication, etat, attendu):
    assert publication.etape(etat) == attendu
