"""« Le conseil en clair » : vérifier un relevé, ne publier que ce qui est retenu.

Ce que ces tests protègent tient en deux phrases. Un relevé dont un seul chiffre
n'est pas retrouvé dans ses pièces ne peut ni être retenu ni être publié. Une
feuille n'est publiée que si un validateur l'a RETENUE — la règle inverse des
lignes importées, décidée le 30/09/2026.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from collectors.en_clair.verifier import verifier

PV = ("PROCÈS-VERBAL DU CONSEIL MUNICIPAL du 10 janvier 2026.\n"
      "Présents : 3. Votants : 3.\n"
      "SUBVENTION AU CLUB\n"
      "Le Conseil Municipal, après en avoir délibéré à l’unanimité :\n"
      "DECIDE d’attribuer au club une subvention de 1 200 €.\n"
      "REGLEMENT DU CIMETIERE\n"
      "Le Conseil Municipal, après en avoir délibéré à l’unanimité :\n"
      "APPROUVE le règlement du cimetière.\n")


def _releve(texte_apres="Le club reçoit 1 200 € pour sa saison."):
    return {
        "code": "cm",
        "seance": {"assemblee": "Conseil municipal de Fictiville",
                   "assemblee_court": "Conseil municipal de Fictiville",
                   "date": "2026-01-10", "votants": 3},
        "origine": {"releve": "test", "le": "2026-01-11", "statut": "a_relire", "relu_par": None},
        "sources": {"pv": "data/pv.txt"},
        "sources_url": {"pv": "https://fictiville.invalid/pv.pdf"},
        "marque_acte_ordinale": r"apr[eè]s en avoir d[ée]lib[ée]r[ée]",
        "actes": [
            {"n": 1, "objet": "Subvention au club", "vote": {"unanimite": True},
             "citation": "DECIDE d’attribuer au club une subvention de 1 200 €.", "montants": ["1 200"]},
            {"n": 2, "objet": "Règlement du cimetière", "vote": {"unanimite": True},
             "citation": "APPROUVE le règlement du cimetière."},
        ],
        "anomalies_seance": ["Le PV ne dit pas qui préside."],
        "calculs": [{"valeur": "2", "formule": "n_actes", "dit": "délibérations"}],
        "en_clair": {
            "avant": {"statut": "non_publie", "avertissement": "Aucune convocation publiée.",
                      "titre": "Samedi, à la mairie", "chapeau": "Séance publique.",
                      "ordre_du_jour": ["Subvention", "Cimetière"], "pied": "Reconstitué."},
            "apres": {"titre": "Ce qui a été décidé", "chapeau": "Séance ordinaire.",
                      "chiffres": [{"valeur": "2", "dit": "délibérations"}],
                      "items": [{"titre": "Le club aidé", "texte": texte_apres, "actes": [1]}],
                      "aussi": [{"texte": "Règlement du cimetière approuvé.", "actes": [2]}],
                      "pied": "Source : procès-verbal."},
        },
    }


@pytest.fixture
def instance(tmp_path):
    """Une instance minimale : le vérificateur la reconnaît à `collectors/`."""
    racine = tmp_path / "instance"
    (racine / "collectors").mkdir(parents=True)
    (racine / "data").mkdir()
    (racine / "data" / "pv.txt").write_text(PV)
    d = racine / "data" / "conseils" / "2026-01-10-cm"
    d.mkdir(parents=True)
    (d / "releve.json").write_text(json.dumps(_releve(), ensure_ascii=False))
    return racine


def _chemin(instance):
    return instance / "data" / "conseils" / "2026-01-10-cm" / "releve.json"


# ── le vérificateur ──────────────────────────────────────────────────────────

def test_un_releve_conforme_passe(instance):
    assert verifier(_chemin(instance)) == []


def test_un_chiffre_invente_est_refuse(instance):
    _chemin(instance).write_text(json.dumps(_releve("Le club reçoit 1 300 €."), ensure_ascii=False))
    fautes = verifier(_chemin(instance))
    assert any("1 300" in f for f in fautes)


@pytest.mark.parametrize("formule", [
    "().__class__.__base__.__subclasses__()",      # la sortie classique d'un eval « réduit »
    "__import__('os').system('id')",
    "open('/etc/passwd').read()",
    "actes.clear()",
    "jours.__globals__",
    "2 ** 99999999",
    "sum(1 for a in actes for b in actes for c in actes)",
])
def test_une_formule_qui_n_est_pas_un_calcul_est_une_faute_pas_du_code(instance, formule):
    """Un relevé est rédigé d'après des documents que personne ne maîtrise, et le
    vérificateur tourne dans l'API de l'atelier : sa formule se CALCULE, elle ne
    s'exécute pas."""
    r = _releve()
    r["calculs"] = [{"valeur": "2", "formule": formule, "dit": "délibérations"}]
    _chemin(instance).write_text(json.dumps(r, ensure_ascii=False))
    fautes = verifier(_chemin(instance))
    assert any(f.startswith("CALCUL") and "formule refusée" in f for f in fautes), fautes


@pytest.mark.parametrize("formule, valeur", [
    ("n_actes", "2"), ("unanimes", "2"), ("round((1 - 20914 / 29835) * 100)", "30"),
    ("sum(1 for a in actes if (a['vote'] or {}).get('unanimite'))", "2"),
    ("sum(1 for a in actes if 'club' in a['objet'] or 'Poste' in a['objet'])", "1"),
    ("jours('2026-09-23','2026-10-01')", "8"), ("round(163500 - 123555.80, 2)", "39944,20"),
])
def test_les_formules_ordinaires_se_calculent_toujours(instance, formule, valeur):
    r = _releve()
    r["calculs"].append({"valeur": valeur, "formule": formule, "dit": "essai"})
    _chemin(instance).write_text(json.dumps(r, ensure_ascii=False))
    assert [f for f in verifier(_chemin(instance)) if f.startswith("CALCUL")] == []


def _avec_dit(instance, citation, actes):
    r = _releve()
    r["en_clair"]["comprendre"] = {
        "titre": "Comprendre la séance",
        "debats": [{"titre": "Le club", "texte": "Le maire explique la subvention.",
                    "citation": citation, "actes": actes}],
        "a_suivre": [{"texte": "Le versement au club.", "actes": [1]}],
        "lexique": [{"terme": "Subvention", "definition": "une aide publique."}],
    }
    _chemin(instance).write_text(json.dumps(r, ensure_ascii=False))
    return r


def test_une_parole_rapportee_est_retrouvee_dans_son_acte(instance):
    _avec_dit(instance, "DECIDE d’attribuer au club une subvention de 1 200 €.", [1])
    assert verifier(_chemin(instance)) == []


def test_une_parole_inventee_est_refusee(instance):
    _avec_dit(instance, "DECIDE de ne rien attribuer au club.", [1])
    assert any(f.startswith("DIT") and "introuvable" in f for f in verifier(_chemin(instance)))


def test_une_parole_qui_precede_sa_deliberation_est_admise(tmp_path):
    """Dans un PV de conseil communautaire, le débat vient AVANT « Délibération
    n°1/2026 » : la borne stricte le refuserait à tort."""
    racine = tmp_path / "cc"
    (racine / "collectors").mkdir(parents=True)
    (racine / "data").mkdir()
    (racine / "data" / "pv.txt").write_text(
        "PV du conseil communautaire. Présents : 3. Votants : 3.\n"
        "I. Pacte. M. X propose de différer le vote.\n"
        "Délibération n°1/2026 Le Conseil, après en avoir délibéré à l'unanimité, APPROUVE le pacte.\n"
        "II. Tourisme. Délibération n°2/2026 Le Conseil APPROUVE le choix.\n")
    r = _releve()
    r.pop("marque_acte_ordinale")
    r["marque_acte"] = "Délibération n°{n}/2026"
    r["actes"] = [{"n": 1, "objet": "Pacte", "vote": {"unanimite": True}, "citation": "APPROUVE le pacte."},
                  {"n": 2, "objet": "Tourisme", "vote": {"unanimite": True}, "citation": "APPROUVE le choix."}]
    r["calculs"] = []
    r["en_clair"]["apres"]["chiffres"] = []
    r["en_clair"]["apres"]["items"] = [{"titre": "Le pacte", "texte": "Approuvé.", "actes": [1]}]
    r["en_clair"]["apres"]["aussi"] = []
    r["en_clair"]["comprendre"] = {"debats": [
        {"titre": "Différer ?", "texte": "Un élu propose d'attendre.",
         "citation": "M. X propose de différer le vote.", "actes": [1]}]}
    d = racine / "data" / "conseils" / "2026-01-10-cc"
    d.mkdir(parents=True)
    (d / "releve.json").write_text(json.dumps(r, ensure_ascii=False))
    assert verifier(d / "releve.json") == []


def test_la_feuille_comprendre_est_rendue_et_les_documents_deviennent_la_quatrieme(instance):
    from collectors.en_clair.rendu import feuilles, page_erreurs
    r = _avec_dit(instance, "APPROUVE le règlement du cimetière.", [2])
    html = feuilles(r) + page_erreurs(r)
    assert html.count('class="sheet') == 4
    assert "Ce qui s’est dit" in html and "À suivre" in html and "Les mots de la séance" in html
    assert "Feuille 4 · les documents" in html


# ── la publication ───────────────────────────────────────────────────────────

def _seance(conn) -> int:
    sid = conn.execute("INSERT INTO events(type, date, title) VALUES "
                       "('conseil_municipal', '2026-01-10', 'Conseil municipal')").lastrowid
    conn.commit()
    return sid


def _verdict(conn, sid, statut, instance=None):
    """Un verdict posé comme l'atelier le pose : retenir signe l'empreinte du relevé lu."""
    from collectors.verdict import empreinte
    emp = empreinte(_chemin(instance).read_bytes()) if instance and statut == "retenu" else None
    conn.execute("INSERT INTO annotations(object_type, object_id, review_status, reviewed_by, "
                 "reviewed_at, empreinte) VALUES('en_clair', ?, ?, 'relectrice@fictiville.invalid', "
                 "'2026-01-12 10:00:00', ?)", (sid, statut, emp))
    conn.commit()


@pytest.mark.parametrize("statut, publiee", [
    (None, False), ("a_revoir", False), ("ecarte", False), ("retenu", True)])
def test_seule_une_feuille_retenue_est_publiee(base, instance, tmp_path, statut, publiee):
    from scripts.build_public_snapshot import export_en_clair
    sid = _seance(base)
    if statut:
        _verdict(base, sid, statut, instance)
    out = tmp_path / "snapshot"

    r = export_en_clair(base, out, instance)

    index = json.loads((out / "conseils.json").read_text())
    assert r["publiees"] == int(publiee) == index["total"]
    fichier = out / "conseils" / "2026-01-10_conseil-municipal.html"
    assert fichier.exists() is publiee
    if publiee:
        html = fichier.read_text()
        assert "À RELIRE" not in html, "une feuille retenue ne porte plus le tampon"
        assert "relectrice@" not in html, "l'adresse du relecteur n'est pas publiée"
        assert "Ce que les documents publics ont de faux" in html


def test_une_feuille_retenue_devenue_fausse_sort_du_site(base, instance, tmp_path):
    """La source a changé depuis la relecture : la feuille n'est plus vraie."""
    from scripts.build_public_snapshot import export_en_clair
    _verdict(base, _seance(base), "retenu", instance)
    (instance / "data" / "pv.txt").write_text(PV.replace("1 200 €", "1 500 €"))

    r = export_en_clair(base, tmp_path / "snapshot", instance)

    assert r["publiees"] == 0
    assert r["en_faute"] == ["2026-01-10-cm"]


def test_un_releve_reecrit_apres_relecture_ne_sort_plus(base, instance, tmp_path):
    """Le défaut du 01/10/2026 : réécrit après avoir été retenu, un relevé
    serait sorti signé « relu à l'atelier » sans que personne l'ait relu."""
    from scripts.build_public_snapshot import export_en_clair
    _verdict(base, _seance(base), "retenu", instance)
    _chemin(instance).write_text(json.dumps(_releve("Le club reçoit 1 200 € cette année."),
                                            ensure_ascii=False))
    assert verifier(_chemin(instance)) == [], "le relevé réécrit reste conforme"

    r = export_en_clair(base, tmp_path / "snapshot", instance)

    assert (r["publiees"], r["modifies"]) == (0, ["2026-01-10-cm"])


def test_les_numeros_d_actes_menent_a_l_acte_publie_par_sa_cle(base, instance, tmp_path):
    """03/10/2026 : une séance en clair relève ses actes par numéro. Le n°1 est
    publié, il devient un lien vers sa clé datée et un retour vers la séance ;
    le n°2 ne l'est pas, il reste du texte."""
    from collectors.citations import index_de, lignes_en_base
    from collectors.graphe import Graphe
    from scripts.build_public_snapshot import export_en_clair
    _verdict(base, _seance(base), "retenu", instance)
    un = base.execute("INSERT INTO events(type, date, title, source, metadata) VALUES("
                      "'deliberation', '2026-01-10', 'Subvention au club', 'x', "
                      "'{\"numero_acte\": \"1\"}')").lastrowid
    base.execute("INSERT INTO events(type, date, title, source, metadata) VALUES("
                 "'deliberation', '2026-01-10', 'Cimetière', 'x', '{\"numero_acte\": \"2\"}')")
    graphe = Graphe(index_de(lignes_en_base(base), {un}))

    export_en_clair(base, tmp_path / "snapshot", instance, graphe)

    html = (tmp_path / "snapshot" / "conseils" / "2026-01-10_conseil-municipal.html").read_text()
    assert '<a href="/deliberations/2026#c-2026-1">1</a>' in html
    assert 'href="/deliberations/2026#c-2026-2"' not in html, "jamais un lien vers un acte non publié"
    assert graphe.retours["c-2026-1"] == [{"type": "en_clair", "date": "2026-01-10",
                                           "assemblee": "Conseil municipal de Fictiville",
                                           "fichier": "conseils/2026-01-10_conseil-municipal.html"}]


def test_un_verdict_sans_empreinte_ne_publie_pas(base, instance, tmp_path):
    """Retenu avant l'empreinte et pas repris : on ne sait pas ce qui a été relu."""
    from scripts.build_public_snapshot import export_en_clair
    _verdict(base, _seance(base), "retenu")
    assert export_en_clair(base, tmp_path / "snapshot", instance)["publiees"] == 0


# ── l'atelier ────────────────────────────────────────────────────────────────

VALIDEUR = {"id": 1, "email": "v@fictiville.invalid", "role": "validator"}
CONTRIB = {"id": 2, "email": "c@fictiville.invalid", "role": "contributor"}


@pytest.fixture
def atelier(tmp_path, monkeypatch, schema_sql, instance):
    # Le job « tests » de la CI n'installe que pytest : l'API y est sautée, et
    # jouée par « tests-deps », qui refuse le moindre test sauté.
    pytest.importorskip("fastapi", reason="job « tests-deps » : pip install -r requirements.txt")
    from fastapi.testclient import TestClient
    chemin = tmp_path / "instance.db"
    conn = sqlite3.connect(chemin)
    conn.executescript(schema_sql)
    for u in (VALIDEUR, CONTRIB):
        conn.execute("INSERT INTO users(id, email, password_hash, role) VALUES(?,?,?,?)",
                     (u["id"], u["email"], "x", u["role"]))
    sid = _seance(conn)
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

    yield {"en_tant_que": en_tant_que, "seance": sid, "instance": instance}
    api.app.dependency_overrides.clear()


def test_la_file_montre_la_seance_verifiee(atelier):
    r = atelier["en_tant_que"](CONTRIB).get("/api/atelier/en-clair")
    assert r.status_code == 200, r.text
    [s] = r.json()
    assert (s["seance_id"], s["fautes"], s["verdict"]) == (atelier["seance"], [], "jamais_relu")
    assert s["erreurs_documents"] == 1


def test_seul_un_validateur_retient(atelier):
    url = f"/api/atelier/annotations/en_clair/{atelier['seance']}"
    assert atelier["en_tant_que"](CONTRIB).patch(url, json={"review_status": "retenu"}).status_code == 403
    r = atelier["en_tant_que"](VALIDEUR).patch(url, json={"review_status": "retenu", "note": "relu"})
    assert r.status_code == 200, r.text
    assert r.json()["review_status"] == "retenu"


def test_retenir_signe_le_releve_lu_et_le_signale_quand_il_change(atelier):
    client = atelier["en_tant_que"](VALIDEUR)
    [s] = client.get("/api/atelier/en-clair").json()
    url = f"/api/atelier/annotations/en_clair/{atelier['seance']}"
    assert client.patch(url, json={"review_status": "retenu",
                                   "empreinte_vue": s["empreinte"]}).status_code == 200
    assert client.get("/api/atelier/en-clair").json()[0]["modifie"] is False

    _chemin(atelier["instance"]).write_text(
        json.dumps(_releve("Le club reçoit 1 200 € cette année."), ensure_ascii=False))
    assert client.get("/api/atelier/en-clair").json()[0]["modifie"] is True
    # Retenir la version qu'on a vue AVANT le changement : refusé.
    r = client.patch(url, json={"review_status": "retenu", "empreinte_vue": s["empreinte"]})
    assert r.status_code == 409


def test_un_releve_en_faute_ne_peut_pas_etre_retenu(atelier):
    _chemin(atelier["instance"]).write_text(
        json.dumps(_releve("Le club reçoit 1 300 €."), ensure_ascii=False))
    r = atelier["en_tant_que"](VALIDEUR).patch(
        f"/api/atelier/annotations/en_clair/{atelier['seance']}", json={"review_status": "retenu"})
    assert r.status_code == 409
    assert "non conforme" in r.text


def test_lapercu_porte_les_trois_feuilles(atelier):
    r = atelier["en_tant_que"](CONTRIB).get("/api/atelier/en-clair/2026-01-10-cm/apercu")
    assert r.status_code == 200
    assert r.text.count('class="sheet"') == 3
    assert atelier["en_tant_que"](CONTRIB).get("/api/atelier/en-clair/..%2Fetc/apercu").status_code in (404, 422)
