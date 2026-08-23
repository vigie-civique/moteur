"""Helpers SQLite — connexion, init, upsert."""
import sqlite3
import contextlib
from .config import DB_PATH, SCHEMA_PATH
from .nom_normalise import normaliser, rectifier, reparer_encodage


def get_conn(read_only: bool = False) -> sqlite3.Connection:
    """
    Connexion SQLite.
    - read_only=True  → mode ro (query_only, pas de busy_timeout requis)
    - read_only=False → écriture WAL, busy_timeout=5000 ms (anti-SQLITE_BUSY collaboratif)
    """
    if read_only:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


@contextlib.contextmanager
def transaction():
    """Context manager : connexion + commit/rollback automatique."""
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# Colonnes ajoutées après coup. `CREATE TABLE IF NOT EXISTS` ne touche pas une
# table qui existe déjà : sans ce rattrapage, une base collectée avant l'ajout
# reste sans la colonne, et le code qui la lit échoue sur une base ancienne
# alors qu'il marche sur une base neuve. En attendant des migrations
# versionnées, la liste ci-dessous est le rattrapage minimal — chaque entrée
# est jouée une fois, et ne fait rien si la colonne est déjà là.
_COLONNES_AJOUTEES = [
    ("marches_publics", "confidence",
     "TEXT DEFAULT 'verified'"),   # 20/08/2026 — acheteur non établi = probable

    # 20/08/2026 — huit colonnes que le CODE utilisait sans que le SCHÉMA les
    # déclare. Elles existaient dans la base historique et n'avaient jamais été
    # reportées : toute instance créée par le moteur naissait sans elles, et la
    # file de revue de l'atelier échouait sur « no such column:
    # validation_status ». Le défaut était masqué parce que la seule instance
    # qu'on ouvrait régulièrement avait une base venue de la production.
    ("entities", "validation_status", "TEXT DEFAULT 'unverified'"),
    ("entities", "responsible",       "TEXT"),
    ("entities", "x_l93",             "REAL"),
    ("entities", "y_l93",             "REAL"),
    ("entities", "geocode_score",     "REAL"),
    ("annotations", "corrections",    "TEXT"),
    ("businesses", "pappers_fetched_at", "TEXT"),
    ("businesses", "pappers_raw",     "TEXT"),
    ("associations", "siren",         "TEXT"),

    # 20/08/2026 — `origine` : qui a structuré la donnée de cette ligne, et donc
    # ce qu'un humain a le droit d'en faire. Cf. collectors/origine.py. Ajoutée
    # SANS valeur par défaut : une ligne non classée doit se voir, pas se fondre
    # dans une catégorie choisie par le schéma. `scripts/classer_origine.py` la
    # remplit, et refuse de deviner ce qu'il ne reconnaît pas.
    ("events",               "origine", "TEXT"),
    ("financial_flows",      "origine", "TEXT"),
    ("marches_publics",      "origine", "TEXT"),
    ("budget_vote",          "origine", "TEXT"),
    ("dotations_etat",       "origine", "TEXT"),
    ("approbations_projets", "origine", "TEXT"),

    # Le document local qui porte la ligne. Sur les tables issues de lecture, il
    # y a presque toujours un PDF ou un HTML dans `raw_documents` derrière —
    # mais le lien n'existait que par comparaison d'URL, ce qui casse dès qu'une
    # source republie sous une autre adresse. Une saisie manuelle, elle, ne
    # s'enregistre pas sans lui.
    ("events",               "raw_document_id", "INTEGER REFERENCES raw_documents(id)"),
    ("financial_flows",      "raw_document_id", "INTEGER REFERENCES raw_documents(id)"),
    ("marches_publics",      "raw_document_id", "INTEGER REFERENCES raw_documents(id)"),
    ("budget_vote",          "raw_document_id", "INTEGER REFERENCES raw_documents(id)"),
    ("dotations_etat",       "raw_document_id", "INTEGER REFERENCES raw_documents(id)"),
    ("approbations_projets", "raw_document_id", "INTEGER REFERENCES raw_documents(id)"),

    # Qui a saisi, et quand. Vides sur tout ce qu'un collecteur a écrit : c'est
    # la signature du travail humain, celle qui part dans l'export de décisions.
    ("events",               "saisi_par", "TEXT"),
    ("financial_flows",      "saisi_par", "TEXT"),
    ("marches_publics",      "saisi_par", "TEXT"),
    ("budget_vote",          "saisi_par", "TEXT"),
    ("dotations_etat",       "saisi_par", "TEXT"),
    ("approbations_projets", "saisi_par", "TEXT"),
    ("events",               "saisi_le", "TEXT"),
    ("financial_flows",      "saisi_le", "TEXT"),
    ("marches_publics",      "saisi_le", "TEXT"),
    ("budget_vote",          "saisi_le", "TEXT"),
    ("dotations_etat",       "saisi_le", "TEXT"),
    ("approbations_projets", "saisi_le", "TEXT"),
]


# Index portant sur une colonne rattrapée. Ils ne peuvent PAS vivre dans
# `db/schema.sql` : celui-ci est joué en entier AVANT `_rattraper_colonnes`, donc
# sur une base antérieure à l'ajout de la colonne, `init_db()` échouerait sur
# « no such column » — et échouerait entièrement, laissant la base à moitié
# migrée. Même raison d'être que la liste ci-dessus, même dette : des migrations
# versionnées rendraient les deux inutiles.
_INDEX_AJOUTES = [
    ("idx_events_origine",  "events",          "origine"),
    ("idx_flows_origine",   "financial_flows", "origine"),
    ("idx_marches_origine", "marches_publics", "origine"),
]


def _rattraper_index(conn) -> None:
    for nom, table, colonnes in _INDEX_AJOUTES:
        existe = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,)).fetchone()
        if not existe:
            continue
        presentes = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if not set(c.strip() for c in colonnes.split(",")) <= presentes:
            continue
        conn.execute(f"CREATE INDEX IF NOT EXISTS {nom} ON {table}({colonnes})")


def _rattraper_colonnes(conn) -> None:
    for table, colonne, definition in _COLONNES_AJOUTEES:
        existe = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,)).fetchone()
        if not existe:
            continue
        colonnes = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if colonne in colonnes:
            continue
        # La contrainte CHECK n'est pas reprise ici : SQLite ne sait pas
        # l'ajouter par ALTER TABLE. Elle vaut pour les bases neuves, et le code
        # qui écrit n'utilise que les valeurs autorisées.
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {colonne} {definition}")
        print(f"[db] colonne ajoutée : {table}.{colonne}")


def init_db():
    """Crée le schéma si absent, et rattrape les colonnes ajoutées depuis."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    schema = SCHEMA_PATH.read_text()
    conn = get_conn()
    try:
        conn.executescript(schema)
        _rattraper_colonnes(conn)
        _rattraper_index(conn)
        conn.commit()
        print(f"[db] Schéma initialisé → {DB_PATH}")
    finally:
        conn.close()


# ----------------------------------------------------------------
# Helpers d'insertion
# ----------------------------------------------------------------

def _entite_existante(conn, type_, name, commune):
    """Retrouve une entité déjà en base malgré une variante d'écriture.

    Trois passes, de la plus sûre à la plus permissive :
      1. nom EXACT — comportement historique, inchangé ;
      2. nom NORMALISÉ dans la MÊME commune — c'est le cas des accents
         (« Frédéric VERGNAUD » / « Frederic VERGNAUD »), qui sont toujours deux
         écritures d'un même acteur d'une même commune ;
      3. nom normalisé, appelant sans commune, et un seul candidat en base.

    La commune est une condition NÉCESSAIRE, et c'est le point délicat : un
    index unique sur le seul nom normalisé aurait été un bug. « CENTRE COMMUNAL
    D'ACTION SOCIALE (CCAS) » existe à Lasalle (SIREN 263000598) ET à
    Saint-André-de-Valborgne (SIREN 263000994) : ce sont deux personnes morales
    distinctes qui ne diffèrent que par une apostrophe de saisie. Les fondre
    aurait rattaché le CCAS d'une commune aux données de l'autre.

    En contrepartie, deux fiches d'un même acteur rattachées à deux communes
    différentes ne sont pas réunies ici — c'est structurel : pour un dirigeant
    SIRENE, `commune` est celle de son entreprise, pas son domicile. Ces cas-là
    relèvent de `qa_loop` (check `duplicate_name`) et d'un arbitrage humain sur
    la date de naissance, pas d'une règle automatique.
    """
    exact = conn.execute(
        "SELECT id,lat,lng,address,commune FROM entities WHERE type=? AND name=?",
        (type_, name)).fetchone()
    if exact:
        return exact

    candidats = conn.execute(
        "SELECT id,lat,lng,address,commune,name FROM entities"
        " WHERE type=? AND name_norm=? ORDER BY id",
        (type_, normaliser(name))).fetchall()
    if not candidats:
        return None
    if commune:
        for c in candidats:
            if c["commune"] == commune:
                return c
        return None
    return candidats[0] if len(candidats) == 1 else None


def upsert_entity(conn, *, type, name, short_name=None,
                  lat=None, lng=None, address=None,
                  confidence="verified", commune=None) -> int:
    """
    Retourne l'id de l'entité, créée si elle n'existe pas.
    La recherche tolère les variantes d'écriture (accents, tirets, casse) au
    sein d'une même commune — cf. `_entite_existante`.
    Si l'entité existe, met à jour lat/lng/address (+ commune si encore vide) si fournis.

    commune : tag de rattachement géographique. **Toujours le passer.** Sans lui,
    l'entité vaut NULL et `migrate_perimetre.py` la classera `hors` ou `C3` — ce
    qui est la vérité quand on ne sait pas, et se voit. Jusqu'au 12/08/2026 le
    schéma portait `DEFAULT 'Lasalle'` : une entité sans commune naissait
    lasalloise, et comme le tag n'est jamais écrasé, la corriger après coup ne
    faisait rien. Trois incidents en sont sortis, cf.
    d'une migration ponctuelle, non versionnée.
    """
    # Les rectifications déclarées s'appliquent ICI, et nulle part ailleurs :
    # c'est le seul point par lequel passent toutes les fiches, de tous les
    # collecteurs. Déclarée une fois, une rectification vaut donc pour SIRENE,
    # le RNA, OSM et les saisies — et ne peut plus être défaite par une
    # recollecte. Liste vide par défaut : une instance qui n'en déclare pas ne
    # voit aucune différence.
    # L'encodage se répare AVANT la rectification déclarée : une entrée de la
    # liste s'écrit dans la langue de la source, pas dans son mojibake, et
    # « L'EUZIAÈRE » ne rejoindrait jamais « L'EUZIÈRE » sans ça. Réparer ici
    # vaut aussi pour la déduplication : deux graphies d'un même nom, dont une
    # abîmée, faisaient deux fiches.
    name = rectifier(reparer_encodage(name))
    address = rectifier(reparer_encodage(address))

    row = _entite_existante(conn, type, name, commune)
    if row is None:
        # Colonne toujours écrite, même à NULL : plus aucun défaut implicite ne
        # peut se glisser entre le collecteur et la base.
        conn.execute(
            "INSERT OR IGNORE INTO entities"
            " (type,name,name_norm,short_name,lat,lng,address,confidence,commune)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (type, name, normaliser(name), short_name, lat, lng, address,
             confidence, commune)
        )
        # Toujours SELECT — lastrowid est stale quand INSERT est ignoré
        row = conn.execute(
            "SELECT id,lat,lng,address,commune FROM entities WHERE type=? AND name=?",
            (type, name)
        ).fetchone()
    eid = row["id"]
    updates, vals = [], []
    if lat is not None and row["lat"] is None:
        updates.append("lat=?"); vals.append(lat)
    if lng is not None and row["lng"] is None:
        updates.append("lng=?"); vals.append(lng)
    if address and not row["address"]:
        updates.append("address=?"); vals.append(address)
    # Ne corrige la commune que si elle est vide (ne jamais écraser un tag existant)
    if commune and not row["commune"]:
        updates.append("commune=?"); vals.append(commune)
    if updates:
        vals.append(eid)
        conn.execute(
            f"UPDATE entities SET {','.join(updates)}, updated_at=datetime('now')"
            " WHERE id=?", vals
        )
    return eid


def upsert_relation(conn, from_id, to_id, rel_type,
                    source, since=None, until=None,
                    confidence="verified", metadata=None):
    conn.execute(
        "INSERT OR IGNORE INTO relations"
        " (from_id,to_id,relation_type,source,since,until,confidence,metadata)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (from_id, to_id, rel_type, source, since, until, confidence, metadata)
    )


def upsert_person(conn, *, firstname, lastname,
                  birth_year=None, birth_month=None,
                  confidence="verified") -> int:
    name = f"{firstname} {lastname}".strip() if firstname else lastname
    eid = upsert_entity(conn, type="person", name=name, confidence=confidence)
    conn.execute(
        "INSERT OR IGNORE INTO persons (entity_id,firstname,lastname,birth_year,birth_month)"
        " VALUES (?,?,?,?,?)",
        (eid, firstname, lastname, birth_year, birth_month)
    )
    return eid


def log_run_start(conn, collector: str, items_before: int | None) -> int:
    """Ouvre une ligne collector_runs et retourne son id.

    Toute exécution de collecteur doit être journalisée, quel que soit le
    chemin d'appel (run_all en cron mensuel, collect_loop en pipeline, appel
    manuel). Sans ça, une source morte ne produit aucun signal : DECP est resté
    figé 577 jours et `api-dvf.cerema.fr` répond NXDOMAIN depuis des mois sans
    que rien ne le remonte. `scripts/qa_loop.py::check_silent_source` s'appuie
    sur cette table.
    """
    cur = conn.execute(
        "INSERT INTO collector_runs (collector, items_before) VALUES (?,?)",
        (collector, items_before),
    )
    conn.commit()
    return cur.lastrowid


def log_run_end(conn, run_id: int, status: str,
                items_after: int | None, items_before: int | None,
                error: str | None = None) -> None:
    """Clôt la ligne collector_runs. status ∈ ok | empty | error | timeout."""
    added = (items_after - items_before) if (
        items_after is not None and items_before is not None) else None
    if status == "ok" and added == 0:
        status = "empty"
    conn.execute(
        "UPDATE collector_runs SET finished_at=datetime('now'), status=?,"
        " items_after=?, items_added=?, error=? WHERE id=?",
        (status, items_after, added, error, run_id),
    )
    conn.commit()


def stats(conn) -> dict:
    """Retourne les statistiques globales de la base."""
    row = conn.execute("SELECT * FROM v_stats").fetchone()
    return dict(row) if row else {}


def pivot_ids(conn) -> dict:
    """Identifiants des entités structurantes, créées si elles manquent.

    Quatre collecteurs portaient ces identifiants en dur (`COMMUNE_ID = 63`,
    `ETAT_ID = 2044`…) : c'étaient les numéros de ligne de la base de Lasalle.
    Rejoués sur une autre base, ils désignent n'importe quelle entité — un flux
    financier de l'État vers la commune devenait un flux entre deux entreprises
    prises au hasard, sans que rien ne signale l'erreur. On les résout donc par
    le nom, à l'exécution.
    """
    from .config import COMMUNE_NAME, DEPARTEMENT, EPCI_NOM, PREFECTURE_NOM
    return {
        "commune": upsert_entity(conn, type="service",
                                 name=f"Commune de {COMMUNE_NAME}",
                                 short_name=COMMUNE_NAME, commune=COMMUNE_NAME,
                                 confidence="verified"),
        "epci":    upsert_entity(conn, type="service", name=EPCI_NOM,
                                 confidence="verified"),
        "etat":    upsert_entity(conn, type="service", name="État français",
                                 confidence="verified"),
        "prefecture": upsert_entity(conn, type="service", name=PREFECTURE_NOM,
                                    confidence="verified"),
    }
