"""La portée d'un acte : la commune, l'intercommunalité, ou ni l'une ni l'autre.

Un site communal qui additionne les deux ment sur qui décide. « 1 997
délibérations » en page de garde de Lasalle, dont 833 votées par le conseil
communautaire : ce ne sont ni les mêmes élus, ni le même budget, ni le même
bulletin de vote, et le lecteur concluait à un conseil municipal deux fois plus
actif qu'il ne l'est.

Trois valeurs, et la troisième est une honnêteté : une annonce légale ou un
permis de construire SE PASSENT ici sans que personne d'élu les ait votés. Les
ranger sous « commune » gonflerait le compteur de l'action publique avec la vie
des entreprises.
"""
from __future__ import annotations

import pytest

from scripts.build_public_snapshot import PORTEE_PAR_PERIMETRE, portee_evenement


class TestLAssembleePrime:
    """Le type d'acte dit quelle assemblée l'a voté. Rien ne passe avant."""

    def test_une_deliberation_communautaire_reste_intercommunale(self):
        # Même quand elle ne cite que des acteurs de la commune : c'est l'EPCI
        # qui l'a votée, et c'est ça que le lecteur doit pouvoir isoler.
        assert portee_evenement("deliberation_cc", {"C1"}) == "intercommunalite"
        assert portee_evenement("conseil_communautaire", {"C1", "C2"}) == "intercommunalite"

    def test_une_deliberation_municipale_reste_communale(self):
        # Et réciproquement : un conseil municipal qui délibère sur une
        # convention avec une commune voisine délibère quand même chez lui.
        assert portee_evenement("deliberation", {"C2"}) == "commune"
        assert portee_evenement("conseil_municipal", set()) == "commune"


class TestSansAssembleeCeSontLesActeurs:
    """Un acte qu'aucune assemblée n'a voté est situé par ceux qu'il nomme."""

    def test_une_annonce_visant_un_acteur_de_la_commune(self):
        assert portee_evenement("bodacc_creation", {"C1"}) == "commune"

    def test_une_annonce_visant_une_commune_voisine(self):
        assert portee_evenement("bodacc_creation", {"C2"}) == "intercommunalite"

    def test_c1_l_emporte_sur_c2(self):
        # Un acte qui touche la commune ET une voisine intéresse d'abord la
        # commune : c'est un site communal, pas un annuaire d'EPCI.
        assert portee_evenement("bodacc_divers", {"C1", "C2"}) == "commune"

    def test_sans_acteur_rattache_c_est_le_territoire(self):
        # Un permis de construire, une annonce légale sans lien exploitable :
        # ça se passe ici, personne ne l'a voté. Le dire plutôt que le ranger.
        assert portee_evenement("autorisation_urbanisme", set()) == "territoire"
        assert portee_evenement("bodacc_vente", {"C3"}) == "territoire"

    def test_un_type_inconnu_ne_leve_pas(self):
        assert portee_evenement(None, set()) == "territoire"
        assert portee_evenement("type_invente_demain", {"C1"}) == "commune"


@pytest.mark.parametrize("perimetre, attendu", [
    ("C1", "commune"),
    ("C2", "intercommunalite"),
    ("C3", None),
    ("lien", None),
    ("", None),
])
def test_traduction_du_perimetre_d_entite(perimetre, attendu):
    """C1/C2 sont le vocabulaire du classement interne ; le site parle français.

    C3 et `lien` n'ont pas d'équivalent : ni la commune ni l'EPCI n'agit, la
    valeur retombe sur « territoire » côté appelant plutôt que de forcer un
    rattachement que rien ne fonde.
    """
    assert PORTEE_PAR_PERIMETRE.get(perimetre) == attendu
