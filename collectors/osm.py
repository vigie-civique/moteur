"""
Collecteur OSM — points d'intérêt des communes du périmètre.

L'instance de référence importait un `lasalle_pois.geojson` produit par un
script hors dépôt : le fichier n'étant pas versionné (et n'ayant pas à l'être),
le collecteur s'arrêtait sur « introuvable » au premier lancement ici. Il
interroge donc Overpass lui-même, commune par commune — une requête par commune
plutôt qu'une requête globale, parce que c'est le seul moyen simple de savoir de
quelle commune relève chaque POI, et que `entities.commune` non renseignée fait
classer l'entité hors périmètre (cf. la note de `db.upsert_entity`).

Le résultat est mis en cache dans `territoire/pois_<insee>.geojson` : Overpass
est une ressource partagée, on ne la réinterroge pas à chaque exécution.
"""
import json
import time
import urllib.parse
import urllib.request

from .archive import archive_fetch
from .config import (COMMUNES, HEADERS, OVERPASS, REQUEST_DELAY, TERRITOIRE)
from .db import transaction, upsert_entity

# Clés OSM retenues : ce qui relève d'un service, d'un commerce, d'un lieu
# public ou du patrimoine. Le reste (bâti, voirie, nature) n'a pas d'usage
# civique et gonflerait la base sans rien documenter.
CLES = ("amenity", "shop", "tourism", "leisure", "historic", "office", "craft")

GABARIT = """[out:json][timeout:180];
area["ref:INSEE"="{insee}"]["boundary"="administrative"]->.a;
(
{filtres}
);
out center tags;"""

# Correspondance OSM value → catégorie service public
# OSM écrit `amenity=townhall` (sans tiret bas) : la valeur `town_hall` du
# registre d'origine ne matchait rien, et la mairie entrait comme simple lieu.
SERVICE_VALUES = {
    "post_office", "town_hall", "townhall", "school", "kindergarten",
    "fire_station", "police", "hospital", "doctors", "pharmacy",
    "library", "community_centre", "social_facility",
    "bus_station", "bus_stop"
}

SERVICE_CATEGORIES = {
    "post_office": "admin", "town_hall": "admin", "townhall": "admin",
    "school": "education", "kindergarten": "education",
    "fire_station": "sécurité", "police": "sécurité",
    "hospital": "santé", "doctors": "santé", "pharmacy": "santé",
    "library": "culture", "community_centre": "culture",
    "social_facility": "social",
    "bus_station": "transport", "bus_stop": "transport",
}


def _requete(insee: str) -> str:
    filtres = "\n".join(f'  nwr(area.a)["{cle}"];' for cle in CLES)
    return GABARIT.format(insee=insee, filtres=filtres)


def _telecharger(insee: str, nom: str) -> list[dict]:
    """POIs d'une commune, en cache local. Retourne des features GeoJSON."""
    TERRITOIRE.mkdir(parents=True, exist_ok=True)
    cache = TERRITOIRE / f"pois_{insee}.geojson"
    if cache.exists() and cache.stat().st_size > 0:
        return json.loads(cache.read_bytes()).get("features", [])

    donnees = urllib.parse.urlencode({"data": _requete(insee)}).encode()
    req = urllib.request.Request(OVERPASS, data=donnees, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=200) as r:
            raw = r.read()
    except Exception as e:
        print(f"  [osm][erreur] {nom} ({insee}) → {e}")
        return []
    archive_fetch("osm", OVERPASS, raw, "application/json", 200, doc_type="json",
                  title=f"overpass {nom}")
    elements = json.loads(raw).get("elements", [])

    features = []
    for el in elements:
        tags = el.get("tags", {})
        centre = el.get("center") or {}
        lat = el.get("lat", centre.get("lat"))
        lon = el.get("lon", centre.get("lon"))
        cle = next((c for c in CLES if c in tags), "")
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "id": f"{el.get('type')}/{el.get('id')}",
                "name": tags.get("name"),
                "category": cle,
                "value": tags.get(cle, ""),
                "commune": nom,
                "tags": tags,
            },
        })
    cache.write_text(json.dumps({"type": "FeatureCollection", "features": features},
                                ensure_ascii=False), encoding="utf-8")
    time.sleep(max(REQUEST_DELAY, 2))   # Overpass est une ressource partagée
    return features


def import_osm():
    features = []
    for insee, commune in COMMUNES.items():
        lot = _telecharger(insee, commune["nom"])
        print(f"  [osm] {commune['nom']:26} {len(lot):4} POIs")
        features += lot
    print(f"[osm] {len(features)} POIs sur {len(COMMUNES)} communes")

    inserted = skipped = 0

    with transaction() as conn:
        for feat in features:
            props = feat.get("properties", {})
            geom  = feat.get("geometry", {})
            name  = props.get("name")

            if not name:
                skipped += 1
                continue

            coords = geom.get("coordinates", [None, None])
            lng, lat = coords[0], coords[1]
            osm_id   = props.get("id")
            category = props.get("category", "")
            value    = props.get("value", "")
            tags     = props.get("tags", {})
            commune  = props.get("commune")

            # Type d'entité
            if value in SERVICE_VALUES:
                etype = "service"
            else:
                etype = "place"

            eid = upsert_entity(conn,
                type=etype,
                name=name,
                lat=float(lat) if lat else None,
                lng=float(lng) if lng else None,
                commune=commune,
                confidence="verified"
            )

            if etype == "service":
                cat = SERVICE_CATEGORIES.get(value, "autre")
                conn.execute(
                    "INSERT OR IGNORE INTO services"
                    " (entity_id,category,opening_hours)"
                    " VALUES (?,?,?)",
                    (eid, cat, tags.get("opening_hours"))
                )
            else:
                conn.execute(
                    "INSERT OR IGNORE INTO places"
                    " (entity_id,osm_id,osm_category,osm_value,tags)"
                    " VALUES (?,?,?,?,?)",
                    (eid, osm_id, category, value,
                     json.dumps(tags, ensure_ascii=False))
                )

            inserted += 1

    print(f"[osm] OK — {inserted} POIs importés, {skipped} sans nom ignorés")
