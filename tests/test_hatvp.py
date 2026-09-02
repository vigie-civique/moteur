"""HATVP : rattacher une obligation à la bonne collectivité, ou à personne.

Aucun appel réseau. Les lignes reproduites sont au format du fichier
`liste.csv` de la HATVP, et les qualités citées en sont de vraies — dont celle
qui a permis de rapprocher l'intercommunalité de la commune d'essai.

Ce que ces essais protègent : la source ne porte ni code INSEE ni SIREN. Le seul
rattachement est un texte libre, et rapprocher sur la présence d'un mot
attribuerait à une commune l'obligation d'une autre — dans un dispositif de
transparence, c'est la faute qu'on ne peut pas commettre.
"""
from __future__ import annotations

from collectors.hatvp import cite_l_epci, cite_la_commune, selectionner

ENTETE = ("civilite;prenom;nom;classement;type_mandat;qualite;type_document;"
          "departement;date_publication;date_depot;nom_fichier;url_dossier;"
          "open_data;statut_publication;id_origine;url_photo")


def _ligne(qualite: str, dep: str, mandat: str = "commune", nom: str = "DUPONT",
           statut: str = "Déclaration publiée", classement: str = "ref1") -> str:
    return (f"M.;Jean;{nom};{classement};{mandat};{qualite};di;{dep};;2026-01-05;;"
            f"/pages_nominatives/{nom.lower()};;{statut};;")


class TestNomDeCommune:
    def test_le_nom_entier_est_reconnu(self):
        assert cite_la_commune("Maire de Lasalle", "Lasalle")
        assert cite_la_commune("Adjoint au maire de Saillans", "Saillans")

    def test_un_nom_plus_long_n_est_pas_le_notre(self):
        """« Lasalle » ne doit pas ramasser « Lasalle-sur-Cèze »."""
        assert not cite_la_commune("Maire de Lasalle-sur-Cèze", "Lasalle")
        assert not cite_la_commune("Maire de Saint-Just-Malmont", "Saint-Just")

    def test_un_nom_compose_est_reconnu_entier(self):
        assert cite_la_commune("Maire de Saint-Martin-de-Boubaux",
                               "Saint-Martin-de-Boubaux")

    def test_une_commune_voisine_au_nom_proche_est_ecartee(self):
        assert not cite_la_commune("Maire de Saint-Martin-de-Valgalgues",
                                   "Saint-Martin-de-Boubaux")

    def test_la_casse_et_les_accents_ne_comptent_pas(self):
        assert cite_la_commune("MAIRE D'ALES", "Alès")


class TestNomEpci:
    def test_l_ecriture_de_la_hatvp_differe_de_celle_de_la_prefecture(self):
        """Le vrai cas : deux graphies du même EPCI, rapprochées sur les mots.

        « CC du Crestois et de Pays de Saillans Cœur de Drôme » devient chez la
        HATVP « communauté de communes du Crestois et du pays de Saillans ».
        """
        assert cite_l_epci(
            "Président de la communauté de communes du Crestois et du pays de Saillans",
            "CC du Crestois et de Pays de Saillans Coeur de Drôme")

    def test_une_autre_intercommunalite_du_departement_est_ecartee(self):
        assert not cite_l_epci(
            "Vice-Président de la communauté de communes Val de Drôme en Biovallée",
            "CC du Crestois et de Pays de Saillans Coeur de Drôme")

    def test_un_seul_mot_commun_ne_suffit_pas(self):
        assert not cite_l_epci("Président de la communauté de communes des Cévennes",
                               "CC Causses Aigoual Cévennes Terres Solidaires")

    def test_un_nom_sans_mot_significatif_ne_rapproche_rien(self):
        """Un EPCI nommé « CC du Pays » ne peut rapprocher personne, et c'est bien."""
        assert not cite_l_epci("Président de la communauté de communes du Pays",
                               "CC du Pays")


class TestSelection:
    def test_le_departement_doit_correspondre(self):
        texte = "\n".join([ENTETE, _ligne("Maire de Lasalle", "34")])
        retenus, ecartes = selectionner(texte, "30", "Lasalle", None)
        assert retenus == [] and ecartes == 0    # autre département : pas même lu

    def test_le_type_de_mandat_doit_correspondre(self):
        """Un « Maire de Lasalle » rangé en `epci` ne serait pas cohérent."""
        texte = "\n".join([ENTETE, _ligne("Maire de Lasalle", "30", mandat="epci")])
        retenus, ecartes = selectionner(texte, "30", "Lasalle", None)
        assert retenus == [] and ecartes == 1

    def test_une_commune_soumise_est_retenue_avec_son_lien(self):
        texte = "\n".join([ENTETE, _ligne("Maire de Lasalle", "30")])
        retenus, _ = selectionner(texte, "30", "Lasalle", None)
        assert len(retenus) == 1
        assert retenus[0]["portee"] == "commune"
        assert retenus[0]["url"].startswith("https://www.hatvp.fr/pages_nominatives/")

    def test_les_ecarts_du_departement_sont_comptes(self):
        """Ce que le rapprochement REFUSE doit rester visible au journal."""
        texte = "\n".join([ENTETE,
                           _ligne("Maire de Lasalle", "30"),
                           _ligne("Maire d'Alès", "30", nom="MARTIN", classement="r2"),
                           _ligne("Maire de Nîmes", "30", nom="DURAND", classement="r3")])
        retenus, ecartes = selectionner(texte, "30", "Lasalle", None)
        assert len(retenus) == 1 and ecartes == 2

    def test_sans_epci_declare_aucune_ligne_epci_n_est_prise(self):
        texte = "\n".join([ENTETE,
                           _ligne("Président de la CC des Causses", "30", mandat="epci")])
        retenus, ecartes = selectionner(texte, "30", "Lasalle", None)
        assert retenus == [] and ecartes == 1
