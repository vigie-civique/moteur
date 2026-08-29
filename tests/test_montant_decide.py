"""Le montant d'une délibération est celui qu'elle DÉCIDE.

Cas relevé le 29/08/2026 sur le conseil municipal du 28/05/2026 : un acte
intitulé « LE NEZ AU VENT » affichait **2 200 €**. Le texte disait, pour deux
associations à la suite :

    Le Nez au Vent          — demandé   540 € ; attribué  100 €
    Les Nocturnes de Lasalle — demandé 2 200 € ; attribué  500 €

2 200 € était donc le montant DEMANDÉ par l'AUTRE association. Le montant
publié était le plus élevé du texte, sans égard à ce qu'il représentait.
"""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _charger(nom):
    # Le script n'est pas un module importable : on le charge par son chemin,
    # comme le fait tests/test_perimetre.py.
    spec = importlib.util.spec_from_file_location(nom, ROOT / "scripts" / f"{nom}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


montant_de_la_decision = _charger("build_public_snapshot").montant_de_la_decision

ACTE_28_05_2026 = [
    {"value": 540.0, "context": "M. SCHWEDA : Montant demandé : 540 € ; Montant attribué : 100 €"},
    {"value": 100.0, "context": "M. SCHWEDA : Montant demandé : 540 € ; Montant attribué : 100 € Le Conseil"},
    {"value": 100.0, "context": "− DECIDE d'attribuer à l'association Le Nez au Vent une subvention "
                                "de 100 €, LES NOCTURNES"},
    {"value": 2200.0, "context": "LES NOCTURNES DE LASALLE (Anciennement Mandragora) M. SCHWEDA : "
                                 "Montant demandé : 2 200 € ; Montant attribué : 500 €"},
    {"value": 500.0, "context": "Mandragora) M. SCHWEDA : Montant demandé : 2 200 € ; "
                                "Montant attribué : 500 € Le Conseil"},
    {"value": 500.0, "context": "− DECIDE d'attribuer à l'association Les Nocturnes de Lasalle "
                                "une subvention de 500 €,"},
]


@pytest.mark.parametrize("titre,attendu", [
    ("LE NEZ AU VENT", 100.0),
    ("LES NOCTURNES DE LASALLE", 500.0),
])
def test_le_titre_designe_la_subvention_de_l_acte(titre, attendu):
    """Un bloc porte plusieurs subventions : le titre dit de laquelle il s'agit."""
    principal, _ = montant_de_la_decision(ACTE_28_05_2026, titre)
    assert principal == attendu


def test_un_montant_demande_ne_devient_pas_le_montant_de_l_acte():
    principal, _ = montant_de_la_decision([
        {"value": 9000.0, "context": "montant demandé : 9 000 €"},
        {"value": 1200.0, "context": "travaux de voirie 1 200 €"}])
    assert principal == 1200.0


def test_l_accorde_l_emporte_sur_le_sollicite():
    principal, _ = montant_de_la_decision([
        {"value": 5000.0, "context": "sollicite une subvention de 5 000 €"},
        {"value": 1500.0, "context": "DECIDE d'attribuer 1 500 €"}])
    assert principal == 1500.0


def test_sans_qualificatif_le_comportement_ne_change_pas():
    """Faute d'indice, on retombe sur le plus élevé : ne pas régresser."""
    principal, _ = montant_de_la_decision([
        {"value": 800.0, "context": "coût des travaux 800 €"},
        {"value": 250.0, "context": "et 250 €"}])
    assert principal == 800.0


def test_les_valeurs_aberrantes_restent_ecartees():
    """L'OCR lit des concaténations de chiffres comme des euros."""
    principal, tous = montant_de_la_decision([
        {"value": 213087450.0, "context": "budget 213 087 450 €"},
        {"value": 900.0, "context": "subvention de 900 €"}])
    assert principal == 900.0
    assert 213087450.0 not in tous


def test_aucun_montant_lisible():
    assert montant_de_la_decision([]) == (None, [])


# ── L'extraction elle-même : un montant doit être ISOLÉ ──────────────────────

@pytest.mark.parametrize("texte,attendus", [
    # « CD30 » est le conseil départemental du Gard, pas le début du montant.
    ("Etudes préalables 50 420,00 € CD30 145 834,00 € pour le solde",
     [50420.0, 145834.0]),
    # Un millésime de programme européen collé au montant.
    ("FEDER 2021-2027 458 784,55 € versés", [458784.55]),
    # Une date collée au montant.
    ("facture 25/5/2023 14 275.20€ et 8 634€", [14275.20, 8634.0]),
    # Les formes normales ne bougent pas.
    ("une subvention de 1 500 € et 250,50 €", [1500.0, 250.5]),
    ("TOTAL HT 1 809 652,75 €", [1809652.75]),
    # Un montant SIGNÉ reste entier : le tiret n'est pas un collage.
    ("une baisse de -36 706,26 € par rapport à 2015 (78 005,30 €)",
     [36706.26, 78005.30]),
])
def test_un_montant_ne_recolle_pas_ce_qui_le_precede(texte, attendus):
    """Une commune de 1 200 habitants publiait des lignes à 30 M€.

    Le motif acceptait « un chiffre puis n'importe quelle suite de chiffres et
    d'espaces » : tout nombre collé à gauche du montant en faisait partie.
    """
    from collectors.cm_parser import extract_amounts
    assert [round(m["value"], 2) for m in extract_amounts(texte)] == attendus
