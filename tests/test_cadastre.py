"""Cadastre : la référence de DVF n'est pas l'identifiant du plan.

Aucun appel réseau. Les identifiants reproduits sont ceux du fichier Etalab de
la commune d'essai, et les références DVF celles de sa base.

Ce que ces essais protègent : DVF écrit `AC` / `0323`, le cadastre écrit
`301400000AC0323`. Sans le calage de la section sur deux caractères et du numéro
sur quatre, le rapprochement ne trouve RIEN — et un silence total se lirait
comme « aucune parcelle connue » au lieu de « clé mal formée ».
"""
from __future__ import annotations

from collectors.cadastre import _departement, centroide, identifiant_dvf


class TestIdentifiant:
    def test_la_section_est_calee_sur_deux_caracteres(self):
        assert identifiant_dvf("30140", "A", "28") == "301400000A0028"

    def test_une_section_deja_a_deux_caracteres_ne_bouge_pas(self):
        # Relevé dans le fichier Etalab de la commune d'essai : `30140000AC0001`.
        # L'identifiant fait TOUJOURS quatorze caractères — c'est la section qui
        # occupe deux places, calées à gauche, pas une chaîne qu'on allonge.
        assert identifiant_dvf("30140", "AC", "323") == "30140000AC0323"

    def test_l_identifiant_fait_toujours_quatorze_caracteres(self):
        for section, numero in (("A", "28"), ("AC", "323"), ("0B", "0360")):
            assert len(identifiant_dvf("30140", section, numero)) == 14

    def test_le_numero_est_cale_sur_quatre(self):
        assert identifiant_dvf("30140", "0B", "360") == "301400000B0360"

    def test_dvf_ecrit_parfois_le_numero_deja_cale(self):
        assert identifiant_dvf("30140", "0B", "0360") == "301400000B0360"

    def test_un_prefixe_de_commune_deleguee_est_respecte(self):
        """Une commune absorbée garde son préfixe : `000` y serait faux."""
        assert identifiant_dvf("30140", "A", "28", prefixe="044") == "301400440A0028"

    def test_une_reference_incomplete_ne_fabrique_pas_de_cle(self):
        assert identifiant_dvf("30140", "", "28") == ""
        assert identifiant_dvf("30140", "A", "") == ""


class TestDepartement:
    def test_metropole(self):
        assert _departement("30140") == "30"

    def test_corse(self):
        assert _departement("2A004") == "2A"

    def test_outre_mer(self):
        assert _departement("97401") == "974"


class TestCentroide:
    def test_le_centre_d_un_carre_est_son_milieu(self):
        carre = {"type": "Polygon", "coordinates": [
            [[3.0, 44.0], [3.2, 44.0], [3.2, 44.2], [3.0, 44.2], [3.0, 44.0]]]}
        lat, lng = centroide(carre)
        assert abs(lat - 44.08) < 0.05 and abs(lng - 3.08) < 0.05

    def test_une_geometrie_vide_ne_donne_pas_de_point(self):
        assert centroide({}) == (None, None)
        assert centroide({"coordinates": []}) == (None, None)
