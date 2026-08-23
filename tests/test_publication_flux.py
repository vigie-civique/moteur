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
    # « Promu localement », pas « publié » : le build et la mise en ligne
    # restent à faire, et l'atelier ne les fait pas.
    assert publication.etape(publication.lire_etat()) == "promu_localement"


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


@pytest.fixture
def build_dapercu(publication, tmp_path, monkeypatch):
    """Un build déjà là, pour les tests qui portent sur le SERVEUR.

    Construire pour de vrai demanderait `npm` et une minute par test ; ce qui
    s'éprouve ici, c'est ce que l'atelier lance et sur quoi il le lance.
    """
    build = tmp_path / "apercu_build"
    build.mkdir()
    (build / "index.html").write_text("<h1>aperçu</h1>", encoding="utf-8")
    monkeypatch.setattr(publication, "APERCU_BUILD", build)
    faux_vite = tmp_path / "vite"
    faux_vite.write_text("", encoding="utf-8")
    monkeypatch.setattr(publication, "_vite", lambda: faux_vite)
    return build


def test_le_serveur_d_apercu_sert_le_build_du_brouillon(
        publication, emplacements, port_libre, build_dapercu, monkeypatch):
    """Ce qui est servi est l'ARTEFACT, pas le serveur de développement.

    Avant le 23/08/2026, l'aperçu lançait `vite dev` : rendu à la volée,
    modules non groupés, aucun prérendu. Ce qui part en ligne est un build
    statique de 1 449 pages, et c'est là que se logent les défauts qui restent.
    On prévisualisait la seule version du site qui ne sera jamais publiée.
    """
    snapshot(emplacements["brouillon"], [1])
    snapshot(emplacements["publie"], [1, 2])
    lance = {}
    construit = {}

    def faux_popen(cmd, cwd=None, env=None, **kw):
        lance.update(cmd=cmd, cwd=cwd, env=env)
        return FauxVite(port=port_libre)

    monkeypatch.setattr(publication.subprocess, "Popen", faux_popen)
    monkeypatch.setattr(publication, "construire_apercu",
                        lambda cible=None: construit.update(cible=cible))

    etat = publication.demarrer_serveur_apercu()
    try:
        # Construit sur le brouillon, jamais sur ce qui est déjà servi.
        assert construit["cible"] == emplacements["brouillon"]
        # Servi par le serveur statique du dépôt, pas par Vite.
        assert lance["cmd"][1].endswith("servir_apercu.py")
        assert lance["cmd"][2] == str(build_dapercu)
        assert etat["actif"] and etat["url"]
        assert etat["build"]["existe"] is True
    finally:
        assert publication.arreter_serveur_apercu()["actif"] is False


def test_un_build_dapercu_qui_echoue_ne_se_montre_pas(publication, emplacements,
                                                      build_dapercu, monkeypatch):
    """Un build rouge est un défaut de l'artefact publiable, pas de l'atelier :
    il n'y a rien à montrer tant qu'il n'est pas corrigé. Servir le build
    PRÉCÉDENT serait pire — on croirait regarder ses corrections."""
    snapshot(emplacements["brouillon"], [1])

    def build_rouge(cible=None):
        raise publication.PublicationRefusee("Le build de l'aperçu a échoué")

    # Le port de la machine qui fait tourner les tests n'a rien à voir avec ce
    # qu'on éprouve ici : l'atelier du développeur occupe souvent 5180.
    monkeypatch.setattr(publication, "_port_repond", lambda: False)
    monkeypatch.setattr(publication, "construire_apercu", build_rouge)
    monkeypatch.setattr(publication.subprocess, "Popen",
                        lambda *a, **kw: pytest.fail("rien ne devait être servi"))

    with pytest.raises(publication.PublicationRefusee) as refus:
        publication.demarrer_serveur_apercu()
    assert "build" in str(refus.value).lower()


def test_un_apercu_qui_ne_demarre_pas_se_dit(publication, emplacements, port_libre,
                                             build_dapercu, monkeypatch):
    """Le serveur peut sortir en une seconde. Rendre la main sur « c'est parti »
    afficherait une prévisualisation en marche devant un cadre vide."""
    snapshot(emplacements["brouillon"], [1])
    monkeypatch.setattr(publication, "construire_apercu", lambda cible=None: None)
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
    # Le build non plus : construire 1 449 pages pour découvrir ensuite que le
    # port est pris ferait attendre une minute pour rien.
    monkeypatch.setattr(publication, "construire_apercu",
                        lambda cible=None: pytest.fail("rien ne devait être construit"))
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
#
# `publie` s'appelle désormais `promu_localement`, et un cinquième état
# s'ajoute derrière : `en_ligne`. Le mot « publié » recouvrait les deux — la
# page annonçait « Ce qui est publié », puis précisait plus bas que le build et
# la mise en ligne restaient à faire. Un exploitant qui lit « publié » et ferme
# l'onglet croit son site à jour.
#
# Le dernier état ne se déduit pas : l'atelier ne fait ni le build ni le
# déploiement. Il demande une CONSTATATION — le site public interrogé sert bien
# l'empreinte promue.

@pytest.mark.parametrize("etat,attendu", [
    ({}, "aucun_apercu"),
    ({"brouillon": {"genere_le": "t", "controle": {"ok": False}}}, "controles_en_echec"),
    ({"brouillon": {"genere_le": "t", "controle": {"ok": True}}}, "pret_a_publier"),
    # Promu localement : les répertoires servis portent l'aperçu, et personne
    # n'a encore constaté quoi que ce soit en ligne.
    ({"brouillon": {"genere_le": "t", "controle": {"ok": True}},
      "publie": {"apercu_genere_le": "t"}}, "promu_localement"),
    ({"brouillon": {"genere_le": "t2", "controle": {"ok": True}},
      "publie": {"apercu_genere_le": "t1"}}, "pret_a_publier"),
    # En ligne : une vérification HTTP a trouvé l'empreinte promue.
    ({"brouillon": {"genere_le": "t", "controle": {"ok": True}},
      "publie": {"apercu_genere_le": "t", "empreinte": "abc"},
      "en_ligne": {"ok": True, "empreinte": "abc"}}, "en_ligne"),
    # Une vérification verte sur une AUTRE empreinte ne vaut rien : c'est le
    # déploiement d'avant qu'elle a constaté.
    ({"brouillon": {"genere_le": "t", "controle": {"ok": True}},
      "publie": {"apercu_genere_le": "t", "empreinte": "neuve"},
      "en_ligne": {"ok": True, "empreinte": "ancienne"}}, "promu_localement"),
    # Site injoignable : promu, pas en ligne.
    ({"brouillon": {"genere_le": "t", "controle": {"ok": True}},
      "publie": {"apercu_genere_le": "t", "empreinte": "abc"},
      "en_ligne": {"ok": False, "motif": "Site injoignable"}}, "promu_localement"),
])
def test_etapes(publication, etat, attendu):
    assert publication.etape(etat) == attendu


def test_chaque_etape_porte_un_libelle(publication):
    """Un état sans phrase est un état que l'interface devra traduire seule,
    et deux traductions divergentes valent deux vérités."""
    assert set(publication.LIBELLES_ETAPES) == set(publication.ETAPES)
    assert all(publication.LIBELLES_ETAPES[e].strip() for e in publication.ETAPES)


def test_le_repertoire_servi_declare_la_version_quil_sert(publication, emplacements):
    """`version.json` est la seule pièce qui permette de constater, de
    l'extérieur, ce que le site déployé sert réellement."""
    publication.generer_apercu(builder=builder([1, 2]),
                               controleur=lambda cible: controle(True))
    publie = publication.publier(auteur="admin@exemple", role="admin",
                                 controleur=lambda cible: controle(True))

    for servi in ("publie", "site"):
        declare = json.loads(
            (emplacements[servi] / "version.json").read_text(encoding="utf-8"))
        assert declare["empreinte"] == publie["empreinte"]


def test_lempreinte_ne_depend_pas_du_fichier_qui_la_declare(publication, tmp_path):
    """Sinon elle serait circulaire : écrire l'empreinte changerait l'empreinte."""
    a = tmp_path / "a"
    snapshot(a, [1])
    avant = publication.empreinte(a)
    (a / "version.json").write_text('{"empreinte": "peu importe"}', encoding="utf-8")
    assert publication.empreinte(a) == avant


def test_verification_en_ligne_sans_adresse_declaree(publication, emplacements,
                                                     monkeypatch):
    """Une instance de test n'a pas de site public : l'atelier doit le dire,
    pas inventer une URL ni afficher un état vert."""
    monkeypatch.setattr(publication, "site_url", lambda: None)
    verdict = publication.verifier_en_ligne()
    assert verdict["ok"] is False
    assert "aucune adresse publique" in verdict["motif"].lower()


def test_une_verification_perimee_ne_passe_pas_pour_verte(publication, emplacements,
                                                          monkeypatch):
    """Publier de nouveau invalide la constatation précédente : elle portait sur
    la version d'avant."""
    monkeypatch.setattr(publication, "site_url", lambda: None)
    publication.generer_apercu(builder=builder([1]),
                               controleur=lambda cible: controle(True))
    publication.publier(auteur="admin@exemple", role="admin",
                        controleur=lambda cible: controle(True))
    etat = publication.lire_etat()
    etat["en_ligne"] = {"ok": True, "empreinte": "dune-autre-fois",
                        "empreinte_attendue": "dune-autre-fois"}
    publication.ecrire_etat(etat)

    vu = publication.etat_publication()

    assert vu["etape"] == "promu_localement"
    assert vu["en_ligne"]["perimee"] is True
    assert vu["en_ligne"]["ok"] is False


# ── La mise en service est atomique ──────────────────────────────────────────
#
# Jusqu'au 23/08/2026, `publier()` recopiait les fichiers un par un DANS le
# répertoire servi, puis contrôlait le résultat. Trois conséquences, toutes
# vérifiables ci-dessous :
#
#   — un contrôle rouge trouvait l'ancien snapshot déjà à moitié écrasé, sans
#     rien pour revenir en arrière, et le message « le site public est
#     inchangé » était faux au moment où il s'affichait ;
#   — un visiteur tombant pendant la copie voyait un site mi-ancien mi-neuf ;
#   — deux publications simultanées se recouvraient sans que rien ne le dise.


def test_un_controle_rouge_a_la_copie_laisse_la_version_precedente_entiere(
        publication, emplacements):
    """Le cas qui n'avait pas de filet : l'aperçu passe, la copie échoue.

    C'est le seul moment où le contrôleur peut dire non alors que tout allait
    bien une seconde plus tôt — et c'est précisément là que l'ancien snapshot
    se retrouvait à moitié remplacé.
    """
    snapshot(emplacements["publie"], [1, 2, 3], marque="en ligne")
    avant = empreinte(emplacements["publie"])
    publication.generer_apercu(builder=builder([9], marque="brouillon"),
                               controleur=lambda cible: controle(True))

    # Vert sur le brouillon, rouge sur la copie.
    def controleur(cible):
        return controle(Path(cible).resolve() == emplacements["brouillon"].resolve())

    with pytest.raises(publication.PublicationRefusee) as refus:
        publication.publier(auteur="admin@exemple", role="admin",
                            controleur=controleur)

    assert "précédente reste servie" in str(refus.value)
    assert empreinte(emplacements["publie"]) == avant, \
        "le répertoire servi a été touché alors que le contrôle a refusé"


def test_rien_ne_traine_a_cote_du_repertoire_servi(publication, emplacements):
    """Le répertoire de travail ne doit pas survivre à un refus : il porte des
    données non contrôlées, à côté de données servies."""
    snapshot(emplacements["publie"], [1], marque="en ligne")
    publication.generer_apercu(builder=builder([9], marque="brouillon"),
                               controleur=lambda cible: controle(True))

    with pytest.raises(publication.PublicationRefusee):
        publication.publier(
            auteur="admin@exemple", role="admin",
            controleur=lambda cible: controle(
                Path(cible).resolve() == emplacements["brouillon"].resolve()))

    publie = emplacements["publie"]
    assert not (publie.parent / f".{publie.name}.neuf").exists()


def test_la_version_precedente_est_conservee_et_peut_reprendre_du_service(
        publication, emplacements):
    """Un contrôle vert ne dit pas qu'une version est BONNE : il dit qu'elle est
    étanche. Un chiffre faux, un découpage raté, une page vide passent le
    contrôle. Quelqu'un doit pouvoir revenir sans reconstruire."""
    snapshot(emplacements["publie"], [1, 2, 3], marque="en ligne")
    snapshot(emplacements["site"], [1, 2, 3], marque="en ligne")
    publication.generer_apercu(builder=builder([7], marque="brouillon"),
                               controleur=lambda cible: controle(True))
    publication.publier(auteur="admin@exemple", role="admin",
                        controleur=lambda cible: controle(True))
    assert json.loads((emplacements["publie"] / "stats.json").read_text())["marque"] == "brouillon"

    publication.revenir_a_la_version_precedente(emplacements["publie"])

    stats = json.loads((emplacements["publie"] / "stats.json").read_text())
    assert stats["marque"] == "en ligne"
    assert sorted(f.name for f in (emplacements["publie"] / "entite").glob("*.json")) \
        == ["1.json", "2.json", "3.json"]


def test_revenir_deux_fois_ramene_la_ou_lon_etait(publication, emplacements):
    """Sinon on creuse : le deuxième retour irait chercher une version encore
    plus ancienne, que personne n'a demandée."""
    snapshot(emplacements["publie"], [1], marque="en ligne")
    publication.generer_apercu(builder=builder([2], marque="brouillon"),
                               controleur=lambda cible: controle(True))
    publication.publier(auteur="admin@exemple", role="admin",
                        controleur=lambda cible: controle(True))

    publication.revenir_a_la_version_precedente(emplacements["publie"])
    publication.revenir_a_la_version_precedente(emplacements["publie"])

    assert json.loads(
        (emplacements["publie"] / "stats.json").read_text())["marque"] == "brouillon"


def test_revenir_sans_version_precedente_se_dit(publication, emplacements):
    snapshot(emplacements["publie"], [1])
    with pytest.raises(publication.PublicationRefusee) as refus:
        publication.revenir_a_la_version_precedente(emplacements["publie"])
    assert "aucune version précédente" in str(refus.value).lower()


def test_letat_publie_porte_lempreinte_de_ce_qui_est_servi(publication, emplacements):
    """« Publié » et « en ligne » sont deux états distincts. L'empreinte est ce
    qui permettra, plus tard, de vérifier que le site déployé sert bien cette
    version-là — et pas celle d'avant-hier."""
    publication.generer_apercu(builder=builder([1, 2], marque="brouillon"),
                               controleur=lambda cible: controle(True))
    publie = publication.publier(auteur="admin@exemple", role="admin",
                                 controleur=lambda cible: controle(True))

    assert publie["empreinte"] == publication.empreinte(emplacements["publie"])


def test_deux_snapshots_qui_different_dun_fichier_retire_ont_deux_empreintes(
        publication, tmp_path):
    """L'empreinte porte les CHEMINS autant que les contenus : c'est ce qui
    permet de voir qu'une fiche a disparu, et la disparition d'une fiche est
    exactement ce que la publication doit propager."""
    a, b = tmp_path / "a", tmp_path / "b"
    snapshot(a, [1, 2])
    snapshot(b, [1, 2])
    assert publication.empreinte(a) == publication.empreinte(b)
    (b / "entite" / "2.json").unlink()
    assert publication.empreinte(a) != publication.empreinte(b)


def test_une_publication_concurrente_est_refusee_et_ne_touche_a_rien(
        publication, emplacements, monkeypatch):
    """Deux clics valent deux requêtes. Rien n'empêchait deux publications de
    se recouvrir dans le même répertoire."""
    import fcntl

    snapshot(emplacements["publie"], [1], marque="en ligne")
    avant = empreinte(emplacements["publie"])
    publication.generer_apercu(builder=builder([2], marque="brouillon"),
                               controleur=lambda cible: controle(True))

    verrou = publication.VERROU
    verrou.parent.mkdir(parents=True, exist_ok=True)
    with open(verrou, "w") as tenu:
        fcntl.flock(tenu, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Sans raccourcir l'attente, le test durerait la trentaine de secondes
        # que l'atelier accorde à un opérateur pressé.
        vrai_verrou = publication.verrou_de_publication
        monkeypatch.setattr(publication, "verrou_de_publication",
                            lambda delai=0.3: vrai_verrou(delai))

        with pytest.raises(publication.PublicationRefusee) as refus:
            publication.publier(auteur="admin@exemple", role="admin",
                                controleur=lambda cible: controle(True))

    assert "en cours" in str(refus.value).lower()
    assert empreinte(emplacements["publie"]) == avant


def test_le_verrou_est_relache_apres_usage(publication):
    """Un verrou qui survivrait à son opération immobiliserait l'instance."""
    with publication.verrou_de_publication(delai=1):
        pass
    with publication.verrou_de_publication(delai=1):
        pass    # doit être immédiat, pas une seconde d'attente


# ── La ligne de commande aussi : générer n'est pas publier ───────────────────

def test_le_cli_ne_sert_pas_un_brouillon(publication):
    """`build_public_snapshot.py --out <brouillon>` recopiait quand même le
    résultat dans `public/static/data`.

    La publication en deux temps a corrigé ça côté atelier — l'aperçu n'écrit
    que dans son brouillon — mais le défaut restait entier côté ligne de
    commande, là où l'exploitant travaille : construire un aperçu le mettait en
    ligne, sans contrôle et sans qu'une ligne le dise.

    Le test lit le code plutôt que de lancer un build : construire un vrai
    snapshot demande une base, et ce qui est en jeu ici est une DÉCISION, pas
    un résultat.
    """
    source = (ROOT / "scripts" / "build_public_snapshot.py").read_text(encoding="utf-8")
    bloc = source[source.index("def main()"):]
    assert "vers_le_repertoire_publie" in bloc, \
        "la synchro vers le site ne vérifie plus où pointe --out"
    # La recopie est sous condition, jamais dans la branche par défaut.
    avant_sync = bloc[:bloc.index("synchroniser_site_public(args.out")]
    assert "DEFAULT_OUT.resolve()" in avant_sync

# ── Mettre en ligne ──────────────────────────────────────────────────────────
#
# Le seul geste de l'atelier qui sorte de la machine. Promouvoir écrit dans deux
# répertoires locaux ; mettre en ligne change ce que le public voit.
#
# Ce qu'il ne fait PAS, et c'est le point : rejouer `deploy/publier-site.sh` en
# entier. Ce script commence par reconstruire le snapshot depuis la base — or ce
# qui a été promu a été CONTRÔLÉ. Le reconstruire déploierait une version que
# personne n'a validée, différente dès qu'un collecteur a tourné entre-temps.


@pytest.fixture
def pret_a_deployer(publication, emplacements, monkeypatch):
    """Un snapshot promu, et un projet d'hébergement déclaré."""
    monkeypatch.setattr(publication, "projet_hebergeur", lambda: "vigie-essai")
    monkeypatch.setattr(publication, "DEPLOIEMENT_LOG",
                        emplacements["brouillon"].parent / "mise-en-ligne.log")
    monkeypatch.setattr(publication, "DEPLOIEMENT_ETAT",
                        emplacements["brouillon"].parent / "mise-en-ligne.json")
    monkeypatch.setattr(publication, "_deploiement", None)
    publication.generer_apercu(builder=builder([1, 2]),
                               controleur=lambda cible: controle(True))
    return publication.publier(auteur="admin@exemple", role="admin",
                               controleur=lambda cible: controle(True))


def test_seul_un_admin_met_en_ligne(publication, pret_a_deployer):
    for role in (None, "contributor", "validator"):
        with pytest.raises(publication.PublicationRefusee) as refus:
            publication.mettre_en_ligne(auteur="x", role=role)
        assert "admin" in str(refus.value).lower()


def test_sans_rien_de_promu_la_mise_en_ligne_refuse(publication, emplacements,
                                                    monkeypatch):
    """Mettre en ligne ne construit pas de snapshot : il déploie celui qui a été
    contrôlé. S'il n'y en a pas, il n'y a rien à déployer."""
    monkeypatch.setattr(publication, "projet_hebergeur", lambda: "vigie-essai")
    monkeypatch.setattr(publication, "_deploiement", None)
    with pytest.raises(publication.PublicationRefusee) as refus:
        publication.mettre_en_ligne(auteur="admin@exemple", role="admin")
    assert "promu" in str(refus.value).lower()


def test_sans_projet_declare_la_mise_en_ligne_refuse(publication, pret_a_deployer,
                                                     monkeypatch):
    """Un déploiement sans nom de projet irait au hasard — ou, pire, chez le
    voisin : une machine porte souvent plusieurs instances."""
    monkeypatch.setattr(publication, "projet_hebergeur", lambda: None)
    with pytest.raises(publication.PublicationRefusee) as refus:
        publication.mettre_en_ligne(auteur="admin@exemple", role="admin")
    assert "projet" in str(refus.value).lower()


def test_la_mise_en_ligne_part_de_ce_qui_est_servi(publication, pret_a_deployer,
                                                   emplacements, monkeypatch):
    """Le build est lancé dans `public/`, qui lit le répertoire servi — pas une
    reconstruction depuis la base."""
    lance = {}

    class FauxDeploiement:
        returncode = None
        def poll(self): return None

    def faux_popen(cmd, cwd=None, **kw):
        lance.update(cmd=cmd, cwd=cwd)
        return FauxDeploiement()

    monkeypatch.setattr(publication.subprocess, "Popen", faux_popen)
    monkeypatch.setattr(publication, "_deploiement", None)
    # `node_modules` est exigé avant de lancer quoi que ce soit.
    (publication.ROOT / "public" / "node_modules").mkdir(parents=True, exist_ok=True)

    etat = publication.mettre_en_ligne(auteur="admin@exemple", role="admin")

    assert lance["cwd"].endswith("public")
    commande = " ".join(lance["cmd"])
    assert "npm run build" in commande
    assert "wrangler pages deploy build" in commande
    # L'environnement Production, explicitement : sans `--branch=main`, wrangler
    # lit la branche git courante et déploie en Preview — la production reste
    # inchangée sans que rien n'échoue.
    assert "--branch=main" in commande
    assert "--project-name=vigie-essai" in commande
    # Aucune reconstruction de snapshot : ce qui a été contrôlé part tel quel.
    assert "build_public_snapshot" not in commande
    assert "publier-site.sh" not in commande
    assert etat["actif"] is True
    assert etat["empreinte_visee"] == pret_a_deployer["empreinte"]


def test_letat_dit_quand_un_deploiement_a_echoue(publication, pret_a_deployer,
                                                 monkeypatch):
    """Un déploiement rouge doit se voir : le site n'a pas changé, et celui qui
    a cliqué doit le savoir sans aller lire un journal."""
    class Echoue:
        returncode = 1
        def poll(self): return 1

    monkeypatch.setattr(publication, "_deploiement", Echoue())
    etat = publication.etat_mise_en_ligne()
    assert etat["actif"] is False
    assert etat["ok"] is False
    assert etat["code_retour"] == 1
