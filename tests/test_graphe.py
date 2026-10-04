"""Le graphe des liens au snapshot : vers le bas, vers le haut, dans le temps, en largeur.

Ce que ces tests protègent (03/10/2026) :
  - un dossier publié sort RELIÉ, et la page de l'acte sait qui la cite ;
  - un acte cité qui change après la relecture laisse le dossier PUBLIÉ, avec
    un bandeau — et l'atelier le montre à revoir sans toucher au verdict ;
  - les anciennes ancres `#a{id}` sont servies un cycle par une table d'alias ;
  - l'index des personnes morales ne porte que des SIREN de structures publiées.

Tout passe par une vraie base et par les fonctions de publication réelles.
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

from collectors import dossiers as D
from collectors.citations import index_selon_regles, relier
from collectors.graphe import Graphe

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "dossiers" / "eau.md"
REGLES = {"events": {"public_sources": ["exemple.invalid", "epci.exemple.invalid"],
                     "exclude_types": []}}


@pytest.fixture
def instance(tmp_path, base):
    """Une instance avec le dossier d'épreuve, et les actes de la base de la CI."""
    sys.path.insert(0, str(ROOT / "tests"))
    from amorcer_base_ci import ACTES, SEANCES  # les mêmes actes que la CI
    for type_, date, titre in SEANCES:
        base.execute("INSERT INTO events(type, date, title, source) VALUES(?,?,?,?)",
                     (type_, date, titre, "exemple.invalid"))
    for type_, date, numero, titre, texte, montants, vote in ACTES:
        source = "epci.exemple.invalid" if type_ == "deliberation_cc" else "exemple.invalid"
        base.execute("INSERT INTO events(type, date, title, content, source, source_url, metadata) "
                     "VALUES(?,?,?,?,?,?,?)",
                     (type_, date, titre, texte, source, f"https://{source}/{date}.pdf",
                      json.dumps({"numero_acte": numero, "montants": montants, "vote": vote})))
    base.commit()
    racine = tmp_path / "instance"
    (racine / "dossiers").mkdir(parents=True)
    shutil.copyfile(FIXTURE, racine / "dossiers" / "eau.md")
    return racine


def _retenir(conn, racine, slug="eau"):
    """Ce que fait l'atelier quand un validateur retient : verdict, empreinte, sceau."""
    D.assurer_schema(conn)
    did = D.identifiant(conn, slug, creer=True)
    emp = D.empreinte_de(D.chemin(racine, slug))
    conn.execute("INSERT INTO annotations(object_type, object_id, review_status, reviewed_by, "
                 "reviewed_at, empreinte) VALUES('dossier', ?, 'retenu', 'v', "
                 "'2026-10-01 10:00:00', ?)", (did, emp))
    D.sceller(conn, did, emp, relier(D.chemin(racine, slug).read_text(),
                                     index_selon_regles(conn, REGLES)), "2026-10-01 10:00:00")
    conn.commit()
    return did


def _exporter(conn, racine, out):
    from scripts.build_public_snapshot import export_dossiers
    graphe = Graphe(index_selon_regles(conn, REGLES))
    r = export_dossiers(conn, out, racine, graphe)
    [d] = json.loads((out / "dossiers.json").read_text())["dossiers"] or [None]
    return r, d, graphe


# ── vers le bas ──────────────────────────────────────────────────────────────

def test_un_dossier_publie_sort_relie_avec_ses_citations(base, instance, tmp_path):
    _retenir(base, instance)
    r, d, _ = _exporter(base, instance, tmp_path / "snap")
    assert "/deliberations/2021#c-2021-41" in d["texte"]
    assert r["citations"]["precis"] >= 5 and r["citations"]["non_resolu"] >= 1
    c41 = next(c for c in d["citations"] if c["cle"] == "c-2021-41")
    assert (c41["assemblee"], c41["date"], c41["statut"]) == ("Conseil municipal", "2021-04-14", "precis")
    assert "perime" not in d, "rien n'a changé depuis la relecture"


def test_un_dossier_non_retenu_ne_cite_rien_et_ne_donne_aucun_retour(base, instance, tmp_path):
    r, d, graphe = _exporter(base, instance, tmp_path / "snap")
    assert d is None and r["publies"] == 0
    assert not graphe.retours and not graphe.lacunes, \
        "un renvoi vers un dossier non publié révélerait son existence"


# ── vers le haut ─────────────────────────────────────────────────────────────

def test_les_retours_disent_quel_dossier_et_quelle_partie(base, instance, tmp_path):
    _retenir(base, instance)
    _, _, graphe = _exporter(base, instance, tmp_path / "snap")
    renvois = graphe.retours["c-2021-41"]
    assert {(r["slug"], r["ancre"]) for r in renvois} == {("eau", "l-essentiel"), ("eau", "la-frise")}
    assert graphe.retours["c-2021-04-14"][0]["precis"] is False, "la séance, citée imprécisément"
    graphe.ecrire(tmp_path / "snap", alias={}, personnes_morales={})
    liens = json.loads((tmp_path / "snap" / "liens.json").read_text())
    assert liens["actes"]["c-2021-41"] == renvois


# ── dans le temps ────────────────────────────────────────────────────────────

def test_un_acte_cite_qui_change_laisse_le_dossier_publie_avec_un_bandeau(base, instance, tmp_path):
    _retenir(base, instance)
    base.execute("UPDATE events SET title = title || ' (relu)' WHERE date='2021-04-14' "
                 "AND json_extract(metadata, '$.numero_acte') = '42'")
    base.execute("UPDATE events SET metadata = json_set(metadata, '$.vote', json('{\"unanimite\": false, \"pour\": 9}')) "
                 "WHERE date='2025-04-02' AND type='deliberation_cc'")
    base.commit()
    r, d, _ = _exporter(base, instance, tmp_path / "snap")
    assert r["publies"] == 1 and r["perimes"] == ["eau"], "il a été relu : il RESTE publié"
    assert d["perime"]["relu_le"] == "2026-10-01"
    par_cle = {e["cle"]: e for e in d["perime"]["elements"]}
    assert par_cle["c-2021-42"]["champs"] == ["le titre"]
    assert par_cle["cc-2025-12"]["champs"] == ["le vote"]
    assert all(e["quoi"] == "modifie" for e in par_cle.values())


def test_un_acte_cite_retire_du_site_est_dit_disparu_sans_son_titre(base, instance, tmp_path):
    _retenir(base, instance)
    eid = base.execute("SELECT id FROM events WHERE date='2025-04-02' AND type='deliberation_cc'"
                       ).fetchone()[0]
    base.execute("INSERT INTO annotations(object_type, object_id, review_status) "
                 "VALUES('deliberation', ?, 'ecarte')", (eid,))
    base.commit()
    _, d, _ = _exporter(base, instance, tmp_path / "snap")
    [el] = [e for e in d["perime"]["elements"] if e["cle"] == "cc-2025-12"]
    assert el["quoi"] == "disparu"
    assert "Redevance" not in json.dumps(el, ensure_ascii=False), \
        "un acte retiré du site n'y revient pas par le bandeau d'un dossier"


def test_sans_sceau_on_ne_pretend_rien(base, instance, tmp_path):
    """Un dossier retenu avant le 03/10/2026 n'a pas de sceau : on ne sait pas
    ce qui a été vu, on n'affiche aucun bandeau."""
    did = _retenir(base, instance)
    D.lever_le_sceau(base, did)
    base.execute("UPDATE events SET title = 'autre' WHERE date='2021-04-14'")
    base.commit()
    _, d, _ = _exporter(base, instance, tmp_path / "snap")
    assert d and "perime" not in d


# ── en largeur ───────────────────────────────────────────────────────────────

def test_les_personnes_morales_par_acte_et_jamais_une_personne(base):
    from collectors.graphe import personnes_morales_par_acte
    societe = base.execute("INSERT INTO entities(type, name) VALUES('business', 'Régie SA')").lastrowid
    personne = base.execute("INSERT INTO entities(type, name) VALUES('person', 'Une élue')").lastrowid
    sans_siren = base.execute("INSERT INTO entities(type, name) VALUES('association', 'Club')").lastrowid
    base.execute("INSERT INTO businesses(entity_id, siren) VALUES(?, '999000001')", (societe,))
    evts = [{"id": 1, "cle": "c-2021-41", "ancre": "c-2021-41"},
            {"id": 2, "cle": "c-2021-03-04-tabc", "ancre": "a2", "cle_faible": True}]
    liens = [{"event_id": 1, "entity_id": societe}, {"event_id": 1, "entity_id": personne},
             {"event_id": 1, "entity_id": sans_siren}, {"event_id": 2, "entity_id": societe}]
    publiques = [{"id": societe, "type": "business", "name": "Régie SA"},
                 {"id": personne, "type": "person", "name": "Une élue"},
                 {"id": sans_siren, "type": "association", "name": "Club"}]
    assert personnes_morales_par_acte(base, evts, liens, publiques) == {
        "c-2021-41": [{"siren": "999000001", "nom": "Régie SA", "entity_id": societe}]}


# ── le snapshot entier ───────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def snapshot(tmp_path_factory):
    """La base de la CI et le vrai générateur, comme le job `site`."""
    d = tmp_path_factory.mktemp("graphe")
    db = d / "ci.db"
    env = {**os.environ, "VIGIE_INSTANCE": str(ROOT / "tests" / "instance_test.json"),
           "VIGIE_DB": str(db)}
    env.pop("VIGIE_CI_DOSSIERS", None)
    r = subprocess.run([sys.executable, "tests/amorcer_base_ci.py"], cwd=ROOT, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    env["VIGIE_RULES"] = str(db.with_suffix(".regles.json"))
    out = d / "out"
    code = ("import sys; sys.path.insert(0, 'scripts'); "
            "import build_public_snapshot as b; from pathlib import Path; "
            f"b.build_snapshot(Path({str(out)!r}))")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    return out


def test_chaque_acte_publie_porte_sa_cle_et_son_ancre(snapshot):
    evts = json.loads((snapshot / "events.json").read_text())["events"]
    par_ancre = {e["ancre"]: e for e in evts if e.get("ancre")}
    assert {"c-2021-41", "c-2022-41", "cc-2025-12", "cc-2024-12", "c-2021-04-14"} <= set(par_ancre)
    faible = next(e for e in evts if e.get("cle_faible"))
    assert faible["ancre"] == f"a{faible['id']}", "une clé faible n'est jamais une ancre"


def test_les_textes_d_actes_sont_extraits(snapshot):
    """Le défaut que la base de la CI laissait passer : aucun acte avec texte."""
    assert len(list((snapshot / "extrait").glob("*.json"))) >= 6


def test_l_alias_des_anciennes_ancres_et_la_recherche(snapshot):
    evts = json.loads((snapshot / "events.json").read_text())["events"]
    liens = json.loads((snapshot / "liens.json").read_text())
    e41 = next(e for e in evts if e.get("cle") == "c-2021-41")
    assert liens["alias"][f"a{e41['id']}"] == "c-2021-41"
    recherche = json.loads((snapshot / "recherche_index.json").read_text())["index"]
    assert "/deliberations/2021#c-2021-41" in {r.get("u") for r in recherche}


def test_la_recherche_ne_mene_jamais_a_une_ancre_absente(snapshot):
    """04/10/2026 : tout événement publié menait à /deliberations/<année>, qui
    n'affiche que les actes d'assemblée — ≈ 1 400 résultats de Lasalle visaient
    une ancre absente. Une adresse /deliberations désigne désormais un acte
    d'assemblée publié ; les autres mènent à leur source, ou nulle part."""
    evts = json.loads((snapshot / "events.json").read_text())["events"]
    assemblee = {"deliberation", "deliberation_cc", "conseil_municipal", "conseil_communautaire"}
    ancres = {f"/deliberations/{(e.get('date') or '')[:4] or 'sans-date'}"
              f"#{e.get('ancre') or 'a' + str(e['id'])}"
              for e in evts if e["type"] in assemblee}
    recherche = json.loads((snapshot / "recherche_index.json").read_text())["index"]
    vers_actes = {r["u"] for r in recherche if r.get("u", "").startswith("/deliberations/")}
    assert vers_actes and vers_actes <= ancres
    assert all(r.get("u") for r in recherche if r["k"] != "acte"), \
        "seul un événement sans source peut être sans adresse"


def test_le_snapshot_ecrit_les_trois_tables_meme_sans_dossier(snapshot):
    """Saillans, Brassac : ni dossier ni séance relue. Les tables existent,
    vides, et rien n'échoue."""
    assert json.loads((snapshot / "liens.json").read_text())["total"] == 0
    assert json.loads((snapshot / "lacunes.json").read_text())["total"] == 0
    pm = json.loads((snapshot / "personnes_morales.json").read_text())
    assert pm["actes"] == {"cc-2025-12": [{"siren": "999000001", "nom": "Boulangerie d'épreuve",
                                           "entity_id": pm["actes"]["cc-2025-12"][0]["entity_id"]}]}
