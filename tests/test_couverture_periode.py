"""La période couverte par une source s'arrête à la date d'arrêt des données.

Relevé par l'audit du 24/09/2026 : /couverture annonçait lasalle.fr couvert
« jusqu'au 14/11/2026 », deux mois après la collecte — un concert de l'agenda.
Ce qui est annoncé pour plus tard se compte à part.
"""
from __future__ import annotations

import sqlite3

from scripts.build_public_snapshot import export_couverture

STATS = {"generated_at": "2026-09-24T14:00:00"}


def _source(evenements):
    conn = sqlite3.connect(":memory:")
    sources = export_couverture(conn, evenements, STATS)["sources"]
    return {s["source"]: s for s in sources}


def test_un_evenement_annonce_ne_prolonge_pas_la_periode():
    s = _source([
        {"source": "mairie", "date": "2016-01-13"},
        {"source": "mairie", "date": "2026-09-20"},
        {"source": "mairie", "date": "2026-11-14"},
    ])["mairie"]
    assert (s["debut"], s["fin"]) == ("2016-01-13", "2026-09-20")
    assert (s["a_venir"], s["annonce_jusqu_au"]) == (1, "2026-11-14")
    assert s["actes"] == 3


def test_le_jour_de_l_arret_compte_dans_la_periode():
    s = _source([{"source": "mairie", "date": "2026-09-24"}])["mairie"]
    assert s["fin"] == "2026-09-24" and s["a_venir"] == 0


# ── Le journal des corrections ────────────────────────────────────────────────
import json  # noqa: E402

from scripts.build_public_snapshot import (  # noqa: E402
    export_corrections, lire_journal_corrections)


def test_le_journal_ecarte_ce_qui_est_incomplet_et_ne_suit_aucune_url(tmp_path):
    f = tmp_path / "journal.json"
    f.write_text(json.dumps([
        {"date": "2026-09-24", "page": "/finances", "constat": "0 € versé",
         "correction": "commune retrouvée malgré la casse"},
        {"date": "24/09/2026", "constat": "date mal formée", "correction": "x"},
        {"date": "2026-09-20", "constat": "sans correction"},
        {"date": "2026-09-21", "page": "https://ailleurs.example/x",
         "constat": "lien externe", "correction": "retiré"},
    ]), encoding="utf-8")
    journal = lire_journal_corrections(f)
    assert [e["date"] for e in journal] == ["2026-09-24", "2026-09-21"]
    assert journal[1]["page"] is None


def test_un_journal_absent_est_un_journal_vide(tmp_path):
    assert lire_journal_corrections(tmp_path / "absent.json") == []


def test_une_donnee_rectifiee_entre_au_journal_avec_son_motif():
    j = export_corrections(
        [{"id": 7, "date": "2024-03-01", "title": "Subvention",
          "corrige": ["montant"], "note_revue": "article 12 lu comme montant"},
         {"id": 8, "date": "2024-03-01", "title": "Rien à signaler"}],
        [], [], [])
    assert j["site"] == []
    assert [(d["id"], d["champs"], d["motif"]) for d in j["donnees"]] == [
        (7, ["montant"], "article 12 lu comme montant")]
