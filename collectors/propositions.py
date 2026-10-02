"""Les propositions : ce qu'un contributeur écrit sur un objet PUBLIÉ.

Arbitré par Julien le 02/10/2026, avant l'arrivée des premiers bénévoles. Les
rôles disaient « le contributeur propose sans trancher », mais l'API ne
réservait au validateur que le verdict et la fiabilité : le nom d'une fiche
publiée, le type d'une relation, le montant corrigé d'un acte s'écrivaient
directement — et la passe quotidienne les mettait en ligne sans que personne
les ait relus.

Une proposition garde ce que le contributeur voulait écrire (`charge`), ce
qu'il avait sous les yeux (`avant`), et attend. Un validateur l'accepte — elle
est alors REJOUÉE par le même écrivain que s'il l'avait saisie lui-même, il n'y
a pas de second chemin d'écriture — ou la refuse, avec un motif.

Ce module ne porte que la table. Les écrivains vivent dans `api.py`, à côté de
ce qu'ils écrivent.
"""
from __future__ import annotations

import json
from typing import Optional

#: Ce qu'une proposition peut porter, et l'objet qu'elle vise.
NATURES = ("fiche", "coords", "relation", "correction")
ETATS = ("en_attente", "acceptee", "refusee", "retiree")

SCHEMA = """CREATE TABLE IF NOT EXISTS propositions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    nature       TEXT NOT NULL,
    object_type  TEXT NOT NULL,
    object_id    INTEGER NOT NULL,
    entity_id    INTEGER,
    charge       TEXT NOT NULL,
    avant        TEXT,
    propose_par  INTEGER REFERENCES users(id),
    propose_le   TEXT DEFAULT (datetime('now')),
    etat         TEXT NOT NULL DEFAULT 'en_attente',
    tranche_par  INTEGER REFERENCES users(id),
    tranche_le   TEXT,
    motif        TEXT
)"""


def assurer_schema(conn) -> None:
    """L'API ne passe pas par `init_db()` : une base d'avant le 02/10/2026 n'a
    pas la table, et la première proposition y échouerait."""
    conn.execute(SCHEMA)


def proposer(conn, nature: str, object_type: str, object_id: int,
             entity_id: Optional[int], charge: dict, avant: dict, user: dict) -> int:
    """Enregistre la proposition et la journalise. Une proposition encore en
    attente du même auteur, sur le même objet et de même nature, est REMPLACÉE :
    corriger sa propre proposition ne doit pas en empiler deux à relire."""
    conn.execute(
        "UPDATE propositions SET etat='retiree', tranche_le=datetime('now') "
        "WHERE etat='en_attente' AND nature=? AND object_type=? AND object_id=? "
        "AND propose_par=?", (nature, object_type, object_id, user["id"]))
    pid = conn.execute(
        "INSERT INTO propositions(nature, object_type, object_id, entity_id, charge, "
        "avant, propose_par) VALUES(?,?,?,?,?,?,?)",
        (nature, object_type, object_id, entity_id,
         json.dumps(charge, ensure_ascii=False), json.dumps(avant, ensure_ascii=False),
         user["id"])).lastrowid
    conn.execute(
        "INSERT INTO audit_log(user_id, entity_id, table_name, action, field, new_value) "
        "VALUES(?,?,?,?,?,?)",
        (user["id"], entity_id, "propositions", "proposer", f"proposition/{pid}",
         json.dumps(charge, ensure_ascii=False)[:4000]))
    return pid


def _ligne(r) -> dict:
    d = dict(r)
    for cle in ("charge", "avant"):
        try:
            d[cle] = json.loads(d[cle]) if d[cle] else {}
        except json.JSONDecodeError:
            d[cle] = {}
    return d


_SELECTION = """
    SELECT p.id, p.nature, p.object_type, p.object_id, p.entity_id, p.charge, p.avant,
           p.propose_par AS propose_par_id, up.email AS propose_par, p.propose_le,
           p.etat, ut.email AS tranche_par, p.tranche_le, p.motif,
           e.name AS fiche
    FROM propositions p
    LEFT JOIN users up   ON up.id = p.propose_par
    LEFT JOIN users ut   ON ut.id = p.tranche_par
    LEFT JOIN entities e ON e.id = p.entity_id
"""


def lire(conn, proposition_id: int) -> Optional[dict]:
    r = conn.execute(_SELECTION + " WHERE p.id=?", (proposition_id,)).fetchone()
    return _ligne(r) if r else None


def lister(conn, etat: str = "en_attente", auteur_id: Optional[int] = None,
           limit: int = 200) -> list[dict]:
    """Les plus anciennes d'abord : c'est une file. `auteur_id` restreint à
    celles d'un compte — un contributeur ne voit que les siennes."""
    sql, params = _SELECTION + " WHERE p.etat=?", [etat]
    if auteur_id is not None:
        sql += " AND p.propose_par=?"
        params.append(auteur_id)
    return [_ligne(r) for r in conn.execute(sql + " ORDER BY p.id LIMIT ?", params + [limit])]


def clore(conn, proposition_id: int, etat: str, user: dict, motif: str = "") -> None:
    conn.execute(
        "UPDATE propositions SET etat=?, tranche_par=?, tranche_le=datetime('now'), motif=? "
        "WHERE id=?", (etat, user["id"], (motif or "").strip()[:1000] or None, proposition_id))
    conn.execute(
        "INSERT INTO audit_log(user_id, entity_id, table_name, action, field, new_value) "
        "SELECT ?, entity_id, 'propositions', ?, 'proposition/' || id, ? "
        "FROM propositions WHERE id=?",
        (user["id"], etat, (motif or "").strip()[:1000] or None, proposition_id))
