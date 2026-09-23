"""Les rapprochements à trancher — `collectors/detect_links.py`.

Ce module a vécu des mois sans être appelé : ni step de `run_all.py`, ni
script. Câblé le 23/09/2026, il a fallu d'abord mesurer ce qu'il produirait.
Joué entier sur copie des trois instances : **59 799 candidats**, dont
**52 637 `maiden_name`** — des liens de famille présumés entre personnes
physiques, déduits des parenthèses SIRENE. Les 87 sièges de commission qui
attendaient vraiment à Lasalle auraient disparu dessous.

Ces tests tiennent les deux décisions qui en sont sorties :

* la passe quotidienne ne joue que les signaux qu'un humain peut trancher, et
  un signal éteint n'est pas seulement tu — son détecteur ne tourne PAS ;
* un « fantôme » de subvention se reconnaît à une PROPRIÉTÉ, pas à une plage
  d'identifiants relevée un jour sur la base de Lasalle.
"""
from __future__ import annotations

import sqlite3

import pytest

from collectors.detect_links import (SIGNAUX_FAMILLE, SIGNAUX_PAR_DEFAUT,
                                     TOUS_SIGNAUX, detect_subsidy_phantoms,
                                     normalize, parse_married_name)


# ── Ce que la passe quotidienne joue, et ce qu'elle ne joue pas ───────────────

def test_les_signaux_familiaux_sont_eteints_par_defaut():
    """54 000 liens de parenté présumés sur des particuliers n'est pas une file."""
    for signal in SIGNAUX_FAMILLE:
        assert signal not in SIGNAUX_PAR_DEFAUT
    assert set(SIGNAUX_PAR_DEFAUT) | set(SIGNAUX_FAMILLE) == set(TOUS_SIGNAUX)


def test_le_step_quotidien_ne_pose_que_ce_qui_se_tranche():
    assert set(SIGNAUX_PAR_DEFAUT) == {
        "entity_duplicate", "same_full_name", "toponym", "subsidy_entity_match"}


def test_un_signal_inconnu_est_refuse(monkeypatch, tmp_path, schema_sql):
    """Refusé, pas ignoré : demander un signal qui n'existe pas doit se voir."""
    from collectors import detect_links
    chemin = tmp_path / "t.db"
    sqlite3.connect(chemin).executescript(schema_sql)
    monkeypatch.setattr(detect_links, "DB_PATH", chemin)
    with pytest.raises(ValueError, match="signal inconnu"):
        detect_links.run(dry_run=True, signaux=("patronyme_magique",))


def test_un_signal_eteint_ne_tourne_pas(monkeypatch, tmp_path, schema_sql):
    """Le taire ne suffit pas : les détecteurs familiaux parcourent des dizaines
    de milliers de couples de personnes. Les jouer pour jeter le résultat, c'est
    payer la minute qu'on cherchait à ne pas payer."""
    from collectors import detect_links
    chemin = tmp_path / "t.db"
    sqlite3.connect(chemin).executescript(schema_sql)
    monkeypatch.setattr(detect_links, "DB_PATH", chemin)

    appels = []
    for nom in ("detect_maiden_names", "detect_rare_surnames"):
        monkeypatch.setattr(detect_links, nom,
                            lambda *a, _n=nom, **k: appels.append(_n) or 0)

    resultats = detect_links.run(dry_run=True)
    assert appels == []
    assert set(resultats) == set(SIGNAUX_PAR_DEFAUT)

    detect_links.run(dry_run=True, signaux=TOUS_SIGNAUX)
    assert sorted(appels) == ["detect_maiden_names", "detect_rare_surnames"]


# ── La passe se journalise : c'est ce qui donne sa raison à un zéro ──────────

def test_une_vraie_passe_laisse_une_trace(monkeypatch, tmp_path, schema_sql):
    from collectors import detect_links
    chemin = tmp_path / "t.db"
    sqlite3.connect(chemin).executescript(schema_sql)
    monkeypatch.setattr(detect_links, "DB_PATH", chemin)

    detect_links.run()
    conn = sqlite3.connect(chemin)
    ligne = conn.execute("SELECT collector, status, finished_at FROM collector_runs"
                         ).fetchone()
    # Le nom est celui du step : `collectors/files.py` le cherche sous ce mot.
    assert ligne[0] == "liens" and ligne[1] in ("ok", "empty") and ligne[2]


def test_une_mesure_a_blanc_ne_date_rien(monkeypatch, tmp_path, schema_sql):
    """Sinon la file dirait « mesuré à l'instant » après un simple essai."""
    from collectors import detect_links
    chemin = tmp_path / "t.db"
    sqlite3.connect(chemin).executescript(schema_sql)
    monkeypatch.setattr(detect_links, "DB_PATH", chemin)

    detect_links.run(dry_run=True)
    conn = sqlite3.connect(chemin)
    assert conn.execute("SELECT COUNT(*) FROM collector_runs").fetchone()[0] == 0


# ── Le fantôme est une propriété, pas un numéro de ligne ─────────────────────

@pytest.fixture
def base_subventions(base):
    """Une commune, une asso attestée au RNA, et deux bénéficiaires nommés dans
    un acte dont aucun registre ne parle."""
    def entite(type_, nom):
        return base.execute("INSERT INTO entities(type, name) VALUES(?,?)",
                            (type_, nom)).lastrowid

    commune = entite("service", "Commune d'Épreuve")
    vraie = entite("association", "Les Amis du Four Banal")
    base.execute("INSERT INTO associations(entity_id, rna_id) VALUES(?,?)",
                 (vraie, "W000000001"))
    fantome = entite("association", "AMIS DU FOUR BANAL")
    hors_sujet = entite("association", "Club de Pétanque")

    for beneficiaire in (fantome, hors_sujet):
        base.execute(
            "INSERT INTO financial_flows(type, year, amount, from_id, to_id, source) "
            "VALUES('subvention', 2025, 500, ?, ?, 'PV du conseil')",
            (commune, beneficiaire))
    base.commit()
    return {"vraie": vraie, "fantome": fantome, "hors_sujet": hors_sujet}


def test_un_beneficiaire_sans_registre_est_rapproche_dune_entite_connue(
        base, base_subventions):
    assert detect_subsidy_phantoms(base.cursor()) >= 1
    lignes = base.execute(
        "SELECT from_id, to_id, signal FROM relation_candidates").fetchall()
    couples = {(l["from_id"], l["to_id"]) for l in lignes}
    assert (base_subventions["fantome"], base_subventions["vraie"]) in couples
    assert all(l["signal"] == "subsidy_entity_match" for l in lignes)


def test_une_entite_attestee_par_un_registre_nest_pas_un_fantome(
        base, base_subventions):
    """Elle a un RNA : elle existe, il n'y a rien à rapprocher."""
    detect_subsidy_phantoms(base.cursor())
    partants = {l["from_id"] for l in base.execute(
        "SELECT from_id FROM relation_candidates").fetchall()}
    assert base_subventions["vraie"] not in partants


def test_le_rapprochement_ne_depend_daucune_plage_didentifiants(base):
    """Le défaut d'origine : `PHANTOM_SUBSIDY_IDS = range(107, 122)`, relevé un
    jour sur Lasalle. Ici les identifiants commencent à 5 000 — sur le moteur
    générique, rien ne dit où tombent les bénéficiaires d'une autre commune."""
    base.execute("INSERT INTO entities(id, type, name) VALUES(5000,'service','Commune')")
    base.execute("INSERT INTO entities(id, type, name) "
                 "VALUES(5001,'association','Comité des Fêtes du Village')")
    base.execute("INSERT INTO associations(entity_id, rna_id) VALUES(5001,'W000000002')")
    base.execute("INSERT INTO entities(id, type, name) "
                 "VALUES(5002,'association','COMITE DES FETES DU VILLAGE')")
    base.execute("INSERT INTO financial_flows(type, year, amount, from_id, to_id, source) "
                 "VALUES('subvention', 2025, 300, 5000, 5002, 'PV')")
    base.commit()

    assert detect_subsidy_phantoms(base.cursor()) >= 1
    assert base.execute(
        "SELECT COUNT(*) FROM relation_candidates WHERE from_id=5002 AND to_id=5001"
    ).fetchone()[0] == 1


def test_sans_aucun_fantome_rien_nest_propose(base):
    """Zéro bénéficiaire sans registre : la requête ne doit pas partir en vrille
    sur une liste d'identifiants vide."""
    base.execute("INSERT INTO entities(type, name) VALUES('association','Seule')")
    base.commit()
    assert detect_subsidy_phantoms(base.cursor()) == 0


# ── Les briques de normalisation, inchangées mais désormais couvertes ────────

@pytest.mark.parametrize("entree, attendu", [
    ("Commune de Lasalle", "commune de lasalle"),
    ("COMMUNE DE LASALLE", "commune de lasalle"),
    ("Établissement Public — Étang", "etablissement public etang"),
    ("", ""),
])
def test_normalisation(entree, attendu):
    assert normalize(entree) == attendu


def test_le_nom_de_naissance_se_lit_entre_parentheses():
    assert parse_married_name("Marie DUPONT (MARTIN)") == ("Marie DUPONT", "MARTIN")
    assert parse_married_name("Jean DURAND") == (None, None)
