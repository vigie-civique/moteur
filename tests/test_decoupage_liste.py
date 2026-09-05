"""Un en-tête n'autorise pas un découpage ; une numérotation le prouve.

Le régime `liste` a longtemps tenu son autorisation de la formule
« Délibérations : », au motif — écrit dans le module — que « c'est lui qui
l'autorise, pas la mise en page ». La mesure du 21/08/2026 sur 389 procès-verbaux
de Lasalle, de son intercommunalité, de Saillans et de Brassac a démenti la
prémisse : les 21 documents découpés par ce régime l'étaient TOUS à tort, et ils
fournissaient 4 337 des 5 529 actes du corpus de Lasalle — 78 %.

Deux causes, reproduites ici : « Délibération : » AU SINGULIER introduit le texte
d'UNE délibération dans un procès-verbal suivi, et la formule de clôture ne vient
jamais — les intercommunalités écrivent « La séance se termine à 12h50 ».

Les extraits sont raccourcis mais gardent la forme des documents d'origine.
"""
from __future__ import annotations

from collectors.pv_parsers import deliberations

# Séance du 02/10/2019 de la CC Causses Aigoual Cévennes : 57 521 caractères
# après l'en-tête, devenus 497 « délibérations » d'une ligne.
PV_SUIVI = """
Présents : Mesdames Laurette ANGELI, Marie DURAND et Monsieur Thomas VIDAL
Secrétaire de séance : Marie DURAND

Délibération :
Le Président de la Communauté de communes expose les dispositions de la loi
n° 99-586 du 12 juillet 1999 relative au renforcement et à la simplification de
la coopération intercommunale.
Vu la loi n° 99-586 du 12 juillet 1999
Considérant que la Communauté de Communes perçoit la Redevance d'Enlèvement
Risque de contentieux
Impayés à la charge de la collectivité
La séance se termine à 12h50
Thomas Vidal
"""

# Même intercommunalité, séance du 16/03/2022 : les délibérations y sont bien
# énumérées, en chiffres romains, et le corps de chacune suit son intitulé.
PV_NUMEROTE_ROMAIN = """
Présents : Mesdames Laurette ANGELI et Monsieur Thomas VIDAL
Secrétaire de séance : Marie DURAND

III. Approbations des Comptes de Gestion 2021
Après s'être fait présenter le budget primitif 2021 et les décisions
modificatives qui s'y rattachent, le conseil approuve.
1. Compte de Gestion 2021 « Budget Principal »
2. Compte de Gestion 2021 « Déchets »
IV. Approbations des Comptes Administratifs 2021
Le conseil, réuni sous la présidence de Madame ANGELI, approuve.
V. Débat d'orientation budgétaire
Le débat a lieu.
VI. Fonds de concours aux communes
Le conseil décide d'attribuer les fonds de concours.
La séance est levée à 12h30
"""


def test_un_en_tete_seul_ne_decoupe_plus():
    """« Délibération : » suivi de prose ne rend aucun acte, plutôt que 497."""
    actes = deliberations(PV_SUIVI)
    titres = [a["titre"] for a in actes]
    assert not [t for t in titres if t.startswith(("Vu la loi", "Considérant",
                                                   "Risque", "Impayés"))], titres
    assert "Thomas Vidal" not in titres, titres


def test_une_suite_d_ordinaux_decoupe():
    actes = deliberations(PV_NUMEROTE_ROMAIN)
    assert [a["regime"] for a in actes] == ["liste"] * len(actes)
    titres = [a["titre"] for a in actes]
    assert titres == ["Approbations des Comptes de Gestion 2021",
                      "Approbations des Comptes Administratifs 2021",
                      "Débat d'orientation budgétaire",
                      "Fonds de concours aux communes"], titres


def test_le_corps_de_la_deliberation_suit_son_intitule():
    """Le régime rendait une ligne par acte ; il rend maintenant son texte.

    Les sous-points d'une délibération — « 1. Compte de Gestion 2021 » sous
    « III. Approbations des Comptes de Gestion » — reviennent dans le corps de
    l'acte au lieu d'en former de nouveaux."""
    actes = deliberations(PV_NUMEROTE_ROMAIN)
    premier = actes[0]
    assert "budget primitif 2021" in premier["texte"]
    assert "Compte de Gestion 2021 « Déchets »" in premier["texte"]


def test_la_suite_s_arrete_a_la_levee_de_seance():
    actes = deliberations(PV_NUMEROTE_ROMAIN)
    assert "La séance est levée" not in actes[-1]["texte"], actes[-1]["texte"]


def test_un_ordinal_isole_ne_prouve_rien():
    """Une séance à une seule délibération n'est pas découpée par ce régime.

    Fabriquer un acte sur une ligne numérotée isolée reviendrait à faire
    confiance à un indice — le reproche adressé au régime précédent."""
    pv = """
Secrétaire de séance : Marie DURAND
1. Avis sur le projet de schéma de cohérence territoriale
Le conseil municipal donne un avis favorable.
"""
    assert [a for a in deliberations(pv) if a["regime"] == "liste"] == []


def test_un_tableau_du_conseil_n_est_pas_un_ordre_du_jour():
    """Les conseils d'installation numérotent leurs conseillers.

    Sur Brassac, une séance rendait dix-sept « actes » nommés d'après les élus.
    """
    pv = """
Secrétaire de séance : Marie DURAND
ORDRE DU JOUR
1. Jean-Marie FABRE
2. François BONO
3. Jean-Claude GUIRAUD
4. Brigitte PAILHE-FERNANDEZ
5. Christine CALVET
"""
    assert [a for a in deliberations(pv) if a["regime"] == "liste"] == []


# ── Un compte rendu HTML n'a pas de pages ────────────────────────────────────
#
# `_sans_entetes` retire les lignes qui reviennent quatre fois ou plus : c'est
# l'en-tête d'un PDF de vingt-quatre pages. Sur une page web, ce qui revient
# vingt fois, c'est la LIGNE DE COLONNES des tableaux. Le compte rendu du
# 27/04/2026 de Lasalle vote huit budgets ; « Chap / Art », « Intitulé » et
# « BP 2026 » y reviennent vingt fois chacun, et disparaissaient tous les trois.
# `budgets_votes` n'y trouvait plus une seule ancre.

CR_HTML = """
Secrétaire de séance : Marie DURAND

BUDGET PRINCIPAL
Chap / Art
Intitulé
BP 2026
011 Charges à caractère général 120 000,00
012 Charges de personnel 300 000,00
BUDGET CANTINE
Chap / Art
Intitulé
BP 2026
011 Charges à caractère général 162 724,13
012 Charges de personnel 40 000,00
BUDGET EAU
Chap / Art
Intitulé
BP 2026
011 Charges à caractère général 15 000,00
012 Charges de personnel 5 000,00
BUDGET ASSAINISSEMENT
Chap / Art
Intitulé
BP 2026
011 Charges à caractère général 9 000,00
"""


def test_la_ligne_de_colonnes_survit_a_un_compte_rendu_html():
    from collectors.budgets_votes import tableaux

    texte = "\n".join(a["titre"] + "\n" + a["texte"]
                      for a in deliberations(CR_HTML, pagine=False))
    assert "Chap / Art" in texte and "BP 2026" in texte, texte[:300]
    assert tableaux("", texte), "aucune ancre de budget voté dans les actes"
    assert "162 724,13" in texte


def test_un_pdf_pagine_perd_toujours_son_en_tete_repete():
    """La correction ne désarme pas le nettoyage là où il sert."""
    from collectors.pv_parsers import _sans_entetes

    pdf = "\n".join(["COMMUNE DE LASALLE — PROCES-VERBAL"] * 6 + ["DELIBERATION UNE"])
    assert "PROCES-VERBAL" not in _sans_entetes(pdf, pagine=True)
    assert "PROCES-VERBAL" in _sans_entetes(pdf, pagine=False)


# ── La classe « majuscules » n'en était pas une ──────────────────────────────
#
# `[A-ZÀ-Ÿ]` est un INTERVALLE de points de code, U+00C0→U+0178, qui traverse
# tout le bloc des minuscules accentuées. Deux dégâts : le motif reconnaissait
# « à » comme une majuscule, et surtout il recouvrait la classe des minuscules
# — d'où deux lectures possibles de chaque « -à », et un retour arrière
# exponentiel quand la ligne finit par ne pas correspondre. Signalé par CodeQL
# le 05/09/2026 ; mesuré à 0,7 s sur 67 caractères, ×2,6 toutes les deux
# répétitions de plus.

def test_les_classes_de_casse_ne_se_recouvrent_pas():
    """Le recouvrement était la cause ; c'est lui qu'on surveille."""
    import re

    from collectors.pv_parsers import _MAJUSCULES, _MINUSCULES

    lettres = [chr(i) for i in range(0x20, 0x250)]
    hautes = {c for c in lettres if re.match(f"[{_MAJUSCULES}]", c)}
    basses = {c for c in lettres if re.match(f"[{_MINUSCULES}]", c)}

    assert not (hautes & basses), \
        f"les deux classes se recouvrent sur {''.join(sorted(hautes & basses))!r}"
    assert all(c.isupper() for c in hautes), \
        f"« majuscules » accepte {''.join(c for c in sorted(hautes) if not c.isupper())!r}"
    assert all(c.islower() for c in basses), \
        f"« minuscules » accepte {''.join(c for c in sorted(basses) if not c.islower())!r}"


def test_une_ligne_de_charabia_ne_fige_pas_le_decoupage():
    """Le texte vient de PDF océrisés : le charabia est un cas NORMAL.

    Avec l'ancien motif, cette ligne de 2 003 caractères ne rendait pas la main
    avant des heures — sans rien planter, donc sans rien dire.
    """
    import time

    from collectors.pv_parsers import _ITEM_PERSONNE

    charabia = "A'" + "-à" * 1000 + "!"
    depart = time.perf_counter()
    assert not _ITEM_PERSONNE.match(charabia)
    assert time.perf_counter() - depart < 1.0, "retour arrière exponentiel"


def test_les_noms_restent_reconnus():
    """La correction resserre la classe : elle ne doit rien perdre en route.

    Les accents, les apostrophes, les prénoms composés et les ligatures passent
    dans les deux sens — c'est ce qui distingue un resserrement d'une casse.
    """
    from collectors.pv_parsers import _ITEM_PERSONNE

    for nom in ["Jean-Claude GUIRAUD", "BOUSQUET Christiane", "Élodie MARTIN",
                "Jean-François D'ARGENSON", "François ŒUVRARD",
                "O'CONNOR Patrick", "Brigitte PAILHE-FERNANDEZ",
                "DUPONT Jean 12,50 €"]:
        assert _ITEM_PERSONNE.match(nom), nom
    for intitule in ["Approbation du compte administratif",
                     "Convention avec le SIAEP",
                     "Vote du taux des taxes locales"]:
        assert not _ITEM_PERSONNE.match(intitule), intitule


def test_un_nom_de_famille_en_deux_mots_echappe_encore():
    """Une limite ANCIENNE, que la correction ne touche pas — elle est notée ici
    pour qu'on ne la découvre pas deux fois.

    Le patronyme est un seul jeton : « LE GALL » et « DE LA TOUR » n'entrent
    dans aucune des deux branches. Un tableau du conseil rempli de ces noms-là
    serait donc pris pour un ordre du jour. Les corriger demande d'autoriser
    plusieurs jetons majuscules d'affilée, ce qui rapproche dangereusement le
    motif d'un intitulé en capitales (« DELIBERATION N° 2024-045 ») : ça se
    tranche sur un corpus, pas sur une intuition.
    """
    from collectors.pv_parsers import _ITEM_PERSONNE

    assert not _ITEM_PERSONNE.match("Anne-Marie LE GALL")
    assert not _ITEM_PERSONNE.match("Noëlle DE LA TOUR")
