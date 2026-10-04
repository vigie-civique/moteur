"""L'ordre de fabrication du snapshot, déclaré une fois.

Chaque ligne dit quelle fonction tourne, ce qu'elle lit, ce qu'elle modifie en
place, ce qu'elle produit et quels fichiers elle écrit (cf.
`scripts/snapshot/registre.py`). `build_snapshot()` n'a plus qu'à exécuter
cette liste ; le manifeste du snapshot pourra dire, pour chaque fichier, quelle
étape l'a écrit.
"""
from __future__ import annotations

from scripts.snapshot.actes import etape_actes, etape_cles_actes, etape_liens_actes
from scripts.snapshot.argent import etape_flux
from scripts.snapshot.fiches import etape_couches, etape_fiches
from scripts.snapshot.perimetre import etape_perimetre
from scripts.snapshot.personnes import etape_personnes_publiques
from scripts.snapshot.registre import Etape
from scripts.snapshot.relations import etape_relations
from scripts.snapshot.revue import etape_revue

#: Les faits que `build_snapshot()` donne à la première étape : la connexion
#: (lecture seule), le répertoire de sortie, l'heure de la construction, et le
#: relevé des exclusions — ce que chaque filtre a écarté et pourquoi, que les
#: étapes complètent au fil de l'eau et que `stats.json` publie.
FOURNIS = ("conn", "out", "horloge", "exclusions")

ETAPES: list[Etape] = [
    Etape("perimetre", etape_perimetre,
          lit=("conn",), produit=("sans_perimetre",)),
    Etape("revue", etape_revue,
          lit=("conn",), produit=("revue", "revue_annotations", "relations_ecartees")),
    Etape("personnes_publiques", etape_personnes_publiques,
          lit=("conn", "relations_ecartees"),
          produit=("civic_person_ids", "beneficiaires", "public_person_ids",
                   "redige", "redactions", "noms_publics", "ids_conseil_communautaire")),
    Etape("fiches", etape_fiches,
          lit=("conn", "revue", "public_person_ids", "ids_conseil_communautaire"),
          complete=("exclusions",),
          produit=("entity_rows", "ei_ids", "public_entities", "entity_exclusions",
                   "ecartees_du_perimetre", "location_quality", "public_ids")),
    Etape("relations", etape_relations,
          lit=("conn", "revue", "public_ids", "civic_person_ids", "beneficiaires", "ei_ids"),
          complete=("exclusions",),
          produit=("relation_rows", "public_relations", "relation_exclusions")),
    Etape("actes", etape_actes,
          lit=("conn", "revue", "noms_publics", "redige"),
          complete=("exclusions",),
          produit=("event_rows", "public_events", "event_exclusions",
                   "textes_extraits", "masquages")),
    # Après les liens, la portée : un acte sans type d'assemblée connu a besoin
    # de ses acteurs pour dire de qui il parle. L'étape l'écrit dans chaque
    # acte publié.
    Etape("liens_actes", etape_liens_actes,
          lit=("conn", "public_ids", "public_entities"),
          complete=("public_events", "exclusions"),
          produit=("public_links", "perimetre_par_entite")),
    # La clé datée de chaque acte publié, son ancre, et l'index que le graphe
    # des liens résoudra. Écrites dans les actes en place.
    Etape("cles_actes", etape_cles_actes,
          lit=("conn",), complete=("public_events",),
          produit=("index_actes", "affiches", "cles_stats")),
    Etape("flux", etape_flux,
          lit=("conn", "revue", "entity_rows", "public_person_ids", "public_ids",
               "ecartees_du_perimetre", "redige"),
          complete=("exclusions",),
          produit=("flow_rows", "public_flows", "flows_par_etat")),
    # AVANT `citations` : les couches copient les fiches telles qu'elles sont.
    Etape("couches", etape_couches,
          lit=("public_entities",), produit=("public_layers",)),
]
