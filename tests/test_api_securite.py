"""L'atelier en ligne : ce qu'un compte, ou un document collecté, ne doit pas pouvoir faire.

Revue du 02/10/2026, avant la mise sur serveur. Tant que l'atelier tournait sur
le poste de celui qui tient l'instance, ces défauts n'avaient pas de victime :
il n'y avait qu'un compte. À plusieurs, le texte d'un PV, un fichier déposé ou
une adresse saisie par un contributeur s'affichent dans le navigateur d'un
administrateur — qui y garde son jeton de session, et qui publie.

Comme `test_api_roles`, ces tests passent par de VRAIS jetons.
"""
from __future__ import annotations

import sqlite3

import pytest

pytest.importorskip("fastapi", reason="job « tests-deps » : pip install -r requirements.txt")

from fastapi.routing import APIRoute  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

MDP = "mot-de-passe-de-test"


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
    monkeypatch.setattr(api, "RACINE", tmp_path)
    monkeypatch.setattr(api_auth, "_echecs", {})
    monkeypatch.delenv("ADMIN_KEY", raising=False)
    monkeypatch.setattr(api, "ADMIN_KEY", "")
    client = TestClient(api.app)

    def sql(requete, params=()):
        c = sqlite3.connect(chemin_db)
        try:
            cur = c.execute(requete, params)
            c.commit()
            return cur.lastrowid
        finally:
            c.close()

    def compte(email, role):
        sql("INSERT INTO users(email, password_hash, role) VALUES(?,?,?)",
            (email, api_auth._hash_pw(MDP), role))
        j = client.post("/api/auth/login", json={"email": email, "password": MDP}).json()
        return {"Authorization": f"Bearer {j['access_token']}"}

    return {"client": client, "sql": sql, "compte": compte, "racine": tmp_path, "app": api.app}


class TestSansJeton:
    def test_aucune_route_de_l_api_ne_repond_sans_session(self, atelier):
        """Parcourt les routes DÉCLARÉES : une route ajoutée demain est couverte
        sans que personne pense à l'inscrire ici."""
        c = atelier["client"]
        ouvertes = []
        for route in atelier["app"].routes:
            if not isinstance(route, APIRoute) or route.path.startswith("/api/auth/"):
                continue
            assert route.path.startswith("/api/"), (
                f"{route.path} : hors de /api/, donc hors du verrou global")
            chemin = route.path
            for nom in route.param_convertors:
                chemin = chemin.replace("{" + nom + "}", "1")
            for methode in route.methods - {"HEAD", "OPTIONS"}:
                if c.request(methode, chemin).status_code != 401:
                    ouvertes.append(f"{methode} {route.path}")
        assert ouvertes == []

    def test_la_documentation_de_l_api_est_eteinte(self, atelier):
        for chemin in ("/docs", "/redoc", "/openapi.json"):
            assert atelier["client"].get(chemin).status_code == 404, chemin


class TestDerriereUnMurHttp:
    """nginx `auth_basic` occupe `Authorization` : la session passe à côté."""

    def test_la_session_tient_quand_authorization_porte_le_mur(self, atelier):
        h = atelier["compte"]("contrib@exemple.fr", "contributor")
        jeton = h["Authorization"].removeprefix("Bearer ")
        r = atelier["client"].get("/api/atelier/stats", headers={
            "Authorization": "Basic YXRlbGllcjptdXI=", "X-Atelier-Session": jeton})
        assert r.status_code == 200, r.text

    def test_le_mur_seul_n_ouvre_rien(self, atelier):
        r = atelier["client"].get("/api/atelier/stats",
                                  headers={"Authorization": "Basic YXRlbGllcjptdXI="})
        assert r.status_code == 401

    def test_la_deconnexion_revoque_le_jeton_de_l_en_tete(self, atelier):
        h = atelier["compte"]("contrib@exemple.fr", "contributor")
        session = {"X-Atelier-Session": h["Authorization"].removeprefix("Bearer ")}
        c = atelier["client"]
        assert c.post("/api/auth/logout", headers=session).status_code == 200
        assert c.get("/api/atelier/stats", headers=session).status_code == 401


class TestContenuCollecte:
    def test_une_balise_dans_un_acte_ne_sort_pas_de_l_extrait(self, atelier):
        atelier["sql"](
            "INSERT INTO events(type, title, content) VALUES('deliberation', 'Budget', ?)",
            ("Vote du budget primitif <img src=x onerror=alert(1)> à l'unanimité",))
        h = atelier["compte"]("contrib@exemple.fr", "contributor")
        r = atelier["client"].get("/api/events/search", params={"q": "primitif"}, headers=h)
        assert r.status_code == 200, r.text
        extrait = r.json()[0]["snippet"]
        assert "<mark>primitif</mark>" in extrait
        assert "<img" not in extrait and "&lt;img" in extrait

    def _deposer(self, atelier, h, nom, contenu):
        r = atelier["client"].post("/api/atelier/documents", headers=h,
                                   files={"fichier": (nom, contenu, "text/html")})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def test_une_page_html_deposee_se_telecharge_et_ne_s_affiche_pas(self, atelier):
        h = atelier["compte"]("contrib@exemple.fr", "contributor")
        doc = self._deposer(atelier, h, "piege.html", b"<script>alert(1)</script>")
        r = atelier["client"].get(f"/api/atelier/documents/{doc}/fichier", headers=h)
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/octet-stream"
        assert r.headers["content-disposition"].startswith("attachment")
        assert r.headers["x-content-type-options"] == "nosniff"

    def test_un_pdf_s_affiche(self, atelier):
        h = atelier["compte"]("contrib@exemple.fr", "contributor")
        doc = self._deposer(atelier, h, "pv.pdf", b"%PDF-1.4 faux pv")
        r = atelier["client"].get(f"/api/atelier/documents/{doc}/fichier", headers=h)
        assert r.headers["content-type"] == "application/pdf"
        assert "attachment" not in r.headers.get("content-disposition", "")

    def test_un_chemin_hors_de_data_n_est_pas_servi(self, atelier):
        """`local_path` vit en base, que d'autres chemins que l'API écrivent :
        il ne doit jamais mener au `.env` ni à la base, qui sont dans le même arbre."""
        (atelier["racine"] / ".env").write_text("JWT_SECRET=secret")
        doc = atelier["sql"](
            "INSERT INTO raw_documents(source, url, doc_type, sha256, byte_size, local_path, "
            "title, parse_status) VALUES('atelier', NULL, 'bin', 'abc', 17, '.env', 'x', 'manuel')")
        h = atelier["compte"]("contrib@exemple.fr", "contributor")
        r = atelier["client"].get(f"/api/atelier/documents/{doc}/fichier", headers=h)
        assert r.status_code == 404


class TestAdresseSaisie:
    @pytest.mark.parametrize("adresse", ["javascript:alert(1)", "data:text/html,x",
                                         " JavaScript:alert(1)", "exemple.fr"])
    def test_un_site_qui_n_est_pas_une_adresse_http_est_refuse(self, atelier, adresse):
        eid = atelier["sql"]("INSERT INTO entities(type, name) VALUES('association', 'Le Four')")
        h = atelier["compte"]("contrib@exemple.fr", "contributor")
        c = atelier["client"]
        r = c.post(f"/api/atelier/entities/{eid}/websites", headers=h, json={"url": adresse})
        assert r.status_code == 400, r.text
        r = c.post(f"/api/atelier/entities/{eid}/contacts", headers=h,
                   json={"type": "website", "value": adresse})
        assert r.status_code == 400, r.text

    def test_une_relation_ne_prend_pas_un_type_inconnu_a_la_modification(self, atelier):
        a = atelier["sql"]("INSERT INTO entities(type, name) VALUES('person', 'A')")
        b = atelier["sql"]("INSERT INTO entities(type, name) VALUES('association', 'B')")
        rel = atelier["sql"]("INSERT INTO relations(from_id, to_id, relation_type, source, "
                             "confidence) VALUES(?,?,'membre','manual','probable')", (a, b))
        h = atelier["compte"]("contrib@exemple.fr", "contributor")
        r = atelier["client"].put(f"/api/atelier/relations/{rel}", headers=h,
                                  json={"relation_type": "<b>n'importe quoi</b>"})
        assert r.status_code == 400, r.text

    def test_une_adresse_http_passe(self, atelier):
        eid = atelier["sql"]("INSERT INTO entities(type, name) VALUES('association', 'Le Four')")
        h = atelier["compte"]("contrib@exemple.fr", "contributor")
        r = atelier["client"].post(f"/api/atelier/entities/{eid}/websites", headers=h,
                                   json={"url": "https://exemple.fr/four"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "candidate"


class TestSessionHorsDePorteeDesScripts:
    """Le jeton de sept jours vit dans un cookie que la page ne peut pas lire."""

    def _connecter(self, atelier):
        atelier["compte"]("une@exemple.fr", "validator")
        return atelier["client"].post("/api/auth/login",
                                      json={"email": "une@exemple.fr", "password": MDP})

    def test_la_connexion_pose_un_cookie_que_les_scripts_ne_lisent_pas(self, atelier):
        cookie = self._connecter(atelier).headers["set-cookie"].lower()
        assert cookie.startswith("atelier_refresh=")
        assert "httponly" in cookie and "samesite=strict" in cookie
        assert "path=/api/auth" in cookie

    def test_le_cookie_suffit_a_rafraichir_et_la_deconnexion_le_revoque(self, atelier):
        c = atelier["client"]
        self._connecter(atelier)
        r = c.post("/api/auth/refresh")                 # ni corps, ni en-tête
        assert r.status_code == 200, r.text
        acces = {"X-Atelier-Session": r.json()["access_token"]}
        assert c.get("/api/atelier/stats", headers=acces).status_code == 200

        ancien = c.cookies.get("atelier_refresh")
        assert c.post("/api/auth/logout", headers=acces).status_code == 200
        assert c.post("/api/auth/refresh").status_code == 401
        # Le jeton lui-même est révoqué, pas seulement retiré du navigateur.
        assert c.post("/api/auth/refresh", json={"refresh_token": ancien}).status_code == 401

    def test_sans_cookie_ni_jeton_rien_ne_se_rafraichit(self, atelier):
        assert atelier["client"].post("/api/auth/refresh").status_code == 401


class TestEssaisRates:
    """Celui qui se trompe est arrêté — pas celui qu'il vise."""

    def test_cinq_essais_rates_arretent_cette_origine_pas_le_compte(self, atelier):
        from fastapi.testclient import TestClient as Client
        atelier["compte"]("admin@exemple.fr", "admin")
        c = atelier["client"]
        faux = {"email": "admin@exemple.fr", "password": "pas-le-bon-mot-de-passe"}
        juste = {"email": "admin@exemple.fr", "password": MDP}
        for _ in range(5):
            assert c.post("/api/auth/login", json=faux).status_code == 401
        # La même origine est arrêtée, même avec le bon mot de passe…
        assert c.post("/api/auth/login", json=juste).status_code == 429
        # …l'administrateur, lui, entre de chez lui.
        ailleurs = Client(atelier["app"], client=("203.0.113.7", 50000))
        assert ailleurs.post("/api/auth/login", json=juste).status_code == 200

    def test_un_compte_inexistant_repond_comme_un_mauvais_mot_de_passe(self, atelier):
        c = atelier["client"]
        inconnu = {"email": "personne@exemple.fr", "password": "x" * 12}
        for _ in range(5):
            assert c.post("/api/auth/login", json=inconnu).status_code == 401
        assert c.post("/api/auth/login", json=inconnu).status_code == 429


class TestModeleDistant:
    """Envoyer la base de travail hors de la machine se décide, ça ne s'obtient
    pas en renseignant une adresse."""

    @pytest.mark.parametrize("adresse, accepte, attendu", [
        ("http://localhost:11434/v1", False, True),
        ("http://127.0.0.1:11434/v1", False, True),
        ("https://api.exemple.com/v1", False, False),
        ("https://api.exemple.com/v1", True, True),
        ("https://localhost.exemple.com/v1", False, False),     # pas une sous-chaîne
    ])
    def test_un_modele_distant_demande_une_decision(self, monkeypatch, adresse, accepte, attendu):
        import api
        monkeypatch.setattr(api, "_IA_URL", adresse)
        monkeypatch.setattr(api, "_IA_MODELE", "un-modele")
        monkeypatch.setattr(api, "_IA_HORS_MACHINE", accepte)
        assert api._ia_configuree() is attendu
