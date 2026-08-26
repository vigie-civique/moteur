"""
qualite_eau.py — Qualité des cours d'eau (Hub'Eau, API qualité rivières).

Stations physico-chimiques des communes suivies en profondeur : stations →
table eau_stations, analyses → table eau_analyses (clé naturelle code_analyse,
INSERT OR IGNORE — jamais d'écrasement). Collecte incrémentale : repart de la
dernière date de prélèvement connue par station.

Usage :
  python3 -m collectors.qualite_eau                    # collecte incrémentale
  python3 -m collectors.qualite_eau --since 2015-01-01 # historique complet
  python3 -m collectors.qualite_eau --stats            # état des stations
  python3 -m collectors.qualite_eau --report           # synthèse paramètres clés (Markdown)
"""
import argparse
import json
import time
import urllib.parse
import urllib.request

from .config import HEADERS, communes_du_step
from .db import get_conn

API = "https://hubeau.eaufrance.fr/api/v2/qualite_rivieres"
PAGE_SIZE = 5000

# Paramètres SANDRE pertinents pour une pollution domestique / assainissement
PARAMS_CLES = {
    "1340": "Nitrates",
    "1335": "Ammonium",
    "1433": "Orthophosphates",
    "1350": "Phosphore total",
    "1313": "DBO5",
    "1311": "Oxygène dissous",
    "1305": "MES",
    "1447": "Escherichia coli",
    "1449": "Entérocoques",
}


def ensure_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS eau_stations (
            code_station    TEXT PRIMARY KEY,
            libelle         TEXT,
            code_commune    TEXT,
            cours_eau       TEXT,
            latitude        REAL,
            longitude       REAL,
            created_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS eau_analyses (
            code_analyse        TEXT PRIMARY KEY,
            code_station        TEXT NOT NULL REFERENCES eau_stations(code_station),
            date_prelevement    TEXT,
            code_parametre      TEXT,
            libelle_parametre   TEXT,
            resultat            REAL,
            symbole_unite       TEXT,
            code_remarque       TEXT,   -- 1=résultat, 2=<seuil de quantification…
            libelle_qualification TEXT,
            code_fraction       TEXT,
            nom_producteur      TEXT,
            created_at          TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_eau_analyses_station_date
            ON eau_analyses(code_station, date_prelevement);
        CREATE INDEX IF NOT EXISTS idx_eau_analyses_param
            ON eau_analyses(code_parametre);
    """)
    conn.commit()


def _get_json(url: str, timeout: int = 120, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except (TimeoutError, urllib.error.URLError):
            if attempt == retries - 1:
                raise
            time.sleep(5 * (attempt + 1))


def fetch_stations(conn) -> list[str]:
    cibles = communes_du_step("eau")
    url = (f"{API}/station_pc?code_commune={','.join(cibles)}"
           f"&size=200&format=json")
    data = _get_json(url)
    codes = []
    for s in data.get("data", []):
        conn.execute(
            "INSERT OR IGNORE INTO eau_stations"
            " (code_station, libelle, code_commune, cours_eau, latitude, longitude)"
            " VALUES (?,?,?,?,?,?)",
            (s["code_station"], s.get("libelle_station"), s.get("code_commune"),
             s.get("libelle_cours_eau"), s.get("latitude"), s.get("longitude"))
        )
        codes.append(s["code_station"])
    conn.commit()
    return codes


def fetch_analyses(conn, code_station: str, since: str | None) -> int:
    """Analyses d'une station depuis `since` (défaut : dernière date connue)."""
    if since is None:
        row = conn.execute(
            "SELECT MAX(date_prelevement) FROM eau_analyses WHERE code_station=?",
            (code_station,)).fetchone()
        since = row[0] or "2010-01-01"
    params = {"code_station": code_station, "date_debut_prelevement": since,
              "size": PAGE_SIZE, "format": "json"}
    url = f"{API}/analyse_pc?{urllib.parse.urlencode(params)}"
    inserted = 0
    while url:
        data = _get_json(url)
        for a in data.get("data", []):
            cur = conn.execute(
                "INSERT OR IGNORE INTO eau_analyses"
                " (code_analyse, code_station, date_prelevement, code_parametre,"
                "  libelle_parametre, resultat, symbole_unite, code_remarque,"
                "  libelle_qualification, code_fraction, nom_producteur)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (str(a["code_analyse"]), a["code_station"], a.get("date_prelevement"),
                 a.get("code_parametre"), a.get("libelle_parametre"),
                 a.get("resultat"), a.get("symbole_unite"),
                 str(a.get("code_remarque") or ""),
                 a.get("libelle_qualification"), a.get("code_fraction"),
                 a.get("nom_producteur_analyse")))
            inserted += cur.rowcount
        url = data.get("next")
        conn.commit()
        time.sleep(0.5)
    return inserted


def run(since: str | None):
    conn = get_conn()
    ensure_tables(conn)
    codes = fetch_stations(conn)
    print(f"[eau] {len(codes)} station(s) sur "
          f"{len(communes_du_step('eau'))} commune(s) en profondeur")
    total = 0
    for code in codes:
        lib = conn.execute("SELECT libelle FROM eau_stations WHERE code_station=?",
                           (code,)).fetchone()[0]
        try:
            n = fetch_analyses(conn, code, since)
        except Exception as e:
            print(f"  [eau] échec {code} {lib} → {e}")
            continue
        total += n
        print(f"  ✓ {code} {lib} — {n} nouvelle(s) analyse(s)")
    print(f"[eau] OK — {total} analyses insérées")
    conn.close()


def show_stats():
    conn = get_conn(read_only=True)
    for r in conn.execute("""
        SELECT s.code_station, s.libelle,
               COUNT(a.code_analyse), MIN(a.date_prelevement), MAX(a.date_prelevement)
        FROM eau_stations s LEFT JOIN eau_analyses a USING(code_station)
        GROUP BY s.code_station ORDER BY s.libelle"""):
        print(f"  {r[0]} {r[1][:45]:45} {r[2]:>6} analyses  {r[3] or '—'} → {r[4] or '—'}")
    conn.close()


def show_report():
    """Synthèse Markdown des paramètres clés (pollution domestique) par station."""
    conn = get_conn(read_only=True)
    print("# Qualité de l'eau — paramètres clés (source : Hub'Eau / Naïades)\n")
    for st in conn.execute("SELECT code_station, libelle FROM eau_stations ORDER BY libelle"):
        rows = conn.execute(f"""
            SELECT libelle_parametre,
                   MAX(date_prelevement),
                   (SELECT resultat || ' ' || coalesce(symbole_unite,'') FROM eau_analyses
                    WHERE code_station=? AND code_parametre=a.code_parametre
                    ORDER BY date_prelevement DESC LIMIT 1),
                   ROUND(AVG(resultat), 3), COUNT(*)
            FROM eau_analyses a
            WHERE code_station=? AND code_parametre IN ({','.join('?' * len(PARAMS_CLES))})
            GROUP BY code_parametre ORDER BY libelle_parametre""",
            (st[0], st[0], *PARAMS_CLES)).fetchall()
        if not rows:
            continue
        print(f"## {st[1]} ({st[0]})\n")
        print("| Paramètre | Dernière mesure | Valeur | Moyenne | N |")
        print("|---|---|---|---|---|")
        for p, dmax, last, avg, n in rows:
            print(f"| {p} | {dmax} | {last} | {avg} | {n} |")
        print()
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Hub'Eau — qualité des rivières du vallon")
    ap.add_argument("--since", default=None,
                    help="date plancher AAAA-MM-JJ (défaut : incrémental)")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()
    if args.stats:
        show_stats()
    elif args.report:
        show_report()
    else:
        run(args.since)
