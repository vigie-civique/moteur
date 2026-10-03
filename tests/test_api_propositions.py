"""Un contributeur PROPOSE sur ce qui est publié ; un validateur accepte ou refuse.

Arbitré par Julien le 02/10/2026. Jusque-là l'API ne réservait au validateur
que le verdict et la fiabilité : le nom d'une fiche publiée, le type d'une
relation, le montant corrigé d'un acte s'écrivaient directement, et la passe
quotidienne les mettait en ligne sans relecture.

Ces tests passent par de VRAIS jetons, comme `test_api_roles`.
"""
from __future__ import annotations

import sqlite3

import pytest

pytest.importorskip("fastapi", reason="job « tests-deps » : pip install -r requirements.txt")

from fastapi.testclient import TestClient  # noqa: E402

from collectors.origine import VERBATIM  # noqa: E402

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
    from collectors import db as db_mod, saisies as saisies_mod
    for module in (api, api_auth, db_mod):
        monkeypatch.setattr(module, "DB_PATH", chemin_db)
    monkeypatch.setattr(saisies_mod, "SAISIES", tmp_path / "saisies.json")
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
        return {"Authorization": f"Bearer {j['access_token']}"}

    def fiche(confidence="verified", nom="Les Amis du Four"):
        _, eid = sql("INSERT INTO entities(type, name, confidence, lat, lng, updated_at) "
                     "VALUES('association', ?, ?, 44.04, 3.85, ?)", (nom, confidence, AVANT))
        return eid

    return {"client": client, "sql": sql, "compte": compte, "fiche": fiche,
            "contrib": compte("contrib@exemple.fr", "contributor"),
            "valid": compte("valid@exemple.fr", "validator")}


def _nom(atelier, eid):
    return atelier["sql"]("SELECT name FROM entities WHERE id=?", (eid,))[0][0]["name"]


def _en_attente(atelier, h):
    return atelier["client"].get("/api/atelier/propositions", headers=h).json()["propositions"]


class TestFiche:
    def test_sur_une_fiche_publiee_le_contributeur_propose(self, atelier):
        c, eid = atelier["client"], atelier["fiche"]()
        r = c.patch(f"/api/atelier/entities/{eid}", headers=atelier["contrib"],
                    json={"updated_at": AVANT, "name": "Les Amis du Four à pain"})
        assert r.status_code == 202, r.text
        assert r.json()["propose"] is True and r.json()["proposes"] == ["name"]
        # Rien n'a bougé : ni la valeur, ni le verrou de la fiche.
        assert _nom(atelier, eid) == "Les Amis du Four"
        assert r.json()["updated_at"] == AVANT
        attente = _en_attente(atelier, atelier["valid"])
        assert [(p["nature"], p["charge"], p["avant"], p["actuel"]) for p in attente] == [
            ("fiche", {"name": "Les Amis du Four à pain"}, {"name": "Les Amis du Four"},
             {"name": "Les Amis du Four"})]

    def test_sur_une_fiche_non_publiee_il_ecrit(self, atelier):
        c, eid = atelier["client"], atelier["fiche"]("probable")
        r = c.patch(f"/api/atelier/entities/{eid}", headers=atelier["contrib"],
                    json={"updated_at": AVANT, "name": "Les Amis du Four à pain"})
        assert r.status_code == 200, r.text
        assert _nom(atelier, eid) == "Les Amis du Four à pain"
        assert _en_attente(atelier, atelier["valid"]) == []

    def test_le_validateur_ecrit_directement(self, atelier):
        c, eid = atelier["client"], atelier["fiche"]()
        r = c.patch(f"/api/atelier/entities/{eid}", headers=atelier["valid"],
                    json={"updated_at": AVANT, "name": "Les Amis du Four à pain"})
        assert r.status_code == 200, r.text
        assert _nom(atelier, eid) == "Les Amis du Four à pain"

    def test_accepter_applique_et_journalise_au_nom_du_validateur(self, atelier):
        c, eid = atelier["client"], atelier["fiche"]()
        pid = c.patch(f"/api/atelier/entities/{eid}", headers=atelier["contrib"],
                      json={"updated_at": AVANT, "name": "Les Amis du Four à pain"}
                      ).json()["proposition"]
        r = c.post(f"/api/atelier/propositions/{pid}/decision", headers=atelier["valid"],
                   json={"accepter": True})
        assert r.status_code == 200, r.text
        assert r.json()["etat"] == "acceptee" and r.json()["tranche_par"] == "valid@exemple.fr"
        assert _nom(atelier, eid) == "Les Amis du Four à pain"
        journal, _ = atelier["sql"](
            "SELECT u.email, a.table_name, a.action FROM audit_log a "
            "JOIN users u ON u.id = a.user_id WHERE a.entity_id=? ORDER BY a.id", (eid,))
        assert [tuple(j.values()) for j in journal] == [
            ("contrib@exemple.fr", "propositions", "proposer"),
            ("valid@exemple.fr", "entities", "update"),
            ("valid@exemple.fr", "propositions", "acceptee")]
        assert _en_attente(atelier, atelier["valid"]) == []

    def test_refuser_demande_un_motif_et_n_ecrit_rien(self, atelier):
        c, eid = atelier["client"], atelier["fiche"]()
        pid = c.patch(f"/api/atelier/entities/{eid}", headers=atelier["contrib"],
                      json={"updated_at": AVANT, "name": "Autre nom"}).json()["proposition"]
        url = f"/api/atelier/propositions/{pid}/decision"
        assert c.post(url, headers=atelier["valid"], json={"accepter": False}).status_code == 400
        r = c.post(url, headers=atelier["valid"],
                   json={"accepter": False, "motif": "Le nom déclaré au RNA est l'ancien."})
        assert r.status_code == 200 and r.json()["etat"] == "refusee"
        assert _nom(atelier, eid) == "Les Amis du Four"
        # Tranchée, elle ne se retranche pas.
        assert c.post(url, headers=atelier["valid"], json={"accepter": True}).status_code == 409

    def test_un_contributeur_ne_tranche_pas_et_ne_voit_que_les_siennes(self, atelier):
        c, eid = atelier["client"], atelier["fiche"]()
        pid = c.patch(f"/api/atelier/entities/{eid}", headers=atelier["contrib"],
                      json={"updated_at": AVANT, "name": "Autre nom"}).json()["proposition"]
        r = c.post(f"/api/atelier/propositions/{pid}/decision", headers=atelier["contrib"],
                   json={"accepter": True})
        assert r.status_code == 403
        autre = atelier["compte"]("autre@exemple.fr", "contributor")
        assert _en_attente(atelier, autre) == []
        assert c.delete(f"/api/atelier/propositions/{pid}", headers=autre).status_code == 404
        assert len(_en_attente(atelier, atelier["contrib"])) == 1

    def test_reproposer_remplace_sa_proposition_en_attente(self, atelier):
        c, eid = atelier["client"], atelier["fiche"]()
        for nom in ("Premier essai", "Second essai"):
            c.patch(f"/api/atelier/entities/{eid}", headers=atelier["contrib"],
                    json={"updated_at": AVANT, "name": nom})
        attente = _en_attente(atelier, atelier["valid"])
        assert [p["charge"] for p in attente] == [{"name": "Second essai"}]

    def test_l_auteur_retire_sa_proposition(self, atelier):
        c, eid = atelier["client"], atelier["fiche"]()
        pid = c.patch(f"/api/atelier/entities/{eid}", headers=atelier["contrib"],
                      json={"updated_at": AVANT, "name": "Autre nom"}).json()["proposition"]
        assert c.delete(f"/api/atelier/propositions/{pid}",
                        headers=atelier["contrib"]).status_code == 200
        assert _en_attente(atelier, atelier["valid"]) == []


class TestCoordonnees:
    def test_deplacer_une_fiche_publiee_se_propose_puis_s_accepte(self, atelier):
        c, eid = atelier["client"], atelier["fiche"]()
        r = c.patch(f"/api/atelier/entities/{eid}/coords", headers=atelier["contrib"],
                    json={"lat": 44.05, "lng": 3.86})
        assert r.status_code == 202, r.text
        assert atelier["sql"]("SELECT lat FROM entities WHERE id=?", (eid,))[0][0]["lat"] == 44.04
        r = c.post(f"/api/atelier/propositions/{r.json()['proposition']}/decision",
                   headers=atelier["valid"], json={"accepter": True})
        assert r.status_code == 200, r.text
        ligne = atelier["sql"]("SELECT lat, lng, geocode_source FROM entities WHERE id=?",
                               (eid,))[0][0]
        assert ligne == {"lat": 44.05, "lng": 3.86, "geocode_source": "manual"}


class TestRelation:
    def _relation(self, atelier, confidence):
        a, b = atelier["fiche"](), atelier["fiche"](nom="Le Foyer rural")
        _, rid = atelier["sql"](
            "INSERT INTO relations(from_id, to_id, relation_type, source, confidence) "
            "VALUES(?,?,'membre','manual',?)", (a, b, confidence))
        return rid

    def _type(self, atelier, rid):
        return atelier["sql"]("SELECT relation_type FROM relations WHERE id=?",
                              (rid,))[0][0]["relation_type"]

    def test_changer_le_type_d_une_relation_publiee_se_propose(self, atelier):
        c, rid = atelier["client"], self._relation(atelier, "verified")
        r = c.put(f"/api/atelier/relations/{rid}", headers=atelier["contrib"],
                  json={"relation_type": "président"})
        assert r.status_code == 202, r.text
        assert self._type(atelier, rid) == "membre"
        r = c.post(f"/api/atelier/propositions/{r.json()['proposition']}/decision",
                   headers=atelier["valid"], json={"accepter": True})
        assert r.status_code == 200, r.text
        assert self._type(atelier, rid) == "président"

    def test_une_relation_non_publiee_se_modifie(self, atelier):
        c, rid = atelier["client"], self._relation(atelier, "probable")
        r = c.put(f"/api/atelier/relations/{rid}", headers=atelier["contrib"],
                  json={"relation_type": "président"})
        assert r.status_code == 200, r.text
        assert self._type(atelier, rid) == "président"


class TestCorrection:
    def _flux(self, atelier):
        _, fid = atelier["sql"](
            "INSERT INTO financial_flows(type, year, amount, description, source, origine) "
            "VALUES('subvention', 2024, 1500, 'Subvention', 'pv', ?)", (VERBATIM,))
        return fid

    def _corrections(self, atelier, fid):
        lignes, _ = atelier["sql"]("SELECT corrections FROM annotations WHERE "
                                   "object_type='flow' AND object_id=?", (fid,))
        return lignes[0]["corrections"] if lignes else None

    def test_la_correction_d_un_contributeur_attend_un_validateur(self, atelier):
        c, fid = atelier["client"], self._flux(atelier)
        r = c.patch(f"/api/atelier/annotations/flow/{fid}", headers=atelier["contrib"],
                    json={"corrections": {"amount": 15000}})
        assert r.status_code == 200, r.text
        assert r.json()["propose"] is True and r.json()["corrections"] == {}
        assert self._corrections(atelier, fid) is None
        r = c.post(f"/api/atelier/propositions/{r.json()['proposition']}/decision",
                   headers=atelier["valid"], json={"accepter": True})
        assert r.status_code == 200, r.text
        assert self._corrections(atelier, fid) == '{"amount": 15000.0}'

    def test_la_note_du_contributeur_s_ecrit_la_correction_se_propose(self, atelier):
        c, fid = atelier["client"], self._flux(atelier)
        r = c.patch(f"/api/atelier/annotations/flow/{fid}", headers=atelier["contrib"],
                    json={"note": "Le PV dit 15 000.", "corrections": {"amount": 15000}})
        assert r.status_code == 200, r.text
        assert r.json()["propose"] is True
        lignes, _ = atelier["sql"]("SELECT note, corrections FROM annotations WHERE "
                                   "object_type='flow' AND object_id=?", (fid,))
        assert lignes == [{"note": "Le PV dit 15 000.", "corrections": None}]

    def test_le_validateur_corrige_directement(self, atelier):
        c, fid = atelier["client"], self._flux(atelier)
        r = c.patch(f"/api/atelier/annotations/flow/{fid}", headers=atelier["valid"],
                    json={"corrections": {"amount": 15000}})
        assert r.status_code == 200 and r.json()["propose"] is False
        assert self._corrections(atelier, fid) == '{"amount": 15000.0}'


class TestAujourdhui:
    def test_la_carte_compte_ce_qui_attend(self, atelier):
        c, eid = atelier["client"], atelier["fiche"]()
        carte = lambda: next(f for f in c.get("/api/atelier/files",  # noqa: E731
                                              headers=atelier["valid"]).json()["files"]
                             if f["cle"] == "propositions")
        assert (carte()["reste"], carte()["role_min"]) == (0, "validator")
        c.patch(f"/api/atelier/entities/{eid}", headers=atelier["contrib"],
                json={"updated_at": AVANT, "name": "Autre nom"})
        assert carte()["reste"] == 1


class TestSaisieValidee:
    """Retirer une saisie efface sa ligne : une fois retenue par un validateur,
    son auteur ne la sort plus du site tout seul."""

    def _saisir(self, atelier):
        r = atelier["client"].post("/api/atelier/saisies", headers=atelier["contrib"], json={
            "objet": "acte", "confidence": "probable",
            "valeurs": {"date": "2026-04-27", "title": "Vote du budget primitif"},
            "source": {"sans_document_motif": "registre consulté en mairie"}})
        assert r.status_code == 201, r.text
        sid = r.json()["saisie"]["id"]
        acte = atelier["sql"]("SELECT id FROM events WHERE source=?", (f"atelier:{sid}",))[0]
        return sid, acte[0]["id"]

    def test_non_validee_son_auteur_la_retire(self, atelier):
        sid, _ = self._saisir(atelier)
        r = atelier["client"].delete(f"/api/atelier/saisies/{sid}", headers=atelier["contrib"])
        assert r.status_code == 200, r.text
        assert atelier["sql"]("SELECT COUNT(*) AS n FROM events")[0][0]["n"] == 0

    def test_retenue_par_un_validateur_elle_ne_se_retire_plus_seule(self, atelier):
        c = atelier["client"]
        sid, acte = self._saisir(atelier)
        r = c.patch(f"/api/atelier/annotations/deliberation/{acte}", headers=atelier["valid"],
                    json={"review_status": "retenu"})
        assert r.status_code == 200, r.text
        r = c.delete(f"/api/atelier/saisies/{sid}", headers=atelier["contrib"])
        assert r.status_code == 403
        assert "validateur" in r.json()["detail"]["message"]
        assert atelier["sql"]("SELECT COUNT(*) AS n FROM events")[0][0]["n"] == 1
        # Le validateur, lui, le peut.
        assert c.delete(f"/api/atelier/saisies/{sid}", headers=atelier["valid"]).status_code == 200


class TestJournal:
    def test_les_evenements_de_comptes_ne_se_lisent_qu_en_admin(self, atelier):
        c = atelier["client"]
        admin = atelier["compte"]("admin@exemple.fr", "admin")
        r = c.post("/api/admin/comptes/invitations", headers=admin,
                   json={"email": "nouvelle@exemple.fr", "role": "contributor"})
        assert r.status_code == 201, r.text
        eid = atelier["fiche"]("probable")
        c.patch(f"/api/atelier/entities/{eid}", headers=atelier["contrib"],
                json={"updated_at": AVANT, "address": "1 rue Basse"})

        vu = c.get("/api/atelier/journal", headers=atelier["contrib"]).json()
        assert [l["quoi"] for l in vu["lignes"]] == ["entities"]
        assert vu["total"] == 1 and "users" not in vu["tables"]
        assert "nouvelle@exemple.fr" not in str(vu)
        # Demander la table par son nom ne la rend pas davantage.
        force = c.get("/api/atelier/journal?quoi=users", headers=atelier["valid"]).json()
        assert force["lignes"] == []

        vu = c.get("/api/atelier/journal", headers=admin).json()
        assert {l["quoi"] for l in vu["lignes"]} == {"entities", "users"}
        assert "users" in vu["tables"]
