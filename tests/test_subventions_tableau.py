"""Les subventions votées en TABLEAU, et l'assemblée qui les a votées.

`SUBV_RE` lit une phrase — « attribuer à X une subvention de N € ». C'est la
forme communale. L'intercommunalité vote toutes ses subventions en une fois et
les présente en tableau : le régime de la phrase n'y trouve rien, et les
25 associations subventionnées par la CC de Lasalle en 2019 — dont la Filature
du Mazel pour 25 500 € — ne sortaient d'aucun collecteur alors que le texte
était en base.

Les extraits sont fidèles aux procès-verbaux réels : trois mises en page
coexistent dans le même corpus, et deux d'entre elles portent en fin de ligne
l'issue du vote, qui NOMME les élus qui se déportent.
"""
from __future__ import annotations

import pytest

from collectors.cm_finances import (Resolver, _domaine, extract_subventions_tableau,
                                    lire_tableau, payeur)
from collectors.config import COMMUNE_URL, EPCI_URL

# Les domaines viennent de la CONFIGURATION, jamais écrits en dur : la suite
# tourne sur une instance fictive, et un test qui nomme lasalle.fr ne passerait
# que chez son auteur.
SITE_COMMUNE = _domaine(COMMUNE_URL)
SITE_EPCI = _domaine(EPCI_URL)

# Montant sur sa propre ligne, et un qualificatif entre parenthèses.
PV_COLONNES = """Après délibération, le Conseil Communautaire, à l'unanimité, décide d'accorder pour
l'exercice 2018 les subventions à :
SUBVENTIONS
ASSOCIATIONS
ANNEE 2018
Office de Tourisme Mt Aigoual Causses Cévennes
217 000 €
(fonctionnement 157000 € + mise à disposition personnel 60 000 €)
AFR Lous Pitchouns Anhels (crèche Lanuéjols) 41 000 €
ASLH multi-site de l'Aigoual 19 116 €
"""

# L'issue du vote suit le montant, et déborde sur sa propre ligne en nommant
# des élus. Montants avec centimes.
PV_AVEC_VOTES = """ASSOCIATION Montant Vote
AIGOUAL ORIENTATION 409 € A l'unanimité
ART'REVES 245,40 € 24 pour et 1 abstention (Régis Valgalier)
21 pour, 1 contre (Jean Pierre Espaze) et
CHAMP CONTRECHAMP 6 135 € 3 abstentions (Henri De Latour, Jocelyne
Zanchi et Patrick Bénéfice)
LA FILATURE DU MAZEL 818 €
TOTAL 7 607,40 €
"""

# L'annotation de vote collée au nom, et le montant à la ligne suivante.
PV_NOM_ANNOTE = """Après délibération, le Conseil Communautaire décide d'accorder pour l'exercice 2019 des
subventions à :
MONTANT
ASSOCIATIONS PROPOSE EN Vote du Conseil communautaire
LA FILATURE du MAZEL A l'unanimité
4 600 €
Projet land'art
LA TRUITE DU BONHEUR 460 €
VIVALTO 3 220 €
"""

# Une DEMANDE : les lignes nomment des financeurs, pas des bénéficiaires.
PV_PLAN_DE_FINANCEMENT = """Demande de subvention Fête de la Transhumance 2026
Le plan de financement s'établit comme suit :
Région Occitanie 2 500 €
Conseil départemental du Gard 5 000 €
Parc National des Cévennes 5 000 €
Autofinancement CC CACTS 12 500 €
"""


def lignes(texte):
    return dict(lire_tableau(texte))


# ── Les trois mises en page ──────────────────────────────────────────────────

def test_le_montant_sur_sa_propre_ligne_est_rattache_au_nom_precedent():
    assert lignes(PV_COLONNES)["Office de Tourisme Mt Aigoual Causses Cévennes"] == 217000


def test_le_montant_en_fin_de_ligne_est_lu():
    assert lignes(PV_AVEC_VOTES)["AIGOUAL ORIENTATION"] == 409


def test_un_nom_annote_par_le_vote_garde_le_montant_qui_suit():
    """« LA FILATURE du MAZEL A l'unanimité » puis « 4 600 € ». Écarter la
    ligne parce qu'elle parle du vote jetait le nom, et avec lui le montant."""
    assert lignes(PV_NOM_ANNOTE)["LA FILATURE du MAZEL"] == 4600


def test_les_centimes_sont_lus():
    assert lignes(PV_AVEC_VOTES)["ART'REVES"] == 245


# ── Ce qui n'est pas un bénéficiaire ─────────────────────────────────────────

def test_la_ligne_de_total_ferme_le_tableau():
    assert not any("TOTAL" in nom.upper() for nom in lignes(PV_AVEC_VOTES))


def test_les_entetes_ne_sont_pas_des_beneficiaires():
    lus = lignes(PV_COLONNES)
    assert not ({"SUBVENTIONS", "ASSOCIATIONS", "ANNEE 2018"} & set(lus))


def test_un_entete_ne_ferme_pas_le_tableau():
    """Trois lignes d'en-tête séparent la phrase d'ouverture de la première
    association. Les compter comme illisibles épuisait la tolérance, et le
    tableau se fermait sur son propre titre."""
    assert len(lignes(PV_COLONNES)) == 3


def test_les_elus_deportes_ne_deviennent_pas_beneficiaires():
    """Un tableau de subventions est aussi une liste de conflits d'intérêts
    déclarés. Ces noms sont des personnes physiques : les lire comme des
    associations les publierait comme bénéficiaires d'argent public."""
    lus = " | ".join(lignes(PV_AVEC_VOTES))
    for nom in ("Valgalier", "Espaze", "De Latour", "Zanchi", "Bénéfice"):
        assert nom not in lus


def test_un_plan_de_financement_nest_pas_un_tableau_dattribution():
    """Ses lignes nomment les FINANCEURS. Les lire ici inverserait le sens de
    l'argent — « l'intercommunalité a versé 2 500 € à la Région Occitanie »."""
    assert lire_tableau(PV_PLAN_DE_FINANCEMENT) == []


def test_le_qualificatif_entre_parentheses_quitte_le_nom():
    """« (crèche Lanuéjols) » précise l'objet, pas l'identité. Le garder
    séparait l'association de ses autres lignes dans le même tableau."""
    assert "AFR Lous Pitchouns Anhels" in lignes(PV_COLONNES)


def test_le_detail_entre_parentheses_nest_pas_une_ligne():
    assert 157000 not in lignes(PV_COLONNES).values()


# ── L'assemblée qui a voté ───────────────────────────────────────────────────

def test_le_type_dit_lassemblee():
    assert payeur("deliberation", SITE_COMMUNE) == "commune"
    assert payeur("conseil_municipal", SITE_COMMUNE) == "commune"
    assert payeur("deliberation_cc", SITE_EPCI) == "epci"
    assert payeur("conseil_communautaire", SITE_EPCI) == "epci"


def test_lediteur_tranche_quand_le_type_dit_commune():
    """44 séances du conseil COMMUNAUTAIRE de Lasalle portent le type
    `conseil_municipal` — résidu du redécoupage qui enregistrait en portée
    commune les PV de l'intercommunalité. Les croire ferait payer par la
    commune des subventions votées par l'EPCI."""
    assert payeur("conseil_municipal", SITE_EPCI) == "epci"


def test_un_editeur_inconnu_reste_a_la_commune():
    assert payeur("deliberation", "web.archive.org") == "commune"


# ── Bout en bout, sur une base réelle ────────────────────────────────────────

@pytest.fixture
def pose(base):
    def _poser(type_, source, date, titre, contenu):
        base.execute(
            "INSERT INTO events (type, date, title, content, source) VALUES (?,?,?,?,?)",
            (type_, date, titre, contenu, source))
        base.commit()
    return _poser


def test_le_flux_porte_lassemblee_qui_la_vote(base, pose):
    pose("deliberation_cc", SITE_EPCI, "2018-04-04",
         "Subventions aux associations 2018", PV_COLONNES)
    lus = extract_subventions_tableau(base)
    assert lus and all(qui == "epci" for _, _, _, _, qui in lus)


def test_lexercice_vote_prime_sur_la_date_de_seance(base, pose):
    """Un tableau adopté en décembre porte sur l'exercice qu'il nomme."""
    pose("deliberation_cc", SITE_EPCI, "2017-12-19",
         "Subventions aux associations", PV_COLONNES)
    assert {an for an, *_ in extract_subventions_tableau(base)} == {2018}


def test_une_demande_est_ecartee_sur_son_titre(base, pose):
    pose("deliberation_cc", SITE_EPCI, "2026-02-04",
         "Demande de subvention Fête de la Transhumance 2026", PV_PLAN_DE_FINANCEMENT)
    assert extract_subventions_tableau(base) == []


# ── Le mot qui distingue deux associations ───────────────────────────────────

@pytest.fixture
def resolveur(base, entite):
    entite("OFFICE DE TOURISME MONT AIGOUAL CAUSSES CEVENNES", "association")
    entite("ASSOCIATION AMITIE CEVENNES", "association")
    entite("VELO CLUB LASALLOIS", "association")
    return Resolver(base)


def test_un_mot_distinctif_absent_interdit_le_rapprochement(resolveur):
    """« OLYMPIQUE MONT AIGOUAL » couvrait deux de ses trois mots dans
    « OFFICE DE TOURISME MONT AIGOUAL CAUSSES CÉVENNES » : 920 € d'une
    association sportive étaient portés au compte de l'office de tourisme.
    Mieux vaut créer un doublon que d'attribuer son argent à une autre."""
    assert resolveur.resolve("OLYMPIQUE MONT AIGOUAL")[0] is None


def test_un_mot_de_structure_absent_ne_separe_pas(resolveur):
    """« club » nomme une forme de groupement, pas le groupement."""
    eid, nom = resolveur.resolve("Club Amitié Cévennes")
    assert nom == "ASSOCIATION AMITIE CEVENNES"


def test_une_orthographe_abimee_ne_separe_pas(resolveur):
    """Un procès-verbal océrisé écrit « Lasailois » pour « Lasallois »."""
    eid, nom = resolveur.resolve("Vélo Club Lasailois")
    assert nom == "VELO CLUB LASALLOIS"


def test_une_abreviation_reste_rapprochee(resolveur):
    """« Mt » est trop court pour porter une identité à lui seul."""
    eid, nom = resolveur.resolve("Office de Tourisme Mt Aigoual Causses Cévennes")
    assert nom == "OFFICE DE TOURISME MONT AIGOUAL CAUSSES CEVENNES"


# ── Ce que l'en-tête décide (15/09/2026) ─────────────────────────────────────

# La CC écrit « octroyer », et les élus qui se déportent ont leur propre ligne.
CC_OCTROYER = """Après délibération, le Conseil Communautaire décide pour l'exercice 2022 d'octroyer les
subventions suivantes :
MONTANT VOTE DU CONSEIL
ASSOCIATIONS
PROPOSE COMMUNAUTAIRE
AIGOUAL ORIENTATION 900,00 € A l'unanimité
25 voix pour, Christophe
BOISSON ne vote pas
3 500,00 €
EVEN 900,00 € A l'unanimité
FOYER DE SKI DE FOND 1 500,00 € A l'unanimité
"""

# L'annexe d'une commune : deux colonnes qui s'ADDITIONNENT, et un « année 2022 »
# cité avant le titre d'un tableau de 2023.
ANNEXE_DEUX_COLONNES = """Le bilan de l'année 2022 a été présenté en commission.
Tableau annexé à la délibération du Conseil Municipal.
SUBVENTIONS ALLOUÉES AUX ASSOCIATIONS 2023
Associations 2023 : subventions
Nom Fonctionnnement Evènementielle
Le Goût de L'ici et du La 500 €
Couleurs et Volumes 500 € 2 000 €
Si Saillans Sonne
2 800 €
Le Forum 1 800 € 0 €
Total 10 800 € 3 500 €
"""

# Trois colonnes dont une seule est la décision : accordé l'an passé | demandé | voté.
CC_TROIS_COLONNES = """Monsieur le Président met au vote les subventions ci-dessous :
MONTANT
MONTANT MONTANT
ASSOCIATIONS ACCORDE EN | DEMANDE VOTE VOTE
2023
ADYCT 1 692,00€ | 2 500,00 € 1 700,00 € | 1 2PStention
24 pour
Atelier Val-D'Aigoual 3 000,00 € 1 700,00 € | Unanimité
Fonderie d'art et d'ornement 1 160,00 € - €
La Truite Salamandre 282,00 € | - 255,00 € | Unanimité
Christophe BOISSON
Ski Club Mont Aigoual 2350,00€ | 3 500,00 € 2 125,00 € | sort de la salle
24 pour
UNIVERSITE SAUVAGE ET 1 abstention
POPULAIRE 2 500,00 € 1 275,00 € 24 pour
"""


def test_octroyer_ouvre_le_tableau():
    lus = lignes(CC_OCTROYER)
    assert lus["AIGOUAL ORIENTATION"] == 900 and lus["FOYER DE SKI DE FOND"] == 1500


def test_lelu_qui_ne_vote_pas_ne_recoit_pas_le_montant_suivant():
    """« BOISSON ne vote pas » puis « 3 500,00 € » : pris pour un nom en attente,
    l'élu devenait le bénéficiaire de 3 500 € d'argent public."""
    assert not any("BOISSON" in nom for nom in lignes(CC_OCTROYER))


def test_deux_colonnes_fonctionnement_et_evenement_sadditionnent():
    lus = lignes(ANNEXE_DEUX_COLONNES)
    assert lus["Couleurs et Volumes"] == 2500
    assert lus["Le Forum"] == 1800
    assert lus["Si Saillans Sonne"] == 2800


def test_seule_la_colonne_votee_compte():
    """Additionner, ce serait publier comme voté ce qui a été demandé."""
    lus = lignes(CC_TROIS_COLONNES)
    assert lus["ADYCT"] == 1700
    assert lus["Atelier Val-D'Aigoual"] == 1700
    assert lus["La Truite Salamandre"] == 255


def test_rien_de_vote_ne_devient_pas_le_montant_de_lan_passe():
    """« 1 160,00 € - € » : 1 160 € accordés en 2023, rien de voté en 2024."""
    assert "Fonderie d'art et d'ornement" not in lignes(CC_TROIS_COLONNES)


def test_sans_entete_qui_tranche_plusieurs_montants_ne_sont_pas_lus():
    texte = CC_TROIS_COLONNES.replace("ACCORDE EN | DEMANDE VOTE VOTE", "")
    assert "ADYCT" not in lignes(texte)


def test_lexercice_est_celui_du_titre_du_tableau(base, pose):
    """Tableau de 2023 rangé en 2022 à cause d'un « année 2022 » cité plus haut."""
    pose("deliberation", SITE_COMMUNE, "2023-04-06",
         "Subventions aux associations d'intérêt local", ANNEXE_DEUX_COLONNES)
    assert {an for an, *_ in extract_subventions_tableau(base)} == {2023}


def test_deux_copies_du_meme_vote_ne_comptent_quune_fois(base, pose):
    """Le PV et le registre portent le même tableau, coupé autrement, et l'OCR du
    registre en a perdu une ligne : 3 000 € étaient comptés deux fois, sous deux
    noms, parce que les deux copies n'avaient plus les mêmes montants — l'OCR du
    registre lit même 150 € pour 1 500 €."""
    tete = "Le Conseil Communautaire décide pour l'exercice 2022 d'octroyer les subventions suivantes :\n"
    pv = tete + ("EVEN 900,00 € A l'unanimité\nFOYER DE SKI DE FOND 1 500,00 € A l'unanimité\n"
                 "VELO CLUB LASALLOIS / MONTPELLIER\n3 000,00 € A l'unanimité\n"
                 "OLYMPIQUE MONT AIGOUAL 1 000,00 € A l'unanimité\n")
    registre = tete + ("FOYER DE SKI DE FOND 150,00 € A l'unanimité\n"
                       "VELO CLUB LASALLOIS / MONTPELLIER\nLANGUEDOC CYCLISME\n3 000,00 € A l'unanimité\n"
                       "OLYMPIQUE MONT AIGOUAL 1 000,00 € A l'unanimité\n")
    pose("deliberation_cc", SITE_EPCI, "2022-04-13", "Subventions aux associations", pv)
    pose("deliberation_cc", SITE_EPCI, "2022-04-13", "Subventions aux associations", registre)
    montants = [m for _, _, m, _, _ in extract_subventions_tableau(base)]
    assert sorted(montants) == [900, 1000, 1500, 3000]


def test_un_second_tableau_dans_le_meme_acte_est_lu(base, pose):
    """Le premier « décide d'accorder » d'un long registre n'est pas forcément
    celui des associations : ne lire que lui laissait le tableau de 2024 hors
    de toute collecte."""
    contenu = ("Décide d'accorder une subvention complémentaire à l'association X.\n"
               "Le conseil passe au point suivant.\nI. Voirie\nII. Budget\nIII. Eau\nIV. Déchets\n"
               "Subventions aux associations — Année 2024\n" + CC_TROIS_COLONNES)
    pose("deliberation_cc", SITE_EPCI, "2024-04-03", "Registre des délibérations", contenu)
    lus = {nom: m for an, nom, m, _, _ in extract_subventions_tableau(base) if an == 2024}
    assert lus.get("ADYCT") == 1700


def test_une_apostrophe_courbe_ne_fait_pas_un_second_beneficiaire(base, pose):
    tete = "SUBVENTIONS ALLOUÉES AUX ASSOCIATIONS 2022\n"
    pose("deliberation", SITE_COMMUNE, "2022-04-07", "Subventions",
         tete + "Au fil d'argent 500 €\nRaid VTT 2 000 €\nLe Forum 1 800 €\n")
    pose("deliberation", SITE_COMMUNE, "2022-04-07", "Subventions",
         tete + "Au fil d’argent 500 €\nRaid VTT 2 000 €\nTennis club 1 000 €\nLe Forum 1 800 €\n")
    assert [m for _, _, m, _, _ in extract_subventions_tableau(base)].count(500) == 1


def test_lelu_qui_sort_de_la_salle_nempeche_pas_de_lire_la_ligne():
    """« sort de la salle » est une issue de vote : sans elle, deux lignes du
    tableau 2024 manquaient, et le total lu ne rejoignait pas le TOTAL voté."""
    lus = lignes(CC_TROIS_COLONNES)
    assert lus["Ski Club Mont Aigoual"] == 2125
    assert not any("BOISSON" in nom for nom in lus)


def test_un_nom_coupe_par_un_mot_de_liaison_est_recolle():
    assert lignes(CC_TROIS_COLONNES)["UNIVERSITE SAUVAGE ET POPULAIRE"] == 1275
