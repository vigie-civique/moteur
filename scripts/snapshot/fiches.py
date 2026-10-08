"""Les fiches publiées : quelles entités sortent, sous quelle forme, et pourquoi les autres non.

L'étape `fiches` lit toutes les entités de la base et rend celles qui ont
droit à une fiche publique (`public_entities`, `public_ids`), et pour les
autres la raison de leur exclusion. Le verdict de l'atelier passe avant les
règles ; le périmètre et les règles de publication font le reste
(`public_entity`).
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

from collectors.verdict import ecarte
from scripts.snapshot.actes import _annee_de_trace
from scripts.snapshot.perimetre import publiable_dans_perimetre
from scripts.snapshot.socle import ROOT, RULES, rows, write_json_compact


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


def ids_retenus_par_un_fait(conn) -> set[int]:
    """Les fiches qu'un fait PUBLIC désigne : de l'argent (flux), un marché, ou
    une mention dans un acte. C'est ce qui retient en ligne un entrepreneur
    individuel qui a cessé son activité (cf. `public_entity`)."""
    return {r["id"] for r in rows(conn, """
        SELECT from_id AS id FROM financial_flows WHERE from_id IS NOT NULL
        UNION SELECT to_id FROM financial_flows WHERE to_id IS NOT NULL
        UNION SELECT titulaire_id FROM marches_publics WHERE titulaire_id IS NOT NULL
        UNION SELECT acheteur_id FROM marches_publics WHERE acheteur_id IS NOT NULL
        UNION SELECT entity_id FROM event_entities WHERE entity_id IS NOT NULL
    """)}


def public_entity(
    row_data: dict,
    urls: list[dict],
    public_person_ids: set[int],
    ids_conseil_communautaire: set[int] = frozenset(),
    ids_retenus: set[int] = frozenset(),
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

    # Un entrepreneur individuel, c'est le NOM d'une personne. En activité, il
    # fait partie de la vie économique qu'on décrit ; son activité cessée, il
    # ne reste que ce nom — publié seulement si de l'argent public, un marché ou
    # un acte le désigne (Julien, 08/10/2026 ; registre des traitements,
    # point 9). La fiche reste en base. `actif` inconnu n'est pas « cessé ».
    if (entity_type == "business"
            and str(row_data.get("legal_form_code") or "") == "1000"
            and etat_activite(row_data)[0] is False
            and row_data["id"] not in ids_retenus):
        return None, ["ei_activite_cessee"]

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


def comptes_syndicats_par_entite(conn) -> dict[int, list[dict]]:
    """Les comptes d'un syndicat, par exercice puis par budget.

    Écrits par `collectors/syndicats_comptes` depuis les balances DGFiP. Deux
    budgets d'un même syndicat (principal, annexe) restent SÉPARÉS : les
    additionner compterait deux fois ce que l'un reverse à l'autre. Une base
    antérieure au 24/09/2026 n'a pas la table — la fiche n'a alors pas d'encart,
    ce qui est exact : rien n'a été collecté.
    """
    try:
        rows = conn.execute(
            "SELECT entity_id, year, budget, libelle_budget, nomenclature, poste,"
            " montant FROM comptes_syndicats WHERE entity_id IS NOT NULL"
            " ORDER BY entity_id, year DESC, budget").fetchall()
    except sqlite3.OperationalError:
        return {}
    par: dict[int, dict[int, dict[str, dict]]] = defaultdict(lambda: defaultdict(dict))
    for r in rows:
        bloc = par[r["entity_id"]][r["year"]].setdefault(r["budget"], {
            "libelle": r["libelle_budget"], "nomenclature": r["nomenclature"],
            "postes": {}})
        bloc["postes"][r["poste"]] = round(r["montant"] or 0)
    return {
        eid: [{"year": an, "budgets": list(budgets.values())}
              for an, budgets in sorted(annees.items(), reverse=True)]
        for eid, annees in par.items()
    }


def write_entity_bundles(out: Path, public_entities, public_relations,
                         public_events, public_links, public_flows,
                         marches_data, comptes_syndicats=None) -> int:
    """Un fichier par acteur : `entite/<id>.json`, tout pré-résolu.

    Avant ça, afficher une fiche imposait de télécharger `entities.json`
    (1,1 Mo) + `events.json` (1 Mo) + `event_links.json` (387 Ko) +
    `relations.json` + `flows.json` + `marches.json` — près de 3 Mo pour lire
    une association, et tout le filtrage fait dans le navigateur. Sur le réseau
    des Cévennes c'est disqualifiant. Chaque bundle fait quelques kilo-octets et
    contient exactement ce que la page affiche.

    Ces fichiers alimentent aussi le prérendu (`+page.server.js`) : le contenu
    part dans le HTML, donc les fiches sont enfin indexables et partageables.
    """
    names = {e["id"]: e["name"] for e in public_entities}
    events_by_id = {e["id"]: e for e in public_events}

    liens_par_entite: dict[int, list[dict]] = defaultdict(list)
    for link in public_links:
        event = events_by_id.get(link["event_id"])
        if event:
            liens_par_entite[link["entity_id"]].append({**event, "role": link["role"]})

    relations_par_entite: dict[int, list[dict]] = defaultdict(list)
    for rel in public_relations:
        for side, autre_id in (("from_id", rel["to_id"]), ("to_id", rel["from_id"])):
            eid = rel[side]
            relations_par_entite[eid].append({
                **rel,
                "autre_id": autre_id,
                "autre": names.get(autre_id),
            })

    flows_par_entite: dict[int, list[dict]] = defaultdict(list)
    for flow in public_flows:
        if flow.get("perimetre") == "agregat":
            continue
        for eid in {flow.get("from_id"), flow.get("to_id")} - {None}:
            flows_par_entite[eid].append(flow)

    marches_par_entite: dict[int, list[dict]] = defaultdict(list)
    for marche in marches_data:
        for eid in {marche.get("titulaire_id"), marche.get("acheteur_id")} - {None}:
            marches_par_entite[eid].append(marche)

    dest = out / "entite"
    dest.mkdir(parents=True, exist_ok=True)

    # PURGE AVANT ÉCRITURE. Sans elle, une entité retirée de la publication
    # gardait sa fiche ici, et la synchro miroir la recopiait fidèlement vers le
    # site : le 19/08/2026, deux sites en ligne servaient des fiches périmées en
    # `/data/entite/<id>.json` — 1 229 sur l'un dont 80 personnes physiques,
    # 9 697 sur l'autre dont 156 — alors que le filtre les avait écartées.
    # Personne ne le voyait, parce que la page HTML de ces entités rendait bien
    # 404 : seul le fichier de données restait accessible. Écrire par-dessus ne
    # suffit pas, il faut retirer ce qui ne doit plus sortir.
    attendus = {f"{e['id']}.json" for e in public_entities}
    perimees = [f for f in dest.glob("*.json") if f.name not in attendus]
    for f in perimees:
        f.unlink()
    if perimees:
        print(f"   {len(perimees)} fiche(s) périmée(s) retirée(s) de {dest.name}/")

    for entity in public_entities:
        eid = entity["id"]
        write_json_compact(dest / f"{eid}.json", {
            "entity": entity,
            "relations": relations_par_entite.get(eid, []),
            "liens": sorted(liens_par_entite.get(eid, []),
                            key=lambda e: (e.get("date") or ""), reverse=True),
            "flows": sorted(flows_par_entite.get(eid, []),
                            key=lambda f: (f.get("year") or 0), reverse=True),
            "marches": marches_par_entite.get(eid, []),
            **({"comptes_syndicat": (comptes_syndicats or {})[eid]}
               if eid in (comptes_syndicats or {}) else {}),
        })
    return len(public_entities)


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
    ids_retenus = ids_retenus_par_un_fait(conn)
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
            ids_retenus,
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


def etape_couches(public_entities) -> dict:
    """Les points de la carte, une couche par type d'acteur localisé.

    Chaque point emporte une COPIE des propriétés de sa fiche, prise ici :
    ce qu'une étape ajoute aux fiches plus tard (`citations`) n'entre pas dans
    les couches. C'est la sortie telle qu'elle a toujours été ; l'ordre du
    registre la garde.
    """
    public_layers = {
        "businesses": [],
        "associations": [],
        "places": [],
        "services": [],
    }
    for entity in public_entities:
        if not entity.get("has_public_location"):
            continue
        layer_key = {
            "business": "businesses",
            "association": "associations",
            "place": "places",
            "service": "services",
        }.get(entity["type"])
        if not layer_key:
            continue
        public_layers[layer_key].append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [entity["lng"], entity["lat"]]},
            "properties": {k: v for k, v in entity.items() if k not in {"lat", "lng"}},
        })

    return {"public_layers": public_layers}


def etape_citations(public_events, public_links, public_relations, public_flows,
                    marches_data, public_entities, stats) -> None:
    """Ce que les actes, liens, flux et marchés publiés disent de chaque fiche :
    combien de fois elle y est citée, et l'année de sa dernière trace. Écrit
    dans les fiches en place, et compté dans `stats`."""
    # ── Citations : l'acteur est-il nommé dans un acte public ? ───────────
    # « Cité » = nommé dans une décision publique : délibération, conseil,
    # marché, autorisation d'urbanisme, flux financier, mandat. Les ~1 800
    # entreprises importées de SIRENE n'y figurent pas et noyaient la page
    # publique (2 700 cartes à parcourir à l'œil). Tout le répertoire reste
    # publié, mais le compteur permet de mettre en avant ce qui est documenté.
    #
    # Les annonces BODACC (dépôts de comptes, immatriculations…) sont
    # exclues : purement déclaratives, elles font remonter n'importe quelle
    # société ayant déposé ses comptes devant les associations subventionnées.
    events_by_id_all = {e["id"]: e for e in public_events}
    citations = Counter()
    for lien in public_links:
        ev = events_by_id_all.get(lien["event_id"])
        if not ev or str(ev.get("type", "")).startswith("bodacc"):
            continue
        citations[lien["entity_id"]] += 1
    for source, paires in (
        (public_relations, ("from_id", "to_id")),
        (public_flows, ("from_id", "to_id")),
        (marches_data, ("acheteur_id", "titulaire_id")),
    ):
        for row in source:
            for eid in {row.get(k) for k in paires} - {None}:
                citations[eid] += 1
    # ── Dernière trace publique ──────────────────────────────────────────
    #
    # 28 associations et 92 entreprises de Lasalle ont des registres MUETS :
    # ni cessées ni dissoutes, mais rien ne dit non plus qu'elles vivent.
    # Une association qui a cessé de se réunir sans déclarer sa dissolution
    # reste « A » au Journal officiel pour toujours — le registre ne
    # l'apprend jamais.
    #
    # Ce qu'on peut dire sans rien inventer : LA DERNIÈRE FOIS QU'UNE SOURCE
    # PUBLIQUE L'A NOMMÉE. Ce n'est pas un verdict de dormance, c'est un
    # fait daté, et il laisse le lecteur conclure — « dernière trace : 2014 »
    # se lit tout seul.
    #
    # À la différence des citations, les annonces BODACC comptent ici : une
    # radiation de 2019 est une trace, et c'est même la plus parlante.
    #
    # L'ANNÉE, et pas la date : un flux financier n'a que son millésime.
    # Lui donner un jour le ferait passer pour plus précis qu'il n'est, et
    # un acteur documenté par un seul flux paraîtrait plus récent qu'un
    # acteur cité dans une délibération du même exercice.
    traces: dict[int, int] = {}
    _annee = _annee_de_trace

    def _tracer(eid, an):
        if eid and an and an > traces.get(eid, 0):
            traces[eid] = an

    for lien in public_links:
        ev = events_by_id_all.get(lien["event_id"])
        if ev:
            _tracer(lien["entity_id"], _annee(ev.get("date")))
    for rel in public_relations:
        for champ in ("since", "until"):
            for eid in (rel.get("from_id"), rel.get("to_id")):
                _tracer(eid, _annee(rel.get(champ)))
    for flux in public_flows:
        for eid in (flux.get("from_id"), flux.get("to_id")):
            _tracer(eid, _annee(flux.get("year")))
    for marche in marches_data:
        for eid in (marche.get("acheteur_id"), marche.get("titulaire_id")):
            _tracer(eid, _annee(marche.get("date_notif")))

    for e in public_entities:
        e["citations"] = citations.get(e["id"], 0)
        e["derniere_trace"] = traces.get(e["id"])
    stats["entities_cited"] = sum(1 for e in public_entities if e["citations"])
    # Ce que les registres taisent, et depuis quand la source publique
    # s'est tue. Publié pour que la lacune se mesure au lieu de se deviner.
    muettes = [e for e in public_entities
               if e["type"] in ("business", "association") and e.get("actif") is None]
    stats["entities_registres_muets"] = {
        "total": len(muettes),
        "sans_aucune_trace": sum(1 for e in muettes if not e.get("derniere_trace")),
        "par_derniere_trace": dict(sorted(Counter(
            e.get("derniere_trace") for e in muettes if e.get("derniere_trace")
        ).items(), reverse=True)),
    }


def etape_fiches_acteurs(conn, out, public_entities, public_relations, public_events,
                         public_links, public_flows, marches_data) -> dict:
    """Un fichier par fiche publiée, tout pré-résolu ; les fiches retirées sortent."""
    bundles = write_entity_bundles(out, public_entities, public_relations,
                                   public_events, public_links, public_flows,
                                   marches_data,
                                   comptes_syndicats_par_entite(conn))
    return {"bundles": bundles}
