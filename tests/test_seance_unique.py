"""Une séance est identifiée par sa date et son assemblée, pas par sa pièce.

Un conseil municipal produit plusieurs documents : la convocation, l'ordre du
jour, le registre des délibérations télétransmis à la préfecture, le
procès-verbal qui rapporte les débats, parfois une annexe. `enregistrer_seance`
prenait l'URL du document pour identité — chaque pièce faisait donc sa séance.

Relevé sur la base de Lasalle le 15/09/2026, avant correction :

    séances                              243
    dates portant plusieurs fiches        46
    fiches en trop                        49   (20 %)
    dont une seconde séance réelle         0

Pas une seule de ces 46 dates ne portait deux séances tenues le même jour : le
cas que l'identité par l'URL protégeait est resté hypothétique, celui qu'elle
fabriquait se lisait sur la page d'accueil — « Conseil municipal du 2026-06-30 »
deux fois de suite, l'une pour le registre, l'autre pour le procès-verbal.
"""
from __future__ import annotations

import json

import pytest

from collectors import conseils
from collectors.connecteurs.base import DocumentPublie


def _doc(url: str, libelle: str, date: str = "2026-06-30") -> DocumentPublie:
    return DocumentPublie(date=date, url=url, libelle=libelle,
                          source="lasalle.fr")


def test_deux_pieces_ne_font_qu_une_seance(base):
    """Le registre et le procès-verbal rapportent LA MÊME séance."""
    registre = conseils.enregistrer_seance(
        base, _doc("https://x.fr/CM-30.06.26-DELIBERATIONS.pdf",
                   "cm du 30 juin 2026 deliberations"), "commune",
        {"nb_deliberations": 15})
    pv = conseils.enregistrer_seance(
        base, _doc("https://x.fr/2026.06.30.pdf",
                   "pv du conseil municipal du 30 juin 2026"), "commune",
        {"presents": ["SCHWEDA", "BAREAU"]})

    assert registre == pv, "deux fiches pour une séance"
    n = base.execute("SELECT COUNT(*) FROM events"
                     " WHERE type='conseil_municipal'").fetchone()[0]
    assert n == 1, f"{n} séances pour un seul conseil"


def test_la_fusion_ne_perd_pas_ce_que_la_piece_precedente_a_lu(base):
    """Les présents viennent du PV, le nombre d'actes du registre.

    Remplacer les métadonnées au lieu de les fusionner effaçait les uns ou les
    autres selon l'ordre de collecte — et l'ordre de collecte n'est pas un fait
    sur la séance.
    """
    conseils.enregistrer_seance(
        base, _doc("https://x.fr/registre.pdf", "deliberations du 30 juin"),
        "commune", {"nb_deliberations": 15})
    seance = conseils.enregistrer_seance(
        base, _doc("https://x.fr/pv.pdf", "pv du 30 juin 2026"), "commune",
        {"presents": ["SCHWEDA"], "pouvoirs": [{"de": "PIBAROT", "à": "BAREAU"}]})

    meta = json.loads(base.execute("SELECT metadata FROM events WHERE id=?",
                                   (seance,)).fetchone()["metadata"])
    assert meta["nb_deliberations"] == 15
    assert meta["presents"] == ["SCHWEDA"]
    assert len(meta["pouvoirs"]) == 1


def test_les_pieces_sont_toutes_gardees_et_rangees(base):
    """Aucune pièce n'est perdue, et la plus probante vient en tête."""
    for url, libelle in (
            ("https://x.fr/convocation.pdf", "Convocation Conseil du 30 juin 2026"),
            ("https://x.fr/registre.pdf", "Deliberations du 30 juin 2026"),
            ("https://x.fr/pv.pdf", "PV du 30.06.2026"),
    ):
        seance = conseils.enregistrer_seance(base, _doc(url, libelle), "commune")

    row = base.execute("SELECT source_url, metadata FROM events WHERE id=?",
                       (seance,)).fetchone()
    pieces = json.loads(row["metadata"])["pieces"]
    assert [p["nature"] for p in pieces] == ["proces_verbal", "deliberations",
                                             "convocation"]
    # La fiche renvoie au procès-verbal : il rapporte la séance entière, quand
    # la convocation ne fait que l'annoncer.
    assert row["source_url"] == "https://x.fr/pv.pdf"


def test_une_piece_recollectee_ne_se_dedouble_pas(base):
    """L'idempotence tient sur la pièce comme sur la séance."""
    doc = _doc("https://x.fr/pv.pdf", "PV du 30.06.2026")
    conseils.enregistrer_seance(base, doc, "commune")
    seance = conseils.enregistrer_seance(base, doc, "commune")
    pieces = json.loads(base.execute("SELECT metadata FROM events WHERE id=?",
                                     (seance,)).fetchone()["metadata"])["pieces"]
    assert len(pieces) == 1, pieces


def test_deux_assemblees_le_meme_jour_restent_deux_seances(base):
    """Ce que la date seule ne doit PAS confondre : le conseil municipal et le
    conseil communautaire peuvent siéger le même jour. L'identité porte sur le
    couple (assemblée, date), jamais sur la date seule."""
    cm = conseils.enregistrer_seance(
        base, _doc("https://x.fr/cm.pdf", "PV du conseil municipal"), "commune")
    cc = conseils.enregistrer_seance(
        base, _doc("https://y.fr/cc.pdf", "PV du conseil communautaire"), "epci")
    assert cm != cc


@pytest.mark.parametrize("iso, attendu", [
    ("2026-06-30", "30 juin 2026"),
    ("2026-08-01", "1er août 2026"),
    ("2026-12-09", "9 décembre 2026"),
    ("", ""),
])
def test_le_titre_se_lit_en_francais(iso, attendu):
    """Une date ISO est une clé, pas une phrase : « Conseil municipal du
    2026-06-30 » était servi tel quel sur la page d'accueil."""
    assert conseils.date_en_francais(iso) == attendu


def test_le_titre_de_la_seance_ne_porte_plus_d_iso(base):
    seance = conseils.enregistrer_seance(
        base, _doc("https://x.fr/pv.pdf", "PV du 30.06.2026"), "commune")
    titre = base.execute("SELECT title FROM events WHERE id=?",
                         (seance,)).fetchone()["title"]
    assert titre == "Conseil municipal du 30 juin 2026"
