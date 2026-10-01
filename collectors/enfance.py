"""
enfance.py — Grandir ici : les élèves de chaque école rentrée après rentrée, sa
position sociale, et l'accueil des moins de trois ans.

Trois relevés, trois mailles — à ne jamais confondre à l'affichage :
  1. `ecoles_effectifs` — élèves et classes PAR ÉCOLE et par rentrée (ministère
     de l'éducation nationale, `fr-en-ecoles-effectifs-nb_classes`). Une école
     n'est pas une commune : elle scolarise aussi les enfants des communes
     voisines, et ceux d'ici peuvent être scolarisés ailleurs.
  2. `ecoles_ips` — l'indice de position sociale de l'école. Deux jeux qui se
     suivent (avant et après la rentrée 2022) ; seul le second porte les
     moyennes nationale et départementale du secteur public.
  3. `accueil_petite_enfance` — places d'accueil des moins de 3 ans et taux de
     couverture (CAF). La CAF ne publie la commune qu'au-dessus d'un seuil de
     taille : la maille est l'INTERCOMMUNALITÉ, avec le département et la France
     pour repères.

Les écoles sont celles que `education.py` a recensées (l'UAI en est la clé) : ce
step se joue après lui. Le jeu des effectifs porte lui aussi un code commune,
mais il n'est pas fiable — on y trouve un code POSTAL à la place du code INSEE.

Les lignes se remplacent à chaque passe : un constat de rentrée se corrige.

Usage :
  python3 -m collectors.enfance
  python3 -m collectors.enfance --stats
"""
from __future__ import annotations

import argparse
import urllib.parse

from .archive import fetch_json
from .config import DEPARTEMENT, EPCI_SIREN, communes_du_step
from .db import get_conn

EDUC = "https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets"
CAF = "https://data.caf.fr/api/explore/v2.1/catalog/datasets"
IPS_JEUX = ("fr-en-ips_ecoles_v2", "fr-en-ips-ecoles-ap2022")


def ensure_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ecoles_effectifs (
            uai         TEXT NOT NULL,
            rentree     INTEGER NOT NULL,
            eleves      INTEGER,
            maternelle  INTEGER,
            classes     INTEGER,
            PRIMARY KEY (uai, rentree)
        );
        CREATE TABLE IF NOT EXISTS ecoles_ips (
            uai                    TEXT NOT NULL,
            rentree                TEXT NOT NULL,   -- « 2024-2025 »
            ips                    REAL,
            ips_france_public      REAL,   -- NULL avant la rentrée 2022
            ips_departement_public REAL,
            PRIMARY KEY (uai, rentree)
        );
        CREATE TABLE IF NOT EXISTS accueil_petite_enfance (
            portee      TEXT NOT NULL,   -- 'epci' | 'departement' | 'france'
            code        TEXT NOT NULL DEFAULT '',
            annee       INTEGER NOT NULL,
            creche      INTEGER,   -- places en établissement d'accueil
            assistantes INTEGER,   -- places chez les assistantes maternelles
            domicile    INTEGER,   -- garde à domicile
            ecole       INTEGER,   -- école avant 3 ans
            total       INTEGER,
            taux        REAL,      -- places pour 100 enfants de moins de 3 ans
            PRIMARY KEY (portee, code, annee)
        );
    """)
    conn.commit()


def ods(base: str, jeu: str, source: str, **params) -> list[dict]:
    url = f"{base}/{jeu}/records?" + urllib.parse.urlencode({"limit": 100, **params})
    return fetch_json(url, source=source, timeout=60).get("results", [])


def nombre(valeur) -> float | None:
    """Les deux jeux d'IPS ne s'accordent pas : un nombre ici, une chaîne là."""
    try:
        return float(valeur) if valeur not in (None, "") else None
    except (TypeError, ValueError):
        return None


def entier(valeur) -> int | None:
    n = nombre(valeur)
    return None if n is None else int(n)


def ecoles_suivies(conn, communes: list[str]) -> list[str]:
    """Les UAI des écoles du premier degré recensées dans ces communes."""
    marques = ",".join("?" * len(communes))
    return [r[0] for r in conn.execute(
        f"SELECT uai FROM etablissements_scolaires WHERE uai IS NOT NULL"
        f" AND json_extract(raw_data, '$.type_etablissement') = 'Ecole'"
        f" AND json_extract(raw_data, '$.code_commune') IN ({marques}) ORDER BY uai", communes)]


def ligne_effectif(l: dict) -> tuple:
    return (l["numero_ecole"], int(l["rentree_scolaire"]), entier(l.get("nombre_total_eleves")),
            entier(l.get("nombre_eleves_preelementaire_hors_ulis")),
            entier(l.get("nombre_total_classes")))


def ligne_ips(l: dict) -> tuple:
    return (l["uai"], l["rentree_scolaire"], nombre(l.get("ips")),
            nombre(l.get("ips_national_public")), nombre(l.get("ips_departemental_public")))


def lignes_accueil(portee: str, code: str, places: list[dict], taux: list[dict],
                   suffixe: str) -> list[tuple]:
    """Places et taux d'une même maille, réunis par année. Les jeux de la CAF
    viennent par deux — le courant et l'historique — qui se recouvrent sur une
    année, où ils ne s'accordent pas toujours (57,4 et 57,1 places pour 100
    enfants en 2022 pour une même intercommunalité). La première ligne lue pour
    une année est gardée : l'appelant passe le COURANT d'abord, celui dont
    viennent aussi les repères du département et de la France."""
    par_annee: dict[int, dict] = {}
    for l in places:
        par_annee.setdefault(int(l["annee"]), {}).setdefault("places", l)
    for l in taux:
        par_annee.setdefault(int(l["annee"]), {}).setdefault("taux", l)
    rendu = []
    for annee, d in sorted(par_annee.items()):
        p, t = d.get("places", {}), d.get("taux", {})
        rendu.append((portee, code, annee, entier(p.get(f"pl_eaje_{suffixe}")),
                      entier(p.get(f"pl_am_ind_{suffixe}")), entier(p.get(f"pl_gad_ind_{suffixe}")),
                      entier(p.get(f"pl_prescol_{suffixe}")), entier(p.get(f"tot_offre_{suffixe}")),
                      nombre(t.get(f"txcouv_{suffixe}"))))
    return rendu


def releve_ecoles(conn, communes: list[str]) -> str:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='etablissements_scolaires'").fetchone():
        return "aucune école recensée — jouer `education` d'abord"
    ecoles = ecoles_suivies(conn, communes)
    # Tout lire, puis écrire : `fetch_json` archive chaque réponse par sa propre
    # connexion, et une écriture laissée ouverte ici la ferait renoncer.
    effectifs, ips = [], []
    for uai in ecoles:
        effectifs += [ligne_effectif(l) for l in ods(
            EDUC, "fr-en-ecoles-effectifs-nb_classes", "education",
            where=f"numero_ecole='{uai}'", order_by="rentree_scolaire")]
        for jeu in IPS_JEUX:
            ips += [ligne_ips(l) for l in ods(EDUC, jeu, "education", where=f"uai='{uai}'",
                                              order_by="rentree_scolaire")]
    conn.executemany("INSERT OR REPLACE INTO ecoles_effectifs VALUES (?,?,?,?,?)", effectifs)
    conn.executemany("INSERT OR REPLACE INTO ecoles_ips VALUES (?,?,?,?,?)", ips)
    conn.commit()
    return (f"{len(ecoles)} école(s), {len(effectifs)} rentrée(s), "
            f"{len(ips)} indice(s) de position sociale")


def releve_accueil(conn) -> str:
    if not EPCI_SIREN:
        return "pas d'intercommunalité déclarée : la CAF ne publie pas cette commune seule"
    epci = f"numepci='{EPCI_SIREN}'"
    lignes = lignes_accueil(
        "epci", EPCI_SIREN,
        ods(CAF, "nbpla_pe_epci", "caf", where=epci) + ods(CAF, "nbpla_pe_epci_hist", "caf", where=epci),
        ods(CAF, "txcouv_pe_epci", "caf", where=epci) + ods(CAF, "txcouv_pe_epci_hist", "caf", where=epci),
        "epci")
    lignes += lignes_accueil("departement", DEPARTEMENT, [],
                             ods(CAF, "txcouv_pe_dep", "caf", where=f"numdep='{DEPARTEMENT}'"), "dep")
    lignes += lignes_accueil("france", "", [], ods(CAF, "txcouv_pe_nat", "caf"), "nat")
    conn.executemany("INSERT OR REPLACE INTO accueil_petite_enfance VALUES (?,?,?,?,?,?,?,?,?)",
                     lignes)
    conn.commit()
    ici = [l for l in lignes if l[0] == "epci"]
    return (f"{len(ici)} année(s) pour l'intercommunalité" if ici
            else "intercommunalité absente des séries de la CAF")


def run():
    conn = get_conn()
    ensure_tables(conn)
    communes = communes_du_step("enfance")
    etapes = (("écoles", lambda: releve_ecoles(conn, communes)),
              ("accueil des moins de 3 ans", lambda: releve_accueil(conn)))
    echecs = []
    for nom, etape in etapes:
        try:
            print(f"  [enfance] {nom} : {etape()}")
        except Exception as e:          # une source muette n'empêche pas l'autre
            echecs.append(nom)
            print(f"  [enfance] {nom} : échec → {type(e).__name__}: {e}")
    conn.close()
    if echecs:
        raise RuntimeError(f"relevés en échec : {', '.join(echecs)}")


def show_stats():
    conn = get_conn(read_only=True)
    for r in conn.execute("SELECT uai, COUNT(*), MIN(rentree), MAX(rentree) FROM ecoles_effectifs"
                          " GROUP BY uai"):
        print(f"  {r[0]} — {r[1]} rentrée(s), {r[2]} → {r[3]}")
    for r in conn.execute("SELECT portee, code, COUNT(*), MIN(annee), MAX(annee)"
                          " FROM accueil_petite_enfance GROUP BY portee, code"):
        print(f"  accueil {r[0]} {r[1] or ''} — {r[2]} année(s), {r[3]} → {r[4]}")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Écoles et accueil du jeune enfant")
    ap.add_argument("--stats", action="store_true")
    show_stats() if ap.parse_args().stats else run()
