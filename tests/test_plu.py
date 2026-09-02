"""Document d'urbanisme au GPU : attribution, mesure du territoire, garde-fous.

Aucun appel réseau. Les propriétés reproduites sont celles que
`apicarto.ign.fr/api/gpu` a rendues le 02/09/2026 sur Saillans et Brassac — et
les intrus sont de VRAIS voisins, ceux que la requête a effectivement ramenés
parce que leur frontière touche la commune interrogée.

Ce que ces essais protègent :
  1. l'interrogation se fait par géométrie, donc elle rend aussi le document du
     voisin — l'attribuer serait donner à une commune le PLU d'une autre ;
  2. un PLUi se dépose par partitions territoriales, dont une seule s'applique
     ici : la retenir sur un simple CONTACT de zone en ferait deux ;
  3. une part de territoire ne se calcule pas en sommant des zones qui
     débordent — mesurée ainsi, elle vaudrait quand même 100 %.
"""
from __future__ import annotations

from collectors.geometrie import aire_m2, dedans, grille
from collectors.plu import _date_approbation, _famille, attribuer

INSEE, EPCI = "81037", "200066561"


def _doc(grid_name: str, titre: str, du_type: str, nom: str,
         partition: str) -> dict:
    return {"properties": {"grid_name": grid_name, "grid_title": titre,
                           "du_type": du_type, "name": nom,
                           "partition": partition, "gpu_status": "production",
                           "gpu_timestamp": "2026-03-03T22:00:17.938Z"}}


# Ce que la requête sur Brassac a réellement rendu : deux partitions du PLUi de
# son intercommunalité, et le PLU de la commune d'Angles.
DOCUMENTS_BRASSAC = [
    _doc(EPCI, "PLUI SIDOBRE VALS ET PLATEAUX", "PLUi",
         "200066561_PLUi_20260223_A", "DU_200066561_A"),
    _doc(EPCI, "PLUI SIDOBRE VALS ET PLATEAUX", "PLUi",
         "200066561_PLUi_20241202_B", "DU_200066561_B"),
    _doc("81014", "ANGLES", "PLU", "81014_PLU_20240909", "DU_81014"),
]

# Et sur Saillans : la carte communale d'une voisine, le PLU d'une autre, le sien.
DOCUMENTS_SAILLANS = [
    _doc("26015", "AUBENASSON", "CC", "26015_CC_20220218", "DU_26015"),
    _doc("26183", "MIRABEL-ET-BLACONS", "PLU", "26183_PLU_20230322", "DU_26183"),
    _doc("26289", "SAILLANS", "PLU", "26289_PLU_20200306", "DU_26289"),
]


class TestAttribution:
    def test_le_document_du_voisin_est_ecarte(self):
        notres, ecartes = attribuer(DOCUMENTS_SAILLANS, "26289", "200040509")
        assert [d["partition"] for d in notres] == ["DU_26289"]
        assert ecartes == ["AUBENASSON", "MIRABEL-ET-BLACONS"]

    def test_le_document_intercommunal_est_le_notre(self):
        notres, ecartes = attribuer(DOCUMENTS_BRASSAC, INSEE, EPCI)
        assert [d["portee"] for d in notres] == ["intercommunal", "intercommunal"]
        assert ecartes == ["ANGLES"]

    def test_sans_epci_declare_seul_le_communal_passe(self):
        """Une instance sans intercommunalité ne doit pas hériter d'un PLUi.

        Le piège est le `grid_name` vide comparé à un `EPCI_SIREN` vide : deux
        chaînes vides sont égales, et tout document sans grille serait devenu
        celui de la commune.
        """
        notres, ecartes = attribuer(DOCUMENTS_BRASSAC + [_doc("", "", "PLU", "", "DU_X")],
                                    INSEE, "")
        assert notres == []
        assert len(ecartes) == 4

    def test_la_date_vient_du_nom_du_document(self):
        notres, _ = attribuer(DOCUMENTS_SAILLANS, "26289", None)
        assert notres[0]["date_appro"] == "2020-03-06"

    def test_un_nom_sans_date_ne_fabrique_pas_de_date(self):
        assert _date_approbation("26289_PLU") is None
        assert _date_approbation("26289_PLU_99999999") is None
        assert _date_approbation(None) is None


class TestFamilles:
    def test_les_sous_zones_rejoignent_leur_famille(self):
        assert _famille("AUc") == "à urbaniser"
        assert _famille("AUs") == "à urbaniser"
        assert _famille("Ua") == "urbaine"
        assert _famille("N") == "naturelle"
        assert _famille("A") == "agricole"

    def test_un_type_inconnu_ne_recoit_pas_de_famille(self):
        assert _famille("Zzz") is None
        assert _famille("") is None
        assert _famille(None) is None


# Un carré de 0,1° de côté, avec un trou carré en son milieu.
CARRE = {"type": "Polygon", "coordinates": [
    [[0.0, 45.0], [0.1, 45.0], [0.1, 45.1], [0.0, 45.1], [0.0, 45.0]],
    [[0.04, 45.04], [0.06, 45.04], [0.06, 45.06], [0.04, 45.06], [0.04, 45.04]],
]}


class TestGeometrie:
    def test_le_trou_est_hors_du_polygone(self):
        assert dedans(0.02, 45.02, CARRE)
        assert not dedans(0.05, 45.05, CARRE)      # dans le trou
        assert not dedans(0.5, 45.5, CARRE)        # au loin

    def test_la_surface_deduit_le_trou(self):
        # Le carré fait 0,1° × 0,1°, le trou 0,02° × 0,02° : 4 % de moins.
        plein = {"type": "Polygon", "coordinates": [CARRE["coordinates"][0]]}
        assert abs(aire_m2(CARRE, 45.0) / aire_m2(plein, 45.0) - 0.96) < 1e-9

    def test_la_grille_ne_pose_de_points_que_dans_la_commune(self):
        points = grille(CARRE, 2000)
        assert points, "une géométrie non vide doit recevoir des points"
        assert all(dedans(x, y, CARRE) for x, y in points)

    def test_la_grille_est_reproductible(self):
        """Deux collectes doivent rendre le même chiffre.

        Une grille tirée au sort ferait varier la part publiée d'une collecte à
        l'autre, et cette variation se lirait comme un changement du territoire.
        """
        assert grille(CARRE, 2000) == grille(CARRE, 2000)

    def test_la_part_mesuree_retrouve_la_part_reelle(self):
        """Le trou fait 4 % du carré : l'échantillon doit le dire à 0,5 point."""
        points = grille(CARRE, 8000)
        plein = {"type": "Polygon", "coordinates": [CARRE["coordinates"][0]]}
        dans_le_plein = grille(plein, 8000)
        part_trou = 100 * (1 - len(points) / len(dans_le_plein))
        assert abs(part_trou - 4.0) < 0.5
