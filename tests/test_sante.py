"""FINESS : le code commune reconstitué, et des coordonnées qui ne sont pas des degrés.

Aucun appel réseau. Les lignes reproduites sont au format exact de l'extraction
du ministère (fichier SANS en-tête, deux types d'enregistrement).

Ce que ces essais protègent :
  1. FINESS n'écrit pas le code INSEE : il écrit le département et un code
     commune sur trois chiffres, qu'il faut recoller — et recoller aussi en
     Corse, où le département n'est pas un nombre ;
  2. les coordonnées sont PROJETÉES. Lues comme des degrés, elles poseraient les
     fiches dans le golfe de Guinée ; lues hors Lambert 93, elles seraient
     fausses ailleurs.
"""
from __future__ import annotations

from collectors.sante import STRUCTURE, _insee, coordonnees, lire

LAMBERT = "2,ATLASANTE,100,BDADRESSE,EPSG:2154 RGF93 / Lambert-93 (Métropole)"
MAYOTTE = "2,ATLASANTE,89,BAN,EPSG:4471 RGM04/UTM zone 38S (Mayotte)"


def _structureet(finess: str, nom: str, dep: str, com: str) -> str:
    champs = [""] * 32
    champs[0] = "structureet"
    champs[STRUCTURE["finess"]] = finess
    champs[STRUCTURE["finess_ej"]] = finess
    champs[STRUCTURE["raison_sociale"]] = nom
    champs[STRUCTURE["raison_sociale_longue"]] = nom
    champs[STRUCTURE["num_voie"]] = "1"
    champs[STRUCTURE["type_voie"]] = "RTE"
    champs[STRUCTURE["voie"]] = "DE LA POSTE"
    champs[STRUCTURE["commune"]] = com
    champs[STRUCTURE["departement"]] = dep
    champs[STRUCTURE["acheminement"]] = "30460 LASALLE"
    champs[STRUCTURE["categorie_libelle"]] = "Pharmacie d'Officine"
    return ";".join(champs)


class TestCodeCommune:
    def test_le_code_insee_se_recolle(self):
        ligne = _structureet("300006475", "PHARMACIE", "30", "140").split(";")
        assert _insee(ligne) == "30140"

    def test_un_code_commune_court_est_complete(self):
        ligne = _structureet("010000024", "CH", "01", "45").split(";")
        assert _insee(ligne) == "01045"

    def test_la_corse_garde_sa_lettre(self):
        ligne = _structureet("2A0000001", "CH", "2A", "004").split(";")
        assert _insee(ligne) == "2A004"

    def test_sans_departement_aucun_code_n_est_fabrique(self):
        ligne = _structureet("999", "X", "", "140").split(";")
        assert _insee(ligne) == ""


class TestCoordonnees:
    def test_le_lambert_93_devient_des_degres(self):
        lat, lng = coordonnees("752000", "6320000", LAMBERT)
        # Quelque part dans le Gard : la conversion doit rendre des degrés
        # plausibles, pas les mètres de départ.
        assert 43.0 < lat < 45.0 and 3.0 < lng < 5.0

    def test_un_autre_systeme_ne_donne_aucune_position(self):
        """Mieux vaut une fiche sans position qu'une fiche à Mayotte-sur-Loire."""
        assert coordonnees("512658.2", "8585893.9", MAYOTTE) == (None, None)

    def test_une_coordonnee_illisible_ne_casse_rien(self):
        assert coordonnees("", "", LAMBERT) == (None, None)
        assert coordonnees("abc", "def", LAMBERT) == (None, None)


class TestLecture:
    def test_seules_les_communes_demandees_sont_retenues(self, tmp_path):
        fichier = tmp_path / "finess.csv"
        fichier.write_text("\n".join([
            "finess;etalab;98;2026-05-12",
            _structureet("300006475", "PHARMACIE DE LA SALENDRINQUE", "30", "140"),
            _structureet("010000024", "CH DE FLEYRIAT", "01", "451"),
            f"geolocalisation;300006475;752000;6320000;{LAMBERT};2026-05-04",
            f"geolocalisation;010000024;841166.7;6581529.1;{LAMBERT};2026-05-04",
        ]) + "\n", encoding="utf-8")
        etabs, positions = lire(fichier, {"30140"})
        assert list(etabs) == ["300006475"]
        # La position de l'établissement écarté ne doit pas être retenue non
        # plus : une table de positions qui déborde finirait par en attribuer
        # une à la mauvaise fiche.
        assert list(positions) == ["300006475"]

    def test_une_ligne_tronquee_est_ignoree_sans_planter(self, tmp_path):
        """Le fichier n'a pas d'en-tête : une ligne courte ne doit pas l'arrêter."""
        fichier = tmp_path / "finess.csv"
        fichier.write_text("\n".join([
            "finess;etalab;98;2026-05-12",
            "structureet;300006475;incomplet",
            _structureet("300006475", "PHARMACIE", "30", "140"),
        ]) + "\n", encoding="utf-8")
        etabs, _ = lire(fichier, {"30140"})
        assert list(etabs) == ["300006475"]
