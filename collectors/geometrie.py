"""
geometrie.py — Le minimum géométrique dont plusieurs collecteurs ont besoin.

Contour d'une commune, appartenance d'un point, surface, échantillonnage : trois
collecteurs en dépendent (`plu`, `mobilite`, et le rattachement d'un arrêt ou
d'une parcelle à la commune). Ils vivaient dans le premier qui en a eu besoin —
les mettre ici évite qu'un import croisé entre collecteurs ne les lie deux à
deux.

Aucune dépendance ajoutée. `shapely` ferait tout cela mieux, mais il ne servirait
qu'ici : ce sont soixante lignes contre un paquet compilé sur toutes les
instances, y compris celles qui ne collectent ni urbanisme ni transport.

⚠️ Une commune n'est pas sa boîte englobante. Filtrer sur la bbox laisse entrer
ce qui appartient au voisin, et c'est la faute la plus facile à commettre : la
bbox de `instance.json` sert à INTERROGER des API qui n'acceptent qu'un
rectangle, jamais à conclure qu'un point est dans la commune. Pour conclure, il
faut le contour — `contour_commune()`.
"""
from __future__ import annotations

import math

from .archive import fetch_json
from .config import GEO_API


def contour_commune(insee: str, source: str = "geo-api") -> dict | None:
    """Le tracé officiel d'une commune, en GeoJSON, ou None.

    `geo.api.gouv.fr` est déjà la source du périmètre d'une instance
    (`scripts/init_instance.py`) : le contour vient donc du même endroit que le
    reste de son identité géographique.
    """
    url = f"{GEO_API}/communes/{insee}?fields=nom,contour&format=json"
    data = fetch_json(url, source=source, timeout=30)
    return (data or {}).get("contour")


def anneaux(geom: dict) -> list[list[list]]:
    """Les polygones d'une géométrie GeoJSON : extérieur d'abord, puis les trous."""
    return (geom["coordinates"] if geom["type"] == "MultiPolygon"
            else [geom["coordinates"]])


def bbox(geom: dict) -> tuple[float, float, float, float]:
    pts = [pt for poly in anneaux(geom) for pt in poly[0]]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def latitude_moyenne(geom: dict) -> float:
    """Latitude représentative, pour l'échelle des longitudes."""
    pts = [pt for p in anneaux(geom) for pt in p[0]]
    return sum(pt[1] for pt in pts) / len(pts)


def dans_anneau(x: float, y: float, anneau: list) -> bool:
    dedans = False
    n = len(anneau)
    j = n - 1
    for i in range(n):
        xi, yi = anneau[i][0], anneau[i][1]
        xj, yj = anneau[j][0], anneau[j][1]
        if (yi > y) != (yj > y):
            if x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                dedans = not dedans
        j = i
    return dedans


def dedans(x: float, y: float, geom: dict) -> bool:
    """Point dans un (Multi)Polygon — lancer de rayon, trous déduits."""
    for poly in anneaux(geom):
        if not dans_anneau(x, y, poly[0]):
            continue
        if any(dans_anneau(x, y, trou) for trou in poly[1:]):
            continue                      # dans un trou : hors du polygone
        return True
    return False


def aire_m2(geom: dict, lat0: float) -> float:
    """Surface d'un (Multi)Polygon, trous déduits.

    Projection équirectangulaire centrée sur `lat0`. À l'échelle d'une commune
    (moins de 30 km), l'écart à une projection conforme reste sous 0,1 % — et ce
    qu'on en tire est le plus souvent une PART, où l'erreur d'échelle se
    simplifie encore.
    """
    kx = math.cos(math.radians(lat0)) * 111320.0
    ky = 110574.0

    def _anneau(coords) -> float:
        s = 0.0
        for i in range(len(coords) - 1):
            x1, y1 = coords[i][0] * kx, coords[i][1] * ky
            x2, y2 = coords[i + 1][0] * kx, coords[i + 1][1] * ky
            s += x1 * y2 - x2 * y1
        return abs(s) / 2

    return sum(_anneau(p[0]) - sum(_anneau(t) for t in p[1:])
               for p in anneaux(geom))


def grille(geom: dict, points_vises: int) -> list[tuple[float, float]]:
    """Points d'une grille régulière tombant DANS la géométrie.

    Le pas est calculé pour que la boîte englobante en porte assez ; une commune
    découpée n'occupe qu'une part de sa boîte, donc on vise large et on garde ce
    qui tombe dedans. Régulière et non tirée au sort : une recollecte doit rendre
    le même chiffre, sans quoi une variation de mesure se lirait comme une
    variation du territoire.
    """
    x0, y0, x1, y1 = bbox(geom)
    largeur, hauteur = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
    # Facteur 2 : la commune remplit rarement plus de la moitié de sa boîte.
    pas = math.sqrt(largeur * hauteur / max(points_vises * 2, 1))
    points = []
    ny = max(int(hauteur / pas), 1)
    nx = max(int(largeur / pas), 1)
    for iy in range(ny):
        y = y0 + (iy + 0.5) * hauteur / ny
        for ix in range(nx):
            x = x0 + (ix + 0.5) * largeur / nx
            if dedans(x, y, geom):
                points.append((x, y))
    return points


def point_interieur(geom: dict) -> tuple[float, float] | None:
    """Un point garanti DANS la géométrie : (lng, lat).

    Le centre des sommets suffit pour une commune compacte, mais une commune en
    croissant, en anneau, ou coupée par une rivière le pose dehors — et une API
    interrogée sur ce point-là répondrait pour la commune voisine. On vérifie
    donc, et à défaut on prend le premier point d'une grille grossière.
    """
    pts = [pt for p in anneaux(geom) for pt in p[0]]
    if not pts:
        return None
    x = sum(p[0] for p in pts) / len(pts)
    y = sum(p[1] for p in pts) / len(pts)
    if dedans(x, y, geom):
        return x, y
    interieurs = grille(geom, 400)
    return interieurs[len(interieurs) // 2] if interieurs else None
