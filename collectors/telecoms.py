"""
telecoms.py — Internet et téléphone : la fibre commune par commune, les sites
mobiles alentour, leurs pannes déclarées, et la qualité du réseau fibre.

Cinq relevés, tous ouverts, tous de l'ARCEP :
  1. `telecoms_fixe` — éligibilité des locaux par technologie (fibre, cuivre,
     4G fixe, satellite…), trimestre par trimestre depuis 2019 (Ma connexion
     internet, statistiques communales). La série entière se relève au premier
     passage ; ensuite, seuls les trimestres nouveaux.
  2. `telecoms_fixe_oi` — la zone (publique ou privée) et l'opérateur
     d'infrastructure du réseau fibre de la commune (déploiements, maille
     commune). C'est lui qui répond des pannes du réseau.
  3. `telecoms_qualite_ftth` — taux de pannes, d'abonnés touchés et d'échecs de
     raccordement, PAR RÉSEAU et sur six mois glissants. Toutes les lignes sont
     gardées : situer un réseau suppose de connaître les autres.
  4. `telecoms_sites_mobiles` — les sites mobiles dans un rayon autour de la
     commune (`collecte.telecoms.rayon_km`, 10 km par défaut), avec leurs
     technologies et le programme dont ils relèvent (zones blanches, New Deal).
  5. `telecoms_indisponibilites` — les sites que les opérateurs déclarent hors
     service, jour par jour, pour les communes de fond. Chaque jour LU est noté
     dans `telecoms_indispo_jours`, même vide : zéro panne est une réponse, un
     jour non lu n'en est pas une.

Aucune source ne publie les pannes de la fibre commune par commune : le relevé 3
est le plus fin qui existe, et il vaut pour tout un réseau départemental.

⚠️ RUPTURE DE SÉRIE, 2ᵉ trimestre 2026 : l'éligibilité au cuivre tombe à zéro
dans 25 805 communes à la fois (43,7 → 23,4 millions de locaux). C'est un
changement de méthode de l'ARCEP, pas une fermeture — le calendrier de
fermeture ne place pas Lasalle dans un lot. Ne pas lire `elig_cu = 0` comme une
coupure sans le fichier de fermeture.

Usage :
  python3 -m collectors.telecoms
  python3 -m collectors.telecoms --stats
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import datetime as dt
import io
import json
import math
import re
import struct
import time
import urllib.request
import zipfile

from .config import CENTROID, HEADERS, NATIONAL_STORE, TELECOMS_RAYON_KM, communes_du_step
from .db import get_conn
from .national_store import ecrire_atomiquement, est_frais

MCI = "https://data.arcep.fr/fixe/maconnexioninternet"
MCI_S3 = "https://arcep.s3.rbx.io.cloud.ovh.net/fixe/maconnexioninternet"
MOBILE = "https://data.arcep.fr/mobile"
INDISPO = ("https://arcep.s3.rbx.io.cloud.ovh.net/sites-indisponibles/all/"
           "{j}/raw{j}.geojson")
DATAGOUV = "https://www.data.gouv.fr/api/1/datasets/{}/"
CACHE = NATIONAL_STORE / "arcep"
# Un an d'historique au premier passage : les relevés quotidiens remontent plus
# loin, mais une année suffit à dire si un site tombe souvent.
INDISPO_RECUL_JOURS = 365

# Les colonnes ont changé de nom en 2021 (`elig_4fg` → `elig_4gf`).
ALIAS = {"elig_4fg": "elig_4gf"}
TECHNOS = ("elig_ftth", "elig_coax", "elig_cu", "elig_thdr", "elig_4gf",
           "elig_hdr", "elig_sat")


def ensure_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS telecoms_fixe (
            trimestre   TEXT NOT NULL,      -- « 2026_T2 »
            insee       TEXT NOT NULL,
            date        TEXT,               -- fin de trimestre publiée
            locaux      INTEGER,
            elig_ftth INTEGER, elig_coax INTEGER, elig_cu INTEGER, elig_thdr INTEGER,
            elig_4gf INTEGER, elig_hdr INTEGER, elig_sat INTEGER,
            -- meilleure technologie THD disponible, local par local
            mt_ftth INTEGER, mt_4gf INTEGER, mt_sat INTEGER, mt_autre INTEGER,
            PRIMARY KEY (trimestre, insee)
        );
        CREATE TABLE IF NOT EXISTS telecoms_fixe_oi (
            trimestre   TEXT NOT NULL,
            insee       TEXT NOT NULL,
            zone        TEXT,               -- zipu : initiative publique ; zipri : privée
            oi          TEXT,               -- code opérateur d'infrastructure (WIGA…)
            locaux      INTEGER,
            ftth        INTEGER,
            couverture  REAL,               -- en %, telle que publiée
            PRIMARY KEY (trimestre, insee)
        );
        CREATE TABLE IF NOT EXISTS telecoms_operateurs (
            code        TEXT PRIMARY KEY,
            nom         TEXT
        );
        CREATE TABLE IF NOT EXISTS telecoms_qualite_ftth (
            periode     TEXT NOT NULL,      -- « 10/25 - 03/26 »
            oi          TEXT NOT NULL,
            maison_mere TEXT,
            perimetre   TEXT NOT NULL,      -- reseau | departement
            dep_code    TEXT NOT NULL,
            taux_pannes REAL,
            taux_echecs_raccordement REAL,
            taux_echecs_raccordement_retraite REAL,
            taux_abonnes_avec_panne REAL,
            PRIMARY KEY (periode, oi, perimetre, dep_code)
        );
        CREATE TABLE IF NOT EXISTS telecoms_sites_mobiles (
            trimestre   TEXT NOT NULL,
            code_op     TEXT NOT NULL,
            nom_op      TEXT,
            num_site    TEXT NOT NULL,
            id_site_partage TEXT,
            id_station_anfr TEXT,
            insee_com   TEXT,
            nom_com     TEXT,
            latitude    REAL,
            longitude   REAL,
            distance_km REAL,
            site_2g INTEGER, site_3g INTEGER, site_4g INTEGER, site_5g INTEGER,
            site_zb     INTEGER,            -- programme zones blanches centres-bourgs
            site_dcc    INTEGER,            -- dispositif de couverture ciblée (New Deal)
            site_strategique INTEGER,
            PRIMARY KEY (trimestre, code_op, num_site)
        );
        CREATE TABLE IF NOT EXISTS telecoms_indisponibilites (
            jour        TEXT NOT NULL,
            operateur   TEXT NOT NULL,
            station_anfr TEXT NOT NULL,
            code_insee  TEXT,
            voix TEXT, data TEXT, voix4g TEXT, data4g TEXT, data5g TEXT,
            raison      TEXT,
            detail      TEXT,
            debut       TEXT,
            fin         TEXT,
            PRIMARY KEY (jour, operateur, station_anfr)
        );
        -- Chaque jour lu, même sans panne dans la commune : zéro est une réponse.
        CREATE TABLE IF NOT EXISTS telecoms_indispo_jours (
            jour        TEXT PRIMARY KEY,
            sites_france INTEGER,
            releve_le   TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()


# ── Accès ────────────────────────────────────────────────────────────────────

def _get(url: str, timeout: int = 300, retries: int = 3) -> bytes:
    for tentative in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code < 500 or tentative == retries - 1:
                raise
        except (TimeoutError, ConnectionError, urllib.error.URLError):
            if tentative == retries - 1:
                raise
        time.sleep(5 * (tentative + 1))


def _en_cache(nom: str, url: str, jours: int | None) -> bytes:
    """Un fichier national, lu une fois pour toutes les instances."""
    chemin = CACHE / nom
    if est_frais(chemin, jours):
        return chemin.read_bytes()
    contenu = _get(url)
    ecrire_atomiquement(chemin, contenu)
    return contenu


def _sous_repertoires(url_index: str) -> list[str]:
    """Les trimestres « AAAA_TN » d'un index ARCEP (pages statiques)."""
    html = _get(url_index, timeout=60).decode("utf-8", "replace")
    return sorted(set(re.findall(r'href="(\d{4}_T\d)/', html)))


def nombre(valeur) -> float | None:
    """« 46,21473 », « 1322 », « NA », « » → nombre ou None."""
    if valeur is None:
        return None
    s = str(valeur).strip().replace(",", ".")
    if s in ("", "NA", "nan"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def entier(valeur) -> int | None:
    n = nombre(valeur)
    return None if n is None else int(round(n))


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(a))


def _texte(contenu: bytes) -> str:
    """UTF-8 si le fichier l'est, sinon Windows-1252 : l'ARCEP publie les deux,
    et un décodage forcé en UTF-8 écrivait « Ensemble du r�seau »."""
    try:
        return contenu.decode("utf-8-sig")
    except UnicodeDecodeError:
        return contenu.decode("cp1252", "replace")


def _csv(contenu: bytes, sep: str = ";") -> list[dict]:
    texte = _texte(contenu)
    return [{ALIAS.get(k, k): v for k, v in r.items()}
            for r in csv.DictReader(io.StringIO(texte), delimiter=sep)]


# ── 1. Éligibilité par technologie ───────────────────────────────────────────

def lignes_fixe(techno: list[dict], meilleure: list[dict], communes: set[str],
                trimestre: str) -> list[tuple]:
    mt = {r["code_insee"]: r for r in meilleure if r.get("type") == "all"}
    lignes = []
    for r in techno:
        if r.get("type") != "all" or r.get("code_insee") not in communes:
            continue
        m = mt.get(r["code_insee"], {})
        autres = sum(entier(m.get(k)) or 0 for k in
                     ("elig_coax", "elig_cu_30", "elig_thdr", "elig_cu_8", "elig_hdr"))
        lignes.append((trimestre, r["code_insee"], r.get("date"), entier(r.get("nbr")),
                       *(entier(r.get(k)) for k in TECHNOS),
                       entier(m.get("elig_ftth")), entier(m.get("elig_4gf")),
                       entier(m.get("elig_sat")), autres if m else None))
    return lignes


def releve_fixe(conn, communes: list[str]) -> int:
    connus = {r[0] for r in conn.execute("SELECT DISTINCT trimestre FROM telecoms_fixe")}
    ecrits = 0
    for t in _sous_repertoires(f"{MCI}/statistiques/index.html"):
        if t in connus:
            continue
        base = f"{MCI_S3}/statistiques/{t}/commune"
        try:
            techno = _csv(_en_cache(f"mci/{t}_commune_techno.csv",
                                    f"{base}/commune_techno.csv", None))
            try:
                meilleure = _csv(_en_cache(f"mci/{t}_commune_meilleure_techno_thd.csv",
                                           f"{base}/commune_meilleure_techno_thd.csv", None))
            except urllib.error.HTTPError:
                meilleure = []          # les premiers trimestres ne la publient pas
        except urllib.error.HTTPError as e:
            print(f"  [telecoms] {t} : {e}")
            continue
        lignes = lignes_fixe(techno, meilleure, set(communes), t)
        conn.executemany(f"INSERT OR IGNORE INTO telecoms_fixe VALUES ({','.join('?' * 15)})",
                         lignes)
        conn.commit()
        ecrits += len(lignes)
    return ecrits


# ── 2. Zone et opérateur d'infrastructure ────────────────────────────────────

def lire_dbf(contenu: bytes, garder) -> list[dict]:
    """Les enregistrements d'un .dbf (dBase III) que `garder(ligne)` retient."""
    n, entete, taille = struct.unpack("<xxxxIHH20x", contenu[:32])
    champs, pos = [], 32
    while contenu[pos] != 0x0D:
        b = contenu[pos:pos + 32]
        champs.append((b[:11].split(b"\0")[0].decode("latin-1"), b[16]))
        pos += 32
    lignes = []
    for i in range(n):
        rec = contenu[entete + i * taille: entete + (i + 1) * taille]
        if rec[:1] == b"*":             # enregistrement effacé
            continue
        ligne, p = {}, 1
        for nom, longueur in champs:
            ligne[nom] = rec[p:p + longueur].decode("utf-8", "replace").strip()
            p += longueur
        if garder(ligne):
            lignes.append(ligne)
    return lignes


def _ressource(jeu: str, motif: str) -> tuple[str, str] | None:
    """(titre, url) de la ressource la plus récente dont le titre suit `motif`."""
    meta = json.loads(_get(DATAGOUV.format(jeu), timeout=60))
    for r in meta.get("resources", []):      # data.gouv les classe du plus récent au plus ancien
        if re.search(motif, r.get("title") or ""):
            return r["title"], r["url"]
    return None


def releve_oi(conn, communes: list[str]) -> int:
    res = _ressource("le-marche-du-haut-et-tres-haut-debit-fixe-deploiements",
                     r"^\d{4}T\d-Commune$")
    if not res:
        print("  [telecoms] déploiements par commune introuvables")
        return 0
    titre, url = res
    trimestre = titre[:4] + "_" + titre[4:6]
    if conn.execute("SELECT 1 FROM telecoms_fixe_oi WHERE trimestre=?", (trimestre,)).fetchone():
        return 0
    archive = zipfile.ZipFile(io.BytesIO(_en_cache(f"deploiements/{titre}.zip", url, None)))
    dbf = next(n for n in archive.namelist() if n.lower().endswith(".dbf"))
    cibles = set(communes)
    lignes = lire_dbf(archive.read(dbf), lambda l: l.get("INSEE_COM") in cibles)
    conn.executemany(
        "INSERT OR IGNORE INTO telecoms_fixe_oi VALUES (?,?,?,?,?,?,?)",
        [(trimestre, l["INSEE_COM"], l.get("zone"), l.get("oi"), entier(l.get("Locaux")),
          entier(l.get("ftth")), nombre(l.get("couv"))) for l in lignes])
    ops = _csv(_get(f"{MCI}/reference/last/operateur/operateur.csv", timeout=60))
    conn.executemany("INSERT OR REPLACE INTO telecoms_operateurs VALUES (?,?)",
                     [(o["code"], o.get("nom")) for o in ops if o.get("code")])
    conn.commit()
    return len(lignes)


# ── 3. Qualité des réseaux fibre ─────────────────────────────────────────────

def releve_qualite(conn) -> int:
    res = _ressource("qualite-des-reseaux-en-fibre-optique", r"par réseau")
    if not res:
        return 0
    lignes = _csv(_get(res[1]))
    conn.executemany(
        "INSERT OR REPLACE INTO telecoms_qualite_ftth VALUES (?,?,?,?,?,?,?,?,?)",
        [(r["periode"], r["OI"], r.get("maison_mere"), r["perimetre"], r["dep_code"],
          nombre(r.get("taux_pannes")), nombre(r.get("taux_echecs_raccordement")),
          nombre(r.get("taux_echecs_raccordement_retraite")),
          nombre(r.get("taux_abonnes_avec_panne"))) for r in lignes if r.get("periode")])
    conn.commit()
    return len(lignes)


# ── 4. Sites mobiles alentour ────────────────────────────────────────────────

def sites_proches(lignes: list[dict], centre: tuple, rayon: float, trimestre: str) -> list[tuple]:
    retenus = []
    for r in lignes:
        lat, lon = nombre(r.get("latitude")), nombre(r.get("longitude"))
        if lat is None or lon is None:
            continue
        d = distance_km(centre[0], centre[1], lat, lon)
        if d > rayon:
            continue
        retenus.append((trimestre, r["code_op"], r.get("nom_op"), r["num_site"],
                        r.get("id_site_partage") or None, r.get("id_station_anfr"),
                        r.get("insee_com"), r.get("nom_com"), lat, lon, round(d, 2),
                        entier(r.get("site_2g")), entier(r.get("site_3g")),
                        entier(r.get("site_4g")), entier(r.get("site_5g")),
                        entier(r.get("site_ZB")), entier(r.get("site_DCC")),
                        entier(r.get("site_strategique"))))
    return retenus


def releve_sites(conn) -> int:
    if len(CENTROID) != 2:
        print("  [telecoms] pas de centroïde : sites mobiles ignorés")
        return 0
    trimestre = _sous_repertoires(f"{MOBILE}/sites/index.html")[-1]
    if conn.execute("SELECT 1 FROM telecoms_sites_mobiles WHERE trimestre=?",
                    (trimestre,)).fetchone():
        return 0
    lignes = _csv(_en_cache(f"mobile/{trimestre}_sites_Metropole.csv",
                            f"{MOBILE}/sites/{trimestre}/{trimestre}_sites_Metropole.csv", None))
    retenus = sites_proches(lignes, CENTROID, TELECOMS_RAYON_KM, trimestre)
    conn.executemany(f"INSERT OR IGNORE INTO telecoms_sites_mobiles VALUES ({','.join('?' * 18)})",
                     retenus)
    conn.commit()
    return len(retenus)


# ── 5. Indisponibilités déclarées, jour par jour ─────────────────────────────

def pannes_du_jour(features: list[dict], communes: set[str]) -> list[dict]:
    return [f["properties"] for f in features
            if (f.get("properties") or {}).get("code_insee") in communes]


def _jour(j: str):
    try:
        return j, json.loads(_get(INDISPO.format(j=j), timeout=90))["features"]
    except Exception as e:              # un jour illisible reste à relire
        return j, e


def releve_indisponibilites(conn, communes: list[str]) -> tuple[int, int]:
    lus = {r[0] for r in conn.execute("SELECT jour FROM telecoms_indispo_jours")}
    hier = dt.date.today() - dt.timedelta(days=1)
    jours = [(hier - dt.timedelta(days=i)).isoformat() for i in range(INDISPO_RECUL_JOURS)]
    a_lire = [j for j in jours if j not in lus]
    cibles, pannes = set(communes), 0
    with cf.ThreadPoolExecutor(6) as ex:
        for j, features in ex.map(_jour, a_lire):
            if isinstance(features, Exception):
                continue
            for p in pannes_du_jour(features, cibles):
                conn.execute(
                    "INSERT OR IGNORE INTO telecoms_indisponibilites VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (j, p.get("operateur"), (p.get("station_anfr") or "").lstrip("0"),
                     p.get("code_insee"), p.get("voix"), p.get("data"), p.get("voix4g"),
                     p.get("data4g"), p.get("data5g"), p.get("raison"), p.get("detail"),
                     p.get("debut"), p.get("fin")))
                pannes += 1
            conn.execute("INSERT OR REPLACE INTO telecoms_indispo_jours (jour, sites_france)"
                         " VALUES (?,?)", (j, len(features)))
            conn.commit()
    lus_ici = conn.execute("SELECT COUNT(*) FROM telecoms_indispo_jours").fetchone()[0]
    return pannes, lus_ici


def run():
    conn = get_conn()
    ensure_tables(conn)
    communes = communes_du_step("telecoms")
    etapes = (("éligibilité par technologie", lambda: releve_fixe(conn, communes)),
              ("zone et opérateur d'infrastructure", lambda: releve_oi(conn, communes)),
              ("qualité des réseaux fibre", lambda: releve_qualite(conn)),
              ("sites mobiles alentour", lambda: releve_sites(conn)),
              ("indisponibilités déclarées", lambda: releve_indisponibilites(conn, communes)))
    echecs = []
    for nom, etape in etapes:
        try:
            print(f"  [telecoms] {nom} : {etape()}")
        except Exception as e:          # une source muette n'empêche pas les autres
            echecs.append(nom)
            print(f"  [telecoms] {nom} : échec → {type(e).__name__}: {e}")
    conn.close()
    if echecs:
        raise RuntimeError(f"relevés en échec : {', '.join(echecs)}")


def show_stats():
    conn = get_conn(read_only=True)
    for r in conn.execute("""SELECT trimestre, insee, locaux, elig_ftth, mt_4gf, mt_sat
                             FROM telecoms_fixe ORDER BY insee, trimestre"""):
        part = f"{100 * r[3] / r[2]:.1f} %" if r[2] else "—"
        print(f"  {r[1]} {r[0]}  {r[2]:>6} locaux  fibre {r[3]:>6} ({part})"
              f"  meilleure : 4G fixe {r[4]}, satellite {r[5]}")
    for r in conn.execute("SELECT * FROM telecoms_fixe_oi"):
        print(f"  zone {r[2]}, opérateur d'infrastructure {r[3]} ({r[0]})")
    n = conn.execute("SELECT COUNT(*), COUNT(DISTINCT id_site_partage) FROM telecoms_sites_mobiles"
                     " WHERE trimestre=(SELECT MAX(trimestre) FROM telecoms_sites_mobiles)").fetchone()
    print(f"  sites mobiles dans le rayon : {n[0]} (dont {n[1]} partagés)")
    j = conn.execute("SELECT COUNT(*), MIN(jour), MAX(jour) FROM telecoms_indispo_jours").fetchone()
    p = conn.execute("SELECT COUNT(*) FROM telecoms_indisponibilites").fetchone()[0]
    print(f"  indisponibilités : {p} sur {j[0]} jours lus ({j[1]} → {j[2]})")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="ARCEP — fibre, mobile, pannes")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()
    show_stats() if args.stats else run()
