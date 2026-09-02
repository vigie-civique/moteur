"""Mobilité et dispositifs de l'État : la commune n'est pas son rectangle.

Aucun appel réseau. Les arrêts reproduits ont la forme que rend
`transport.data.gouv.fr/api/gtfs-stops`, et l'en-tête de croisement est celui
du fichier de l'ANCT du 13/04/2026.

Ce que ces essais protègent : l'API des arrêts n'accepte qu'un RECTANGLE, et
celui d'une commune contient toujours du voisin. Sur la commune d'essai, 5 des
20 arrêts rendus sont hors du contour — les publier ferait une desserte
communale d'un tiers supérieure à la réalité.
"""
from __future__ import annotations

import io

from collectors.mobilite import DISPOSITIFS, lire_croisement, retenir_arrets

# Un carré de 0,1° de côté, tenant lieu de commune.
CONTOUR = {"type": "Polygon", "coordinates": [
    [[0.0, 45.0], [0.1, 45.0], [0.1, 45.1], [0.0, 45.1], [0.0, 45.0]]]}


def _arret(nom: str, lng: float, lat: float, reseau: str = "Réseau urbain",
           stop_id: str = "1") -> dict:
    return {"type": "Feature",
            "properties": {"dataset_title": reseau, "stop_name": nom,
                           "stop_id": stop_id, "location_type": 0},
            "geometry": {"type": "Point", "coordinates": [lng, lat]}}


class TestArrets:
    def test_l_arret_du_voisin_est_marque_dehors(self):
        lignes = retenir_arrets([_arret("Place", 0.05, 45.05, stop_id="1"),
                                 _arret("Ailleurs", 0.5, 45.5, stop_id="2")],
                                CONTOUR, "99001")
        assert [l[6] for l in lignes] == [1, 0]

    def test_rien_n_est_jete(self):
        """Les deux comptes doivent rester lisibles : dedans, et dans la boîte."""
        lignes = retenir_arrets([_arret("A", 0.05, 45.05, stop_id="1"),
                                 _arret("B", 0.5, 45.5, stop_id="2")],
                                CONTOUR, "99001")
        assert len(lignes) == 2

    def test_sans_contour_aucun_arret_n_est_declare_dans_la_commune(self):
        """Faute de contour, on ne PRÉTEND pas savoir : tout est marqué dehors.

        Le repli est la boîte englobante, et une boîte ne prouve rien. Marquer
        ces arrêts « dans la commune » ferait passer une approximation pour un
        constat.
        """
        lignes = retenir_arrets([_arret("A", 0.05, 45.05)], None, "99001")
        assert lignes[0][6] == 0

    def test_un_arret_sans_coordonnees_ne_casse_pas_la_collecte(self):
        trait = {"properties": {"stop_name": "Sans point", "stop_id": "9"},
                 "geometry": None}
        lignes = retenir_arrets([trait], CONTOUR, "99001")
        assert lignes[0][6] == 0


ENTETE = ("insee_com;lib_com;id_pvd;id_ti;id_crte;id_acv;id_ami;id_fabp;"
          "id_habinclus;id_fs;id_amm;id_acv2;id_va;id_site;id_cite;id_cde")


class TestCroisement:
    def test_seules_les_colonnes_remplies_sont_retenues(self):
        csv = ENTETE + "\n30140;Lasalle;;;crte-76-30-2;;ami-mas-04;;;1264;;;va-30-882;;;\n"
        table = lire_croisement(io.StringIO(csv))
        assert set(table["30140"]) == {"id_crte", "id_ami", "id_fs", "id_va"}
        assert table["30140"]["id_fs"] == "1264"

    def test_une_commune_sans_dispositif_reste_dans_la_table(self):
        """Sans elle, « aucun dispositif » et « commune absente » se confondraient."""
        csv = ENTETE + "\n99001;Testonville;;;;;;;;;;;;;;\n"
        table = lire_croisement(io.StringIO(csv))
        assert table["99001"] == {}

    def test_une_colonne_inconnue_est_conservee(self):
        """Un dispositif ajouté par l'ANCT doit apparaître, pas disparaître."""
        csv = ENTETE + ";id_nouveau\n30140;Lasalle;;;;;;;;;;;;;;;NEUF-1\n"
        table = lire_croisement(io.StringIO(csv))
        assert table["30140"]["id_nouveau"] == "NEUF-1"

    def test_le_dictionnaire_couvre_les_colonnes_publiees(self):
        colonnes = [c for c in ENTETE.split(";") if c.startswith("id_")]
        manquants = [c for c in colonnes if c not in DISPOSITIFS]
        assert not manquants, f"colonnes sans libellé : {manquants}"
