"""L'API tient-elle la règle, ou seulement l'interface ?

L'interface grise ce qu'elle sait interdit — mais une interface n'est pas un
verrou : elle ne protège que celui qui l'utilise. Ces tests s'adressent
directement à l'API, comme le ferait un script, et vérifient les trois refus qui
comptent :

  1. une saisie sans source ne s'enregistre pas ;
  2. la valeur d'une ligne institutionnelle ne se réécrit pas ;
  3. …mais elle peut toujours être ÉCARTÉE de la publication, parce que refuser
     de publier un chiffre qu'on juge faux n'exige pas d'en connaître un meilleur.
"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from collectors.origine import ATELIER, INSTITUTIONNEL, VERBATIM


@pytest.fixture
def client(tmp_path, monkeypatch, schema_sql):
    chemin_db = tmp_path / "instance.db"
    conn = sqlite3.connect(chemin_db)
    conn.executescript(schema_sql)
    # L'utilisateur existe vraiment : chaque écriture de l'atelier laisse une
    # trace dans `audit_log`, qui référence `users`. Le simuler passerait à côté
    # de cette contrainte — et c'est justement elle qui garantit qu'aucune
    # modification n'est anonyme.
    conn.execute("INSERT INTO users(id, email, password_hash, role) "
                 "VALUES(1, 'julien@exemple.fr', 'x', 'admin')")
    conn.commit()
    conn.close()

    import api
    from api_auth import require_auth
    from collectors import db as db_mod, saisies as saisies_mod

    monkeypatch.setattr(api, "DB_PATH", chemin_db)
    monkeypatch.setattr(db_mod, "DB_PATH", chemin_db)
    monkeypatch.setattr(saisies_mod, "SAISIES", tmp_path / "saisies.json")
    monkeypatch.setattr(api, "RACINE", tmp_path)

    # Deux verrous à franchir, et c'est volontaire : un middleware garde tout
    # `/api/` en amont (clé de service ou JWT), les routes exigent en plus une
    # session. Le test passe par la clé de service — la même porte que les
    # scripts — et surcharge la dépendance de session.
    monkeypatch.setenv("ADMIN_KEY", "cle-de-test")
    api.app.dependency_overrides[require_auth] = lambda: {
        "id": 1, "email": "julien@exemple.fr", "role": "admin"}
    yield (TestClient(api.app, headers={"x-admin-key": "cle-de-test"}), chemin_db)
    api.app.dependency_overrides.clear()


def _flux(conn, origine, source):
    cur = conn.execute(
        "INSERT INTO financial_flows(type, year, amount, description, source, origine)"
        " VALUES('dotation', 2024, 90000, 'x', ?, ?)", (source, origine))
    conn.commit()
    return cur.lastrowid


class TestGardeOrigine:
    def test_rectifier_une_ligne_institutionnelle_est_refuse(self, client):
        api_client, chemin = client
        conn = sqlite3.connect(chemin)
        fid = _flux(conn, INSTITUTIONNEL, "OFGL")
        conn.close()

        r = api_client.patch(f"/api/atelier/annotations/flow/{fid}",
                             json={"corrections": {"amount": 12345}})
        assert r.status_code == 409
        assert "institutionnel" in r.text.lower()

    def test_ecarter_une_ligne_institutionnelle_reste_permis(self, client):
        """La nuance qui fait tenir la règle : on garde le droit de ne pas
        publier, on perd seulement celui de réécrire."""
        api_client, chemin = client
        conn = sqlite3.connect(chemin)
        fid = _flux(conn, INSTITUTIONNEL, "OFGL")
        conn.close()

        r = api_client.patch(f"/api/atelier/annotations/flow/{fid}",
                             json={"review_status": "rejected",
                                   "note": "montant aberrant, signalé à l'OFGL"})
        assert r.status_code == 200
        assert r.json()["review_status"] == "rejected"

    def test_rectifier_une_lecture_est_permis(self, client):
        api_client, chemin = client
        conn = sqlite3.connect(chemin)
        fid = _flux(conn, VERBATIM, "CR CM 2024")
        conn.close()

        r = api_client.patch(f"/api/atelier/annotations/flow/{fid}",
                             json={"corrections": {"amount": 12345}})
        assert r.status_code == 200
        assert r.json()["corrections"]["amount"] == 12345

    def test_origine_non_classee_est_protegee(self, client):
        """Devant l'inconnu, ne rien casser — et dire quoi faire pour en sortir."""
        api_client, chemin = client
        conn = sqlite3.connect(chemin)
        fid = _flux(conn, None, "source jamais vue")
        conn.close()

        r = api_client.patch(f"/api/atelier/annotations/flow/{fid}",
                             json={"corrections": {"amount": 1}})
        assert r.status_code == 409
        assert "classer_origine" in r.text

    def test_annuler_une_correction_reste_possible(self, client):
        """Sinon une correction posée par erreur avant classement deviendrait
        indélogeable."""
        api_client, chemin = client
        conn = sqlite3.connect(chemin)
        fid = _flux(conn, INSTITUTIONNEL, "OFGL")
        conn.execute("INSERT INTO annotations(object_type, object_id, review_status,"
                     " corrections) VALUES('flow', ?, 'pending', '{\"amount\": 1}')",
                     (fid,))
        conn.commit()
        conn.close()

        r = api_client.patch(f"/api/atelier/annotations/flow/{fid}",
                             json={"corrections": {"amount": ""}})
        assert r.status_code == 200
        assert r.json()["corrections"] == {}


class TestFiltreOrigine:
    """Un filtre qui ne filtre pas est pire que pas de filtre : il fait croire
    qu'on a tout vu."""

    def _peupler(self, chemin):
        conn = sqlite3.connect(chemin)
        _flux(conn, INSTITUTIONNEL, "OFGL")
        _flux(conn, VERBATIM, "CR CM 2024")
        _flux(conn, VERBATIM, "CR CM 2025")
        _flux(conn, None, "source jamais vue")
        conn.close()

    def test_chaque_origine_rend_les_siennes(self, client):
        api_client, chemin = client
        self._peupler(chemin)
        for origine, attendu in [("institutionnel", 1), ("verbatim", 2),
                                 ("non-classe", 1), ("", 4)]:
            r = api_client.get(f"/api/atelier/donnees?type=flow&origine={origine}")
            assert r.status_code == 200, r.text
            assert len(r.json()) == attendu, origine

    def test_une_origine_inventee_est_refusee(self, client):
        api_client, _ = client
        r = api_client.get("/api/atelier/donnees?type=flow&origine=officieux")
        assert r.status_code == 400


class TestSaisie:
    def test_le_contrat_est_servi_au_formulaire(self, client):
        api_client, _ = client
        r = api_client.get("/api/atelier/saisies/champs")
        assert r.status_code == 200
        objets = r.json()["objets"]
        assert "flux" in objets and "budget_vote" in objets

    def test_sans_source_rien_ne_senregistre(self, client):
        api_client, _ = client
        r = api_client.post("/api/atelier/saisies", json={
            "objet": "budget_vote",
            "valeurs": {"year": 2026, "agregat": "Recettes", "value": 100},
            "source": {}})
        assert r.status_code == 400
        assert "source" in r.text.lower()

    def test_un_champ_obligatoire_manquant_est_refuse(self, client):
        api_client, _ = client
        r = api_client.post("/api/atelier/saisies", json={
            "objet": "budget_vote",
            "valeurs": {"year": 2026, "agregat": "Recettes"},   # pas de valeur
            "source": {"sans_document_motif": "registre consulté en mairie"}})
        assert r.status_code == 400
        assert "value" in r.text

    def test_un_champ_inconnu_est_refuse(self, client):
        """Accepter un champ hors contrat, c'est laisser croire à une saisie qui
        n'aura aucun effet visible — la panne qui ne dit rien."""
        api_client, _ = client
        r = api_client.post("/api/atelier/saisies", json={
            "objet": "budget_vote",
            "valeurs": {"year": 2026, "agregat": "Recettes", "value": 100,
                        "montant_secret": 42},
            "source": {"sans_document_motif": "registre consulté en mairie"}})
        assert r.status_code == 400
        assert "montant_secret" in r.text

    def test_une_saisie_complete_arrive_en_base(self, client):
        api_client, chemin = client
        r = api_client.post("/api/atelier/saisies", json={
            "objet": "budget_vote",
            "valeurs": {"year": 2026, "agregat": "Recettes de fonctionnement",
                        "value": 2459773.03},
            "source": {"sans_document_motif": "registre consulté en mairie",
                       "citation": "« recettes : 2 459 773,03 € »"},
            "confidence": "confirmed"})
        assert r.status_code == 201, r.text

        conn = sqlite3.connect(chemin)
        conn.row_factory = sqlite3.Row
        ligne = dict(conn.execute("SELECT * FROM budget_vote").fetchone())
        conn.close()
        assert ligne["value"] == pytest.approx(2459773.03)
        assert ligne["origine"] == ATELIER
        assert ligne["saisi_par"] == "julien@exemple.fr"

    def test_verified_est_refuse_a_la_saisie(self, client):
        api_client, _ = client
        r = api_client.post("/api/atelier/saisies", json={
            "objet": "budget_vote",
            "valeurs": {"year": 2026, "agregat": "Recettes", "value": 100},
            "source": {"sans_document_motif": "registre consulté en mairie"},
            "confidence": "verified"})
        assert r.status_code == 400

    def test_deposer_puis_saisir_avec_le_document(self, client):
        api_client, chemin = client
        depot = api_client.post(
            "/api/atelier/documents",
            files={"fichier": ("pv.pdf", b"%PDF-1.4 faux pv", "application/pdf")},
            data={"titre": "PV du conseil du 27 avril"})
        assert depot.status_code == 201, depot.text
        doc_id = depot.json()["id"]

        r = api_client.post("/api/atelier/saisies", json={
            "objet": "acte",
            "valeurs": {"date": "2026-04-27", "title": "Vote du budget primitif"},
            "source": {"raw_document_id": doc_id}})
        assert r.status_code == 201, r.text

        conn = sqlite3.connect(chemin)
        conn.row_factory = sqlite3.Row
        acte = dict(conn.execute("SELECT * FROM events").fetchone())
        conn.close()
        assert acte["raw_document_id"] == doc_id
        assert acte["origine"] == ATELIER

    def test_deux_depots_du_meme_fichier_ne_font_quune_entree(self, client):
        api_client, _ = client
        fichier = {"fichier": ("pv.pdf", b"%PDF-1.4 identique", "application/pdf")}
        premier = api_client.post("/api/atelier/documents", files=fichier)
        second = api_client.post("/api/atelier/documents", files=fichier)
        assert second.json()["id"] == premier.json()["id"]
        assert second.json()["deja_present"] is True

    def test_retirer_une_saisie_efface_sa_ligne(self, client):
        api_client, chemin = client
        cree = api_client.post("/api/atelier/saisies", json={
            "objet": "budget_vote",
            "valeurs": {"year": 2026, "agregat": "Recettes", "value": 100},
            "source": {"sans_document_motif": "registre consulté en mairie"}})
        saisie_id = cree.json()["saisie"]["id"]

        r = api_client.delete(f"/api/atelier/saisies/{saisie_id}")
        assert r.status_code == 200

        conn = sqlite3.connect(chemin)
        restantes = conn.execute("SELECT COUNT(*) FROM budget_vote").fetchone()[0]
        conn.close()
        assert restantes == 0
