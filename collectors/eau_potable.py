"""
eau_potable.py — L'eau du robinet : les réseaux qui desservent la commune, et le
contrôle sanitaire de ce qui en sort (Hub'Eau, API qualité de l'eau potable).

À ne pas confondre avec `qualite_eau.py`, qui mesure les RIVIÈRES : une station
de cours d'eau ne dit rien de l'eau que l'on boit. Le 30/09/2026, les 91 600
analyses de l'instance de Lasalle étaient toutes des mesures de rivières, prises
côté Aigoual — aucune au robinet, aucune dans la commune.

Deux temps :
  1. `communes_udi` : quels réseaux (UDI) desservent chaque commune suivie en
     profondeur, quartier par quartier, année par année. Une commune peut en
     avoir plusieurs, chacun avec son maître d'ouvrage et son prix — c'est le
     cas de Lasalle (bourg en régie, écarts au syndicat).
  2. `resultats_dis` : les prélèvements du contrôle sanitaire (ARS) sur chacun
     de ces réseaux, et leurs résultats paramètre par paramètre. Interrogés par
     RÉSEAU et non par commune : un réseau intercommunal est souvent prélevé
     dans une commune voisine, et le chercher par commune le rend vide.

Clés naturelles, INSERT OR IGNORE — jamais d'écrasement. Collecte incrémentale :
chaque réseau repart du dernier prélèvement que SA requête a rapporté, noté dans
`eau_potable_suivi`. Pas du dernier prélèvement qui lui est rattaché : un
prélèvement partagé, arrivé par la requête d'un réseau voisin, lui donnerait une
date récente, et sa propre histoire ne serait jamais collectée — c'est arrivé au
premier essai, le 30/09/2026 : le réseau de Thoiras avait perdu 2016-2020. Découpée par année :
Hub'Eau refuse de paginer au-delà de 20 000 résultats par requête.

Usage :
  python3 -m collectors.eau_potable                     # collecte incrémentale
  python3 -m collectors.eau_potable --since 2016-01-01  # historique complet
  python3 -m collectors.eau_potable --stats             # état par réseau
"""
import argparse
import datetime as dt
import time
import urllib.parse

from .config import communes_du_step
from .db import get_conn
from .qualite_eau import _get_json

API = "https://hubeau.eaufrance.fr/api/v1/qualite_eau_potable"
PAGE_SIZE = 5000
# Le contrôle sanitaire publié par Hub'Eau commence en 2016.
DEBUT = "2016-01-01"

CHAMPS_RESULTAT = (
    "code_prelevement,date_prelevement,code_commune,nom_commune,nom_uge,"
    "nom_distributeur,nom_moa,conclusion_conformite_prelevement,"
    "conformite_limites_bact_prelevement,conformite_limites_pc_prelevement,"
    "conformite_references_bact_prelevement,conformite_references_pc_prelevement,"
    "reseaux,code_parametre,libelle_parametre,code_type_parametre,"
    "code_lieu_analyse,resultat_alphanumerique,resultat_numerique,libelle_unite,"
    "limite_qualite_parametre,reference_qualite_parametre"
)


def ensure_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS eau_potable_udi (
            annee           TEXT NOT NULL,
            code_commune    TEXT NOT NULL,
            nom_quartier    TEXT NOT NULL DEFAULT '',
            code_reseau     TEXT NOT NULL,
            nom_reseau      TEXT,
            debut_alim      TEXT,
            created_at      TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (annee, code_commune, nom_quartier, code_reseau)
        );
        CREATE TABLE IF NOT EXISTS eau_potable_prelevements (
            code_prelevement    TEXT PRIMARY KEY,
            date_prelevement    TEXT,
            code_commune        TEXT,   -- commune du POINT de prélèvement
            nom_commune         TEXT,
            nom_uge             TEXT,   -- unité de gestion
            nom_distributeur    TEXT,   -- l'exploitant (régie, délégataire)
            nom_moa             TEXT,   -- le maître d'ouvrage (commune, syndicat, EPCI)
            conclusion          TEXT,
            limites_bact        TEXT,   -- C conforme, N non conforme, S sans objet
            limites_pc          TEXT,
            references_bact     TEXT,
            references_pc       TEXT,
            created_at          TEXT DEFAULT (datetime('now'))
        );
        -- Un prélèvement peut valoir pour plusieurs réseaux.
        CREATE TABLE IF NOT EXISTS eau_potable_prelevement_reseaux (
            code_prelevement    TEXT NOT NULL
                REFERENCES eau_potable_prelevements(code_prelevement),
            code_reseau         TEXT NOT NULL,
            PRIMARY KEY (code_prelevement, code_reseau)
        );
        CREATE TABLE IF NOT EXISTS eau_potable_resultats (
            code_prelevement    TEXT NOT NULL
                REFERENCES eau_potable_prelevements(code_prelevement),
            code_parametre      TEXT NOT NULL,
            code_lieu_analyse   TEXT NOT NULL DEFAULT '',   -- L labo, T terrain
            libelle_parametre   TEXT,
            code_type_parametre TEXT,
            resultat_alpha      TEXT,   -- tel que publié : « <0,005 », « 12 »
            resultat_numerique  REAL,   -- ⚠ 0.0 pour « <seuil » : lire resultat_alpha
            unite               TEXT,
            limite_qualite      TEXT,
            reference_qualite   TEXT,
            -- Le libellé est dans la clé : une microcystine totale, dissoute ou
            -- dans la biomasse porte le MÊME code paramètre, et seul le libellé
            -- les distingue. Sans lui, deux mesures sur trois disparaissaient.
            PRIMARY KEY (code_prelevement, code_parametre, code_lieu_analyse,
                         libelle_parametre)
        );
        -- Jusqu'où la requête de CE réseau a été lue, année close par année close.
        CREATE TABLE IF NOT EXISTS eau_potable_suivi (
            code_reseau         TEXT PRIMARY KEY,
            dernier_prelevement TEXT NOT NULL,
            releve_le           TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_eau_potable_prel_date
            ON eau_potable_prelevements(date_prelevement);
        CREATE INDEX IF NOT EXISTS idx_eau_potable_res_param
            ON eau_potable_resultats(code_parametre);
    """)
    conn.commit()


def ligne_udi(u: dict) -> tuple:
    return (str(u["annee"]), u["code_commune"], u.get("nom_quartier") or "",
            u["code_reseau"], u.get("nom_reseau"), u.get("debut_alim"))


def ligne_prelevement(r: dict) -> tuple:
    return (r["code_prelevement"], r.get("date_prelevement"), r.get("code_commune"),
            r.get("nom_commune"), r.get("nom_uge"), r.get("nom_distributeur"),
            r.get("nom_moa"), r.get("conclusion_conformite_prelevement"),
            r.get("conformite_limites_bact_prelevement"),
            r.get("conformite_limites_pc_prelevement"),
            r.get("conformite_references_bact_prelevement"),
            r.get("conformite_references_pc_prelevement"))


def ligne_resultat(r: dict) -> tuple:
    return (r["code_prelevement"], r["code_parametre"], r.get("code_lieu_analyse") or "",
            r.get("libelle_parametre"), r.get("code_type_parametre"),
            r.get("resultat_alphanumerique"), r.get("resultat_numerique"),
            r.get("libelle_unite"), r.get("limite_qualite_parametre"),
            r.get("reference_qualite_parametre"))


def enregistrer_resultats(conn, lignes: list[dict], code_reseau: str) -> int:
    """Écrit une page de `resultats_dis`. Rend le nombre de résultats nouveaux.

    Le réseau interrogé est toujours rattaché, même si la réponse n'en liste
    pas : c'est à son titre que le prélèvement a été demandé.
    """
    nouveaux = 0
    for r in lignes:
        conn.execute(
            "INSERT OR IGNORE INTO eau_potable_prelevements VALUES"
            " (?,?,?,?,?,?,?,?,?,?,?,?, datetime('now'))", ligne_prelevement(r))
        reseaux = {x["code"] for x in r.get("reseaux") or [] if x.get("code")}
        for code in reseaux | {code_reseau}:
            conn.execute(
                "INSERT OR IGNORE INTO eau_potable_prelevement_reseaux VALUES (?,?)",
                (r["code_prelevement"], code))
        cur = conn.execute(
            "INSERT OR IGNORE INTO eau_potable_resultats VALUES (?,?,?,?,?,?,?,?,?,?)",
            ligne_resultat(r))
        nouveaux += cur.rowcount
    return nouveaux


def fetch_udi(conn, communes: list[str]) -> list[str]:
    """Les réseaux qui desservent ces communes, toutes années confondues."""
    for insee in communes:
        url = f"{API}/communes_udi?{urllib.parse.urlencode({'code_commune': insee, 'size': 1000})}"
        while url:
            data = _get_json(url)
            conn.executemany(
                "INSERT OR IGNORE INTO eau_potable_udi"
                " (annee, code_commune, nom_quartier, code_reseau, nom_reseau, debut_alim)"
                " VALUES (?,?,?,?,?,?)",
                [ligne_udi(u) for u in data.get("data", [])])
            url = data.get("next")
        conn.commit()
    marques = ",".join("?" * len(communes))
    return [r[0] for r in conn.execute(
        f"SELECT DISTINCT code_reseau FROM eau_potable_udi"
        f" WHERE code_commune IN ({marques}) ORDER BY code_reseau", communes)]


def depart(conn, code_reseau: str, since: str | None) -> str:
    """Date de reprise : `since`, sinon le dernier prélèvement lu par la
    requête de ce réseau — jamais celui d'un rattachement (cf. en-tête)."""
    if since:
        return since
    row = conn.execute("SELECT dernier_prelevement FROM eau_potable_suivi"
                       " WHERE code_reseau=?", (code_reseau,)).fetchone()
    return (row[0] if row else DEBUT)[:10]


def noter_suivi(conn, code_reseau: str, lignes: list[dict], deja: str | None) -> str | None:
    """Avance le suivi du réseau jusqu'au plus récent prélèvement de `lignes`."""
    dates = [r["date_prelevement"] for r in lignes if r.get("date_prelevement")]
    plus_recent = max([d for d in (*dates, deja) if d], default=None)
    if plus_recent and plus_recent != deja:
        conn.execute(
            "INSERT INTO eau_potable_suivi (code_reseau, dernier_prelevement)"
            " VALUES (?,?) ON CONFLICT(code_reseau) DO UPDATE SET"
            " dernier_prelevement=excluded.dernier_prelevement,"
            " releve_le=datetime('now')", (code_reseau, plus_recent))
    return plus_recent


def fetch_resultats(conn, code_reseau: str, since: str) -> int:
    nouveaux = 0
    deja = None
    for annee in range(int(since[:4]), dt.date.today().year + 1):
        debut = since if annee == int(since[:4]) else f"{annee}-01-01"
        params = {"code_reseau": code_reseau, "date_min_prelevement": debut,
                  "date_max_prelevement": f"{annee}-12-31",
                  "size": PAGE_SIZE, "fields": CHAMPS_RESULTAT}
        url = f"{API}/resultats_dis?{urllib.parse.urlencode(params)}"
        lues = []
        while url:
            data = _get_json(url)
            nouveaux += enregistrer_resultats(conn, data.get("data", []), code_reseau)
            lues += data.get("data", [])
            conn.commit()
            url = data.get("next")
            time.sleep(0.5)
        # Le suivi n'avance qu'une fois l'année lue en entier : une page qui
        # échoue en cours d'année laisse la reprise au début de cette année.
        deja = noter_suivi(conn, code_reseau, lues, deja)
        conn.commit()
    return nouveaux


def run(since: str | None = None):
    conn = get_conn()
    ensure_tables(conn)
    communes = communes_du_step("eau_potable")
    reseaux = fetch_udi(conn, communes)
    print(f"[eau_potable] {len(reseaux)} réseau(x) pour {len(communes)} commune(s)")
    total = 0
    for code in reseaux:
        nom = conn.execute("SELECT nom_reseau FROM eau_potable_udi WHERE code_reseau=?"
                           " ORDER BY annee DESC LIMIT 1", (code,)).fetchone()[0]
        try:
            n = fetch_resultats(conn, code, depart(conn, code, since))
        except Exception as e:
            print(f"  [eau_potable] échec {code} {nom} → {e}")
            continue
        total += n
        print(f"  ✓ {code} {nom} — {n} nouveau(x) résultat(s)")
    print(f"[eau_potable] OK — {total} résultats insérés")
    conn.close()


def show_stats():
    conn = get_conn(read_only=True)
    print("Réseaux desservant les communes suivies (dernière année publiée) :")
    for r in conn.execute("""
        SELECT code_commune, code_reseau, nom_reseau,
               group_concat(DISTINCT NULLIF(nom_quartier,'')), MIN(annee), MAX(annee)
        FROM eau_potable_udi GROUP BY code_commune, code_reseau"""):
        print(f"  {r[0]} {r[1]} {r[2] or '—':42} {r[4]}→{r[5]}  quartiers : {r[3] or '—'}")
    print("\nContrôle sanitaire par réseau :")
    for r in conn.execute("""
        SELECT r.code_reseau, COUNT(DISTINCT p.code_prelevement),
               MIN(p.date_prelevement), MAX(p.date_prelevement),
               SUM(p.limites_bact='N'), SUM(p.limites_pc='N'),
               group_concat(DISTINCT p.nom_moa), group_concat(DISTINCT p.nom_distributeur)
        FROM eau_potable_prelevement_reseaux r JOIN eau_potable_prelevements p
             USING(code_prelevement)
        GROUP BY r.code_reseau"""):
        print(f"  {r[0]}  {r[1]:>4} prélèvements  {(r[2] or '—')[:10]} → {(r[3] or '—')[:10]}"
              f"  hors limites : bact {r[4]}, physico-chimie {r[5]}")
        print(f"      maître d'ouvrage : {r[6] or '—'} · exploitant : {r[7] or '—'}")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Hub'Eau — l'eau du robinet")
    ap.add_argument("--since", default=None,
                    help="date plancher AAAA-MM-JJ (défaut : incrémental)")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()
    if args.stats:
        show_stats()
    else:
        run(args.since)
