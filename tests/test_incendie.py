"""Forêt, feux et débroussaillement : lectures et publication, sans appel réseau.

La page de la BDIFF reproduite a la forme rendue le 01/10/2026.

Ce que ces essais protègent :
  1. la BDIFF garde ses critères dans la session : une page d'une AUTRE commune
     veut dire que le filtre est perdu, et le relevé s'arrête au lieu d'écrire
     les feux de la France entière ;
  2. une adresse dans le trou d'un polygone n'est pas dans le zonage ;
  3. « aucun feu », « aucune forêt publique » ne se publient que si le relevé a
     abouti : sans ligne de suivi, rien n'est dit.
"""
from __future__ import annotations

import pytest

from collectors.incendie import (adresses_dans_le_zonage, ensure_tables, forets_de_la_commune,
                                 lire_page_bdiff, points_de_la_commune)


def _page(*lignes):
    """Le tableau des incendies, tel que la BDIFF le rend : le numéro de fiche
    dans un libellé masqué, le code INSEE et le détail des surfaces aussi."""
    corps = "".join(f"""
        <tr><td><input type="checkbox" aria-label="Sélectionner l'incendie {fiche}"></td>
          <td><a href="#" class="eye" title="Aperçu de la fiche {fiche}">
                <span class="hide">Aperçu de la fiche {fiche}"</span></a></td>
          <td> {alerte[6:10]} </td><td><span> {alerte} </span></td>
          <td><span title="GARD"> 30 </span></td>
          <td><span> {commune} </span><div class="hidden"><div><strong>INSEE :</strong> {insee} </div></div></td>
          <td class="right"><span> {surface} </span>{foret}</td>
          <td> {cause} </td><td> - </td></tr>"""
                    for fiche, alerte, commune, insee, surface, foret, cause in lignes)
    return f"<table><tr><td></td><th>Année</th></tr>{corps}</table>"


FORET = '<div class="hidden"><div><strong>Forêt :</strong> 0.1410 ha </div></div>'


def test_une_ligne_de_la_bdiff_est_lue():
    [feu] = lire_page_bdiff(_page(("2016-8831", "10/08/2016 15:35", "Lasalle", "99001",
                                   "0.3000", FORET, "Involontaire (particulier)")), "99001")
    assert feu == {"cle": "2016-8831", "alerte": "2016-08-10 15:35", "surface_ha": 0.3,
                   "foret_ha": 0.141, "cause": "Involontaire (particulier)"}


def test_une_cause_vide_n_est_pas_une_cause():
    [feu] = lire_page_bdiff(_page(("2015-6340", "15/07/2015 10:10", "Lasalle", "99001",
                                   "0.0057", "", "-")), "99001")
    assert feu["cause"] is None and feu["foret_ha"] is None


def test_une_page_d_une_autre_commune_arrete_le_releve():
    with pytest.raises(RuntimeError, match="filtre perdu"):
        lire_page_bdiff(_page(("2020-1", "01/08/2020 12:00", "Ailleurs", "01001", "5.0000",
                               "", "-")), "99001")
    with pytest.raises(RuntimeError, match="tableau"):
        lire_page_bdiff("<html>maintenance</html>", "99001")


CARRE = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
TROU = [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]


def test_une_adresse_dans_un_trou_n_est_pas_dans_le_zonage():
    zones = [{"geometry": {"type": "Polygon", "coordinates": [CARRE, TROU]}, "properties": {}},
             {"geometry": {"type": "Polygon", "coordinates": [
                 [[20, 20], [30, 20], [30, 30], [20, 30], [20, 20]]]}, "properties": {}}]
    dans, touchees = adresses_dans_le_zonage([(1, 1), (5, 5), (50, 50)], zones)
    assert (dans, touchees) == (1, {0}), "la zone voisine ne contient aucune adresse"


def test_les_adresses_sont_celles_de_la_commune():
    csv = "code_insee;lon;lat\n99001;3.85;44.04\n99002;3.9;44.1\n99001;;\n"
    assert points_de_la_commune(csv, "99001") == [(3.85, 44.04)]


def test_la_foret_du_voisin_n_est_pas_nommee():
    limite = {"type": "Polygon", "coordinates": [CARRE]}
    foret = lambda nom, x: {"properties": {"toponyme": nom, "nature": "Forêt domaniale"},
                            "geometry": {"type": "Polygon", "coordinates": [
                                [[x, 1], [x + 2, 1], [x + 2, 3], [x, 3], [x, 1]]]}}
    assert forets_de_la_commune([foret("Ici", 1), foret("À côté", 40)], limite) == [
        ("Ici", "Forêt domaniale")]


# ── La publication (`export_incendie`) ───────────────────────────────────────

def test_sans_releve_rien_n_est_dit(base):
    from scripts.build_public_snapshot import export_incendie
    assert export_incendie(base, "99001") is None
    ensure_tables(base)
    assert export_incendie(base, "99001") is None, "tables vides : aucun relevé n'a abouti"


def test_un_zero_ne_sort_que_d_un_releve_abouti(base):
    from scripts.build_public_snapshot import export_incendie
    ensure_tables(base)
    base.execute("INSERT INTO incendie_suivi (insee, releve, debut, fin)"
                 " VALUES ('99001', 'feux', 2006, 2025)")
    base.commit()

    i = export_incendie(base, "99001")

    assert i["feux"] == {"debut": 2006, "fin": 2025, "nombre": 0, "surface_ha": 0,
                         "plus_grand": None, "liste": []}
    # Les forêts publiques n'ont pas été relevées : None, pas une liste vide.
    assert i["forets_publiques"] is None and i["boisement"] is None
    assert i["debroussaillement"] is None


def test_les_feux_publies_sont_ceux_de_la_commune(base):
    from scripts.build_public_snapshot import export_incendie
    ensure_tables(base)
    base.executemany("INSERT INTO feux VALUES (?,?,?,?,?,?)", [
        ("99001", "2016-1", "2016-08-10 15:35", 0.3, 0.141, None),
        ("99001", "2015-1", "2015-04-14 13:31", 0.2, 0.094, "Involontaire (travaux)"),
        ("99002", "2019-1", "2019-07-01 12:00", 50.0, 50.0, None)])
    base.executemany("INSERT INTO incendie_suivi (insee, releve, debut, fin) VALUES (?,?,?,?)", [
        ("99001", "feux", 2006, 2025), ("99001", "forets_publiques", None, None)])
    base.commit()

    i = export_incendie(base, "99001")

    assert (i["feux"]["nombre"], i["feux"]["surface_ha"]) == (2, 0.5)
    assert i["feux"]["plus_grand"]["alerte"] == "2016-08-10 15:35"
    assert i["forets_publiques"] == [], "relevé abouti, aucune forêt publique : un zéro mesuré"
