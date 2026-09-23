"""Le verdict — ce qu'un humain a dit d'un objet, et ce que le site en fait.

Relevé le 21/09/2026 sur les trois instances : 22 783 fiches, toutes
`unverified`. Le ✓ de la file de travail écrivait dans
`entities.validation_status`, qu'AUCUNE étape de publication ne lisait :
trancher une fiche ne changeait rien au site, et rien ne le disait. La table des
décisions (`annotations`), elle, était lue — mais ne couvrait ni les fiches ni
les relations, et restait vide.

Ces tests tiennent la règle confirmée par Julien le 21/09 : `ecarte` retire,
`jamais_relu`, `retenu` et `a_revoir` laissent passer ce que les règles
admettent, et un verdict n'OUVRE jamais ce que les règles ferment. Le premier
bloc joue la VRAIE publication, en sous-processus, sur la base d'épreuve de la
CI : c'est le garde-fou qui a manqué à `validation_status`.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from collectors.verdict import (A_REVOIR, ECARTE, JAMAIS_RELU, OBJETS, RETENU,
                                VERDICTS, ecarte, verdict_de)

ROOT = Path(__file__).resolve().parent.parent


# ── Vocabulaire ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ancien, neuf", [
    ("pending", JAMAIS_RELU), ("unverified", JAMAIS_RELU), ("draft", JAMAIS_RELU),
    ("reviewing", A_REVOIR), ("validated", RETENU), ("verified", RETENU),
    ("published", RETENU), ("rejected", ECARTE),
])
def test_les_anciens_mots_restent_compris(ancien, neuf):
    assert verdict_de(ancien) == neuf


def test_labsence_de_decision_vaut_jamais_relu():
    assert verdict_de(None) == JAMAIS_RELU
    assert verdict_de("") == JAMAIS_RELU


def test_un_mot_inconnu_nest_pas_devine():
    # Ni signé à la place de quelqu'un, ni retiré sans que personne l'ait décidé.
    assert verdict_de("peut-être") is None
    assert not ecarte("peut-être")


def test_seul_ecarte_retire():
    assert [v for v in VERDICTS if ecarte(v)] == [ECARTE]


# ── La vraie publication ─────────────────────────────────────────────────────
# Un objet publiable de chaque type d'`OBJETS`, sur la base d'épreuve de la CI.

def _graines(conn) -> dict[str, tuple[int, str, str]]:
    """{objet: (id, fichier du snapshot, texte qui le reconnaît)}."""
    def id_de(sql, *p):
        return conn.execute(sql, p).fetchone()[0]
    boulangerie = id_de("SELECT id FROM entities WHERE name = ?", "Boulangerie d'épreuve")
    mairie = id_de("SELECT id FROM entities WHERE name = ?", "Mairie d'épreuve")
    acte = conn.execute(
        "INSERT INTO events (type, date, title, content, source) VALUES "
        "('deliberation', '2026-02-01', 'Délibération d''épreuve', "
        "'Le conseil décide.', 'interieur')").lastrowid
    flux = conn.execute(
        "INSERT INTO financial_flows (from_id, to_id, type, year, amount, description,"
        " source, confidence) VALUES (?, ?, 'subvention', 2025, 1500,"
        " 'Subvention d''épreuve', 'ofgl', 'verified')", (mairie, boulangerie)).lastrowid
    marche = conn.execute(
        "INSERT INTO marches_publics (acheteur_siren, acheteur_nom, titulaire_id,"
        " titulaire_nom, objet, montant, date_notif, source, confidence) VALUES"
        " ('219900010', 'Testonville', ?, 'Boulangerie d''épreuve', 'Marché d''épreuve',"
        " 9000, '2026-03-01', 'DECP', 'verified')", (boulangerie,)).lastrowid
    # PAS le mandat de maire : l'écarter retire aussi l'élue (il est son seul
    # rôle civique), et la relation tomberait faute d'extrémité publiée — elle
    # passerait le test pour la mauvaise raison. Ce lien-ci relie deux fiches
    # publiques par elles-mêmes.
    lien = conn.execute(
        "INSERT INTO relations (from_id, to_id, relation_type, confidence)"
        " VALUES (?, ?, 'prestataire', 'verified')", (boulangerie, mairie)).lastrowid
    conn.commit()
    return {
        "entity":       (boulangerie, "entities.json", "Boulangerie d'épreuve"),
        "relation":     (lien, "relations.json", '"prestataire"'),
        "deliberation": (acte, "events.json", "Délibération d'épreuve"),
        "flow":         (flux, "flows.json", "Subvention d'épreuve"),
        "marche":       (marche, "marches.json", "Marché d'épreuve"),
    }


def _env(db: Path) -> dict:
    return {**os.environ,
            "VIGIE_INSTANCE": str(ROOT / "tests" / "instance_test.json"),
            "VIGIE_RULES": str(ROOT / "config" / "publication_rules.exemple.json"),
            "VIGIE_DB": str(db)}


def _publier(db: Path, out: Path) -> dict[str, str]:
    """`build_snapshot` et lui seul : `main()` régénère aussi les libellés du
    site (`instance.js`), qu'un test n'a pas à réécrire avec « Testonville »."""
    code = ("import sys; sys.path.insert(0, 'scripts'); "
            "import build_public_snapshot as b; from pathlib import Path; "
            f"b.build_snapshot(Path({str(out)!r}))")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=_env(db),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    return {f.name: f.read_text(encoding="utf-8") for f in out.glob("*.json")}


@pytest.fixture(scope="module")
def epreuve(tmp_path_factory):
    """La base de la CI, plus un acte, un flux et un marché publiables."""
    dossier = tmp_path_factory.mktemp("epreuve")
    db = dossier / "epreuve.db"
    r = subprocess.run([sys.executable, "tests/amorcer_base_ci.py"], cwd=ROOT,
                       env=_env(db), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    conn = sqlite3.connect(db)
    graines = _graines(conn)
    conn.close()
    return db, graines


def _copie_avec(epreuve, tmp_path, decisions: dict[str, str]) -> Path:
    db, graines = epreuve
    copie = tmp_path / "base.db"
    shutil.copy(db, copie)
    conn = sqlite3.connect(copie)
    for objet, verdict in decisions.items():
        conn.execute("INSERT INTO annotations (object_type, object_id, review_status)"
                     " VALUES (?, ?, ?)", (objet, graines[objet][0], verdict))
    conn.commit()
    conn.close()
    return copie


def test_chaque_type_a_une_graine(epreuve):
    # Un type ajouté à OBJETS sans graine ici ne serait jamais éprouvé.
    assert set(epreuve[1]) == set(OBJETS)


def test_sans_decision_tout_est_publie(epreuve, tmp_path):
    sortie = _publier(_copie_avec(epreuve, tmp_path, {}), tmp_path / "snap")
    for objet, (_, fichier, marque) in epreuve[1].items():
        assert marque in sortie[fichier], f"{objet} absent sans aucune décision"


def test_ecarte_retire_chaque_type_de_la_publication(epreuve, tmp_path):
    """LE garde-fou. Tous les types sauf la fiche d'abord — écarter la
    boulangerie retirerait aussi son flux et délierait son marché, et ces
    deux-là passeraient alors pour la mauvaise raison."""
    autres = [o for o in OBJETS if o != "entity"]
    sortie = _publier(_copie_avec(epreuve, tmp_path, {o: ECARTE for o in autres}),
                      tmp_path / "snap")
    for objet in autres:
        _, fichier, marque = epreuve[1][objet]
        assert marque not in sortie[fichier], \
            f"« {objet} » écarté mais toujours publié : la publication ne lit pas son verdict"

    (tmp_path / "seule").mkdir()
    sortie = _publier(_copie_avec(epreuve, tmp_path / "seule", {"entity": ECARTE}),
                      tmp_path / "seule" / "snap")
    _, fichier, marque = epreuve[1]["entity"]
    assert marque not in sortie[fichier]
    exclusions = json.loads(sortie["stats.json"])["exclusions"]["entities"]
    assert exclusions["rejete_en_atelier"] == 1


def test_les_autres_verdicts_laissent_passer(epreuve, tmp_path):
    """Une seule publication : les verdicts tournent sur les cinq types, chacun
    posé au moins une fois — l'ancien mot `validated` compris."""
    autres = [JAMAIS_RELU, RETENU, A_REVOIR, "validated"]
    poses = {o: autres[i % len(autres)] for i, o in enumerate(OBJETS)}
    assert set(poses.values()) == set(autres)
    sortie = _publier(_copie_avec(epreuve, tmp_path, poses), tmp_path / "snap")
    for objet, (_, fichier, marque) in epreuve[1].items():
        assert marque in sortie[fichier], f"« {objet} » retiré par « {poses[objet]} »"


def test_une_relation_ecartee_ne_justifie_plus_la_personne(epreuve, tmp_path):
    """Le mandat de maire est le seul rôle civique de l'élue d'épreuve : jugé
    faux, il ne peut pas continuer de la rendre publiable."""
    copie = _copie_avec(epreuve, tmp_path, {})
    conn = sqlite3.connect(copie)
    conn.execute("INSERT INTO annotations (object_type, object_id, review_status) "
                 "SELECT 'relation', id, 'ecarte' FROM relations WHERE relation_type='maire'")
    conn.commit()
    conn.close()
    sortie = _publier(copie, tmp_path / "snap")
    assert "Élue de Testonville" not in sortie["entities.json"]
    assert '"maire"' not in sortie["relations.json"]


def test_retenu_nouvre_pas_ce_que_les_regles_ferment(epreuve, tmp_path):
    """« Une habitante » n'a aucun rôle civique : `retenu` ne la publie pas."""
    db, _ = epreuve
    copie = _copie_avec(epreuve, tmp_path, {})
    conn = sqlite3.connect(copie)
    habitante = conn.execute("SELECT id FROM entities WHERE name = 'Une habitante'"
                             ).fetchone()[0]
    conn.execute("INSERT INTO annotations (object_type, object_id, review_status)"
                 " VALUES ('entity', ?, 'retenu')", (habitante,))
    conn.commit()
    conn.close()
    assert "Une habitante" not in _publier(copie, tmp_path / "snap")["entities.json"]


# ── L'atelier : un seul écrivain des décisions ───────────────────────────────

pytest.importorskip("fastapi", reason="job « tests-deps » : pip install -r requirements.txt")
from fastapi.testclient import TestClient  # noqa: E402

VALIDEUR = {"id": 1, "email": "valide@exemple.fr", "role": "validator"}
CONTRIB = {"id": 2, "email": "propose@exemple.fr", "role": "contributor"}


@pytest.fixture
def atelier(tmp_path, monkeypatch, schema_sql):
    chemin = tmp_path / "instance.db"
    conn = sqlite3.connect(chemin)
    conn.executescript(schema_sql)
    for u in (VALIDEUR, CONTRIB):
        conn.execute("INSERT INTO users(id, email, password_hash, role) VALUES(?,?,?,?)",
                     (u["id"], u["email"], "x", u["role"]))
    fiche = conn.execute("INSERT INTO entities(type, name) VALUES('association', "
                         "'Les Amis du Four')").lastrowid
    autre = conn.execute("INSERT INTO entities(type, name) VALUES('service', "
                         "'Mairie')").lastrowid
    lien = conn.execute("INSERT INTO relations(from_id, to_id, relation_type) "
                        "VALUES(?, ?, 'subventionné')", (fiche, autre)).lastrowid
    conn.commit()
    conn.close()

    import api
    from api_auth import require_auth
    from collectors import db as db_mod
    monkeypatch.setattr(api, "DB_PATH", chemin)
    monkeypatch.setattr(db_mod, "DB_PATH", chemin)
    monkeypatch.setenv("ADMIN_KEY", "cle-de-test")
    client = TestClient(api.app, headers={"x-admin-key": "cle-de-test"})

    def en_tant_que(user):
        api.app.dependency_overrides[require_auth] = lambda: user
        return client

    def sql(requete, params=()):
        c = sqlite3.connect(chemin)
        c.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in c.execute(requete, params).fetchall()]
        finally:
            c.close()

    yield {"en_tant_que": en_tant_que, "sql": sql, "fiche": fiche, "lien": lien}
    api.app.dependency_overrides.clear()


def _decision(atelier, objet, oid):
    lignes = atelier["sql"]("SELECT review_status, reviewed_by, note FROM annotations "
                            "WHERE object_type=? AND object_id=?", (objet, oid))
    return lignes[0] if lignes else None


class TestDecisionSurUneFiche:
    def test_ecarter_une_fiche_pose_une_decision_et_entre_dans_son_historique(self, atelier):
        f = atelier["fiche"]
        r = atelier["en_tant_que"](VALIDEUR).patch(
            f"/api/atelier/annotations/entity/{f}",
            json={"review_status": "ecarte", "note": "doublon de la fiche SIRENE"})
        assert r.status_code == 200, r.text
        assert _decision(atelier, "entity", f) == {
            "review_status": "ecarte", "reviewed_by": VALIDEUR["email"],
            "note": "doublon de la fiche SIRENE"}
        historique = atelier["sql"]("SELECT field FROM audit_log WHERE entity_id=?", (f,))
        assert historique == [{"field": f"entity/{f}"}]

    def test_le_bouton_de_la_file_pose_la_meme_decision(self, atelier):
        f = atelier["fiche"]
        r = atelier["en_tant_que"](VALIDEUR).patch(
            f"/api/atelier/entities/{f}/status", json={"verdict": "retenu"})
        assert r.status_code == 200, r.text
        assert r.json()["verdict"] == "retenu"
        assert _decision(atelier, "entity", f)["review_status"] == "retenu"
        # Et plus rien n'écrit la colonne gelée.
        assert atelier["sql"]("SELECT validation_status FROM entities WHERE id=?",
                              (f,))[0]["validation_status"] == "unverified"

    def test_un_ancien_mot_est_range_dans_le_vocabulaire_neuf(self, atelier):
        f = atelier["fiche"]
        r = atelier["en_tant_que"](VALIDEUR).patch(
            f"/api/atelier/entities/{f}/status", json={"validation_status": "rejected"})
        assert r.status_code == 200
        assert _decision(atelier, "entity", f)["review_status"] == "ecarte"

    def test_un_mot_inconnu_est_refuse(self, atelier):
        r = atelier["en_tant_que"](VALIDEUR).patch(
            f"/api/atelier/annotations/entity/{atelier['fiche']}",
            json={"review_status": "bof"})
        assert r.status_code == 400
        assert "jamais_relu" in r.text

    def test_le_contributeur_note_mais_ne_tranche_pas(self, atelier):
        f = atelier["fiche"]
        client = atelier["en_tant_que"](CONTRIB)
        assert client.patch(f"/api/atelier/annotations/entity/{f}",
                            json={"review_status": "ecarte"}).status_code == 403
        assert client.patch(f"/api/atelier/annotations/entity/{f}",
                            json={"note": "adresse ancienne ?"}).status_code == 200
        assert _decision(atelier, "entity", f)["review_status"] == "jamais_relu"

    def test_une_decision_de_fiche_ne_porte_ni_fiabilite_ni_correction(self, atelier):
        f = atelier["fiche"]
        client = atelier["en_tant_que"](VALIDEUR)
        for corps in ({"confidence": "probable"}, {"corrections": {"name": "X"}}):
            r = client.patch(f"/api/atelier/annotations/entity/{f}", json=corps)
            assert r.status_code == 400, corps

    def test_on_ne_decide_pas_dun_objet_qui_nexiste_pas(self, atelier):
        client = atelier["en_tant_que"](VALIDEUR)
        for objet in ("entity", "relation"):
            r = client.patch(f"/api/atelier/annotations/{objet}/99999",
                             json={"review_status": "ecarte"})
            assert r.status_code == 404

    def test_une_relation_se_decide_aussi(self, atelier):
        lien = atelier["lien"]
        r = atelier["en_tant_que"](VALIDEUR).patch(
            f"/api/atelier/annotations/relation/{lien}", json={"review_status": "ecarte"})
        assert r.status_code == 200
        assert _decision(atelier, "relation", lien)["review_status"] == "ecarte"

    def test_la_file_de_travail_suit_le_verdict(self, atelier):
        f = atelier["fiche"]
        client = atelier["en_tant_que"](VALIDEUR)
        a_relire = client.get("/api/atelier/workqueue").json()
        assert f in [i["id"] for i in a_relire["items"]]
        client.patch(f"/api/atelier/entities/{f}/status", json={"verdict": "ecarte"})
        assert f not in [i["id"] for i in client.get("/api/atelier/workqueue").json()["items"]]
        ecartees = client.get("/api/atelier/workqueue?status=ecarte").json()["items"]
        assert [(i["id"], i["verdict"]) for i in ecartees] == [(f, "ecarte")]
        stats = client.get("/api/atelier/stats").json()
        assert stats["ecarte"] == 1 and stats["jamais_relu"] == 1

    def test_la_fiche_dit_son_verdict(self, atelier):
        f = atelier["fiche"]
        client = atelier["en_tant_que"](VALIDEUR)
        client.patch(f"/api/atelier/entities/{f}/status",
                     json={"verdict": "a_revoir", "note": "siège déménagé ?"})
        e = client.get(f"/api/atelier/entities/{f}").json()
        assert (e["verdict"], e["verdict_note"], e["verdict_par"]) == \
            ("a_revoir", "siège déménagé ?", VALIDEUR["email"])
        assert "origine" in e and "validation_status" not in e

    def test_le_formulaire_refuse_le_statut_au_lieu_de_lignorer(self, atelier):
        """Un geste qui ne fait rien derrière « Sauvegardé ✓ », c'est le lot 1."""
        f = atelier["fiche"]
        client = atelier["en_tant_que"](VALIDEUR)
        verrou = client.get(f"/api/atelier/entities/{f}").json()["updated_at"]
        r = client.patch(f"/api/atelier/entities/{f}",
                         json={"updated_at": verrou, "validation_status": "verified"})
        assert r.status_code == 400
        assert "décision" in r.text


# ── Migration ────────────────────────────────────────────────────────────────

def test_la_migration_range_les_anciens_mots_et_les_anciens_statuts(
        tmp_path, monkeypatch, schema_sql, capsys):
    chemin = tmp_path / "ancienne.db"
    conn = sqlite3.connect(chemin)
    conn.executescript(schema_sql)
    conn.execute("INSERT INTO users(id, email, password_hash, role) "
                 "VALUES(7, 'ancienne@exemple.fr', 'x', 'validator')")
    ids = {}
    for nom, statut in (("Rejetée", "rejected"), ("Vérifiée", "verified"),
                        ("Saisie", "validated"), ("Intacte", "unverified")):
        ids[nom] = conn.execute("INSERT INTO entities(type, name, validation_status) "
                                "VALUES('business', ?, ?)", (nom, statut)).lastrowid
    conn.execute("INSERT INTO audit_log(user_id, entity_id, field, action, new_value) "
                 "VALUES(7, ?, 'validation_status', 'update', 'rejected')",
                 (ids["Rejetée"],))
    conn.execute("INSERT INTO annotations(object_type, object_id, review_status) "
                 "VALUES('flow', 1, 'rejected'), ('marche', 2, 'pending')")
    conn.commit()
    conn.close()

    from collectors import db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", chemin)
    from scripts import migrer_verdicts as m

    assert m.run(appliquer=False) == {"mots": 2, "decisions": 2, "a_la_main": 1}
    assert "SORTIRONT" in capsys.readouterr().out
    m.run(appliquer=True)

    lire = sqlite3.connect(chemin)
    decisions = dict(lire.execute(
        "SELECT object_type || ':' || object_id, review_status FROM annotations"))
    assert decisions == {"flow:1": "ecarte", "marche:2": "jamais_relu",
                         f"entity:{ids['Rejetée']}": "ecarte",
                         f"entity:{ids['Vérifiée']}": "retenu"}
    auteur = lire.execute("SELECT reviewed_by FROM annotations WHERE object_type='entity'"
                          " AND object_id=?", (ids["Rejetée"],)).fetchone()[0]
    assert auteur == "ancienne@exemple.fr"
    # `validated` disait « créée à la main » : une origine, pas une signature.
    assert lire.execute("SELECT origine FROM entities WHERE id=?",
                        (ids["Saisie"],)).fetchone()[0] == "atelier"
    lire.close()
    # Rejouée : rien à faire.
    assert m.run(appliquer=False) == {"mots": 0, "decisions": 0, "a_la_main": 1}


# ── Origine d'une fiche ──────────────────────────────────────────────────────

def test_lorigine_dune_fiche_se_deduit_de_ce_qui_latteste(base):
    from scripts.classer_origine import classer_entites

    def fiche(type_, nom, origine=None):
        return base.execute("INSERT INTO entities(type, name, origine) VALUES(?,?,?)",
                            (type_, nom, origine)).lastrowid
    sirene = fiche("business", "SARL Four")
    base.execute("INSERT INTO businesses(entity_id, siren) VALUES(?, '123456789')", (sirene,))
    lue = fiche("person", "Nommée dans un PV")
    acte = base.execute("INSERT INTO events(type, title, source, origine) "
                        "VALUES('deliberation', 'D', 'CM 2026', 'verbatim')").lastrowid
    base.execute("INSERT INTO event_entities(event_id, entity_id, role) VALUES(?,?,'sujet')",
                 (acte, lue))
    dirigeant = fiche("person", "Dirigeant aussi cité")
    base.execute("INSERT INTO relations(from_id, to_id, relation_type, source) "
                 "VALUES(?, ?, 'dirigeant', 'sirene')", (dirigeant, sirene))
    base.execute("INSERT INTO event_entities(event_id, entity_id, role) VALUES(?,?,'sujet')",
                 (acte, dirigeant))
    mairie = fiche("service", "Mairie")
    base.execute("INSERT INTO relations(from_id, to_id, relation_type, source) "
                 "VALUES(?, ?, 'maire', 'rne')", (dirigeant, mairie))
    main = fiche("association", "Saisie à la main", "atelier")
    orpheline = fiche("person", "Sans aucune trace")
    base.commit()

    a_ecrire, non_classees = classer_entites(base)
    assert a_ecrire[sirene] == "institutionnel"
    assert a_ecrire[lue] == "verbatim"
    assert a_ecrire[dirigeant] == "institutionnel"   # le registre prime sur la lecture
    assert mairie not in a_ecrire                     # un lien n'atteste pas un service
    assert main not in a_ecrire                       # une saisie n'est jamais reclassée
    assert orpheline not in a_ecrire                  # pas de preuve, pas de classement
    assert non_classees == {"service": 1, "person": 1}


# ── Export et import des décisions ───────────────────────────────────────────

def test_les_decisions_de_fiche_et_de_relation_voyagent(tmp_path, schema_sql, monkeypatch):
    """Deux ateliers, deux bases aux identifiants différents : le verdict suit
    la fiche et la relation par leur clé naturelle."""
    from collectors import saisies as _saisies
    from scripts.exporter_decisions import exporter
    from scripts.importer_decisions import importer
    monkeypatch.setattr(_saisies, "charger", lambda: {"saisies": []})

    def remplir(chemin, decalage):
        c = sqlite3.connect(chemin)
        c.executescript(schema_sql)
        for _ in range(decalage):
            c.execute("INSERT INTO entities(type, name) VALUES('place', hex(randomblob(4)))")
        a = c.execute("INSERT INTO entities(type, name) VALUES('business', 'SARL Four')").lastrowid
        c.execute("INSERT INTO businesses(entity_id, siren) VALUES(?, '123456789')", (a,))
        b = c.execute("INSERT INTO entities(type, name, commune) VALUES('service', 'Mairie', "
                      "'Testonville')").lastrowid
        r = c.execute("INSERT INTO relations(from_id, to_id, relation_type) "
                      "VALUES(?, ?, 'prestataire')", (a, b)).lastrowid
        c.commit()
        return c, a, r

    ici, fiche_ici, lien_ici = remplir(tmp_path / "ici.db", 0)
    ici.execute("INSERT INTO annotations(object_type, object_id, review_status, note) "
                "VALUES('entity', ?, 'ecarte', 'doublon'), ('relation', ?, 'rejected', NULL)",
                (fiche_ici, lien_ici))
    ici.commit()
    exporter(ici, tmp_path / "decisions", sans_personnes=False)

    la_bas, fiche_la, lien_la = remplir(tmp_path / "la.db", 5)
    assert fiche_la != fiche_ici
    rapport = importer(la_bas, tmp_path / "decisions", appliquer=True, forcer=False)
    la_bas.commit()
    assert rapport.applique == 2 and not rapport.non_rattachees
    assert dict(la_bas.execute(
        "SELECT object_type, review_status FROM annotations")) == {
            "entity": "ecarte", "relation": "ecarte"}
