"""
equipements.py — Ce qu'il y a dans la commune, et ce qui a fermé (BPE, INSEE).

École, médecin, pharmacie, boulangerie, distributeur : la base permanente des
équipements recense ce qui existe, commune par commune. C'est le tableau le plus
parlant qu'on puisse tirer de l'INSEE pour une commune rurale — et il était
collecté sans être lisible ni publié.

⚠️ Ce collecteur ne DÉCOUVRE pas une source : `insee_social` interrogeait déjà
`DS_BPE` et rangeait 502 lignes par instance dans `insee_indicateurs`, sous des
codes comme `BPE_A129`, sans libellé, que rien ne lisait. Le manque n'était pas
la collecte, c'était le SENS. Le jeu passe donc ici, avec sa nomenclature, et
`insee_social` cesse de le collecter : un fait, un endroit.

─────────────────────────────────────────────────────────────────────────────
LA SÉRIE HISTORIQUE N'EXISTE PAS À LA COMMUNE, ET C'EST VÉRIFIÉ

« La série historique montre les fermetures » supposait une profondeur que la
source ne donne pas à cette échelle. Mesuré le 02/09/2026 :

  - `DS_BPE` ne publie qu'UN millésime (2025). Interrogé sur une commune, il
    rend l'état, jamais la trajectoire.
  - `DS_BPE_EVOLUTION` porte bien 2015, 2020 et 2025 — mais ses niveaux
    géographiques sont arrondissement, bassin de vie, EPCI, aire d'attraction,
    unité urbaine, zone d'emploi, département, région, France. **Pas la
    commune.** Interrogé en `COM-30140`, il rend zéro observation : un zéro qui
    vient d'une absence de publication, pas d'une absence d'équipement.

L'évolution est donc collectée à l'échelle de l'INTERCOMMUNALITÉ, qui est le
plus fin des niveaux publiés et que le dispositif suit déjà comme institution.
Elle se lit comme telle, et le champ `geo_type` l'écrit en toutes lettres pour
qu'aucune page ne puisse la présenter comme communale.

Sources, sans clé :
  - `api.insee.fr/melodi/data/DS_BPE`            — état, par commune
  - `api.insee.fr/melodi/data/DS_BPE_EVOLUTION`  — 2015 / 2020 / 2025, par EPCI
  - la nomenclature des types, tirée des fichiers que l'INSEE publie AVEC
    chaque jeu (`DS_BPE_<millésime>_metadata.csv`), jamais recopiée à la main :
    ses libellés changent d'un millésime à l'autre, et les deux jeux n'emploient
    pas les mêmes codes.

Usage :
  python3 -m collectors.equipements
  python3 -m collectors.equipements --insee 30140
  python3 -m collectors.equipements --stats
"""
import argparse
import csv
import io
import json
import time
import urllib.request
import zipfile

from .archive import HEADERS, fetch_json
from .config import (COMMUNES, EPCI_NOM, EPCI_SIREN, NATIONAL_STORE,
                     REQUEST_DELAY, communes_du_step)
from .db import get_conn, transaction
from .national_store import ecrire_atomiquement, est_frais

SOURCE = "insee-bpe"
MELODI = "https://api.insee.fr/melodi"
CACHE = NATIONAL_STORE / "bpe"

# La nomenclature suit le millésime du jeu : elle se re-tire une fois l'an.
NOMENCLATURE_JOURS = 300

# Les trois niveaux de la classification INSEE, du plus large au plus fin.
NIVEAUX = {
    "FACILITY_DOM": "domaine",
    "FACILITY_SDOM": "sous_domaine",
    "FACILITY_TYPE": "type",
}


def _telecharger(url: str, timeout: int = 300) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def nomenclature(dataset: str = "DS_BPE") -> dict[str, str]:
    """{code: libellé} pour les domaines, sous-domaines et types d'équipement.

    L'INSEE publie la nomenclature dans un `*_metadata.csv` livré À L'INTÉRIEUR
    de l'archive du jeu complet. On ne garde pas l'archive : 14 Mo pour 2 Mo de
    métadonnées, dont on extrait quelques milliers de couples code/libellé qui
    tiennent dans 30 Ko. Le magasin national n'a pas à porter le reste, et le
    disque est déjà un sujet.

    L'identifiant du fichier porte le millésime (`DS_BPE_2025_CSV_FR`) : il est
    donc LU dans le catalogue, jamais écrit ici. Codé en dur, la collecte se
    serait arrêtée au premier millésime suivant, en rendant un 404 que personne
    n'aurait relié à la nomenclature.
    """
    catalogue = fetch_json(f"{MELODI}/catalog/{dataset}", source=SOURCE, timeout=60)
    produits = [p for p in catalogue.get("product", [])
                if p.get("format") == "CSV" and p.get("language") == "FR"]
    if not produits:
        raise RuntimeError(f"catalogue {dataset} : aucun produit CSV français")
    produit = produits[0]
    cache = CACHE / f"{produit['id']}.nomenclature.json"
    if est_frais(cache, NOMENCLATURE_JOURS):
        return json.loads(cache.read_text(encoding="utf-8"))

    brut = _telecharger(produit["accessURL"])
    libelles: dict[str, str] = {}
    with zipfile.ZipFile(io.BytesIO(brut)) as z:
        noms = [n for n in z.namelist() if n.endswith("metadata.csv")]
        if not noms:
            raise RuntimeError(f"{produit['id']} : pas de fichier de métadonnées")
        with z.open(noms[0]) as f:
            lecteur = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"),
                                     delimiter=";")
            for ligne in lecteur:
                if ligne.get("COD_VAR") in NIVEAUX:
                    code = (ligne.get("COD_MOD") or "").strip()
                    lib = (ligne.get("LIB_MOD") or "").strip()
                    if code and lib:
                        libelles[code] = lib
    ecrire_atomiquement(cache, json.dumps(libelles, ensure_ascii=False).encode())
    print(f"  [equipements] nomenclature {produit['id']} : {len(libelles)} libellés")
    return libelles


def nomenclatures() -> dict[str, str]:
    """Les libellés des DEUX jeux, réunis.

    Chaque jeu livre sa propre nomenclature, et elles ne se recouvrent pas :
    `DS_BPE_EVOLUTION` emploie des codes de REGROUPEMENT que l'état annuel
    ignore — `A10G` par exemple, resté sans libellé tant qu'on ne lisait que le
    premier fichier. Un code sans libellé n'est pas une donnée manquante : c'est
    une nomenclature qu'on n'est pas allé chercher.
    """
    libelles = nomenclature("DS_BPE")
    for code, lib in nomenclature("DS_BPE_EVOLUTION").items():
        libelles.setdefault(code, lib)
    return libelles


def classer(dims: dict) -> tuple[str, str]:
    """Le niveau de finesse d'une observation, et son code.

    La BPE empile trois niveaux dans le MÊME jeu : une ligne porte à la fois un
    domaine, un sous-domaine et un type, et `_T` marque celui qui totalise. Les
    prendre tous pour des types compterait trois fois les mêmes équipements —
    le total du domaine, celui du sous-domaine, et le détail.
    """
    dom, sdom, typ = (dims.get("FACILITY_DOM"), dims.get("FACILITY_SDOM"),
                      dims.get("FACILITY_TYPE"))
    if typ and typ != "_T":
        return "type", typ
    if sdom and sdom != "_T":
        return "sous_domaine", sdom
    if dom and dom != "_T":
        return "domaine", dom
    return "total", "_T"


def _observations(dataset: str, geo: str, maxi: int = 6000) -> list[dict]:
    url = f"{MELODI}/data/{dataset}?GEO={geo}&maxResult={maxi}"
    data = fetch_json(url, source=SOURCE, timeout=90)
    return data.get("observations") or []


def _valeur(obs: dict):
    """La mesure, ou None quand l'INSEE la retient (secret statistique).

    Une observation sous secret arrive avec un `OBS_VALUE_NIVEAU` vide : la
    prendre pour un zéro ferait disparaître un équipement qui existe.
    """
    mesure = (obs.get("measures") or {}).get("OBS_VALUE_NIVEAU") or {}
    return mesure.get("value")


def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS equipements (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            geo_type  TEXT NOT NULL,   -- COM | EPCI — jamais confondre les deux
            geo_code  TEXT NOT NULL,
            geo_nom   TEXT,
            annee     TEXT NOT NULL,
            niveau    TEXT NOT NULL,   -- domaine | sous_domaine | type | total
            code      TEXT NOT NULL,
            libelle   TEXT,
            nombre    REAL,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(geo_type, geo_code, annee, niveau, code)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_equip_geo"
                 " ON equipements(geo_type, geo_code, annee)")
    conn.commit()


def _ecrire(conn, geo_type: str, geo_code: str, geo_nom: str, annee: str,
            niveau: str, code: str, libelle: str | None, nombre) -> None:
    conn.execute(
        "INSERT INTO equipements"
        " (geo_type,geo_code,geo_nom,annee,niveau,code,libelle,nombre)"
        " VALUES (?,?,?,?,?,?,?,?)"
        " ON CONFLICT(geo_type,geo_code,annee,niveau,code) DO UPDATE SET"
        " nombre=excluded.nombre, libelle=excluded.libelle, geo_nom=excluded.geo_nom",
        (geo_type, geo_code, geo_nom, annee, niveau, code, libelle, nombre))


def import_commune(insee: str, commune_nom: str, libelles: dict) -> int:
    """L'état des équipements de la commune, au dernier millésime publié."""
    obs = _observations("DS_BPE", f"COM-{insee}")
    if not obs:
        print(f"  [equipements] {commune_nom} — aucune observation")
        return 0
    n = 0
    with transaction() as conn:
        ensure_table(conn)
        for o in obs:
            d = o.get("dimensions") or {}
            if d.get("BPE_MEASURE") != "FACILITIES":
                continue
            annee = d.get("TIME_PERIOD")
            niveau, code = classer(d)
            _ecrire(conn, "COM", insee, commune_nom, annee, niveau, code,
                    libelles.get(code) if code != "_T" else "Tous équipements",
                    _valeur(o))
            n += 1
    total = next((_valeur(o) for o in obs
                  if (o.get("dimensions") or {}).get("FACILITY_DOM") == "_T"
                  and (o.get("dimensions") or {}).get("FACILITY_TYPE") == "_T"), None)
    print(f"  [equipements] {commune_nom} — {n} ligne(s)"
          + (f", {total:.0f} équipement(s) au total" if total else ""))
    return n


def import_evolution(libelles: dict) -> int:
    """La trajectoire, à l'échelle de l'intercommunalité — le plus fin publié."""
    if not EPCI_SIREN:
        print("  [equipements] pas d'intercommunalité déclarée : pas d'évolution")
        return 0
    obs = _observations("DS_BPE_EVOLUTION", f"EPCI-{EPCI_SIREN}")
    if not obs:
        print(f"  [equipements] évolution — rien pour l'EPCI {EPCI_SIREN}")
        return 0
    n = 0
    annees = set()
    with transaction() as conn:
        ensure_table(conn)
        for o in obs:
            d = o.get("dimensions") or {}
            if d.get("BPE_MEASURE") != "FACILITIES":
                continue
            code = d.get("FACILITY_TYPE") or "_T"
            annees.add(d.get("TIME_PERIOD"))
            _ecrire(conn, "EPCI", EPCI_SIREN, EPCI_NOM, d.get("TIME_PERIOD"),
                    "type" if code != "_T" else "total",
                    code, libelles.get(code) if code != "_T" else "Tous équipements",
                    _valeur(o))
            n += 1
    print(f"  [equipements] évolution {EPCI_NOM or EPCI_SIREN} — {n} ligne(s), "
          f"millésimes {', '.join(sorted(a for a in annees if a))}")
    return n


def run(insee: str | None = None) -> int:
    libelles = nomenclatures()
    cibles = [insee] if insee else communes_du_step("equipements")
    total = 0
    for i, code in enumerate(cibles):
        nom = COMMUNES.get(code, {}).get("nom", code)
        try:
            total += import_commune(code, nom, libelles)
        except Exception as e:                      # noqa: BLE001
            print(f"  [equipements] {nom} — ÉCHEC : {e}")
        if i < len(cibles) - 1:
            time.sleep(REQUEST_DELAY)
    try:
        total += import_evolution(libelles)
    except Exception as e:                          # noqa: BLE001
        print(f"  [equipements] évolution — ÉCHEC : {e}")
    print(f"[equipements] {total} ligne(s) sur {len(cibles)} commune(s)")
    return total


def stats():
    conn = get_conn()
    ensure_table(conn)
    for r in conn.execute(
            "SELECT geo_type, geo_nom, annee, COUNT(*) n,"
            " SUM(CASE WHEN niveau='type' THEN nombre ELSE 0 END) equip"
            " FROM equipements GROUP BY 1,2,3 ORDER BY 1,2,3"):
        print(f"  {r['geo_type']:<5} {r['geo_nom'] or '':<34} {r['annee']}  "
              f"{r['n']:>4} ligne(s)  {r['equip'] or 0:.0f} équipement(s)")
    print("  — ce qui a bougé dans l'intercommunalité :")
    for r in conn.execute("""
            SELECT code, libelle,
                   MAX(CASE WHEN annee=(SELECT MIN(annee) FROM equipements WHERE geo_type='EPCI')
                            THEN nombre END) debut,
                   MAX(CASE WHEN annee=(SELECT MAX(annee) FROM equipements WHERE geo_type='EPCI')
                            THEN nombre END) fin
              FROM equipements WHERE geo_type='EPCI' AND niveau='type'
             GROUP BY code, libelle HAVING debut IS NOT NULL AND fin IS NOT NULL
                AND fin <> debut ORDER BY (fin - debut) LIMIT 12"""):
        print(f"    {r['libelle'] or r['code']:<44} {r['debut']:>5.0f} → {r['fin']:.0f}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--insee", help="une seule commune")
    p.add_argument("--stats", action="store_true")
    a = p.parse_args()
    if a.stats:
        stats()
    else:
        run(a.insee)
