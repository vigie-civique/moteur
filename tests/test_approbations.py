"""Les plans de financement votés : de l'argent engagé qui n'est pas un marché.

« Le Conseil APPROUVE le projet dont le montant s'élève à 16 130,10 € HT soit
19 356,12 € TTC et demande son inscription au programme. » Aucune entreprise
n'est retenue : la commune vote sa participation à une opération portée par un
syndicat. Le publier comme un marché fausserait le décompte des attributaires ;
ne pas le publier du tout laisse de l'argent public hors du site.

Ce collecteur remplace un script de la première commune qui post-traitait un
rapport d'extraction par modèle de langage. La détection y était déjà faite par
expressions régulières : la version portée s'en tient donc au déterministe, sans
dépendre d'un fournisseur d'IA — cf. le principe de liberté du repreneur.

Les tournures ci-dessous sont relevées dans des procès-verbaux réels.
"""
from __future__ import annotations

import pytest

from collectors.approbations import (MONTANT_MIN, _nombre, dedoublonner,
                                     _explicite, _phrases, APPROBATION)

VOTES = [
    "Le Conseil Municipal APPROUVE le projet dont le montant s'élève à "
    "16 130,10 € HT soit 19 356,12 € TTC et demande son inscription au programme.",
    "Ce projet s'élève à 87 799,37 € HT soit 105 359,24 € TTC.",
    "Vu l'état financier estimatif de 2 088,76 € HT, le conseil approuve.",
    "Le plan de financement s'établit à 45 000,00 € HT soit 54 000,00 € TTC.",
]

PAS_DES_VOTES = [
    "Le marché est attribué à la SARL DU PONT pour 12 000,00 € HT.",
    "Le conseil prend acte du compte rendu de la séance précédente.",
    "Achat de fournitures de bureau pour 250,00 € TTC.",
]


@pytest.mark.parametrize("phrase", VOTES)
def test_une_participation_votee_est_reconnue(phrase):
    assert APPROBATION.search(phrase), f"tournure manquée : {phrase[:50]}"


@pytest.mark.parametrize("phrase", PAS_DES_VOTES)
def test_un_marche_attribue_n_est_pas_une_approbation(phrase):
    assert not APPROBATION.search(phrase), f"pris à tort : {phrase[:50]}"


@pytest.mark.parametrize("brut,attendu", [
    ("16 130,10", 16130.10),
    ("87 799.37", 87799.37),
    ("2 088,76", 2088.76),
    ("45 000", 45000.0),
])
def test_les_montants_se_lisent_avec_virgule_comme_avec_point(brut, attendu):
    """Les procès-verbaux mélangent les deux notations dans un même document."""
    assert _nombre(brut) == pytest.approx(attendu)


@pytest.mark.parametrize("brut", ["12,00", "250,00", "3"])
def test_une_broutille_n_est_pas_un_plan_de_financement(brut):
    """Sous le seuil, c'est une ligne de facture mal découpée, pas une opération."""
    assert _nombre(brut) is None or _nombre(brut) >= MONTANT_MIN


def test_un_montant_delirant_est_refuse():
    assert _nombre("99 999 999 999,00") is None


def test_les_phrases_se_coupent_aussi_sur_les_retours_a_la_ligne():
    """Les PV ponctuent mal : sans coupure sur les sauts de ligne, une « phrase »
    ramasse les montants de l'opération suivante."""
    texte = "Approuve le projet à 1 000,00 € HT\nAutre opération : 2 000,00 € HT"
    assert len(_phrases(texte)) == 2


def test_la_meme_operation_votee_deux_fois_ne_compte_qu_une_fois():
    """Une approbation figure dans le PV de séance ET dans la délibération
    dédiée. Le montant HT au centime près est la signature."""
    base = {"montant_ht": 16130.10, "montant_ttc": None, "maitre_ouvrage": None,
            "citation": "", "source": "", "source_url": None, "event_id": 1}
    a = {**base, "date": "2026-03-10", "objet": "travaux"}
    b = {**base, "date": "2026-05-12", "objet": "Poste Calviac — renforcement",
         "event_id": 2}
    retenus, ecartes = dedoublonner([a, b])
    assert len(retenus) == 1 and len(ecartes) == 1
    assert retenus[0]["objet"].startswith("Poste Calviac"), \
        "l'objet qui NOMME l'opération doit l'emporter sur le générique"


def test_deux_operations_de_meme_montant_a_deux_ans_restent_distinctes():
    base = {"montant_ht": 5000.0, "montant_ttc": None, "maitre_ouvrage": None,
            "citation": "", "source": "", "source_url": None, "objet": "travaux"}
    retenus, _ = dedoublonner([{**base, "date": "2020-01-10", "event_id": 1},
                               {**base, "date": "2024-01-10", "event_id": 2}])
    assert len(retenus) == 2


def test_un_objet_nommant_l_operation_vaut_mieux_qu_un_objet_long():
    assert _explicite("Poste Calviac") > _explicite(
        "travaux d'electricite ou travaux d'investissement sur le reseau")


@pytest.mark.parametrize("texte,attendu", [
    ("Le SMEG propose l'extension du réseau.", "SMEG"),
    # Le cas qui a produit le défaut : un patronyme en capitales a la même forme
    # qu'un sigle, et il partait dans un champ publié.
    ("M. SERRE : Le SMEG propose l'extension.", "SMEG"),
    ("Mme SERRE indique que les travaux sont votés.", None),
    ("Le syndicat mixte porte l'opération.", "syndicat mixte"),
    ("Le syndicat d'électrification du Gard finance.", "syndicat d'électrification du Gard"),
    ("Le conseil approuve les travaux de voirie.", None),
])
def test_un_patronyme_en_capitales_n_est_pas_un_syndicat(texte, attendu):
    from collectors.approbations import _maitre_ouvrage
    assert _maitre_ouvrage(texte) == attendu


@pytest.mark.parametrize("titre", [
    "M. SERRE : Le SMEG",
    "Mme MARTIN : je m'abstiens",
    "Monsieur DUPONT : avis favorable",
])
def test_une_prise_de_parole_n_est_pas_un_intitule(titre):
    """Elle nomme une personne, et ne dit rien de l'opération."""
    from collectors.approbations import PRISE_DE_PAROLE
    assert PRISE_DE_PAROLE.match(titre)


@pytest.mark.parametrize("titre", [
    "EXTENSION DU RESEAU D’ECLAIRAGE PUBLIC",
    "TRAVAUX RUES BASSE ET PONT VIEUX",
])
def test_un_vrai_intitule_n_est_pas_pris_pour_une_prise_de_parole(titre):
    from collectors.approbations import PRISE_DE_PAROLE
    assert not PRISE_DE_PAROLE.match(titre)
