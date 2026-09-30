"""Médiathèque WordPress, et l'identité d'un acte numéroté.

Aucun appel réseau : les pièces sont celles relevées le 30/09/2026 dans la
médiathèque de l'intercommunalité du premier portage, réduites à ce que l'API
rend. Ce que ces tests protègent tient en deux phrases. Une page « conseil » ne
lie pas tout ce qui est déposé, et ce qui manque se trouve dans la médiathèque.
Un numéro d'acte n'est unique que dans son année.
"""
from __future__ import annotations

import pytest

from collectors.connecteurs import wordpress_rest as wp
from collectors.connecteurs.base import DocumentPublie

BASE = "https://cc.exemple.invalid"
UP = f"{BASE}/wp-content/uploads"


def _media(chemin: str, depose_le: str, titre: str = "") -> dict:
    return {"source_url": f"{UP}/{chemin}", "date": f"{depose_le}T10:00:00",
            "title": {"rendered": titre}}


MEDIAS = [
    _media("2026/07/delibs-09.07.26.pdf", "2026-07-23"),
    _media("2026/07/Liste-des-deliberations-09.07.2026.pdf", "2026-07-15"),
    _media("2026/06/Convocation-Conseil-du-9-juillet-2026.pdf", "2026-06-30"),
    _media("2026/03/Deliberation-N%C2%B041-du-4-mars-2026-Tarifs-AEP-Assainissement.pdf",
           "2026-03-24", "Deliberation N°41 du 4 mars 2026 Tarifs AEP Assainissement"),
    _media("2026/05/PV-du-04.03.2026-tampon.pdf", "2026-05-07"),
    _media("2026/02/Deliberations-conseil-communautaire-fevrier-2026.pdf", "2026-02-19"),
    _media("2026/04/Rapport-activite-2025.pdf", "2026-04-02"),
    # Rend compte, ne délibère pas.
    _media("2026/07/Compte-Rendu-COPIL-26.06.2026.pdf", "2026-07-01"),
    # Une autre assemblée, et une procédure qui n'est pas un conseil.
    _media("2022/07/SIRPMMM-Deliberations-conseil-syndical-12-07-2022.pdf", "2022-07-20"),
    _media("2023/10/PV_EXAMEN_CONJOINT_DPMEC_PLUI_12_10_2023.pdf", "2023-10-20"),
    # Le titre réécrit à la main a perdu la date ; le nom de fichier la garde.
    _media("2026/05/PV-du-16.04.2026-tampon.pdf", "2026-05-07", "PV tampon"),
    _media("2022/10/Delib-N%C2%B044-du-5-avril-2017-Tarif-redevance-SPANC-2017.pdf",
           "2022-10-11"),
]


@pytest.fixture
def mediatheque(monkeypatch):
    monkeypatch.setattr(wp.Site, "pdf_deposes", lambda self: iter(MEDIAS))


# ── la date ──────────────────────────────────────────────────────────────────

def test_la_date_se_lit_dans_le_libelle():
    assert wp._date_de_piece("Deliberation N°41 du 4 mars 2026 Tarifs", "2026-03-24") \
        == "2026-03-04"
    assert wp._date_de_piece("PV du 04.03.2026 tampon", "2026-05-07") == "2026-03-04"


def test_une_annee_courte_nest_crue_que_si_le_depot_la_confirme():
    assert wp._date_de_piece("delibs 09.07.26", "2026-07-23") == "2026-07-09"
    # Séance de décembre, publiée en janvier.
    assert wp._date_de_piece("delibs 17.12.25", "2026-01-08") == "2025-12-17"
    # Le libellé a perdu ses tirets, ou colle la date au mot qui précède.
    assert wp._date_de_piece("PV 28 05 2014", "2022-10-05") == "2014-05-28"
    assert wp._date_de_piece("PV du8.02.2023", "2023-03-24") == "2023-02-08"
    assert wp._date_de_piece("pv27032026signée", "2026-04-02") == "2026-03-27"
    # Rien ne permet de trancher : la pièce reste non datée.
    assert wp._date_de_piece("DELIB N°128 DU 29 11 17", "2022-10-07") is None
    assert wp._date_de_piece("delibs 09.07.26", "2031-02-01") is None


# ── le catalogue ─────────────────────────────────────────────────────────────

def test_seules_les_pieces_qui_rapportent_une_decision_sont_reprises(mediatheque, capsys):
    docs = wp.catalogue_mediatheque(BASE, deja=set())
    noms = sorted(d.url.rsplit("/", 1)[-1] for d in docs)

    assert noms == ["Delib-N%C2%B044-du-5-avril-2017-Tarif-redevance-SPANC-2017.pdf",
                    "Deliberation-N%C2%B041-du-4-mars-2026-Tarifs-AEP-Assainissement.pdf",
                    "PV-du-04.03.2026-tampon.pdf", "PV-du-16.04.2026-tampon.pdf",
                    "delibs-09.07.26.pdf"]
    # Un recueil daté du seul mois n'est pas daté : il est annoncé, pas deviné.
    assert "sans date lisible" in capsys.readouterr().out


def test_une_piece_deja_liee_par_la_page_nest_pas_reprise(mediatheque):
    # La page lie la pièce avec le « ° » en clair, la médiathèque l'encode.
    deja = {f"{UP}/2026/03/Deliberation-N°41-du-4-mars-2026-Tarifs-AEP-Assainissement.pdf",
            f"{UP}/2026/05/PV-du-04.03.2026-tampon.pdf"}

    docs = wp.catalogue_mediatheque(BASE, deja=deja)

    assert sorted(d.url.rsplit("/", 1)[-1] for d in docs) == [
        "Delib-N%C2%B044-du-5-avril-2017-Tarif-redevance-SPANC-2017.pdf",
        "PV-du-16.04.2026-tampon.pdf", "delibs-09.07.26.pdf"]


def test_une_deliberation_publiee_seule_est_un_acte(mediatheque):
    docs = {d.date: d for d in wp.catalogue_mediatheque(BASE, deja=set())
            if d.acte}

    acte = docs["2026-03-04"]
    assert acte.acte["numero"] == "41"
    assert acte.meta == {"depuis_mediatheque": True, "depose_le": "2026-03-24"}
    assert docs["2017-04-05"].acte["numero"] == "44", "« Delib-N°44 » abrégé"
    assert len(docs) == 2, "un recueil ou un PV n'est pas un acte"


# ── l'identité d'un acte numéroté ────────────────────────────────────────────

def _deliberation(base, numero: str, date: str, titre: str) -> int:
    pytest.importorskip("pdfplumber",
                        reason="job « tests-deps » : pip install -r requirements.txt")
    from collectors import conseils
    from collectors.pv_parsers import acte_unique

    doc = DocumentPublie(date=date, url=f"{UP}/{date}-{numero}.pdf",
                         source="cc.exemple.invalid")
    return conseils.enregistrer_deliberation(
        base, doc, "epci", acte_unique(titre, f"{titre}. Adopté à l'unanimité.", numero))


def test_le_meme_numero_une_autre_annee_est_un_autre_acte(base):
    """Le défaut du 30/09/2026 : la n°41 de 2026 écrasait la n°41 de 2021."""
    a = _deliberation(base, "41", "2021-03-03", "Convention de mise à disposition")
    b = _deliberation(base, "41", "2026-03-04", "Tarification de l'eau 2026")

    assert a != b
    titres = [r[0] for r in base.execute(
        "SELECT title FROM events WHERE type='deliberation_cc' ORDER BY date")]
    assert titres == ["Convention de mise à disposition", "Tarification de l'eau 2026"]


def test_le_meme_numero_la_meme_annee_retrouve_sa_fiche(base):
    """Un portail affiche la télétransmission avant que la séance ne soit lue."""
    a = _deliberation(base, "DE2026116BIS", "2026-07-06", "Budget supplémentaire")
    b = _deliberation(base, "DE2026116BIS", "2026-06-25", "Budget supplémentaire")

    assert a == b
    assert base.execute("SELECT date FROM events WHERE id=?", (a,)).fetchone()[0] \
        == "2026-06-25"
