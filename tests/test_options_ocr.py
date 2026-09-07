"""Les options d'océrisation sont déclarées une fois, et personne ne les refait.

Elles étaient recopiées dans `cm_ocr.ocr_if_needed` et dans `conseils.ocr` —
deux listes identiques, dans deux modules, pour le même outil. Une option
ajoutée d'un côté seulement produit alors deux qualités d'océrisation selon le
chemin d'appel, et rien ne le dit : les deux collecteurs écrivent le même
`.ocr.pdf` à côté du même original. C'est le défaut d'`attribution_acheteur`,
qui vivait en trois exemplaires dont un dans son propre essai.

Ces essais ne recopient pas la liste — un contrôle qui compare une valeur à sa
propre copie est vert par construction et ne protège rien. Ils vérifient deux
propriétés indépendantes : que les deux appels passent par la même déclaration,
et que la rastérisation atteint au moins la résolution du calque de texte des
documents scannés.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

RACINE = pathlib.Path(__file__).resolve().parent.parent
MODULES = ("collectors/cm_ocr.py", "collectors/conseils.py")


def _appels_ocrmypdf(chemin: pathlib.Path) -> list[ast.List]:
    """Les listes d'arguments passées à un `subprocess.run` qui lance ocrmypdf."""
    arbre = ast.parse(chemin.read_text())
    trouves = []
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.Call) or not noeud.args:
            continue
        premier = noeud.args[0]
        if not isinstance(premier, ast.List) or not premier.elts:
            continue
        tete = premier.elts[0]
        if isinstance(tete, ast.Constant) and tete.value == "ocrmypdf":
            trouves.append(premier)
    return trouves


def test_aucun_appel_ne_reconstruit_ses_propres_options():
    """Un appel à ocrmypdf déplie la déclaration commune, il ne la réécrit pas."""
    for module in MODULES:
        appels = _appels_ocrmypdf(RACINE / module)
        assert appels, f"{module} : aucun appel à ocrmypdf trouvé — essai périmé"
        for appel in appels:
            deplie = [e for e in appel.elts if isinstance(e, ast.Starred)]
            assert deplie, (
                f"{module} : un appel à ocrmypdf n'utilise aucune déclaration "
                f"commune. Les options y sont écrites à la main, elles vont "
                f"diverger de l'autre module.")
            options = [e.value for e in appel.elts
                       if isinstance(e, ast.Constant) and isinstance(e.value, str)
                       and e.value.startswith("--")]
            assert not options, (
                f"{module} : options écrites en clair dans l'appel : {options}. "
                f"Elles appartiennent à la déclaration commune.")


def test_les_deux_modules_partagent_la_meme_declaration():
    """`conseils` reprend celle de `cm_ocr`, il n'en tient pas une seconde.

    Importer les deux modules exige `pdfplumber`, que le job « tests » n'installe
    pas — il ne veut dépendre ni des collecteurs ni de l'API. Sauté ici, joué par
    « tests-deps », qui refuse le moindre test sauté. Même convention que
    `tests/test_dematdoc.py`.
    """
    pytest.importorskip("pdfplumber",
                        reason="job « tests-deps » : pip install -r requirements.txt")
    from collectors import cm_ocr, conseils
    assert conseils.OPTIONS_OCRMYPDF is cm_ocr.OPTIONS_OCRMYPDF, (
        "les deux modules tiennent deux objets distincts : la déclaration a été "
        "dupliquée au lieu d'être importée")


def test_la_rasterisation_atteint_la_resolution_du_calque_de_texte():
    """Au moins 300 points par pouce, parce que c'est ce que portent les scans.

    Les pages scannées superposent un fond en couleur à 150 ou 200 ppi et un
    calque de texte bitonal à 300 ppi. Rastériser en dessous de 300 jette la
    finesse du calque, celle qui porte les lettres. Mesuré sur 80 pages : les
    formes abîmées distinctes passent de 1 046 à 931 quand la rastérisation
    monte, et le gain ne se produit QUE sur les documents qui portent le calque
    à 300 — les documents à 200 ppi n'y gagnent rien.

    La borne est le mécanisme, pas la valeur retenue : monter plus haut reste
    permis, descendre sous 300 fait perdre ce qui a été mesuré.
    """
    pytest.importorskip("pdfplumber",
                        reason="job « tests-deps » : pip install -r requirements.txt")
    from collectors.cm_ocr import OPTIONS_OCRMYPDF
    assert "--oversample" in OPTIONS_OCRMYPDF, (
        "aucun sur-échantillonnage : la rastérisation retombe sous la "
        "résolution du calque de texte des documents scannés")
    valeur = OPTIONS_OCRMYPDF[OPTIONS_OCRMYPDF.index("--oversample") + 1]
    assert int(valeur) >= 300, (
        f"rastérisation à {valeur} ppi, sous les 300 ppi du calque de texte")
