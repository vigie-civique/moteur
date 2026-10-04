"""Les personnes publiques : qui peut être nommé, et à quel titre.

Une personne physique n'a de fiche que si elle tient un rôle civique (mandat,
candidature, commission) ou si elle dirige une structure qui a reçu de
l'argent public — la règle de pertinence. Tout le reste du snapshot en dépend :
la sélection des fiches, le masquage des noms de particuliers dans les titres
et les flux, et la liste des noms qu'un texte d'acte peut citer.
"""
from __future__ import annotations

from scripts.snapshot.socle import RULES, rows, table_exists
from scripts.snapshot.textes import compilateur_redaction, noms_des_personnes_publiques

#: Une relation que l'atelier a écartée ne justifie plus rien : ajouté aux
#: requêtes qui rendent une personne publiable, avec la liste JSON des
#: relations écartées (`relations_ecartees`, cf. l'étape `revue`).
pas_ecartee = "AND r.id NOT IN (SELECT value FROM json_each(?))"


def beneficiaires_argent_public(conn) -> set[int]:
    """Entités ayant reçu de l'argent public : subvention, marché, bail.

    Base de la règle de pertinence : le lien économique d'une personne avec une
    structure qui touche de l'argent public est d'intérêt général, celui avec une
    société sans rapport avec la commune ne l'est pas.

    Les flux sont sommés sur `perimetre='detail'` seulement, demandes et
    annulations écartées : les agrégats OFGL englobent la DGF présente en détail
    (double compte), et `statut='demande'` désigne une subvention **sollicitée**,
    pas obtenue. Le filtre nommait la valeur retenue (`= 'realise'`) plutôt que
    celles qu'il écarte — étendre la liste des statuts saisissables l'aurait
    vidé sans un mot d'erreur.
    """
    ids: set[int] = set()
    for r in rows(conn, """
        SELECT DISTINCT to_id AS id FROM financial_flows
         WHERE to_id IS NOT NULL
           AND COALESCE(perimetre,'detail') = 'detail'
           AND COALESCE(statut,'realise') NOT IN ('demande','annule')
    """):
        ids.add(r["id"])
    if table_exists(conn, "marches_publics"):
        for r in rows(conn, "SELECT DISTINCT titulaire_id AS id FROM marches_publics"
                            " WHERE titulaire_id IS NOT NULL"):
            ids.add(r["id"])
    types = sorted(RULES["relations"]["public_money_relation_types"])
    for r in rows(conn, f"""
        SELECT DISTINCT from_id AS a, to_id AS b FROM relations
         WHERE relation_type IN ({",".join("?" for _ in types)})
           AND confidence IN ({",".join("?" for _ in RULES["confidence"]["public"])})
    """, [*types, *sorted(RULES["confidence"]["public"])]):
        ids.update({r["a"], r["b"]} - {None})
    return ids


def etape_personnes_publiques(conn, relations_ecartees) -> dict:
    # 1) Personnes à rôle civique : élus, candidats, membres de commission.
    civic_person_ids = {
        r["entity_id"] for r in rows(conn, f"""
            SELECT DISTINCT e.id AS entity_id
            FROM entities e
            JOIN relations r ON r.from_id = e.id OR r.to_id = e.id
            WHERE e.type = 'person'
              AND e.confidence IN ({",".join("?" for _ in RULES["confidence"]["public"])})
              AND r.confidence IN ({",".join("?" for _ in RULES["confidence"]["public"])})
              AND r.relation_type IN ({",".join("?" for _ in RULES["people"]["publish_only_with_relation_types"])})
              {pas_ecartee}
        """, [
            *sorted(RULES["confidence"]["public"]),
            *sorted(RULES["confidence"]["public"]),
            *sorted(RULES["people"]["publish_only_with_relation_types"]),
            relations_ecartees,
        ])
    }

    # 2) Règle de pertinence (arbitrage du 26/07/2026) : une personne devient
    # publiable si elle dirige une structure ayant reçu de l'argent public.
    # Publier « qui a touché » sans pouvoir dire « qui la dirige » n'informe
    # personne ; à l'inverse, le gérant d'une société sans lien avec la
    # commune reste privé.
    beneficiaires = beneficiaires_argent_public(conn)
    eco_types = sorted(RULES["relations"].get("relevance_allowlist", []))
    pertinent_person_ids: set[int] = set()
    if eco_types and beneficiaires:
        marks = ",".join("?" for _ in eco_types)
        benes = ",".join("?" for _ in beneficiaires)
        pertinent_person_ids = {
            r["entity_id"] for r in rows(conn, f"""
                SELECT DISTINCT e.id AS entity_id
                FROM entities e
                JOIN relations r ON r.from_id = e.id OR r.to_id = e.id
                WHERE e.type = 'person'
                  AND e.confidence IN ({",".join("?" for _ in RULES["confidence"]["public"])})
                  AND r.confidence IN ({",".join("?" for _ in RULES["confidence"]["public"])})
                  AND r.relation_type IN ({marks})
                  AND (r.from_id IN ({benes}) OR r.to_id IN ({benes}))
                  AND r.from_id NOT IN (SELECT entity_id FROM businesses
                                         WHERE legal_form_code = '1000')
                  AND r.to_id   NOT IN (SELECT entity_id FROM businesses
                                         WHERE legal_form_code = '1000')
                  {pas_ecartee}
            """, [
                *sorted(RULES["confidence"]["public"]),
                *sorted(RULES["confidence"]["public"]),
                *eco_types,
                *sorted(beneficiaires), *sorted(beneficiaires),
                relations_ecartees,
            ])
        }

    public_person_ids = civic_person_ids | pertinent_person_ids
    redige, redactions = compilateur_redaction(conn, public_person_ids)
    noms_publics = noms_des_personnes_publiques(conn, public_person_ids)

    # Ceux qui siègent au conseil communautaire : seules personnes des
    # communes C2 publiables en fiche (cf. `publiable_dans_perimetre`).
    ids_conseil_communautaire = {
        r["entity_id"] for r in rows(conn, f"""
            SELECT DISTINCT from_id AS entity_id FROM relations r
            WHERE relation_type IN ('élu_cc','vice_président_cc','président_cc')
              AND confidence IN ('verified','confirmed')
              {pas_ecartee}
        """, [relations_ecartees])
    }

    # Calculés de tout temps, jamais publiés : ils restent lisibles ici pour
    # qui voudrait les publier un jour (`persons_civic`,
    # `persons_par_pertinence`, `beneficiaires_argent_public`).
    return {
        "civic_person_ids": civic_person_ids,
        "beneficiaires": beneficiaires,
        "public_person_ids": public_person_ids,
        "redige": redige,
        "redactions": redactions,
        "noms_publics": noms_publics,
        "ids_conseil_communautaire": ids_conseil_communautaire,
    }
