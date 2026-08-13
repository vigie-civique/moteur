"""
Collecteur RNA / Associations
Sources :
  1. API JO associations (Journal Officiel) — déclarations post-2009 (nationale)
  2. les pages d'annuaire du site officiel — responsables nommés

La source 2 passe par le connecteur de l'instance : la version d'origine
scrapait une page précise d'un site précis, avec un navigateur furtif pour
contourner l'anti-bot d'un thème Drupal. Les pages à lire se déclarent dans
`config/instance.json` (clé `pages.commune.annuaires`).

Ce que ces pages publient et que le RNA ne donne pas : le nom du responsable de
chaque association, avec ses coordonnées. C'est collecté tel quel — la règle de
l'atelier est de tout collecter et de filtrer à la publication, pas l'inverse —
et rangé dans `entity_notes`, jamais dans une fiche personne.
"""
import json
import re
import time
import urllib.parse
import urllib.request
import unicodedata
from .archive import fetch_json
from .config import (JO_ASSO_API, CODE_POSTAL, COMMUNE_NAME, COMMUNES,
                     HEADERS, REQUEST_DELAY)


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
# Source 2 : page « associations » du site communal
# ----------------------------------------------------------------

# « Brassac Basket Club \n THEVENARD Raphaël \n 119 avenue du Sidobre… »
# Le responsable est la ligne qui suit le nom, en « NOM Prénom ».
# Le prénom composé s'écrit « Jean-François » : le tiret n'est admis que suivi
# d'une majuscule, sinon la capture s'arrête sur « Jean- » et le responsable
# devient une association de plus.
_RESPONSABLE = re.compile(
    r"^([A-ZÀ-Ÿ][A-ZÀ-Ÿ'’\-]{2,}(?:\s+[A-ZÀ-Ÿ][A-ZÀ-Ÿ'’\-]{2,})*)\s+"
    r"([A-ZÀ-Ÿ][a-zà-ÿ'’]+(?:-[A-ZÀ-Ÿ][a-zà-ÿ'’]+)*)$")
_CONTACT = re.compile(r"(0\d[\s.]?(?:\d{2}[\s.]?){4}|[\w.+-]+@[\w-]+\.[\w.]+|https?://\S+)")


def fetch_structures_site() -> list[dict]:
    """Associations listées sur le site communal, avec leur responsable.

    Retourne [{name, responsable, contacts, url, source}]. Le découpage se fait
    sur les lignes : une association ouvre un bloc (ligne sans chiffre ni
    contact), le responsable suit, puis l'adresse et les contacts.
    """
    from .connecteurs import charger
    from .config import COMMUNE_URL
    import urllib.parse

    source = urllib.parse.urlparse(COMMUNE_URL).netloc.removeprefix("www.")
    structures = []
    for texte in charger().pages_annuaire("commune"):
        lignes = [l.strip() for l in texte.splitlines() if l.strip()]
        courante = None
        for ligne in lignes:
            if ligne.isupper() and "ANNUAIRE" in ligne:
                continue
            # Une phrase d'introduction n'est pas une association : elle est
            # longue et se termine par une ponctuation de phrase.
            if len(ligne) > 60 or ligne.endswith((":", ".")):
                continue
            m = _RESPONSABLE.match(ligne)
            if m and courante:
                courante["responsable"] = f"{m.group(2)} {m.group(1)}"
                continue
            contacts = _CONTACT.findall(ligne)
            if contacts and courante:
                courante["contacts"] += contacts
                continue
            # Une ligne d'adresse commence par un numéro, ou porte le code
            # postal de la commune.
            if re.match(r"^[\d]", ligne) or CODE_POSTAL in ligne:
                continue
            courante = {"name": ligne, "responsable": None, "contacts": [],
                        "url": COMMUNE_URL, "source": source}
            structures.append(courante)

    print(f"  [rna/site] {len(structures)} associations listées, "
          f"{sum(1 for s in structures if s['responsable'])} avec un responsable nommé")
    return structures


def _import_structures(conn, structures: list[dict]) -> int:
    """Rattache responsable et contacts à l'association, en note d'entité."""
    poses = 0
    for st in structures:
        if not st["responsable"] and not st["contacts"]:
            continue
        eid = upsert_entity(conn, type="association", name=st["name"],
                            commune=COMMUNE_NAME, confidence="probable")
        note = json.dumps({"responsable": st["responsable"],
                           "contacts": st["contacts"],
                           "url": st["url"]}, ensure_ascii=False)
        # `entity_notes` n'a pas de contrainte d'unicité : sans ce contrôle,
        # chaque exécution ajoute une note identique de plus.
        if conn.execute(
            "SELECT 1 FROM entity_notes WHERE entity_id=? AND note=?",
            (eid, note)).fetchone():
            continue
        conn.execute(
            "INSERT INTO entity_notes (entity_id, note, source, confidence)"
            " VALUES (?,?,?,?)",
            (eid, note, st["source"], "probable"))
        poses += 1
    return poses


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

    # Source 2 : uniquement sur le CP de la commune — la page ne liste que les
    # associations de Brassac, la relancer pour chaque CP du registre ferait
    # seize fois le même travail.
    if cp == CODE_POSTAL:
        structures = fetch_structures_site()
        with transaction() as conn:
            poses = _import_structures(conn, structures)
        print(f"[rna] {poses} associations enrichies depuis le site communal")


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
