"""Les relations publiées : quels liens entre acteurs sortent, avec quoi.

Un lien ne sort que si ses deux extrémités sont publiées, si son type est
admis et, pour un lien économique, s'il a un rapport avec l'action publique
(`relation_pertinente`). De ses métadonnées, seule une liste blanche sort
(`relation_meta_publique`).
"""
from __future__ import annotations

import json

from collectors.verdict import ecarte
from scripts.snapshot.socle import RULES, rows
from scripts.snapshot.textes import champ_publiable, norm_nom


# Seules clés de `relations.metadata` publiables : elles qualifient le lien
# lui-même (« responsable » de la commission, « volet agricole ») et rien de la
# personne. Le reste du bloc porte des données de travail — nom complet,
# année de naissance, notes d'enquête — qui ne sortent pas.
# Liste blanche : rien d'autre ne sort des métadonnées d'une relation.
#
# Deux champs y manquaient alors que le code les lisait déjà : `fonction_rne`
# (la fonction telle que le Répertoire National des Élus l'écrit — le code
# retombait donc toujours sur son libellé par défaut, sans le savoir) et
# `etat_au` (la date à laquelle la source a arrêté son état, sur laquelle
# repose le tri entre mandature en cours et mandature précédente). Une liste
# blanche protège, mais elle rend `None` en silence : ce qu'elle omet n'a pas
# l'air absent, il a l'air vide.
RELATION_META_PUBLIQUE = ("role", "precision", "fonction_rne", "etat_au")


def relation_meta_publique(brut: str | None, noms_publics: set[str] | None = None) -> dict:
    """Les métadonnées d'un lien qui peuvent sortir.

    Avec `noms_publics`, les valeurs passent par le masque : `role` et
    `precision` sont du texte libre, saisi ou extrait.
    """
    if not brut:
        return {}
    try:
        meta = json.loads(brut)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(meta, dict):
        return {}
    publiques = {k: meta[k] for k in RELATION_META_PUBLIQUE
                 if isinstance(meta.get(k), str)}
    if noms_publics is None:
        return publiques
    return {k: champ_publiable(v, None, noms_publics) for k, v in publiques.items()}


def relation_pertinente(rel: dict, civic_ids: set[int],
                        beneficiaires: set[int],
                        ei_ids: set[int] | None = None) -> bool:
    """Un lien économique a-t-il un rapport avec l'action publique ?

    Vrai si une extrémité est un acteur civique (élu, candidat — ses intérêts
    économiques relèvent de la déclaration d'intérêts), ou si une extrémité a
    reçu de l'argent public (on publie alors qui dirige la structure payée).

    Exception : les **entreprises individuelles**. Une EI n'est pas une personne
    morale distincte de son exploitant : « Prénom NOM dirige PRENOM NOM » est
    une tautologie issue de SIRENE, qui n'informe personne et re-expose un
    particulier. Le projet traite déjà l'EI comme une donnée personnelle
    (679 domiciles masqués sur la carte) ; on reste cohérent.

    Deux détections, parce qu'aucune ne suffit seule :
      - forme juridique 1000 (907 entités) ;
      - **même nom normalisé aux deux bouts** — indispensable car 10 entités ont
        un `legal_form_code` NULL (l'enrichissement SIRENE ne l'a pas rempli) et
        passaient donc le premier filtre : « Prénom NOM → PRENOM NOM »,
        « Philippe BRISSAC → PHILIPPE BRISSAC »…
    """
    bouts = {rel.get("from_id"), rel.get("to_id")} - {None}
    if ei_ids and bouts & ei_ids:
        return False
    if norm_nom(rel.get("from_name")) == norm_nom(rel.get("to_name")):
        return False
    return bool(bouts & civic_ids) or bool(bouts & beneficiaires)


def sort_du_type(relation_type: str | None) -> str:
    """Ce qu'un TYPE de lien peut devenir, indépendamment de ses extrémités.

    Trois réponses : `prive` (il ne sort jamais), `public` (il sort si ses
    extrémités le permettent), `selon_pertinence` (lien économique, jugé au cas
    par cas). Extrait de `is_public_relation` le 23/09/2026, qui l'appelle
    désormais — l'atelier en a besoin pour dire à un bénévole ce que son geste
    changera, et deux lectures de la même règle finiraient par se contredire.

    ⚖️ Le défaut est PRIVÉ. Un type absent des trois listes ne sort pas : c'est
    ce qui a évité une fuite quand le détecteur de liens a été câblé et s'est
    mis à proposer `même_personne_probable`, qu'aucun marqueur ne visait.
    """
    t = relation_type or ""
    if any(marker in t for marker in RULES["relations"]["private_markers"]):
        return "prive"
    if t in set(RULES["relations"]["public_allowlist"]):
        return "public"
    if t in set(RULES["relations"].get("relevance_allowlist", [])):
        return "selon_pertinence"
    return "prive"


def is_public_relation(rel: dict, public_ids: set[int],
                       civic_ids: set[int] | None = None,
                       beneficiaires: set[int] | None = None,
                       ei_ids: set[int] | None = None) -> tuple[bool, str]:
    if rel.get("confidence") not in set(RULES["confidence"]["public"]):
        return False, "private_confidence"
    if rel["from_id"] not in public_ids or rel["to_id"] not in public_ids:
        return False, "endpoint_not_public"
    relation_type = rel.get("relation_type") or ""
    sort = sort_du_type(relation_type)
    if sort == "public":
        return True, "public"
    # Liens économiques : publiés au cas par cas selon la pertinence, pas par type.
    if sort == "selon_pertinence":
        if relation_pertinente(rel, civic_ids or set(), beneficiaires or set(),
                               ei_ids or set()):
            return True, "public_par_pertinence"
        return False, "economique_sans_lien_public"
    # `prive` : soit un marqueur le vise, soit aucune liste ne l'admet. Les deux
    # motifs restent distingués — l'un est une décision, l'autre un défaut.
    if any(marker in relation_type for marker in RULES["relations"]["private_markers"]):
        return False, "private_relation_type"
    return False, "not_in_public_allowlist"


def etape_relations(conn, revue, public_ids, civic_person_ids, beneficiaires,
                    ei_ids, noms_publics, exclusions) -> dict:
    relation_rows = rows(conn, """
        SELECT r.id, r.from_id, r.to_id, r.relation_type, r.since, r.until,
               r.source, r.confidence, r.metadata,
               f.name AS from_name, t.name AS to_name
        FROM relations r
        LEFT JOIN entities f ON f.id = r.from_id
        LEFT JOIN entities t ON t.id = r.to_id
        ORDER BY r.id
    """)
    public_relations: list[dict] = []
    relation_exclusions: list[dict] = []
    revue_relations = revue.get("relation", {})
    for rel in relation_rows:
        verdict = revue_relations.get(rel["id"])
        if verdict and ecarte(verdict["statut"]):
            ok, reason = False, "rejete_en_atelier"
        else:
            ok, reason = is_public_relation(rel, public_ids,
                                            civic_person_ids, beneficiaires,
                                            ei_ids)
        if not ok:
            exclusions["relations"][reason] += 1
            relation_exclusions.append({
                "id": rel["id"],
                "from_id": rel["from_id"],
                "to_id": rel["to_id"],
                "relation_type": rel["relation_type"],
                "confidence": rel["confidence"],
                "source": rel["source"],
                "reason": reason,
            })
            continue
        public_relations.append({
            "id": rel["id"],
            "from_id": rel["from_id"],
            "to_id": rel["to_id"],
            "relation_type": rel["relation_type"],
            "since": rel["since"],
            "until": rel["until"],
            "source": rel["source"],
            "confidence": rel["confidence"],
            "from_name": rel["from_name"],
            "to_name": rel["to_name"],
            # `relations.metadata` sert de fourre-tout aux collecteurs : on
            # y trouve aussi bien un rôle en commission qu'une année de
            # naissance. Liste blanche stricte, jamais le bloc entier.
            **relation_meta_publique(rel.get("metadata"), noms_publics),
        })

    return {
        "relation_rows": relation_rows,
        "public_relations": public_relations,
        "relation_exclusions": relation_exclusions,
    }
