"""Télécoms : les lectures des fichiers de l'ARCEP, sans appel réseau.

Les lignes reproduites ont la forme exacte que l'ARCEP a publiée au 30/09/2026.

Ce que ces essais protègent :
  1. la colonne `elig_4fg` des trimestres anciens est la même que `elig_4gf` —
     sans l'alias, la 4G fixe disparaissait de toute la série avant 2021 ;
  2. les coordonnées publiées avec une virgule décimale (« 44,0403 ») sont lues ;
  3. un site hors du rayon n'est pas retenu, un site dans le rayon l'est ;
  4. le lecteur .dbf retrouve une commune dans le fichier des déploiements ;
  5. un fichier en Windows-1252 n'est pas lu comme de l'UTF-8 cassé.
"""
from __future__ import annotations

import struct

from collectors.telecoms import (_csv, distance_km, lignes_fixe, lire_dbf, nombre,
                                 pannes_du_jour, sites_proches)


def test_une_virgule_decimale_est_lue():
    assert nombre("44,0403") == 44.0403
    assert nombre("NA") is None and nombre("") is None


def test_l_ancien_nom_de_colonne_de_la_4g_fixe_est_reconnu():
    ancien = _csv(b"code_insee;nbr;type;elig_ftth;elig_cu;elig_4fg;elig_sat;date\n"
                  b"30140;1227;all;0;1227;793;1227;2020-12-31\n")
    [ligne] = lignes_fixe(ancien, [], {"30140"}, "2020_T4")
    # (trimestre, insee, date, locaux, ftth, coax, cu, thdr, 4gf, hdr, sat, …)
    assert ligne[3] == 1227 and ligne[8] == 793


def test_seules_les_communes_suivies_sont_gardees():
    techno = _csv(b"code_insee;nbr;type;elig_ftth\n30140;1372;all;1322\n"
                  b"30329;500;all;400\n30140;10;pro;5\n")
    lignes = lignes_fixe(techno, [], {"30140"}, "2026_T2")
    assert [(l[1], l[3]) for l in lignes] == [("30140", 1372)]


def test_un_fichier_windows_1252_est_decode():
    [r] = _csv("dep_nom\nEnsemble du réseau\n".encode("cp1252"))
    assert r["dep_nom"] == "Ensemble du réseau"


def _site(lat, lon, num="1"):
    return {"code_op": "20801", "nom_op": "Orange", "num_site": num, "latitude": lat,
            "longitude": lon, "insee_com": "30140", "site_4g": "1", "site_ZB": "1"}


def test_le_rayon_trie_les_sites():
    centre = (44.0403, 3.85)
    proche, loin = _site("44,05", "3,86", "1"), _site("44,5", "3,85", "2")
    retenus = sites_proches([proche, loin], centre, 10, "2026_T2")
    assert [r[3] for r in retenus] == ["1"]
    assert retenus[0][10] < 2 and retenus[0][15] == 1       # distance, zones blanches


def test_la_distance_est_en_kilometres():
    assert 55 < distance_km(44.0, 3.85, 44.5, 3.85) < 56


def _dbf(lignes: list[dict], champs: list[tuple[str, int]]) -> bytes:
    taille = 1 + sum(l for _, l in champs)
    entete = 32 + 32 * len(champs) + 1
    tete = struct.pack("<BBBBIHH20x", 3, 126, 9, 30, len(lignes), entete, taille)
    desc = b"".join(n.encode().ljust(11, b"\0") + b"C" + b"\0" * 4 + bytes([l]) + b"\0" * 15
                    for n, l in champs)
    corps = b"".join(b" " + b"".join(str(l.get(n, "")).encode().ljust(t)[:t] for n, t in champs)
                     for l in lignes)
    return tete + desc + b"\x0d" + corps


def test_le_lecteur_dbf_retrouve_une_commune():
    champs = [("INSEE_COM", 5), ("zone", 6), ("oi", 6)]
    contenu = _dbf([{"INSEE_COM": "06021", "zone": "zipri", "oi": "FRTE"},
                    {"INSEE_COM": "30140", "zone": "zipu", "oi": "WIGA"}], champs)
    assert lire_dbf(contenu, lambda l: l["INSEE_COM"] == "30140") == [
        {"INSEE_COM": "30140", "zone": "zipu", "oi": "WIGA"}]


def test_une_panne_d_ailleurs_n_est_pas_gardee():
    features = [{"properties": {"code_insee": "01249", "operateur": "Bouygues Telecom"}},
                {"properties": {"code_insee": "30140", "operateur": "Orange"}}]
    assert [p["operateur"] for p in pannes_du_jour(features, {"30140"})] == ["Orange"]


# ── La publication (`export_telecoms`) ───────────────────────────────────────
# Ce que ces tests protègent : un zéro qui n'est pas un fait (cuivre, pannes non
# relevées), un rang comparé à une autre période, un site compté autant de fois
# qu'il héberge d'opérateurs.

def _fixe(conn, trimestre, date, locaux, fibre, cuivre, insee="99001"):
    conn.execute("INSERT INTO telecoms_fixe (trimestre, insee, date, locaux, elig_ftth, "
                 "elig_cu, mt_ftth, mt_4gf, mt_sat, mt_autre) VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (trimestre, insee, date, locaux, fibre, cuivre, fibre,
                  locaux - fibre, 0, 0))


def _base_telecoms(base):
    from collectors.telecoms import ensure_tables
    ensure_tables(base)
    _fixe(base, "2022_T2", "2022-06-30", 200, 0, 200)
    _fixe(base, "2022_T3", "2022-09-30", 180, 90, 180)
    _fixe(base, "2025_T4", "2025-12-31", 100, 90, 100)
    _fixe(base, "2026_T1", "2026-03-31", 100, 95, 0)
    _fixe(base, "2099_T1", "2099-03-31", 50, 50, 50, insee="99002")   # une voisine
    base.execute("INSERT INTO telecoms_fixe_oi VALUES ('2026_T1','99001','zipu','FICT',100,95,95.0)")
    base.execute("INSERT INTO telecoms_operateurs VALUES ('FICT','Fictif')")
    q = "INSERT INTO telecoms_qualite_ftth (periode, oi, perimetre, dep_code, taux_pannes, " \
        "taux_abonnes_avec_panne) VALUES (?,?,?,?,?,?)"
    for periode, oi, perimetre, dep, pannes, abonnes in (
            ("10/25 - 03/26", "Fictif Fibre", "reseau", "00", 0.003, None),
            ("10/25 - 03/26", "Autre", "reseau", "00", 0.001, None),
            ("10/25 - 03/26", "Troisième", "reseau", "00", 0.002, None),
            ("04/25 - 09/25", "Fictif Fibre", "reseau", "00", 0.0001, None),  # plus ancienne
            ("10/25 - 03/26", "Fictif Fibre", "departement", "99", 0.003, 0.02),
            ("10/25 - 03/26", "Autre", "departement", "12", 0.001, 0.01)):
        base.execute(q, (periode, oi, perimetre, dep, pannes, abonnes))
    s = "INSERT INTO telecoms_sites_mobiles (trimestre, code_op, nom_op, num_site, " \
        "id_site_partage, insee_com, nom_com, distance_km, site_2g, site_3g, site_4g, " \
        "site_5g, site_zb, site_dcc) VALUES ('2026_T2',?,?,?,?,?,?,?,0,1,1,?,?,0)"
    for code, nom, num, partage, insee, dist, g5, zb in (
            ("1", "Orange", "A1", "ZP1", "99001", 1.5, 0, 1),
            ("2", "SFR", "B7", "ZP1", "99001", 1.5, 0, 1),
            ("3", "Free", "C3", None, "99003", 4.0, 1, 0)):
        base.execute(s, (code, nom, num, partage, insee,
                         "Fictiville" if insee == "99001" else "Voisine", dist, g5, zb))
    base.commit()


def test_la_publication_des_telecoms_qualifie_ses_zeros(base):
    from scripts.build_public_snapshot import export_telecoms
    _base_telecoms(base)

    t = export_telecoms(base, "99001", "99", 10)

    assert [s["part"] for s in t["fixe"]["serie"]] == [0.0, 50.0, 90.0, 95.0]
    assert t["fixe"]["ouverture"]["trimestre"] == "2022_T3"
    assert t["fixe"]["dernier"]["sans_fibre"] == 5
    # Le cuivre à zéro en 2026 est la rupture de méthode, pas une fermeture.
    assert t["fixe"]["cuivre_a_zero"] == {"trimestre": "2026_T1", "date": "2026-03-31",
                                          "avant": 100, "date_avant": "2025-12-31"}
    q = t["reseau"]["qualite"]
    assert q["periode"] == "10/25 - 03/26", "la période la plus récente, triée par sa fin"
    assert q["oi"] == "Fictif Fibre", "jointure par préfixe : « Fictif » → « Fictif Fibre »"
    assert (q["pannes"]["rang"], q["pannes"]["sur"], q["pannes"]["mediane"]) == (3, 3, 0.002)
    assert q["abonnes_avec_panne"]["taux"] == 0.02, "le département de la commune"
    # Deux opérateurs sur un même support : un site, pas deux.
    assert t["mobile"]["sites"] == 2
    [site] = t["mobile"]["dans_la_commune"]
    assert (site["site"], len(site["operateurs"]), site["zones_blanches"]) == ("ZP1", 2, True)
    assert t["mobile"]["plus_proche_5g"]["commune"] == "Voisine"
    # Aucun jour lu : rien n'est dit, surtout pas « zéro panne ».
    assert t["pannes"] is None


def test_un_cuivre_a_zero_hors_de_la_rupture_n_est_pas_explique(base):
    from collectors.telecoms import ensure_tables
    from scripts.build_public_snapshot import export_telecoms
    ensure_tables(base)
    _fixe(base, "2024_T1", "2024-03-31", 100, 50, 100)
    _fixe(base, "2024_T2", "2024-06-30", 100, 50, 0)
    base.commit()

    assert export_telecoms(base, "99001", "99", 10)["fixe"]["cuivre_a_zero"] is None


def test_zero_panne_ne_se_dit_que_sur_des_jours_lus(base):
    from scripts.build_public_snapshot import export_telecoms
    _base_telecoms(base)
    base.execute("INSERT INTO telecoms_indispo_jours (jour, sites_france) VALUES "
                 "('2026-09-01', 120), ('2026-09-02', 80)")
    base.execute("INSERT INTO telecoms_indisponibilites (jour, operateur, station_anfr, "
                 "code_insee) VALUES ('2026-09-02', 'SFR', '1', '99003')")   # une voisine
    base.commit()

    assert export_telecoms(base, "99001", "99", 10)["pannes"] == {
        "jours": 2, "du": "2026-09-01", "au": "2026-09-02", "declarees": 0}
