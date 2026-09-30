"""Rivières : la sélection par bassin, et la purge de ce qui en sort.

Aucun appel réseau. Ce que ces essais protègent :
  1. un bassin déclaré se cherche par cours d'eau ET par rayon — la Drôme compte
     des stations sur cent kilomètres ;
  2. sans déclaration, le step reste sur les communes de fond ;
  3. une station que la sélection ne retient plus disparaît, analyses
     comprises : le 30/09/2026, les trois instances publiaient des stations
     collectées quand le step visait toute l'intercommunalité.
"""
from __future__ import annotations

from collectors.qualite_eau import ensure_tables, purger_hors_selection, selection_stations


def test_un_bassin_declare_se_cherche_par_cours_d_eau_et_par_rayon():
    p = selection_stations({"codes": ["V7130640", "V7130500"], "rayon_km": 25},
                           (44.04, 3.85), ["30140"])
    assert p == {"code_cours_eau": "V7130640,V7130500",
                 "latitude": 44.04, "longitude": 3.85, "distance": 25}


def test_le_rayon_a_une_valeur_par_defaut():
    assert selection_stations({"codes": ["V42-0400"]}, (44.7, 5.2), [])["distance"] == 20


def test_sans_bassin_on_reste_sur_les_communes_de_fond():
    assert selection_stations({}, (44.04, 3.85), ["30140"]) == {"code_commune": "30140"}


def _station(base, code):
    base.execute("INSERT INTO eau_stations (code_station, libelle) VALUES (?, ?)", (code, code))
    base.execute("INSERT INTO eau_analyses (code_analyse, code_station) VALUES (?, ?)",
                 (f"a-{code}", code))


def test_une_station_hors_selection_est_purgee_avec_ses_analyses(base):
    ensure_tables(base)
    for code in ("06128750", "05148200"):
        _station(base, code)
    assert purger_hors_selection(base, ["06128750"]) == 1
    assert [r[0] for r in base.execute("SELECT code_station FROM eau_stations")] == ["06128750"]
    assert base.execute("SELECT COUNT(*) FROM eau_analyses").fetchone()[0] == 1


def test_une_selection_vide_purge_tout(base):
    """Une commune sans station, sans bassin déclaré : rien ne doit rester
    publié sous son nom."""
    ensure_tables(base)
    _station(base, "05148200")
    assert purger_hors_selection(base, []) == 1
    assert base.execute("SELECT COUNT(*) FROM eau_stations").fetchone()[0] == 0
