"""
Collecteur RNA / Associations
Sources :
  1. API JO associations (Journal Officiel) — déclarations post-2009
  2. lasalle.fr/structures — responsables nommés localement
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import unicodedata
from .archive import fetch_json
from .config import JO_ASSO_API, CODE_POSTAL, HEADERS, REQUEST_DELAY, LASALLE_URL, COMMUNES


def _norm(s: str) -> str:
    """Normalise un nom de commune : sans accents, minuscules, séparateurs unifiés."""
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    for ch in "-'’":
        s = s.replace(ch, " ")
    return " ".join(s.lower().split())


# Index nom normalisé → nom officiel du registre (pour taguer/filtrer les assos)
_COMMUNE_LOOKUP = {_norm(c["nom"]): c["nom"] for c in COMMUNES.values()}
# Alias commune nouvelle Thoiras-Corbès (le JO peut encore utiliser les anciens noms)
for _alias in ("Thoiras", "Corbès"):
    _COMMUNE_LOOKUP[_norm(_alias)] = "Thoiras-Corbès"


def _match_commune(ville: str) -> str | None:
    """Nom officiel du registre si la commune est collectée, sinon None."""
    return _COMMUNE_LOOKUP.get(_norm(ville))
from .db import transaction, upsert_entity, upsert_relation


# ----------------------------------------------------------------
# Source 1 : API JO associations
# ----------------------------------------------------------------

def fetch_jo_page(offset: int = 0, limit: int = 100, cp: str = CODE_POSTAL) -> dict:
    params = urllib.parse.urlencode({
        "where": f'codepostal_actuel="{cp}"',
        "limit": limit,
        "offset": offset,
        "order_by": "dateparution DESC"
    })
    url = f"{JO_ASSO_API}?{params}"
    return fetch_json(url, source="rna-jo", timeout=15)


def fetch_all_jo(cp: str = CODE_POSTAL) -> list[dict]:
    results = []
    offset = 0
    limit  = 100
    total  = None

    while True:
        try:
            data = fetch_jo_page(offset, limit, cp)
        except Exception as e:
            print(f"  [rna] erreur offset {offset}: {e}")
            break

        items = data.get("results", [])
        results.extend(items)

        if total is None:
            total = data.get("total_count", 0)
            print(f"  [rna] {total} associations JO pour CP {cp}")

        if not items or len(results) >= total:
            break

        offset += limit
        time.sleep(REQUEST_DELAY)

    return results


# ----------------------------------------------------------------
# Source 2 : lasalle.fr/structures (responsables nommés)
# ----------------------------------------------------------------

def fetch_lasalle_structures() -> list[dict]:
    """
    Scrape lasalle.fr/structures pour récupérer les responsables.
    Retourne une liste de {name, responsable, url}.
    """
    # Scrapling est emprunté à un autre environnement virtuel quand il n'est pas
    # installé ici. Le chemin était codé en dur avec un nom d'utilisateur et le
    # nom d'un projet sans rapport : inutilisable ailleurs, et indiscret dans un
    # dépôt public. Il se déclare désormais dans l'environnement, et son absence
    # dégrade proprement — ce collecteur est optionnel.
    chemin_scrapling = os.environ.get("SCRAPLING_SITE_PACKAGES")
    try:
        if chemin_scrapling:
            sys.path.insert(0, chemin_scrapling)
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        print("  [rna] Scrapling non disponible — structures lasalle.fr ignorées")
        return []

    structures = []
    fetcher = StealthyFetcher()
    base = f"{LASALLE_URL}/structures"

    # Découverte des pages
    try:
        page = fetcher.fetch(base)
        links = page.css("a[href*='/structures/']")
        struct_urls = list({
            f"{LASALLE_URL}{a.attrib['href']}"
            if a.attrib['href'].startswith('/') else a.attrib['href']
            for a in links
            if '/structures/' in a.attrib.get('href', '')
            and a.attrib.get('href', '').count('/') > 2
        })
        print(f"  [rna/lasalle] {len(struct_urls)} pages structures trouvées")
    except Exception as e:
        print(f"  [rna/lasalle] erreur index: {e}")
        return []

    for url in struct_urls[:50]:   # limite 50 pour ne pas surcharger
        try:
            p = fetcher.fetch(url)
            name = p.css("h1").first
            resp = p.find(lambda el: "responsable" in el.text.lower()
                          or "contact" in el.text.lower(), first=True)
            structures.append({
                "name":        name.text.strip() if name else url.split("/")[-1],
                "responsable": resp.text.strip() if resp else None,
                "url":         url,
                "source":      "lasalle.fr"
            })
            time.sleep(REQUEST_DELAY)
        except Exception:
            continue

    return structures


# ----------------------------------------------------------------
# Import en base
# ----------------------------------------------------------------

def import_rna(cp: str = CODE_POSTAL):
    print(f"[rna] Démarrage collecte JO associations (CP {cp})...")
    items = fetch_all_jo(cp)
    print(f"[rna] CP {cp} : {len(items)} associations récupérées, import en base...")

    inserted   = 0
    skipped    = 0
    hors_perimetre = 0

    with transaction() as conn:
        for item in items:
            # Filtre : ne garder que les communes collectées (registre COMMUNES).
            # Indispensable — un CP déborde toujours sur des communes voisines.
            if not _match_commune(item.get("commune_actuelle") or ""):
                hors_perimetre += 1
                continue
            try:
                _import_jo_record(conn, item)
                inserted += 1
            except Exception as e:
                skipped += 1
                print(f"  [rna] skip {item.get('numero_rna','?')}: {e}")
            if inserted % 50 == 0 and inserted > 0:
                conn.commit()

    print(f"[rna] CP {cp} OK — {inserted} associations du périmètre, "
          f"{hors_perimetre} hors périmètre ignorées, {skipped} erreurs")


def _import_jo_record(conn, item: dict):
    # Schéma dataset jo_associations (Opendatasoft v2.1, refonte 2024)
    rna_id  = item.get("numero_rna") or item.get("id", "")
    titre   = (item.get("titre") or item.get("titre_search") or rna_id).strip()
    objet   = item.get("objet", "")
    cp      = item.get("codepostal_actuel", "") or ""
    ville   = (item.get("commune_actuelle") or "").strip()
    addr    = (item.get("adresse_actuelle") or "").strip()
    addr_str = " ".join(filter(None, [addr, cp, ville]))

    # Type d'avis : Création / Modification / Dissolution
    typeavis = (item.get("typeavis") or "").lower()
    is_diss  = "dissol" in typeavis
    status   = "D" if is_diss else "A"

    # Coordonnées
    geo  = item.get("geo_point") or {}
    lat  = geo.get("lat")
    lng  = geo.get("lon")

    crea = item.get("datedeclaration") or item.get("dateparution", "")
    diss = item.get("datedeclaration") if is_diss else None

    commune = _match_commune(ville) or (ville or None)

    eid = upsert_entity(conn,
        type="association",
        name=titre,
        lat=float(lat) if lat else None,
        lng=float(lng) if lng else None,
        address=addr_str or None,
        confidence="verified",
        commune=commune
    )

    conn.execute(
        "INSERT OR IGNORE INTO associations"
        " (entity_id,rna_id,object,status,creation_date,dissolution_date,raw_data)"
        " VALUES (?,?,?,?,?,?,?)",
        (eid, rna_id, objet, status, crea[:10] if crea else None,
         diss[:10] if diss else None,
         json.dumps(item, ensure_ascii=False))
    )
