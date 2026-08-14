"""
urbanisme_sitadel.py — Autorisations d'urbanisme (Sitadel, SDES via API DIDO).

**Pourquoi.** Sur l'instance d'origine, la base ne comptait que 3 événements
`urbanisme` alors que le foncier était le sujet le plus sensible du territoire :
30,7 % de résidences secondaires, un marché DVF actif, un dossier déjà ouvert.
Le rapport vaut pour toute commune où la pression foncière existe.
Sitadel donne chaque permis depuis 2013, avec **la référence cadastrale** et
**le SIREN du demandeur** quand c'est une personne morale — donc deux
croisements exacts, sans rapprochement approximatif :

  - `SIREN_DEM`  → `businesses.siren`  : qui construit, et est-ce un acteur déjà
    connu de la base (SCI, promoteur, entreprise locale) ;
  - `SEC/NUM_CADASTRE1` → `dvf_transactions.cadastre_ref` : la parcelle
    a-t-elle changé de main avant le dépôt du permis.

**API DIDO** (`data.statistiques.developpement-durable.gouv.fr`) : filtrage
côté serveur, syntaxe `?COMM=in:30140,30322&columns=…`. Le fichier national
fait 1,9 million de lignes — on n'en garde que les communes collectées.
Piège : un nom de colonne inexistant renvoie **400 Bad Request** sans dire
lequel ; la liste faisant foi est dans les métadonnées du datafile.

**Sur les dates.** `DR_DEPOT` est ramené au 1er janvier pour les petites
communes (contrôle de divulgation statistique) : on a l'année, pas le jour.
Ne pas présenter ces dates comme exactes.

Usage :
  python3 -m collectors.urbanisme_sitadel
  python3 -m collectors.urbanisme_sitadel --insee 30140
  python3 -m collectors.urbanisme_sitadel --stats
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import urllib.parse
import urllib.request

from .archive import archive_fetch
from .config import COMMUNES_ADRESSE, COMMUNES_INSEE_ADRESSE, HEADERS
from .db import get_conn

DATAGOUV_DATASET = "liste-des-permis-de-construire-et-autres-autorisations-durbanisme"
DATAGOUV_API = "https://www.data.gouv.fr/api/1/datasets"
DIDO = "https://data.statistiques.developpement-durable.gouv.fr/dido/api/v1/datafiles"

# Colonnes demandées à DIDO. Sous-ensemble volontaire des 94 disponibles :
# identification, localisation, demandeur, nature et volumétrie du projet.
COLONNES = [
    "COMM", "TYPE_DAU", "NUM_DAU", "ETAT_DAU",
    "DATE_REELLE_AUTORISATION", "DR_DEPOT", "DATE_REELLE_DAACT",
    "DENOM_DEM", "SIREN_DEM", "CJ_DEM", "APE_DEM", "LOCALITE_DEM",
    "ADR_NUM_TER", "ADR_LIBVOIE_TER", "ADR_LIEUDIT_TER", "ADR_LOCALITE_TER",
    "SEC_CADASTRE1", "NUM_CADASTRE1", "SUPERFICIE_TERRAIN",
    "NATURE_PROJET_DECLAREE", "NB_LGT_TOT_CREES", "NB_LGT_DEMOLIS",
    "SURF_HAB_CREEE", "SURF_LOC_CREEE",
    "RES_PRINCIP_OU_SECOND", "RES_TOURISME", "I_PISCINE", "REC_ARCHI",
]

# Titres des ressources data.gouv → nature de l'autorisation.
RESSOURCES = {
    "Liste des autorisations d'urbanisme créant des logements": "logements",
    "Liste des autorisations d'urbanisme créant des locaux non résidentiels": "locaux",
}

# `availableValues` du datafile : ces libellés sont documentés par le SDES.
TYPE_DAU_LABELS = {
    "PC": "Permis de construire",
    "DP": "Déclaration préalable",
    "PA": "Permis d'aménager",
    "PD": "Permis de démolir",
}
# 1 = résidence principale, 2 = secondaire, 3 = indéterminé (dictionnaire SDES).
RESIDENCE_LABELS = {"1": "principale", "2": "secondaire", "3": "indéterminé"}


def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS urbanisme_autorisations (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            num_dau         TEXT NOT NULL,
            insee           TEXT NOT NULL,
            commune         TEXT,
            categorie       TEXT,          -- logements | locaux
            type_dau        TEXT,          -- PC | DP | PA | PD
            type_label      TEXT,
            etat_dau        TEXT,
            date_depot      TEXT,          -- ⚠ ramenée au 01/01 pour les petites communes
            date_autorisation TEXT,
            date_achevement TEXT,
            demandeur_nom   TEXT,
            demandeur_siren TEXT,
            demandeur_entity_id INTEGER REFERENCES entities(id) ON DELETE SET NULL,
            adresse         TEXT,
            lieu_dit        TEXT,
            cadastre_ref    TEXT,          -- normalisé façon DVF : 'AC0167'
            superficie_terrain REAL,
            nature_projet   TEXT,
            nb_logements    INTEGER,
            nb_logements_demolis INTEGER,
            surface_hab_creee REAL,
            surface_loc_creee REAL,
            residence       TEXT,          -- principale | secondaire | indéterminé
            res_tourisme    TEXT,
            piscine         TEXT,
            recours_architecte TEXT,
            event_id        INTEGER REFERENCES events(id) ON DELETE SET NULL,
            source          TEXT DEFAULT 'sitadel',
            created_at      TEXT DEFAULT (datetime('now')),
            UNIQUE(num_dau, categorie)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_urba_insee"
                 " ON urbanisme_autorisations(insee, date_depot)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_urba_cadastre"
                 " ON urbanisme_autorisations(cadastre_ref)")
    conn.commit()


def cadastre_dvf(section: str | None, numero: str | None) -> str | None:
    """« C » + « 1213 » → « 0C1213 », format de `dvf_transactions.cadastre_ref`.

    DVF stocke la section sur 2 caractères complétés à gauche par un zéro et le
    numéro de parcelle sur 4 chiffres. Sans cette normalisation, aucun permis ne
    se rapproche d'une mutation.
    """
    sec = (section or "").strip().upper()
    num = (numero or "").strip()
    if not sec or not num or not num.isdigit():
        return None
    return f"{sec.rjust(2, '0')}{num.zfill(4)}"


def resolve_datafile(resource_title: str) -> tuple[str, str | None]:
    """(rid DIDO, last_modified) d'une ressource CSV du dataset Sitadel."""
    req = urllib.request.Request(f"{DATAGOUV_API}/{DATAGOUV_DATASET}/", headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r:
        meta = json.load(r)
    for res in meta.get("resources", []):
        if res.get("title") == resource_title and res.get("format") == "csv":
            # .../dido/api/v1/datafiles/<rid>/csv
            parts = res["url"].rstrip("/").split("/")
            if "datafiles" in parts:
                return parts[parts.index("datafiles") + 1], res.get("last_modified")
    raise RuntimeError(
        f"ressource CSV « {resource_title} » introuvable — titres : "
        f"{[r.get('title') for r in meta.get('resources', []) if r.get('format') == 'csv']}")


def datafile_columns(rid: str) -> list[str]:
    """Colonnes réellement présentes dans le datafile.

    Indispensable : les deux fichiers n'ont pas le même schéma (celui des locaux
    non résidentiels n'a pas `NB_LGT_TOT_CREES` ni `RES_PRINCIP_OU_SECOND`), et
    DIDO renvoie un **400 sans préciser la colonne fautive**. On demande donc
    l'intersection de ce qu'on veut et de ce qui existe.
    """
    req = urllib.request.Request(f"{DIDO}/{rid}", headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r:
        meta = json.load(r)
    return [c["name"] for c in meta.get("columns", []) if c.get("name")]


def fetch_rows(rid: str, insee_list: list[str]) -> list[dict]:
    """Lignes Sitadel du périmètre, filtrées côté serveur par DIDO."""
    dispo = set(datafile_columns(rid))
    colonnes = [c for c in COLONNES if c in dispo]
    manquantes = [c for c in COLONNES if c not in dispo]
    if manquantes:
        print(f"    (colonnes absentes de ce fichier : {', '.join(manquantes)})")
    url = f"{DIDO}/{rid}/csv?" + urllib.parse.urlencode(
        {"COMM": "in:" + ",".join(insee_list), "columns": ",".join(colonnes)})
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read()
    archive_fetch("sitadel", url, raw, doc_type="csv",
                  title="Sitadel — autorisations d'urbanisme du périmètre",
                  metadata={"rid": rid, "communes": insee_list})
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8", "replace")), delimiter=";"))


def _num(v):
    try:
        return float(v) if v not in (None, "", "NA") else None
    except (TypeError, ValueError):
        return None


def _int(v):
    n = _num(v)
    return int(n) if n is not None else None


def import_rows(conn, categorie: str, rows: list[dict]) -> dict:
    """Insert idempotent + événement + rattachement du demandeur par SIREN."""
    siren_idx = {
        r["siren"]: r["entity_id"] for r in conn.execute(
            "SELECT siren, entity_id FROM businesses"
            " WHERE siren IS NOT NULL AND siren <> ''")
    }
    res = {"lignes": len(rows), "inseres": 0, "events": 0,
           "lies_par_siren": 0, "siren_inconnus": set(), "cadastre_croise": 0}

    for row in rows:
        insee = (row.get("COMM") or "").strip()
        num_dau = (row.get("NUM_DAU") or "").strip()
        if not insee or not num_dau:
            continue
        commune = COMMUNES_ADRESSE.get(insee, {}).get("nom")
        type_dau = (row.get("TYPE_DAU") or "").strip()
        siren = (row.get("SIREN_DEM") or "").strip() or None
        entity_id = siren_idx.get(siren) if siren else None
        if siren and entity_id is None:
            res["siren_inconnus"].add(siren)
        if entity_id:
            res["lies_par_siren"] += 1

        cad = cadastre_dvf(row.get("SEC_CADASTRE1"), row.get("NUM_CADASTRE1"))
        date_depot = (row.get("DR_DEPOT") or "").strip() or None
        adresse = " ".join(x for x in (
            (row.get("ADR_NUM_TER") or "").strip(),
            (row.get("ADR_LIBVOIE_TER") or "").strip()) if x) or None
        nb_lgt = _int(row.get("NB_LGT_TOT_CREES"))
        residence = RESIDENCE_LABELS.get((row.get("RES_PRINCIP_OU_SECOND") or "").strip())

        # Événement : place le permis dans la chronologie et l'indexe en FTS.
        titre_parts = [TYPE_DAU_LABELS.get(type_dau, type_dau or "Autorisation")]
        if nb_lgt:
            titre_parts.append(f"{nb_lgt} logement{'s' if nb_lgt > 1 else ''}")
        if row.get("ADR_LIEUDIT_TER"):
            titre_parts.append(f"au lieu-dit {row['ADR_LIEUDIT_TER'].strip()}")
        titre = f"{' — '.join(titre_parts)} ({commune or insee})"

        metadata = {
            "num_dau": num_dau, "type_dau": type_dau, "categorie": categorie,
            "cadastre_ref": cad, "demandeur": (row.get("DENOM_DEM") or "").strip() or None,
            "siren_demandeur": siren, "nb_logements": nb_lgt,
            "surface_hab_creee": _num(row.get("SURF_HAB_CREEE")),
            "superficie_terrain": _num(row.get("SUPERFICIE_TERRAIN")),
            "residence": residence,
            "date_precision": "annee",   # cf. contrôle de divulgation statistique
        }
        cur = conn.execute(
            "INSERT INTO events (type, date, title, content, source, source_url, metadata)"
            " SELECT 'autorisation_urbanisme', ?, ?, ?, 'sitadel', ?, ?"
            " WHERE NOT EXISTS (SELECT 1 FROM events"
            "   WHERE type='autorisation_urbanisme'"
            "     AND json_extract(metadata,'$.num_dau')=?"
            "     AND json_extract(metadata,'$.categorie')=?)",
            (date_depot, titre,
             f"Autorisation d'urbanisme {num_dau} — {commune or insee}."
             + (f" Demandeur : {row.get('DENOM_DEM')}." if row.get("DENOM_DEM") else "")
             + (f" Parcelle {cad}." if cad else "")
             + (f" Résidence {residence}." if residence else ""),
             f"https://www.statistiques.developpement-durable.gouv.fr/"
             f"catalogue?page=dataset&datasetId={DATAGOUV_DATASET}",
             json.dumps(metadata, ensure_ascii=False), num_dau, categorie))
        event_id = None
        if cur.rowcount:
            res["events"] += 1
            event_id = conn.execute(
                "SELECT id FROM events WHERE type='autorisation_urbanisme'"
                " AND json_extract(metadata,'$.num_dau')=?"
                " AND json_extract(metadata,'$.categorie')=?",
                (num_dau, categorie)).fetchone()["id"]
            if entity_id:
                conn.execute(
                    "INSERT OR IGNORE INTO event_entities (event_id, entity_id, role)"
                    " VALUES (?,?,'demandeur')", (event_id, entity_id))

        conn.execute("""
            INSERT OR IGNORE INTO urbanisme_autorisations
              (num_dau, insee, commune, categorie, type_dau, type_label, etat_dau,
               date_depot, date_autorisation, date_achevement,
               demandeur_nom, demandeur_siren, demandeur_entity_id,
               adresse, lieu_dit, cadastre_ref, superficie_terrain, nature_projet,
               nb_logements, nb_logements_demolis, surface_hab_creee, surface_loc_creee,
               residence, res_tourisme, piscine, recours_architecte, event_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (num_dau, insee, commune, categorie, type_dau,
              TYPE_DAU_LABELS.get(type_dau), (row.get("ETAT_DAU") or "").strip() or None,
              date_depot,
              (row.get("DATE_REELLE_AUTORISATION") or "").strip() or None,
              (row.get("DATE_REELLE_DAACT") or "").strip() or None,
              (row.get("DENOM_DEM") or "").strip() or None, siren, entity_id,
              adresse, (row.get("ADR_LIEUDIT_TER") or "").strip() or None,
              cad, _num(row.get("SUPERFICIE_TERRAIN")),
              (row.get("NATURE_PROJET_DECLAREE") or "").strip() or None,
              nb_lgt, _int(row.get("NB_LGT_DEMOLIS")),
              _num(row.get("SURF_HAB_CREEE")), _num(row.get("SURF_LOC_CREEE")),
              residence, (row.get("RES_TOURISME") or "").strip() or None,
              (row.get("I_PISCINE") or "").strip() or None,
              (row.get("REC_ARCHI") or "").strip() or None, event_id))
        res["inseres"] += 1

    conn.commit()
    res["siren_inconnus"] = sorted(res["siren_inconnus"])
    return res


def croisement_cadastre(conn) -> list[dict]:
    """Parcelles portant à la fois une mutation DVF et une autorisation.

    Le rapprochement est exact (même référence cadastrale), pas heuristique :
    c'est la trace « vendu puis construit » ou « construit puis vendu ».
    """
    return [dict(r) for r in conn.execute("""
        SELECT u.cadastre_ref, u.commune, u.num_dau, u.date_depot,
               u.demandeur_nom, u.nb_logements,
               COUNT(d.id) AS mutations,
               MIN(d.date) AS premiere_mutation, MAX(d.date) AS derniere_mutation,
               MAX(d.price) AS prix_max
        FROM urbanisme_autorisations u
        JOIN dvf_transactions d ON d.cadastre_ref = u.cadastre_ref
        WHERE u.cadastre_ref IS NOT NULL
        GROUP BY u.id
        ORDER BY u.date_depot DESC
    """)]


def run(insee_list: list[str] | None = None) -> dict:
    conn = get_conn()
    ensure_table(conn)
    cibles = insee_list or COMMUNES_INSEE_ADRESSE
    total = {}
    try:
        for titre, categorie in RESSOURCES.items():
            try:
                rid, last_modified = resolve_datafile(titre)
                rows = fetch_rows(rid, cibles)
            except Exception as e:
                print(f"  [sitadel] {categorie} : erreur — {e}")
                continue
            res = import_rows(conn, categorie, rows)
            res["publication"] = last_modified
            total[categorie] = res
            print(f"  [sitadel] {categorie}: {res['lignes']} autorisations, "
                  f"{res['events']} nouveaux événements, "
                  f"{res['lies_par_siren']} rattachées par SIREN, "
                  f"{len(res['siren_inconnus'])} SIREN inconnus")

        croises = croisement_cadastre(conn)
        print(f"  [sitadel] {len(croises)} parcelles avec mutation DVF ET autorisation")
        total["cadastre_croise"] = len(croises)
    finally:
        conn.close()
    return total


def stats():
    conn = get_conn()
    try:
        n = conn.execute("SELECT COUNT(*) FROM urbanisme_autorisations").fetchone()[0]
        print(f"urbanisme_autorisations : {n}\n")
        print(f"  {'commune':<32}{'PC':>5}{'DP':>5}{'logts':>7}{'2e rés.':>9}")
        for r in conn.execute("""
            SELECT commune,
                   SUM(type_dau='PC') pc, SUM(type_dau='DP') dp,
                   SUM(COALESCE(nb_logements,0)) logts,
                   -- `residence` est NULL sur tout le fichier « locaux » : sans
                   -- COALESCE, SUM() rend NULL dès qu'une commune n'a que des
                   -- locaux non résidentiels.
                   SUM(COALESCE(residence='secondaire', 0)) second
            FROM urbanisme_autorisations GROUP BY commune ORDER BY logts DESC
        """):
            print(f"  {(r['commune'] or '?'):<32}{r['pc'] or 0:>5}{r['dp'] or 0:>5}"
                  f"{r['logts'] or 0:>7}{r['second'] or 0:>9}")
        croises = croisement_cadastre(conn)
        if croises:
            print(f"\n  Parcelles vendues ET autorisées ({len(croises)}) — 8 premières :")
            for c in croises[:8]:
                print(f"    {c['cadastre_ref']} {(c['commune'] or ''):<16} "
                      f"permis {str(c['date_depot'])[:4]} | {c['mutations']} mutation(s) "
                      f"{str(c['premiere_mutation'])[:10]}→{str(c['derniere_mutation'])[:10]}"
                      + (f" | {c['demandeur_nom']}" if c["demandeur_nom"] else ""))
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--insee", action="append")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()
    if args.stats:
        stats()
        return
    run(insee_list=args.insee)


if __name__ == "__main__":
    main()
