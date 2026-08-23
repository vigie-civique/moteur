"""Un montant voté n'est pas un montant payé.

Sur Lasalle au 23/08/2026, les 193 flux financiers portaient tous
`statut = 'realise'` : la subvention votée en conseil, la dotation lue dans les
comptes administratifs, le marché notifié et la demande de DSIL avec le même
mot. La page Finances en tirait « la commune a versé 10 k€ » pour un exercice
2026 dont aucun paiement n'est consolidé — les 18 lignes viennent toutes de
délibérations.

Le seul endroit où la page rattrapait la nuance cherchait « demandée » dans le
NOM du type : un accident de libellé tenait lieu de modèle de données, et il ne
marchait que pour `DSIL_demande`.

L'état se DÉDUIT de la provenance : un compte administratif atteste un
paiement, une délibération atteste un vote, un avis de notification atteste un
engagement. Quand la provenance ne dit rien, l'état est `inconnu` — jamais
`paye` par défaut, parce que c'est l'affirmation la plus forte des cinq.

Les cas ci-dessous sont les sources réellement présentes dans la base.
"""
from __future__ import annotations

import pytest

from collectors.etat_flux import DEFINITIONS, ETATS, est_verse, etat_du_flux


class TestDeductionParSource:
    @pytest.mark.parametrize("source", ["OFGL", "Comptes administratifs 2024",
                                        "balance comptable"])
    def test_les_comptes_attestent_un_paiement(self, source):
        assert etat_du_flux("DGF", source) == "paye"

    @pytest.mark.parametrize("source", ["CR CM 2026", "CR CM 2022", "CM",
                                        "Délibération du 12/03", "PV du conseil"])
    def test_une_deliberation_atteste_un_vote(self, source):
        assert etat_du_flux("subvention", source) == "vote"

    @pytest.mark.parametrize("source", ["DECP v3 data.economie.gouv.fr",
                                        "DECP data.gouv.fr", "BOAMP"])
    def test_un_marche_notifie_est_engage(self, source):
        assert etat_du_flux("marché", source) == "engage"

    @pytest.mark.parametrize("source", [None, "", "source inconnue"])
    def test_sans_provenance_lisible_letat_reste_inconnu(self, source):
        """Le défaut ne peut pas être `paye` : c'est l'affirmation la plus forte."""
        assert etat_du_flux("subvention", source) == "inconnu"


class TestDeductionParType:
    @pytest.mark.parametrize("type_", ["DSIL_demande", "DETR_demande",
                                       "Fonds_Vert_demande", "subvention_demandee"])
    def test_une_demande_reste_une_demande_meme_votee_en_conseil(self, type_):
        """C'est le conseil qui décide de SOLLICITER : la décision porte sur la
        demande, pas sur un versement. Ces trois types existent en base et
        pesaient 1 014 828 € comptés comme réalisés."""
        assert etat_du_flux(type_, "CR CM 2024") == "demande"

    def test_une_annulation_prime_sur_la_source(self):
        assert etat_du_flux("subvention_annulee", "CR CM 2025") == "annule"


class TestSaisieHumaine:
    """Quelqu'un qui saisit dans l'atelier a lu la pièce : il gagne."""

    @pytest.mark.parametrize("statut", ["vote", "engage", "paye", "demande", "annule"])
    def test_la_saisie_prime_sur_la_deduction(self, statut):
        assert etat_du_flux("DGF", "OFGL", statut) == statut

    @pytest.mark.parametrize("statut", ["realise", "", None])
    def test_realise_natteste_rien_et_ne_prime_sur_rien(self, statut):
        """`realise` était la valeur par défaut de la colonne, posée par tous les
        collecteurs sans y penser. Elle ne peut pas valoir témoignage."""
        assert etat_du_flux("subvention", "CR CM 2026", statut) == "vote"

    def test_la_casse_de_la_saisie_ne_change_rien(self):
        assert etat_du_flux("subvention", "CR CM 2026", "PAYE") == "paye"


class TestVocabulaire:
    def test_verse_ne_vaut_que_pour_un_paiement(self):
        """Le seul prédicat qui autorise le mot « versé » à l'écran."""
        assert est_verse("paye")
        for autre in ("vote", "engage", "demande", "annule", "inconnu"):
            assert not est_verse(autre), autre

    def test_chaque_etat_porte_sa_definition(self):
        """Le site reprend ces phrases mot pour mot : un état sans définition
        serait une étiquette que le lecteur devrait interpréter seul."""
        assert set(DEFINITIONS) == set(ETATS)
        assert all(DEFINITIONS[e].strip() for e in ETATS)

    def test_toute_deduction_tombe_dans_le_vocabulaire_declare(self):
        for type_ in ("subvention", "DGF", "marché", "DSIL_demande", "bail", ""):
            for source in ("OFGL", "CR CM 2024", "DECP", "", None):
                assert etat_du_flux(type_, source) in ETATS
