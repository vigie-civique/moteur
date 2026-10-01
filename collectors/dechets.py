"""
dechets.py — Les déchets ménagers : qui collecte, combien par habitant, où ça
part (SINOE®, l'enquête « collecte » de l'ADEME, data.ademe.fr).

La maille de SINOE n'est PAS la commune : c'est la collectivité qui exerce la
compétence (« l'acteur » — une intercommunalité, un syndicat). On entre donc par
la commune (`communes desservies` : qui collecte ici ?) et tout le reste se lit
par le code d'acteur qui en sort. Le SIREN n'y figure pas. Ce que ces chiffres
disent vaut pour TOUT le territoire de l'acteur, et la publication doit le dire.

Six relevés :
  1. `dechets_desserte` — les services déclarés pour la commune, par année ;
  2. `dechets_performance` — kilos par habitant et par an, hors gravats, avec la
     population et la typologie retenues par l'ADEME cette année-là ;
  3. `dechets_tonnes` (axe `dechet`) — tonnes par type de déchet ;
  4. `dechets_tonnes` (axe `destination`) — tonnes par destination ;
  5. `dechets_decheteries` — l'annuaire des déchèteries de l'acteur ;
  6. `dechets_reperes` — les quartiles de la même grandeur, la même année, pour
     toutes les collectivités de France et du département : sans eux, un
     « 271 kg par habitant » ne se lit pas.

L'enquête n'a pas lieu tous les ans (2015, 2017, 2021, 2023, 2024 pour la
plupart des acteurs) : une année absente n'est pas une année sans déchets. Les
lignes se remplacent à chaque passe — l'ADEME corrige ses millésimes.

Usage :
  python3 -m collectors.dechets
  python3 -m collectors.dechets --stats
"""
from __future__ import annotations

import argparse
import urllib.parse

from .archive import fetch_json
from .config import communes_du_step
from .db import get_conn

ADEME = "https://data.ademe.fr/data-fair/api/v1/datasets"
JEUX = {
    "desserte": "cced1-odftuf9crb2dvsa9om",
    "performance": "k9lr0llpdxbho37mz43fmrud",
    "tonnages": "9h8pu3ozd-ttw2yz69e3b86i",
    "destinations": "g5hu0gcq88w3vtmgyqiuhay9",
    "acteur": "34yfa-k9q2kzkmsw8j6l42-5",
    "decheteries": "sinoe-(r)-annuaire-des-decheteries-dma",
}
PAGE = 200

# (colonne de la base, champ SINOE) — « hg » : hors gravats, la grandeur que
# l'ADEME compare d'une collectivité à l'autre.
PERFORMANCES = (("omr", "perf_omr_hg"), ("tri", "perf_cs_men_hg"),
                ("verre", "perf_verre_hg"), ("decheterie", "perf_dech_hg"),
                ("total", "perf_dma_hg"))
QUARTILES = (25, 50, 75, 95)


def ensure_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS dechets_desserte (
            annee       INTEGER NOT NULL,
            insee       TEXT NOT NULL,
            code_acteur TEXT NOT NULL,
            acteur      TEXT,
            service     TEXT NOT NULL,
            PRIMARY KEY (annee, insee, code_acteur, service)
        );
        -- Kilos par habitant et par an, hors gravats sauf `total_gravats`.
        CREATE TABLE IF NOT EXISTS dechets_performance (
            code_acteur   TEXT NOT NULL,
            annee         INTEGER NOT NULL,
            population    INTEGER,   -- celle que l'ADEME a retenue pour diviser
            typologie     TEXT,      -- rural, touristique… : ce qui rend comparable
            omr           REAL,      -- ordures ménagères résiduelles
            tri           REAL,      -- collecte séparée : emballages, papiers ET verre
            verre         REAL,      -- déjà compté dans `tri`
            decheterie    REAL,
            total         REAL,
            total_gravats REAL,
            PRIMARY KEY (code_acteur, annee)
        );
        CREATE TABLE IF NOT EXISTS dechets_tonnes (
            code_acteur TEXT NOT NULL,
            annee       INTEGER NOT NULL,
            axe         TEXT NOT NULL,   -- 'dechet' | 'destination'
            libelle     TEXT NOT NULL,
            tonnes      REAL,
            PRIMARY KEY (code_acteur, annee, axe, libelle)
        );
        CREATE TABLE IF NOT EXISTS dechets_decheteries (
            code_acteur TEXT NOT NULL,
            annee       INTEGER NOT NULL,
            nom         TEXT NOT NULL,
            insee       TEXT,
            commune     TEXT,
            lieu        TEXT,
            ouverte_le  TEXT,
            gestion     TEXT,
            accepte     TEXT,
            PRIMARY KEY (code_acteur, annee, nom)
        );
        CREATE TABLE IF NOT EXISTS dechets_reperes (
            annee         INTEGER NOT NULL,
            indicateur    TEXT NOT NULL,   -- omr | tri | verre | decheterie | total
            portee        TEXT NOT NULL,   -- 'france' | 'departement'
            code          TEXT NOT NULL DEFAULT '',
            collectivites INTEGER,
            p25 REAL, p50 REAL, p75 REAL, p95 REAL,
            PRIMARY KEY (annee, indicateur, portee, code)
        );
    """)
    conn.commit()


def _appel(jeu: str, operation: str, **params) -> dict:
    url = (f"{ADEME}/{urllib.parse.quote(JEUX[jeu])}/{operation}?"
           + urllib.parse.urlencode(params))
    return fetch_json(url, source="sinoe", timeout=60)


def lignes(jeu: str, **params) -> list[dict]:
    """Toutes les lignes d'une requête. data-fair pagine par un lien `next`."""
    data = _appel(jeu, "lines", size=PAGE, **params)
    rendu = list(data.get("results", []))
    while data.get("next") and len(rendu) < data.get("total", 0):
        data = fetch_json(data["next"], source="sinoe", timeout=60)
        rendu += data.get("results", [])
    return rendu


def lignes_desserte(services: list[dict], insee: str) -> list[tuple]:
    return [(int(s["annee"]), insee, str(s["code_acteur"]), s.get("libelle_acteur"),
             s["libelle_service"]) for s in services if s.get("libelle_service")]


def lignes_performance(code: str, perf: list[dict], acteur: list[dict]) -> list[tuple]:
    """Une ligne par année d'enquête. La population vient d'un autre jeu : une
    année qui n'y figure pas garde ses kilos, et une population vide."""
    pop = {int(a["annee"]): a for a in acteur}
    return [(code, int(p["annee"]), pop.get(int(p["annee"]), {}).get("pop_adh_coll"),
             pop.get(int(p["annee"]), {}).get("typa1"),
             *(p.get(champ) for _, champ in PERFORMANCES), p.get("perf_dma_ag"))
            for p in perf]


def lignes_tonnes(code: str, axe: str, resultats: list[dict]) -> list[tuple]:
    """Tonnes avec gravats, sommées par libellé : SINOE peut rendre plusieurs
    lignes pour un même regroupement (une par origine du déchet)."""
    champ, libelle = (("dma2_ag", "libelle_regroupement_dechet") if axe == "dechet"
                      else ("dma4_ag", "libelle_regroupement_service_destination"))
    sommes: dict[tuple, float] = {}
    for r in resultats:
        if r.get(libelle) and r.get(champ) is not None:
            cle = (int(r["annee"]), r[libelle])
            sommes[cle] = sommes.get(cle, 0.0) + float(r[champ])
    return [(code, annee, axe, nom, tonnes) for (annee, nom), tonnes in sorted(sommes.items())]


def lignes_decheteries(code: str, annuaire: list[dict]) -> list[tuple]:
    """Le dernier millésime de l'annuaire seulement : il se republie chaque
    année en entier, et une déchèterie fermée n'y figure simplement plus."""
    dernier = max((int(d["ANNEE"]) for d in annuaire), default=None)
    return [(code, dernier, d["N_SERVICE"], d.get("C_COMM"), d.get("L_VILLE_SITE"),
             d.get("AD1_SITE"), d.get("D_OUV"), d.get("LOV_MO_GEST"),
             d.get("ORIGINE_DECHET_ACC"))
            for d in annuaire if int(d["ANNEE"]) == dernier and d.get("N_SERVICE")]


def ligne_repere(annee: int, indicateur: str, portee: str, code: str, agregat: dict) -> tuple:
    q = {c["key"]: c["value"] for c in agregat.get("metric", [])}
    return (annee, indicateur, portee, code, agregat.get("total"),
            *(q.get(k) for k in QUARTILES))


def releve_reperes(conn, annee: int, departement: str) -> int:
    """Quartiles de chaque grandeur parmi les collectivités qui la déclarent
    cette année-là. Une collectivité à zéro (elle n'exerce pas ce service) ne
    compte pas : elle tirerait le quartile vers une collecte qui n'existe pas."""
    reperes = []
    for indicateur, champ in PERFORMANCES:
        for portee, code, filtre in (("france", "", ""),
                                     ("departement", departement,
                                      f" AND code_departement:{departement}")):
            agregat = _appel("performance", "metric_agg", metric="percentiles", field=champ,
                             qs=f"annee:{annee} AND {champ}:>0{filtre}")
            reperes.append(ligne_repere(annee, indicateur, portee, code, agregat))
    _ecrire(conn, "INSERT OR REPLACE INTO dechets_reperes VALUES (?,?,?,?,?,?,?,?,?)", reperes)
    return len(reperes)


def _ecrire(conn, sql: str, lots: list[tuple]) -> None:
    """Écrit et VALIDE aussitôt. `fetch_json` archive chaque réponse par sa
    propre connexion : une écriture laissée ouverte ici la ferait attendre,
    puis renoncer (« database is locked »), à chaque appel suivant."""
    conn.executemany(sql, lots)
    conn.commit()


def releve_commune(conn, insee: str) -> str:
    services = lignes("desserte", qs=f"code_commune:{insee}", sort="-annee")
    if not services:
        return "commune absente de SINOE (« communes desservies »)"
    _ecrire(conn, "INSERT OR REPLACE INTO dechets_desserte VALUES (?,?,?,?,?)",
            lignes_desserte(services, insee))
    derniere = max(int(s["annee"]) for s in services)
    acteurs = sorted({str(s["code_acteur"]) for s in services if int(s["annee"]) == derniere})
    annees: set[int] = set()
    for code in acteurs:
        qs = f"code_acteur:{code}"
        perf = lignes_performance(code, lignes("performance", qs=qs), lignes("acteur", qs=qs))
        _ecrire(conn, "INSERT OR REPLACE INTO dechets_performance VALUES (?,?,?,?,?,?,?,?,?,?)",
                perf)
        annees |= {p[1] for p in perf}
        for axe, jeu in (("dechet", "tonnages"), ("destination", "destinations")):
            _ecrire(conn, "INSERT OR REPLACE INTO dechets_tonnes VALUES (?,?,?,?,?)",
                    lignes_tonnes(code, axe, lignes(jeu, qs=qs)))
        _ecrire(conn, "INSERT OR REPLACE INTO dechets_decheteries VALUES (?,?,?,?,?,?,?,?,?)",
                lignes_decheteries(code, lignes("decheteries", qs=f"C_ACTEUR:{code}", sort="-ANNEE")))
    # Les repères de la dernière année d'enquête seulement : c'est elle que la
    # page situe, et les quartiles d'une année close ne bougent plus.
    reperes = releve_reperes(conn, max(annees), insee[:2]) if annees else 0
    return (f"{len(acteurs)} collectivité(s), années {sorted(annees) or '—'}, "
            f"{reperes} repère(s)")


def run():
    conn = get_conn()
    ensure_tables(conn)
    echecs = []
    for insee in communes_du_step("dechets"):
        try:
            print(f"  [dechets] {insee} : {releve_commune(conn, insee)}")
        except Exception as e:          # une commune muette n'empêche pas les autres
            echecs.append(insee)
            print(f"  [dechets] {insee} : échec → {type(e).__name__}: {e}")
    conn.close()
    if echecs:
        raise RuntimeError(f"communes en échec : {', '.join(echecs)}")


def show_stats():
    conn = get_conn(read_only=True)
    for r in conn.execute("""
        SELECT p.code_acteur, MAX(d.acteur), COUNT(DISTINCT p.annee), MIN(p.annee), MAX(p.annee)
          FROM dechets_performance p LEFT JOIN dechets_desserte d USING (code_acteur)
         GROUP BY p.code_acteur"""):
        print(f"  {r[0]} {r[1] or '—'} — {r[2]} année(s) d'enquête, {r[3]} → {r[4]}")
    for table in ("dechets_tonnes", "dechets_decheteries", "dechets_reperes"):
        print(f"  {table} : {conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]} ligne(s)")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="SINOE — les déchets ménagers")
    ap.add_argument("--stats", action="store_true")
    show_stats() if ap.parse_args().stats else run()
