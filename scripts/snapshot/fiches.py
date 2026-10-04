"""Les fiches publiées : quelles entités sortent, sous quelle forme, et pourquoi les autres non.

L'étape `fiches` lit toutes les entités de la base et rend celles qui ont
droit à une fiche publique (`public_entities`, `public_ids`), et pour les
autres la raison de leur exclusion. Le verdict de l'atelier passe avant les
règles ; le périmètre et les règles de publication font le reste
(`public_entity`).
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from urllib.parse import urlparse

from collectors.verdict import ecarte
from scripts.snapshot.perimetre import publiable_dans_perimetre
from scripts.snapshot.socle import ROOT, RULES, rows


def in_commune_bbox(lat, lng) -> bool:
    if lat is None or lng is None:
        return False
    bbox = RULES["locations"]["bbox"]
    return (
        bbox["lat_min"] <= lat <= bbox["lat_max"]
        and bbox["lng_min"] <= lng <= bbox["lng_max"]
    )


def in_center_box(lat, lng) -> bool:
    if lat is None or lng is None:
        return False
    box = RULES["locations"]["center_fallback_box"]
    return (
        box["lat_min"] <= lat <= box["lat_max"]
        and box["lng_min"] <= lng <= box["lng_max"]
    )


def domain_for(url: str | None) -> str:
    if not url:
        return ""
    value = url.strip()
    if not value:
        return ""
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    return urlparse(value).netloc.lower().removeprefix("www.")


def load_confirmed_urls() -> dict[int, list[dict]]:
    path = ROOT / "config" / "sites_locaux.json"
    if not path.exists():
        return {}

    data = json.loads(path.read_text(encoding="utf-8"))
    entries: list[dict] = []
    if isinstance(data, dict):
        for category, items in data.items():
            for item in items or []:
                item = dict(item)
                item["_category"] = category
                entries.append(item)
    elif isinstance(data, list):
        entries = data

    by_entity: dict[int, list[dict]] = defaultdict(list)
    for item in entries:
        entity_id = item.get("entity_id")
        url = (item.get("url") or "").strip()
        if not entity_id or not url or item.get("confirmed") is not True:
            continue
        dom = domain_for(url)
        if dom in set(RULES["urls"]["exclude_generic_domains"]):
            continue
        by_entity[int(entity_id)].append({
            "url": url,
            "domain": dom,
            "label": item.get("name") or dom,
            "source": "sites_locaux.confirmed",
        })
    return by_entity


# ── Ce qu'une fiche ne disait pas d'elle-même ────────────────────────────────
#
# ACTIVITÉ. Sur les 744 « entreprises » publiées à Lasalle, 377 étaient CESSÉES
# — plus de la moitié. Sur les 294 associations, 22 sont dissoutes au Journal
# officiel et 15 cessées au répertoire. Un annuaire qui les aligne sans le dire
# décrit une commune qui n'existe plus, et un habitant qui cherche un artisan
# tombe une fois sur deux sur une entreprise fermée depuis dix ans.
#
# Ce que la source dit vraiment : SIRENE porte `A` (active) ou `C`/`F` (cessée,
# fermée), le RNA porte `A` ou `D` (dissoute). Elle ne dit RIEN de plus — une
# association qui a cessé de se réunir sans déclarer sa dissolution reste `A`
# pour toujours. `actif` vaut donc None quand la source se tait : c'est une
# ignorance, pas une présomption d'activité.
FIN_DACTIVITE = {"C", "F", "D"}


def etat_activite(row_data: dict) -> tuple[bool | None, str | None]:
    """(actif, date de fin) d'après les registres. None quand ils se taisent."""
    statut = row_data.get("asso_status") or row_data.get("biz_status")
    fin = row_data.get("dissolution_date") or row_data.get("business_closing_date")
    if not statut:
        return (None, fin or None)
    return (statut.upper() not in FIN_DACTIVITE, fin or None)


# NATURE. « 744 entreprises » comptait 524 entreprises individuelles et 85
# sociétés dont l'activité déclarée est la gestion immobilière — des structures
# qui détiennent un patrimoine, pas des entreprises qui produisent. Les
# distinguer n'est pas un jugement : c'est le code NAF et la forme juridique,
# tels que l'INSEE les publie.
#
# L'activité l'emporte sur la forme juridique : une SCI en NAF 41 (construction)
# construit, une entreprise individuelle en NAF 68 loue. C'est ce que la
# structure FAIT qui répond à la question posée, pas comment elle est montée.
NAF_IMMOBILIER = "68"


def nature_entreprise(row_data: dict) -> str:
    """`patrimoniale`, `individuelle` ou `societe`."""
    if str(row_data.get("naf_code") or "").startswith(NAF_IMMOBILIER):
        return "patrimoniale"
    if str(row_data.get("legal_form_code") or "") == "1000":
        return "individuelle"
    return "societe"


def public_entity(
    row_data: dict,
    urls: list[dict],
    public_person_ids: set[int],
    ids_conseil_communautaire: set[int] = frozenset(),
) -> tuple[dict | None, list[str]]:
    reasons: list[str] = []
    confidence = row_data.get("confidence")
    if confidence not in set(RULES["confidence"]["public"]):
        return None, ["private_confidence"]

    entity_type = row_data.get("type")
    if entity_type == "person" and row_data["id"] not in public_person_ids:
        return None, ["person_without_public_civic_role"]

    perimetre = row_data.get("perimetre")
    if not publiable_dans_perimetre(perimetre, entity_type,
                                    row_data["id"] in ids_conseil_communautaire):
        return None, [f"hors_fiche_perimetre_{perimetre}"]

    lat = row_data.get("lat")
    lng = row_data.get("lng")
    has_public_location = False
    location_quality = "missing"

    if entity_type == "person":
        location_quality = "hidden_person"
        lat = None
        lng = None
    elif row_data.get("lat") is None or row_data.get("lng") is None:
        location_quality = "missing"
    elif (entity_type == "business"
          and str(row_data.get("legal_form_code") or "") == "1000"
          and row_data.get("geocode_source") != "manual"):
        # RGPD : entrepreneur individuel — le siège est très souvent le domicile.
        # Coords retirées du public, sauf placement manuel délibéré à l'atelier
        # (structure avec un vrai local). cf. known-issues « vigilance RGPD ».
        location_quality = "hidden_ei_domicile"
        lat = None
        lng = None
    elif not in_commune_bbox(row_data["lat"], row_data["lng"]):
        location_quality = "outside_lasalle_bbox"
        lat = None
        lng = None
    elif in_center_box(row_data["lat"], row_data["lng"]):
        location_quality = "approx_center"
        has_public_location = entity_type in {"place", "service"}
        if not has_public_location:
            lat = None
            lng = None
    else:
        location_quality = "usable"
        has_public_location = True

    public = {
        "id": row_data["id"],
        "type": entity_type,
        "name": row_data["name"],
        "short_name": row_data.get("short_name"),
        # La commune de rattachement : la collecte couvre les 15 communes de
        # l'intercommunalité, et rien ne le disait sur une fiche — un lecteur
        # pouvait croire que tout était à Lasalle.
        "commune": row_data.get("commune"),
        # C1 = Lasalle, C2 = l'intercommunalité, C3 = autorité supra-communale,
        # lien = rattaché à un acteur suivi sans être sur le territoire.
        # L'UI doit le montrer : une fiche C2 ou `lien` ne se lit pas comme une
        # fiche lasalloise.
        "perimetre": row_data.get("perimetre"),
        "confidence": confidence,
        "location_quality": location_quality,
        "lat": lat,
        "lng": lng,
        "has_public_location": has_public_location,
        "urls": urls,
    }

    if entity_type in ("business", "association"):
        actif, fin = etat_activite(row_data)
        # `actif` à None = les registres ne disent rien. À ne jamais lire comme
        # « en activité » : c'est justement la case où se cachent les structures
        # dormantes qui n'ont jamais déclaré leur fin.
        public["actif"] = actif
        public["fin_activite"] = fin

    if entity_type == "business":
        public.update({
            "siren": row_data.get("siren"),
            "naf_code": row_data.get("naf_code"),
            "naf_label": row_data.get("naf_label"),
            "status": row_data.get("biz_status"),
            "creation_date": row_data.get("business_creation_date"),
            "nature": nature_entreprise(row_data),
        })
    elif entity_type == "association":
        public.update({
            "rna_id": row_data.get("rna_id"),
            "object": row_data.get("asso_object"),
            "status": row_data.get("asso_status"),
            "creation_date": row_data.get("asso_creation_date"),
        })
    elif entity_type == "place":
        public.update({
            "osm_category": row_data.get("osm_category"),
            "osm_value": row_data.get("osm_value"),
        })
    elif entity_type == "service":
        public.update({
            "category": row_data.get("service_category"),
            "operator": row_data.get("operator"),
            "opening_hours": row_data.get("opening_hours"),
        })
    elif entity_type == "person":
        public.update({
            "firstname": row_data.get("firstname"),
            "lastname": row_data.get("lastname"),
        })

    return public, reasons


def etape_fiches(conn, revue, public_person_ids, ids_conseil_communautaire,
                 exclusions) -> dict:
    confirmed_urls = load_confirmed_urls()
    entity_rows = rows(conn, """
        SELECT
            e.id, e.type, e.name, e.short_name, e.lat, e.lng, e.address, e.confidence,
            e.geocode_source, e.commune, e.perimetre,
            p.firstname, p.lastname, p.birth_year,
            b.siren, b.naf_code, b.naf_label, b.status AS biz_status,
            b.legal_form_code,
            b.creation_date AS business_creation_date,
            b.closing_date AS business_closing_date,
            a.rna_id, a.object AS asso_object,
            a.status AS asso_status, a.dissolution_date,
            a.creation_date AS asso_creation_date,
            pl.osm_category, pl.osm_value,
            s.category AS service_category, s.operator, s.opening_hours
        FROM entities e
        LEFT JOIN persons p ON p.entity_id = e.id
        LEFT JOIN businesses b ON b.entity_id = e.id
        LEFT JOIN associations a ON a.entity_id = e.id
        LEFT JOIN places pl ON pl.entity_id = e.id
        LEFT JOIN services s ON s.entity_id = e.id
        ORDER BY e.name
    """)

    # Entreprises individuelles : le lien « dirigeant » y est tautologique.
    ei_ids = {r["id"] for r in entity_rows
              if str(r.get("legal_form_code") or "") == "1000"}
    public_entities: list[dict] = []
    entity_exclusions: list[dict] = []
    # Les entités MORALES écartées pour le seul périmètre : leurs flux
    # d'argent public se publient déliés (cf. `statut_extremites`).
    ecartees_du_perimetre: set[int] = set()
    location_quality = Counter()
    revue_fiches = revue.get("entity", {})
    for entity in entity_rows:
        # Le verdict de l'atelier passe AVANT les règles : écarter une fiche
        # n'a pas à attendre que le filtre soit d'accord. Il ne peut en
        # revanche rien OUVRIR — une fiche que les règles tiennent privée le
        # reste, même `retenu` (cf. `collectors/verdict.py`).
        verdict = revue_fiches.get(entity["id"])
        if verdict and ecarte(verdict["statut"]):
            exclusions["entities"]["rejete_en_atelier"] += 1
            entity_exclusions.append({
                "id": entity["id"],
                "type": entity["type"],
                "name": entity["name"],
                "confidence": entity["confidence"],
                "reasons": ["rejete_en_atelier"],
            })
            continue
        item, reasons = public_entity(
            entity,
            confirmed_urls.get(entity["id"], []),
            public_person_ids,
            ids_conseil_communautaire,
        )
        if item is None:
            for reason in reasons:
                exclusions["entities"][reason] += 1
            if (entity["type"] != "person"
                    and all(r.startswith("hors_fiche_perimetre_")
                            for r in reasons)):
                ecartees_du_perimetre.add(entity["id"])
            entity_exclusions.append({
                "id": entity["id"],
                "type": entity["type"],
                "name": entity["name"],
                "confidence": entity["confidence"],
                "reasons": reasons,
            })
            continue
        public_entities.append(item)
        location_quality[item["location_quality"]] += 1

    public_ids = {e["id"] for e in public_entities}

    return {
        "entity_rows": entity_rows,
        "ei_ids": ei_ids,
        "public_entities": public_entities,
        "entity_exclusions": entity_exclusions,
        "ecartees_du_perimetre": ecartees_du_perimetre,
        "location_quality": location_quality,
        "public_ids": public_ids,
    }
