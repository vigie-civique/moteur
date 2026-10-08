"""Une personne que plus rien ne désigne quitte la base ; toute autre y reste."""
from __future__ import annotations

import sqlite3

import pytest

from scripts import purger_personnes_sans_lien as purge


@pytest.fixture
def base(tmp_path, schema_sql):
    conn = sqlite3.connect(tmp_path / "instance.db")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(schema_sql)

    def personne(nom, naissance=None):
        eid = conn.execute("INSERT INTO entities(type, name, commune, perimetre) "
                           "VALUES('person', ?, 'Ailleurs', 'C2')", (nom,)).lastrowid
        conn.execute("INSERT INTO persons(entity_id, lastname, birth_year) VALUES(?,?,?)",
                     (eid, nom, naissance))
        return eid

    ids = {n: personne(n, a) for n, a in (("seule", 1960), ("seule2", None), ("dirigeante", 1970),
                                          ("relue", None), ("notee", None), ("corrigee", None))}
    ids["asso"] = conn.execute("INSERT INTO entities(type, name) VALUES('association', 'Sans lien')").lastrowid
    conn.execute("INSERT INTO relations(from_id, to_id, relation_type) VALUES(?,?,'président')",
                 (ids["dirigeante"], ids["asso"]))
    conn.execute("INSERT INTO annotations(object_type, object_id, review_status) "
                 "VALUES('entity', ?, 'ecarte')", (ids["relue"],))
    conn.execute("INSERT INTO entity_notes(entity_id, date, note) VALUES(?, '2026-10-01', 'vue')",
                 (ids["notee"],))
    conn.execute("INSERT INTO audit_log(entity_id, table_name, action) VALUES(?, 'entities', 'update')",
                 (ids["corrigee"],))
    conn.commit()
    yield conn, ids
    conn.close()


def test_le_releve_compte_sans_rien_ecrire(base):
    conn, _ = base
    r = purge.releve(conn)
    assert (r["personnes"], r["sans_lien"], r["avec_naissance"]) == (6, 2, 1)
    assert r["par_perimetre"] == {"C2": 2}
    assert conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 7


def test_seules_les_personnes_que_rien_ne_retient_partent(base):
    conn, ids = base
    assert purge.purger(conn) == 2
    conn.commit()
    restent = {r[0] for r in conn.execute("SELECT id FROM entities")}
    assert restent == {ids[n] for n in ("dirigeante", "relue", "notee", "corrigee", "asso")}
    # La fiche étendue part avec la fiche, et le journal garde la trace.
    assert conn.execute("SELECT COUNT(*) FROM persons").fetchone()[0] == 4
    assert conn.execute("SELECT action, field FROM audit_log ORDER BY id DESC LIMIT 1").fetchone() == (
        "purge", "personnes sans lien")
    assert purge.releve(conn)["sans_lien"] == 0
