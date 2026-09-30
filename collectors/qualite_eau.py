"""
qualite_eau.py — Qualité des cours d'eau (Hub'Eau, API qualité rivières).

Stations physico-chimiques du BASSIN suivi : les cours d'eau que l'instance
déclare (`collecte.cours_eau`), dans un rayon autour de la commune — à défaut,
les stations des communes de fond. Stations → table eau_stations, analyses →
table eau_analyses (clé naturelle code_analyse, INSERT OR IGNORE — jamais
d'écrasement). Collecte incrémentale : repart de la dernière date de
prélèvement connue par station.

Une station sortie de la sélection est PURGÉE avec ses analyses. Le 30/09/2026,
les trois instances publiaient des stations collectées à leur création, quand
le step visait toute l'intercommunalité : 28 sur 28 hors de Lasalle, 29 sur 29
hors de Brassac, 11 sur 12 hors de Saillans — des mesures de la Dourbie
présentées comme celles de la Salindrenque. Réduire la sélection sans purger
ne retire rien de ce qui est publié.

Usage :
  python3 -m collectors.qualite_eau                    # collecte incrémentale
  python3 -m collectors.qualite_eau --since 2015-01-01 # historique complet
  python3 -m collectors.qualite_eau --stats            # état des stations
  python3 -m collectors.qualite_eau --report           # synthèse paramètres clés (Markdown)
  python3 -m collectors.qualite_eau --proposer [km]     # cours d'eau candidats autour de la commune
"""
import argparse
import datetime as dt
import json
import time
import urllib.parse
import urllib.request

from .config import CENTROID, EAU_COURS_EAU, HEADERS, communes_du_step
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
        # ValueError : Hub'Eau rend parfois un corps vide avec un statut 200 —
        # trois fois le 30/09/2026 en une soirée. Un nouvel essai suffit.
        except (TimeoutError, ConnectionError, urllib.error.URLError, ValueError) as e:
            # Un refus (4xx) ne change pas en réessayant : c'est à l'appelant
            # de reformuler — cf. le découpage par mois de fetch_analyses.
            if isinstance(e, urllib.error.HTTPError) and e.code < 500:
                raise
            if attempt == retries - 1:
                raise
            time.sleep(5 * (attempt + 1))


def selection_stations(cours_eau: dict, centroid: tuple, communes: list[str]) -> dict:
    """Paramètres `station_pc` : le bassin déclaré, sinon les communes de fond."""
    if cours_eau:
        return {"code_cours_eau": ",".join(cours_eau["codes"]),
                "latitude": centroid[0], "longitude": centroid[1],
                "distance": cours_eau.get("rayon_km", 20)}
    return {"code_commune": ",".join(communes)}


def purger_hors_selection(conn, gardees: list[str]) -> int:
    """Retire les stations (et leurs analyses) que la sélection ne retient plus."""
    marques = ",".join("?" * len(gardees)) or "''"
    sortantes = [r[0] for r in conn.execute(
        f"SELECT code_station FROM eau_stations WHERE code_station NOT IN ({marques})",
        gardees)]
    for code in sortantes:
        conn.execute("DELETE FROM eau_analyses WHERE code_station=?", (code,))
        conn.execute("DELETE FROM eau_stations WHERE code_station=?", (code,))
    conn.commit()
    return len(sortantes)


def fetch_stations(conn) -> list[str]:
    params = selection_stations(EAU_COURS_EAU, CENTROID, communes_du_step("eau"))
    url = f"{API}/station_pc?{urllib.parse.urlencode({**params, 'size': 200, 'format': 'json'})}"
    data = _get_json(url)
    codes = []
    for s in data.get("data", []):
        # v2 de l'API : `nom_cours_eau`. L'ancien `libelle_cours_eau` n'existe
        # plus, et la colonne restait vide sans que rien ne le signale.
        conn.execute(
            "INSERT INTO eau_stations"
            " (code_station, libelle, code_commune, cours_eau, latitude, longitude)"
            " VALUES (?,?,?,?,?,?) ON CONFLICT(code_station) DO UPDATE SET"
            " cours_eau=COALESCE(excluded.cours_eau, eau_stations.cours_eau)",
            (s["code_station"], s.get("libelle_station"), s.get("code_commune"),
             s.get("nom_cours_eau") or s.get("libelle_cours_eau"),
             s.get("latitude"), s.get("longitude"))
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
    inserted = 0
    # Une requête par année, et par mois si l'année refuse : Hub'Eau répond
    # HTTP 400 au-delà de 20 000 résultats paginés, et la station du Gardon de
    # Saint-Jean à Thoiras dépasse ce plafond sur une seule année.
    for annee in range(int(since[:4]), dt.date.today().year + 1):
        debut = since[:10] if annee == int(since[:4]) else f"{annee}-01-01"
        try:
            inserted += _fetch_periode(conn, code_station, debut, f"{annee}-12-31")
        except urllib.error.HTTPError as e:
            if e.code != 400:
                raise
            for mois in range(int(debut[5:7]), 13):
                fin = (dt.date(annee + mois // 12, mois % 12 + 1, 1) - dt.timedelta(days=1))
                d = debut if mois == int(debut[5:7]) else f"{annee}-{mois:02d}-01"
                inserted += _fetch_periode(conn, code_station, d, fin.isoformat())
    return inserted


def _fetch_periode(conn, code_station: str, debut: str, fin: str) -> int:
    params = {"code_station": code_station, "date_debut_prelevement": debut,
              "date_fin_prelevement": fin, "size": PAGE_SIZE, "format": "json"}
    return _fetch_pages(conn, f"{API}/analyse_pc?{urllib.parse.urlencode(params)}")


def _fetch_pages(conn, url: str) -> int:
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
    if EAU_COURS_EAU:
        print(f"[eau] {len(codes)} station(s) sur {len(EAU_COURS_EAU['codes'])} cours "
              f"d'eau, à moins de {EAU_COURS_EAU.get('rayon_km', 20)} km")
    else:
        print(f"[eau] {len(codes)} station(s) sur "
              f"{len(communes_du_step('eau'))} commune(s) en profondeur"
              " — aucun cours d'eau déclaré (collecte.cours_eau)")
    purgees = purger_hors_selection(conn, codes)
    if purgees:
        print(f"[eau] {purgees} station(s) hors sélection purgée(s), analyses comprises")
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


def proposer(rayon_km: float):
    """Cours d'eau surveillés autour de la commune, pour remplir collecte.cours_eau."""
    if len(CENTROID) != 2:
        raise SystemExit("config/instance.json : pas de « centroid »")
    params = {"latitude": CENTROID[0], "longitude": CENTROID[1], "distance": rayon_km,
              "size": 500, "format": "json",
              "fields": "code_station,libelle_station,code_cours_eau,nom_cours_eau,date_arret"}
    data = _get_json(f"{API}/station_pc?{urllib.parse.urlencode(params)}")
    par_cours = {}
    for s in data.get("data", []):
        if s.get("code_cours_eau"):
            par_cours.setdefault((s["code_cours_eau"], s.get("nom_cours_eau")), []).append(s)
    print(f"Cours d'eau surveillés à moins de {rayon_km} km :\n")
    for (code, nom), stations in sorted(par_cours.items(), key=lambda kv: -len(kv[1])):
        actives = sum(1 for s in stations if not s.get("date_arret"))
        print(f"  {code:10} {nom or '—':32} {len(stations):>2} station(s), {actives} active(s)")
        for s in stations[:4]:
            print(f"               · {s['libelle_station'].strip()}")
    print('\nÀ déclarer : "collecte": {"cours_eau": {"codes": [...], "rayon_km": 20}}')


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Hub'Eau — qualité des rivières du vallon")
    ap.add_argument("--since", default=None,
                    help="date plancher AAAA-MM-JJ (défaut : incrémental)")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--proposer", nargs="?", type=float, const=15.0, default=None,
                    metavar="KM")
    args = ap.parse_args()
    if args.proposer is not None:
        proposer(args.proposer)
    elif args.stats:
        show_stats()
    elif args.report:
        show_report()
    else:
        run(args.since)
