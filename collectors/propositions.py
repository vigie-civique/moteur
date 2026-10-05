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

Depuis le 04/10/2026, une proposition peut aussi porter une ligne EXTRAITE
d'un texte et qui n'est encore nulle part en base : un marché lu dans un
procès-verbal (`collectors/marches_extraits.py`). Elle ne vise alors pas un
objet publié mais l'acte d'où elle a été lue (`object_type = 'deliberation'`),
et sa `cle` — l'empreinte de la ligne — est ce qui empêche un rapport rejoué
d'empiler deux fois la même relecture.
"""
from __future__ import annotations

import json
from typing import Optional

#: Ce qu'une proposition peut porter, et l'objet qu'elle vise.
NATURES = ("fiche", "coords", "relation", "correction", "marche")
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
    motif        TEXT,
    cle          TEXT
)"""

#: Une ligne extraite ne se propose qu'une fois, quel que soit son sort : une
#: ligne écartée qu'un rapport rejoué ramènerait en attente ferait relire deux
#: fois ce qu'un validateur a déjà tranché.
INDEX_CLE = ("CREATE UNIQUE INDEX IF NOT EXISTS idx_propositions_cle "
             "ON propositions(nature, cle) WHERE cle IS NOT NULL")


def assurer_schema(conn) -> None:
    """L'API ne passe pas par `init_db()` : une base d'avant le 02/10/2026 n'a
    pas la table, et la première proposition y échouerait. Une base d'avant le
    04/10/2026 l'a sans `cle`."""
    conn.execute(SCHEMA)
    if "cle" not in {r[1] for r in conn.execute("PRAGMA table_info(propositions)")}:
        conn.execute("ALTER TABLE propositions ADD COLUMN cle TEXT")
    conn.execute(INDEX_CLE)


def proposer(conn, nature: str, object_type: str, object_id: int,
             entity_id: Optional[int], charge: dict, avant: dict, user: dict,
             cle: Optional[str] = None) -> int:
    """Enregistre la proposition et la journalise. Une proposition encore en
    attente du même auteur, sur le même objet et de même nature, est REMPLACÉE :
    corriger sa propre proposition ne doit pas en empiler deux à relire.

    Sauf quand elle porte une `cle` : plusieurs marchés se lisent dans le même
    acte, et le second ne remplace pas le premier. C'est alors la clé qui
    dédoublonne (cf. `INDEX_CLE`)."""
    if cle is None:
        conn.execute(
            "UPDATE propositions SET etat='retiree', tranche_le=datetime('now') "
            "WHERE etat='en_attente' AND nature=? AND object_type=? AND object_id=? "
            "AND propose_par=?", (nature, object_type, object_id, user["id"]))
    pid = conn.execute(
        "INSERT INTO propositions(nature, object_type, object_id, entity_id, charge, "
        "avant, propose_par, cle) VALUES(?,?,?,?,?,?,?,?)",
        (nature, object_type, object_id, entity_id,
         json.dumps(charge, ensure_ascii=False), json.dumps(avant, ensure_ascii=False),
         user["id"], cle)).lastrowid
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
           p.cle, e.name AS fiche
    FROM propositions p
    LEFT JOIN users up   ON up.id = p.propose_par
    LEFT JOIN users ut   ON ut.id = p.tranche_par
    LEFT JOIN entities e ON e.id = p.entity_id
"""


def lire(conn, proposition_id: int) -> Optional[dict]:
    r = conn.execute(_SELECTION + " WHERE p.id=?", (proposition_id,)).fetchone()
    return _ligne(r) if r else None


def lister(conn, etat: str = "en_attente", auteur_id: Optional[int] = None,
           limit: int = 200, nature: Optional[str] = None) -> list[dict]:
    """Les plus anciennes d'abord : c'est une file. `auteur_id` restreint à
    celles d'un compte — un contributeur ne voit que les siennes."""
    sql, params = _SELECTION + " WHERE p.etat=?", [etat]
    if auteur_id is not None:
        sql += " AND p.propose_par=?"
        params.append(auteur_id)
    if nature is not None:
        sql += " AND p.nature=?"
        params.append(nature)
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
