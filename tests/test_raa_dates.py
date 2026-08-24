"""Date d'un recueil des actes administratifs : nom de fichier, puis couverture.

Trois préfectures, trois habitudes, et c'est la source qui a raison :
le Gard date ses fichiers, la Drôme les numérote. Un recueil sans date entre en
base comme un événement sans date — invisible dans une frise, impossible à
situer. Relevé le 24/08/2026 : 79 recueils de la Drôme, aucune date.
"""
from __future__ import annotations

from collectors.raa_prefecture import date_du_recueil

# La couverture réglementaire, telle que pdftotext la rend.
COUVERTURE = """DRÔME

RECUEIL DES ACTES
ADMINISTRATIFS SPÉCIAL
N°26-2026-016
PUBLIÉ LE 16 JANVIER 2026
"""


def test_le_nom_de_fichier_quand_il_porte_la_date():
    assert date_du_recueil("recueil-30-2026-001-special du 05 01 2026.pdf") == "2026-01-05"


def test_le_nom_de_fichier_meme_en_capitales():
    """Trois recueils du Gard restaient sans date pour un « DU » majuscule."""
    assert date_du_recueil("recueil-30-2026-042-special DU 03 03 2026.pdf") == "2026-03-03"


def test_la_couverture_quand_le_nom_ne_dit_rien():
    assert date_du_recueil("RAA SPECIAL N°26-2026-016.pdf", [COUVERTURE]) == "2026-01-16"


def test_le_nom_prime_sur_la_couverture():
    """Les deux se sont toujours accordés ; le nom ne coûte pas de lecture."""
    assert date_du_recueil("recueil du 05 01 2026.pdf", [COUVERTURE]) == "2026-01-05"


def test_rien_nest_deduit_dun_recueil_muet():
    """Mieux vaut un événement sans date qu'un événement mal daté."""
    assert date_du_recueil("recueil-26-2026-100.pdf", ["une couverture muette"]) is None
    assert date_du_recueil("recueil-26-2026-100.pdf") is None


def test_seule_la_premiere_page_fait_foi():
    """« PUBLIÉ LE » au fil d'un arrêté, page 12, n'est pas la date du recueil."""
    pages = ["couverture sans date", "ARRÊTÉ … publié le 3 mars 2026 au registre"]

    assert date_du_recueil("recueil-26-2026-100.pdf", pages) is None
