"""
insee_social.py — Indicateurs sociaux INSEE par commune (API Melodi, sans clé).

Jeux collectés (headline par commune, table insee_indicateurs) :
  - DS_POPULATIONS_REFERENCE : populations légales (PMUN/PCAP/PTOT)
  - DS_RP_SERIE_HISTORIQUE   : population, logements (principales/secondaires/
                               vacants), naissances, décès, superficie — 1968→
  - DS_RP_POPULATION_PRINC   : structure par âge (totaux sexes)
  - DS_RP_EMPLOI_LR_PRINC    : actifs / chômeurs 15-64 (totaux sexes+diplômes)
  - DS_FILOSOFI_CC           : niveau de vie / pauvreté — souvent sous secret
                               statistique (<2000 hab) → valeurs vides ignorées
  - DS_BPE                   : équipements par type (commerces, santé, écoles…)

Chaque réponse API est archivée (raw_documents, source insee-melodi) et
rejouable via scripts/reparse.py. Insert : INSERT OR REPLACE (donnée officielle
rafraîchie, UNIQUE(insee, dataset, indicateur, annee)).

Usage :
  python3 -m collectors.insee_social               # 7 communes, tous les jeux
  python3 -m collectors.insee_social --insee 30140
  python3 -m collectors.insee_social --dataset DS_BPE
  python3 -m collectors.insee_social --stats
"""
import argparse
import json
import time
import urllib.error

from .archive import fetch_json
from .config import COMMUNES, COMMUNES_INSEE, REQUEST_DELAY
from .db import get_conn

MELODI_API = "https://api.insee.fr/melodi/data"

DATASETS = [
    "DS_POPULATIONS_REFERENCE",
    "DS_RP_SERIE_HISTORIQUE",
    "DS_RP_POPULATION_PRINC",
    "DS_RP_EMPLOI_LR_PRINC",
    "DS_FILOSOFI_CC",
    "DS_BPE",
]

# Libellés lisibles des indicateurs clés (les autres gardent leur code)
LABELS = {
    "POPREF_PMUN":             "Population municipale",
    "POPREF_PCAP":             "Population comptée à part",
    "POPREF_PTOT":             "Population totale",
    "POP":                     "Population (recensement)",
    "DWELLINGS":               "Logements — total",
    "DWELLINGS_DW_MAIN":       "Résidences principales",
    "DWELLINGS_DW_SEC_DW_OCC": "Résidences secondaires et occasionnelles",
    "DWELLINGS_DW_VAC":        "Logements vacants",
    "DWELLINGS_POPSIZE_DW_MAIN": "Population des résidences principales",
    "BRTH":                    "Naissances (période intercensitaire)",
    "DEATH":                   "Décès (période intercensitaire)",
    "SUP":                     "Superficie",
    "EMP_1T2_Y15T64":          "Actifs 15-64 ans",
    "EMP_1_Y15T64":            "Actifs occupés 15-64 ans",
    "EMP_2_Y15T64":            "Chômeurs 15-64 ans",
    "FILO_D2_SL":              "Niveau de vie médian (€/an)",
    "BPE_TOTAL":               "Équipements — total",
}


def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS insee_indicateurs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            insee       TEXT NOT NULL,
            commune     TEXT,
            dataset     TEXT NOT NULL,
            indicateur  TEXT NOT NULL,
            libelle     TEXT,
            annee       TEXT NOT NULL,
            valeur      REAL,
            dims        TEXT,
            source      TEXT DEFAULT 'insee-melodi',
            created_at  TEXT DEFAULT (datetime('now')),
            UNIQUE(insee, dataset, indicateur, annee)
        )
    """)
    conn.commit()


def _fetch_json_429(url: str):
    """fetch_json avec retry sur le rate limit Melodi (30 req/min)."""
    for attempt in range(4):
        try:
            return fetch_json(url, source="insee-melodi", timeout=30)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 30 * (attempt + 1)
                print(f"    429 rate limit — attente {wait}s (tentative {attempt + 1})")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Melodi : trop de tentatives (429)")


def fetch_dataset(dataset: str, insee: str) -> list[dict]:
    """Toutes les observations d'un jeu pour une commune (suit la pagination)."""
    url = f"{MELODI_API}/{dataset}?GEO=COM-{insee}&maxResult=10000"
    observations = []
    while url:
        data = _fetch_json_429(url)
        observations.extend(data.get("observations", []))
        url = (data.get("paging") or {}).get("next")
        if url:
            time.sleep(REQUEST_DELAY)
    return observations


def _extract(dataset: str, obs: dict) -> tuple[str, str, float, dict] | None:
    """(indicateur, annee, valeur, dims_residuelles) ou None si hors headline."""
    dims = obs.get("dimensions", {})
    val = (obs.get("measures", {}).get("OBS_VALUE_NIVEAU") or {}).get("value")
    if val is None:  # secret statistique (Filosofi) ou mesure absente
        return None
    annee = str(dims.get("TIME_PERIOD", ""))
    if not annee:
        return None

    if dataset == "DS_POPULATIONS_REFERENCE":
        ind = f"POPREF_{dims.get('POPREF_MEASURE', '')}"
    elif dataset == "DS_RP_SERIE_HISTORIQUE":
        ind = dims.get("RP_MEASURE", "")
        ocs = dims.get("OCS", "_T")
        if ocs != "_T":
            ind += f"_{ocs}"
    elif dataset == "DS_RP_POPULATION_PRINC":
        if dims.get("SEX") != "_T" or dims.get("RP_MEASURE") != "POP":
            return None
        ind = f"POP_AGE_{dims.get('AGE', '_T')}"
    elif dataset == "DS_RP_EMPLOI_LR_PRINC":
        if dims.get("SEX") != "_T" or dims.get("EDUC") != "_T":
            return None
        ind = f"EMP_{dims.get('EMPSTA_ENQ', '')}_{dims.get('AGE', '')}"
    elif dataset == "DS_FILOSOFI_CC":
        ind = f"FILO_{dims.get('FILOSOFI_MEASURE', '')}"
    elif dataset == "DS_BPE":
        if dims.get("BPE_MEASURE") != "FACILITIES":
            return None
        ftype = dims.get("FACILITY_TYPE", "")
        if ftype == "_T":
            # Lignes agrégées : totaux par sous-domaine, domaine, ou général
            sdom, dom = dims.get("FACILITY_SDOM", "_T"), dims.get("FACILITY_DOM", "_T")
            if sdom != "_T":
                ind = f"BPE_SDOM_{sdom}"
            elif dom != "_T":
                ind = f"BPE_DOM_{dom}"
            else:
                ind = "BPE_TOTAL"
        else:
            ind = f"BPE_{ftype}"
    else:
        return None

    if not ind or ind.endswith("_"):
        return None
    rest = {k: v for k, v in dims.items() if k not in ("GEO", "FREQ", "TIME_PERIOD")}
    return ind, annee, float(val), rest


def import_observations(conn, dataset: str, insee: str, observations: list[dict]) -> int:
    """Insert idempotent — réutilisé par scripts/reparse.py."""
    commune = COMMUNES.get(insee, {}).get("nom")
    inserted = 0
    for obs in observations:
        row = _extract(dataset, obs)
        if not row:
            continue
        ind, annee, valeur, rest = row
        conn.execute(
            "INSERT OR REPLACE INTO insee_indicateurs"
            " (insee, commune, dataset, indicateur, libelle, annee, valeur, dims)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (insee, commune, dataset, ind, LABELS.get(ind), annee, valeur,
             json.dumps(rest, ensure_ascii=False) if rest else None)
        )
        inserted += 1
    conn.commit()
    return inserted


def run(insee_list: list[str] | None = None, datasets: list[str] | None = None):
    conn = get_conn()
    ensure_table(conn)
    total = 0
    for insee in (insee_list or COMMUNES_INSEE):
        commune = COMMUNES.get(insee, {}).get("nom", insee)
        print(f"[insee] {commune} ({insee})")
        for ds in (datasets or DATASETS):
            try:
                observations = fetch_dataset(ds, insee)
            except Exception as e:
                print(f"  {ds}: erreur — {e}")
                continue
            n = import_observations(conn, ds, insee, observations)
            total += n
            print(f"  {ds}: {len(observations)} obs → {n} indicateurs")
            time.sleep(REQUEST_DELAY)
    print(f"[insee] OK — {total} indicateurs insérés/mis à jour")
    conn.close()


def show_stats():
    conn = get_conn(read_only=True)
    rows = conn.execute("""
        SELECT commune, dataset, COUNT(*), MIN(annee), MAX(annee)
        FROM insee_indicateurs GROUP BY commune, dataset ORDER BY commune, dataset
    """).fetchall()
    if not rows:
        print("Table insee_indicateurs vide.")
        return
    for c, ds, n, y0, y1 in rows:
        print(f"  {c or '?':32} {ds:28} {n:>5} ({y0}–{y1})")
    # Aperçu : résidences secondaires au dernier recensement
    print("\nRésidences secondaires (dernier recensement) :")
    for r in conn.execute("""
        SELECT commune, annee, valeur FROM insee_indicateurs AS i
        WHERE i.indicateur='DWELLINGS_DW_SEC_DW_OCC'
          AND i.annee=(SELECT MAX(i2.annee) FROM insee_indicateurs i2
                       WHERE i2.insee=i.insee AND i2.indicateur=i.indicateur)
        ORDER BY valeur DESC
    """):
        print(f"  {r[0]:32} {r[1]}: {r[2]:,.0f}")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Indicateurs INSEE Melodi — 15 communes de l'EPCI")
    ap.add_argument("--insee", help="Limiter à un/des codes INSEE (virgule)")
    ap.add_argument("--dataset", help="Limiter à un/des jeux (virgule)")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()
    if args.stats:
        show_stats()
    else:
        run(insee_list=args.insee.split(",") if args.insee else None,
            datasets=args.dataset.split(",") if args.dataset else None)
