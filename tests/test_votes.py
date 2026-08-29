"""Le décompte des voix, dans toutes les tournures que les PV emploient.

Les huit formes ci-dessous ne sont pas inventées : elles sont relevées sur les
254 passages de vote des procès-verbaux de la commune, avec leur fréquence. Un
motif qui n'acceptait que « X voix pour et Y contre », dans cet ordre, en
manquait 48 — et les manquait en SILENCE, en enregistrant zéro opposition.

Conséquence publiée : les 26 délibérations dont le texte porte « N voix contre »
étaient comptées comme adoptées sans opposition, et la page annonçait « 90 %
adoptés sans une voix contre ni une abstention ».
"""
import pytest

from collectors.cm_parser import extract_vote


@pytest.mark.parametrize("texte,attendu", [
    # 94× — la forme la plus courante
    ("Le Conseil Municipal, après en avoir délibéré, par 12 voix « Pour » "
     "et 1 abstention (M. DUPONT) :", {"pour": 12, "contre": 0, "abstentions": 1}),
    # 64×
    ("adopté par 13 voix pour et 1 voix contre (Jean Pierre ESPAZE)",
     {"pour": 13, "contre": 1, "abstentions": 0}),
    # 45×
    ("Le Conseil Municipal, après en avoir délibéré, par 11 voix « Pour » :",
     {"pour": 11, "contre": 0, "abstentions": 0}),
    # 21× — l'opposition ANNONCÉE EN PREMIER, lue comme zéro jusqu'au 29/08/2026
    ("Le conseil municipal par 3 voix contre (MF, JPE et AR) et 10 voix pour",
     {"pour": 10, "contre": 3, "abstentions": 0}),
    # 10× — le « pour » n'est pas écrit : « et 11 voix » tout court
    ("Le Conseil Municipal, après en avoir délibéré, par 1 « abstention » et 11 voix :",
     {"pour": 11, "contre": 0, "abstentions": 1}),
    # 9× — pas de « pour » du tout
    ("Le Conseil Municipal, après en avoir délibéré, 1 voix contre (Jean Pierre ESPAZE) :",
     {"pour": None, "contre": 1, "abstentions": 0}),
    # 8×
    ("après en avoir délibéré, 1 abstention (Armelle ROUVERET) et 11 voix pour :",
     {"pour": 11, "contre": 0, "abstentions": 1}),
    # 1× — les trois mentions
    ("Le conseil municipal, après en avoir délibéré, par 9 voix « Pour », "
     "2 voix « Contre » (Mme ZANCHI, Mme ROLAND), et 2 abstentions :",
     {"pour": 9, "contre": 2, "abstentions": 2}),
])
def test_toutes_les_tournures_des_pv(texte, attendu):
    vote = extract_vote(texte)
    assert vote is not None, "aucun vote lu"
    for cle, valeur in attendu.items():
        assert vote[cle] == valeur, f"{cle} : {vote[cle]} au lieu de {valeur}"


def test_unanimite_sans_decompte():
    assert extract_vote("après en avoir délibéré, décide à l'unanimité :") == {
        "pour": None, "contre": 0, "abstentions": 0, "unanimite": True}


def test_une_opposition_interdit_l_unanimite():
    """« à l'unanimité » et une voix contre ne peuvent pas coexister."""
    v = extract_vote("adopté à l'unanimité des présents, par 10 voix pour et 2 voix contre")
    assert v["contre"] == 2
    assert v["unanimite"] is False


def test_un_texte_sans_vote_ne_rend_rien():
    assert extract_vote("Le maire informe le conseil d'un courrier de la préfecture.") is None


def test_les_votants_nommes_sortent_d_une_mention_de_vote():
    """Toute parenthèse n'est pas un votant.

    L'ancienne version prenait n'importe quelle parenthèse commençant par une
    majuscule : sur une délibération de subventions, elle rangeait
    « (Anciennement Mandragora) » — un ancien nom d'association — parmi les
    personnes ayant voté contre.
    """
    v = extract_vote("par 10 voix pour : DECIDE d'attribuer à l'association "
                     "LES NOCTURNES (Anciennement Mandragora) une subvention")
    assert "nommés" not in v or "Mandragora" not in " ".join(v["nommés"])


def test_deux_deliberations_dans_un_bloc_ne_s_additionnent_pas():
    """Un décompte ne peut pas dépasser l'effectif du conseil.

    Le découpage laisse parfois deux délibérations dans un même bloc, chacune
    avec son vote. Une fenêtre de lecture large les additionnait : « par 3 voix
    contre et 10 voix pour », deux fois, donnait 20 pour et 6 contre dans un
    conseil de treize membres. La fenêtre est donc la LIGNE, et rien de plus.
    """
    bloc = (
        "M. SCHWEDA : Montant demandé : 540 € ; Montant attribué : 100 €\n"
        "Le Conseil Municipal, après en avoir délibéré par 3 voix « contre » "
        "et 10 voix « pour » :\n"
        "− DECIDE d'attribuer à l'association Le Nez au Vent une subvention de 100 €,\n"
        "LES NOCTURNES DE LASALLE (Anciennement Mandragora)\n"
        "M. SCHWEDA : Montant demandé : 2 200 € ; Montant attribué : 500 €\n"
        "Le Conseil Municipal, après en avoir délibéré par 3 voix « contre » "
        "et 10 voix « pour » :")
    v = extract_vote(bloc)
    assert (v["pour"], v["contre"]) == (10, 3), "les deux votes ont été additionnés"


@pytest.mark.parametrize("texte", [
    "Le total des dépenses 2016 s'élève à 1 147 555,28 € pour la commune",
    "BUDGET 2024 pour la commune, section investissement",
    "les taux 2019 pour la part communale",
])
def test_un_millesime_n_est_pas_un_decompte(texte):
    """Un décompte de voix ne dépasse pas l'effectif d'une assemblée.

    « 2016 … pour » se lit comme 2 016 voix pour. 232 délibérations de Lasalle
    en portaient un après la première correction du parseur — un défaut mis en
    ligne avant d'être vu. Aucun conseil communautaire n'a mille délégués.
    """
    assert extract_vote(texte) is None


def test_un_gros_conseil_communautaire_reste_lisible():
    """La borne ne doit pas exclure une vraie grande assemblée."""
    v = extract_vote("Le conseil communautaire, par 87 voix pour, adopte")
    assert v["pour"] == 87
