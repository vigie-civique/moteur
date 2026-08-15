#!/usr/bin/env python3
"""
init_instance.py — Amorce une instance à partir d'un code INSEE.

Écrit `config/instance.json` et adapte `config/publication_rules.json` en
interrogeant les référentiels nationaux :

  geo.api.gouv.fr                     commune, code postal, population, EPCI,
                                      communes membres, contour, centroïde
  recherche-entreprises.api.gouv.fr   SIREN et SIRET de la collectivité,
                                      SIREN de l'EPCI, communes déléguées
                                      encore inscrites au répertoire

Ce que le script NE devine pas, et qu'il laisse à renseigner :

  - l'adresse du site de la mairie et celle de l'intercommunalité. Aucun
    référentiel national ne les publie de façon fiable ; le script propose des
    candidats et vérifie lesquels répondent, mais c'est un humain qui tranche.
  - le connecteur à utiliser pour les lire (cf. collectors/connecteurs/).
  - le chemin des recueils de la préfecture, dont l'arborescence change d'un
    département à l'autre.

Ce partage est le résultat du portage documenté dans docs/portage-brassac.md :
tout ce qui est national s'automatise, les sites officiels non.

Usage :
  python3 scripts/init_instance.py 81037
  python3 scripts/init_instance.py 81037 --dry-run
  python3 scripts/init_instance.py 81037 --force     # écrase une instance
  python3 scripts/init_instance.py 81037 --regles    # rafraîchit les règles
                                                     # après avoir complété les
                                                     # adresses des sites
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTANCE = ROOT / "config" / "instance.json"
REGLES = ROOT / "config" / "publication_rules.json"
REGLES_EXEMPLE = ROOT / "config" / "publication_rules.exemple.json"

GEO = "https://geo.api.gouv.fr"
ENTREPRISES = "https://recherche-entreprises.api.gouv.fr/search"
UA = {"User-Agent": "VigieCivique/1.0 (amorçage d'instance, données publiques)"}


def _get(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        print(f"  [erreur] {url} → {e}", file=sys.stderr)
        return None


def _repond(url: str) -> bool:
    """Le site répond-il ? Un candidat qui ne répond pas n'est pas proposé."""
    req = urllib.request.Request(url, headers=UA, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status < 400
    except Exception:
        return False


def _bbox(contour: dict) -> list[float]:
    """(sud, ouest, nord, est) depuis le contour communal, arrondi à l'extérieur."""
    coords = contour["coordinates"]
    points = []
    pile = list(coords)
    while pile:
        item = pile.pop()
        if isinstance(item[0], (int, float)):
            points.append(item)
        else:
            pile.extend(item)
    lats = [p[1] for p in points]
    lngs = [p[0] for p in points]
    marge = 0.01
    return [round(min(lats) - marge, 4), round(min(lngs) - marge, 4),
            round(max(lats) + marge, 4), round(max(lngs) + marge, 4)]


def _sirens(insee: str, nom: str) -> tuple[str, str]:
    """SIREN et SIRET de la collectivité, depuis le répertoire des entreprises.

    Le SIREN d'une commune est construit : « 21 », puis le département sur deux
    chiffres, puis le numéro de commune sur quatre (complété d'un zéro), puis
    une clé. Vérifié sur trois communes de trois départements :

        30140 → 213001407      81037 → 218100378      26289 → 212602890

    On le calcule et on le cherche en priorité, parce que le répertoire peut
    contenir DEUX « COMMUNE DE X » — c'est le cas d'au moins une commune
    rencontrée, dont un enregistrement récent côtoie l'historique. Prendre le
    premier résultat, c'était fausser ensuite tout le filtrage des marchés
    publics par SIREN acheteur, sans qu'aucun contrôle ne s'en aperçoive.

    La règle ne vaut pas pour la Corse ni l'outre-mer, dont les codes ne
    s'alignent pas ainsi : on y retombe sur le premier résultat, en le signalant.
    """
    attendu = ("21" + insee[:2] + "0" + insee[2:]
               if insee[:2].isdigit() and not insee.startswith(("97", "98"))
               else "")
    q = urllib.parse.urlencode({"q": f"commune de {nom}", "code_commune": insee})
    data = _get(f"{ENTREPRISES}?{q}") or {}
    candidats = [r for r in data.get("results", [])
                 if r.get("nom_complet", "").upper().startswith("COMMUNE")]

    for r in candidats:
        if attendu and r.get("siren", "").startswith(attendu):
            return r["siren"], (r.get("siege") or {}).get("siret", "")
    if len(candidats) > 1:
        print(f"  ⚠ {len(candidats)} entités « COMMUNE DE … » au répertoire, "
              "aucune au format attendu : SIREN à vérifier à la main")
    for r in candidats:
        return r.get("siren", ""), (r.get("siege") or {}).get("siret", "")
    return "", ""


def _candidats_site(nom: str) -> list[str]:
    """Adresses plausibles pour le site d'une mairie, testées une à une."""
    base = (nom.lower().replace("'", "").replace("’", "")
            .replace(" ", "-").replace("--", "-"))
    formes = [f"https://www.{base}.fr", f"https://{base}.fr",
              f"https://www.mairie-{base}.fr", f"https://www.ville-{base}.fr",
              f"https://{base}.com"]
    return [u for u in formes if _repond(u)]


def construire(insee: str) -> dict:
    print(f"[init] commune {insee}")
    commune = _get(f"{GEO}/communes/{insee}?fields=nom,code,codesPostaux,"
                   f"population,centre,contour,epci,anciensCodes")
    if not commune:
        raise SystemExit(f"Code INSEE inconnu : {insee}")

    nom = commune["nom"]
    cp = commune["codesPostaux"][0]
    dept = insee[:3] if insee.startswith(("97", "98")) else insee[:2]
    epci = commune.get("epci") or {}
    print(f"  {nom} ({cp}), département {dept}, "
          f"{commune.get('population', '?')} habitants")

    membres = {}
    if epci.get("code"):
        print(f"  EPCI : {epci['nom']} ({epci['code']})")
        for c in _get(f"{GEO}/epcis/{epci['code']}/communes"
                      f"?fields=nom,code,codesPostaux,population") or []:
            membres[c["code"]] = {
                "nom": c["nom"],
                "cp": (c.get("codesPostaux") or [""])[0],
                "population": c.get("population"),
            }
        print(f"  {len(membres)} communes membres")
    else:
        membres[insee] = {"nom": nom, "cp": cp,
                          "population": commune.get("population")}
        print("  commune isolée : aucun EPCI déclaré")

    siren, siret = _sirens(insee, nom)
    # Le « code » d'un EPCI chez geo.api.gouv.fr EST son SIREN : inutile
    # d'interroger le répertoire des entreprises pour le retrouver, et risqué
    # (deux intercommunalités peuvent porter des noms proches).
    epci_siren = epci.get("code", "")

    sites = _candidats_site(nom)
    print(f"  site de la mairie : {sites[0] if sites else 'à renseigner'}"
          + (f"  (autres candidats : {', '.join(sites[1:])})" if len(sites) > 1 else ""))

    # Les fusions concernent le PÉRIMÈTRE, pas seulement la commune-siège :
    # sur le territoire de portage, la commune nouvelle était une commune
    # membre. Ne regarder que la commune de collecte, c'était manquer les trois
    # anciennes communes que SIRENE et BODACC indexent encore.
    deleguees = {}
    for code_membre in membres:
        detail = (_get(f"{GEO}/communes/{code_membre}?fields=nom,anciensCodes")
                  or {})
        for ancien in detail.get("anciensCodes") or []:
            deleguees[ancien] = {
                "nom": "", "cp": membres[code_membre]["cp"], "population": 0,
                "commune": code_membre,
                "_a_confirmer": f"ancienne commune fusionnée dans "
                                f"{detail.get('nom', code_membre)}",
            }
    if deleguees:
        print(f"  {len(deleguees)} commune(s) déléguée(s) détectée(s) — "
              "nom à confirmer, cf. _a_faire")

    centre = commune.get("centre", {}).get("coordinates", [None, None])

    return {
        "_doc": ("Périmètre de l'instance. Écrit par scripts/init_instance.py, "
                 "relu par un humain. C'est le SEUL endroit du dispositif où "
                 "une donnée de commune a le droit d'exister."),
        "_source": "geo.api.gouv.fr + recherche-entreprises.api.gouv.fr",
        "commune_insee": insee,
        "commune_nom": nom,
        "code_postal": cp,
        "departement": dept,
        "commune_siren": siren,
        "commune_siret": siret,
        "communes": membres,
        "communes_deleguees": deleguees,
        "epci_nom": epci.get("nom", ""),
        "epci_siren": epci_siren,
        "commune_url": sites[0] if sites else "",
        "epci_url": "",
        "connecteur": "wordpress_rest",
        "pages": {},
        "prefecture_nom": f"Préfecture ({dept})",
        "prefecture_url": f"https://www.{_nom_departement(dept)}.gouv.fr"
                          if _nom_departement(dept) else "",
        "prefecture_raa_path": "",
        "centroid": [centre[1], centre[0]] if centre[0] else [],
        "bbox": _bbox(commune["contour"]) if commune.get("contour") else [],
        # Dépôt d'où vient ce code. Cité par la page « répliquer » du site :
        # une instance qui a forké doit renvoyer vers SON dépôt, pas vers celui
        # dont elle est partie. Vide, la page invite à écrire plutôt que de
        # pointer une adresse fausse.
        "depot_url": "",
        "_a_faire": [
            "vérifier commune_url et renseigner epci_url",
            "choisir le connecteur (cf. collectors/connecteurs/) et ses pages",
            "renseigner prefecture_raa_path (chemin des recueils des actes)",
            "confirmer le nom des communes déléguées, s'il y en a",
            "renseigner depot_url si le code est publié quelque part",
        ],
    }


def _nom_departement(dept: str) -> str:
    """Le sous-domaine préfectoral suit le nom du département, pas son code.
    On ne le devine pas : il est simplement laissé vide s'il est inconnu."""
    return ""


def adapter_regles(inst: dict, dry_run: bool) -> None:
    """Reporte l'identité et la bbox dans les règles de publication.

    Sans cette étape, le filtre de localisation garde la boîte englobante de la
    commune précédente : toutes les entités tombent « hors bbox » et perdent
    leurs coordonnées, sans erreur ni avertissement.
    """
    if not REGLES.exists():
        # Le moteur ne livre que l'exemple : les règles d'une commune ne sont
        # pas versionnées. Une instance neuve part donc de l'exemple, qu'on
        # adapte ensuite comme n'importe quelles règles existantes. Sans ça,
        # l'amorçage laissait l'instance sans filtre de publication.
        if not REGLES_EXEMPLE.exists():
            print("  [regles] ni publication_rules.json ni son exemple — étape ignorée")
            return
        REGLES.write_text(REGLES_EXEMPLE.read_text(encoding="utf-8"),
                          encoding="utf-8")
        print(f"  [regles] créées depuis {REGLES_EXEMPLE.name}")
    r = json.loads(REGLES.read_text(encoding="utf-8"))
    r["project"] = {
        "public_name": f"Vigie Civique {inst['commune_nom']}",
        "private_name": f"Atelier Vigie Civique {inst['commune_nom']}",
        "commune": inst["commune_nom"],
        "insee": inst["commune_insee"],
        "postal_code": inst["code_postal"],
    }
    if inst.get("bbox"):
        sud, ouest, nord, est = inst["bbox"]
        r.setdefault("locations", {})["bbox"] = {
            "lat_min": sud, "lat_max": nord, "lng_min": ouest, "lng_max": est}
    if inst.get("centroid"):
        lat, lng = inst["centroid"]
        # Boîte de repli du géocodeur : une entité posée exactement au centre
        # n'est pas localisée, elle est rattachée à la commune faute de mieux.
        r["locations"]["center_fallback_box"] = {
            "lat_min": round(lat - 0.001, 4), "lat_max": round(lat + 0.001, 4),
            "lng_min": round(lng - 0.001, 4), "lng_max": round(lng + 0.001, 4)}
    r.setdefault("outputs", {})["attribution"] = f"Vigie Civique {inst['commune_nom']}"
    sources = [s for s in r.get("events", {}).get("public_sources", [])
               if not s.endswith(".fr") or s in ("data.gouv.fr",)]
    for url in (inst.get("commune_url"), inst.get("epci_url")):
        if url:
            sources.append(urllib.parse.urlparse(url).netloc.removeprefix("www."))
    r.setdefault("events", {})["public_sources"] = sorted(set(sources))
    if not dry_run:
        REGLES.write_text(json.dumps(r, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    print(f"  [regles] identité, bbox et sources publiables mises à jour"
          + (" (dry-run)" if dry_run else ""))


def main() -> int:
    ap = argparse.ArgumentParser(description="Amorce une instance depuis un code INSEE")
    ap.add_argument("insee", help="code INSEE de la commune (ex. 81037)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="écrase une instance déjà configurée")
    ap.add_argument("--regles", action="store_true",
                    help="ne remet à jour que publication_rules.json, depuis "
                         "l'instance existante — à lancer après avoir complété "
                         "les adresses des sites officiels")
    args = ap.parse_args()

    if args.regles:
        if not INSTANCE.exists():
            print(f"✖ {INSTANCE.relative_to(ROOT)} absent.", file=sys.stderr)
            return 1
        adapter_regles(json.loads(INSTANCE.read_text(encoding="utf-8")),
                       args.dry_run)
        return 0

    if INSTANCE.exists() and not args.force and not args.dry_run:
        print(f"✖ {INSTANCE.relative_to(ROOT)} existe déjà. "
              "Relancer avec --force pour l'écraser.", file=sys.stderr)
        return 1

    inst = construire(args.insee)
    adapter_regles(inst, args.dry_run)

    if args.dry_run:
        print("\n" + json.dumps(inst, ensure_ascii=False, indent=2))
        print("\n(dry-run — rien écrit)")
        return 0

    INSTANCE.parent.mkdir(parents=True, exist_ok=True)
    INSTANCE.write_text(json.dumps(inst, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(f"\n✓ {INSTANCE.relative_to(ROOT)} écrit")

    # Les libellés des deux applications SvelteKit sont générés depuis
    # l'instance et ne sont pas versionnés. Sans eux, `npm run build` échoue sur
    # un ENOENT illisible : le module manque, mais rien ne dit qu'il se génère.
    # Les écrire ici évite d'avoir à le savoir.
    # Importé sous alias : `construire` est aussi le nom d'une fonction de ce
    # module, appelée plus haut dans main(). Un import local du même nom la rend
    # locale pour TOUTE la fonction, y compris avant l'import — l'appel de la
    # ligne 316 levait alors un UnboundLocalError.
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from generer_libelles import (construire as _libelles,
                                      ecrire as _ecrire_libelles, CIBLES)
        _ecrire_libelles(_libelles())
        for cible in CIBLES:
            print(f"✓ {cible.relative_to(ROOT)} généré")
    except Exception as exc:
        print(f"  [libellés] non générés : {exc}\n"
              "  Lancer :  python3 scripts/generer_libelles.py")

    print("\nÀ faire à la main avant la première collecte :")
    for tache in inst["_a_faire"]:
        print(f"  - {tache}")
    print("\nPuis :  python3 -m collectors.run_all")
    print("        (le dernier step, `perimetre`, conditionne la publication)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
