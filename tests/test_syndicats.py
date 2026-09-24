"""Les syndicats auxquels l'intercommunalité adhère : leur fiche et leurs comptes.

Deux défauts relevés le 24/09 à Lasalle, et la règle qui les corrige :
  - `banatic` créait le syndicat par son libellé, à côté de la fiche que
    `sirene` avait déjà posée sous son SIREN — deux fiches, et la relation
    d'adhésion sur celle qui n'avait pas d'identifiant ;
  - sa note était réécrite à chaque passe (trois fois par syndicat).
Et les comptes : ce qui compte comme une dépense, une recette, une dette.
"""
from __future__ import annotations

from collectors.banatic import import_adhesions
from collectors.syndicats_comptes import (agreger, importer,
                                          syndicats_du_territoire)


def _banatic(siren="200091197", libelle="SIAEP de Lasalle"):
    return {"groupementsAdherentsSyndicatMixte": [
        {"libelle": libelle, "siren": siren, "codeNatureJuridique": "SMF",
         "populationTotale": 2416}]}


# ── banatic : la fiche du syndicat ───────────────────────────────────────────

def test_le_syndicat_deja_connu_par_son_siren_nest_pas_recree(base, entite):
    epci = entite("CC Causses Aigoual Cévennes", "service")
    connu = entite("SIAEP DE LASALLE", "service", commune="Lasalle")
    base.execute("INSERT INTO businesses (entity_id, siren) VALUES (?,?)",
                 (connu, "200091197"))
    import_adhesions(base, epci, _banatic(), dry_run=False)
    assert base.execute("SELECT count(*) FROM entities WHERE type='service'"
                        " AND name LIKE 'SIAEP%'").fetchone()[0] == 1
    assert base.execute(
        "SELECT to_id FROM relations WHERE relation_type='adhère_à'"
    ).fetchone()[0] == connu


def test_un_syndicat_nouveau_porte_son_siren(base, entite):
    epci = entite("CC Causses Aigoual Cévennes", "service")
    import_adhesions(base, epci, _banatic("253002711", "SM EPTB Gardons"),
                     dry_run=False)
    row = base.execute(
        "SELECT e.name, b.siren FROM entities e JOIN businesses b"
        " ON b.entity_id = e.id").fetchone()
    assert tuple(row) == ("SM EPTB Gardons", "253002711")


def test_rejouer_banatic_necrit_pas_la_note_deux_fois(base, entite):
    epci = entite("CC Causses Aigoual Cévennes", "service")
    for _ in range(3):
        import_adhesions(base, epci, _banatic(), dry_run=False)
    assert base.execute("SELECT count(*) FROM entity_notes"
                        " WHERE source='BANATIC'").fetchone()[0] == 1


# ── Les syndicats du territoire ──────────────────────────────────────────────

def test_le_siren_se_lit_dans_la_note_quand_la_fiche_nen_a_pas(base, entite):
    """Une base où `banatic` n'a pas été rejoué depuis la correction."""
    epci = entite("CC", "service")
    synd = entite("SM EPTB Gardons", "service")
    base.execute("INSERT INTO relations (from_id, to_id, relation_type, source)"
                 " VALUES (?,?,'adhère_à','banatic')", (epci, synd))
    base.execute("INSERT INTO entity_notes (entity_id, note, source)"
                 " VALUES (?,?,'BANATIC')",
                 (synd, "SIREN: 253002711 | Nature: SMF | Population: 386290"))
    assert syndicats_du_territoire(base) == [(synd, "253002711", "SM EPTB Gardons")]


def test_un_syndicat_sans_siren_nest_pas_cherche_par_son_nom(base, entite):
    epci = entite("CC", "service")
    synd = entite("Syndicat sans identifiant", "service")
    base.execute("INSERT INTO relations (from_id, to_id, relation_type, source)"
                 " VALUES (?,?,'adhère_à','banatic')", (epci, synd))
    assert syndicats_du_territoire(base) == []


# ── Les comptes ──────────────────────────────────────────────────────────────

def _compte(compte, exer="2024", ident="20009119700018", **montants):
    rec = {"compte": compte, "exer": f"{exer}-01-01T00:00:00+00:00",
           "ident": ident, "lbudg": "SIAEP DE LASALLE", "nomen": "M49A",
           "obnetdeb": 0.0, "obnetcre": 0.0, "sd": 0.0, "sc": 0.0}
    rec.update(montants)
    return rec


def test_les_amortissements_ne_sont_pas_une_depense():
    """Une dotation aux amortissements (68) est une écriture d'ordre : au SIAEP
    de Lasalle en 2024, elle pesait 60 k€ sur 109 k€ de classe 6."""
    postes = agreger([_compte("6156", obnetdeb=303.0),
                      _compte("6811", obnetdeb=60000.0)])[(2024, "20009119700018")]["postes"]
    assert postes["depenses_fonctionnement"] == 303.0


def test_une_annulation_se_deduit():
    postes = agreger([_compte("7011", obnetcre=1000.0, obnetdeb=100.0)]
                     )[(2024, "20009119700018")]["postes"]
    assert postes["recettes_fonctionnement"] == 900.0
    assert postes["ventes_et_redevances"] == 900.0


def test_la_dette_est_un_solde_crediteur():
    postes = agreger([_compte("1641", sc=545454.01, obnetdeb=20000.0)]
                     )[(2024, "20009119700018")]["postes"]
    assert postes["encours_dette"] == 545454.01


def test_la_subvention_dequipement_versee_nest_pas_un_investissement_propre():
    postes = agreger([_compte("2041", obnetdeb=5000.0),
                      _compte("2315", obnetdeb=1000.0)])[(2024, "20009119700018")]["postes"]
    assert postes["depenses_investissement"] == 1000.0
    assert postes["subventions_equipement_versees"] == 5000.0


def test_le_financeur_se_lit_dans_le_compte():
    postes = agreger([_compte("7477", obnetcre=10.0), _compte("1317", obnetcre=20.0),
                      _compte("7478", obnetcre=5.0)])[(2024, "20009119700018")]["postes"]
    assert postes["subventions_europe"] == 30.0
    assert postes["subventions_autres"] == 5.0


def test_deux_budgets_ne_sadditionnent_pas():
    blocs = agreger([_compte("6156", obnetdeb=1.0, ident="A"),
                     _compte("6156", obnetdeb=2.0, ident="B")])
    assert set(blocs) == {(2024, "A"), (2024, "B")}


def test_rejouer_met_a_jour_sans_dupliquer(base, entite):
    synd = entite("SIAEP", "service")
    importer(base, synd, "200091197", [_compte("6156", obnetdeb=303.0)])
    importer(base, synd, "200091197", [_compte("6156", obnetdeb=404.0)])
    rows = base.execute("SELECT montant FROM comptes_syndicats"
                        " WHERE poste='depenses_fonctionnement'").fetchall()
    assert [r[0] for r in rows] == [404.0]


# ── L'encart de la fiche ─────────────────────────────────────────────────────

def _snapshot():
    import importlib.util
    import sys
    from pathlib import Path
    racine = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(racine))
    spec = importlib.util.spec_from_file_location(
        "snapshot_sous_test", racine / "scripts" / "build_public_snapshot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_la_fiche_recoit_ses_comptes_par_exercice_et_par_budget(base, entite):
    synd = entite("SIAEP", "service")
    importer(base, synd, "200093797", [
        _compte("6156", exer="2024", ident="PRINCIPAL", obnetdeb=100.0),
        _compte("6156", exer="2024", ident="ANNEXE", obnetdeb=7.0),
        _compte("6156", exer="2023", ident="PRINCIPAL", obnetdeb=90.0),
    ])
    comptes = _snapshot().comptes_syndicats_par_entite(base)[synd]
    assert [c["year"] for c in comptes] == [2024, 2023]
    montants = sorted(b["postes"]["depenses_fonctionnement"]
                      for b in comptes[0]["budgets"])
    assert montants == [7, 100], "deux budgets ne s'additionnent pas"


def test_sans_table_la_fiche_na_pas_dencart(tmp_path):
    import sqlite3
    conn = sqlite3.connect(tmp_path / "ancienne.db")
    conn.row_factory = sqlite3.Row
    assert _snapshot().comptes_syndicats_par_entite(conn) == {}
