#!/usr/bin/env python3
"""Extrait le fond de carte de l'instance : un fichier, servi avec le site.

Pourquoi
--------
Les trois cartes du site chargeaient leurs tuiles chez des tiers — CARTO pour
/carte, `tile.openstreetmap.org` pour /urbanisme et /entite. Trois défauts, dont
deux ne se voient pas :

1. **L'IP de chaque visiteur part chez un tiers**, alors que la page
   Confidentialité promet qu'aucun traceur ne suit le lecteur. Un fond de carte
   distant est une requête vers un serveur étranger, sur chaque page qui en
   porte une.
2. **Un dossier hors-ligne n'a pas de fond de carte du tout** : les repères
   flottent sur du vide.
3. La politique d'usage des tuiles d'openstreetmap.org **interdit** l'usage
   systématique dont relève un site prérendu de plusieurs milliers de fiches.

Un extrait PMTiles règle les trois : un fichier unique, servi comme le reste du
site, lu par plages. Rien ne sort du domaine.

Ce que ça coûte
---------------
L'emprise n'est PAS celle de l'intercommunalité mais celle des points réellement
affichés : une commune tient en 1 à 6 Mo jusqu'au zoom 15, une ville moyenne en
une quinzaine. L'EPCI entier demanderait 30 à 120 Mo — au-delà des 25 Mio
qu'accepte Cloudflare Pages pour un fichier. D'où le garde-fou en fin de course.

Usage
-----
    python3 scripts/carte_fond.py                 # emprise déduite du snapshot
    python3 scripts/carte_fond.py --maxzoom 14    # deux fois plus léger
    python3 scripts/carte_fond.py --bbox 44.0,3.8,44.1,3.9

Source : builds quotidiens de Protomaps (OpenStreetMap, ODbL). On n'y puise
qu'une fois, à la fabrication — le site servi ne les appelle jamais, ce qui est
l'usage que Protomaps recommande.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SORTIE = RACINE / "public" / "static" / "carte" / "fond.pmtiles"
LAYERS = RACINE / "public" / "static" / "data" / "layers"

INDEX_BUILDS = "https://build-metadata.protomaps.dev/builds.json"
BASE_BUILDS = "https://build.protomaps.com/"

# S'identifier plutôt que de se faire passer pour un navigateur : le service
# refuse d'ailleurs l'agent par défaut de Python (403).
UA = "vigie-civique (fond de carte, une extraction par instance)"

# Limite d'un fichier sur Cloudflare Pages. Au-delà, le déploiement échoue —
# autant le dire ici, où l'on peut encore baisser le zoom.
MAX_OCTETS = 25 * 1024 * 1024


def dernier_build() -> str:
    r = urllib.request.Request(INDEX_BUILDS, headers={"User-Agent": UA})
    with urllib.request.urlopen(r, timeout=60) as f:
        builds = json.load(f)
    return BASE_BUILDS + builds[-1]["key"]


def lecteur_distant(url: str):
    """`get_bytes` pour le Reader, avec cache des plages déjà lues.

    Sans cache, le répertoire racine (15 Ko) serait retéléchargé à chaque tuile
    demandée : `Reader.get` le relit systématiquement.
    """
    cache: dict[tuple[int, int], bytes] = {}
    compteur = {"requetes": 0, "octets": 0}

    def get_bytes(offset: int, length: int) -> bytes:
        cle = (offset, length)
        if cle in cache:
            return cache[cle]
        r = urllib.request.Request(
            url, headers={"Range": f"bytes={offset}-{offset + length - 1}", "User-Agent": UA})
        with urllib.request.urlopen(r, timeout=120) as f:
            data = f.read()
        compteur["requetes"] += 1
        compteur["octets"] += len(data)
        # Les répertoires sont relus des dizaines de fois, les tuiles une seule :
        # ne garder que ce qui est petit évite de doubler la mémoire du script.
        if length <= 1 << 20:
            cache[cle] = data
        return data

    return get_bytes, compteur


def emprise_du_snapshot(marge: float = 0.35) -> tuple[float, float, float, float]:
    """Emprise des points publiés, élargie d'une marge.

    C'est ce que la carte montre, et rien de plus : couvrir l'intercommunalité
    entière multiplierait le fichier par vingt pour des tuiles que personne
    n'affiche.

    La marge est large (35 %) parce que la carte se cadre sur les repères, puis
    remplit l'écran autour : sur un écran large, on voit bien au-delà de la
    dernière fiche. Trop juste, le fond s'arrête en plein cadre et laisse des
    bandes blanches sur les côtés.
    """
    lats: list[float] = []
    lons: list[float] = []
    for f in sorted(LAYERS.glob("*.geojson")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for ft in d.get("features", []):
            c = (ft.get("geometry") or {}).get("coordinates")
            if c and len(c) == 2 and all(isinstance(v, (int, float)) for v in c):
                lons.append(c[0])
                lats.append(c[1])
    if not lats:
        raise SystemExit(
            f"Aucun point dans {LAYERS} : construire le snapshot d'abord "
            "(scripts/build_public_snapshot.py), ou passer --bbox.")
    dlat = max(max(lats) - min(lats), 0.02) * marge
    dlon = max(max(lons) - min(lons), 0.02) * marge
    return (min(lats) - dlat, min(lons) - dlon, max(lats) + dlat, max(lons) + dlon)


def tuiles_de(bbox, zmin: int, zmax: int):
    """Les (z, x, y) qui couvrent l'emprise, du plus large au plus fin."""
    lat1, lon1, lat2, lon2 = bbox
    for z in range(zmin, zmax + 1):
        n = 2 ** z
        def x_de(lon): return min(n - 1, max(0, int((lon + 180) / 360 * n)))
        def y_de(lat):
            lat = max(-85.05, min(85.05, lat))
            return min(n - 1, max(0, int(
                (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)))
        for x in range(x_de(lon1), x_de(lon2) + 1):
            for y in range(y_de(lat2), y_de(lat1) + 1):
                yield z, x, y


def main() -> int:
    ap = argparse.ArgumentParser(description="Extrait le fond de carte de l'instance")
    ap.add_argument("--bbox", help="lat_min,lon_min,lat_max,lon_max (défaut : les points publiés)")
    ap.add_argument("--maxzoom", type=int, default=15,
                    help="15 = les rues d'un village (défaut). Chaque niveau en moins divise "
                         "le poids par ~4")
    ap.add_argument("--minzoom", type=int, default=0)
    ap.add_argument("--source", help="URL d'un build PMTiles (défaut : le plus récent)")
    ap.add_argument("--sortie", type=Path, default=SORTIE)
    args = ap.parse_args()

    bbox = (tuple(float(v) for v in args.bbox.split(","))
            if args.bbox else emprise_du_snapshot())
    if len(bbox) != 4:
        raise SystemExit("--bbox attend quatre nombres : lat_min,lon_min,lat_max,lon_max")

    url = args.source or dernier_build()
    print(f"[fond] source   : {url}")
    print(f"[fond] emprise  : lat {bbox[0]:.4f}→{bbox[2]:.4f}  lon {bbox[1]:.4f}→{bbox[3]:.4f}")

    from pmtiles.reader import Reader          # noqa: PLC0415 — dépendance optionnelle
    from pmtiles.reader import zxy_to_tileid
    from pmtiles.writer import Writer

    get_bytes, compteur = lecteur_distant(url)
    lecteur = Reader(get_bytes)
    entete = lecteur.header()
    zmax = min(args.maxzoom, entete["max_zoom"])
    if zmax < args.maxzoom:
        print(f"[fond] la source s'arrête au zoom {zmax} : maxzoom ramené là")

    cibles = sorted(tuiles_de(bbox, args.minzoom, zmax),
                    key=lambda t: zxy_to_tileid(*t))
    print(f"[fond] {len(cibles)} tuiles à copier (zoom {args.minzoom}–{zmax})")

    args.sortie.parent.mkdir(parents=True, exist_ok=True)
    provisoire = args.sortie.with_suffix(".pmtiles.partiel")
    copiees = vides = 0
    with open(provisoire, "wb") as f:
        w = Writer(f)
        for i, (z, x, y) in enumerate(cibles, 1):
            data = lecteur.get(z, x, y)
            # Une tuile absente est normale : la mer, un massif sans rien de
            # cartographié. Elle ne s'écrit pas, le rendu la traite comme vide.
            if data:
                w.write_tile(zxy_to_tileid(z, x, y), data)
                copiees += 1
            else:
                vides += 1
            if i % 25 == 0 or i == len(cibles):
                print(f"\r[fond] {i}/{len(cibles)} tuiles…", end="", flush=True)
        print()
        meta = lecteur.metadata()
        w.finalize(
            {
                "tile_type": entete["tile_type"],
                "tile_compression": entete["tile_compression"],
                "min_zoom": args.minzoom,
                "max_zoom": zmax,
                "min_lon_e7": int(bbox[1] * 1e7), "min_lat_e7": int(bbox[0] * 1e7),
                "max_lon_e7": int(bbox[3] * 1e7), "max_lat_e7": int(bbox[2] * 1e7),
                "center_zoom": zmax - 2,
                "center_lon_e7": int((bbox[1] + bbox[3]) / 2 * 1e7),
                "center_lat_e7": int((bbox[0] + bbox[2]) / 2 * 1e7),
            },
            meta,
        )

    taille = provisoire.stat().st_size
    if taille > MAX_OCTETS:
        provisoire.unlink()
        raise SystemExit(
            f"\n✖ {taille / 1024 / 1024:.1f} Mo — au-dessus des 25 Mio qu'accepte "
            f"Cloudflare Pages pour un fichier.\n"
            f"  Relancer avec --maxzoom {zmax - 1} (environ quatre fois plus léger).")

    # Renommage final : un fond à moitié écrit ne remplace jamais celui qui sert.
    os.replace(provisoire, args.sortie)
    print(f"[fond] {args.sortie.relative_to(RACINE) if args.sortie.is_relative_to(RACINE) else args.sortie}"
          f" — {taille / 1024 / 1024:.2f} Mo, {copiees} tuiles ({vides} vides ignorées)")
    print(f"[fond] {compteur['requetes']} requêtes, "
          f"{compteur['octets'] / 1024 / 1024:.1f} Mo lus chez la source")
    print(f"[fond] attribution : {meta.get('attribution', '—')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
