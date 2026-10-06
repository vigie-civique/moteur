"""`conflits.json` ne cite que ce qui est publié par ailleurs.

La vue `v_conflits_potentiels` joint relations et flux sans regarder ni la
confiance d'un lien ni le sort d'un acte : une piste `hypothesis` sortait comme
« situation à vérifier », et le déport citait le titre brut d'un acte que
`events.json` ne publie pas. Un conflit se compose désormais de ce que les
autres étapes ont retenu — liens, versements, actes.
"""
from __future__ import annotations

import json

from scripts.snapshot.conflits import export_conflits


def _lien(base, de, vers, type_, confidence="verified"):
    cur = base.execute(
        "INSERT INTO relations (from_id, to_id, relation_type, confidence) VALUES (?,?,?,?)",
        (de, vers, type_, confidence))
    return {"id": cur.lastrowid, "from_id": de, "to_id": vers, "relation_type": type_,
            "confidence": confidence}


def _versement(base, de, vers, montant=1500, annee=2024):
    cur = base.execute(
        "INSERT INTO financial_flows (from_id, to_id, type, amount, year, confidence) "
        "VALUES (?,?,'subvention',?,?,'verified')", (de, vers, montant, annee))
    return {"id": cur.lastrowid}


def _decor(base, entite, confiance_du_lien):
    commune = entite("Commune de Testonville", "service")
    elue = entite("Jeanne MARTIN", "person")
    asso = entite("Les Amis du Lavoir", "association")
    mandat = _lien(base, elue, commune, "élu_cm")
    direction = _lien(base, elue, asso, "président", confiance_du_lien)
    flux = _versement(base, commune, asso)
    base.commit()
    return commune, elue, asso, mandat, direction, flux


def _exporter(base, ids, relations, flux, actes=()):
    return export_conflits(base, set(ids), relations, flux, list(actes), lambda t: t)


def test_une_piste_ne_fait_pas_une_situation(base, entite):
    commune, elue, asso, mandat, direction, flux = _decor(base, entite, "hypothesis")
    # `relations.json` ne retient pas la piste : seul le mandat est publié.
    sortie = _exporter(base, (commune, elue, asso), [mandat], [flux])
    assert sortie["cas"] == [] and sortie["total"] == 0


def test_un_lien_publie_et_son_versement_font_une_situation(base, entite):
    commune, elue, asso, mandat, direction, flux = _decor(base, entite, "verified")
    sortie = _exporter(base, (commune, elue, asso), [mandat, direction], [flux])
    assert [(c["person_id"], c["entite_id"], c["flux_id"]) for c in sortie["cas"]] == [
        (elue, asso, flux["id"])]


def test_un_versement_non_publie_ne_laisse_que_le_lien(base, entite):
    commune, elue, asso, mandat, direction, flux = _decor(base, entite, "verified")
    sortie = _exporter(base, (commune, elue, asso), [mandat, direction], [])
    assert [(c["flux_id"], c["flux_montant"], c["statut"]) for c in sortie["cas"]] == [
        (None, None, "lien_sans_versement")]


def test_le_deport_ne_cite_quun_acte_publie_et_sous_son_titre_publie(base, entite):
    commune, elue, asso, mandat, direction, flux = _decor(base, entite, "verified")
    brut = "Subvention Lavoir — Mme MARTIN, née le 05/03/1961, ne participe pas"
    cur = base.execute(
        "INSERT INTO events (type, date, title, source, metadata) VALUES "
        "('deliberation','2024-04-02',?,'source_inconnue',?)",
        (brut, json.dumps({"conflit_interet": "Jeanne MARTIN ne participe pas au vote"})))
    base.commit()
    acte = cur.lastrowid

    # L'acte n'est pas publié : pas de déport, et il n'est pas compté.
    sortie = _exporter(base, (commune, elue, asso), [mandat, direction], [flux])
    assert sortie["cas"][0]["deport"] is None
    assert sortie["deports_repertories"] == 0
    assert "1961" not in json.dumps(sortie, ensure_ascii=False)

    # Publié, il est cité tel que `events.json` l'écrit.
    publie = {"id": acte, "date": "2024-04-02", "source_url": "https://exemple.test/pv.pdf",
              "title": "Subvention Lavoir — Mme MARTIN, née le [date masquée], ne participe pas"}
    sortie = _exporter(base, (commune, elue, asso), [mandat, direction], [flux], [publie])
    deport = sortie["cas"][0]["deport"]
    assert deport["event_id"] == acte and deport["titre"] == publie["title"]
    assert sortie["cas"][0]["statut"] == "deport_constate"
    assert sortie["deports_repertories"] == 1
    assert "1961" not in json.dumps(sortie, ensure_ascii=False)
