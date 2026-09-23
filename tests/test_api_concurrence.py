"""Deux éditeurs sur la même ligne : le second l'apprend, et apprend de qui.

Mesuré le 17/09/2026 sur une copie de l'atelier de Lasalle, deux validateurs
travaillant en même temps :

  * le statut d'une fiche passait au dernier arrivé, sans un mot ;
  * l'annotation d'une délibération aussi — et la note du premier disparaissait
    sans trace, le journal ne gardant que le statut et les corrections ;
  * la fiche, elle, refusait bien le second enregistrement, mais avec
    « updated_at attendu='…', actuel='…' » pour toute explication ;
  * un champ vidé ne s'effaçait jamais (`null` valait « non fourni »), et un
    champ de détail d'une fiche sans ligne de détail ne s'écrivait nulle part —
    derrière « Sauvegardé ✓ » dans les deux cas.
"""
from __future__ import annotations

import sqlite3

import pytest

pytest.importorskip("fastapi", reason="job « tests-deps » : pip install -r requirements.txt")

from fastapi.testclient import TestClient  # noqa: E402

UN = {"id": 1, "email": "une@exemple.fr", "role": "validator"}
DEUX = {"id": 2, "email": "deux@exemple.fr", "role": "validator"}
AVANT = "2026-01-01 00:00:00"   # lu bien avant : aucune écriture ne tombe la même seconde


@pytest.fixture
def atelier(tmp_path, monkeypatch, schema_sql):
    chemin_db = tmp_path / "instance.db"
    conn = sqlite3.connect(chemin_db)
    conn.executescript(schema_sql)
    for u in (UN, DEUX):
        conn.execute("INSERT INTO users(id, email, password_hash, role) VALUES(?,?,?,?)",
                     (u["id"], u["email"], "x", u["role"]))
    conn.commit()
    conn.close()

    import api
    from api_auth import require_auth
    from collectors import db as db_mod

    monkeypatch.setattr(api, "DB_PATH", chemin_db)
    monkeypatch.setattr(db_mod, "DB_PATH", chemin_db)
    monkeypatch.setenv("ADMIN_KEY", "cle-de-test")
    client = TestClient(api.app, headers={"x-admin-key": "cle-de-test"})

    def en_tant_que(user):
        api.app.dependency_overrides[require_auth] = lambda: user
        return client

    def sql(requete, params=()):
        c = sqlite3.connect(chemin_db)
        c.row_factory = sqlite3.Row
        try:
            cur = c.execute(requete, params)
            c.commit()
            return [dict(r) for r in cur.fetchall()], cur.lastrowid
        finally:
            c.close()

    def fiche(type_="association", avec_detail=True, **champs):
        # `updated_at` posé À L'INSERTION : un UPDATE le réécrirait par le
        # déclencheur. Et surtout pas en recréant ce déclencheur : il passerait
        # avant celui de l'index plein texte, qui retirerait alors des termes
        # absents — « database disk image is malformed ».
        _, eid = sql("INSERT INTO entities(type, name, responsible, updated_at) "
                     "VALUES(?,?,?,?)",
                     (type_, champs.get("name", "Les Amis du Four"),
                      champs.get("responsible"), AVANT))
        if avec_detail and type_ == "association":
            sql("INSERT INTO associations(entity_id, object) VALUES(?,?)", (eid, "pain"))
        return eid

    yield {"en_tant_que": en_tant_que, "sql": sql, "fiche": fiche}
    api.app.dependency_overrides.clear()


class TestStatut:
    def test_le_second_apprend_que_le_statut_a_change_et_par_qui(self, atelier):
        eid = atelier["fiche"]()
        r1 = atelier["en_tant_que"](UN).patch(
            f"/api/atelier/entities/{eid}/status",
            json={"verdict": "retenu", "statut_lu": "jamais_relu"})
        assert r1.status_code == 200

        r2 = atelier["en_tant_que"](DEUX).patch(
            f"/api/atelier/entities/{eid}/status",
            json={"verdict": "ecarte", "statut_lu": "jamais_relu"})
        assert r2.status_code == 409
        detail = r2.json()["detail"]
        assert detail["par"] == UN["email"]
        assert detail["actuel"] == "retenu"
        # Le verdict est une DÉCISION, là où la publication la lit — plus la
        # colonne `validation_status`, que rien ne lisait.
        statut, _ = atelier["sql"](
            "SELECT review_status FROM annotations WHERE object_type='entity' "
            "AND object_id=?", (eid,))
        assert statut[0]["review_status"] == "retenu"

    def test_sans_statut_lu_un_script_ecrit_toujours(self, atelier):
        eid = atelier["fiche"]()
        r = atelier["en_tant_que"](UN).patch(
            f"/api/atelier/entities/{eid}/status", json={"verdict": "a_revoir"})
        assert r.status_code == 200


class TestAnnotation:
    def _delib(self, atelier):
        _, did = atelier["sql"](
            "INSERT INTO events(type, title, date, source) "
            "VALUES('deliberation', 'Tarifs de la cantine', '2026-09-10', 'lasalle.fr')")
        return did

    def test_la_note_du_premier_nest_pas_ecrasee_en_silence(self, atelier):
        did = self._delib(atelier)
        r1 = atelier["en_tant_que"](UN).patch(
            f"/api/atelier/annotations/deliberation/{did}",
            json={"review_status": "validated", "note": "vu sur le PV papier", "lu_le": None})
        assert r1.status_code == 200
        assert r1.json()["reviewed_at"]

        r2 = atelier["en_tant_que"](DEUX).patch(
            f"/api/atelier/annotations/deliberation/{did}",
            json={"review_status": "rejected", "note": "doublon", "lu_le": None})
        assert r2.status_code == 409
        detail = r2.json()["detail"]
        assert detail["par"] == UN["email"]
        assert detail["actuel"]["note"] == "vu sur le PV papier"

    def test_le_journal_garde_la_note_remplacee(self, atelier):
        did = self._delib(atelier)
        client = atelier["en_tant_que"](UN)
        premier = client.patch(f"/api/atelier/annotations/deliberation/{did}",
                               json={"note": "première lecture"}).json()
        client.patch(f"/api/atelier/annotations/deliberation/{did}",
                     json={"note": "seconde lecture", "lu_le": premier["reviewed_at"]})
        journal, _ = atelier["sql"](
            "SELECT old_value, new_value FROM audit_log WHERE table_name='annotations' "
            "ORDER BY id")
        assert "première lecture" in journal[-1]["old_value"]
        assert "seconde lecture" in journal[-1]["new_value"]


class TestFiche:
    def test_le_conflit_dit_qui_quand_et_quels_champs(self, atelier):
        eid = atelier["fiche"]()
        r1 = atelier["en_tant_que"](UN).patch(
            f"/api/atelier/entities/{eid}", json={"updated_at": AVANT, "address": "1 rue Basse"})
        assert r1.status_code == 200

        r2 = atelier["en_tant_que"](DEUX).patch(
            f"/api/atelier/entities/{eid}", json={"updated_at": AVANT, "address": "2 rue Haute"})
        assert r2.status_code == 409
        detail = r2.json()["detail"]
        assert detail["par"] == UN["email"]
        assert "updated_at" not in detail["message"]
        assert [(c["champ"], c["apres"]) for c in detail["champs"]] == [("address", "1 rue Basse")]
        assert detail["updated_at"] == r1.json()["updated_at"]

    def test_une_mise_a_jour_de_collecte_nest_imputee_a_personne(self, atelier):
        eid = atelier["fiche"]()
        # Un humain est passé il y a longtemps…
        atelier["sql"]("INSERT INTO audit_log(user_id, entity_id, table_name, action, field, at)"
                       " VALUES(1, ?, 'entities', 'update', 'address', '2025-06-01 10:00:00')",
                       (eid,))
        # …puis la collecte réécrit la fiche, sans journal.
        atelier["sql"]("UPDATE entities SET perimetre='C1' WHERE id=?", (eid,))
        r = atelier["en_tant_que"](DEUX).patch(
            f"/api/atelier/entities/{eid}", json={"updated_at": AVANT, "address": "x"})
        assert r.status_code == 409
        assert r.json()["detail"]["par"] is None
        assert r.json()["detail"]["champs"] == []

    def test_vider_un_champ_lefface(self, atelier):
        eid = atelier["fiche"](responsible="Mme Erronée")
        r = atelier["en_tant_que"](UN).patch(
            f"/api/atelier/entities/{eid}", json={"updated_at": AVANT, "responsible": ""})
        assert r.status_code == 200
        ligne, _ = atelier["sql"]("SELECT responsible FROM entities WHERE id=?", (eid,))
        assert ligne[0]["responsible"] is None
        journal, _ = atelier["sql"]("SELECT old_value, new_value FROM audit_log WHERE entity_id=?",
                                    (eid,))
        assert journal == [{"old_value": "Mme Erronée", "new_value": None}]

    def test_le_nom_ne_se_vide_pas(self, atelier):
        eid = atelier["fiche"]()
        r = atelier["en_tant_que"](UN).patch(
            f"/api/atelier/entities/{eid}", json={"updated_at": AVANT, "name": " "})
        assert r.status_code == 400

    def test_un_champ_inchange_necrit_rien(self, atelier):
        eid = atelier["fiche"]()
        r = atelier["en_tant_que"](UN).patch(
            f"/api/atelier/entities/{eid}",
            json={"updated_at": AVANT, "name": "Les Amis du Four", "short_name": None})
        assert r.status_code == 200
        assert r.json()["updated_at"] == AVANT
        journal, _ = atelier["sql"]("SELECT 1 FROM audit_log WHERE entity_id=?", (eid,))
        assert journal == []

    def test_le_detail_secrit_meme_sans_ligne_de_detail(self, atelier):
        eid = atelier["fiche"](avec_detail=False)
        r = atelier["en_tant_que"](UN).patch(
            f"/api/atelier/entities/{eid}", json={"updated_at": AVANT, "asso_object": "fournil"})
        assert r.status_code == 200
        assert r.json()["modifies"] == ["object"]
        ligne, _ = atelier["sql"]("SELECT object FROM associations WHERE entity_id=?", (eid,))
        assert ligne == [{"object": "fournil"}]

    def test_un_champ_reecrit_deux_fois_fait_une_seule_ligne(self, atelier):
        eid = atelier["fiche"]()
        client = atelier["en_tant_que"](UN)
        u1 = client.patch(f"/api/atelier/entities/{eid}",
                          json={"updated_at": AVANT, "address": "1 rue Basse"}).json()["updated_at"]
        client.patch(f"/api/atelier/entities/{eid}",
                     json={"updated_at": u1, "address": "3 rue Basse"})
        r = atelier["en_tant_que"](DEUX).patch(
            f"/api/atelier/entities/{eid}", json={"updated_at": AVANT, "address": "x"})
        champs = r.json()["detail"]["champs"]
        assert [(c["champ"], c["avant"], c["apres"]) for c in champs] == [
            ("address", None, "3 rue Basse")]


class TestReservation:
    def _site(self, atelier):
        eid = atelier["fiche"]()
        _, wid = atelier["sql"](
            "INSERT INTO entity_websites(entity_id, url, status) VALUES(?, 'https://four.fr', 'candidate')",
            (eid,))
        return wid

    def test_on_reserve_a_son_nom_pas_a_celui_quon_ecrit(self, atelier):
        wid = self._site(atelier)
        r = atelier["en_tant_que"](UN).post(
            f"/api/atelier/queue/{wid}/claim",
            json={"table": "entity_websites", "locked_by": DEUX["email"]})
        assert r.status_code == 200
        assert r.json()["locked_by"] == UN["email"]

    def test_le_second_voit_qui_a_pris_et_ne_peut_ni_trancher_ni_liberer(self, atelier):
        wid = self._site(atelier)
        atelier["en_tant_que"](UN).post(f"/api/atelier/queue/{wid}/claim",
                                         json={"table": "entity_websites"})
        deux = atelier["en_tant_que"](DEUX)
        r = deux.post(f"/api/atelier/queue/{wid}/claim", json={"table": "entity_websites"})
        assert r.status_code == 409 and r.json()["detail"]["par"] == UN["email"]
        liste = deux.get("/api/atelier/queue/websites").json()
        assert liste[0]["reservation"]["par"] == UN["email"]
        assert deux.patch(f"/api/atelier/websites/{wid}", json={"status": "validated"}).status_code == 409
        assert deux.delete(f"/api/atelier/queue/{wid}/claim?table=entity_websites").status_code == 403

    def test_un_admin_libere_et_une_reservation_expiree_ne_compte_plus(self, atelier):
        wid = self._site(atelier)
        atelier["en_tant_que"](UN).post(f"/api/atelier/queue/{wid}/claim",
                                         json={"table": "entity_websites"})
        admin = {**DEUX, "role": "admin"}
        assert atelier["en_tant_que"](admin).delete(
            f"/api/atelier/queue/{wid}/claim?table=entity_websites").status_code == 200
        atelier["sql"]("UPDATE entity_websites SET locked_by=?, locked_at=datetime('now', '-11 minutes')"
                       " WHERE id=?", (UN["email"], wid))
        deux = atelier["en_tant_que"](DEUX)
        assert deux.get("/api/atelier/queue/websites").json()[0]["reservation"] is None
        assert deux.patch(f"/api/atelier/websites/{wid}", json={"status": "rejected"}).status_code == 200

    def test_reserver_liberer_et_trancher_laissent_une_trace(self, atelier):
        wid = self._site(atelier)
        un = atelier["en_tant_que"](UN)
        un.post(f"/api/atelier/queue/{wid}/claim", json={"table": "entity_websites"})
        un.patch(f"/api/atelier/websites/{wid}", json={"status": "validated"})
        un.delete(f"/api/atelier/queue/{wid}/claim?table=entity_websites")
        journal, _ = atelier["sql"](
            "SELECT user_id, action, old_value, new_value FROM audit_log "
            "WHERE table_name='entity_websites' ORDER BY id")
        assert [(j["user_id"], j["action"]) for j in journal] == [
            (1, "reservation"), (1, "update"), (1, "liberation")]
        assert (journal[1]["old_value"], journal[1]["new_value"]) == ("candidate", "validated")
