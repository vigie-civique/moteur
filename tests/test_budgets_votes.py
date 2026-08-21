"""Budget voté ou compte financier : la seule chose que ce collecteur doit tenir.

Les deux tableaux ont la même forme, les mêmes intitulés, et se suivent souvent
dans le même procès-verbal. Ce qui les sépare tient à une colonne : le budget
primitif annonce un montant, le compte financier en aligne deux — prévu, puis
réalisé. Les confondre publierait du prévisionnel comme du constaté sans qu'aucun
chiffre soit faux, donc sans que rien ne le signale.

Les extraits ci-dessous sont recopiés de procès-verbaux réels, à la ponctuation
près, y compris leurs défauts : espaces insécables, virgule et point mêlés,
séance entière tassée dans un seul acte parce que le découpage a échoué.
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def bv():
    # `collectors.db` lit la configuration d'instance au chargement : c'est
    # `conftest.py` qui pose l'instance factice, avant tout import.
    from collectors import budgets_votes
    return budgets_votes


BP_FONCTIONNEMENT = (
    "Chap/art Intitulé BP 2026 "
    ".011 Charges à caractère général 430 563.32 "
    ".012 Charges de personnel, frais assimilés 1 035 000.00 "
    "65 Autres charges de gestion courante 475 667.07 "
    "TOTAL DES DEPENSES FONCT. EXERCICE 2 270 783.59"
)

COMPTE_FINANCIER = (
    ".011 Charges à caractère général 75 750.00 73 321.21 "
    ".012 Charges de personnel, frais assimilés 71 700.00 71 561.80 "
    "TOTAL DES DEPENSES FONCT. EXERCICE 177 717.01 175 149.78"
)


# ── La colonne unique fait le budget voté ────────────────────────────────────

def test_budget_primitif_lu(bv):
    tables = bv.tableaux("M57 SECTION DE FONCTIONNEMENT - DEPENSES", BP_FONCTIONNEMENT)
    assert len(tables) == 1
    assert tables[0]["annee"] == 2026
    assert tables[0]["scope"] == "principal"
    agregats = bv.agregats_du_tableau(tables[0]["corps"], tables[0]["section"])
    valeurs = {a["agregat"]: a["value"] for a in agregats}
    assert valeurs["Dépenses de fonctionnement"] == 2270783.59
    assert valeurs["Charges de personnel"] == 1035000.00


def test_compte_financier_ignore(bv):
    """Prévu puis réalisé, sans ligne de colonnes « BP <année> » : ce n'est pas
    un budget voté, et rien ne doit en sortir. L'OFGL publie le réalisé, et
    mieux que nous ne saurions le lire."""
    assert bv.tableaux("CANTINE SECTION DE FONCTIONNEMENT", COMPTE_FINANCIER) == []


# ── La colonne du budget voté est la dernière ────────────────────────────────

RESTES_ET_BP = (
    "DEPENSES D'INVESTISSEMENT Chap / Art Intitulé Restes à réaliser BP 2026 "
    "204 Subvention d'équipement 57 330,40 68 968,27 "
    "TOTAL DES DEPENSES D'INVEST 57 330,40 320 283,30"
)

CA_ET_BP = (
    "DEPENSES DE FONCTIONNEMENT Chap / Art Intitulé CA 2025 BP 2026 "
    ".012 Charges de personnel, frais assimilés 1 002 118,36 1 035 000,00 "
    "TOTAL DES DEPENSES FONCT. 1 818 567,68 2 270 783,59"
)


@pytest.mark.parametrize("texte, agregat, attendu", [
    (RESTES_ET_BP, "Dépenses d'investissement", 320283.30),
    (CA_ET_BP, "Dépenses de fonctionnement", 2270783.59),
    (CA_ET_BP, "Charges de personnel", 1035000.00),
])
def test_les_colonnes_qui_precedent_sont_ecartees(bv, texte, agregat, attendu):
    """« Restes à réaliser » et le compte administratif de l'exercice écoulé
    partagent la ligne avec le budget voté. Renoncer au tableau entier, comme le
    faisait la première version, perdait toute la séance d'avril."""
    table = bv.tableaux("", texte)[0]
    valeurs = {a["agregat"]: a["value"]
               for a in bv.agregats_du_tableau(table["corps"], table["section"])}
    assert valeurs[agregat] == attendu


def test_une_colonne_apres_le_bp_fait_renoncer(bv):
    """Si le budget voté n'est plus la dernière colonne, plus rien ne dit lequel
    des montants d'une ligne est le sien. On ne devine pas : on compte."""
    table = bv.tableaux("", "DEPENSES Chap / Art Intitulé BP 2026 Réalisé "
                            "TOTAL DES DEPENSES FONCT. 2 270 783,59 1 818 567,68")[0]
    assert table["colonne_sure"] is False


def test_les_cellules_sur_leurs_propres_lignes(bv):
    """Une page HTML met chaque cellule sur sa ligne ; un PDF de tableur les
    aligne. Le tableau est le même, et doit se lire pareil."""
    html = ("DEPENSES D'INVESTISSEMENT\nChap / Art\nIntitulé\nRestes à réaliser\n"
            "BP 2026\nTOTAL DES DEPENSES D'INVEST\n57 330,40\n320 283,30\n")
    table = bv.tableaux("", html)[0]
    valeurs = {a["agregat"]: a["value"]
               for a in bv.agregats_du_tableau(table["corps"], table["section"])}
    assert valeurs["Dépenses d'investissement"] == 320283.30


def test_sans_entete_bp_aucun_tableau(bv):
    """Un tableau sans « BP <année> » n'est pas daté : le dater au jugé
    donnerait un budget voté attribué au mauvais exercice."""
    assert bv.tableaux("CANTINE SECTION DE FONCTIONNEMENT", COMPTE_FINANCIER) == []


# ── Une séance mal découpée porte plusieurs budgets ──────────────────────────

SEANCE_ENTIERE = (
    "APPROBATION DES BUDGETS 2025 Monsieur le Maire laisse la parole à l'adjoint "
    "aux finances. Le budget de la cantine, qui s'établit ainsi : "
    "CANTINE SECTION DE FONCTIONNEMENT DEPENSES Chap/art Intitulé BP 2025 "
    ".011 Charges à caractère général 65 750,00 "
    "TOTAL DES DEPENSES FONCT. EXERCICE 169 207,01 SOLDE D'EXECUTION 0,00 "
    "Détail par chapitre : PRINCIPAL SECTION DE FONCTIONNEMENT M57 DEPENSES "
    "Chap/art Intitulé BP 2025 "
    ".011 Charges à caractère général 410 275,00 "
    "TOTAL DES DEPENSES FONCT. EXERCICE 2 097 563,60 SOLDE D'EXECUTION 201 218,80"
)


def test_une_seance_mal_decoupee_rend_chaque_budget_au_sien(bv):
    """Le défaut est réel : une séance budgétaire entière tient dans un acte
    intitulé au hasard de la page où le découpage s'est arrêté. Se fier au titre
    attribuerait au budget communal les chiffres d'une régie."""
    tables = bv.tableaux("Coût à la charge du propriétaire de la parcelle AC 511",
                         SEANCE_ENTIERE)
    assert [t["scope"] for t in tables] == ["cantine", "principal"]
    assert {t["annee"] for t in tables} == {2025}

    cantine = bv.agregats_du_tableau(tables[0]["corps"], tables[0]["section"])
    principal = bv.agregats_du_tableau(tables[1]["corps"], tables[1]["section"])
    assert {a["agregat"]: a["value"] for a in cantine}["Dépenses de fonctionnement"] == 169207.01
    assert {a["agregat"]: a["value"] for a in principal}["Dépenses de fonctionnement"] == 2097563.60
    # Le total de la cantine ne doit pas déborder sur le tableau suivant.
    assert {a["agregat"]: a["value"] for a in cantine}["Charges à caractère général"] == 65750.00


def test_le_solde_prend_le_nom_de_sa_section(bv):
    """« SOLDE D'EXECUTION » ne dit pas de quelle section il est. Deux tableaux
    de la même séance écriraient sinon deux valeurs sous la même clé."""
    corps = bv._norm("TOTAL DES RECETTES D'INVEST EXERCICE 320 283.30 "
                     "SOLDE D'EXECUTION 11 287.40")
    noms = {a["agregat"] for a in bv.agregats_du_tableau(corps, "investissement")}
    assert "Solde d'exécution d'investissement" in noms
    assert "Excédent net de fonctionnement" not in noms


# ── Le nom du budget se lit à rebours, et peut ne pas se lire ────────────────

@pytest.mark.parametrize("avant, attendu", [
    ("m57", "principal"),
    ("principal", "principal"),
    ("qui s'établit ainsi : parc locatif", "parc locatif"),
    ("le budget 2025 de la cantine, qui s'établit ainsi : cantine", "cantine"),
    ("11 pv 2025-04-10 chaufferie bois", "chaufferie bois"),
    ("", None),
])
def test_nom_de_budget(bv, avant, attendu):
    assert bv.nom_de_budget(bv._norm(avant)) == attendu


# ── Les montants : ce qui suit une étiquette, et rien d'autre ────────────────

def test_un_mot_arrete_la_lecture_des_montants(bv):
    """Sans cette borne, le total d'un tableau avalerait le premier chiffre du
    suivant, et un budget voté passerait pour un compte financier."""
    corps = bv._norm("TOTAL DES RECETTES FONCT. EXERCICE 2 459 773.03 "
                     "SOLDE D'EXECUTION 188 989.44")
    valeurs = {a["agregat"]: a["value"] for a in bv.agregats_du_tableau(corps, "fonctionnement")}
    assert valeurs["Recettes de fonctionnement"] == 2459773.03
    assert valeurs["Excédent net de fonctionnement"] == 188989.44
