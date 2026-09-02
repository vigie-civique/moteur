"""
mobilite.py — Qui organise le transport ici, ce qui s'y arrête, et les
dispositifs de l'État qui touchent la commune.

Sur une commune rurale, l'absence de desserte est une donnée politique majeure,
et elle n'est affichée nulle part. Trois faits, trois sources ouvertes :

  1. L'AOM — l'autorité organisatrice de la mobilité compétente. Depuis la loi
     d'orientation des mobilités, une communauté de communes a pu PRENDRE la
     compétence ou la laisser à la région : savoir laquelle des deux organise le
     transport ici, c'est savoir à qui s'adresser.
  2. Les arrêts déclarés dans les fichiers GTFS publiés — donc l'offre telle
     que les réseaux la déclarent à l'État.
  3. Les dispositifs de l'ANCT qui couvrent la commune (France services,
     Villages d'avenir, CRTE…), depuis la table de croisement nationale.

─────────────────────────────────────────────────────────────────────────────
DEUX PIÈGES VÉRIFIÉS LE 02/09/2026

🔴 `GET /api/aoms/{insee}` NE RÉPOND PAS À LA QUESTION QU'ON CROIT. Son nom dit
« search AOM by INSEE code », mais le code attendu est celui de la commune
PRINCIPALE de l'AOM, pas d'une commune couverte : interrogé sur trois communes
rurales, il rend **500**, et 200 sur Paris. Un collecteur écrit là-dessus aurait
conclu « aucune AOM » pour presque toutes les communes de France — un zéro qui
vient d'une absence, pas d'un fait. L'AOM se cherche donc PAR COORDONNÉES.

🔴 LA BOÎTE ENGLOBANTE N'EST PAS LA COMMUNE. L'API des arrêts n'accepte qu'un
rectangle ; celui d'une commune contient toujours des morceaux de voisines. Les
arrêts rendus sont donc repassés au CONTOUR officiel de la commune, et les deux
comptes sont conservés : ce qui est dans la commune, et ce que la boîte
ramassait. Publier le second pour le premier gonflerait la desserte d'une
commune avec les arrêts du bourg d'à côté.

⚠️ ET LE ZONAGE ZRR/FRR N'EXISTE PAS EN OPEN DATA NATIONAL. Cherché le
02/09/2026 : l'ANCT ne le publie pas, et data.gouv.fr n'en porte que des
versions DÉPARTEMENTALES, éparses, de formats hétérogènes et souvent périmées
(le zonage ZRR a été remplacé par France Ruralités Revitalisation au
1er juillet 2024). Le collecteur ne l'invente pas : il collecte les dispositifs
que l'ANCT publie vraiment, et le manque est écrit ici.

Sources : `transport.data.gouv.fr` (API publique), `data.gouv.fr` (ANCT).

Usage :
  python3 -m collectors.mobilite
  python3 -m collectors.mobilite --insee 30140
  python3 -m collectors.mobilite --stats
"""
import argparse
import csv
import time
import urllib.parse
import urllib.request

from .archive import HEADERS, archive_fetch, fetch_json
from .config import (BBOX, CENTROID, COMMUNE_INSEE, COMMUNES, NATIONAL_STORE,
                     REQUEST_DELAY, communes_du_step)
from .db import get_conn, transaction
from .geometrie import bbox as bbox_geom
from .geometrie import contour_commune, dedans, point_interieur
from .national_store import ecrire_atomiquement, est_frais

SOURCE = "transport-anct"
TRANSPORT = "https://transport.data.gouv.fr/api"
CACHE = NATIONAL_STORE / "anct"

# La table de croisement de l'ANCT, publiée sur data.gouv.fr. On passe par
# l'API du portail plutôt que par une URL de fichier : celle-ci porte la date
# de dépôt (`/20260413-100516/`) et changerait à chaque mise à jour.
ANCT_DATASET = "croisement-des-dispositifs-de-politique-publique-de-lanct"
ANCT_JOURS = 30

# Ce que les colonnes de la table de croisement désignent. L'ANCT ne publie ce
# dictionnaire qu'en PDF ; la liste des dispositifs, elle, est en clair dans la
# description du jeu, et les abréviations s'y rattachent une à une. Une colonne
# INCONNUE n'est pas ignorée : elle est conservée sous son code brut, pour qu'un
# dispositif ajouté demain apparaisse au lieu de disparaître.
DISPOSITIFS = {
    "id_pvd":       "Petites villes de demain",
    "id_ti":        "Territoires d'industrie",
    "id_crte":      "Contrat de relance et de transition écologique",
    "id_acv":       "Action cœur de ville",
    "id_ami":       "Avenir montagnes ingénierie",
    "id_fabp":      "Fabriques prospectives",
    "id_habinclus": "Habitat inclusif — la Fabrique à projets",
    "id_fs":        "France services",
    "id_amm":       "Avenir montagnes mobilités",
    "id_acv2":      "Action cœur de ville — entrées de ville",
    "id_va":        "Villages d'avenir",
    "id_site":      "Site clé en main France 2030",
    "id_cite":      "Cité éducative",
    "id_cde":       "Cité de l'emploi",
}


def aom(lat: float, lng: float) -> dict | None:
    """L'autorité organisatrice compétente à ce point, ou None."""
    url = f"{TRANSPORT}/aoms?" + urllib.parse.urlencode({"lat": lat, "lon": lng})
    data = fetch_json(url, source=SOURCE, timeout=45)
    return data if isinstance(data, dict) and data.get("nom") else None


def arrets(sud: float, ouest: float, nord: float, est: float) -> list[dict]:
    """Arrêts GTFS déclarés dans un rectangle.

    `width_px`/`height_px` décrivent la carte que l'API croit servir ; à
    l'échelle d'une commune, la réponse ne change pas avec eux (mesuré : 41
    arrêts pour 10 comme pour 2 000 pixels). On les fixe donc généreusement,
    pour que l'API n'ait aucune raison de regrouper.
    """
    url = f"{TRANSPORT}/gtfs-stops?" + urllib.parse.urlencode({
        "south": sud, "north": nord, "west": ouest, "east": est,
        "width_px": 2000, "height_px": 2000})
    data = fetch_json(url, source=SOURCE, timeout=60)
    return data.get("features") or []


def _url_anct() -> str | None:
    """L'URL courante du fichier de croisement, lue dans la fiche du jeu.

    ⚠️ Par le SLUG, pas par la recherche : `?q=croisement-des-dispositifs-…`
    rend zéro résultat — le moteur de data.gouv.fr cherche dans les titres, pas
    dans les identifiants. Interroger la fiche directement est exact et ne
    dépend pas d'un classement de pertinence.
    """
    url = f"https://www.data.gouv.fr/api/1/datasets/{ANCT_DATASET}/"
    jeu = fetch_json(url, source=SOURCE, timeout=45)
    for res in jeu.get("resources", []):
        if (res.get("format") or "").lower() == "csv":
            return res.get("url")
    return None


def croisement_anct() -> dict[str, dict]:
    """{code INSEE: {dispositif: identifiant}} pour toute la France.

    1,9 Mo pour 34 969 communes : le fichier va au magasin national, comme les
    autres jeux nationaux, et sert à toutes les instances de la machine.
    """
    cache = CACHE / "croisement-dispositifs.csv"
    if not est_frais(cache, ANCT_JOURS):
        source = _url_anct()
        if not source:
            raise RuntimeError("ANCT : aucune ressource CSV dans le catalogue")
        req = urllib.request.Request(source, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=180) as r:
            brut = r.read()
            archive_fetch(SOURCE, source, brut,
                          content_type=r.headers.get_content_type(),
                          http_status=r.status)
        ecrire_atomiquement(cache, brut)

    with cache.open(encoding="utf-8-sig", newline="") as f:
        return lire_croisement(f)


def lire_croisement(flux) -> dict[str, dict]:
    """{code INSEE: {colonne: identifiant}} — les colonnes vides sont omises.

    Toute colonne `id_*` est retenue, y compris celle qu'on ne sait pas nommer :
    un dispositif ajouté par l'ANCT doit apparaître sous son code brut plutôt
    que disparaître parce que le dictionnaire n'a pas été mis à jour.
    """
    table: dict[str, dict] = {}
    for ligne in csv.DictReader(flux, delimiter=";"):
        insee = (ligne.get("insee_com") or "").strip()
        if not insee:
            continue
        table[insee] = {k: v.strip() for k, v in ligne.items()
                        if k and k.startswith("id_") and (v or "").strip()}
    return table


def retenir_arrets(traits: list[dict], contour: dict | None,
                   insee: str) -> list[tuple]:
    """Les arrêts rendus par la boîte, chacun marqué dedans/dehors.

    Rien n'est jeté : un arrêt hors contour est conservé avec `dans_commune=0`.
    C'est ce qui permet de dire ensuite « 15 arrêts dans la commune, 5 dans le
    rectangle interrogé » plutôt que de publier 20 comme si c'était la desserte
    communale.
    """
    lignes = []
    for f in traits:
        p = f.get("properties") or {}
        coords = (f.get("geometry") or {}).get("coordinates") or [None, None]
        lng, lat = coords[0], coords[1]
        interieur = bool(contour and lat is not None and lng is not None
                         and dedans(lng, lat, contour))
        lignes.append((insee, p.get("dataset_title"), p.get("stop_name"),
                       str(p.get("stop_id")), lat, lng, int(interieur)))
    return lignes


def ensure_tables(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mobilite_aom (
            insee       TEXT PRIMARY KEY,
            nom         TEXT,
            siren       TEXT,
            forme       TEXT,
            departement TEXT,
            releve_le   TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mobilite_arrets (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            insee       TEXT NOT NULL,
            reseau      TEXT,
            arret       TEXT,
            stop_id     TEXT,
            lat         REAL,
            lng         REAL,
            dans_commune INTEGER,   -- 0 : rendu par la boîte, hors du contour
            UNIQUE(insee, reseau, stop_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dispositifs_etat (
            insee       TEXT NOT NULL,
            code        TEXT NOT NULL,
            libelle     TEXT,
            reference   TEXT,       -- l'identifiant que l'ANCT donne au dossier
            releve_le   TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (insee, code)
        )
    """)
    conn.commit()


def import_commune(insee: str, commune_nom: str, table_anct: dict) -> dict:
    releve = {"aom": None, "arrets": 0, "arrets_boite": 0, "dispositifs": 0,
              "contour": False}

    # Le contour officiel, pour deux raisons : interroger l'AOM à un point qui
    # est vraiment DANS la commune, et ne pas prendre les arrêts du voisin.
    contour = None
    try:
        contour = contour_commune(insee, source=SOURCE)
    except Exception as e:                              # noqa: BLE001
        print(f"    ↳ contour de {commune_nom} indisponible : {e}")
    releve["contour"] = contour is not None

    # ⚠️ Le centroïde de `instance.json` est celui de la commune de l'instance :
    # s'en servir pour toutes rendrait la MÊME AOM à chacune. Le point vient
    # donc du contour de la commune interrogée, et ne sert de repli que faute
    # de contour.
    point = point_interieur(contour) if contour else None
    if point is None and CENTROID and insee == COMMUNE_INSEE:
        point = (CENTROID[1], CENTROID[0])
    autorite = None
    if point:
        time.sleep(REQUEST_DELAY)
        autorite = aom(point[1], point[0])
        releve["aom"] = (autorite or {}).get("nom")

    if contour:
        ouest, sud, est, nord = bbox_geom(contour)
    elif BBOX:
        sud, ouest, nord, est = BBOX
    else:
        sud = ouest = nord = est = None

    trouves = []
    if None not in (sud, ouest, nord, est):
        time.sleep(REQUEST_DELAY)
        trouves = retenir_arrets(arrets(sud, ouest, nord, est), contour, insee)
    releve["arrets_boite"] = len(trouves)
    releve["arrets"] = sum(1 for t in trouves if t[6])

    dispositifs = table_anct.get(insee, {})
    releve["dispositifs"] = len(dispositifs)

    with transaction() as conn:
        ensure_tables(conn)
        if autorite:
            conn.execute(
                "INSERT INTO mobilite_aom (insee,nom,siren,forme,departement,releve_le)"
                " VALUES (?,?,?,?,?,datetime('now'))"
                " ON CONFLICT(insee) DO UPDATE SET nom=excluded.nom,"
                " siren=excluded.siren, forme=excluded.forme,"
                " departement=excluded.departement, releve_le=excluded.releve_le",
                (insee, autorite.get("nom"), autorite.get("siren"),
                 autorite.get("forme_juridique"), autorite.get("departement")))
        # Les arrêts se remplacent en bloc : un arrêt supprimé d'un GTFS doit
        # disparaître d'ici, sans quoi le site publierait une desserte morte.
        conn.execute("DELETE FROM mobilite_arrets WHERE insee=?", (insee,))
        for t in trouves:
            conn.execute(
                "INSERT OR IGNORE INTO mobilite_arrets"
                " (insee,reseau,arret,stop_id,lat,lng,dans_commune)"
                " VALUES (?,?,?,?,?,?,?)", t)
        conn.execute("DELETE FROM dispositifs_etat WHERE insee=?", (insee,))
        for code, reference in sorted(dispositifs.items()):
            conn.execute(
                "INSERT INTO dispositifs_etat (insee,code,libelle,reference,releve_le)"
                " VALUES (?,?,?,?,datetime('now'))",
                (insee, code, DISPOSITIFS.get(code), reference))

    hors = releve["arrets_boite"] - releve["arrets"]
    print(f"  [mobilite] {commune_nom} — AOM : {releve['aom'] or 'aucune'}"
          f" ; {releve['arrets']} arrêt(s) dans la commune"
          + (f" ({hors} écarté(s) hors contour)" if hors else "")
          + (" ⚠️ sans contour, comptés sur la boîte" if not contour and trouves else "")
          + f" ; {releve['dispositifs']} dispositif(s) de l'État")
    return releve


def run(insee: str | None = None) -> int:
    table = croisement_anct()
    cibles = [insee] if insee else communes_du_step("mobilite")
    total = 0
    for i, code in enumerate(cibles):
        nom = COMMUNES.get(code, {}).get("nom", code)
        try:
            r = import_commune(code, nom, table)
            total += r["arrets"] + r["dispositifs"]
        except Exception as e:                          # noqa: BLE001
            print(f"  [mobilite] {nom} — ÉCHEC : {e}")
        if i < len(cibles) - 1:
            time.sleep(REQUEST_DELAY)
    print(f"[mobilite] {total} fait(s) sur {len(cibles)} commune(s)")
    return total


def stats():
    conn = get_conn()
    ensure_tables(conn)
    for r in conn.execute("SELECT * FROM mobilite_aom ORDER BY insee"):
        print(f"  AOM {r['insee']} : {r['nom']} ({r['forme']}, SIREN {r['siren']})")
    for r in conn.execute(
            "SELECT insee, reseau, COUNT(*) n,"
            " SUM(dans_commune) dedans FROM mobilite_arrets"
            " GROUP BY insee, reseau ORDER BY insee, n DESC"):
        print(f"    {r['insee']} {r['reseau'] or '?':<38} {r['dedans']}/{r['n']} arrêt(s)")
    for r in conn.execute("SELECT insee, code, libelle, reference"
                          " FROM dispositifs_etat ORDER BY insee, code"):
        print(f"    {r['insee']} {r['libelle'] or r['code']:<46} {r['reference']}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--insee", help="une seule commune")
    p.add_argument("--stats", action="store_true")
    a = p.parse_args()
    if a.stats:
        stats()
    else:
        run(a.insee)
