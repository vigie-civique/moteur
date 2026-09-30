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
