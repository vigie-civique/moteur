"""
Collecteur OSM — importe lasalle_pois.geojson en base.
"""
import json
from .archive import archive_fetch
from .config import TERRITOIRE
from .db import transaction, upsert_entity

# Correspondance OSM value → catégorie service public
SERVICE_VALUES = {
    "post_office", "town_hall", "school", "kindergarten",
    "fire_station", "police", "hospital", "doctors", "pharmacy",
    "library", "community_centre", "social_facility",
    "bus_station", "bus_stop"
}

SERVICE_CATEGORIES = {
    "post_office": "admin", "town_hall": "admin",
    "school": "education", "kindergarten": "education",
    "fire_station": "sécurité", "police": "sécurité",
    "hospital": "santé", "doctors": "santé", "pharmacy": "santé",
    "library": "culture", "community_centre": "culture",
    "social_facility": "social",
    "bus_station": "transport", "bus_stop": "transport",
}


def import_osm():
    geojson_path = TERRITOIRE / "lasalle_pois.geojson"
    if not geojson_path.exists():
        print("[osm] lasalle_pois.geojson introuvable")
        return

    raw = geojson_path.read_bytes()
    archive_fetch("osm", None, raw, doc_type="json", title=geojson_path.name)
    data = json.loads(raw)
    features = data.get("features", [])
    print(f"[osm] {len(features)} POIs dans le GeoJSON")

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
