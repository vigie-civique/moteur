"""Fixtures communes.

Deux partis pris, qui expliquent la forme de ces tests.

**La base n'est jamais simulée.** Elle est créée depuis `db/schema.sql`, le
même fichier que celui d'une instance réelle. Une base simulée aurait les
colonnes qu'on croit, pas celles qui existent — c'est précisément ce qui a
laissé `build_rag_index` interroger `events.entity_id`, colonne inexistante,
et n'indexer aucun acte pendant des mois sans que rien ne le signale.

**L'instance est factice mais complète.** `tests/instance_test.json` décrit une
commune qui n'existe pas, pour qu'un dépôt fraîchement cloné puisse lancer sa
suite sans configurer de périmètre, et pour qu'un test en échec ne fasse jamais
douter d'une vraie collecte.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Doit être posé AVANT tout import de collectors.config, qui lit ces variables
# au chargement du module.
os.environ.setdefault("VIGIE_INSTANCE",
                      str(Path(__file__).parent / "instance_test.json"))
os.environ.setdefault("VIGIE_RULES",
                      str(ROOT / "config" / "publication_rules.exemple.json"))


@pytest.fixture(scope="session")
def schema_sql() -> str:
    return (ROOT / "db" / "schema.sql").read_text(encoding="utf-8")


@pytest.fixture
def base(tmp_path, schema_sql) -> sqlite3.Connection:
    """Une base vide au schéma réel, jetable."""
    conn = sqlite3.connect(tmp_path / "test.db")
    conn.executescript(schema_sql)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn
    conn.close()


@pytest.fixture
def entite(base):
    """Fabrique une entité et renvoie son identifiant.

    Les identifiants ne sont jamais écrits en dur dans les tests : c'est le
    défaut que le dispositif combat (`XXX_ID = 63`), il n'a pas à être réintroduit
    ici.
    """
    def _creer(nom: str, type_: str = "business", commune: str | None = None,
               perimetre: str | None = None, confidence: str = "verified") -> int:
        cur = base.execute(
            "INSERT INTO entities (type, name, commune, perimetre, confidence) "
            "VALUES (?,?,?,?,?)", (type_, nom, commune, perimetre, confidence))
        base.commit()
        return cur.lastrowid
    return _creer
