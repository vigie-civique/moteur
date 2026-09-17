"""Rôles emboîtés et comptes sur invitation — tenus par l'API, pas par l'interface.

Arbitré par Julien le 17/09/2026 :

  * le contributeur propose sans trancher ; le validateur fait tout ce que fait
    le contributeur, tranche et voit les analyses ; l'admin fait tout ce que fait
    le validateur, gère les comptes et publie ;
  * on n'entre dans l'atelier que sur invitation d'un admin, qui choisit le rôle.

Constaté avant : `contributor` et `validator` avaient les mêmes droits — un
contributeur rendait une fiche publiable, rejetait une délibération, lisait
l'analyse « familles » ; et les comptes ne se créaient qu'en ligne de commande.

Ces tests passent par de VRAIS jetons, obtenus à la connexion : le verrou global
de `api.py`, les dépendances et le contrôle de session sont tous traversés.
"""
from __future__ import annotations

import sqlite3

import pytest

pytest.importorskip("fastapi", reason="job « tests-deps » : pip install -r requirements.txt")

from fastapi.testclient import TestClient  # noqa: E402

MDP = "mot-de-passe-de-test"
AVANT = "2026-01-01 00:00:00"


@pytest.fixture
def atelier(tmp_path, monkeypatch, schema_sql):
    chemin_db = tmp_path / "instance.db"
    conn = sqlite3.connect(chemin_db)
    conn.executescript(schema_sql)
    conn.close()

    import api
    import api_auth
    from collectors import db as db_mod
    for module in (api, api_auth, db_mod):
        monkeypatch.setattr(module, "DB_PATH", chemin_db)
    monkeypatch.delenv("ADMIN_KEY", raising=False)
    monkeypatch.setattr(api, "ADMIN_KEY", "")
    client = TestClient(api.app)

    def sql(requete, params=()):
        c = sqlite3.connect(chemin_db)
        c.row_factory = sqlite3.Row
        try:
            cur = c.execute(requete, params)
            c.commit()
            return [dict(r) for r in cur.fetchall()], cur.lastrowid
        finally:
            c.close()

    def compte(email, role):
        sql("INSERT INTO users(email, password_hash, role) VALUES(?,?,?)",
            (email, api_auth._hash_pw(MDP), role))
        j = client.post("/api/auth/login", json={"email": email, "password": MDP}).json()
        return {"Authorization": f"Bearer {j['access_token']}"}, j

    def fiche():
        _, eid = sql("INSERT INTO entities(type, name, updated_at) "
                     "VALUES('association', 'Les Amis du Four', ?)", (AVANT,))
        return eid

    return {"client": client, "sql": sql, "compte": compte, "fiche": fiche}


# ─── La matrice des rôles ─────────────────────────────────────────────────────

class TestContributeur:
    """Propose : corrige, note, saisit en `probable` — ne tranche rien."""

    def test_corrige_une_fiche_mais_ne_la_rend_pas_publiable(self, atelier):
        c, eid = atelier["client"], atelier["fiche"]()
        h, _ = atelier["compte"]("contrib@exemple.fr", "contributor")
        r = c.patch(f"/api/atelier/entities/{eid}", headers=h,
                    json={"updated_at": AVANT, "address": "1 rue Basse"})
        assert r.status_code == 200
        u = r.json()["updated_at"]
        r = c.patch(f"/api/atelier/entities/{eid}", headers=h,
                    json={"updated_at": u, "confidence": "probable"})
        assert r.status_code == 403
        assert "validateur" in r.json()["detail"]["message"]

    def test_ne_tranche_ni_statut_ni_revue(self, atelier):
        c, eid = atelier["client"], atelier["fiche"]()
        h, _ = atelier["compte"]("contrib@exemple.fr", "contributor")
        assert c.patch(f"/api/atelier/entities/{eid}/status", headers=h,
                       json={"validation_status": "verified"}).status_code == 403
        _, did = atelier["sql"]("INSERT INTO events(type, title, date, source) "
                                "VALUES('deliberation', 'Cantine', '2026-09-10', 'x')")
        assert c.patch(f"/api/atelier/annotations/deliberation/{did}", headers=h,
                       json={"review_status": "rejected"}).status_code == 403
        # …mais il annote : une note n'est pas un verdict
        assert c.patch(f"/api/atelier/annotations/deliberation/{did}", headers=h,
                       json={"note": "à vérifier sur le PV papier"}).status_code == 200

    def test_ne_saisit_pas_une_donnee_confirmee(self, atelier):
        h, _ = atelier["compte"]("contrib@exemple.fr", "contributor")
        r = atelier["client"].post("/api/atelier/saisies", headers=h, json={
            "objet": "flux", "valeurs": {}, "source": {}, "confidence": "confirmed"})
        assert r.status_code == 403

    def test_un_site_quil_ajoute_attend_un_validateur(self, atelier):
        c, eid = atelier["client"], atelier["fiche"]()
        h, _ = atelier["compte"]("contrib@exemple.fr", "contributor")
        r = c.post(f"/api/atelier/entities/{eid}/websites", headers=h,
                   json={"url": "https://four.fr"})
        assert r.status_code == 200 and r.json()["status"] == "candidate"
        assert c.patch(f"/api/atelier/websites/{r.json()['id']}", headers=h,
                       json={"status": "validated"}).status_code == 403

    def test_ne_voit_pas_les_analyses(self, atelier):
        h, _ = atelier["compte"]("contrib@exemple.fr", "contributor")
        for route in ("familles", "mandats-croises", "adresses-partagees"):
            assert atelier["client"].get(f"/api/analyses/{route}", headers=h).status_code == 403

    def test_ne_gere_pas_les_comptes(self, atelier):
        h, _ = atelier["compte"]("contrib@exemple.fr", "contributor")
        assert atelier["client"].get("/api/admin/comptes", headers=h).status_code == 403


class TestValidateur:
    def test_fait_ce_que_fait_le_contributeur_et_tranche(self, atelier):
        c, eid = atelier["client"], atelier["fiche"]()
        h, _ = atelier["compte"]("valid@exemple.fr", "validator")
        r = c.patch(f"/api/atelier/entities/{eid}", headers=h,
                    json={"updated_at": AVANT, "address": "1 rue Basse", "confidence": "confirmed"})
        assert r.status_code == 200
        assert c.patch(f"/api/atelier/entities/{eid}/status", headers=h,
                       json={"validation_status": "verified"}).status_code == 200
        assert c.get("/api/analyses/familles", headers=h).status_code == 200

    def test_ne_gere_pas_les_comptes_ni_ne_publie(self, atelier):
        c = atelier["client"]
        h, _ = atelier["compte"]("valid@exemple.fr", "validator")
        assert c.get("/api/admin/comptes", headers=h).status_code == 403
        assert c.post("/api/admin/comptes/invitations", headers=h,
                      json={"email": "x@exemple.fr"}).status_code == 403
        assert c.post("/api/admin/publication/publier", headers=h).status_code == 403


# ─── Invitations ──────────────────────────────────────────────────────────────

def _inviter(atelier, h, email="nouvelle@exemple.fr", role="validator"):
    r = atelier["client"].post("/api/admin/comptes/invitations", headers=h,
                               json={"email": email, "role": role})
    assert r.status_code == 201, r.text
    return r.json()


class TestInvitation:
    def test_seul_linvite_cree_son_compte_avec_le_role_choisi(self, atelier):
        c = atelier["client"]
        h, _ = atelier["compte"]("admin@exemple.fr", "admin")
        inv = _inviter(atelier, h, "Nouvelle@Exemple.fr", "validator")
        assert inv["invitation"]["etat"] == "en_attente"

        lu = c.post("/api/auth/invitation/lire", json={"jeton": inv["jeton"]}).json()
        assert (lu["email"], lu["role"], lu["invite_par"]) == (
            "nouvelle@exemple.fr", "validator", "admin@exemple.fr")

        r = c.post("/api/auth/invitation/accepter", json={"jeton": inv["jeton"], "motdepasse": MDP})
        assert r.status_code == 200
        nouvelle = {"Authorization": f"Bearer {r.json()['access_token']}"}
        assert c.get("/api/auth/me", headers=nouvelle).json()["role"] == "validator"
        assert c.post("/api/auth/login", json={"email": "nouvelle@exemple.fr",
                                               "password": MDP}).status_code == 200

        # le jeton n'est jamais stocké en clair
        stocke, _ = atelier["sql"]("SELECT jeton_sha256 FROM invitations")
        assert inv["jeton"] not in str(stocke)

    def test_un_lien_ne_sert_quune_fois(self, atelier):
        c = atelier["client"]
        h, _ = atelier["compte"]("admin@exemple.fr", "admin")
        jeton = _inviter(atelier, h)["jeton"]
        assert c.post("/api/auth/invitation/accepter",
                      json={"jeton": jeton, "motdepasse": MDP}).status_code == 200
        r = c.post("/api/auth/invitation/accepter", json={"jeton": jeton, "motdepasse": MDP})
        assert r.status_code == 410

    def test_lien_inconnu_expire_annule_ou_remplace(self, atelier):
        c = atelier["client"]
        h, _ = atelier["compte"]("admin@exemple.fr", "admin")
        assert c.post("/api/auth/invitation/lire", json={"jeton": "au-hasard"}).status_code == 404

        premier = _inviter(atelier, h, "a@exemple.fr")
        second = _inviter(atelier, h, "a@exemple.fr")          # remplace le premier
        assert c.post("/api/auth/invitation/lire", json={"jeton": premier["jeton"]}).status_code == 410
        assert c.post("/api/auth/invitation/lire", json={"jeton": second["jeton"]}).status_code == 200

        atelier["sql"]("UPDATE invitations SET expire_le=datetime('now', '-1 minute') WHERE id=?",
                       (second["invitation"]["id"],))
        r = c.post("/api/auth/invitation/accepter", json={"jeton": second["jeton"], "motdepasse": MDP})
        assert r.status_code == 410 and "expiré" in r.json()["detail"]

        troisieme = _inviter(atelier, h, "b@exemple.fr")
        assert c.delete(f"/api/admin/comptes/invitations/{troisieme['invitation']['id']}",
                        headers=h).status_code == 200
        assert c.post("/api/auth/invitation/lire", json={"jeton": troisieme["jeton"]}).status_code == 410

    def test_on_ninvite_pas_une_adresse_qui_a_deja_un_compte(self, atelier):
        h, _ = atelier["compte"]("admin@exemple.fr", "admin")
        r = atelier["client"].post("/api/admin/comptes/invitations", headers=h,
                                   json={"email": "ADMIN@exemple.fr", "role": "contributor"})
        assert r.status_code == 409

    def test_mot_de_passe_trop_court_refuse_et_lien_intact(self, atelier):
        c = atelier["client"]
        h, _ = atelier["compte"]("admin@exemple.fr", "admin")
        jeton = _inviter(atelier, h)["jeton"]
        assert c.post("/api/auth/invitation/accepter",
                      json={"jeton": jeton, "motdepasse": "court"}).status_code == 400
        assert c.post("/api/auth/invitation/lire", json={"jeton": jeton}).status_code == 200


class TestComptes:
    def test_lien_de_mot_de_passe_clot_les_anciennes_sessions(self, atelier):
        c = atelier["client"]
        h_admin, _ = atelier["compte"]("admin@exemple.fr", "admin")
        h_val, j_val = atelier["compte"]("valid@exemple.fr", "validator")
        vid = atelier["sql"]("SELECT id FROM users WHERE email='valid@exemple.fr'")[0][0]["id"]

        r = c.post(f"/api/admin/comptes/{vid}/lien-mot-de-passe", headers=h_admin)
        assert r.status_code == 201
        assert c.post("/api/auth/invitation/accepter",
                      json={"jeton": r.json()["jeton"], "motdepasse": "nouveau-mot-de-passe"}
                      ).status_code == 200

        assert c.get("/api/atelier/stats", headers=h_val).status_code == 401
        assert c.post("/api/auth/refresh",
                      json={"refresh_token": j_val["refresh_token"]}).status_code == 401
        assert c.post("/api/auth/login", json={"email": "valid@exemple.fr",
                                               "password": "nouveau-mot-de-passe"}).status_code == 200

    def test_changer_son_mot_de_passe_garde_la_session_qui_le_change(self, atelier):
        c = atelier["client"]
        h, _ = atelier["compte"]("valid@exemple.fr", "validator")
        r = c.post("/api/auth/mot-de-passe", headers=h,
                   json={"actuel": MDP, "nouveau": "un-autre-mot-de-passe"})
        assert r.status_code == 200
        neuf = {"Authorization": f"Bearer {r.json()['access_token']}"}
        assert c.get("/api/auth/me", headers=neuf).status_code == 200
        assert c.get("/api/auth/me", headers=h).status_code == 401

    def test_un_compte_desactive_perd_laccès_tout_de_suite(self, atelier):
        c = atelier["client"]
        h_admin, _ = atelier["compte"]("admin@exemple.fr", "admin")
        h_val, _ = atelier["compte"]("valid@exemple.fr", "validator")
        vid = atelier["sql"]("SELECT id FROM users WHERE email='valid@exemple.fr'")[0][0]["id"]
        assert c.patch(f"/api/admin/comptes/{vid}", headers=h_admin,
                       json={"actif": False}).status_code == 200
        assert c.get("/api/atelier/stats", headers=h_val).status_code == 401
        assert c.post("/api/auth/login", json={"email": "valid@exemple.fr",
                                               "password": MDP}).status_code == 403

    def test_le_dernier_admin_reste_admin(self, atelier):
        c = atelier["client"]
        h, _ = atelier["compte"]("admin@exemple.fr", "admin")
        aid = atelier["sql"]("SELECT id FROM users")[0][0]["id"]
        assert c.patch(f"/api/admin/comptes/{aid}", headers=h,
                       json={"role": "validator"}).status_code == 409

    def test_les_invitations_dun_admin_retrograde_tombent(self, atelier):
        c = atelier["client"]
        h1, _ = atelier["compte"]("admin1@exemple.fr", "admin")
        h2, _ = atelier["compte"]("admin2@exemple.fr", "admin")
        jeton = _inviter(atelier, h2, "par-admin2@exemple.fr")["jeton"]
        a2 = atelier["sql"]("SELECT id FROM users WHERE email='admin2@exemple.fr'")[0][0]["id"]
        assert c.patch(f"/api/admin/comptes/{a2}", headers=h1,
                       json={"role": "contributor"}).status_code == 200
        assert c.post("/api/auth/invitation/lire", json={"jeton": jeton}).status_code == 410

    def test_tout_passe_au_journal(self, atelier):
        c = atelier["client"]
        h, _ = atelier["compte"]("admin@exemple.fr", "admin")
        jeton = _inviter(atelier, h, "nouvelle@exemple.fr", "contributor")["jeton"]
        c.post("/api/auth/invitation/accepter", json={"jeton": jeton, "motdepasse": MDP})
        journal = c.get("/api/atelier/journal?quoi=users", headers=h).json()
        faits = [(l["par"], l["action"], l["champ"]) for l in journal["lignes"]]
        assert ("admin@exemple.fr", "invitation", "nouvelle@exemple.fr") in faits
        assert ("nouvelle@exemple.fr", "inscription", "nouvelle@exemple.fr") in faits
        assert journal["lignes"][0]["quoi_libelle"] == "compte"
