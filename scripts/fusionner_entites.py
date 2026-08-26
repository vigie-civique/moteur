"""Fusionner deux fiches qui désignent la même structure.

Une fusion n'est pas une suppression : tout ce qui pendait à la fiche absorbée
— subventions, baux, marchés, relations, délibérations, sites, notes — est
reporté sur la fiche gardée AVANT qu'elle disparaisse. Une subvention perdue en
route serait pire que le doublon qu'on corrige.

Les colonnes à reporter sont LUES DANS LE SCHÉMA (`PRAGMA foreign_key_list`),
jamais recopiées ici : une table ajoutée demain sera reprise sans qu'on y pense.
Deux exceptions, déclarées plus bas, parce qu'aucune clé étrangère ne les
signale : `feed_items.entity_ids` est un tableau JSON, et les tables
d'extension (`businesses`, `associations`…) se fusionnent champ par champ au
lieu de se déplacer.

Sous `UPDATE OR IGNORE`, une ligne qui violerait une contrainte d'unicité après
report (la même relation existe déjà des deux côtés) reste sur l'absorbée et
part avec elle. C'est voulu : c'est un doublon, pas une perte.
"""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata

# Tables dont la clé primaire EST l'entité : elles ne se déplacent pas, elles
# se complètent — la fiche gardée garde ce qu'elle sait, et hérite du reste.
EXTENSIONS = ("persons", "businesses", "associations", "services", "places",
              "entity_enrichment")

# Un identifiant national, opposable. `W303001619` en est un ; `ASS00786`, que
# le Journal officiel met dans le même champ pour les dossiers antérieurs au
# RNA, n'en est pas un — c'est un numéro d'annonce, il change d'une parution à
# l'autre pour la même association. Confondre les deux, c'est croire à deux
# structures là où il n'y en a qu'une.
RNA_FORT = re.compile(r"^W\d{9}$")

_STOP = {"de", "du", "des", "d", "la", "le", "les", "l", "et", "en", "a", "au",
         "aux", "pour", "sur", "the", "of"}


def jeton(nom: str) -> frozenset[str]:
    """Jeu de mots normalisé — apostrophes SOUDÉES, pas découpées.

    « VIV'ALTO » et « VIVALTO » sont la même association. Découper sur
    l'apostrophe donnerait {viv, alto} et ne les réunirait jamais.
    """
    s = re.sub(r"[’'`]", "", nom or "")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", " ", s).lower()
    return frozenset(t for t in s.split() if len(t) > 1 and t not in _STOP)


# ── Lecture du schéma ────────────────────────────────────────────────────────

def colonnes_referencant_entities(conn) -> list[tuple[str, str]]:
    """(table, colonne) de tout ce qui pointe vers `entities`, hors extensions."""
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
        " AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%_fts%'")]
    trouve = []
    for t in tables:
        if t in EXTENSIONS:
            continue
        for fk in conn.execute(f"PRAGMA foreign_key_list({t})"):
            if fk["table"] == "entities":
                trouve.append((t, fk["from"]))
    return sorted(set(trouve))


def _colonnes(conn, table: str) -> list[str]:
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]


def _existe(conn, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,)).fetchone() is not None


# ── Identité d'une fiche ─────────────────────────────────────────────────────

def identifiants(conn, eid: int) -> dict:
    """Ce qui rattache la fiche à un registre national."""
    out = {"rna": None, "siren": None}
    if _existe(conn, "associations"):
        r = conn.execute("SELECT rna_id, siren FROM associations WHERE entity_id=?",
                         (eid,)).fetchone()
        if r:
            if r["rna_id"] and RNA_FORT.match(r["rna_id"]):
                out["rna"] = r["rna_id"]
            if r["siren"]:
                out["siren"] = r["siren"]
    if _existe(conn, "businesses"):
        r = conn.execute("SELECT siren FROM businesses WHERE entity_id=?",
                         (eid,)).fetchone()
        if r and r["siren"]:
            out["siren"] = out["siren"] or r["siren"]
    return out


def attaches(conn, eid: int) -> int:
    """Combien de choses pendent à cette fiche — sert à départager, pas à trier."""
    n = 0
    for table, col in colonnes_referencant_entities(conn):
        n += conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {col}=?", (eid,)).fetchone()[0]
    return n


def choisir_garde(conn, ids: list[int]) -> int:
    """La fiche qui survit : celle qu'un registre identifie, puis la mieux fournie.

    Un identifiant national l'emporte sur le nombre de rattachements : une fiche
    née d'un compte rendu peut porter six subventions sans qu'on sache de QUI
    elle parle — les subventions se déplacent, l'identité non.
    """
    def cle(eid: int):
        idt = identifiants(conn, eid)
        return (bool(idt["rna"]), bool(idt["siren"]), attaches(conn, eid), -eid)
    return max(ids, key=cle)


# ── La fusion ────────────────────────────────────────────────────────────────

def fusionner(conn, garde: int, absorbe: int) -> dict:
    """Reporte tout d'`absorbe` vers `garde`, puis supprime `absorbe`.

    Rend le détail de ce qui a bougé — un compte par table, pour qu'un journal
    de fusion se relise sans rouvrir la base.
    """
    if garde == absorbe:
        raise ValueError("fusionner une fiche avec elle-même")
    for eid in (garde, absorbe):
        if conn.execute("SELECT 1 FROM entities WHERE id=?", (eid,)).fetchone() is None:
            raise ValueError(f"entité {eid} absente")

    bouge: dict[str, int] = {}

    # 1. Extensions : compléter, ne jamais écraser.
    for table in EXTENSIONS:
        if not _existe(conn, table):
            continue
        src = conn.execute(f"SELECT * FROM {table} WHERE entity_id=?",
                           (absorbe,)).fetchone()
        if src is None:
            continue
        dst = conn.execute(f"SELECT * FROM {table} WHERE entity_id=?",
                           (garde,)).fetchone()
        if dst is None:
            conn.execute(f"UPDATE OR IGNORE {table} SET entity_id=? WHERE entity_id=?",
                         (garde, absorbe))
            bouge[table] = bouge.get(table, 0) + 1
            conn.execute(f"DELETE FROM {table} WHERE entity_id=?", (absorbe,))
        else:
            vides = [c for c in _colonnes(conn, table)
                     if c != "entity_id" and not dst[c] and src[c]]
            # La ligne absorbée part AVANT que ses valeurs soient recopiées :
            # `rna_id` est UNIQUE, et le temps d'un UPDATE les deux fiches
            # porteraient le même identifiant. `src` est déjà en mémoire.
            conn.execute(f"DELETE FROM {table} WHERE entity_id=?", (absorbe,))
            if vides:
                conn.execute(
                    f"UPDATE {table} SET {','.join(f'{c}=?' for c in vides)}"
                    f" WHERE entity_id=?", (*[src[c] for c in vides], garde))
                bouge[f"{table} (champs)"] = len(vides)

    # 2. Tout le reste : reporter la référence.
    for table, col in colonnes_referencant_entities(conn):
        n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {col}=?",
                         (absorbe,)).fetchone()[0]
        if not n:
            continue
        conn.execute(f"UPDATE OR IGNORE {table} SET {col}=? WHERE {col}=?",
                     (garde, absorbe))
        reste = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {col}=?",
                             (absorbe,)).fetchone()[0]
        bouge[f"{table}.{col}"] = n - reste
        if reste:
            bouge[f"{table}.{col} (doublon écarté)"] = reste

    # 3. Une relation ne relie plus une fiche à elle-même. « X dirige X » n'est
    #    pas une information, c'est une trace de la fusion.
    for table in ("relations", "relation_candidates"):
        if _existe(conn, table):
            n = conn.execute(f"DELETE FROM {table} WHERE from_id=? AND to_id=?",
                             (garde, garde)).rowcount
            if n:
                bouge[f"{table} (boucle sur soi)"] = n

    # 4. `feed_items.entity_ids` est un tableau JSON : aucune clé étrangère ne
    #    le signale, et il resterait à pointer une entité supprimée.
    if _existe(conn, "feed_items"):
        n = 0
        for r in conn.execute(
                "SELECT id, entity_ids FROM feed_items WHERE entity_ids IS NOT NULL"):
            try:
                ids = json.loads(r["entity_ids"])
            except (ValueError, TypeError):
                continue
            if not isinstance(ids, list) or absorbe not in ids:
                continue
            neufs = sorted({garde if i == absorbe else i for i in ids})
            conn.execute("UPDATE feed_items SET entity_ids=? WHERE id=?",
                         (json.dumps(neufs), r["id"]))
            n += 1
        if n:
            bouge["feed_items.entity_ids"] = n

    # 5. L'entité gardée hérite des cases qu'elle n'avait pas remplies.
    src = conn.execute("SELECT * FROM entities WHERE id=?", (absorbe,)).fetchone()
    dst = conn.execute("SELECT * FROM entities WHERE id=?", (garde,)).fetchone()
    heritables = ("short_name", "lat", "lng", "address", "commune",
                  "geocode_source", "x_l93", "y_l93", "geocode_score")
    vides = [c for c in heritables
             if c in dst.keys() and not dst[c] and src[c]]
    if vides:
        conn.execute(f"UPDATE entities SET {','.join(f'{c}=?' for c in vides)}"
                     f" WHERE id=?", (*[src[c] for c in vides], garde))
        bouge["entities (champs hérités)"] = len(vides)

    conn.execute("DELETE FROM entities WHERE id=?", (absorbe,))
    bouge["entité supprimée"] = absorbe
    return bouge


# ── Grappes de doublons ──────────────────────────────────────────────────────

def grappes(conn, types=("association", "business", "service", "place")) -> list[dict]:
    """Fiches de même nom normalisé, groupées, avec ce qui empêche de les fusionner.

    Les personnes sont hors sujet : « ALAIN ANDRE » l'entreprise et « Alain
    ANDRE » la personne portent le même nom parce que c'est une entreprise
    individuelle. Ce sont deux choses différentes, pas un doublon.
    """
    par_cle: dict[tuple, list] = {}
    for r in conn.execute(
            "SELECT id, name, type, commune FROM entities"
            f" WHERE type IN ({','.join('?' * len(types))})", types):
        t = jeton(r["name"])
        if t:
            par_cle.setdefault((t, (r["commune"] or "").strip().lower()), []).append(dict(r))

    out = []
    for (_, _), membres in par_cle.items():
        if len(membres) < 2:
            continue
        idts = [identifiants(conn, m["id"]) for m in membres]
        rna = {i["rna"] for i in idts if i["rna"]}
        siren = {i["siren"] for i in idts if i["siren"]}
        types_presents = {m["type"] for m in membres}
        obstacle = None
        if len(rna) > 1:
            obstacle = f"deux identifiants RNA distincts ({', '.join(sorted(rna))})"
        elif len(siren) > 1:
            obstacle = f"deux SIREN distincts ({', '.join(sorted(siren))})"
        elif "place" in types_presents and len(types_presents) > 1:
            # Un point OSM qui porte le nom d'une association peut être le local
            # qu'elle occupe — et un local peut en abriter plusieurs. Le nom ne
            # tranche pas : celui-là se regarde.
            obstacle = "un lieu et une structure portent le même nom"
        out.append({"membres": membres, "identifiants": idts, "obstacle": obstacle})
    return out


def ouvrir(chemin) -> sqlite3.Connection:
    conn = sqlite3.connect(str(chemin))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
