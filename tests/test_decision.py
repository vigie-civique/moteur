"""L'écran d'une décision, et le premier jour d'un bénévole — lots C et D.

Ce que ces tests tiennent :

* **Un geste est un verdict PLUS un motif**, et il repart par l'écrivain unique
  des décisions (`api._decider`). Un second chemin d'écriture, ce serait deux
  vérités — le défaut que le lot A venait de fermer.
* **Écarter sans dire pourquoi est refusé.** Deux personnes écartent une ligne
  pour des raisons opposées — le chiffre est faux, ou il touche à la vie privée
  — et six semaines plus tard rien ne les distingue.
* **Un geste du premier jour mène quelque part.** Le lot B a montré ce que
  devient une file dont l'écran n'existe pas : elle attend des mois sans que
  personne s'en aperçoive.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from collectors.files import PREMIER_JOUR, ROLES_EMBOITES, premier_jour
from collectors.verdict import (A_REVOIR, ECARTE, GESTES, JAMAIS_RELU, RETENU,
                                geste_de, note_du_geste)

ROOT = Path(__file__).resolve().parent.parent


# ── Le catalogue des gestes ──────────────────────────────────────────────────

def test_chaque_geste_pose_un_verdict_connu_et_annonce_son_effet():
    from collectors.verdict import VERDICTS
    for g in GESTES:
        assert g.verdict in VERDICTS, g.cle
        assert g.effet and g.libelle, g.cle


def test_un_geste_ne_cree_pas_un_etat_de_plus():
    """Les quatre verdicts suffisent : un geste, c'est un verdict et un motif."""
    assert {g.verdict for g in GESTES} <= {JAMAIS_RELU, RETENU, A_REVOIR, ECARTE}


def test_deux_gestes_peuvent_poser_le_meme_verdict_pour_des_raisons_opposees():
    """C'est tout l'objet du motif : « ce n'est pas exact » et « cela concerne
    une personne » écartent tous deux, et ne disent pas la même chose."""
    ecartent = [g for g in GESTES if g.verdict == ECARTE]
    assert len(ecartent) >= 2
    assert len({g.motif for g in ecartent}) == len(ecartent)


def test_un_geste_inconnu_nest_jamais_devine():
    assert geste_de("retenir") is not None
    assert geste_de("retenir-vraiment") is None
    assert geste_de(None) is None
    assert geste_de("") is None


def test_la_note_porte_le_motif_puis_la_precision():
    assert note_du_geste(geste_de("inexact"), "montant HT, l'acte vote le TTC") \
        == "inexact — montant HT, l'acte vote le TTC"
    assert note_du_geste(geste_de("personnelle")) == "donnée personnelle"


def test_une_note_ne_paraphrase_pas_son_verdict():
    """« Retenir » sans motif ne laisse RIEN : `review_status` le dit déjà."""
    assert note_du_geste(geste_de("retenir")) == ""


# ── Le premier jour ──────────────────────────────────────────────────────────

def test_chaque_role_a_exactement_trois_gestes_du_premier_jour():
    """Trois, pas douze. Une liste de douze possibilités n'est pas un accueil."""
    for role in ROLES_EMBOITES:
        assert len(PREMIER_JOUR[role]) == 3, role


def test_un_role_voit_ses_trois_gestes_et_herite_des_precedents():
    assert len(premier_jour("contributor")["miens"]) == 3
    assert premier_jour("contributor")["herites"] == []
    assert len(premier_jour("validator")["herites"]) == 3
    assert len(premier_jour("admin")["herites"]) == 6
    # Les siens ne sont jamais répétés dans les hérités.
    d = premier_jour("admin")
    assert not ({g["titre"] for g in d["miens"]} & {g["titre"] for g in d["herites"]})


def test_un_role_inconnu_ne_propose_rien_plutot_que_de_deviner():
    """Mieux vaut un accueil absent qu'un accueil dont les gestes sont refusés."""
    assert premier_jour("visiteur") == {"miens": [], "herites": []}
    assert premier_jour("") == {"miens": [], "herites": []}


def test_chaque_geste_du_premier_jour_mene_a_une_page_qui_existe():
    """Le défaut que le lot B a trouvé, transposé : une porte sans pièce."""
    for role, gestes in PREMIER_JOUR.items():
        for g in gestes:
            page = (ROOT / "dashboard" / "src" / "routes"
                    / g.route.lstrip("/") / "+page.svelte")
            assert page.exists(), f"{role} → {g.route} n'a pas de page"


# ── L'endpoint, traversé ─────────────────────────────────────────────────────

pytest.importorskip("fastapi", reason="job « tests-deps » : pip install -r requirements.txt")

from fastapi.testclient import TestClient  # noqa: E402

MDP = "mot-de-passe-de-test"


@pytest.fixture
def atelier(tmp_path, monkeypatch, schema_sql):
    chemin = tmp_path / "instance.db"
    conn = sqlite3.connect(chemin)
    conn.executescript(schema_sql)
    # Un flux que la machine n'a pas su affirmer, et l'acte qui le porte.
    conn.execute("INSERT INTO events(id, type, title, date, content, source) "
                 "VALUES(1, 'deliberation', 'Subvention au comité', '2025-04-12', "
                 "'Le conseil vote une subvention de 1 500 € au comité des fêtes.', 'CM')")
    conn.execute("INSERT INTO entities(id, type, name) VALUES(1,'service','Commune')")
    conn.execute("INSERT INTO entities(id, type, name) VALUES(2,'association','Comité des fêtes')")
    conn.execute("INSERT INTO financial_flows(id, type, year, amount, from_id, to_id, "
                 "event_id, description, source, confidence, origine) "
                 "VALUES(10, 'subvention', 2025, 1500, 1, 2, 1, 'Subvention', 'CM', "
                 "'probable', 'verbatim')")
    # Et une ligne que la machine AFFIRME : elle n'attend personne. Sans elle,
    # le décor ne peut pas distinguer « à trancher » de « toutes les lignes »,
    # et le test d'accord carte/écran passerait même prédicat retiré.
    conn.execute("INSERT INTO financial_flows(id, type, year, amount, from_id, to_id, "
                 "source, confidence) "
                 "VALUES(9, 'subvention', 2024, 800, 1, 2, 'OFGL', 'verified')")
    conn.commit()
    conn.close()

    import api
    import api_auth
    from collectors import db as db_mod
    for module in (api, api_auth, db_mod):
        monkeypatch.setattr(module, "DB_PATH", chemin)
    monkeypatch.delenv("ADMIN_KEY", raising=False)
    monkeypatch.setattr(api, "ADMIN_KEY", "")
    client = TestClient(api.app)

    def compte(email, role):
        c = sqlite3.connect(chemin)
        c.execute("INSERT INTO users(email, password_hash, role) VALUES(?,?,?)",
                  (email, api_auth._hash_pw(MDP), role))
        c.commit(); c.close()
        j = client.post("/api/auth/login",
                        json={"email": email, "password": MDP}).json()
        return {"Authorization": f"Bearer {j['access_token']}"}

    def verdict_en_base():
        c = sqlite3.connect(chemin)
        r = c.execute("SELECT review_status, note, reviewed_by FROM annotations "
                      "WHERE object_type='flow' AND object_id=10").fetchone()
        c.close()
        return r

    return {"client": client, "compte": compte, "verdict": verdict_en_base}


def test_lecran_sert_la_question_la_revendication_et_lacte(atelier):
    h = atelier["compte"]("val@exemple.fr", "validator")
    r = atelier["client"].get("/api/atelier/decision/flow/10", headers=h)
    assert r.status_code == 200
    d = r.json()
    assert d["question"].endswith("?")
    # La revendication se lit sans connaître le schéma.
    assert "1 500" in d["revendication"].replace(" ", " ")
    assert "Comité des fêtes" in d["revendication"]
    # La PIÈCE : le texte de l'acte, sans quoi la question est sans réponse.
    assert "subvention de 1 500 €" in d["acte"]["content"]
    assert d["decision"]["verdict"] == JAMAIS_RELU


def test_un_geste_devient_un_verdict_et_un_motif(atelier):
    h = atelier["compte"]("val@exemple.fr", "validator")
    r = atelier["client"].post("/api/atelier/decision/flow/10", headers=h,
                               json={"geste": "personnelle"})
    assert r.status_code == 200, r.text
    assert r.json()["verdict"] == ECARTE
    statut, note, par = atelier["verdict"]()
    assert statut == ECARTE
    assert note == "donnée personnelle"
    assert par == "val@exemple.fr"          # la décision est signée


def test_un_geste_qui_demande_un_mot_le_refuse_vide(atelier):
    h = atelier["compte"]("val@exemple.fr", "validator")
    r = atelier["client"].post("/api/atelier/decision/flow/10", headers=h,
                               json={"geste": "inexact", "precision": "   "})
    assert r.status_code == 400
    assert "reprendra au même point" in r.json()["detail"]["message"]
    assert atelier["verdict"]() is None      # rien n'a été écrit


def test_un_geste_inconnu_est_refuse_et_nomme_les_valeurs(atelier):
    h = atelier["compte"]("val@exemple.fr", "validator")
    r = atelier["client"].post("/api/atelier/decision/flow/10", headers=h,
                               json={"geste": "supprimer"})
    assert r.status_code == 400
    assert "retenir" in r.json()["detail"]


def test_un_contributeur_lit_lecran_mais_ne_tranche_pas(atelier):
    h = atelier["compte"]("contrib@exemple.fr", "contributor")
    assert atelier["client"].get("/api/atelier/decision/flow/10",
                                 headers=h).status_code == 200
    r = atelier["client"].post("/api/atelier/decision/flow/10", headers=h,
                               json={"geste": "retenir"})
    assert r.status_code == 403
    assert atelier["verdict"]() is None


def test_remettre_a_relire_nest_propose_que_sur_une_ligne_tranchee(atelier):
    """Proposer d'annuler ce qui n'existe pas est un bouton qui ne fait rien."""
    h = atelier["compte"]("val@exemple.fr", "validator")
    cles = lambda: {g["cle"] for g in atelier["client"].get(
        "/api/atelier/decision/flow/10", headers=h).json()["gestes"]}
    assert "remettre" not in cles()
    atelier["client"].post("/api/atelier/decision/flow/10", headers=h,
                           json={"geste": "retenir"})
    assert "remettre" in cles()


def test_les_gestes_du_premier_jour_suivent_le_role_connecte(atelier):
    for role, email, herites in (("contributor", "c@x.fr", 0),
                                 ("validator", "v@x.fr", 3),
                                 ("admin", "a@x.fr", 6)):
        h = atelier["compte"](email, role)
        d = atelier["client"].get("/api/atelier/files", headers=h).json()["premier_jour"]
        assert len(d["miens"]) == 3, role
        assert len(d["herites"]) == herites, role


# ── Le compte de la carte et celui de l'écran ne peuvent pas diverger ────────

def test_le_reste_de_lecran_est_celui_de_la_carte(atelier):
    """Le défaut vu à l'écran le 23/09 : la carte annonçait 79 lignes à
    trancher, l'écran de décision en annonçait 544 — toutes les lignes de la
    table, sans le filtre de fiabilité. C'est le compte de l'écran qu'on lit
    juste avant de décider, et c'est lui qui aurait découragé le bénévole.

    Éprouvé par mutation : élargir `ECRANS` à toutes les lignes fait tomber ce
    test, comme `GEO_A_FAIRE` pour la file géographique.
    """
    h = atelier["compte"]("val@exemple.fr", "validator")
    files = atelier["client"].get("/api/atelier/files", headers=h).json()["files"]
    carte = next(f for f in files if f["cle"] == "donnees-a-arbitrer")
    ecran = atelier["client"].get("/api/atelier/decision/flow/10", headers=h).json()
    assert carte["reste"] == ecran["reste"]


def test_une_ligne_sure_nentre_pas_dans_la_file(atelier):
    """Seul ce que la machine n'a pas su affirmer attend un humain.

    Le décor porte deux flux : un `probable` (10) et un `verified` (9). Un
    seul attend un geste.
    """
    h = atelier["compte"]("val@exemple.fr", "validator")
    d = atelier["client"].get("/api/atelier/decision/flow/10", headers=h).json()
    assert d["reste"] == 1
    assert d["suivant"] is None          # le `verified` n'est pas « le suivant »


def test_la_file_enchaine_dun_type_a_lautre(atelier):
    """« Chiffres à confirmer » porte des flux ET des marchés. Le suivant porte
    son type : s'arrêter au changement de famille ferait croire la file finie."""
    import api
    c = sqlite3.connect(api.DB_PATH)
    c.execute("INSERT INTO marches_publics(id, acheteur_siren, acheteur_nom, objet, "
              "source, montant, confidence) VALUES(5,'21000000000000','Commune',"
              "'Réfection du mur','procès-verbal',12000,'probable')")
    c.commit(); c.close()
    h = atelier["compte"]("val@exemple.fr", "validator")
    d = atelier["client"].get("/api/atelier/decision/flow/10", headers=h).json()
    assert d["reste"] == 2
    assert d["suivant"] == {"objet": "marche", "id": 5}


def test_un_montant_nul_nest_pas_presente_comme_un_fait():
    """Personne ne vote une subvention de zéro euro : un 0 dit que la lecture
    de l'acte n'a pas su retenir le montant. Relevé sur Lasalle : 10 flux à
    NULL, 2 à zéro, et le premier écran ouvert en affichait un."""
    from api import _euros
    assert _euros(0) == "Aucun montant retenu"
    assert _euros(None) == "Aucun montant retenu"
    assert "0" not in _euros(0)
    assert _euros(1500).replace(" ", " ") == "1 500 €"
