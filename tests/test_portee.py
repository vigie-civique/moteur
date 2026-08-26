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


# ── L'éditeur situe l'acte quand aucune assemblée ne l'a voté ────────────────

class TestLEditeurCompte:
    """Ce que la mairie publie sur son propre site concerne la commune.

    Les 39 annonces d'agenda de Lasalle n'ont aucun acteur rattaché : elles
    sortaient en « territoire » et ont disparu de la page de garde le jour où
    celle-ci est devenue communale. Un filtre correct sur une donnée
    incomplète — le pire des deux mondes, parce que rien ne le signale.
    """

    def test_le_site_de_la_commune_donne_une_portee_communale(self):
        from scripts.build_public_snapshot import portee_evenement
        assert portee_evenement("local_event", set(), "exemple.invalid") == "commune"

    def test_le_site_de_l_epci_donne_une_portee_intercommunale(self):
        from scripts.build_public_snapshot import portee_evenement
        assert portee_evenement("local_event", set(), "https://epci.exemple.invalid/agenda") == "intercommunalite"

    def test_l_assemblee_prime_encore_sur_l_editeur(self):
        # Une délibération communautaire mise en ligne par la mairie reste
        # communautaire : c'est l'EPCI qui l'a votée, pas celui qui l'héberge.
        from scripts.build_public_snapshot import portee_evenement
        assert portee_evenement("deliberation_cc", set(), "exemple.invalid") == "intercommunalite"

    def test_une_source_tierce_ne_situe_rien(self):
        from scripts.build_public_snapshot import portee_evenement
        assert portee_evenement("bodacc_divers", set(), "bodacc.fr") == "territoire"


# ── Ce qu'une fiche ne disait pas d'elle-même ───────────────────────────────

class TestEtatDActivite:
    """Sur 744 « entreprises » publiées à Lasalle, 388 étaient CESSÉES."""

    def test_une_entreprise_radiee_n_est_pas_active(self):
        from scripts.build_public_snapshot import etat_activite
        assert etat_activite({"biz_status": "C", "business_closing_date": "2015-03-01"}) \
            == (False, "2015-03-01")

    def test_une_association_dissoute_n_est_pas_active(self):
        from scripts.build_public_snapshot import etat_activite
        assert etat_activite({"asso_status": "D", "dissolution_date": "2019-06-02"}) \
            == (False, "2019-06-02")

    def test_le_registre_de_l_association_prime_sur_celui_des_entreprises(self):
        # Une association dissoute au JO dont l'établissement SIRENE traîne
        # encore en « A » est dissoute. Le RNA est le registre qui fait foi.
        from scripts.build_public_snapshot import etat_activite
        assert etat_activite({"asso_status": "D", "biz_status": "A"})[0] is False

    def test_le_silence_des_registres_n_est_pas_une_activite(self):
        # C'est la case où se cachent les structures dormantes : une
        # association qui a cessé de se réunir sans le déclarer reste « A »
        # pour toujours. `None` dit qu'on ne sait pas, et ça se voit.
        from scripts.build_public_snapshot import etat_activite
        assert etat_activite({}) == (None, None)
        assert etat_activite({"business_closing_date": "2020-01-01"}) == (None, "2020-01-01")


class TestNatureDEntreprise:
    """505 des 744 étaient individuelles, 112 ne font que détenir."""

    def test_l_activite_immobiliere_l_emporte_sur_la_forme(self):
        # Une entreprise individuelle qui loue des logements détient ;
        # une SCI en NAF construction construit. C'est ce que la structure
        # FAIT qui répond à la question, pas comment elle est montée.
        from scripts.build_public_snapshot import nature_entreprise
        assert nature_entreprise({"naf_code": "6820A", "legal_form_code": "1000"}) == "patrimoniale"
        assert nature_entreprise({"naf_code": "4120A", "legal_form_code": "6540"}) == "societe"

    def test_l_entreprise_individuelle_se_distingue(self):
        from scripts.build_public_snapshot import nature_entreprise
        assert nature_entreprise({"naf_code": "4399C", "legal_form_code": "1000"}) == "individuelle"

    def test_tout_le_reste_est_une_societe(self):
        from scripts.build_public_snapshot import nature_entreprise
        assert nature_entreprise({"naf_code": "5610A", "legal_form_code": "5499"}) == "societe"
        assert nature_entreprise({}) == "societe"


class TestDerniereTrace:
    """Ce qu'on peut dire quand les registres se taisent.

    28 associations et 92 entreprises de Lasalle ne sont ni cessées ni
    dissoutes, et rien ne dit non plus qu'elles vivent : une association qui a
    cessé de se réunir sans déclarer sa dissolution reste « A » au Journal
    officiel pour toujours. On ne peut pas conclure — on peut dater la dernière
    fois qu'une source publique l'a nommée, et laisser lire.
    """

    def test_l_annee_et_pas_la_date(self, base, entite):
        """Un flux financier n'a que son millésime.

        Lui donner un jour le ferait passer pour plus précis qu'il n'est, et un
        acteur documenté par un seul flux paraîtrait plus récent qu'un acteur
        cité dans une délibération du même exercice.
        """
        from scripts.build_public_snapshot import _annee_de_trace
        assert _annee_de_trace("2016-03-04") == 2016
        assert _annee_de_trace(2016) == 2016
        assert _annee_de_trace(None) is None
        assert _annee_de_trace("") is None
        assert _annee_de_trace("sans date") is None
