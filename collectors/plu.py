"""
plu.py — Documents d'urbanisme et zonage, depuis le Géoportail de l'urbanisme.

Ce que la commune peut construire, et où, tient dans un document : PLU, PLUi,
carte communale — ou rien du tout, et c'est alors le règlement national
d'urbanisme (RNU) qui s'applique. Le fait n'était pas collecté : `urbanisme.py`
le lisait dans `config/seed_local.json`, c'est-à-dire de la main de quelqu'un.
Sa docstring annonçait pourtant « GPU/IGN → zones d'urbanisme via bbox » : le
module ne contenait aucun appel réseau. Une intention n'est pas une capacité,
cf. [[feedback-intention-et-capacite]].

Source : `apicarto.ign.fr/api/gpu`, sans clé, sans compte. Le GPU est le
registre où les collectivités DÉPOSENT leur document ; depuis le 1er janvier
2020, c'est cette publication qui rend le document opposable (art. L133-1 et
L153-22 du code de l'urbanisme). L'absence d'un document au GPU est donc un
fait juridique, pas un trou de collecte — mais elle ne se lit pas comme
« la commune n'a pas de PLU » : elle se lit « aucun document déposé au GPU ».

─────────────────────────────────────────────────────────────────────────────
CE QUE LA SOURCE REND, ET LE PIÈGE QU'ELLE TEND

L'interrogation se fait par GÉOMÉTRIE. Rendre la géométrie de la commune, c'est
donc recevoir aussi les documents et les zones des communes VOISINES, dont la
frontière touche la nôtre. Mesuré le 02/09/2026 : la requête sur Saillans rend
trois documents — la carte communale d'Aubenasson, le PLU de Mirabel-et-Blacons
et le PLU de Saillans ; celle sur Brassac rend le PLU d'Angles en plus du PLUi
de son intercommunalité. Attribuer sans filtrer donnerait à une commune le
document d'une autre.

L'attribution ne tient donc qu'à `grid_name`, qui porte SOIT le code INSEE de
la commune (document communal), SOIT le SIREN de l'EPCI (document
intercommunal). Ces deux valeurs, on les connaît par la configuration : la
comparaison est exacte, jamais approchée. Tout le reste est écarté, et compté.

⚠️ ET UN POURCENTAGE QUI NE SE VÉRIFIE PAS EST FAUX. Les zones rendues ne sont
pas DÉCOUPÉES à la frontière communale : sur Brassac, la somme des zones du
PLUi vaut 6,24 fois la surface de la commune, parce qu'un PLUi couvre l'EPCI
entier. Sommer ces surfaces pour en tirer « x % du territoire est
constructible » donnerait un chiffre juste sous un cadre faux — et le défaut
serait invisible, puisque les parts tomberaient bien à 100 %.

La part se mesure donc PAR ÉCHANTILLONNAGE du territoire communal : une grille
régulière de points, les points retenus sont ceux qui tombent dans la commune,
et chacun reçoit la zone qui le contient. Ce que l'on compte est alors du
territoire COMMUNAL, jamais celui du voisin, que le document soit communal ou
intercommunal. La grille est régulière et non aléatoire pour qu'une seconde
collecte rende le même chiffre.

🔴 ET LE TERRITOIRE DE MESURE NE VIENT PAS DU GPU. Le polygone que le GPU rend
pour Saillans couvre 15,64 km² quand la commune en fait 37,42 : un périmètre
d'avant fusion. Les zones y tenaient parfaitement — couverture 0,99 — et les
parts publiées ne portaient que sur 42 % du territoire. Un contrôle qui vérifie
la cohérence des zones entre elles ne peut pas voir que le SOL est le mauvais.
La mesure se fait donc sur le contour officiel (`geo.api.gouv.fr`), et l'écart
avec le polygone du GPU est écrit en base plutôt que subi.

Le contrôle qui reste est celui de la COUVERTURE : la part du territoire
communal à laquelle une zone a été attribuée. Un document complet couvre tout —
mesuré à 1,00 sur Brassac. Sur Saillans il tombe à 0,42, et c'est précisément ce
qu'il faut savoir : le PLU y est antérieur à la fusion et ne couvre pas la
partie absorbée. En dessous de 95 %, les parts ne sont pas publiées, et la
raison est écrite en base plutôt que devinée par le lecteur.

Usage :
  python3 -m collectors.plu
  python3 -m collectors.plu --insee 30140
  python3 -m collectors.plu --stats
"""
import argparse
import json
import time
import urllib.request

from .archive import HEADERS, archive_fetch
from .config import (COMMUNES, COMMUNES_DELEGUEES, EPCI_SIREN, REQUEST_DELAY,
                     communes_du_step)
from .db import get_conn, transaction
from .geometrie import (aire_m2, bbox, contour_commune, dedans, grille,
                        latitude_moyenne)

API = "https://apicarto.ign.fr/api/gpu"
SOURCE = "gpu"

# Part minimale du territoire communal qu'une zone doit couvrir pour qu'on
# publie des parts. En dessous, le document ne couvre pas la commune — ou la
# collecte en a manqué un morceau — et une part calculée sur le reste dirait
# autre chose que ce qu'elle prétend.
COUVERTURE_MIN = 0.95

# Nombre visé de points de mesure DANS la commune. À 8 000 points, l'incertitude
# d'une part de 76 % vaut 0,5 point — largement sous la précision à laquelle une
# part de territoire se lit. Monter plus haut coûte du temps sans rien apprendre.
POINTS_VISES = 8000

# Part des points mesurés en deçà de laquelle une partition de document n'est
# pas tenue pour applicable ici. Elle sépare le document qui couvre la commune
# de celui qui l'effleure : sur Brassac, la partition `_B` du PLUi mord sur cinq
# zones de bordure, soit moins d'un point sur mille.
PART_MIN_PARTITION = 0.01

# Ce que le premier caractère du type de zone annonce. La nomenclature du CNIG
# (standard CNIG PLU) n'a que quatre familles ; les suffixes (AUc, AUs, Ua…)
# sont des sous-zones du règlement local, qu'on ne cherche pas à interpréter.
FAMILLES = {
    "U":  "urbaine",
    "AU": "à urbaniser",
    "A":  "agricole",
    "N":  "naturelle",
}


def _fetch(chemin: str, corps: dict | None = None, timeout: int = 90):
    """GET si `corps` est absent, POST sinon. La réponse brute est archivée.

    Le POST existe parce que la géométrie d'une commune ne tient pas toujours
    dans une URL : celle de Brassac fait 301 points, d'autres en font plusieurs
    milliers, et un GET tomberait sur la limite du serveur sans le dire.
    """
    url = f"{API}/{chemin}"
    donnees = en_tetes = None
    if corps is not None:
        donnees = json.dumps(corps).encode("utf-8")
        en_tetes = {**HEADERS, "Content-Type": "application/json"}
    req = urllib.request.Request(url, data=donnees, headers=en_tetes or HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        archive_fetch(SOURCE, url, raw, content_type=r.headers.get_content_type(),
                      http_status=r.status)
    return json.loads(raw)


def _famille(typezone: str | None) -> str | None:
    t = (typezone or "").strip()
    if not t:
        return None
    return FAMILLES.get(t[:2].upper()) or FAMILLES.get(t[:1].upper())


def _date_approbation(nom: str | None) -> str | None:
    """`26289_PLU_20200306` → `2020-03-06`. Le nom du document porte sa date.

    C'est le seul endroit où elle figure : `datappro` est vide sur la plupart
    des zones rendues par l'API. Une chaîne qui ne porte pas huit chiffres rend
    None — on préfère pas de date à une date fabriquée.
    """
    for morceau in (nom or "").split("_"):
        if len(morceau) == 8 and morceau.isdigit():
            a, m, j = morceau[:4], morceau[4:6], morceau[6:]
            if "1900" < a < "2100" and "01" <= m <= "12" and "01" <= j <= "31":
                return f"{a}-{m}-{j}"
    return None


def attribuer(documents: list[dict], insee: str,
              epci_siren: str | None) -> tuple[list[dict], list[str]]:
    """Sépare les documents de CETTE collectivité de ceux du voisinage.

    Rien d'approché : `grid_name` porte le code INSEE de la commune ou le SIREN
    de l'EPCI, et on les connaît. Un document dont la valeur ne tombe sur ni
    l'un ni l'autre appartient à quelqu'un d'autre — il est écarté et nommé,
    pour qu'un écart de configuration se voie au journal.
    """
    notres, ecartes = [], []
    for f in documents:
        p = f.get("properties") or {}
        grid = (p.get("grid_name") or "").strip()
        if grid and grid == insee:
            portee = "communal"
        elif grid and epci_siren and grid == epci_siren:
            portee = "intercommunal"
        else:
            ecartes.append(p.get("grid_title") or grid)
            continue
        notres.append({
            "partition": p.get("partition"), "grid_name": grid,
            "titre": p.get("grid_title"), "du_type": p.get("du_type"),
            "portee": portee, "date_appro": _date_approbation(p.get("name")),
            "gpu_status": p.get("gpu_status"), "gpu_maj": p.get("gpu_timestamp"),
            "raw": p,
        })
    return notres, ecartes


def ensure_tables(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS urbanisme_documents (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            insee        TEXT NOT NULL,
            partition    TEXT NOT NULL,
            grid_name    TEXT,      -- INSEE de la commune, ou SIREN de l'EPCI
            titre        TEXT,
            du_type      TEXT,      -- PLU | PLUi | CC | POS | PSMV
            portee       TEXT,      -- communal | intercommunal
            couvre       INTEGER,   -- 1 = des zones de ce document sont sur la commune
            date_appro   TEXT,
            gpu_status   TEXT,
            gpu_maj      TEXT,
            raw_data     TEXT,
            created_at   TEXT DEFAULT (datetime('now')),
            UNIQUE(insee, partition)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS urbanisme_zonage (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            insee        TEXT NOT NULL,
            partition    TEXT,
            typezone     TEXT,      -- U | AUc | A | N…
            famille      TEXT,      -- urbaine | à urbaniser | agricole | naturelle
            zones        INTEGER,   -- nombre de polygones du document
            points       INTEGER,   -- points de mesure tombés dans ce type
            aire_m2      REAL,      -- surface DANS la commune, déduite de la part
            part_pct     REAL,      -- NULL si la couverture ne se vérifie pas
            couverture   REAL,      -- part des points de la commune couverts par une zone
            created_at   TEXT DEFAULT (datetime('now')),
            UNIQUE(insee, partition, typezone)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS urbanisme_statut (
            insee        TEXT PRIMARY KEY,
            nom          TEXT,
            rnu          INTEGER,   -- 1 = aucun document local : le RNU s'applique
            aire_km2     REAL,      -- contour officiel (geo.api.gouv.fr)
            aire_gpu_km2 REAL,      -- ce que le GPU croit être la commune
            documents    INTEGER,   -- documents RETENUS, pas rendus
            releve_le    TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()


def _enregistrer_event(conn, insee: str, commune_nom: str, doc: dict,
                       lat: float, lng: float) -> bool:
    """Un document approuvé est un fait daté : il a sa place dans la frise.

    Dédupliqué sur la partition, qui est l'identifiant du document au GPU.
    """
    ref = doc["partition"]
    if conn.execute("SELECT 1 FROM events WHERE type='urbanisme_document'"
                    " AND metadata LIKE ?", (f'%"{ref}"%',)).fetchone():
        return False
    quoi = {"PLUi": "Plan local d'urbanisme intercommunal",
            "PLU": "Plan local d'urbanisme",
            "CC": "Carte communale",
            "POS": "Plan d'occupation des sols",
            "PSMV": "Plan de sauvegarde et de mise en valeur"}.get(
                doc["du_type"], doc["du_type"] or "Document d'urbanisme")
    date = doc["date_appro"]
    titre = f"{quoi} — {doc['titre']}" if doc["portee"] == "intercommunal" else quoi
    conn.execute(
        "INSERT INTO events (type, date, title, content, source, source_url,"
        " metadata, origine) VALUES (?,?,?,?,?,?,?,'institutionnel')",
        ("urbanisme_document", date, titre,
         f"{quoi} déposé au Géoportail de l'urbanisme"
         + (f", approuvé le {date}." if date else ".")
         + " La publication au GPU est ce qui rend le document opposable.",
         SOURCE,
         f"https://www.geoportail-urbanisme.gouv.fr/map/#tile=1&lon={lng}"
         f"&lat={lat}&zoom=13",
         json.dumps({"partition": ref, "du_type": doc["du_type"],
                     "portee": doc["portee"], "commune": commune_nom},
                    ensure_ascii=False)))
    return True


def import_commune(insee: str, commune_nom: str) -> dict:
    releve = {"documents": 0, "ecartes": 0, "zones": 0, "rnu": None,
              "part_publiee": False}

    muni = _fetch(f"municipality?insee={insee}")
    traits = muni.get("features") or []
    if not traits:
        # Le GPU ne connaît pas ce code : ni RNU ni document ne se déduisent.
        print(f"  [plu] {commune_nom} — commune absente du GPU, rien à dire")
        return releve
    props = traits[0].get("properties") or {}
    releve["rnu"] = bool(props.get("is_rnu"))

    # 🔴 LE TERRITOIRE DE MESURE EST LE CONTOUR OFFICIEL, PAS CELUI DU GPU.
    # Sur Saillans, le polygone que rend le GPU couvre 15,64 km² quand la
    # commune en fait 37,42 : il a gardé un périmètre d'avant une fusion. Mesurer
    # dessus donnait des parts qui semblaient parfaites — la couverture valait
    # 0,99 — sur 42 % du territoire seulement. Un contrôle qui vérifie la
    # cohérence des zones ENTRE ELLES ne peut pas voir que le sol est le mauvais.
    geom = None
    try:
        geom = contour_commune(insee, source=SOURCE)
    except Exception as e:                              # noqa: BLE001
        print(f"    ↳ contour officiel indisponible : {e}")
    aire_gpu = aire_m2(traits[0]["geometry"], latitude_moyenne(traits[0]["geometry"]))
    if geom is None:
        # Repli : le polygone du GPU. Mieux vaut mesurer sur un périmètre
        # imparfait que ne rien mesurer, mais le journal doit le dire.
        print("    ↳ mesure sur le polygone du GPU, faute de contour officiel")
        geom = traits[0]["geometry"]
    lat0 = latitude_moyenne(geom)
    aire_commune = aire_m2(geom, lat0)
    releve["aire_gpu_km2"] = round(aire_gpu / 1e6, 3)
    releve["aire_km2"] = round(aire_commune / 1e6, 3)
    if aire_commune and abs(aire_gpu - aire_commune) / aire_commune > 0.05:
        # Quand l'instance déclare une commune déléguée, l'explication n'est plus
        # une hypothèse : la fusion est connue, et c'est elle que le GPU ignore.
        fusionnees = [d.get("nom") or code
                      for code, d in COMMUNES_DELEGUEES.items()
                      if d.get("commune") == insee]
        cause = (f" — fusion avec {', '.join(n for n in fusionnees if n) or 'une ancienne commune'}"
                 " que le GPU n'a pas reprise" if fusionnees else
                 " — périmètre d'avant fusion, probablement")
        print(f"    ⚠️ le GPU ne connaît que {100 * aire_gpu / aire_commune:.0f} % "
              f"du territoire de {commune_nom} "
              f"({aire_gpu / 1e6:.2f} km² sur {aire_commune / 1e6:.2f}){cause}")

    time.sleep(REQUEST_DELAY)
    documents = (_fetch("document", {"geom": geom}).get("features") or [])
    time.sleep(REQUEST_DELAY)
    zonage = (_fetch("zone-urba", {"geom": geom}).get("features") or [])

    notres, ecartes = attribuer(documents, insee, EPCI_SIREN)
    releve["ecartes"] = len(ecartes)

    # Une carte communale ne vit pas dans `zone-urba` mais dans `secteur-cc` :
    # sans cet appel, une commune dotée d'une CC aurait un document et zéro zone,
    # ce qui se lirait comme un zonage manquant.
    if any(d["du_type"] == "CC" for d in notres):
        time.sleep(REQUEST_DELAY)
        zonage += (_fetch("secteur-cc", {"geom": geom}).get("features") or [])

    partitions = {d["partition"] for d in notres}
    zones_a_nous = [f for f in zonage
                    if (f.get("properties") or {}).get("partition") in partitions]
    releve["zones"] = len(zones_a_nous)

    # ── Mesure sur le territoire COMMUNAL ───────────────────────────────────
    points = grille(geom, POINTS_VISES) if zones_a_nous else []
    # Boîtes englobantes d'abord : un point ne se teste contre le tracé d'une
    # zone que si la boîte de celle-ci le contient. Sans ce filtre, la mesure
    # coûterait le produit des points par les sommets de toutes les zones.
    boites = [(bbox(f["geometry"]), f) for f in zones_a_nous]
    releves: dict[tuple[str, str], int] = {}
    for x, y in points:
        for (bx0, by0, bx1, by1), f in boites:
            if not (bx0 <= x <= bx1 and by0 <= y <= by1):
                continue
            if dedans(x, y, f["geometry"]):
                p = f["properties"]
                cle = (p.get("partition"), (p.get("typezone") or "?").strip() or "?")
                releves[cle] = releves.get(cle, 0) + 1
                break            # une zone et une seule : le zonage ne se superpose pas

    # ⚠️ Être NOTRE document ne suffit pas : il faut qu'il couvre la commune.
    # Un PLUi se dépose par PARTITIONS territoriales — Brassac reçoit `_A` et
    # `_B` du même PLUi. Cinq zones de `_B` mordent sur son sol, mais le
    # document qui s'y applique est `_A` : retenir les deux ferait croire à deux
    # documents applicables. La preuve n'est donc pas le CONTACT d'une zone avec
    # la frontière, c'est la part du territoire qu'elle occupe vraiment — d'où
    # un seuil, mesuré sur les points intérieurs.
    points_par_partition: dict[str, int] = {}
    for (part, _), n in releves.items():
        points_par_partition[part] = points_par_partition.get(part, 0) + n
    mesures = sum(points_par_partition.values())
    for d in notres:
        d["couvre"] = (points_par_partition.get(d["partition"], 0)
                       >= max(1, PART_MIN_PARTITION * mesures))
    applicables = [d for d in notres if d["couvre"]]
    retenues = {d["partition"] for d in applicables}
    releve["documents"] = len(applicables)

    # Ce qui n'est pas retenu ne compte pas non plus dans les parts : sinon les
    # 5 zones de `_B` s'ajouteraient au dénominateur d'un document qui ne
    # s'applique pas ici.
    attribues = sum(n for (part, _), n in releves.items() if part in retenues)
    couverture = (attribues / len(points)) if points else 0.0
    publiable = bool(points) and couverture >= COUVERTURE_MIN
    releve["part_publiee"] = publiable
    releve["points"] = len(points)

    zones_par_cle: dict[tuple[str, str], int] = {}
    for f in zones_a_nous:
        p = f["properties"]
        cle = (p.get("partition"), (p.get("typezone") or "?").strip() or "?")
        zones_par_cle[cle] = zones_par_cle.get(cle, 0) + 1

    with transaction() as conn:
        ensure_tables(conn)
        for d in notres:
            conn.execute(
                "INSERT OR IGNORE INTO urbanisme_documents"
                " (insee,partition,grid_name,titre,du_type,portee,couvre,"
                "  date_appro,gpu_status,gpu_maj,raw_data)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (insee, d["partition"], d["grid_name"], d["titre"], d["du_type"],
                 d["portee"], int(d["couvre"]), d["date_appro"], d["gpu_status"],
                 d["gpu_maj"], json.dumps(d["raw"], ensure_ascii=False)))
            # Le dépôt d'un document peut être rejoué : la mise à jour du GPU
            # change, pas la clé.
            conn.execute("UPDATE urbanisme_documents SET gpu_status=?, gpu_maj=?"
                         " WHERE insee=? AND partition=?",
                         (d["gpu_status"], d["gpu_maj"], insee, d["partition"]))
            if d["couvre"]:
                _enregistrer_event(conn, insee, commune_nom, d,
                                   round(lat0, 5), round(_centre_lng(geom), 5))
        conn.execute("DELETE FROM urbanisme_zonage WHERE insee=?", (insee,))
        for (partition, t), n in sorted(zones_par_cle.items()):
            if partition not in retenues:
                continue
            mesures_zone = releves.get((partition, t), 0)
            part = (100 * mesures_zone / attribues) if publiable and attribues else None
            conn.execute(
                "INSERT INTO urbanisme_zonage"
                " (insee,partition,typezone,famille,zones,points,aire_m2,part_pct,"
                "  couverture) VALUES (?,?,?,?,?,?,?,?,?)",
                (insee, partition, t, _famille(t), n, mesures_zone,
                 # La surface est DÉDUITE de la part : c'est celle qui tombe dans
                 # la commune, la seule dont on puisse répondre. La somme des
                 # zones publiées, elle, déborde dès qu'un PLUi est en jeu.
                 round(aire_commune * part / 100, 1) if part is not None else None,
                 round(part, 2) if part is not None else None,
                 round(couverture, 3)))
        conn.execute(
            "INSERT INTO urbanisme_statut"
            " (insee,nom,rnu,aire_km2,aire_gpu_km2,documents,releve_le)"
            " VALUES (?,?,?,?,?,?,datetime('now'))"
            " ON CONFLICT(insee) DO UPDATE SET nom=excluded.nom, rnu=excluded.rnu,"
            " aire_km2=excluded.aire_km2, aire_gpu_km2=excluded.aire_gpu_km2,"
            " documents=excluded.documents, releve_le=excluded.releve_le",
            (insee, props.get("name") or commune_nom, int(releve["rnu"]),
             round(aire_commune / 1e6, 3), round(aire_gpu / 1e6, 3),
             len(applicables)))

    etat = ("RNU — aucun document local" if releve["rnu"]
            else ", ".join(f"{d['du_type']} ({d['portee']}"
                           + (f", {d['date_appro']}" if d["date_appro"] else "")
                           + ")" for d in applicables)
            or "aucun document déposé au GPU")
    mesure = ""
    if zones_a_nous:
        # Sans zone il n'y a rien à couvrir : afficher « couverture 0,00 » ferait
        # lire un défaut de collecte là où il y a une absence de document.
        mesure = (f" ; {len(zones_a_nous)} zone(s) sur {len(points)} points"
                  f", couverture {couverture:.2f}"
                  + ("" if publiable else " → parts NON publiées"))
    print(f"  [plu] {commune_nom} — {etat}{mesure}"
          + (f" ; {len(ecartes)} document(s) voisin(s) écarté(s)" if ecartes else ""))
    return releve


def _centre_lng(geom: dict) -> float:
    polys = (geom["coordinates"] if geom["type"] == "MultiPolygon"
             else [geom["coordinates"]])
    pts = [pt for p in polys for pt in p[0]]
    return sum(pt[0] for pt in pts) / len(pts)


def run(insee: str | None = None) -> int:
    cibles = [insee] if insee else communes_du_step("plu")
    total = 0
    for i, code in enumerate(cibles):
        nom = COMMUNES.get(code, {}).get("nom", code)
        try:
            r = import_commune(code, nom)
            total += r["documents"]
        except Exception as e:                      # noqa: BLE001
            print(f"  [plu] {nom} — ÉCHEC : {e}")
        if i < len(cibles) - 1:
            time.sleep(REQUEST_DELAY)
    print(f"[plu] {total} document(s) d'urbanisme sur {len(cibles)} commune(s)")
    return total


def stats():
    conn = get_conn()
    ensure_tables(conn)
    for r in conn.execute(
            "SELECT s.insee, s.nom, s.rnu, s.aire_km2, s.documents,"
            " (SELECT GROUP_CONCAT(du_type || ' ' || COALESCE(date_appro,'?'), ', ')"
            "  FROM urbanisme_documents d WHERE d.insee = s.insee AND d.couvre=1) docs"
            " FROM urbanisme_statut s ORDER BY s.nom"):
        print(f"  {r['nom'] or r['insee']:<28} {r['aire_km2'] or 0:7.1f} km²  "
              + ("RNU" if r["rnu"] else (r["docs"] or "aucun document")))
    for r in conn.execute(
            "SELECT insee, typezone, famille, zones, aire_m2, part_pct"
            " FROM urbanisme_zonage ORDER BY insee, aire_m2 DESC"):
        part = f"{r['part_pct']:5.1f} %" if r["part_pct"] is not None else "   — "
        print(f"    {r['insee']} {r['typezone']:<6} {r['famille'] or '':<14}"
              f" {r['zones']:>4} zone(s) {r['aire_m2']/1e6:8.2f} km² {part}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--insee", help="une seule commune")
    p.add_argument("--stats", action="store_true")
    a = p.parse_args()
    if a.stats:
        stats()
    else:
        run(a.insee)
