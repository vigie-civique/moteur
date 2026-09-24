"""Les subventions de l'État aux associations — le jaune budgétaire.

Le jeu couvre la France entière. Ce que ces essais figent, c'est la façon dont
une ligne se rattache au territoire : par un identifiant, à la maille de la
présence, jamais par le nom. Les cas viennent du jeu réel (PLF 2025).
"""
from __future__ import annotations

import json

import pytest

# `requests` : même convention que tests/test_subventions_ouvertes.py — sauté
# dans le job « tests », joué par « tests-deps ».
requests = pytest.importorskip("requests",
                    reason="job « tests-deps » : pip install -r requirements.txt")

from collectors.etat_flux import etat_du_flux  # noqa: E402
from collectors.jaune_associations import (MILLESIMES, SOURCE,  # noqa: E402
                                           exercice, identifiant, importer)

COLONNES_2023 = MILLESIMES[0][2]
COLONNES_2014 = MILLESIMES[2][2]


def _ligne(siren, nic, nom, montant, objet="Fonct et Innov FDVA /",
           programme="163"):
    return {"siren": siren, "nic": nic, "denomination": nom,
            "montant": montant, "objet_2023": objet, "programme": programme}


def _association(base, entite, nom, siren):
    eid = entite(nom, "association")
    base.execute("INSERT INTO associations (entity_id, siren) VALUES (?,?)",
                 (eid, siren))
    base.commit()
    return eid


def _etat(base, entite):
    return entite("État français", "service")


# ── Identifiant ──────────────────────────────────────────────────────────────

def test_le_nic_complete_le_siren_en_siret():
    assert identifiant({"siren": "450499447", "nic": "00024"},
                       COLONNES_2023) == "45049944700024"


def test_un_nic_ampute_de_ses_zeros_se_recomplete():
    """Un export lu comme nombre perd les zéros de tête : « 24 » est « 00024 »."""
    assert identifiant({"siren": "450499447", "nic": "24"},
                       COLONNES_2023) == "45049944700024"


def test_sans_colonne_nic_on_garde_le_siren():
    assert identifiant({"siren": "520358516"}, COLONNES_2014) == "520358516"


def test_nr_chorus_nest_pas_un_identifiant():
    """La colonne SIREN vaut « NR\\nCHORUS » quand l'association n'en a pas.
    Ce n'est pas un identifiant, et le suppléer par le nom est exclu."""
    assert identifiant({"siren": "NR\nCHORUS", "nic": ""}, COLONNES_2023) == ""


def test_lexercice_se_relit_dans_le_millesime():
    """Le jeu nommé « plf-2016 » porte le jaune du PLF 2015, subventions 2014."""
    rec = {"millesime": "'Jaune PLF 2015 - Subventions 2014"}
    assert exercice(rec, 2099) == 2014
    assert exercice({}, 2023) == 2023


# ── Import ───────────────────────────────────────────────────────────────────

def test_une_association_dici_recoit_son_flux(base, entite):
    etat = _etat(base, entite)
    asso = _association(base, entite, "CHAMP-CONTRECHAMP", "450499447")
    stats = importer(base, [_ligne("450499447", "00024", "CHAMP CONTRECHAMP",
                                   "7000.0")], 2023, COLONNES_2023, etat)
    assert stats["inserees"] == 1
    row = base.execute("SELECT * FROM financial_flows WHERE source=?",
                       (SOURCE,)).fetchone()
    assert (row["from_id"], row["to_id"], row["year"], row["amount"]) == \
        (etat, asso, 2023, 7000)
    assert row["description"] == "[P163] Fonct et Innov FDVA /"


def test_un_homonyme_dailleurs_ne_recoit_rien(base, entite):
    """« ECAM LASALLE » (Lyon) a reçu un million d'euros en 2023. Chercher
    Lasalle par le nom l'aurait attribué à la commune du même nom."""
    etat = _etat(base, entite)
    _association(base, entite, "OGEC SAINT JOSEPH", "331129577")
    stats = importer(base, [_ligne("779883446", "00014", "ECAM LASALLE",
                                   "1037261.0")], 2023, COLONNES_2023, etat)
    assert stats["inserees"] == 0 and stats["hors_perimetre"] == 1


def test_le_siege_dailleurs_ne_verse_rien_a_son_etablissement_dici(base, entite):
    etat = _etat(base, entite)
    eid = entite("FEDERATION NATIONALE", "business")
    base.execute("INSERT INTO businesses (entity_id, siren, siret_siege, raw_data)"
                 " VALUES (?,?,?,?)",
                 (eid, "790058572", "79005857200047",
                  json.dumps({"matching_etablissements": [{"siret": "79005857200237"}],
                              "siege": {"siret": "79005857200047"}})))
    base.commit()
    stats = importer(base, [_ligne("790058572", "00047", "FEDERATION", "50000")],
                     2023, COLONNES_2023, etat)
    assert stats["inserees"] == 0


def test_rejouer_ninsere_pas_deux_fois(base, entite):
    etat = _etat(base, entite)
    _association(base, entite, "VIV'ALTO", "804557353")
    lignes = [_ligne("804557353", "00013", "VIV ALTO", "1500.0")]
    importer(base, lignes, 2023, COLONNES_2023, etat)
    stats = importer(base, lignes, 2023, COLONNES_2023, etat)
    assert stats["inserees"] == 0 and stats["deja"] == 1


def test_deux_lignes_du_meme_programme_restent_deux_flux(base, entite):
    """FDVA fonctionnement et FDVA formation, la même année, au même
    bénéficiaire : deux versements, pas un doublon."""
    etat = _etat(base, entite)
    _association(base, entite, "GROUPE CVN", "909260424")
    stats = importer(base, [
        _ligne("909260424", "00017", "GROUPE CVN", "1500", "Formation bénév FDVA /"),
        _ligne("909260424", "00017", "GROUPE CVN", "1500", "Fonct et Innov FDVA /"),
    ], 2023, COLONNES_2023, etat)
    assert stats["inserees"] == 2


def test_un_flux_du_jaune_est_paye():
    assert etat_du_flux("subvention_etat_association", SOURCE, None) == "paye"
