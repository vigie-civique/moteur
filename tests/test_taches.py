"""Les tâches nées des lacunes : une file d'« Aujourd'hui », un cycle de vie qui suit le dossier.

Ce que ces tests protègent (03/10/2026) :
  - chaque lacune d'un dossier devient une tâche de la file `lacunes`, comptée
    comme les autres files — pas une liste à côté ;
  - le libellé est une question en français, jamais un identifiant ;
  - une lacune qui disparaît ferme sa tâche avec la raison ; une lacune qui
    passe de « ouvert » à « en partie » garde sa tâche et son historique ;
  - ⚖️ aucune tâche n'écrit dans le markdown d'un dossier ;
  - répondre propose, valider tranche, et personne ne valide sa propre réponse.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from collectors import taches as T
from collectors.citations import Index, index_selon_regles
from collectors.files import relever

FIXTURE = Path(__file__).parent / "fixtures" / "dossiers" / "eau.md"
REGLES = {"events": {"public_sources": ["exemple.invalid"], "exclude_types": []}}
CONTRIB = {"id": 2, "email": "c@fictiville.invalid", "role": "contributor"}
VALIDEUR = {"id": 1, "email": "v@fictiville.invalid", "role": "validator"}
AUTRE_VALIDEUR = {"id": 3, "email": "w@fictiville.invalid", "role": "validator"}


@pytest.fixture
def instance(tmp_path, base):
    racine = tmp_path / "instance"
    (racine / "dossiers").mkdir(parents=True)
    shutil.copyfile(FIXTURE, racine / "dossiers" / "eau.md")
    for u in (VALIDEUR, CONTRIB, AUTRE_VALIDEUR):
        base.execute("INSERT INTO users(id, email, password_hash, role) VALUES(?,?,?,?)",
                     (u["id"], u["email"], "x", u["role"]))
    T.assurer_schema(base)
    base.commit()
    return racine


def _releve(base, racine, index=None):
    lacunes, titres = T.lacunes_de_l_instance(racine, index or Index([]))
    bilan = T.synchroniser(base, lacunes, titres)
    base.commit()
    return bilan


def _par_nature(base):
    return {t["lacune"]["question"]: t for t in T.lister(base, T.ETATS)}


# ── la file ──────────────────────────────────────────────────────────────────

def test_chaque_lacune_devient_une_tache_comptee_par_aujourd_hui(base, instance):
    bilan = _releve(base, instance)
    taches = T.lister(base)
    natures = sorted(t["nature"] for t in taches)
    assert natures.count("demander") == 2, "les deux questions du tableau"
    assert natures.count("relier") >= 3, "les citations sans acte publié"
    assert bilan["creees"] == len(taches)
    [file] = [f for f in relever(base, "Testonville", "99000") if f["cle"] == "lacunes"]
    assert file["reste"] == len(taches) and file["route"] == "/atelier/taches"
    assert file["role_min"] == "contributor"


def test_une_file_vide_dit_pourquoi(base, tmp_path):
    T.assurer_schema(base)
    [file] = [f for f in relever(base, "Testonville", "99000") if f["cle"] == "lacunes"]
    assert file["reste"] == 0 and file["sans_collecte"] and "Aucun dossier" in file["vide"]


def test_le_libelle_est_une_question_en_francais(base, instance):
    _releve(base, instance)
    for t in T.lister(base):
        assert t["libelle"].endswith("?"), t["libelle"]
        assert ":q-" not in t["libelle"] and ":c-" not in t["libelle"], "jamais un identifiant"
    q = _par_nature(base)["Le contrat du syndicat avec son exploitant"]
    assert q["libelle"] == ("Que faut-il demander, et à qui, pour connaître "
                            "« Le contrat du syndicat avec son exploitant » ?")


def test_le_releve_est_idempotent(base, instance):
    _releve(base, instance)
    assert _releve(base, instance) == {"creees": 0, "fermees": 0, "reouvertes": 0, "etat_change": 0}


# ── le cycle de vie suit le dossier ──────────────────────────────────────────

def _reecrire(instance, avant, apres):
    p = instance / "dossiers" / "eau.md"
    texte = p.read_text(encoding="utf-8")
    assert avant in texte
    p.write_text(texte.replace(avant, apres), encoding="utf-8")


def test_une_lacune_qui_change_d_etat_garde_sa_tache_et_son_historique(base, instance):
    _releve(base, instance)
    avant = _par_nature(base)["La date effective du transfert à l'intercommunalité"]
    _reecrire(instance, "**ouvert** : aucun acte publié ne la fixe",
              "**en partie** : un acte de 2023 la cite, sans la fixer")
    assert _releve(base, instance)["etat_change"] == 1
    apres = T.lire(base, avant["id"])
    assert (apres["etat"], apres["etat_lacune"]) == ("ouverte", "en_partie")
    assert [j["quoi"] for j in apres["journal"]] == ["creee", "etat_lacune"]


def test_une_retouche_de_ponctuation_ne_ferme_rien(base, instance):
    _releve(base, instance)
    _reecrire(instance, "| La date effective du transfert à l'intercommunalité |",
              "| La date effective du transfert, à l'intercommunalité ? |")
    assert _releve(base, instance)["fermees"] == 0


def test_une_lacune_qui_disparait_ferme_sa_tache_avec_la_raison(base, instance):
    _releve(base, instance)
    t = _par_nature(base)["La date effective du transfert à l'intercommunalité"]
    _reecrire(instance, "| La date effective du transfert à l'intercommunalité | **ouvert** : "
                        "aucun acte publié ne la fixe | lecture des délibérations CC de 2022 et 2023 |\n", "")
    assert _releve(base, instance)["fermees"] == 1
    ferme = T.lire(base, t["id"])
    assert ferme["etat"] == "fermee" and "a disparu du dossier « L'eau à Testonville »" in ferme["raison"]


def test_une_citation_reliee_par_l_editeur_ferme_sa_tache(base, instance):
    """La tâche « relier » ne s'écrit pas dans le dossier : c'est l'éditeur qui
    pose la clé, et ce changement-là ferme la tâche."""
    base.execute("INSERT INTO events(type, date, title, source, metadata) VALUES("
                 "'deliberation', '2019-11-28', 'Rapport annuel', 'exemple.invalid', "
                 "'{\"numero_acte\": \"7\"}')")
    base.commit()
    index = index_selon_regles(base, REGLES)
    _releve(base, instance, index)
    [t] = [t for t in T.lister(base) if "12/12/2019" in t["libelle"]]
    _reecrire(instance, "(CM du 12/12/2019)", "([CM du 12/12/2019](acte:c-2019-7))")
    assert _releve(base, instance, index)["fermees"] == 1
    ferme = T.lire(base, t["id"])
    assert ferme["etat"] == "fermee" and "n'est plus sans cible" in ferme["raison"]


def test_une_question_dite_resolue_par_le_dossier_ferme_sa_tache(base, instance):
    _releve(base, instance)
    _reecrire(instance, "**ouvert** : aucun acte publié ne la fixe", "**résolu** : 1er janvier 2023")
    assert _releve(base, instance)["fermees"] == 1


def test_aucune_tache_n_ecrit_dans_le_dossier(base, instance):
    p = instance / "dossiers" / "eau.md"
    avant = p.read_bytes()
    _releve(base, instance)
    for t in T.lister(base):
        contenu = ({"cle": None, "note": "rien trouvé"} if t["nature"] == "relier" else
                   {"destinataire": "le syndicat", "objet": "x", "texte": "y", "envoye_le": "2026-10-03"})
        T.repondre(base, t["id"], CONTRIB, contenu)
        T.valider(base, t["id"], VALIDEUR, True)
    _releve(base, instance)
    assert p.read_bytes() == avant


# ── les gestes ───────────────────────────────────────────────────────────────

def test_repondre_propose_valider_tranche_et_jamais_sa_propre_reponse(base, instance):
    _releve(base, instance)
    t = _par_nature(base)["Le contrat du syndicat avec son exploitant"]
    T.repondre(base, t["id"], VALIDEUR, {"destinataire": "le syndicat", "objet": "Contrat",
                                         "texte": "Madame, Monsieur…"})
    assert T.lire(base, t["id"])["etat"] == "proposee"
    with pytest.raises(T.Refus) as e:
        T.valider(base, t["id"], VALIDEUR, True)
    assert e.value.code == 403
    with pytest.raises(T.Refus):
        T.valider(base, t["id"], AUTRE_VALIDEUR, False)      # renvoyer sans motif
    assert T.valider(base, t["id"], AUTRE_VALIDEUR, True)["etat"] == "validee"


def test_la_relecture_croisee_peut_etre_coupee(base, instance, monkeypatch):
    monkeypatch.setattr(T, "relecture_croisee", lambda: False)
    _releve(base, instance)
    t = T.lister(base)[0]
    contenu = ({"note": "rien"} if t["nature"] == "relier" else
               {"destinataire": "a", "objet": "b", "texte": "c"})
    T.repondre(base, t["id"], VALIDEUR, contenu)
    assert T.valider(base, t["id"], VALIDEUR, True)["etat"] == "validee"


def test_une_demande_envoyee_devient_une_reponse_a_verser_dans_la_meme_tache(base, instance):
    _releve(base, instance)
    t = _par_nature(base)["Le contrat du syndicat avec son exploitant"]
    T.repondre(base, t["id"], CONTRIB, {"destinataire": "le syndicat", "objet": "Contrat",
                                        "texte": "Madame, Monsieur…"})
    T.valider(base, t["id"], VALIDEUR, True)
    t = T.marquer_envoyee(base, t["id"], CONTRIB, "2026-10-05")
    assert (t["nature"], t["etat"], t["envoye_le"]) == ("verser", "ouverte", "2026-10-05")
    assert t["libelle"].endswith("est-elle arrivée ?")
    assert [j["quoi"] for j in t["journal"]] == ["creee", "proposee", "validee", "envoyee"]
    T.repondre(base, t["id"], CONTRIB, {"resume": "Le contrat court jusqu'en 2031.",
                                        "recu_le": "2026-10-20", "ou": "courrier du 18/10"})
    assert T.valider(base, t["id"], VALIDEUR, True)["etat"] == "validee"


def test_relier_n_admet_que_les_actes_proposes(base, instance):
    _releve(base, instance)
    t = next(t for t in T.lister(base) if t["nature"] == "relier")
    with pytest.raises(T.Refus):
        T.repondre(base, t["id"], CONTRIB, {"cle": "c-1999-1"}, candidats={"c-2021-41"})
    with pytest.raises(T.Refus):
        T.repondre(base, t["id"], CONTRIB, {"cle": ""}, candidats=set())   # ni acte ni note
    assert T.repondre(base, t["id"], CONTRIB, {"cle": "c-2021-41"},
                      candidats={"c-2021-41"})["reponse"]["cle"] == "c-2021-41"


@pytest.mark.parametrize("contenu", [{"destinataire": "a", "objet": "b", "texte": "c",
                                      "envoye_le": "demain"},
                                     {"destinataire": "", "objet": "b", "texte": "c"},
                                     "pas un objet"])
def test_une_reponse_mal_formee_est_refusee(base, instance, contenu):
    _releve(base, instance)
    t = _par_nature(base)["Le contrat du syndicat avec son exploitant"]
    with pytest.raises(T.Refus):
        T.repondre(base, t["id"], CONTRIB, contenu)


# ── par l'API ────────────────────────────────────────────────────────────────

@pytest.fixture
def atelier(tmp_path, monkeypatch, schema_sql):
    pytest.importorskip("fastapi", reason="job « tests-deps » : pip install -r requirements.txt")
    from fastapi.testclient import TestClient
    chemin = tmp_path / "instance.db"
    conn = sqlite3.connect(chemin)
    conn.executescript(schema_sql)
    for u in (VALIDEUR, CONTRIB, AUTRE_VALIDEUR):
        conn.execute("INSERT INTO users(id, email, password_hash, role) VALUES(?,?,?,?)",
                     (u["id"], u["email"], "x", u["role"]))
    conn.execute("INSERT INTO events(type, date, title, source, metadata) VALUES('deliberation', "
                 "'2021-04-14', 'Protection des captages', 'exemple.invalid', '{\"numero_acte\": \"41\"}')")
    conn.execute("INSERT INTO events(type, date, title, source, metadata) VALUES('deliberation', "
                 "'2021-04-15', 'Budget', 'exemple.invalid', '{\"numero_acte\": \"42\"}')")
    conn.commit()
    conn.close()
    racine = tmp_path / "racine"
    (racine / "dossiers").mkdir(parents=True)
    (racine / "dossiers" / "eau.md").write_text(
        "---\ntitre: L'eau\n---\n\n## L'essentiel\n\nLe captage (CM du 14/05/2021).\n")
    regles = tmp_path / "regles.json"
    regles.write_text(json.dumps(REGLES))

    import api
    from api_auth import require_auth
    from collectors import config
    from collectors import db as db_mod
    monkeypatch.setattr(api, "DB_PATH", chemin)
    monkeypatch.setattr(db_mod, "DB_PATH", chemin)
    monkeypatch.setattr(api, "RACINE", racine)
    monkeypatch.setattr(config, "RULES_PATH", regles)
    monkeypatch.setenv("ADMIN_KEY", "cle-de-test")
    client = TestClient(api.app, headers={"x-admin-key": "cle-de-test"})

    def en_tant_que(user):
        api.app.dependency_overrides[require_auth] = lambda: user
        return client

    yield en_tant_que
    api.app.dependency_overrides.clear()


def test_par_l_api_aujourd_hui_compte_et_la_file_propose_des_candidats(atelier):
    c = atelier(CONTRIB)
    [file] = [f for f in c.get("/api/atelier/files").json()["files"] if f["cle"] == "lacunes"]
    assert file["reste"] == 1
    [t] = c.get("/api/atelier/taches").json()["taches"]
    assert t["nature"] == "relier" and t["libelle"] == "À quel acte renvoie « CM du 14/05/2021 » ?"
    assert [x["cle"] for x in t["candidats"]] == ["c-2021-42", "c-2021-41"], \
        "les actes publiés les plus proches de la date citée"
    r = c.post(f"/api/atelier/taches/{t['id']}/reponse", json={"contenu": {"cle": "c-1999-9"}})
    assert r.status_code == 400
    r = c.post(f"/api/atelier/taches/{t['id']}/reponse", json={"contenu": {"cle": "c-2021-41"}})
    assert r.status_code == 200, r.text
    assert c.post(f"/api/atelier/taches/{t['id']}/decision", json={"accepter": True}).status_code == 403, \
        "un contributeur propose, il ne valide pas"
    v = atelier(VALIDEUR)
    assert v.post(f"/api/atelier/taches/{t['id']}/decision", json={"accepter": True}).status_code == 200
    [t] = v.get("/api/atelier/taches").json()["taches"]
    assert t["a_reporter"] == "[CM du 14/05/2021](acte:c-2021-41)"
