"""
Collecteur OSM — points d'intérêt des communes suivies en profondeur.

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
from .config import (HEADERS, OVERPASS, REQUEST_DELAY, TERRITOIRE,
                     registre_du_step)
from .db import transaction, upsert_entity

# Clés OSM retenues : ce qui relève d'un service, d'un commerce, d'un lieu
# public ou du patrimoine. Le reste (bâti, voirie, nature) n'a pas d'usage
# civique et gonflerait la base sans rien documenter.
#
# `place` a été ajoutée le 15/08/2026 : elle porte les hameaux, lieux-dits et
# écarts — Le Valat, Sauveplane, La Borie, Prumeiren. Dans une commune rurale
# étendue, c'est la toponymie qui permet de situer une délibération de voirie ou
# une parcelle ; sans elle, la carte ne montre que le bourg. Mesuré sur la base
# historique de l'instance d'origine : 109 des 263 lieux non catégorisés en
# portaient un.
CLES = ("amenity", "shop", "tourism", "leisure", "historic", "office", "craft",
        "place")

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


def nom_utilisable(nom: str | None) -> bool:
    """Un nom sans une seule lettre n'est pas un nom.

    OSM range les panneaux d'information sous `tourism=information`, et le
    `name` y porte le NUMÉRO du panneau. Lasalle en a reçu dix, nommés « 2 » à
    « 10 » et « ? » : ils occupaient la TOTALITÉ de l'onglet « Lieu » de
    l'atelier, en tête de liste puisque les chiffres se trient avant les
    lettres. Le critère est lexical, pas une liste de valeurs OSM à tenir :
    une borne utilement nommée (« Panneau 3 — le Valat ») passe, « 3 » non.
    """
    return any(c.isalpha() for c in (nom or ""))


def _requete(insee: str) -> str:
    filtres = "\n".join(f'  nwr(area.a)["{cle}"];' for cle in CLES)
    return GABARIT.format(insee=insee, filtres=filtres)


# Overpass est une ressource partagée et bridée. Elle répond 429 puis coupe la
# connexion quand on la sollicite trop vite : le 14/08/2026, une collecte a
# obtenu 2 communes sur 15 — dont pas la commune principale — parce que le
# collecteur enchaînait les requêtes toutes les 2 secondes et abandonnait à la
# première erreur. Le site s'est donc retrouvé sans aucun lieu, et le step
# était enregistré « ok ».
ATTENTE_ENTRE_REQUETES = 4      # secondes, même après un échec
TENTATIVES = 4
ATTENTE_APRES_REFUS = 30        # 429 ou connexion coupée : on laisse retomber


def _interroger(insee: str, nom: str) -> bytes | None:
    """Une requête Overpass, avec temporisation croissante sur refus."""
    donnees = urllib.parse.urlencode({"data": _requete(insee)}).encode()
    for tentative in range(1, TENTATIVES + 1):
        req = urllib.request.Request(OVERPASS, data=donnees, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=200) as r:
                return r.read()
        except Exception as e:
            dernier = tentative == TENTATIVES
            print(f"  [osm][{tentative}/{TENTATIVES}] {nom} ({insee}) → {e}"
                  + ("" if dernier else f", nouvelle tentative dans "
                     f"{ATTENTE_APRES_REFUS * tentative} s"))
            if dernier:
                return None
            time.sleep(ATTENTE_APRES_REFUS * tentative)
    return None


def _telecharger(insee: str, nom: str) -> list[dict] | None:
    """POIs d'une commune, en cache local.

    Retourne None si la commune n'a pas pu être interrogée — à distinguer d'une
    commune réellement sans POI, qui rend une liste vide.
    """
    TERRITOIRE.mkdir(parents=True, exist_ok=True)
    cache = TERRITOIRE / f"pois_{insee}.geojson"
    if cache.exists() and cache.stat().st_size > 0:
        donnees = json.loads(cache.read_bytes())
        # Le cache porte les clés qui l'ont produit : élargir CLES sans le dire
        # laissait le cache répondre pour l'ancienne requête, et le changement
        # restait sans effet jusqu'à ce que quelqu'un vide le répertoire.
        if list(donnees.get("cles") or ()) == list(CLES):
            return donnees.get("features", [])
        print(f"  [osm] {nom} — clés élargies, cache réinterrogé")

    raw = _interroger(insee, nom)
    # La temporisation vaut aussi après un échec : sans elle, une série
    # d'erreurs martèle le serveur plus vite qu'une série de succès.
    time.sleep(max(REQUEST_DELAY, ATTENTE_ENTRE_REQUETES))
    if raw is None:
        return None
    try:
        json.loads(raw)
    except json.JSONDecodeError:
        # Overpass rend une page d'erreur en HTML quand il refuse : elle serait
        # tombée hors du filet précédent, qui n'entourait que l'appel réseau.
        print(f"  [osm][erreur] {nom} ({insee}) → réponse illisible "
              f"({raw[:60]!r})")
        return None
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
    cache.write_text(json.dumps({"type": "FeatureCollection", "cles": list(CLES),
                                 "features": features},
                                ensure_ascii=False), encoding="utf-8")
    return features


def import_osm():
    # Les points d'intérêt relèvent de la profondeur `fond` : la carte d'un site
    # communal montre sa commune. Interroger Overpass sur les quinze communes de
    # l'intercommunalité remplissait la carte de commerces qui ne s'y trouvent
    # pas.
    communes = registre_du_step("osm")
    features = []
    echecs = []
    for insee, commune in communes.items():
        lot = _telecharger(insee, commune["nom"])
        if lot is None:
            echecs.append(f"{commune['nom']} ({insee})")
            print(f"  [osm] {commune['nom']:26}    ? non interrogée")
            continue
        print(f"  [osm] {commune['nom']:26} {len(lot):4} POIs")
        features += lot
    print(f"[osm] {len(features)} POIs sur "
          f"{len(communes) - len(echecs)}/{len(communes)} communes")

    inserted = skipped = sans_lettre = 0

    with transaction() as conn:
        for feat in features:
            props = feat.get("properties", {})
            geom  = feat.get("geometry", {})
            name  = props.get("name")

            if not name:
                skipped += 1
                continue

            if not nom_utilisable(name):
                sans_lettre += 1
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

    print(f"[osm] {inserted} POIs importés, {skipped} sans nom "
          f"et {sans_lettre} sans aucune lettre ignorés")

    # Une collecte partielle n'est pas une collecte. Le 14/08/2026, ce step a
    # rendu « ok » avec 13 communes sur 15 en échec — dont la commune
    # principale — et le site publié n'avait aucun lieu. Le journal
    # `collector_runs` doit porter l'échec, pas le nombre de lignes écrites.
    # Les communes obtenues sont conservées en cache : rejouer le step ne
    # réinterroge que celles qui manquent.
    if echecs:
        raise RuntimeError(
            f"{len(echecs)} commune(s) sur {len(COMMUNES)} non interrogées "
            f"(Overpass limite le débit) : {', '.join(echecs[:6])}"
            + (" …" if len(echecs) > 6 else "")
            + " — relancer le step, le cache évite de refaire le travail fait.")
