"""
Géocodage — IGN Géoplateforme (primaire) + BAN (fallback).

Coordonnées stockées :
  lat / lng      WGS84  (EPSG:4326) — pour Leaflet
  x_l93 / y_l93 Lambert 93 (EPSG:2154) — pour calculs métriques

Sources utilisées dans l'ordre :
  1. IGN Géoplateforme  geocodage.api.gouv.fr  (meilleure couverture rurale + lieux-dits)
  2. BAN                api-adresse.data.gouv.fr (fallback)
  3. IGN parcel         lookup par référence cadastrale (DVF)
"""
import math
import time
import urllib.parse
import urllib.request
import json
from .config import CODE_POSTAL, HEADERS, REQUEST_DELAY, COMMUNE_INSEE

# ── APIs ──────────────────────────────────────────────────────────────────────
# IGN Géoplateforme (data.geopf.fr, 2023+) — retourne x/y Lambert 93 nativement, sans clé
IGN_SEARCH  = "https://data.geopf.fr/geocodage/search"
# IGN Apicarto — parcelles cadastrales (polygone + centroïde)
IGN_PARCEL  = "https://apicarto.ign.fr/api/cadastre/parcelle"
BAN_API     = "https://api-adresse.data.gouv.fr/search/"

# ── Conversion Lambert 93 (EPSG:2154) ↔ WGS84 (EPSG:4326) ──────────────────
# Formule IAG officielle, précision < 1 m sur la France métropolitaine.

_A  = 6378137.0        # demi-grand axe GRS80
_E  = 0.08181919104    # excentricité GRS80
_N  = 0.7256077650     # exposant de la conique
_C  = 11754255.426     # constante de la projection
_XS = 700000.0         # fausse abscisse
_YS = 12655612.050     # ordonnée du pôle
_L0 = math.radians(3.0)  # méridien central Lambert 93


def wgs84_to_l93(lat_deg: float, lon_deg: float) -> tuple[float, float]:
    """WGS84 → Lambert 93. Retourne (x, y) en mètres, arrondis au cm."""
    phi = math.radians(lat_deg)
    lam = math.radians(lon_deg)
    sin_phi = math.sin(phi)
    l = math.log(
        math.tan(math.pi / 4 + phi / 2)
        * ((1 - _E * sin_phi) / (1 + _E * sin_phi)) ** (_E / 2)
    )
    x = _XS + _C * math.exp(-_N * l) * math.sin(_N * (lam - _L0))
    y = _YS - _C * math.exp(-_N * l) * math.cos(_N * (lam - _L0))
    return round(x, 2), round(y, 2)


def l93_to_wgs84(x: float, y: float) -> tuple[float, float]:
    """Lambert 93 → WGS84. Retourne (lat, lng) en degrés décimaux."""
    dx = x - _XS
    dy = _YS - y
    r  = math.sqrt(dx**2 + dy**2)
    gamma = math.atan2(dx, dy)
    lam = _L0 + gamma / _N
    l   = -math.log(abs(r / _C)) / _N
    phi = 2 * math.atan(math.exp(l)) - math.pi / 2
    for _ in range(10):
        sin_phi = math.sin(phi)
        phi2 = 2 * math.atan(
            math.exp(l) * ((1 + _E * sin_phi) / (1 - _E * sin_phi)) ** (_E / 2)
        ) - math.pi / 2
        if abs(phi2 - phi) < 1e-12:
            break
        phi = phi2
    return round(math.degrees(phi2), 7), round(math.degrees(lam), 7)


# ── Géocodage IGN ─────────────────────────────────────────────────────────────

def _ign_request(url: str, params: dict) -> list[dict]:
    qs  = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(f"{url}?{qs}", headers={**HEADERS, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        return data.get("features", [])
    except Exception:
        return []


def _parse_ign(feat: dict) -> dict | None:
    """
    Extrait lat/lng (WGS84) + x/y (Lambert 93) + score d'un feature IGN.
    L'IGN renvoie les propriétés x/y déjà en EPSG:2154.
    """
    props = feat.get("properties", {})
    geom  = feat.get("geometry", {})
    score = float(props.get("score", 0))
    if score < 0.3:
        return None
    coords = geom.get("coordinates", [])
    if len(coords) < 2:
        return None
    lng, lat = float(coords[0]), float(coords[1])
    x = props.get("x")
    y = props.get("y")
    if x is None or y is None:
        x, y = wgs84_to_l93(lat, lng)
    return {
        "lat": lat, "lng": lng,
        "x_l93": round(float(x), 2), "y_l93": round(float(y), 2),
        "score": score,
        "source": "ign",
        "type": props.get("type", ""),
        "label": props.get("label", ""),
    }


def geocode_ign(address: str, postcode: str = CODE_POSTAL) -> dict | None:
    """
    Géocode via IGN Géoplateforme.
    Stratégie :
      1. housenumber avec code postal  (score ≥ 0.5)
      2. locality / lieu-dit           (score ≥ 0.4)  ← clé pour zones rurales
      3. requête libre                 (score ≥ 0.35)
    """
    if not address:
        return None

    feats = _ign_request(IGN_SEARCH, {
        "q": f"{address} {postcode}", "postcode": postcode,
        "limit": 1, "type": "housenumber",
    })
    if feats:
        r = _parse_ign(feats[0])
        if r and r["score"] >= 0.5:
            return r

    feats = _ign_request(IGN_SEARCH, {
        "q": f"{address} {postcode}", "citycode": COMMUNE_INSEE,
        "limit": 1, "type": "locality",
    })
    if feats:
        r = _parse_ign(feats[0])
        if r and r["score"] >= 0.4:
            return r

    feats = _ign_request(IGN_SEARCH, {
        "q": f"{address} {postcode} Lasalle", "limit": 1,
    })
    if feats:
        r = _parse_ign(feats[0])
        if r and r["score"] >= 0.35:
            return r

    return None


def geocode_parcel(cadastre_ref: str, city_code: str = COMMUNE_INSEE) -> dict | None:
    """
    Géocode une parcelle cadastrale via IGN Apicarto.
    Ex: cadastre_ref='AD0180', city_code='30140'
    Retourne le centroïde du polygone parcellaire.
    """
    if not cadastre_ref:
        return None
    ref     = cadastre_ref.strip().upper().replace(" ", "")
    section = ''.join(c for c in ref if c.isalpha())
    numero  = ''.join(c for c in ref if c.isdigit()).zfill(4)

    params = urllib.parse.urlencode({
        "code_insee": city_code, "section": section, "numero": numero
    })
    req = urllib.request.Request(f"{IGN_PARCEL}?{params}", headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
    except Exception:
        return None

    feats = data.get("features", [])
    if not feats:
        return None

    # Calculer le centroïde du premier polygone (moyenne des sommets extérieurs)
    geom = feats[0].get("geometry", {})
    gtype = geom.get("type", "")
    rings = []
    if gtype == "Polygon":
        rings = geom["coordinates"]
    elif gtype == "MultiPolygon":
        rings = [ring for poly in geom["coordinates"] for ring in poly]

    if not rings:
        return None

    all_pts = [pt for ring in rings for pt in ring]
    lng = sum(p[0] for p in all_pts) / len(all_pts)
    lat = sum(p[1] for p in all_pts) / len(all_pts)
    x, y = wgs84_to_l93(lat, lng)
    return {
        "lat": round(lat, 7), "lng": round(lng, 7),
        "x_l93": x, "y_l93": y,
        "score": 1.0, "source": "ign_parcel",
        "type": "parcel",
        "label": f"{city_code} {section} {numero}",
    }


# ── Fallback BAN ─────────────────────────────────────────────────────────────

def _geocode_ban(address: str, postcode: str = CODE_POSTAL) -> dict | None:
    for extra, min_score in [("", 0.5), (" Lasalle", 0.4)]:
        params = urllib.parse.urlencode({
            "q": f"{address}{extra}", "postcode": postcode, "limit": 1
        })
        try:
            req = urllib.request.Request(f"{BAN_API}?{params}", headers=HEADERS)
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read())
            feats = data.get("features", [])
            if feats and feats[0]["properties"].get("score", 0) > min_score:
                lng, lat = feats[0]["geometry"]["coordinates"]
                lat, lng = float(lat), float(lng)
                x, y = wgs84_to_l93(lat, lng)
                return {"lat": lat, "lng": lng, "x_l93": x, "y_l93": y,
                        "score": feats[0]["properties"]["score"],
                        "source": "ban", "type": "locality", "label": ""}
        except Exception:
            pass
    return None


# ── Interface publique ────────────────────────────────────────────────────────

def geocode(address: str, postcode: str = CODE_POSTAL) -> dict | None:
    """
    Géocode une adresse. Retourne un dict avec lat, lng, x_l93, y_l93, score, source.
    Retourne None si aucun résultat acceptable.
    """
    if not address:
        return None
    time.sleep(REQUEST_DELAY)
    return geocode_ign(address, postcode) or _geocode_ban(address, postcode)


def geocode_batch(records: list[dict],
                  addr_field: str = "address",
                  postcode_field: str | None = None) -> list[dict]:
    """
    Géocode une liste de dicts. Enrichit lat/lng/x_l93/y_l93/geocode_source/geocode_score.
    Ne modifie pas les enregistrements déjà géocodés.
    """
    for r in records:
        if r.get("lat") and r.get("lng"):
            continue
        addr = r.get(addr_field, "")
        pc   = r.get(postcode_field, CODE_POSTAL) if postcode_field else CODE_POSTAL
        res  = geocode(addr, pc)
        if res:
            r["lat"]            = res["lat"]
            r["lng"]            = res["lng"]
            r["x_l93"]          = res["x_l93"]
            r["y_l93"]          = res["y_l93"]
            r["geocode_source"] = res["source"]
            r["geocode_score"]  = res["score"]
    return records
