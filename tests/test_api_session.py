"""La déconnexion met fin à la session — toute la session.

Constaté le 17/09/2026 : « Déconnexion » révoquait le jeton d'accès (une heure)
mais pas celui de rafraîchissement (sept jours, gardé dans le navigateur), qui
en refabriquait un neuf. Quiconque rouvrait le navigateur était connecté.
"""
from __future__ import annotations

import sqlite3

import pytest

pytest.importorskip("fastapi", reason="job « tests-deps » : pip install -r requirements.txt")

from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch, schema_sql):
    chemin_db = tmp_path / "instance.db"
    conn = sqlite3.connect(chemin_db)
    conn.executescript(schema_sql)
    import api
    import api_auth
    conn.execute("INSERT INTO users(email, password_hash, role) VALUES(?,?,?)",
                 ("une@exemple.fr", api_auth._hash_pw("mot-de-passe-de-test"), "validator"))
    conn.commit()
    conn.close()
    monkeypatch.setattr(api, "DB_PATH", chemin_db)
    monkeypatch.setattr(api_auth, "DB_PATH", chemin_db)
    return TestClient(api.app)


def test_apres_deconnexion_le_rafraichissement_est_refuse(client):
    j = client.post("/api/auth/login", json={"email": "une@exemple.fr",
                                             "password": "mot-de-passe-de-test"}).json()
    assert client.post("/api/auth/refresh",
                       json={"refresh_token": j["refresh_token"]}).status_code == 200

    r = client.post("/api/auth/logout", json={"refresh_token": j["refresh_token"]},
                    headers={"Authorization": f"Bearer {j['access_token']}"})
    assert r.status_code == 200

    assert client.post("/api/auth/refresh",
                       json={"refresh_token": j["refresh_token"]}).status_code == 401
    assert client.get("/api/auth/me",
                      headers={"Authorization": f"Bearer {j['access_token']}"}).status_code == 401


def test_une_deconnexion_sans_corps_reste_acceptee(client):
    j = client.post("/api/auth/login", json={"email": "une@exemple.fr",
                                             "password": "mot-de-passe-de-test"}).json()
    r = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {j['access_token']}"})
    assert r.status_code == 200
