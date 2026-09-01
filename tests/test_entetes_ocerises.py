"""Un en-tête que l'océrisation n'écrit jamais deux fois pareil est un en-tête.

`_sans_entetes` comptait des lignes IDENTIQUES. Sur un document textuel, une
page répète son en-tête au caractère près et le comptage le voit. Sur un
document SCANNÉ, jamais : le procès-verbal du 30/06/2026 de Lasalle répète le
sien sur ses 47 pages, en 47 graphies différentes. Aucune n'atteignait le seuil
de quatre, aucune n'était retirée, et `_capitales` prenait chacune pour le titre
d'une délibération — 37 actes produits pour 5 réels, tous « plausibles » au sens
de `_titre_plausible`, qui a été écrit contre un autre défaut et ne voit pas
celui-ci.

Relevé sur les 58 procès-verbaux scannés de Lasalle : 1 241 actes produits avant
le comptage par forme normalisée, 862 après ; 18 documents s'améliorent, aucun
ne se dégrade. Sur les 134 procès-verbaux TEXTUELS de la même instance, quatre
actes disparaissent, et les quatre sont du mobilier.

Les extraits gardent la forme et les défauts des documents d'origine.

⚠️ Ce que ces essais NE couvrent PAS, et qui reste ouvert : les familles d'en-tête
que l'océrisation abîme DIFFÉREMMENT à chaque page, jusque dans leurs mots —
« REPUBLIQUE FRANÇAISE EXTRAIT DU REG: 6266 7 … », « … EXTRAIT DU RE LE GRADE 7
… », ou la ligne de colonnes d'un tableau d'effectifs rendue six fois en six
orthographes. Leurs formes normalisées sont toutes distinctes : aucune règle de
COMPTAGE, si tolérante soit-elle, ne peut les rapprocher. Sur le document
vérifié à la main, ce sont les 17 actes faux qui subsistent sur 22. Les séparer
d'un vrai titre demande une preuve interne au document — le cachet du contrôle
de légalité porte un numéro qui change d'un acte au suivant — et non un indice
de mise en page. C'est le chantier suivant, pas celui-ci.

Un essai de bout en bout a été écrit puis RETIRÉ : il passait avec l'ancien
découpage comme avec le nouveau. Un contrôle vert des deux côtés ne protège
rien et se fait passer pour une garde.
"""
from __future__ import annotations

from collectors.pv_parsers import _sans_entetes, deliberations

# Le cachet du contrôle de légalité, tel que l'océrisation l'a rendu page après
# page sur un même document : « 030 » devient « 690 », « 20260630 » devient
# « 20260680 », le tiret bas devient une espace ou un point.
CACHETS = [
    "ID : 030-213001407-20260630-DEL2606_02-DE",
    "ID :690-218001407-20260680-DEL2606 19-DE",
    "ID :030-213001407-20260680-DEL2608. 14-DE",
    "ID: 030-213001407:20260630-DEL2606_13-DE",
    "iD :030-213001407-20260680-DEL2606 011-DE",
]


def _document(lignes: list[str]) -> str:
    return "\n".join(lignes)


# Un corps de séance, une ligne par délibération : elles DIFFÈRENT, comme dans un
# vrai document. Les répéter à l'identique les ferait retirer elles aussi — le
# retrait des lignes répétées ne distingue pas le mobilier du corps, il ne
# connaît que la répétition, et c'est vrai depuis toujours.
CORPS = [
    "Le maire propose la création d'un emploi permanent d'adjoint.",
    "Le maire propose de solliciter le département au titre du CD30.",
    "Le maire expose l'état du mur de soutènement de la filature.",
    "Le comptable public a transmis le compte de gestion de l'exercice.",
    "Le maire rend compte des décisions prises par délégation.",
]


def test_un_entete_ocerise_est_retire_malgre_ses_graphies():
    """Cinq graphies d'un même cachet : aucune n'est vue quatre fois."""
    texte = _document(
        [ligne for cachet, corps in zip(CACHETS, CORPS)
         for ligne in (cachet, corps)])
    propre = _sans_entetes(texte)
    assert not any(c in propre for c in CACHETS), (
        "le cachet du contrôle de légalité survit au retrait des en-têtes")
    for corps in CORPS:
        assert corps in propre, f"le corps de la séance a été emporté : {corps}"



def test_une_ligne_qui_porte_un_montant_n_est_jamais_du_mobilier():
    """La garde de la Cantine, à l'épreuve de la marque des nombres.

    Marquer les nombres pour rapprocher deux graphies d'un même cachet rapproche
    AUSSI deux lignes de budget qui ne diffèrent que par leurs sommes. Or le
    texte que rend `_sans_entetes` ne sert pas qu'à trouver les titres : il
    devient le CORPS de l'acte, et `extract_amounts` y puise. Sans cette garde,
    240 600 € du Fonds Vert, 401 000 € HT d'une opération et 2 200 € de
    subvention disparaissaient du corps des actes de Lasalle.
    """
    budgets = [
        "Section de fonctionnement : Dépenses 590,00 € Recettes 2 904,08 €",
        "Section de fonctionnement : Dépenses 36 713,00 € Recettes 48 109,56 €",
        "Section de fonctionnement : Dépenses 101 194,00 € Recettes 108 528,42 €",
        "Section de fonctionnement : Dépenses 322 254,77 € Recettes 278 166,86 €",
        "Section de fonctionnement : Dépenses 127 130,18 € Recettes 162 468,42 €",
    ]
    propre = _sans_entetes(_document(budgets))
    for ligne in budgets:
        assert ligne in propre, f"une ligne de budget a été prise pour un en-tête : {ligne}"


def test_une_page_web_n_est_toujours_pas_traitee_comme_un_pdf():
    """`pagine=False` reste intact : une page web n'a pas d'en-tête de page."""
    texte = _document(CACHETS)
    assert _sans_entetes(texte, pagine=False) == texte
