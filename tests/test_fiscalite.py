"""Les repères de taux : où se place un taux parmi les communes qui lèvent la taxe.

Aucun appel réseau : l'agrégat que rend data.economie.gouv.fr est remplacé par
sa forme, la base est une vraie base.

Ce que ces essais protègent :
  1. une commune sans taux (la redevance remplace la taxe) n'a PAS de repère —
     l'absence de ligne n'est pas un rang ;
  2. le repère porte sur le dernier exercice où la commune a un taux ;
  3. la part publiée est celle des communes dont le taux est au moins égal.
"""
from __future__ import annotations

from collectors import fiscalite


def _taux(base, insee, annee, taux, indicateur="TEOM"):
    base.execute("INSERT INTO fiscalite_taux (insee, annee, indicateur, taux) VALUES (?,?,?,?)",
                 (insee, annee, indicateur, taux))


def test_le_repere_porte_sur_le_dernier_exercice_avec_un_taux(base, monkeypatch):
    fiscalite.ensure_table(base)
    _taux(base, "99001", 2024, 18.0)
    _taux(base, "99001", 2025, 19.92)
    _taux(base, "99002", 2025, 0.0)           # redevance : pas de taxe
    base.commit()
    demandes = []

    def agregat(dataset, select, where):
        demandes.append(where)
        return {"n": 15} if "as n" in select else {"communes": 306, "mediane": 15.22}
    monkeypatch.setattr(fiscalite, "_agregat", agregat)

    assert fiscalite.releve_reperes(base, ["99001", "99002"]) == 2
    assert all("exercice='2025'" in d for d in demandes)
    assert any("taux_plein_teom>=19.92" in d and "dep='99'" in d for d in demandes)
    lignes = base.execute("SELECT insee, annee, portee, taux, communes, au_moins_autant"
                          " FROM fiscalite_reperes ORDER BY portee").fetchall()
    assert [tuple(l) for l in lignes] == [("99001", 2025, "departement", 19.92, 306, 15),
                                          ("99001", 2025, "france", 19.92, 306, 15)]


def test_la_part_publiee_est_celle_des_taux_au_moins_egaux(base):
    from scripts.build_public_snapshot import export_reperes_fiscaux
    assert export_reperes_fiscaux(base) == [], "table absente"
    fiscalite.ensure_table(base)
    base.execute("INSERT INTO fiscalite_reperes VALUES"
                 " ('99001', 2025, 'TEOM', 'france', '', 19.92, 24404, 12.13, 572)")
    base.commit()

    [r] = export_reperes_fiscaux(base)

    assert r["part_au_moins_autant"] == 2.3
