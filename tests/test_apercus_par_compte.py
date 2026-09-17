"""Chacun son aperçu ; seul l'admin publie, et à partir du sien.

Arbitré par Julien le 17/09/2026 : dans l'atelier, TOUT compte peut générer un
aperçu local, non publié — daté, écrasé par son prochain aperçu, effacé au bout
d'un temps. Publier en ligne reste réservé à l'admin, après avoir généré un
aperçu qui passe les contrôles.

Avant : un seul brouillon pour tout l'atelier, que seul l'admin pouvait
générer ; un validateur qui venait de corriger ne pouvait pas regarder l'effet
de sa correction, et deux personnes qui l'auraient pu se seraient écrasées.

Comme `test_publication_flux.py`, le builder et le contrôleur sont passés en
argument : on éprouve QUI écrit OÙ, et qui a le droit.
"""
from __future__ import annotations

import functools
import importlib.util
import json
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _charger(nom, chemin):
    sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location(nom, ROOT / chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def pub():
    return _charger("publication_par_compte", "scripts/publication.py")


@pytest.fixture
def lieux(pub, tmp_path, monkeypatch):
    lieux = {n: tmp_path / n for n in ("brouillon", "publie", "site", "apercus")}
    for d in lieux.values():
        d.mkdir()
    monkeypatch.setattr(pub, "BROUILLON", lieux["brouillon"])
    monkeypatch.setattr(pub, "PUBLIE", lieux["publie"])
    monkeypatch.setattr(pub, "SITE", lieux["site"])
    monkeypatch.setattr(pub, "APERCUS", lieux["apercus"])
    monkeypatch.setattr(pub, "ETAT", tmp_path / "etat.json")
    monkeypatch.setattr(pub, "VERSIONS", tmp_path / "versions")
    monkeypatch.setattr(pub, "VERROU", tmp_path / "publication.lock")
    return lieux


def builder(entites, marque="neuf"):
    def construire(out: Path):
        (out / "entite").mkdir(parents=True, exist_ok=True)
        for i in entites:
            (out / "entite" / f"{i}.json").write_text(json.dumps({"id": i}), encoding="utf-8")
        stats = {"entities_public": len(entites), "marque": marque, "exclusions": {}}
        (out / "stats.json").write_text(json.dumps(stats), encoding="utf-8")
        return stats
    return construire


def controle(ok=True):
    return lambda cible: {"ok": ok, "compte_erreurs": 0 if ok else 2,
                          "compte_avertissements": 0, "erreurs": [], "avertissements": [],
                          "fichiers": 3, "rapport": "OK" if ok else "ÉCHEC"}


def contenu(dossier: Path) -> dict:
    return {str(f.relative_to(dossier)): f.read_text(encoding="utf-8")
            for f in sorted(dossier.rglob("*")) if f.is_file()}


# ── Générer ──────────────────────────────────────────────────────────────────

def test_chacun_genere_son_apercu_sans_toucher_a_rien_dautre(pub, lieux):
    (lieux["publie"] / "stats.json").write_text('{"servi": true}', encoding="utf-8")
    avant = {n: contenu(lieux[n]) for n in ("brouillon", "publie", "site")}

    a = pub.generer_apercu_du_compte(7, "contributrice@exemple.fr",
                                     builder=builder([1, 2]), controleur=controle())
    b = pub.generer_apercu_du_compte(9, "validateur@exemple.fr",
                                     builder=builder([1, 2, 3]), controleur=controle())

    assert a["existe"] and a["genere_par"] == "contributrice@exemple.fr"
    assert a["stats"]["entities_public"] == 2 and b["stats"]["entities_public"] == 3
    assert a["expire_le"] and a["controle"]["ok"]
    assert {n: contenu(lieux[n]) for n in ("brouillon", "publie", "site")} == avant
    assert pub.apercu_du_compte(7)["stats"]["entities_public"] == 2


def test_un_nouvel_apercu_ecrase_le_precedent_du_meme_compte(pub, lieux):
    pub.generer_apercu_du_compte(7, "x", builder=builder([1, 2, 3], "vieux"), controleur=controle())
    pub.generer_apercu_du_compte(9, "y", builder=builder([5], "autre"), controleur=controle())
    pub.generer_apercu_du_compte(7, "x", builder=builder([1], "neuf"), controleur=controle())

    fiches = sorted(p.name for p in (lieux["apercus"] / "7" / "donnees" / "entite").iterdir())
    assert fiches == ["1.json"]                 # écrasé, pas complété
    assert pub.apercu_du_compte(7)["stats"]["marque"] == "neuf"
    assert pub.apercu_du_compte(9)["stats"]["marque"] == "autre"


def test_un_apercu_perime_seffacé(pub, lieux):
    pub.generer_apercu_du_compte(7, "x", builder=builder([1]), controleur=controle())
    pub.generer_apercu_du_compte(9, "y", builder=builder([1]), controleur=controle())
    fiche = lieux["apercus"] / "7" / "apercu.json"
    donnees = json.loads(fiche.read_text())
    donnees["genere_le"] = (datetime.now(timezone.utc)
                            - timedelta(days=pub.APERCU_JOURS + 1)).isoformat()
    fiche.write_text(json.dumps(donnees))
    (lieux["apercus"] / "ne-pas-toucher").mkdir()

    assert pub.purger_apercus() == [7]
    assert not (lieux["apercus"] / "7").exists()
    assert pub.apercu_du_compte(9)["existe"]
    assert (lieux["apercus"] / "ne-pas-toucher").is_dir()


def test_le_compte_devient_un_chemin_seulement_sil_est_un_entier(pub, lieux):
    for mauvais in ("../publie", "7/../../x", -1, 0, True, None):
        with pytest.raises(pub.PublicationRefusee):
            pub.dossier_apercu(mauvais)


def test_letat_montre_laperçu_du_compte_qui_regarde(pub, lieux):
    pub.generer_apercu_du_compte(7, "x", builder=builder([1]), controleur=controle(False))
    assert pub.etat_publication(7)["etape"] == "controles_en_echec"
    assert pub.etat_publication(9)["etape"] == "aucun_apercu"


# ── Publier ──────────────────────────────────────────────────────────────────

def test_ladmin_publie_son_apercu_controle(pub, lieux):
    apercu = pub.generer_apercu_du_compte(1, "admin@exemple.fr",
                                          builder=builder([4, 5]), controleur=controle())
    publie = pub.publier(auteur="admin@exemple.fr", role="admin",
                         apercu=pub.apercu_du_compte(1), controleur=controle())
    assert publie["apercu_genere_par"] == "admin@exemple.fr"
    assert publie["apercu_genere_le"] == apercu["genere_le"]
    servi = set(contenu(lieux["publie"])) - {pub.VERSION_SERVIE}
    assert servi == set(contenu(Path(apercu["repertoire"])))
    assert pub.etat_publication(1)["etape"] == "promu_localement"


@pytest.mark.parametrize("role", ["contributor", "validator", None])
def test_seul_ladmin_publie(pub, lieux, role):
    pub.generer_apercu_du_compte(7, "x", builder=builder([1]), controleur=controle())
    with pytest.raises(pub.PublicationRefusee):
        pub.publier(auteur="x", role=role, apercu=pub.apercu_du_compte(7), controleur=controle())
    assert contenu(lieux["publie"]) == {}


def test_pas_de_publication_sans_apercu_du_compte(pub, lieux):
    # Un brouillon de ligne de commande existe : il ne remplace pas l'aperçu de l'admin.
    builder([1])(lieux["brouillon"])
    with pytest.raises(pub.PublicationRefusee) as refus:
        pub.publier(auteur="a", role="admin", apercu=pub.apercu_du_compte(1),
                    controleur=controle())
    assert "aperçu" in refus.value.message
    assert contenu(lieux["publie"]) == {}


def test_un_apercu_rouge_ou_expire_ne_se_publie_pas(pub, lieux):
    pub.generer_apercu_du_compte(1, "a", builder=builder([1]), controleur=controle())
    with pytest.raises(pub.PublicationRefusee):
        pub.publier(auteur="a", role="admin", apercu=pub.apercu_du_compte(1),
                    controleur=controle(False))           # recontrôlé à l'instant de publier

    apercu = pub.apercu_du_compte(1)
    apercu["expire_le"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    with pytest.raises(pub.PublicationRefusee) as refus:
        pub.publier(auteur="a", role="admin", apercu=apercu, controleur=controle())
    assert "expiré" in refus.value.message
    assert contenu(lieux["publie"]) == {}


# ── Servir ───────────────────────────────────────────────────────────────────

@pytest.fixture
def serveur(tmp_path):
    servir = _charger("servir_par_compte", "scripts/servir_apercu.py")
    racine = tmp_path / "apercus"
    for compte, titre in (("7", "Aperçu de sept"), ("9", "Aperçu de neuf")):
        site = racine / compte / "site"
        site.mkdir(parents=True)
        (site / "index.html").write_text(f"<title>{titre}</title>", encoding="utf-8")
        (site / "finances.html").write_text(f"<title>Finances {compte}</title>", encoding="utf-8")

    class Gestionnaire(servir.HandlerParCompte):
        pass
    Gestionnaire.racine = racine
    httpd = servir.Serveur(("127.0.0.1", 0),
                           functools.partial(Gestionnaire, directory=str(racine)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


class _SansRedirection(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


def _get(url, cookie=None):
    requete = urllib.request.Request(url, headers={"Cookie": cookie} if cookie else {})
    ouvreur = urllib.request.build_opener(_SansRedirection)
    try:
        with ouvreur.open(requete, timeout=5) as r:
            return r.status, dict(r.headers), r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode()


def test_le_lien_de_latelier_pose_le_compte_puis_chacun_voit_le_sien(serveur):
    code, entetes, _ = _get(f"{serveur}/finances?apercu=7")
    assert code == 303 and entetes["Location"] == "/finances"
    assert "vigie_apercu=7" in entetes["Set-Cookie"]

    assert "Finances 7" in _get(f"{serveur}/finances", "vigie_apercu=7")[2]
    assert "Aperçu de neuf" in _get(f"{serveur}/", "vigie_apercu=9")[2]


def test_sans_compte_ou_avec_un_compte_invalide_rien_nest_servi(serveur):
    assert _get(f"{serveur}/")[0] == 404
    assert _get(f"{serveur}/", "vigie_apercu=42")[0] == 404          # aucun aperçu
    assert _get(f"{serveur}/", "vigie_apercu=..")[0] == 404
    assert _get(f"{serveur}/?apercu=../7")[0] == 400
