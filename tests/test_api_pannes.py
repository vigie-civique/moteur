"""Une panne de route n'est pas un refus d'accès.

Constaté le 04/10/2026 : le verrou global enveloppait la route dans son `try` ;
un `FileNotFoundError` du générateur de snapshot et un `OSError: Read-only file
system` de la publication ressortaient tous deux en 401 « Authentification
requise », après 13 à 18 s de travail et sans trace au journal.
"""
from __future__ import annotations

import sqlite3

import pytest

pytest.importorskip("fastapi", reason="job « tests-deps » : pip install -r requirements.txt")

from fastapi.testclient import TestClient  # noqa: E402

CHEMIN_PANNE = "/api/_essai_panne"


@pytest.fixture
def client(tmp_path, monkeypatch, schema_sql):
    chemin_db = tmp_path / "instance.db"
    conn = sqlite3.connect(chemin_db)
    conn.executescript(schema_sql)
    import api
    import api_auth
    conn.execute("INSERT INTO users(email, password_hash, role) VALUES(?,?,?)",
                 ("une@exemple.fr", api_auth._hash_pw("mot-de-passe-de-test"), "admin"))
    conn.commit()
    conn.close()
    monkeypatch.setattr(api, "DB_PATH", chemin_db)
    monkeypatch.setattr(api_auth, "DB_PATH", chemin_db)
    monkeypatch.setenv("ADMIN_KEY", "cle-de-test")

    @api.app.get(CHEMIN_PANNE)
    def _panne():
        raise OSError(30, "Read-only file system", "/srv/instance/dashboard/static")

    yield TestClient(api.app, raise_server_exceptions=False)
    api.app.router.routes[:] = [r for r in api.app.router.routes
                                if getattr(r, "path", None) != CHEMIN_PANNE]


def _jeton(client):
    return client.post("/api/auth/login", json={"email": "une@exemple.fr",
                                                "password": "mot-de-passe-de-test"}
                       ).json()["access_token"]


def test_une_panne_de_route_avec_jeton_valide_rend_500_pas_401(client):
    r = client.get(CHEMIN_PANNE, headers={"Authorization": f"Bearer {_jeton(client)}"})
    assert r.status_code == 500
    assert "OSError" in r.json()["detail"]
    # La cause (un chemin du serveur) reste au journal, hors de la réponse.
    assert "/srv/instance" not in r.text


def test_une_panne_de_route_avec_la_cle_admin_rend_500(client):
    r = client.get(CHEMIN_PANNE, headers={"x-admin-key": "cle-de-test"})
    assert r.status_code == 500


def test_un_jeton_invalide_reste_refuse_en_401(client):
    r = client.get(CHEMIN_PANNE, headers={"Authorization": "Bearer pas-un-jeton"})
    assert r.status_code == 401
    assert client.get(CHEMIN_PANNE).status_code == 401


def test_la_cle_admin_fonctionne_toujours(client):
    r = client.get("/api/stats", headers={"x-admin-key": "cle-de-test"})
    assert r.status_code == 200


def test_une_base_des_comptes_illisible_est_une_panne_pas_un_refus(client, monkeypatch):
    jeton = _jeton(client)
    import api_auth

    def _base_cassee():
        raise sqlite3.OperationalError("unable to open database file")
    monkeypatch.setattr(api_auth, "_db", _base_cassee)
    r = client.get("/api/stats", headers={"Authorization": f"Bearer {jeton}"})
    assert r.status_code == 500
