"""L'export Popolo : les mandats publiés, dans un vocabulaire que d'autres parlent.

Le pourquoi de cet export est écrit là où il est produit, dans l'étape qui
écrit `popolo.json` ; ce module porte la correspondance entre nos types de
relation et Popolo, et la construction du document. `POPOLO_ROLES` sert aussi
au masquage des noms : un mandat, même clos, fait d'une personne une personne
publique (cf. `scripts/snapshot/textes.py`).
"""
from __future__ import annotations

from datetime import datetime

from scripts.snapshot.socle import RULES, write_json


# ── Popolo ───────────────────────────────────────────────────────────────────
# Correspondance entre nos types de relation et le vocabulaire Popolo. Seuls
# les MANDATS deviennent des `Membership` : un mandat est bien « une personne,
# dans une organisation, avec un rôle, entre deux dates », ce que Popolo décrit
# exactement. Les liens économiques (subventionné, prestataire, bail) n'entrent
# pas dans ce moule — ce ne sont pas des appartenances — et restent dans
# `relations.json` et `flows.json`.
POPOLO_ROLES = {
    "maire":             "Maire",
    "adjoint":           "Adjoint au maire",
    "élu_cm":            "Conseiller municipal",
    "élu_cc":            "Conseiller communautaire",
    "président_cc":      "Président du conseil communautaire",
    "vice_président_cc": "Vice-président du conseil communautaire",
    "membre_commission": "Membre de commission",
    "candidat":          "Candidat",
}
# Nos six types d'entités vers la dichotomie Popolo. Popolo ne connaît que
# `Person` et `Organization` : un lieu ou une parcelle n'y a pas sa place, ils
# sont donc absents de cet export (ils restent dans `entities.json` et les
# couches GeoJSON).
POPOLO_ORG_CLASS = {
    "service":     "public_body",
    "association": "association",
    "business":    "company",
}


def build_popolo(entities: list[dict], relations: list[dict],
                 rules: dict = RULES, horloge: datetime | None = None) -> dict:
    """Vue Popolo des mandats publiés — personnes, organisations, appartenances.

    Ne recalcule aucun filtrage : on part des listes DÉJÀ filtrées pour la
    publication. Toute règle RGPD ou de confidence appliquée en amont vaut donc
    ici sans avoir à être répétée — et ne peut pas diverger.
    """
    par_id = {e["id"]: e for e in entities}

    persons, organizations = [], []
    for e in entities:
        if e["type"] == "person":
            persons.append({
                "id": f"person/{e['id']}",
                "name": e["name"],
                # `sort_name` : Popolo prévoit le nom de tri séparément du nom
                # d'affichage. On n'a pas de découpage nom/prénom fiable pour
                # toutes les personnes, on ne l'invente pas.
                "identifiers": [{"scheme": "vigie-civique", "identifier": str(e["id"])}],
                "links": [{"url": u} for u in (e.get("urls") or []) if u],
            })
        elif e["type"] in POPOLO_ORG_CLASS:
            organizations.append({
                "id": f"organization/{e['id']}",
                "name": e["name"],
                "other_names": ([{"name": e["short_name"]}] if e.get("short_name") else []),
                "classification": POPOLO_ORG_CLASS[e["type"]],
                "area_id": f"area/{e['commune']}" if e.get("commune") else None,
                "founding_date": e.get("creation_date"),
                "identifiers": (
                    [{"scheme": "vigie-civique", "identifier": str(e["id"])}]
                    + ([{"scheme": "RNA", "identifier": e["rna_id"]}] if e.get("rna_id") else [])
                ),
                "links": [{"url": u} for u in (e.get("urls") or []) if u],
            })

    memberships = []
    for r in relations:
        role = POPOLO_ROLES.get(r["relation_type"])
        if role is None:
            continue
        source, cible = par_id.get(r["from_id"]), par_id.get(r["to_id"])
        if not source or not cible:
            continue
        if source["type"] != "person" or cible["type"] not in POPOLO_ORG_CLASS:
            continue
        memberships.append({
            "id": f"membership/{r['id']}",
            "person_id": f"person/{r['from_id']}",
            "organization_id": f"organization/{r['to_id']}",
            "role": role,
            "start_date": r.get("since"),
            "end_date": r.get("until"),
            # Hors spec Popolo, mais c'est la colonne vertébrale du projet :
            # aucune affirmation n'est publiée sans sa source ni son niveau de
            # certitude. Les retirer pour rester canonique appauvrirait
            # l'export de ce qui en fait la valeur.
            "sources": [{"note": r["source"]}] if r.get("source") else [],
            "vigie_confidence": r.get("confidence"),
        })

    areas = sorted({e["commune"] for e in entities if e.get("commune")})
    return {
        "@context": "https://www.popoloproject.com/contexts/organization.jsonld",
        "generated_at": (horloge or datetime.now()).isoformat(timespec="seconds"),
        # Licence et attributions : lues dans la config, jamais écrites ici.
        # Le raisonnement qui a conduit à l'ODbL est consigné dans
        # `config/publication_rules.json → outputs._license_note`.
        "license": rules["outputs"]["license"],
        "license_url": rules["outputs"]["license_url"],
        "attribution": rules["outputs"]["attribution"],
        "source_attributions": rules["outputs"]["source_attributions"],
        "note": (
            "Vue Popolo (popoloproject.com) des mandats publiés. Sous-ensemble "
            "de entities.json et relations.json, exporté dans un vocabulaire "
            "partagé pour être réutilisable hors de ce projet. Les liens "
            "économiques et les lieux n'entrent pas dans ce modèle et restent "
            "dans les fichiers d'origine. Pas de VoteEvent : les "
            "procès-verbaux publiés ne donnent pas les votes nominatifs."
        ),
        "persons": persons,
        "organizations": organizations,
        "memberships": memberships,
        "areas": [{"id": f"area/{a}", "name": a, "classification": "commune"}
                  for a in areas],
    }


def etape_popolo(out, public_entities, public_relations, horloge) -> None:
    # ── Export Popolo — l'interopérabilité, pas un doublon ────────────────
    # Popolo (popoloproject.com) est le vocabulaire commun des projets de
    # transparence parlementaire et municipale : Open Civic Data (le
    # standard derrière Councilmatic à Chicago, NYC et Philadelphie),
    # EveryPolitician, mySociety. Il décrit exactement ce que cette base
    # contient déjà — des personnes, des organisations, et des mandats
    # datés qui relient les deux.
    #
    # Pourquoi l'exporter en plus de `entities.json` : nos noms de champs
    # (`from_id`, `relation_type`, `since`) ne veulent rien dire hors du
    # projet. Un chercheur ou une autre commune qui veut comparer doit
    # d'abord lire notre code. En Popolo, `memberships[].person_id` et
    # `start_date` se lisent sans documentation, et les outils existants
    # consomment le fichier tel quel. C'est la contrepartie de l'objectif
    # de réplication : un modèle qui s'exporte doit sortir dans un format
    # que d'autres parlent déjà.
    #
    # Ce qui n'y est PAS : les votes nominatifs (`VoteEvent`/`Vote`). Les
    # procès-verbaux publiés ne donnent pas le détail des votes par élu, et
    # inventer un `Vote` à partir d'un « adopté à l'unanimité » serait une
    # affirmation que la source ne porte pas. Le jour où les PV nominatifs
    # existeront, la classe s'ajoute sans toucher au reste.
    write_json(out / "popolo.json", build_popolo(
        public_entities, public_relations, RULES, horloge))
