"""Les dossiers thématiques : écrits à l'atelier, publiés seulement retenus et tels que relus.

Ce que ces tests protègent (décision du 01/10/2026) : un dossier ne sort plus
sur une ligne de son en-tête. Il sort RETENU par un validateur, et sur le texte
exact qui a été relu. Écrire propose, retenir tranche ; deux éditeurs ne
s'écrasent pas en silence ; une version remplacée est gardée.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from collectors import dossiers as D
from collectors.verdict import empreinte

EAU = ("---\ntitre: L'eau à Fictiville\nchapeau: Deux services d'eau.\nstatut: publie\n"
       "maj: 2026-09-30\n---\n\n## L'essentiel\n\nLa régie sert le bourg.\n")


@pytest.fixture
def instance(tmp_path):
    racine = tmp_path / "instance"
    (racine / "collectors").mkdir(parents=True)
    (racine / "dossiers").mkdir()
    (racine / "dossiers" / "eau.md").write_text(EAU)
    return racine


def _retenir(conn, racine, slug, texte_relu=None):
    D.assurer_schema(conn)
    did = D.identifiant(conn, slug, creer=True)
    emp = empreinte(texte_relu.encode()) if texte_relu else D.empreinte_de(D.chemin(racine, slug))
    conn.execute("INSERT INTO annotations(object_type, object_id, review_status, reviewed_by, "
                 "reviewed_at, empreinte) VALUES('dossier', ?, 'retenu', 'v@fictiville.invalid', "
                 "'2026-10-01 10:00:00', ?)", (did, emp))
    conn.commit()
    return did


# ── la publication ───────────────────────────────────────────────────────────

def test_un_dossier_sans_verdict_ne_sort_pas_meme_marque_publie(base, instance, tmp_path):
    from scripts.build_public_snapshot import export_dossiers
    r = export_dossiers(base, tmp_path / "snap", instance)
    assert (r["publies"], r["non_retenus"]) == (0, ["eau"])
    assert json.loads((tmp_path / "snap" / "dossiers.json").read_text())["dossiers"] == []


def test_un_dossier_retenu_sort_avec_son_texte(base, instance, tmp_path):
    from scripts.build_public_snapshot import export_dossiers
    _retenir(base, instance, "eau")
    r = export_dossiers(base, tmp_path / "snap", instance)
    [d] = json.loads((tmp_path / "snap" / "dossiers.json").read_text())["dossiers"]
    assert r["publies"] == 1
    assert (d["slug"], d["texte"], d["relu_le"]) == ("eau", EAU, "2026-10-01")
    assert "v@fictiville" not in json.dumps(d), "l'adresse du relecteur n'est pas publiée"


def test_un_dossier_modifie_apres_relecture_ne_sort_plus(base, instance, tmp_path):
    from scripts.build_public_snapshot import export_dossiers
    _retenir(base, instance, "eau")
    (instance / "dossiers" / "eau.md").write_text(EAU + "\nUn paragraphe ajouté.\n")
    r = export_dossiers(base, tmp_path / "snap", instance)
    assert (r["publies"], r["modifies"]) == (0, ["eau"])


@pytest.mark.parametrize("statut", ["a_revoir", "ecarte"])
def test_seul_le_verdict_retenu_publie(base, instance, tmp_path, statut):
    from scripts.build_public_snapshot import export_dossiers
    did = _retenir(base, instance, "eau")
    base.execute("UPDATE annotations SET review_status=? WHERE object_id=?", (statut, did))
    base.commit()
    assert export_dossiers(base, tmp_path / "snap", instance)["publies"] == 0


# ── l'écriture ───────────────────────────────────────────────────────────────

def test_ecrire_garde_la_version_remplacee(instance):
    avant = D.empreinte_de(D.chemin(instance, "eau"))
    apres = D.ecrire(instance, "eau", EAU + "\nAjout.\n", avant)
    assert apres != avant
    [v] = (instance / "dossiers" / ".versions" / "eau").iterdir()
    assert v.read_text() == EAU and avant in v.name


def test_deux_editeurs_ne_secrasent_pas(instance):
    lue = D.empreinte_de(D.chemin(instance, "eau"))
    D.ecrire(instance, "eau", EAU + "\nPremier.\n", lue)
    with pytest.raises(D.Conflit):
        D.ecrire(instance, "eau", EAU + "\nSecond.\n", lue)
    assert "Premier." in D.chemin(instance, "eau").read_text()


@pytest.mark.parametrize("slug", ["../etc", "Eau", "", "a/b", ".versions"])
def test_un_identifiant_ne_sort_pas_du_repertoire(instance, slug):
    with pytest.raises(ValueError):
        D.chemin(instance, slug)


# ── la reprise du 01/10/2026 ─────────────────────────────────────────────────

def test_la_reprise_retient_les_dossiers_en_ligne_et_eux_seuls(base, instance, monkeypatch):
    from scripts.reprendre_empreintes import reprendre
    (instance / "dossiers" / "dechets.md").write_text(EAU.replace("statut: publie", "statut: brouillon"))
    (instance / "data" / "conseils").mkdir(parents=True)

    b = reprendre(base, instance, appliquer=True)

    assert (b["dossiers_retenus"], b["dossiers_sans_verdict"]) == (["eau"], ["dechets"])
    sortis, _ = D.publiables(base, instance)
    assert [d["slug"] for d in sortis] == ["eau"]
    # Rejouée, elle ne retient rien de plus.
    assert reprendre(base, instance, appliquer=True)["dossiers_retenus"] == []


# ── l'atelier ────────────────────────────────────────────────────────────────

VALIDEUR = {"id": 1, "email": "v@fictiville.invalid", "role": "validator"}
CONTRIB = {"id": 2, "email": "c@fictiville.invalid", "role": "contributor"}


@pytest.fixture
def atelier(tmp_path, monkeypatch, schema_sql, instance):
    pytest.importorskip("fastapi", reason="job « tests-deps » : pip install -r requirements.txt")
    from fastapi.testclient import TestClient
    chemin = tmp_path / "instance.db"
    conn = sqlite3.connect(chemin)
    conn.executescript(schema_sql)
    for u in (VALIDEUR, CONTRIB):
        conn.execute("INSERT INTO users(id, email, password_hash, role) VALUES(?,?,?,?)",
                     (u["id"], u["email"], "x", u["role"]))
    conn.commit()
    conn.close()

    import api
    from api_auth import require_auth
    from collectors import db as db_mod
    monkeypatch.setattr(api, "DB_PATH", chemin)
    monkeypatch.setattr(db_mod, "DB_PATH", chemin)
    monkeypatch.setattr(api, "RACINE", instance)
    monkeypatch.setenv("ADMIN_KEY", "cle-de-test")
    client = TestClient(api.app, headers={"x-admin-key": "cle-de-test"})

    def en_tant_que(user):
        api.app.dependency_overrides[require_auth] = lambda: user
        return client

    yield {"en_tant_que": en_tant_que, "instance": instance}
    api.app.dependency_overrides.clear()


def test_un_dossier_pose_sur_le_disque_apparait_et_peut_etre_retenu(atelier):
    client = atelier["en_tant_que"](VALIDEUR)
    [d] = client.get("/api/atelier/dossiers").json()
    assert (d["slug"], d["verdict"], d["modifie"]) == ("eau", "jamais_relu", False)
    assert d["dossier_id"], "un dossier posé à la main reçoit son identifiant"
    r = client.patch(f"/api/atelier/annotations/dossier/{d['dossier_id']}",
                     json={"review_status": "retenu", "empreinte_vue": d["empreinte"]})
    assert r.status_code == 200, r.text
    assert client.get("/api/atelier/dossiers").json()[0]["verdict"] == "retenu"


def test_le_contributeur_ecrit_mais_ne_retient_pas(atelier):
    client = atelier["en_tant_que"](CONTRIB)
    d = client.get("/api/atelier/dossiers/eau").json()
    r = client.put("/api/atelier/dossiers/eau", json={"texte": d["texte"] + "\nAjout.\n",
                                                      "empreinte_lue": d["empreinte"]})
    assert r.status_code == 200, r.text
    assert client.patch(f"/api/atelier/annotations/dossier/{d['dossier_id']}",
                        json={"review_status": "retenu"}).status_code == 403


def test_une_modification_apres_relecture_se_voit_et_bloque_la_version_vue(atelier):
    v = atelier["en_tant_que"](VALIDEUR)
    d = v.get("/api/atelier/dossiers/eau").json()
    url = f"/api/atelier/annotations/dossier/{d['dossier_id']}"
    assert v.patch(url, json={"review_status": "retenu", "empreinte_vue": d["empreinte"]}).status_code == 200

    c = atelier["en_tant_que"](CONTRIB)
    assert c.put("/api/atelier/dossiers/eau", json={"texte": d["texte"] + "\nAjout.\n",
                                                    "empreinte_lue": d["empreinte"]}).status_code == 200
    v = atelier["en_tant_que"](VALIDEUR)
    assert v.get("/api/atelier/dossiers").json()[0]["modifie"] is True
    # Retenir la version lue AVANT la modification : refusé.
    assert v.patch(url, json={"review_status": "retenu", "empreinte_vue": d["empreinte"]}).status_code == 409


def test_une_ecriture_sur_une_version_perimee_est_refusee(atelier):
    client = atelier["en_tant_que"](CONTRIB)
    d = client.get("/api/atelier/dossiers/eau").json()
    assert client.put("/api/atelier/dossiers/eau", json={"texte": "x", "empreinte_lue": d["empreinte"]}).status_code == 200
    r = client.put("/api/atelier/dossiers/eau", json={"texte": "y", "empreinte_lue": d["empreinte"]})
    assert r.status_code == 409


def test_creer_un_dossier(atelier):
    client = atelier["en_tant_que"](CONTRIB)
    r = client.post("/api/atelier/dossiers", json={"slug": "dechets", "titre": "Les déchets"})
    assert r.status_code == 200, r.text
    texte = client.get("/api/atelier/dossiers/dechets").json()["texte"]
    assert "titre: Les déchets" in texte and "## L'essentiel" in texte
    assert client.post("/api/atelier/dossiers", json={"slug": "dechets", "titre": "x"}).status_code == 409
    assert client.post("/api/atelier/dossiers", json={"slug": "../x", "titre": "x"}).status_code == 400


# ── le sceau des citations (03/10/2026) ──────────────────────────────────────

@pytest.fixture
def atelier_avec_actes(atelier, tmp_path, monkeypatch):
    """L'atelier, un dossier qui cite un acte, et des règles qui le publient."""
    import api
    from collectors import config
    regles = tmp_path / "regles.json"
    regles.write_text(json.dumps({"events": {"public_sources": ["fictiville.invalid"],
                                             "exclude_types": []}}))
    monkeypatch.setattr(config, "RULES_PATH", regles)
    conn = sqlite3.connect(api.DB_PATH)
    conn.execute("INSERT INTO events(type, date, title, content, source, metadata) VALUES("
                 "'deliberation', '2021-04-14', 'Protection des captages', 'Texte.', "
                 "'fictiville.invalid', '{\"numero_acte\": \"41\"}')")
    conn.commit()
    conn.close()
    (atelier["instance"] / "dossiers" / "eau.md").write_text(
        EAU + "\nLe captage est protégé (CM du 14/04/2021). Le reste (CM du 01/01/2019).\n")
    return atelier


def test_retenir_scelle_les_citations_et_un_acte_change_se_voit_a_revoir(atelier_avec_actes):
    import api
    v = atelier_avec_actes["en_tant_que"](VALIDEUR)
    d = v.get("/api/atelier/dossiers/eau").json()
    assert [(c["texte"], c["statut"]) for c in d["citations"]] == \
        [("CM du 14/04/2021", "precis"), ("CM du 01/01/2019", "non_resolu")], \
        "l'éditeur voit ce qui sera relié avant de demander une relecture"
    url = f"/api/atelier/annotations/dossier/{d['dossier_id']}"
    assert v.patch(url, json={"review_status": "retenu", "empreinte_vue": d["empreinte"]}).status_code == 200

    conn = sqlite3.connect(api.DB_PATH)
    assert conn.execute("SELECT cle FROM citations_relues").fetchall() == [("c-2021-41",)]
    conn.execute("UPDATE events SET title = 'Protection des captages (relu)'")
    conn.commit()
    conn.close()

    [ligne] = v.get("/api/atelier/dossiers").json()
    assert ligne["verdict"] == "retenu", "le verdict n'est pas touché : il RESTE publié"
    assert [e["champs"] for e in ligne["perime"]["elements"]] == [["le titre"]]


def test_un_autre_verdict_leve_le_sceau(atelier_avec_actes):
    import api
    v = atelier_avec_actes["en_tant_que"](VALIDEUR)
    d = v.get("/api/atelier/dossiers/eau").json()
    url = f"/api/atelier/annotations/dossier/{d['dossier_id']}"
    v.patch(url, json={"review_status": "retenu", "empreinte_vue": d["empreinte"]})
    assert v.patch(url, json={"review_status": "a_revoir"}).status_code == 200
    conn = sqlite3.connect(api.DB_PATH)
    assert conn.execute("SELECT COUNT(*) FROM citations_relues").fetchone()[0] == 0
