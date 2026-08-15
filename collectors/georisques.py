"""
georisques.py — Risques naturels, ICPE et arrêtés CATNAT (API Géorisques,
sans clé) pour les communes du registre de collecte (config.COMMUNES).

  - installations_classees → table icpe_installations (régime, Seveso, coords)
  - gaspar/risques         → table risques_gaspar (risques recensés par commune)
  - gaspar/catnat          → events type 'arrete_catnat' (arrêtés de catastrophe
                             naturelle publiés au JO — inondations cévenoles…)

Réponses archivées (raw_documents, source georisques) et rejouables via
une réanalyse depuis raw_documents.

Usage :
  python3 -m collectors.georisques
  python3 -m collectors.georisques --insee 30140
  python3 -m collectors.georisques --stats
"""
import argparse
import json
import time

from .archive import fetch_json
from .config import COMMUNES, COMMUNES_INSEE, REQUEST_DELAY
from .db import get_conn

API = "https://www.georisques.gouv.fr/api/v1"
ENDPOINTS = ["installations_classees", "gaspar/risques", "gaspar/catnat"]


def ensure_tables(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS icpe_installations (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            code_aiot      TEXT UNIQUE,
            raison_sociale TEXT,
            insee          TEXT,
            commune        TEXT,
            adresse        TEXT,
            regime         TEXT,
            seveso         TEXT,
            etat_activite  TEXT,
            lat            REAL,
            lng            REAL,
            raw_data       TEXT,
            created_at     TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS risques_gaspar (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            insee      TEXT NOT NULL,
            commune    TEXT,
            num_risque TEXT NOT NULL,
            libelle    TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(insee, num_risque)
        )
    """)
    conn.commit()


def fetch_paginated(endpoint: str, insee: str) -> list[dict]:
    page, out = 1, []
    while True:
        url = f"{API}/{endpoint}?code_insee={insee}&page={page}&page_size=100"
        data = fetch_json(url, source="georisques", timeout=30)
        out.extend(data.get("data", []))
        if page >= (data.get("total_pages") or 1):
            return out
        page += 1
        time.sleep(REQUEST_DELAY)


def _iso(d: str | None) -> str | None:
    """DD/MM/YYYY → YYYY-MM-DD."""
    if d and len(d) == 10 and d[2] == d[5] == "/":
        return f"{d[6:10]}-{d[3:5]}-{d[0:2]}"
    return d or None


def import_icpe(conn, insee: str, items: list[dict]) -> int:
    n = 0
    for it in items:
        adresse = " ".join(filter(None, [it.get("adresse1"), it.get("adresse2"),
                                         it.get("adresse3")]))
        conn.execute(
            "INSERT OR REPLACE INTO icpe_installations"
            " (code_aiot, raison_sociale, insee, commune, adresse, regime,"
            "  seveso, etat_activite, lat, lng, raw_data)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (it.get("codeAIOT"), it.get("raisonSociale"), insee,
             it.get("commune"), adresse, it.get("regime"),
             it.get("statutSeveso"), it.get("etatActivite"),
             it.get("latitude"), it.get("longitude"),
             json.dumps(it, ensure_ascii=False))
        )
        n += 1
    return n


def import_risques(conn, insee: str, items: list[dict]) -> int:
    commune = COMMUNES.get(insee, {}).get("nom")
    n = 0
    for it in items:
        for r in it.get("risques_detail", []):
            conn.execute(
                "INSERT OR IGNORE INTO risques_gaspar (insee, commune, num_risque, libelle)"
                " VALUES (?,?,?,?)",
                (insee, commune, r.get("num_risque"), r.get("libelle_risque_long"))
            )
            n += 1
    return n


def import_catnat(conn, insee: str, items: list[dict]) -> int:
    commune = COMMUNES.get(insee, {}).get("nom", insee)
    n = 0
    for it in items:
        code = it.get("code_national_catnat", "")
        if not code:
            continue
        exists = conn.execute(
            "SELECT id FROM events WHERE type='arrete_catnat'"
            " AND metadata LIKE ? AND metadata LIKE ?",
            (f'%{code}%', f'%{insee}%')
        ).fetchone()
        if exists:
            continue
        debut, fin = it.get("date_debut_evt", ""), it.get("date_fin_evt", "")
        libelle = it.get("libelle_risque_jo", "Catastrophe naturelle")
        conn.execute(
            "INSERT INTO events (type, date, title, content, source, source_url, metadata)"
            " VALUES ('arrete_catnat', ?, ?, ?, 'georisques', ?, ?)",
            (_iso(it.get("date_publication_arrete")),
             f"CATNAT {libelle} — {commune} ({debut} → {fin})",
             f"Arrêté de catastrophe naturelle « {libelle} », événement du {debut} au {fin}, "
             f"publié au JO le {it.get('date_publication_jo', '?')}.",
             f"https://www.georisques.gouv.fr/api/v1/gaspar/catnat?code_insee={insee}",
             json.dumps({"code": code, "insee": insee, **it}, ensure_ascii=False))
        )
        n += 1
    return n


IMPORTERS = {
    "installations_classees": import_icpe,
    "gaspar/risques":         import_risques,
    "gaspar/catnat":          import_catnat,
}


def run(insee_list: list[str] | None = None):
    conn = get_conn()
    ensure_tables(conn)
    for insee in (insee_list or COMMUNES_INSEE):
        commune = COMMUNES.get(insee, {}).get("nom", insee)
        print(f"[georisques] {commune} ({insee})")
        for ep in ENDPOINTS:
            try:
                items = fetch_paginated(ep, insee)
            except Exception as e:
                print(f"  {ep}: erreur — {e}")
                continue
            n = IMPORTERS[ep](conn, insee, items)
            conn.commit()
            print(f"  {ep}: {len(items)} → {n}")
            time.sleep(REQUEST_DELAY)
    conn.close()
    print("[georisques] OK")


def show_stats():
    conn = get_conn(read_only=True)
    print("ICPE :")
    for r in conn.execute("SELECT commune, raison_sociale, regime FROM icpe_installations"):
        print(f"  {r[0]:20} {r[1]:45} {r[2] or ''}")
    print("\nCATNAT par commune :")
    for r in conn.execute(
        "SELECT json_extract(metadata,'$.insee'), COUNT(*) FROM events"
        " WHERE type='arrete_catnat' GROUP BY 1"):
        print(f"  {COMMUNES.get(r[0], {}).get('nom', r[0]):32} {r[1]}")
    print("\nRisques recensés :")
    for r in conn.execute(
        "SELECT commune, COUNT(*) FROM risques_gaspar GROUP BY insee"):
        print(f"  {r[0]:32} {r[1]}")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Géorisques — 15 communes de l'EPCI")
    ap.add_argument("--insee", help="Limiter à un/des codes INSEE (virgule)")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()
    if args.stats:
        show_stats()
    else:
        run(insee_list=args.insee.split(",") if args.insee else None)
