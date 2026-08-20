"""Une base créée par le moteur doit suffire à faire tourner le moteur.

Le 20/08/2026, ce n'était pas le cas. `db/schema.sql` avait dérivé de ce que le
code interroge : huit colonnes et une table existaient dans la base historique
sans jamais avoir été reportées au schéma. Toute instance créée par le moteur
naissait donc infirme, et la file de revue de l'atelier — sa page principale —
échouait sur « no such column: validation_status ».

Le défaut a tenu des semaines parce que la seule instance qu'on ouvrait
régulièrement avait une base copiée depuis la production, qui, elle, avait les
colonnes. Trois instances sur quatre étaient cassées sans que personne le voie.

Ce test crée une base à partir du seul schéma, et vérifie que les tables et
colonnes que le code nomme y sont. Il ne teste pas du comportement : il teste
que les deux moitiés du dispositif parlent de la même base.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
SCHEMA = RACINE / "db" / "schema.sql"

# Ce que le code nomme, relevé à la main depuis api.py, les collecteurs et les
# scripts de publication. Toute nouvelle colonne utilisée doit venir ici.
ATTENDU = {
    "entities": {"id", "type", "name", "commune", "confidence", "perimetre",
                 "name_norm", "geocode_source", "validation_status",
                 "responsible", "x_l93", "y_l93", "geocode_score"},
    "businesses": {"entity_id", "siren", "naf_code", "pappers_fetched_at",
                   "pappers_raw"},
    "associations": {"entity_id", "rna_id", "siren"},
    "annotations": {"object_type", "object_id", "review_status", "confidence",
                    "note", "reviewed_by", "reviewed_at", "corrections"},
    "marches_publics": {"acheteur_id", "acheteur_nom", "objet", "raw_id",
                        "event_id", "confidence"},
    "relation_candidates": {"from_id", "to_id", "relation_type", "review_status",
                            "review_note", "reviewed_at", "locked_by"},
    "entity_websites": {"entity_id", "url", "status", "found_by"},
    "events": {"id", "type", "date", "title", "source", "source_url", "metadata"},
    "financial_flows": {"type", "year", "amount", "from_id", "to_id",
                        "event_id", "description", "source", "confidence"},
    "budget_vote": {"year", "scope", "agregat", "value", "unit"},
}


@pytest.fixture(scope="module")
def base_neuve():
    """Une base créée du seul schéma, comme à l'amorçage d'une instance."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA.read_text())
    return conn


@pytest.mark.parametrize("table", sorted(ATTENDU))
def test_la_table_existe(base_neuve, table):
    r = base_neuve.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    assert r, f"`{table}` est interrogée par le code et absente du schéma"


@pytest.mark.parametrize("table", sorted(ATTENDU))
def test_les_colonnes_attendues_existent(base_neuve, table):
    presentes = {r[1] for r in base_neuve.execute(f"PRAGMA table_info({table})")}
    manquantes = ATTENDU[table] - presentes
    assert not manquantes, (
        f"`{table}` : le code interroge {sorted(manquantes)}, le schéma ne les "
        f"déclare pas. Une instance neuve naîtrait infirme.")


def test_le_rattrapage_de_colonnes_ne_dit_pas_l_inverse_du_schema():
    """`_COLONNES_AJOUTEES` répare les bases anciennes. Une colonne qui y figure
    doit aussi être au schéma, sinon les bases neuves restent sans elle."""
    src = (RACINE / "collectors" / "db.py").read_text()
    bloc = re.search(r"_COLONNES_AJOUTEES = \[(.*?)\n\]", src, re.S)
    assert bloc, "_COLONNES_AJOUTEES introuvable"
    entrees = re.findall(r'\("(\w+)",\s*"(\w+)"', bloc.group(1))
    assert entrees, "aucune entrée relevée — le motif de lecture a changé"

    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA.read_text())
    for table, colonne in entrees:
        presentes = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        assert colonne in presentes, (
            f"`{table}.{colonne}` est rattrapée sur les bases anciennes mais "
            f"absente du schéma : les bases neuves ne l'auraient jamais.")
