"""Lecture des présents : les formes rencontrées, et ce qui les faisait rater.

Les blocs de ce fichier sont copiés d'actes réels, à la ponctuation près — c'est
elle qui décide. Un conseil de trente-deux présents publié avec un seul n'a rien
d'un cas limite : c'est ce que rendait le moteur le 24/08/2026 sur les actes du
conseil communautaire d'une instance, faute d'un deux-points.
"""
from __future__ import annotations

from collectors.pv_parsers import noms, presences

# Mise en TABLEAU : la légende occupe une cellule, la liste la suivante. Aucun
# deux-points, des points-virgules pour séparer, un « et » pour le dernier — et
# un deux-points fautif au milieu, tel quel dans la pièce.
EN_TETE_TABLEAU = """DELIBERATION DU CONSEIL COMMUNAUTAIRE
Séance du 25 juin 2026 à 18h00
Le 25 juin 2026, le Conseil Communautaire s'est réuni sous la présidence de
Éric ESCANDE, Président.
Présents ARMAGNAT Anne ; BEAUFORT Jean ; ESCANDE Eric ; IMER Mathilde ;
L'ORPHELIN Samuel : MARCHÉ Damien ; TRICOTELLE Flore et VERNIER Hugues.
Pouvoirs ASTRUC Philippe à ARMAGNAT Anne ; BECHET Hélène à IMER Mathilde
Absents
Secrétaire de séance | TRICOTELLE Flore
"""

# La forme classique, avec deux-points : elle ne doit pas changer de rendu.
EN_TETE_DEUX_POINTS = """Séance du 12 mai 2026
Présents : Anne ARMAGNAT, Jean BEAUFORT, Mathilde IMER
Absents : Samuel L'ORPHELIN
Secrétaire de séance : Flore TRICOTELLE
"""


def test_bloc_des_presents_sans_deux_points():
    lus = presences(EN_TETE_TABLEAU, "nom_prenom")["presents"]

    assert len(lus) == 8, lus
    assert "Anne ARMAGNAT" in lus and "Hugues VERNIER" in lus


def test_le_point_virgule_separe_autant_que_la_virgule():
    lus = noms("ARMAGNAT Anne ; BEAUFORT Jean ; IMER Mathilde", "nom_prenom")

    assert lus == ["Anne ARMAGNAT", "Jean BEAUFORT", "Mathilde IMER"]


def test_le_dernier_nom_amene_par_et_nest_pas_perdu():
    lus = noms("TRICOTELLE Flore et VERNIER Hugues.", "nom_prenom")

    assert lus == ["Flore TRICOTELLE", "Hugues VERNIER"]


def test_un_deux_points_fautif_ne_mange_pas_le_nom_suivant():
    """« L'ORPHELIN Samuel : MARCHÉ Damien » — coquille de saisie, deux élus."""
    lus = noms("L'ORPHELIN Samuel : MARCHÉ Damien", "nom_prenom")

    assert lus == ["Samuel L'ORPHELIN", "Damien MARCHÉ"]


def test_le_president_ne_compte_pas_deux_fois_pour_un_accent():
    """« Éric ESCANDE » en ouverture, « ESCANDE Eric » dans la liste."""
    lus = presences(EN_TETE_TABLEAU, "nom_prenom")["presents"]

    assert [n for n in lus if "ESCANDE" in n.upper()] == ["Eric ESCANDE"]


def test_la_forme_a_deux_points_est_inchangee():
    lu = presences(EN_TETE_DEUX_POINTS, "prenom_nom")

    assert lu["presents"] == ["Anne ARMAGNAT", "Jean BEAUFORT", "Mathilde IMER"]
    assert lu["absents"] == ["Samuel L'ORPHELIN"]


def test_le_mot_presents_dans_une_phrase_nouvre_pas_de_bloc():
    """Sans quoi n'importe quelle phrase du corps fabriquerait des présents."""
    texte = ("Séance du 12 mai 2026\n"
             "Les conseillers présents ont approuvé le compte administratif "
             "présenté par Anne ARMAGNAT.\n")

    assert presences(texte, "nom_prenom")["presents"] == []
