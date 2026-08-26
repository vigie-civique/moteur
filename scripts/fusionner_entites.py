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

import difflib
import json
import re
import sqlite3
import unicodedata
from pathlib import Path

# Racine de l'instance : ce module vit dans `<instance>/scripts/`.
RACINE = Path(__file__).resolve().parent.parent
FICHIER_ARBITRAGES = "config/arbitrages_entites.json"

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

# Mots qui disent la FORME d'une structure, jamais laquelle. « SARL ET 7 » et
# « SARL R.D.P. » se réduisent tous deux à {sarl} : les initiales tombent
# (un caractère), « et » est un mot vide, le chiffre aussi. Deux sociétés sans
# rapport se retrouvaient dans la même grappe — sauvées ici par leurs SIREN
# distincts, mais rien ne garantit que deux fiches sans identifiant le soient.
#
# Une grappe dont TOUS les jetons sont dans cette liste n'est pas une
# ressemblance de nom : c'est une absence de nom. Elle sort en arbitrage.
_FORMES = {
    "sarl", "sas", "sasu", "eurl", "sci", "scp", "scm", "scop", "scic", "sci",
    "sa", "snc", "sca", "sem", "gaec", "earl", "gfa", "gie", "asa", "asl",
    "association", "societe", "groupement", "ets", "etablissements", "cabinet",
    "entreprise", "compagnie", "cie", "syndicat", "amicale", "comite", "club",
    "union", "federation", "collectif", "atelier", "maison", "residence",
}


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


# ── Arbitrages déclarés ─────────────────────────────────────────────────────

def cle_arbitrage(conn, eid: int) -> str:
    """Clé STABLE d'une fiche, pour qu'un arbitrage survive à une recollecte.

    Un `id` est un compteur local : une décision écrite « garder #4304 et #4458
    distincts » ne désigne plus rien après une base reconstruite. La clé vient
    donc de la SOURCE — SIREN, numéro RNA, identifiant OSM — et ne retombe sur
    le nom que lorsqu'aucun registre ne nomme la chose. Même esprit que
    `scripts/decisions.py`, dont c'est déjà le principe.
    """
    idt = identifiants(conn, eid)
    if idt["rna"]:
        return f"rna:{idt['rna']}"
    if idt["siren"]:
        return f"siren:{idt['siren']}"
    if _existe(conn, "places"):
        r = conn.execute("SELECT osm_id FROM places WHERE entity_id=?", (eid,)).fetchone()
        if r and r["osm_id"]:
            return f"osm:{r['osm_id']}"
    r = conn.execute("SELECT type, name_norm, commune FROM entities WHERE id=?",
                     (eid,)).fetchone()
    if r is None:
        return f"inconnu:{eid}"
    return f"nom:{r['type']}:{r['name_norm']}:{(r['commune'] or '').lower()}"


def arbitrages_declares(racine: Path | str | None = None) -> list[set[str]]:
    """Les grappes qu'un humain a déjà tranchées : « ces fiches restent distinctes ».

    Sans ça, l'arbitrage s'évapore : la détection les reproposerait à chaque
    passage, et la personne qui reprend le dossier referait le même travail
    sans savoir qu'il a été fait.
    """
    chemin = Path(racine or RACINE) / FICHIER_ARBITRAGES
    try:
        données = json.loads(chemin.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return []
    return [set(e.get("cles") or []) for e in (données.get("distinctes") or [])]


# ── Grappes de doublons ──────────────────────────────────────────────────────

def grappes(conn, types=("association", "business", "service", "place"),
            racine: Path | str | None = None) -> list[dict]:
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

    declares = arbitrages_declares(racine)
    out = []
    for (_, _), membres in par_cle.items():
        if len(membres) < 2:
            continue
        # Une grappe déjà tranchée ne revient pas : elle est arbitrée dès que
        # TOUTES ses fiches sont couvertes par une même déclaration. Un membre
        # nouveau la fait ressortir — c'est voulu, il n'a pas été arbitré.
        cles = {cle_arbitrage(conn, m["id"]) for m in membres}
        if any(cles <= d for d in declares):
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
        elif cles_generiques(membres):
            obstacle = ("le nom ne porte que des mots de forme "
                        "(SARL, SCI…) — ce n'est pas une ressemblance de nom")
        elif "place" in types_presents and len(types_presents) > 1:
            # Un point OSM qui porte le nom d'une association peut être le local
            # qu'elle occupe — et un local peut en abriter plusieurs. Le nom ne
            # tranche pas : celui-là se regarde.
            obstacle = "un lieu et une structure portent le même nom"
        out.append({"membres": membres, "identifiants": idts, "obstacle": obstacle})
    return out


def cles_generiques(membres: list[dict]) -> bool:
    """La grappe ne tient-elle QUE sur des mots de forme juridique ?

    « SARL ET 7 » et « SARL R.D.P. » se réduisent l'un et l'autre à {sarl} :
    les initiales tombent (un caractère), « et » est un mot vide, le chiffre
    aussi. Ce n'est pas la même société — c'est le même statut.
    """
    for m in membres:
        t = jeton(m.get("name") or "")
        if t and not t <= _FORMES:
            return False
    return True


# ── Rapprochement APPROCHANT ─────────────────────────────────────────────────
#
# `grappes()` ne voit que l'identité exacte des jetons. « Caravane Film » et
# « LA CARAVANE FILME » lui échappent deux fois : `film` et `filme` diffèrent
# d'une lettre, et l'une des deux fiches n'a AUCUNE commune (périmètre `lien`).
# Elles portaient pourtant 360 € et 450 € de subventions de la même commune,
# à la même association — le partage d'argent qu'on avait vu sur Vivalto.
#
# Même chose pour les 59 fiches dont la collision `rna_id UNIQUE` a mangé
# l'identité : 22 ont une jumelle séparée par une variante d'écriture
# (SALENDRINQUE/SALINDRENQUE, AUMOMERIE/AUMONERIE).
#
# CE MODULE PROPOSE, IL NE FUSIONNE PAS. À 0,80 de similarité on est déjà dans
# le domaine où deux amicales de villages voisins se ressemblent : la décision
# reste humaine, et se déclare comme les autres.

#: En dessous, une ressemblance ne prouve rien : « MC » et « MCI » font 0,80.
LONGUEUR_MINIMALE = 6


def _cle_comparaison(nom: str) -> str:
    """Les jetons triés, recollés. Compare des MOTS, pas un ordre d'écriture.

    « LAFONT CEDRIC » et « CEDRIC LAFONT » sont la même chaîne une fois triée —
    ce qui est le but : l'inversion nom/prénom est la variante la plus fréquente
    du répertoire des entreprises.
    """
    return " ".join(sorted(jeton(nom)))


def similarite(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _cle_comparaison(a), _cle_comparaison(b)).ratio()


def _nombres(nom: str) -> frozenset[str]:
    """Tous les groupes de chiffres du nom BRUT.

    Pas ceux de `jeton()` : il écarte les mots d'un seul caractère, donc « 1 »
    et « 7 » — exactement les chiffres qui distinguent « KERGREEN 1 » de
    « KERGREEN 7 ». Le filtre qui protège des initiales aveuglait celui-ci.
    """
    return frozenset(re.findall(r"\d+", nom or ""))


def nombres_differents(a: str, b: str) -> bool:
    """Un NOMBRE dans un nom sert à distinguer, pas à décrire.

    « Tente canadienne n°60 » et « n°61 » sont deux tentes ; « KERGREEN 1 » et
    « KERGREEN 7 » deux sociétés de projet ; « Drôme Agri Solaire » et « Drôme
    Agri Solaire 1 » deux sociétés. Sur la similarité de chaîne, ces paires
    frôlent 0,95 — c'est précisément le chiffre qui les sépare, et il pèse un
    caractère.
    """
    na, nb = _nombres(a), _nombres(b)
    return bool(na or nb) and na != nb


def _communes_compatibles(a: str | None, b: str | None) -> bool:
    """Une fiche SANS commune ne contredit personne.

    C'est le cas des entités nées d'un compte rendu : la source les nomme, elle
    ne les situe pas. Exiger l'égalité stricte les excluait toutes du
    rapprochement, précisément celles qui en ont le plus besoin.
    """
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    return not a or not b or a == b


def rapprochements(conn, seuil: float = 0.80,
                   types=("association", "business", "service", "place"),
                   racine=None) -> list[dict]:
    """Paires de fiches qui se ressemblent sans être identiques.

    Écarte ce qu'on sait déjà : identité exacte (c'est le travail de
    `grappes()`), identifiants nationaux distincts, et paires déjà déclarées
    distinctes par un humain.
    """
    lignes = [dict(r) for r in conn.execute(
        "SELECT id, name, type, commune FROM entities"
        f" WHERE type IN ({','.join('?' * len(types))})", types)]
    for r in lignes:
        r["_cle"] = _cle_comparaison(r["name"])
        r["_idt"] = identifiants(conn, r["id"])

    declares = arbitrages_declares(racine)
    trouves = []
    for i, a in enumerate(lignes):
        if len(a["_cle"]) < LONGUEUR_MINIMALE:
            continue
        for b in lignes[i + 1:]:
            if len(b["_cle"]) < LONGUEUR_MINIMALE or a["_cle"] == b["_cle"]:
                continue
            if not _communes_compatibles(a["commune"], b["commune"]):
                continue
            score = difflib.SequenceMatcher(None, a["_cle"], b["_cle"]).ratio()
            if score < seuil:
                continue
            if nombres_differents(a["name"], b["name"]):
                continue
            rna = {x["_idt"]["rna"] for x in (a, b) if x["_idt"]["rna"]}
            siren = {x["_idt"]["siren"] for x in (a, b) if x["_idt"]["siren"]}
            if len(rna) > 1 or len(siren) > 1:
                continue          # deux personnes morales, la question est close
            cles = {cle_arbitrage(conn, a["id"]), cle_arbitrage(conn, b["id"])}
            if any(cles <= d for d in declares):
                continue
            trouves.append({"score": score, "membres": [a, b]})
    trouves.sort(key=lambda t: -t["score"])
    return trouves


def ouvrir(chemin) -> sqlite3.Connection:
    conn = sqlite3.connect(str(chemin))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
