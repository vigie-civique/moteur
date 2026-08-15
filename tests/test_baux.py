"""L'extraction des loyers communaux depuis les délibérations de tarifs.

Les baux ne sont dans aucun registre : ils sont votés en conseil et présentés
en tableau dans le procès-verbal, une ligne par local, le montant en fin de
ligne. Ils avaient été saisis à la main sur l'instance d'origine, avec la
délibération citée en source — la matière était donc déjà là.

Rien n'est publié : les flux entrent en `probable`. Deux raisons, et les tests
les couvrent — le découpage local/occupant est une lecture, et la périodicité
n'est pas toujours écrite dans le PV.
"""
from __future__ import annotations

import pytest

from collectors.cm_finances import extract_baux

# Fidèle à deux PV réels : le tableau de 2023 annonce sa périodicité, celui de
# 2025 ne l'annonce pas. La ligne « Villa N° » est celle qui se résolvait vers
# une entreprise nommée d'après un patronyme.
PV_2023 = """LOYERS COMMUNAUX :
Considérant que la révision des baux communaux au 1er janvier est calculée
sur l'indice de référence des loyers du 1er trimestre.
PAR MOIS
81 rue de la Place - Appart. 461,05
58 rue de la Croix - Microsillon 57,34
116 rue de la Gravière - Comité des Fêtes 44,11
Local Stade - Vélo Club 25,88
Lotissement les Glycines - Villa N° 1417,73
Total 2006,11
"""

PV_2025 = """Adresse Loyer 2025 revalorisé 2,5 %
81 rue de la Place - Appart. 486.75
58 rue de la Croix - Microsillon 60.54
"""


@pytest.fixture
def lignes(base):
    def _poser(titre, date, contenu):
        base.execute(
            "INSERT INTO events (type, date, title, content, source) "
            "VALUES ('deliberation',?,?,?,'CM')", (date, titre, contenu))
        base.commit()
    _poser("LOYERS 2023", "2022-12-12", PV_2023)
    _poser("TARIFS LOYERS COMMUNAUX 2025", "2024-12-20", PV_2025)
    return {(b["annee"], b["local"]): b for b in extract_baux(base)}


def test_les_lignes_de_tableau_sont_lues(lignes):
    assert (2022, "81 rue de la Place - Appart.") in lignes
    assert (2024, "58 rue de la Croix - Microsillon") in lignes


def test_le_montant_est_lu_quelle_que_soit_la_virgule(lignes):
    assert lignes[(2022, "81 rue de la Place - Appart.")]["montant"] == 461.05
    assert lignes[(2024, "81 rue de la Place - Appart.")]["montant"] == 486.75


def test_la_periodicite_declaree_est_retenue(lignes):
    """« PAR MOIS » sur sa propre ligne s'applique au tableau qui suit."""
    assert lignes[(2022, "Local Stade - Vélo Club")]["mensuel"] is True


def test_la_periodicite_absente_nest_pas_supposee(lignes):
    """Le PV de 2025 ne la dit pas : on n'annualise pas, on ne devine pas."""
    assert lignes[(2024, "58 rue de la Croix - Microsillon")]["mensuel"] is False


def test_loccupant_est_lu_apres_le_dernier_tiret(lignes):
    assert lignes[(2022, "58 rue de la Croix - Microsillon")]["occupant"] == "Microsillon"
    assert lignes[(2022, "116 rue de la Gravière - Comité des Fêtes")]["occupant"] \
        == "Comité des Fêtes"


def test_un_mot_de_local_nest_pas_un_occupant(lignes):
    """« Villa N° » désigne le bien, pas son locataire. Il se résolvait vers
    une entreprise nommée d'après un patronyme, à qui la base aurait attribué
    un loyer de 1 418 € — une erreur nominative."""
    assert lignes[(2022, "Lotissement les Glycines - Villa N°")]["occupant"] == ""


def test_appart_nest_pas_un_occupant(lignes):
    assert lignes[(2022, "81 rue de la Place - Appart.")]["occupant"] == ""


def test_la_ligne_de_total_est_ecartee(lignes):
    assert not any("Total" in local for _, local in lignes)


def test_la_prose_nest_pas_un_bail(lignes):
    """Une phrase citant « 1er trimestre » ne doit pas passer pour un tarif."""
    assert not any("indice" in local.lower() or "révision" in local.lower()
                   for _, local in lignes)


def test_une_deliberation_sans_rapport_est_ignoree(base):
    base.execute(
        "INSERT INTO events (type, date, title, content, source) "
        "VALUES ('deliberation','2024-01-01','SUBVENTIONS AUX ASSOCIATIONS',"
        "'Rue de la Place - Untel 100,00','CM')")
    base.commit()
    assert extract_baux(base) == []
