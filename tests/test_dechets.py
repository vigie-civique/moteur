"""Les déchets ménagers (SINOE) : lectures et publication, sans appel réseau.

Les lignes reproduites ont la forme que data.ademe.fr a rendue le 01/10/2026
pour la collectivité qui collecte à Lasalle.

Ce que ces essais protègent :
  1. la population vient d'un autre jeu que les kilos : une année qui n'y est
     pas garde ses kilos au lieu de disparaître ;
  2. l'annuaire des déchèteries se republie chaque année : seul le dernier
     millésime est gardé ;
  3. la publication nomme la MAILLE (la collectivité, pas la commune) et ne
     situe une valeur que parmi les repères de la même année ;
  4. une destination à zéro tonne ne sort pas — c'est une case non déclarée.
"""
from __future__ import annotations

from collectors.dechets import (ensure_tables, ligne_repere, lignes_decheteries,
                                lignes_performance, lignes_tonnes)


def _perf(annee, omr, total=500.0):
    return {"annee": annee, "perf_omr_hg": omr, "perf_cs_men_hg": 100.0, "perf_verre_hg": 40.0,
            "perf_dech_hg": 200.0, "perf_dma_hg": total, "perf_dma_ag": total + 100}


def test_une_annee_sans_population_garde_ses_kilos():
    lignes = lignes_performance("53700", [_perf(2023, 286.1), _perf(2024, 271.1)],
                                [{"annee": 2024, "pop_adh_coll": 5521, "typa1": "Très TOURISTIQUE"}])
    assert [(l[1], l[2], l[4]) for l in lignes] == [(2023, None, 286.1), (2024, 5521, 271.1)]


def test_les_emballages_et_papiers_seuls_sont_releves():
    perf = {**_perf(2024, 271.1), "perf_papier_hg": 57.3}
    [ligne] = lignes_performance("53700", [perf], [])
    assert (ligne[5], ligne[-1]) == (100.0, 57.3), "collecte séparée, puis papier en dernière colonne"


def test_une_base_d_avant_la_colonne_papier_est_rattrapee(base):
    base.execute("CREATE TABLE dechets_performance (code_acteur TEXT, annee INTEGER,"
                 " population INTEGER, typologie TEXT, omr REAL, tri REAL, verre REAL,"
                 " decheterie REAL, total REAL, total_gravats REAL,"
                 " PRIMARY KEY (code_acteur, annee))")
    base.execute("INSERT INTO dechets_performance VALUES ('7', 2024, 5200, 'RURAL',"
                 " 250.0, 100.0, 35.0, 180.0, 530.0, 600.0)")
    from scripts.build_public_snapshot import export_dechets
    base.executescript("CREATE TABLE dechets_desserte (annee, insee, code_acteur, acteur, service);"
                       "INSERT INTO dechets_desserte VALUES (2024, '99001', '7', 'CC', 'Collecte');"
                       "CREATE TABLE dechets_reperes (annee, indicateur, portee, code, collectivites,"
                       " p25, p50, p75, p95);"
                       "CREATE TABLE dechets_tonnes (code_acteur, annee, axe, libelle, tonnes);"
                       "CREATE TABLE dechets_decheteries (code_acteur, annee, nom, insee, commune,"
                       " lieu, ouverte_le, gestion, accepte);")
    # Avant la recollecte : la publication s'en passe, sans erreur.
    assert export_dechets(base, "99001")["acteurs"][0]["serie"][0]["papier"] is None
    ensure_tables(base)
    base.execute("UPDATE dechets_performance SET papier = 57.3")
    assert export_dechets(base, "99001")["acteurs"][0]["serie"][0]["papier"] == 57.3


def test_les_tonnes_d_un_meme_regroupement_s_additionnent():
    lignes = lignes_tonnes("53700", "destination", [
        {"annee": 2024, "libelle_regroupement_service_destination": "Stockage", "dma4_ag": 200.0},
        {"annee": 2024, "libelle_regroupement_service_destination": "Stockage", "dma4_ag": 90.5},
        {"annee": 2024, "libelle_regroupement_service_destination": "Non précisé", "dma4_ag": None}])
    assert lignes == [("53700", 2024, "destination", "Stockage", 290.5)]


def test_seul_le_dernier_millesime_de_l_annuaire_est_garde():
    d = lambda annee, nom: {"ANNEE": annee, "N_SERVICE": nom, "C_COMM": "99001",
                            "L_VILLE_SITE": "Fictiville", "LOV_MO_GEST": "REGIE"}
    assert [l[2] for l in lignes_decheteries("1", [d(2025, "Fermée depuis"), d(2026, "Ouverte")])] \
        == ["Ouverte"]


def test_un_repere_se_lit_dans_les_percentiles():
    agregat = {"total": 936, "metric": [{"key": k, "value": v} for k, v in
                                        ((1, 50), (25, 149), (50, 192), (75, 237), (95, 355))]}
    assert ligne_repere(2024, "omr", "france", "", agregat) == (
        2024, "omr", "france", "", 936, 149, 192, 237, 355)


# ── La publication (`export_dechets`) ────────────────────────────────────────

def _base_dechets(base):
    ensure_tables(base)
    base.executemany("INSERT INTO dechets_desserte VALUES (?,?,?,?,?)", [
        (2023, "99001", "7", "Ancien nom", "Collecte des ordures"),
        (2024, "99001", "7", "CC du Test", "Collecte des ordures"),
        (2024, "99001", "7", "CC du Test", "Déchèterie de Fictiville")])
    base.executemany("INSERT INTO dechets_performance VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
        ("7", 2021, 5000, "RURAL", 300.0, 90.0, 30.0, 150.0, 570.0, 700.0, 55.0),
        ("7", 2024, 5200, "RURAL", 250.0, 100.0, 35.0, 180.0, 565.0, 690.0, 60.0)])
    base.executemany("INSERT INTO dechets_reperes VALUES (?,?,?,?,?,?,?,?,?)", [
        (2024, "omr", "france", "", 900, 150.0, 190.0, 240.0, 350.0),
        (2024, "omr", "departement", "99", 12, 200.0, 220.0, 260.0, 400.0),
        (2021, "tri", "france", "", 900, 10.0, 20.0, 30.0, 40.0)])       # une autre année
    base.executemany("INSERT INTO dechets_tonnes VALUES (?,?,?,?,?)", [
        ("7", 2024, "destination", "Valorisation matière", 2000.0),
        ("7", 2024, "destination", "Valorisation organique", 0.0),
        ("7", 2021, "destination", "Stockage", 900.0)])
    base.executemany("INSERT INTO dechets_decheteries VALUES (?,?,?,?,?,?,?,?,?)", [
        ("7", 2026, "Déchèterie d'ailleurs", "99002", "Ailleurs", None, None, "REGIE", "DMA"),
        ("7", 2026, "Déchèterie de Fictiville", "99001", "Fictiville", None, None, "REGIE", "DMA")])
    base.commit()


def test_la_publication_des_dechets_nomme_la_collectivite_et_situe_a_annee_egale(base):
    from scripts.build_public_snapshot import export_dechets
    _base_dechets(base)

    [a] = export_dechets(base, "99001")["acteurs"]

    assert a["nom"] == "CC du Test", "le nom de la dernière desserte"
    assert a["services"] == ["Collecte des ordures", "Déchèterie de Fictiville"]
    assert [s["annee"] for s in a["serie"]] == [2021, 2024]
    omr = next(s for s in a["situer"] if s["indicateur"] == "omr")
    assert (omr["valeur"], omr["quart"], omr["departement"]["p50"]) == (250.0, 4, 220.0)
    # Le tri n'a de repère qu'en 2021 : en 2024, il n'est pas situé.
    tri = next(s for s in a["situer"] if s["indicateur"] == "tri")
    assert tri["france"] is None and tri["quart"] is None
    # La dernière année déclarée, et pas la case à zéro.
    assert a["destinations"] == {"annee": 2024, "lignes": [
        {"libelle": "Valorisation matière", "tonnes": 2000.0}]}
    assert a["decheteries"][0]["nom"] == "Déchèterie de Fictiville", "celle de la commune d'abord"


def test_une_commune_absente_de_sinoe_ne_publie_rien(base):
    from scripts.build_public_snapshot import export_dechets
    assert export_dechets(base, "99001") is None, "table absente"
    _base_dechets(base)
    assert export_dechets(base, "99999") is None, "commune sans desserte"


def test_un_service_non_exerce_n_est_pas_zero_kilo(base):
    """Un syndicat de traitement déclare 0 kg d'ordures ménagères : il ne les
    ramasse pas. Ni chiffre, ni rang « dans le quart le plus bas »."""
    from scripts.build_public_snapshot import export_dechets
    _base_dechets(base)
    base.execute("UPDATE dechets_performance SET omr = 0 WHERE annee = 2024")
    base.commit()

    [a] = export_dechets(base, "99001")["acteurs"]

    assert a["serie"][-1]["omr"] is None
    situes = [s["indicateur"] for s in a["situer"]]
    assert "omr" not in situes
    # Sans les ordures, le total n'est plus qu'un total partiel : il n'est pas situé.
    assert "total" not in situes and "tri" in situes
