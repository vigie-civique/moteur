"""Un marché en place n'est pas celui de l'intercommunalité parce qu'il n'est pas
celui de la commune.

Relevé le 05/10/2026 sur deux instances : 27 marchés sur 58, et 3 sur 45,
publiés sous la fiche de la communauté de communes alors que leur SIREN
désignait une commune voisine, le Département ou un syndicat. `insert_marche` y
rattachait tout SIREN qui n'était pas celui de la commune ; il ne le fait plus,
mais ne revient pas sur les lignes en place. `scripts/requalifier_marches.py`
les reprend, et ces essais tiennent ce qu'il promet.
"""
from __future__ import annotations

import pytest

from collectors.config import COMMUNE_SIREN, EPCI_NOM, EPCI_SIREN
from scripts import requalifier_marches as R

VOISINE = "219999993"


@pytest.fixture
def epci(base):
    return base.execute("INSERT INTO entities(type, name, confidence) "
                        "VALUES('service', ?, 'verified')", (EPCI_NOM,)).lastrowid


def _marche(conn, fiche, siren, nom, certitude="verified", montant=1000.0):
    ev = conn.execute("INSERT INTO events(type, date, title) "
                      "VALUES('marché_public', '2024-01-01', 'M')").lastrowid
    if fiche:
        conn.execute("INSERT INTO event_entities(event_id, entity_id, role) "
                     "VALUES(?, ?, 'acheteur')", (ev, fiche))
    conn.execute("INSERT INTO financial_flows(type, year, amount, from_id, event_id, "
                 "source, confidence) VALUES('marché', 2024, ?, ?, ?, 'DECP', ?)",
                 (montant, fiche, ev, certitude))
    mid = conn.execute(
        "INSERT INTO marches_publics(acheteur_id, acheteur_siren, acheteur_nom, objet, "
        "montant, source, raw_id, event_id, confidence) VALUES(?,?,?,?,?,'DECP',?,?,?)",
        (fiche, siren, nom, "Objet", montant, f"raw-{ev}", ev, certitude)).lastrowid
    conn.commit()
    return mid, ev


def _lire(conn, mid):
    return tuple(conn.execute("SELECT acheteur_id, confidence FROM marches_publics "
                              "WHERE id=?", (mid,)).fetchone())


def _appliquer(conn):
    plan = R.rattachements_a_reprendre(conn)
    R.reprendre_rattachements(conn, plan)
    conn.commit()
    return plan


def test_un_marche_d_une_commune_voisine_est_detache_sans_perdre_sa_certitude(base, epci):
    mid, ev = _marche(base, epci, VOISINE, "Ville de Voisine")
    [r] = _appliquer(base)
    assert (r["voulue"], r["contredit"]) == (None, False)
    assert _lire(base, mid) == (None, "verified")
    # Le flux et le lien de l'acte suivent : l'argent n'est plus prêté à l'EPCI.
    assert base.execute("SELECT from_id FROM financial_flows WHERE event_id=?",
                        (ev,)).fetchone()[0] is None
    assert base.execute("SELECT COUNT(*) FROM event_entities WHERE event_id=?",
                        (ev,)).fetchone()[0] == 0


def test_il_prend_la_fiche_de_son_siren_quand_elle_existe(base, epci):
    syndicat = base.execute("INSERT INTO entities(type, name, confidence) "
                            "VALUES('business', 'Syndicat des eaux', 'verified')").lastrowid
    base.execute("INSERT INTO businesses(entity_id, siren) VALUES(?, ?)", (syndicat, VOISINE))
    mid, ev = _marche(base, epci, VOISINE + "00017", "Syndicat des eaux")   # un SIRET
    _appliquer(base)
    assert _lire(base, mid) == (syndicat, "verified")
    assert [tuple(x) for x in base.execute(
        "SELECT entity_id, role FROM event_entities WHERE event_id=?", (ev,))] == [
        (syndicat, "acheteur")]


def test_un_nom_qui_contredit_le_siren_attend_un_arbitrage(base, epci):
    """Le nom de la source a été écrasé par celui de l'EPCI : rien ne dit plus
    qui a acheté, sinon un SIREN qui n'est pas le sien."""
    mid, _ = _marche(base, epci, VOISINE, EPCI_NOM)
    [r] = _appliquer(base)
    assert r["contredit"] and _lire(base, mid) == (None, "probable")


def test_les_marches_de_la_commune_et_de_l_epci_ne_bougent_pas(base, epci):
    a, _ = _marche(base, epci, EPCI_SIREN, "Graphie quelconque")
    b, _ = _marche(base, epci, COMMUNE_SIREN, "Mairie")     # mal rattaché, mais pas par le SIREN d'un tiers
    c, _ = _marche(base, epci, "", EPCI_NOM)                # BOAMP : pas de SIREN
    assert _appliquer(base) == []
    assert {_lire(base, x) for x in (a, b, c)} == {(epci, "verified")}


def test_le_siren_ne_promeut_jamais_et_le_rejeu_ne_change_rien(base, epci):
    mid, _ = _marche(base, epci, VOISINE, "Ville de Voisine", certitude="probable")
    _appliquer(base)
    assert _lire(base, mid) == (None, "probable")
    assert _appliquer(base) == []
