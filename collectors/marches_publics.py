"""
marches_publics.py — Marchés publics de la commune et de son EPCI

Sources :
  1. DECP (Données Essentielles de la Commande Publique) — data.gouv.fr
     Fichiers JSON mensuels, filtrés par SIRET acheteur.
     Seuil de publication : ≥ 40 000 € (services/fournitures), ≥ 90 000 € (travaux).
     Note : une commune de 1 300 hab. publie peu dans le DECP — l'EPCI est la
     source principale. Ces trois requêtes (DECP consolidé, DECP v3, DECP
     augmenté) sont nationales : elles fonctionnent sans adaptation locale.
  2. Sites officiels de la commune et de l'intercommunalité, via le connecteur
     déclaré par l'instance (cf. collectors/connecteurs/).

Usage :
  python3 -m collectors.marches_publics --dry-run
  python3 -m collectors.marches_publics
  python3 -m collectors.marches_publics --source decp      # DECP uniquement
  python3 -m collectors.marches_publics --source site      # sites officiels
  python3 -m collectors.marches_publics --years 2022-2025  # plage d'années DECP
"""

import argparse
import json
import re
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

from .config import (
    COMMUNE_INSEE, COMMUNE_NAME, DEPARTEMENT, COMMUNE_SIREN as COMMUNE_SIREN_CFG,
    COMMUNE_SIRET as COMMUNE_SIRET_CFG, EPCI_NOM, EPCI_SIREN,
    HEADERS, REQUEST_DELAY
)
from .db import transaction, upsert_entity
from .archive import archive_fetch

# ── Constantes ────────────────────────────────────────────────────────────────

# SIRET/SIREN de la commune, confirmés via recherche-entreprises.api.gouv.fr
# le 13/08/2026 (COMMUNE DE BRASSAC, siège place de l'Hôtel de Ville).
COMMUNE_SIRET  = COMMUNE_SIRET_CFG
COMMUNE_SIREN  = COMMUNE_SIREN_CFG

# EPCI — SIREN depuis config
CAC_SIREN      = EPCI_SIREN
# Jetons de reconnaissance de l'acheteur dans les libellés en texte libre du
# DECP et du BOAMP, où l'acheteur n'est pas toujours identifié par son SIREN.
# Dérivés de la config : « brassac », « sidobre », « vals et plateaux ».
# Les mots significatifs du nom de l'EPCI : « CC », « Communauté », « de »,
# « des » n'identifient personne. Le seuil de quatre lettres écarte les
# articles sans avoir à les énumérer.
def _norme_acheteur(nom: str) -> str:
    """Forme comparable d'un nom d'acheteur : sans accents, casse, ponctuation
    ni mots de structure. « CC Causses Aigoual Cévennes Terres Solidaires » et
    « Communauté de communes Causses-Aigoual-Cévennes Terres solidaires » sont
    le même acheteur ; « Terres australes françaises » ne l'est pas.
    """
    t = unicodedata.normalize("NFD", nom or "")
    t = "".join(c for c in t if unicodedata.category(c) != "Mn").lower()
    t = re.sub(r"\b(cc|ca|cu|communaute|communautes|commune|communes|de|du|des|d|la|le|les|l)\b",
               " ", t)
    return re.sub(r"[^a-z0-9]+", "", t)


ACHETEUR_JETONS = tuple({COMMUNE_NAME.lower()} | {
    mot.lower() for mot in re.split(r"[\s'’-]+", EPCI_NOM)
    if len(mot) > 4 and mot.lower() not in ("communaute", "communauté", "commune",
                                            "communes", "agglomeration",
                                            "agglomération")
})

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


DECP_CACHE = Path(__file__).resolve().parent.parent / "data" / "raw" / "decp"
DECP_CACHE_JOURS = 7
DECP_ESSAIS = 3


def _nom_cache(titre: str) -> str:
    """Nom de fichier sûr pour le cache — pas de séparateur venu d'une URL."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", titre)[:120] or "decp.json"


def _telecharger_decp(url: str, nom: str) -> bytes | None:
    """Télécharge un fichier DECP consolidé, avec cache et reprise.

    Les fichiers annuels pèsent plusieurs centaines de Mo et static.data.gouv.fr
    rend la main lentement : un `read()` de 120 s expire régulièrement en milieu
    de transfert. Trois conséquences, corrigées ici :

      - un seul fichier manquant faisait échouer tout le step en fin de course
        (`_relever_echecs_reseau`), et emportait les quatre steps suivants ;
      - relancer la collecte retéléchargeait les 37 fichiers déjà lus ;
      - l'échec n'était pas réessayé, alors qu'il est presque toujours passager.

    Le cache est daté : au-delà de DECP_CACHE_JOURS, le fichier est repris à la
    source. Les fichiers d'années révolues ne bougent plus, mais celui du mois
    en cours est réécrit tous les jours.
    """
    DECP_CACHE.mkdir(parents=True, exist_ok=True)
    cache = DECP_CACHE / nom
    if cache.exists():
        age_jours = (time.time() - cache.stat().st_mtime) / 86400
        if age_jours < DECP_CACHE_JOURS:
            return cache.read_bytes()

    dernier = None
    for essai in range(1, DECP_ESSAIS + 1):
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                raw = resp.read()
            cache.write_bytes(raw)
            return raw
        except Exception as e:
            dernier = e
            # Un 404 ou un 403 ne s'améliorera pas en attendant : seules les
            # coupures et les erreurs serveur méritent un nouvel essai.
            if isinstance(e, urllib.error.HTTPError) and e.code < 500 and e.code != 429:
                break
            if essai < DECP_ESSAIS:
                attente = 5 * essai
                print(f"\n    essai {essai}/{DECP_ESSAIS} échoué ({e}), "
                      f"nouvelle tentative dans {attente}s…", end=" ", flush=True)
                time.sleep(attente)

    # Un fichier périmé vaut mieux que rien : on le signale comme tel.
    if cache.exists():
        print(f"\n    [réseau KO] reprise du cache local ({nom})", end=" ", flush=True)
        return cache.read_bytes()

    print(f"\n  [erreur téléchargement] {url[:60]} → {dernier}")
    _echecs_reseau.append(f"{url[:80]} → {dernier}")
    return None


def extract_marches_from_file(url: str, nom: str = "") -> list[dict]:
    """Télécharge et filtre un fichier DECP consolidé JSON sur le périmètre."""
    import gzip as _gzip
    # Le nom de cache vient du titre de la ressource (decp-2025-03.json), pas de
    # l'URL : data.gouv sert ces fichiers derrière un identifiant opaque.
    raw = _telecharger_decp(url, _nom_cache(nom or url))
    if raw is None:
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

        is_commune = acheteur_id.startswith(COMMUNE_SIREN)
        is_epci    = acheteur_id.startswith(CAC_SIREN)
        is_name    = any(j in acheteur_nom for j in ACHETEUR_JETONS)

        if is_commune or is_epci or is_name:
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
    """Interroge le DECP et retourne tous les marchés du périmètre."""
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
        marches = extract_marches_from_file(res["url"], title)
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

    print(f"  [DECP] {len(unique)} marchés uniques sur le périmètre")
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
    """DECP v3 : marchés dont l'ACHETEUR est la commune ou l'EPCI, plus ceux
    dont le LIEU D'EXÉCUTION tombe dans le périmètre — un marché du Département ou
    de la Région exécuté sur la commune intéresse autant le lecteur.

    Attention au lieu d'exécution : `lieuexecution_code` vaut tantôt un code
    INSEE, tantôt un code postal, et les deux jeux se recouvrent d'un
    département à l'autre. D'où le filtre conjoint sur `lieuexecution_typecode`,
    sans lequel on ramène des marchés étrangers au territoire.
    """
    import urllib.parse
    from .config import CODE_POSTAL, COMMUNES, COMMUNES_CP

    insee = ", ".join(f'"{c}"' for c in COMMUNES)
    # Le code postal ne sert qu'en repli du code commune, et il déborde
    # toujours : on ne retient que ceux dont la commune principale est dans le
    # périmètre — ici le CP de la commune elle-même.
    cp = ", ".join(f'"{c}"' for c in COMMUNES_CP if c == CODE_POSTAL)

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
    """Interroge le DECP augmenté Opendatasoft par SIREN acheteur (commune + EPCI)."""
    import urllib.parse
    print("\n[DECP-eco] Requête directe par SIREN acheteur…")
    results, seen = [], set()
    for label, siren in ((COMMUNE_NAME, COMMUNE_SIREN), (EPCI_NOM, CAC_SIREN)):
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
    Interroge l'API BOAMP OpenDataSoft (sans clé) pour la commune et l'EPCI.
    Couvre les avis d'appel public à la concurrence (AAPC) et attributions.
    """
    import urllib.parse
    print(f"\n[BOAMP] Recherche marchés {COMMUNE_NAME} + {EPCI_NOM}…")
    results = []
    seen_ids = set()

    # Le nom de l'acheteur est saisi librement par le publicateur : on
    # interroge sur les jetons du périmètre, en bornant au département pour le
    # nom de la commune — « Brassac » désigne aussi des communes de l'Ariège,
    # du Puy-de-Dôme et du Tarn-et-Garonne.
    queries = [
        f'nomacheteur like "%{COMMUNE_NAME.lower()}%" and code_departement="{DEPARTEMENT}"',
    ] + [f'nomacheteur like "%{j}%"' for j in ACHETEUR_JETONS
         if j != COMMUNE_NAME.lower()]

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
                # ── Qui a passé ce marché ? ──────────────────────────────────
                # Les jetons servent à CHERCHER large, jamais à CONCLURE. Un
                # seul mot commun du nom de l'EPCI suffisait à déclarer que
                # l'intercommunalité était l'acheteur : « terres » attrapait les
                # « Terres australes françaises », « cévennes » le GHT Cévennes
                # Gard Camargue et le CH d'Alès. 711 marchés sur 712 se sont
                # retrouvés attribués à la communauté de communes, qui n'y était
                # pour rien. Affirmer qu'une collectivité a acheté quelque chose
                # demande mieux qu'une coïncidence de vocabulaire.
                #
                # On n'attribue donc que sur le nom COMPLET, normalisé. Le reste
                # entre en base en `probable` et attend l'atelier.
                acheteur_norme = _norme_acheteur(acheteur)
                if _norme_acheteur(COMMUNE_NAME) in acheteur_norme:
                    acheteur_id_str, certitude = COMMUNE_SIREN, "verified"
                elif _norme_acheteur(EPCI_NOM) in acheteur_norme:
                    acheteur_id_str, certitude = CAC_SIREN, "verified"
                else:
                    acheteur_id_str, certitude = "", "probable"
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
                    "confidence":  certitude,
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


# ── Source 3 : avis publiés par la collectivité ─────────────────────────────

def fetch_avis_site() -> list[dict]:
    """Avis de publicité publiés sur les sites officiels, via le connecteur.

    La version d'origine découpait le HTML d'un site précis à coups de
    `re.split('<article|<div class=post')` pour retrouver titre, date et PDF.
    Le connecteur rend ces trois champs ; il n'y a plus de structure de page à
    deviner (cf. collectors/connecteurs/).
    """
    from .connecteurs import charger

    avis = charger().avis_marches()
    print(f"\n[site] {len(avis)} avis de publicité")
    return [{
        "source":       a["source"],
        "source_type":  "site_officiel",
        "acheteur_id":  CAC_SIREN if a.get("portee") == "epci" else COMMUNE_SIREN,
        "acheteur_nom": EPCI_NOM if a.get("portee") == "epci" else COMMUNE_NAME,
        "objet":        a["objet"],
        "nature":       "Avis de publicité",
        "procedure":    "Consultation",
        "montant":      None,
        "date_pub":     a.get("date_pub", ""),
        "date_notif":   "",
        "pdf_url":      a.get("pdf_url", ""),
        "titulaires":   [],
        "raw_id":       a.get("raw_id", ""),
    } for a in avis]


# ── Insertion DB ──────────────────────────────────────────────────────────────

def _get_commune_entity_id(conn) -> int:
    """Retourne l'ID de l'entité « Commune de … » (acheteur)."""
    row = conn.execute(
        "SELECT id FROM entities WHERE type='service' AND name=? LIMIT 1",
        (f"Commune de {COMMUNE_NAME}",)
    ).fetchone()
    if row:
        return row["id"]
    return upsert_entity(
        conn, type="service", name=f"Commune de {COMMUNE_NAME}",
        short_name=COMMUNE_NAME, commune=COMMUNE_NAME, confidence="verified"
    )


def _get_cac_entity_id(conn) -> int:
    """Retourne l'ID de l'EPCI (acheteur)."""
    row = conn.execute(
        "SELECT id FROM entities WHERE type='service' AND name=? LIMIT 1",
        (EPCI_NOM,)
    ).fetchone()
    if row:
        return row["id"]
    return upsert_entity(
        conn, type="service", name=EPCI_NOM, short_name="CCSVP",
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
            confidence      TEXT DEFAULT 'verified',
            created_at      TEXT DEFAULT (datetime('now')),
            UNIQUE(raw_id)
        )
    """)
    # Cette définition double celle de db/schema.sql. Elle doit rester
    # alignée : une base créée par ce collecteur seul, sans passer par
    # `init_db()`, n'aurait pas la colonne et le filtre de publication
    # échouerait au moment de publier — donc trop tard.
    colonnes = {r[1] for r in conn.execute("PRAGMA table_info(marches_publics)")}
    if "confidence" not in colonnes:
        conn.execute("ALTER TABLE marches_publics "
                     "ADD COLUMN confidence TEXT DEFAULT 'verified'")
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
    # Les sources qui identifient l'acheteur par son SIREN (DECP) n'ont pas de
    # doute à exprimer : elles ne posent pas la clé, et le marché vaut
    # `verified`. Seul le BOAMP, où le nom de l'acheteur est en saisie libre,
    # rend parfois `probable`.
    certitude = m.get("confidence") or "verified"

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
        acheteur_label = EPCI_NOM

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
           lieu_exec, source, source_url, raw_id, event_id, confidence)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        acheteur_eid, acheteur_id_str[:9] if acheteur_id_str else "", acheteur_label,
        titulaire_eid, titulaire_siren, titulaire_nom,
        objet, m.get("nature"), m.get("procedure"), montant,
        cpv_str, cpv_label_str, date, date_pub, m.get("duree_mois"),
        m.get("lieu_exec"), m["source"], source_url, raw_id, ev_id,
        certitude,
    ))

    # ── Flux financier ───────────────────────────────────────────────────────
    # Le flux hérite de la certitude du marché : un montant attribué à une
    # collectivité dont on n'est pas sûr qu'elle a acheté serait pire publié
    # que le marché lui-même — c'est de l'argent qu'on lui prête.
    if montant:
        year_str = (date or "")[:4]
        year = int(year_str) if year_str.isdigit() else None
        conn.execute(
            "INSERT INTO financial_flows"
            " (type, year, amount, from_id, to_id, event_id, description, source, confidence)"
            " VALUES ('marché', ?, ?, ?, ?, ?, ?, ?, ?)",
            (year, int(montant), acheteur_eid, titulaire_eid, ev_id,
             f"{objet[:80]} ({acheteur_label})", m["source"], certitude)
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
    print(f"  EPCI SIREN    : {CAC_SIREN} ({EPCI_NOM})")

    all_marches: list[dict] = []

    if source in ("all", "decp"):
        all_marches += fetch_decp_marches(years=years)

    if source in ("all", "decp", "decp-eco"):
        all_marches += fetch_decp_v3_marches()      # jeu vivant
        all_marches += fetch_decp_eco_marches()     # repli historique (figé 03/2026)

    if source in ("all", "boamp"):
        all_marches += fetch_boamp_marches()

    if source in ("all", "site"):
        all_marches += fetch_avis_site()

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
            f"  Les marchés sous seuil de {COMMUNE_NAME} n'y figurent pas — normal pour une petite commune."
        )
    # Après le commit : les marchés lus sont gardés, mais le run est marqué
    # en erreur si une partie des sources n'a pas pu être lue.
    _relever_echecs_reseau()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Marchés publics — commune + EPCI")
    parser.add_argument("--dry-run",  action="store_true")
    parser.add_argument("--source",   default="all",
                        choices=["all", "decp", "decp-eco", "boamp", "site"])
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
