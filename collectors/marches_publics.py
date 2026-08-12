"""
marches_publics.py — Marchés publics Lasalle + CC Causses Aigoual Cévennes Terres Solidaires

Sources :
  1. DECP (Données Essentielles de la Commande Publique) — data.gouv.fr
     Fichiers JSON mensuels, filtrés par SIRET acheteur.
     Seuil de publication : ≥ 40 000 € (services/fournitures), ≥ 90 000 € (travaux).
     Note : une commune de 1166 hab. publie peu dans le DECP — source principale pour CC CAC.
  2. Site CC CAC — caussesaigoualcevennes.fr/marches-publics/
     PDFs d'avis d'appel public à la concurrence (AAPC) publiés sur le site.

Usage :
  python3 -m collectors.marches_publics --dry-run
  python3 -m collectors.marches_publics
  python3 -m collectors.marches_publics --source decp      # DECP uniquement
  python3 -m collectors.marches_publics --source cac       # site CC CAC uniquement
  python3 -m collectors.marches_publics --years 2022-2025  # plage d'années DECP
"""

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from .config import (
    COMMUNE_INSEE, COMMUNE_NAME, EPCI_SIREN, HEADERS, REQUEST_DELAY
)
from .db import transaction, upsert_entity
from .archive import archive_fetch

# ── Constantes ────────────────────────────────────────────────────────────────

# SIRET Lasalle confirmé via recherche-entreprises.api.gouv.fr
COMMUNE_SIRET  = "21300140700013"
COMMUNE_SIREN  = "213001407"

# CC CAC — SIREN depuis config
CAC_SIREN      = EPCI_SIREN          # "200034601"
CAC_SITE_URL   = "https://caussesaigoualcevennes.fr"
CAC_MARCHES    = CAC_SITE_URL + "/marches-publics/"

# DECP — dataset consolidé officiel data.gouv.fr
DATAGOUV_API   = "https://www.data.gouv.fr/api/1/datasets/"
DECP_DATASET   = "donnees-essentielles-de-la-commande-publique-fichiers-consolides"
DECP_SLUG_AWS  = "donnees-essentielles-de-la-commande-publique-decp-de-marches-publics-info-awsolutions"

# Codes CPV fréquents pour communes rurales (pour information dans metadata)
CPV_LABELS = {
    "45": "Travaux de construction",
    "50": "Services de réparation et entretien",
    "55": "Services d'hôtellerie et restauration",
    "60": "Transport",
    "71": "Services d'architecture et ingénierie",
    "72": "Services informatiques",
    "79": "Services aux entreprises",
    "90": "Services d'assainissement/collecte déchets",
}


# ── HTTP helpers ──────────────────────────────────────────────────────────────

# Échecs réseau accumulés pendant le run. Relevés en fin de main() : un run
# partiel doit finir en status='error' côté collect_loop, pas en 'empty' —
# même leçon que bodacc (17 annonces perdues en silence, 10/08/2026).
_echecs_reseau: list[str] = []


def _relever_echecs_reseau() -> None:
    if _echecs_reseau:
        raise RuntimeError(
            f"{len(_echecs_reseau)} échec(s) réseau pendant la collecte — "
            f"dernier : {_echecs_reseau[-1]}"
        )


def fetch_json(url: str, timeout: int = 30) -> dict | list | None:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception as e:
        print(f"  [erreur JSON] {url[:60]} → {e}")
        _echecs_reseau.append(f"{url[:80]} → {e}")
        return None


def fetch_html(url: str, timeout: int = 15) -> str | None:
    req = urllib.request.Request(url, headers={
        **HEADERS,
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 Chrome/122.0 Safari/537.36"
        )
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            from urllib.parse import urlparse
            archive_fetch(f"web:{urlparse(url).netloc}", url, raw,
                          r.headers.get_content_type(), r.status)
            return raw.decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  [erreur HTML] {url[:60]} → {e}")
        _echecs_reseau.append(f"{url[:80]} → {e}")
        return None


# ── Source 1 : DECP data.gouv.fr ─────────────────────────────────────────────

def discover_decp_resources() -> list[dict]:
    """Récupère la liste des ressources DECP consolidées depuis data.gouv.fr."""
    data = fetch_json(DATAGOUV_API + DECP_DATASET + "/")
    if not data:
        print("  ⚠ Dataset DECP consolidé introuvable")
        return []
    resources = []
    for r in data.get("resources", []):
        title = r.get("title", "")
        url   = r.get("url", "")
        # Garder les fichiers mensuels (decp-YYYY-MM.json) et annuels (decp-YYYY.json)
        # Exclure decp-global.json (trop volumineux)
        if (url.endswith(".json")
                and re.search(r"decp-\d{4}", title)
                and "global" not in title.lower()):
            resources.append({"title": title, "url": url})
    seen = set()
    unique = []
    for r in resources:
        if r["url"] not in seen:
            seen.add(r["url"])
            unique.append(r)
    print(f"  {len(unique)} fichiers DECP consolidés découverts")
    return unique


def year_from_title(title: str) -> int | None:
    m = re.search(r"(\d{4})", title)
    return int(m.group(1)) if m else None


def extract_marches_from_file(url: str) -> list[dict]:
    """Télécharge et filtre un fichier DECP consolidé JSON pour Lasalle + CC CAC."""
    import io as _io
    import gzip as _gzip
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
    except Exception as e:
        print(f"  [erreur téléchargement] {url[:60]} → {e}")
        _echecs_reseau.append(f"{url[:80]} → {e}")
        return []

    try:
        data = json.loads(_gzip.decompress(raw))
    except Exception:
        try:
            data = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception as e:
            print(f"  [erreur parsing JSON] {e}")
            return []

    # Format DECP consolidé officiel : {"marches": [{...}]}
    if isinstance(data, dict):
        items = data.get("marches", [])
        if isinstance(items, dict):
            items = items.get("marche", [])
    elif isinstance(data, list):
        items = data
    else:
        return []

    found = []
    for m in items:
        if not isinstance(m, dict):
            continue
        acheteur = m.get("acheteur") or {}
        if not isinstance(acheteur, dict):
            continue
        acheteur_id  = str(acheteur.get("id", ""))
        acheteur_nom = str(acheteur.get("nom", "")).lower()

        is_lasalle = acheteur_id.startswith(COMMUNE_SIREN)
        is_cac     = acheteur_id.startswith(CAC_SIREN)
        is_name    = ("lasalle" in acheteur_nom
                      or "causses aigoual" in acheteur_nom
                      or "causses-aigoual" in acheteur_nom)

        if is_lasalle or is_cac or is_name:
            found.append(m)

    return found


def normalize_decp_marche(m: dict) -> dict:
    """Normalise un marché DECP vers notre format interne."""
    acheteur = m.get("acheteur", {})
    titulaires = m.get("titulaires", [])
    cpv = str(m.get("codeCPV", ""))[:2]

    return {
        "source":         "DECP data.gouv.fr",
        "source_type":    "decp",
        "acheteur_id":    str(acheteur.get("id", "")),
        "acheteur_nom":   str(acheteur.get("nom", "")),
        "objet":          str(m.get("objet", "")),
        "nature":         str(m.get("nature", "Marché")),
        "procedure":      str(m.get("procedure", "")),
        "montant":        m.get("montant"),
        "devise":         m.get("devise", "EUR"),
        "date_notif":     str(m.get("dateNotification", "")),
        "date_pub":       str(m.get("datePublicationDonnees", "")),
        "duree_mois":     m.get("dureeMois"),
        "cpv":            str(m.get("codeCPV", "")),
        "cpv_label":      CPV_LABELS.get(cpv, ""),
        "lieu_exec":      str(m.get("lieuExecution", {}).get("nom", "")),
        "titulaires":     [
            {
                "siren": str(t.get("id", ""))[:9],
                "siret": str(t.get("id", "")),
                "nom":   str(t.get("denominationSociale", "")),
                "type":  str(t.get("typeIdentifiant", "")),
            }
            for t in titulaires
        ],
        "raw_id":         str(m.get("id", "")),
    }


def fetch_decp_marches(years: list[int] | None = None) -> list[dict]:
    """Interroge le DECP et retourne tous les marchés Lasalle/CC CAC trouvés."""
    print("\n[DECP] Découverte des fichiers…")
    resources = discover_decp_resources()

    if years:
        resources = [r for r in resources if year_from_title(r["title"]) in years]
        print(f"  Filtré à {len(resources)} fichiers pour années {years}")

    all_marches = []
    for i, res in enumerate(resources):
        title = res["title"]
        year  = year_from_title(title) or "?"
        print(f"  [{i+1}/{len(resources)}] {title}…", end=" ", flush=True)
        marches = extract_marches_from_file(res["url"])
        print(f"{len(marches)} trouvé(s)")
        all_marches.extend([normalize_decp_marche(m) for m in marches])
        time.sleep(REQUEST_DELAY)

    # Dédoublonner par raw_id
    seen_ids = set()
    unique = []
    for m in all_marches:
        if m["raw_id"] not in seen_ids:
            seen_ids.add(m["raw_id"])
            unique.append(m)

    print(f"  [DECP] {len(unique)} marchés uniques Lasalle/CC CAC")
    return unique


# ── Source 1b : DECP augmenté (Opendatasoft data.economie.gouv.fr) ────────────
# Requête ciblée et directe par SIREN acheteur (pas de téléchargement de fichiers
# consolidés). Plus fiable pour les marchés récents. Champs déjà aplatis +
# titulaire résolu (dénomination + SIRET). Complète fetch_decp_marches().

DECP_ECO_API = ("https://data.economie.gouv.fr/api/explore/v2.1/"
                "catalog/datasets/decp_augmente/records")

# DECP v3 — jeu vivant, mis à jour quotidiennement. `decp_augmente` est figé
# depuis le 05/03/2026 : conservé en repli pour l'historique, mais il ne verra
# plus jamais un marché récent. Vérifié le 26/07/2026 :
#   decp-v3-marches-valides  702 901 enreg., maj du jour
#   decp_augmente            994 123 enreg., maj 2026-03-05
DECP_V3_API = ("https://data.economie.gouv.fr/api/explore/v2.1/"
               "catalog/datasets/decp-v3-marches-valides/records")


def normalize_decp_v3(rec: dict) -> dict:
    """Normalise un record decp-v3-marches-valides vers notre format interne.

    Le schéma v3 diffère de `decp_augmente` : `acheteur_id` au lieu de
    `idacheteur`, `objet` au lieu de `objetmarche`, titulaires numérotés
    `titulaire_id_N` / `titulaire_denominationsociale_N`.
    """
    titulaires = []
    for i in (1, 2, 3):
        tid = str(rec.get(f"titulaire_id_{i}") or "").strip()
        nom = str(rec.get(f"titulaire_denominationsociale_{i}") or "").strip()
        if not tid and not nom:
            continue
        titulaires.append({
            "siren": tid[:9], "siret": tid, "nom": nom,
            "type": str(rec.get(f"titulaire_typeidentifiant_{i}") or "SIRET"),
        })
    division = str(rec.get("codecpv") or "")[:2]
    return {
        "source":       "DECP v3 data.economie.gouv.fr",
        "source_type":  "decp",
        "acheteur_id":  str(rec.get("acheteur_id") or ""),
        "acheteur_nom": str(rec.get("acheteur_nom") or ""),
        "objet":        str(rec.get("objet") or ""),
        "nature":       str(rec.get("nature") or "Marché"),
        "procedure":    str(rec.get("procedure") or ""),
        "montant":      rec.get("montant"),
        "date_notif":   str(rec.get("datenotification") or ""),
        "date_pub":     str(rec.get("datepublicationdonnees") or ""),
        "duree_mois":   rec.get("dureemois"),
        "cpv":          str(rec.get("codecpv") or ""),
        "cpv_label":    CPV_LABELS.get(division, ""),
        "lieu_exec":    str(rec.get("lieuexecution_nom") or ""),
        "titulaires":   titulaires,
        "raw_id":       str(rec.get("id") or ""),
    }


def fetch_decp_v3_marches() -> list[dict]:
    """DECP v3 : marchés dont l'ACHETEUR est Lasalle ou la CC CAC, plus ceux
    dont le LIEU D'EXÉCUTION tombe dans le périmètre — un marché du Département ou
    de la Région exécuté sur la commune intéresse autant le lecteur.

    Attention au lieu d'exécution : `lieuexecution_code` vaut tantôt un code
    INSEE, tantôt un code postal, et 30140 est le code postal d'ANDUZE autant
    que le code INSEE de Lasalle. D'où le filtre conjoint sur
    `lieuexecution_typecode`, sans lequel on ramène les marchés du bassin
    d'Anduze (rénovation du gymnase, etc.).
    """
    import urllib.parse
    from .config import COMMUNES, COMMUNES_CP

    insee = ", ".join(f'"{c}"' for c in COMMUNES)
    cp = ", ".join(f'"{c}"' for c in COMMUNES_CP if c == "30460")

    clauses = [f'startswith(acheteur_id, "{COMMUNE_SIREN}")',
               f'startswith(acheteur_id, "{CAC_SIREN}")',
               f'(lieuexecution_typecode = "Code commune" and lieuexecution_code in ({insee}))']
    if cp:
        clauses.append(f'(lieuexecution_typecode = "Code postal" and lieuexecution_code in ({cp}))')

    print("\n[DECP-v3] Requête par acheteur et par lieu d'exécution…")
    results, seen = [], set()
    for clause in clauses:
        offset = 0
        while True:
            params = urllib.parse.urlencode({
                "where": clause, "limit": 100, "offset": offset,
                "order_by": "datenotification DESC",
            })
            data = fetch_json(f"{DECP_V3_API}?{params}", timeout=30)
            if not data:
                break
            hits = data.get("results", [])
            for rec in hits:
                rid = str(rec.get("id") or "")
                if rid and rid in seen:
                    continue
                seen.add(rid)
                results.append(normalize_decp_v3(rec))
            offset += len(hits)
            if not hits or offset >= data.get("total_count", 0) or offset >= 500:
                break
            time.sleep(REQUEST_DELAY)
    print(f"  [DECP-v3] {len(results)} marchés uniques")
    return results


def _decp_eco_titulaires(rec: dict) -> list[dict]:
    """Construit la liste des titulaires (principal + co-titulaires) d'un record."""
    titulaires = []
    nom = (rec.get("denominationsocialeetablissement")
           or rec.get("denominationunitelegale") or "").strip()
    siret = str(rec.get("siretetablissement") or "").strip()
    if nom:
        titulaires.append({
            "siren": siret[:9], "siret": siret, "nom": nom,
            "type": str(rec.get("typeidentifiantetablissement") or "SIRET"),
        })
    for i in (1, 2, 3):
        co_nom = (rec.get(f"denominationsociale_cotitulaire{i}") or "").strip()
        if co_nom:
            co_id = str(rec.get(f"id_cotitulaire{i}") or "").strip()
            titulaires.append({
                "siren": co_id[:9], "siret": co_id, "nom": co_nom,
                "type": str(rec.get(f"typeidentifiant_cotitulaire{i}") or ""),
            })
    return titulaires


def normalize_decp_eco(rec: dict) -> dict:
    """Normalise un record decp_augmente vers notre format interne."""
    division = str(rec.get("codecpv_division") or "")[:2]
    cpv_label = (rec.get("referencecpv") or CPV_LABELS.get(division, "") or "")
    return {
        "source":      "DECP data.economie.gouv.fr",
        "source_type": "decp",
        "acheteur_id": str(rec.get("idacheteur") or ""),
        "acheteur_nom": str(rec.get("nomacheteur") or ""),
        "objet":       str(rec.get("objetmarche") or ""),
        "nature":      str(rec.get("nature") or rec.get("natureobjetmarche") or "Marché"),
        "procedure":   str(rec.get("procedure") or ""),
        "montant":     rec.get("montant"),
        "date_notif":  str(rec.get("datenotification") or ""),
        "date_pub":    str(rec.get("datepublicationdonnees") or ""),
        "duree_mois":  rec.get("dureemois"),
        "cpv":         str(rec.get("codecpv") or ""),
        "cpv_label":   cpv_label,
        "lieu_exec":   str(rec.get("lieuexecutionnom") or ""),
        "titulaires":  _decp_eco_titulaires(rec),
        "raw_id":      str(rec.get("id") or ""),
    }


def fetch_decp_eco_marches() -> list[dict]:
    """Interroge le DECP augmenté Opendatasoft par SIREN acheteur (Lasalle + CC CAC)."""
    import urllib.parse
    print("\n[DECP-eco] Requête directe par SIREN acheteur…")
    results, seen = [], set()
    for label, siren in ((COMMUNE_NAME, COMMUNE_SIREN), ("CC CAC", CAC_SIREN)):
        offset = 0
        while True:
            params = urllib.parse.urlencode({
                # ODSQL : le wildcard '%' ne fonctionne pas sur idacheteur ;
                # startswith() matche le SIREN (préfixe du SIRET acheteur).
                "where": f'startswith(idacheteur, "{siren}")',
                "limit": 100, "offset": offset,
                "order_by": "datenotification DESC",
            })
            data = fetch_json(f"{DECP_ECO_API}?{params}", timeout=30)
            if not data:
                break
            hits = data.get("results", [])
            for rec in hits:
                rid = str(rec.get("id") or "")
                if rid and rid in seen:
                    continue
                seen.add(rid)
                results.append(normalize_decp_eco(rec))
            total = data.get("total_count", 0)
            offset += len(hits)
            if not hits or offset >= total or offset >= 500:
                break
            time.sleep(REQUEST_DELAY)
        print(f"  [DECP-eco] {label} ({siren}) : {offset} record(s) parcouru(s)")
    print(f"  [DECP-eco] {len(results)} marchés uniques")
    return results


# ── Source 2 : BOAMP ─────────────────────────────────────────────────────────

BOAMP_API = "https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp/records"

def fetch_boamp_marches() -> list[dict]:
    """
    Interroge l'API BOAMP OpenDataSoft (sans clé) pour Lasalle et CC CAC.
    Couvre les avis d'appel public à la concurrence (AAPC) et attributions.
    """
    import urllib.parse
    print("\n[BOAMP] Recherche marchés Lasalle + CC CAC…")
    results = []
    seen_ids = set()

    queries = [
        'nomacheteur like "%lasalle%" and code_departement="30"',
        'nomacheteur like "%causses aigoual%" or nomacheteur like "%causses-aigoual%"',
    ]

    for where in queries:
        offset = 0
        while True:
            params = urllib.parse.urlencode({
                "where": where,
                "limit": 50,
                "offset": offset,
                "order_by": "dateparution DESC",
            })
            data = fetch_json(f"{BOAMP_API}?{params}", timeout=30)
            if not data:
                break
            hits = data.get("results", [])
            if not hits:
                break
            for hit in hits:
                uid = hit.get("idweb") or hit.get("id") or str(offset)
                if uid in seen_ids:
                    continue
                seen_ids.add(uid)
                objet = (hit.get("objet") or "").strip()
                if not objet:
                    continue
                date_pub = (hit.get("dateparution") or "")[:10]
                acheteur = hit.get("nomacheteur") or ""
                # Déterminer acheteur_id depuis nomacheteur
                acheteur_lower = acheteur.lower()
                if "lasalle" in acheteur_lower:
                    acheteur_id_str = COMMUNE_SIREN
                elif "causses" in acheteur_lower:
                    acheteur_id_str = CAC_SIREN
                else:
                    acheteur_id_str = ""
                # Titulaire (peut être str ou list)
                titulaire_raw = hit.get("titulaire") or ""
                if isinstance(titulaire_raw, list):
                    titulaires = [{"nom": str(t), "siren": "", "siret": "", "type": ""} for t in titulaire_raw if t]
                elif titulaire_raw:
                    titulaires = [{"nom": str(titulaire_raw), "siren": "", "siret": "", "type": ""}]
                else:
                    titulaires = []
                results.append({
                    "source":      "BOAMP",
                    "source_type": "boamp",
                    "acheteur_id": acheteur_id_str,
                    "acheteur_nom": acheteur,
                    "objet":       objet,
                    "nature":      hit.get("nature_libelle") or hit.get("nature") or "Marché",
                    "procedure":   hit.get("procedure_libelle") or hit.get("type_procedure") or "",
                    "montant":     None,
                    "date_pub":    date_pub,
                    "date_notif":  "",
                    "pdf_url":     hit.get("url_avis") or f"https://www.boamp.fr/avis/detail/{uid}",
                    "titulaires":  titulaires,
                    "raw_id":      f"boamp_{uid}",
                    "cpv":         hit.get("descripteur_code") or "",
                    "cpv_label":   hit.get("descripteur_libelle") or "",
                    "lieu_exec":   "",
                })
            total = data.get("total_count", 0)
            offset += len(hits)
            if offset >= total or offset >= 200:
                break
            time.sleep(REQUEST_DELAY)

    print(f"  [BOAMP] {len(results)} avis trouvés")
    return results


# ── Source 3 : Site CC CAC ─────────────────────────────────────────────────────

def scrape_cac_marches() -> list[dict]:
    """Scrape les avis de marchés publics publiés sur caussesaigoualcevennes.fr."""
    print(f"\n[CC CAC] Scraping {CAC_MARCHES}…")
    html = fetch_html(CAC_MARCHES)
    if not html:
        return []

    # Extraire les PDFs (AAPC = Avis d'Appel Public à la Concurrence)
    pdf_links = re.findall(
        r'href=["\'](' + re.escape(CAC_SITE_URL) + r'/wp-content/uploads/[^"\']+\.pdf)["\']',
        html, re.I
    )

    # Extraire les textes de marchés depuis le HTML
    marches = []
    seen_urls = set()

    # Chercher les blocs d'articles/posts WordPress
    # Pattern : titre de l'article + date + lien PDF
    blocks = re.split(r'<article|<div[^>]+class=["\'][^"\']*post[^"\']*["\']', html)

    for block in blocks[1:]:
        # Titre
        title_m = re.search(
            r'<h[1-4][^>]*>(.*?)</h[1-4]>', block, re.S | re.I
        )
        title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip() if title_m else ""

        # Date
        date_m = re.search(
            r'datetime=["\'](\d{4}-\d{2}-\d{2})', block
        ) or re.search(
            r'(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})', block
        )
        date_str = ""
        if date_m:
            if date_m.lastindex == 1:
                date_str = date_m.group(1)
            elif date_m.lastindex == 3:
                d, mo, y = date_m.group(1), date_m.group(2), date_m.group(3)
                date_str = f"{y}-{int(mo):02d}-{int(d):02d}"

        # PDFs dans ce bloc
        block_pdfs = re.findall(
            r'href=["\'](' + re.escape(CAC_SITE_URL) + r'/wp-content/[^"\']+\.pdf)["\']',
            block, re.I
        )

        if title and len(title) > 5:
            url = block_pdfs[0] if block_pdfs else ""
            if url in seen_urls:
                continue
            if url:
                seen_urls.add(url)

            marches.append({
                "source":      "caussesaigoualcevennes.fr",
                "source_type": "cac_site",
                "acheteur_id": CAC_SIREN,
                "acheteur_nom": "CC Causses Aigoual Cévennes Terres Solidaires",
                "objet":       title,
                "nature":      "Marché",
                "procedure":   "Appel d'offres",
                "montant":     None,
                "date_pub":    date_str,
                "date_notif":  "",
                "pdf_url":     url,
                "titulaires":  [],
                "raw_id":      url or title[:50],
            })

    # Ajouter les PDFs non capturés dans les blocs
    # Exclure les PDFs purement informatifs (pas des avis de marché)
    _INFO_SLUGS = ("marches-publics.info", "dematerialisation", "guide", "notice")
    for pdf_url in pdf_links:
        if pdf_url in seen_urls:
            continue
        fname_lower = Path(pdf_url).stem.lower()
        if any(x in fname_lower for x in _INFO_SLUGS):
            continue
        seen_urls.add(pdf_url)
        # Extraire infos du nom de fichier
        fname = Path(pdf_url).stem.lower()
        year_m = re.search(r"20\d{2}", pdf_url)
        # Extraire date DD.MM.YYYY depuis le nom de fichier si possible
        date_m2 = re.search(r"(\d{1,2})[.\-](\d{1,2})[.\-](20\d{2})", fname)
        if date_m2:
            date_str = f"{date_m2.group(3)}-{int(date_m2.group(2)):02d}-{int(date_m2.group(1)):02d}"
        else:
            # Extraire depuis le chemin (année/mois)
            path_m = re.search(r"/uploads/(\d{4})/(\d{2})/", pdf_url)
            date_str = (f"{path_m.group(1)}-{path_m.group(2)}-01"
                        if path_m else (year_m.group(0) + "-01-01" if year_m else ""))
        # Titre plus lisible depuis le nom de fichier
        title = re.sub(r"[-_]", " ", Path(pdf_url).stem).title().strip()
        marches.append({
                "source":      "caussesaigoualcevennes.fr",
                "source_type": "cac_site",
                "acheteur_id": CAC_SIREN,
                "acheteur_nom": "CC Causses Aigoual Cévennes Terres Solidaires",
                "objet":       title,
                "nature":      "Marché",
                "procedure":   "Appel d'offres",
                "montant":     None,
                "date_pub":    date_str,
                "date_notif":  "",
                "pdf_url":     pdf_url,
                "titulaires":  [],
                "raw_id":      pdf_url,
            })

    print(f"  [CC CAC] {len(marches)} avis trouvés")
    return marches


# ── Insertion DB ──────────────────────────────────────────────────────────────

def _get_commune_entity_id(conn) -> int:
    """Retourne l'ID de la commune de Lasalle (acheteur)."""
    row = conn.execute(
        "SELECT id FROM entities WHERE type='service' AND name='Commune de Lasalle' LIMIT 1"
    ).fetchone()
    if row:
        return row["id"]
    return upsert_entity(
        conn, type="service", name=f"Commune de {COMMUNE_NAME}",
        short_name=COMMUNE_NAME, commune=COMMUNE_NAME, confidence="verified"
    )


def _get_cac_entity_id(conn) -> int:
    """Retourne l'ID de la CC CAC (acheteur)."""
    row = conn.execute(
        "SELECT id FROM entities WHERE name LIKE '%Causses Aigoual%' OR name LIKE '%CC CAC%' LIMIT 1"
    ).fetchone()
    if row:
        return row["id"]
    return upsert_entity(
        conn, type="service",
        name="CC Causses Aigoual Cévennes Terres Solidaires",
        short_name="CC CAC",
        confidence="verified"
    )


def _upsert_titulaire(conn, t: dict) -> int | None:
    """Crée ou retrouve l'entité prestataire."""
    nom = t.get("nom", "").strip()
    if not nom:
        return None
    eid = upsert_entity(
        conn, type="business", name=nom,
        confidence="verified"
    )
    # Enrichir le SIREN si disponible
    siren = t.get("siren", "").strip()
    if siren and len(siren) == 9:
        conn.execute(
            "INSERT OR IGNORE INTO businesses (entity_id, siren) VALUES (?,?)",
            (eid, siren)
        )
        conn.execute(
            "UPDATE businesses SET siren=? WHERE entity_id=? AND siren IS NULL",
            (siren, eid)
        )
    return eid


def marche_exists(conn, raw_id: str) -> bool:
    row = conn.execute(
        "SELECT id FROM marches_publics WHERE raw_id=? LIMIT 1",
        (raw_id[:100],)
    ).fetchone()
    return row is not None


def _ensure_marches_table(conn):
    """Crée la table marches_publics si absente."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS marches_publics (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            acheteur_id     INTEGER REFERENCES entities(id),
            acheteur_siren  TEXT NOT NULL,
            acheteur_nom    TEXT NOT NULL,
            titulaire_id    INTEGER REFERENCES entities(id),
            titulaire_siren TEXT,
            titulaire_nom   TEXT,
            objet           TEXT NOT NULL,
            nature          TEXT,
            procedure       TEXT,
            montant         REAL,
            cpv             TEXT,
            cpv_label       TEXT,
            date_notif      TEXT,
            date_pub        TEXT,
            duree_mois      INTEGER,
            lieu_exec       TEXT,
            source          TEXT NOT NULL,
            source_url      TEXT,
            raw_id          TEXT,
            event_id        INTEGER REFERENCES events(id),
            created_at      TEXT DEFAULT (datetime('now')),
            UNIQUE(raw_id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mp_acheteur  ON marches_publics(acheteur_siren)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mp_titulaire ON marches_publics(titulaire_siren)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mp_date      ON marches_publics(date_notif DESC)")


def insert_marche(conn, m: dict,
                  commune_id: int, cac_id: int,
                  dry_run: bool = False) -> bool:
    """Insère un marché en DB : events + marches_publics + financial_flows."""
    objet  = m.get("objet", "").strip()
    if not objet:
        return False

    raw_id = m.get("raw_id", "")[:100]
    if marche_exists(conn, raw_id):
        return False

    if dry_run:
        print(f"  [dry-run] {m['acheteur_nom'][:30]} | {objet[:60]} | {m.get('montant','?')} €")
        return False

    acheteur_id_str = m.get("acheteur_id", "")
    if acheteur_id_str.startswith(COMMUNE_SIREN):
        acheteur_eid   = commune_id
        acheteur_label = COMMUNE_NAME
    else:
        acheteur_eid   = cac_id
        acheteur_label = "CC CAC"

    titulaires = m.get("titulaires", [])
    tit = titulaires[0] if titulaires else {}
    titulaire_nom   = tit.get("nom", "").strip() or None
    titulaire_siren = tit.get("siren", "").strip()[:9] or None

    # Retrouver ou créer le titulaire
    titulaire_eid = None
    if titulaires:
        for t in titulaires:
            titulaire_eid = _upsert_titulaire(conn, t)
            if titulaire_eid:
                break

    metadata = json.dumps({
        "raw_id":      raw_id,
        "procedure":   m.get("procedure", ""),
        "nature":      m.get("nature", ""),
        "cpv":         m.get("cpv", ""),
        "cpv_label":   m.get("cpv_label", ""),
        "lieu_exec":   m.get("lieu_exec", ""),
        "duree_mois":  m.get("duree_mois"),
        "acheteur_id": acheteur_id_str,
        "source_type": m.get("source_type", ""),
        "pdf_url":     m.get("pdf_url", ""),
        "titulaires":  titulaires,
    }, ensure_ascii=False)

    date       = m.get("date_notif") or m.get("date_pub") or None
    date_pub   = m.get("date_pub") or None
    source_url = m.get("pdf_url", "")
    montant_raw = m.get("montant")

    # Normaliser montant
    montant = None
    if montant_raw is not None:
        try:
            montant = float(str(montant_raw))
        except (ValueError, TypeError):
            pass

    # Normaliser cpv
    cpv_raw = m.get("cpv", "")
    cpv_str = (json.dumps(cpv_raw, ensure_ascii=False) if isinstance(cpv_raw, list)
               else str(cpv_raw) if cpv_raw else None)
    cpv_label = m.get("cpv_label", "")
    cpv_label_str = (json.dumps(cpv_label, ensure_ascii=False) if isinstance(cpv_label, list)
                     else str(cpv_label) if cpv_label else None)

    # ── Événement ────────────────────────────────────────────────────────────
    ev_id = conn.execute(
        "INSERT INTO events (type, date, title, source, source_url, metadata)"
        " VALUES ('marché_public', ?, ?, ?, ?, ?)",
        (date, objet, m["source"], source_url, metadata)
    ).lastrowid

    # Lier acheteur et titulaires aux événements
    conn.execute(
        "INSERT OR IGNORE INTO event_entities (event_id, entity_id, role) VALUES (?, ?, 'acheteur')",
        (ev_id, acheteur_eid)
    )
    if titulaire_eid:
        conn.execute(
            "INSERT OR IGNORE INTO event_entities (event_id, entity_id, role) VALUES (?, ?, 'prestataire')",
            (ev_id, titulaire_eid)
        )
        conn.execute(
            "INSERT OR IGNORE INTO relations"
            " (from_id, to_id, relation_type, since, source, confidence, metadata)"
            " VALUES (?, ?, 'prestataire', ?, ?, 'verified', ?)",
            (titulaire_eid, acheteur_eid, date, m["source"],
             json.dumps({"objet": objet[:80], "montant": montant}, ensure_ascii=False))
        )

    # ── Table dédiée marches_publics ─────────────────────────────────────────
    conn.execute("""
        INSERT OR IGNORE INTO marches_publics
          (acheteur_id, acheteur_siren, acheteur_nom,
           titulaire_id, titulaire_siren, titulaire_nom,
           objet, nature, procedure, montant,
           cpv, cpv_label, date_notif, date_pub, duree_mois,
           lieu_exec, source, source_url, raw_id, event_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        acheteur_eid, acheteur_id_str[:9] if acheteur_id_str else "", acheteur_label,
        titulaire_eid, titulaire_siren, titulaire_nom,
        objet, m.get("nature"), m.get("procedure"), montant,
        cpv_str, cpv_label_str, date, date_pub, m.get("duree_mois"),
        m.get("lieu_exec"), m["source"], source_url, raw_id, ev_id,
    ))

    # ── Flux financier ───────────────────────────────────────────────────────
    if montant:
        year_str = (date or "")[:4]
        year = int(year_str) if year_str.isdigit() else None
        conn.execute(
            "INSERT INTO financial_flows"
            " (type, year, amount, from_id, to_id, event_id, description, source, confidence)"
            " VALUES ('marché', ?, ?, ?, ?, ?, ?, ?, 'verified')",
            (year, int(montant), acheteur_eid, titulaire_eid, ev_id,
             f"{objet[:80]} ({acheteur_label})", m["source"])
        )

    return True


# ── Main ──────────────────────────────────────────────────────────────────────

def main(
    dry_run: bool = False,
    source: str = "all",
    years: list[int] | None = None,
) -> None:
    print(f"\n[marches_publics] dry_run={dry_run} source={source} years={years}")
    print(f"  Commune SIRET : {COMMUNE_SIRET}")
    print(f"  CC CAC SIREN  : {CAC_SIREN}")

    all_marches: list[dict] = []

    if source in ("all", "decp"):
        all_marches += fetch_decp_marches(years=years)

    if source in ("all", "decp", "decp-eco"):
        all_marches += fetch_decp_v3_marches()      # jeu vivant
        all_marches += fetch_decp_eco_marches()     # repli historique (figé 03/2026)

    if source in ("all", "boamp"):
        all_marches += fetch_boamp_marches()

    if source in ("all", "cac"):
        all_marches += scrape_cac_marches()

    print(f"\n  Total : {len(all_marches)} marchés à traiter")

    if dry_run:
        for m in all_marches:
            print(
                f"  [{m['source_type']}] {m['acheteur_nom'][:25]} | "
                f"{m.get('objet','')[:55]} | "
                f"{m.get('montant','?')} € | {m.get('date_pub','')[:10]}"
            )
        _relever_echecs_reseau()
        return

    inserted = 0
    with transaction() as conn:
        commune_id = _get_commune_entity_id(conn)
        cac_id     = _get_cac_entity_id(conn)
        for m in all_marches:
            if insert_marche(conn, m, commune_id, cac_id, dry_run=False):
                inserted += 1
                print(f"  [+] {m.get('objet','')[:60]}")

    print(f"\n[marches_publics] {inserted}/{len(all_marches)} insérés")
    if inserted == 0 and source in ("all", "decp"):
        print(
            "  Note : le DECP couvre les contrats ≥ 40 000 € (services) / 90 000 € (travaux).\n"
            "  Les marchés sous seuil de Lasalle n'y figurent pas — normale pour petite commune."
        )
    # Après le commit : les marchés lus sont gardés, mais le run est marqué
    # en erreur si une partie des sources n'a pas pu être lue.
    _relever_echecs_reseau()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Marchés publics Lasalle + CC CAC")
    parser.add_argument("--dry-run",  action="store_true")
    parser.add_argument("--source",   default="all",
                        choices=["all", "decp", "decp-eco", "boamp", "cac"])
    parser.add_argument("--years", type=str, default=None,
                        help="Plage d'années ex: 2022-2025 ou 2024")
    args = parser.parse_args()

    years = None
    if args.years:
        if "-" in args.years:
            start, end = args.years.split("-")
            years = list(range(int(start), int(end) + 1))
        else:
            years = [int(args.years)]

    main(dry_run=args.dry_run, source=args.source, years=years)
