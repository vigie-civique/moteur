"""
Collecteur SIRENE — recherche-entreprises.api.gouv.fr
Importe toutes les entités (entreprises, EI, asso, SCI...) dont le siège
est dans la commune de l'instance (code_commune=COMMUNE_INSEE).
"""
import json
import time
import urllib.parse
import urllib.request
from .archive import fetch_json
from .config import SIRENE_API, COMMUNE_INSEE, COMMUNE_NAME, HEADERS, REQUEST_DELAY, naf_theme
from .db import transaction, upsert_entity, upsert_person, upsert_relation


def fetch_page(page: int, per_page: int = 25, insee: str = COMMUNE_INSEE) -> dict:
    params = urllib.parse.urlencode({
        "code_commune": insee,
        "per_page": per_page,
        "page": page,
    })
    url = f"{SIRENE_API}?{params}"
    for attempt in range(4):
        try:
            return fetch_json(url, source="sirene", timeout=15)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 2 ** attempt * 3   # 3, 6, 12, 24s
                print(f"  [sirene] 429 rate limit — attente {wait}s (tentative {attempt+1})")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("SIRENE API: trop de tentatives")


def fetch_all(insee: str = COMMUNE_INSEE) -> list[dict]:
    """Récupère toutes les pages de résultats SIRENE pour une commune."""
    results = []
    page = 1
    per_page = 25
    total = None

    while True:
        try:
            data = fetch_page(page, per_page, insee)
        except Exception as e:
            print(f"  [sirene] erreur page {page}: {e}")
            break

        items = data.get("results", [])
        results.extend(items)

        if total is None:
            total = data.get("total_results", 0)
            print(f"  [sirene] {total} entités au total, {-(-total//per_page)} pages")

        print(f"  [sirene] page {page} → {len(items)} entités")

        if len(results) >= total or not items:
            break

        page += 1
        time.sleep(REQUEST_DELAY)

    return results


def _extract_person(dirigeant: dict) -> dict:
    """Normalise un dirigeant SIRENE en dict personne."""
    nom     = (dirigeant.get("nom") or "").strip().upper()
    prenom  = (dirigeant.get("prenoms") or "").strip().title()
    qualite = dirigeant.get("qualite", "")
    # API retourne "YYYY-MM" dans date_de_naissance ou juste l'année
    dob     = dirigeant.get("date_de_naissance", "") or \
              dirigeant.get("annee_de_naissance", "")
    year    = int(dob[:4]) if dob and len(dob) >= 4 else None
    month   = int(dob[5:7]) if dob and len(dob) >= 7 else None
    return {
        "lastname": nom,
        "firstname": prenom,
        "birth_year": year,
        "birth_month": month,
        "qualite": qualite,
    }


def import_sirene(insee: str = COMMUNE_INSEE, commune: str = COMMUNE_NAME):
    print(f"[sirene] Démarrage collecte {commune} ({insee})...")
    items = fetch_all(insee)
    print(f"[sirene] {commune} : {len(items)} entités récupérées, import en base...")

    inserted_biz  = 0
    inserted_per  = 0
    inserted_rel  = 0
    skipped       = 0

    with transaction() as conn:
        for item in items:
            try:
                _import_one(conn, item, commune=commune,
                            counters=(inserted_biz, inserted_per, inserted_rel))
                inserted_biz += 1
            except Exception as e:
                skipped += 1
                siren = item.get("siren", "?")
                print(f"  [sirene] skip {siren}: {e}")
            # Commit partiel toutes les 50 entités
            if inserted_biz % 50 == 0 and inserted_biz > 0:
                conn.commit()

    print(f"[sirene] {commune} OK — {inserted_biz} entreprises, "
          f"{inserted_per} personnes, {inserted_rel} relations, {skipped} ignorés")


def _import_one(conn, item: dict, counters: tuple, commune: str = COMMUNE_NAME):
    siren    = item.get("siren", "")
    nom      = (item.get("nom_complet") or item.get("nom_raison_sociale") or siren).strip()
    siege    = item.get("siege") or {}
    naf_code = (item.get("activite_principale") or
                siege.get("activite_principale") or "").replace(".", "")
    naf_lbl  = (item.get("activite_principale_naf25") or
                siege.get("activite_principale_naf25") or "")
    status   = item.get("etat_administratif") or siege.get("etat_administratif", "A")
    form_lbl = ""   # non fourni par cette API
    form_cod = item.get("nature_juridique", "")
    creation = item.get("date_creation", "")
    closing  = item.get("date_fermeture", "")
    capital  = item.get("capital", None)
    eff      = item.get("tranche_effectif_salarie", "")

    # Coordonnées siège. SIRENE renvoie la chaîne littérale '[NON-DIFFUSIBLE]'
    # pour les établissements ayant demandé la non-diffusion de leur adresse :
    # `float()` levait alors une ValueError qui faisait perdre l'entreprise
    # ENTIÈRE (6 rejets sur la seule commune de Val-d'Aigoual, 11/08/2026).
    # L'entreprise existe et son SIREN est public : on l'importe sans géoloc.
    def _coord(v):
        try:
            return float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

    lat = _coord(siege.get("latitude"))
    lng = _coord(siege.get("longitude"))
    address = siege.get("adresse") or siege.get("geo_adresse", "")
    if isinstance(address, str) and "NON-DIFFUSIBLE" in address:
        address = None

    # Entité principale
    eid = upsert_entity(conn,
        type="business",
        name=nom,
        short_name=siren,
        lat=lat,
        lng=lng,
        address=address,
        confidence="verified",
        commune=commune
    )

    # Extension businesses
    conn.execute(
        "INSERT OR IGNORE INTO businesses"
        " (entity_id,siren,siret_siege,naf_code,naf_label,"
        "  legal_form_code,legal_form,status,capital,employees_range,"
        "  creation_date,closing_date,raw_data)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (eid, siren, siege.get("siret"), naf_code, naf_lbl,
         form_cod, form_lbl, status, capital, eff,
         creation, closing, json.dumps(item, ensure_ascii=False))
    )

    # Dirigeants
    for dirigeant in (item.get("dirigeants") or []):
        p = _extract_person(dirigeant)
        if not p["lastname"]:
            continue

        full_name = f"{p['firstname']} {p['lastname']}".strip()
        # `commune` DOIT être passée : le schéma a pour défaut 'Lasalle', donc
        # omettre l'argument marque tout dirigeant comme Lasallois — 2 738 faux
        # Lasallois créés le 11/08/2026 en élargissant la collecte aux 15
        # communes de l'EPCI. C'est la commune de l'ENTREPRISE, pas le domicile
        # du dirigeant, que SIRENE ne publie pas : à lire comme un rattachement
        # d'activité, jamais comme une adresse.
        pid = upsert_entity(conn,
            type="person",
            name=full_name,
            commune=commune,
            confidence="verified"
        )
        conn.execute(
            "INSERT OR IGNORE INTO persons"
            " (entity_id,firstname,lastname,birth_year,birth_month)"
            " VALUES (?,?,?,?,?)",
            (pid, p["firstname"], p["lastname"],
             p["birth_year"], p["birth_month"])
        )

        # Relation personne → entreprise
        qualite = p["qualite"] or "dirigeant"
        rel_type = _qualite_to_rel(qualite)
        upsert_relation(conn,
            from_id=pid, to_id=eid,
            rel_type=rel_type,
            source="sirene",
            confidence="verified",
            metadata=json.dumps({"qualite": qualite})
        )


def _qualite_to_rel(qualite: str) -> str:
    q = qualite.lower()
    if "gérant" in q or "gerant" in q:    return "gérant"
    if "président" in q or "president" in q: return "président"
    if "associé" in q or "associe" in q:  return "associé"
    if "directeur" in q:                   return "dirigeant"
    if "trésorier" in q or "tresorier" in q: return "trésorier"
    if "secrétaire" in q or "secretaire" in q: return "secrétaire"
    return "dirigeant"
