"""L'ordre de fabrication du snapshot, déclaré une fois.

Chaque ligne dit quelle fonction tourne, ce qu'elle lit, ce qu'elle modifie en
place, ce qu'elle produit et quels fichiers elle écrit (cf.
`scripts/snapshot/registre.py`). `build_snapshot()` n'a plus qu'à exécuter
cette liste ; le manifeste du snapshot pourra dire, pour chaque fichier, quelle
étape l'a écrit.
"""
from __future__ import annotations

from scripts.snapshot.actes import etape_actes, etape_cles_actes, etape_liens_actes
from scripts.snapshot.actualite import etape_actualite
from scripts.snapshot.argent import etape_finances, etape_flux
from scripts.snapshot.compteurs import etape_compteurs
from scripts.snapshot.couverture import etape_compteurs_provisoires, etape_couverture
from scripts.snapshot.democratie import etape_elections, etape_elus, etape_intercommunalite
from scripts.snapshot.ecritures import (COUCHES, etape_ecrire_actes, etape_ecrire_acteurs,
                                        etape_ecrire_couches, etape_ecrire_finances,
                                        etape_ecrire_flux)
from scripts.snapshot.fiches import etape_citations, etape_couches, etape_fiches
from scripts.snapshot.perimetre import etape_perimetre
from scripts.snapshot.personnes import etape_personnes_publiques
from scripts.snapshot.popolo import etape_popolo
from scripts.snapshot.registre import Etape
from scripts.snapshot.relations import etape_relations
from scripts.snapshot.revue import etape_revue
from scripts.snapshot.territoire import etape_environnement, etape_fiscalite, etape_territoire
from scripts.snapshot.urbanisme import etape_croisement_foncier, etape_urbanisme

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
    Etape("finances", etape_finances,
          lit=("conn", "revue", "public_ids", "perimetre_par_entite"),
          complete=("exclusions",),
          produit=("budget_annuel", "budget_annexe", "ofgl_data", "budget_vote",
                   "dvf_data", "marches_data", "approbations_data")),
    # Tout est sélectionné : les compteurs de `stats.json` se calculent. Le
    # relevé des exclusions y est recopié tel qu'il est à ce moment-là.
    Etape("compteurs", etape_compteurs,
          lit=("conn", "horloge", "sans_perimetre", "entity_rows", "public_entities",
               "ids_conseil_communautaire", "relation_rows", "public_relations",
               "event_rows", "public_events", "flow_rows", "public_flows",
               "flows_par_etat", "budget_annuel", "budget_annexe", "ofgl_data",
               "dvf_data", "marches_data", "approbations_data", "public_layers",
               "location_quality", "exclusions"),
          produit=("stats",)),
    # APRÈS `couches` : ce que l'étape ajoute aux fiches n'entre pas dans la carte.
    Etape("citations", etape_citations,
          lit=("public_events", "public_links", "public_relations", "public_flows",
               "marches_data"),
          complete=("public_entities", "stats")),
    # Le premier fichier écrit. L'étape `stats` le réécrit en dernier : c'est
    # elle qui le déclare.
    Etape("compteurs_provisoires", etape_compteurs_provisoires,
          lit=("out", "stats")),
    Etape("couverture", etape_couverture,
          lit=("conn", "out", "public_events", "stats"), ecrit=("couverture.json",)),
    Etape("ecrire_acteurs", etape_ecrire_acteurs,
          lit=("out", "public_entities", "public_relations"),
          ecrit=("entities.json", "relations.json")),
    Etape("ecrire_actes", etape_ecrire_actes,
          lit=("out", "public_events", "public_links"),
          ecrit=("events.json", "event_links.json")),
    Etape("ecrire_flux", etape_ecrire_flux,
          lit=("out", "public_flows"), ecrit=("flows.json",)),
    Etape("ecrire_couches", etape_ecrire_couches,
          lit=("out", "public_layers"),
          ecrit=tuple(f"layers/{c}.geojson" for c in COUCHES)),
    Etape("ecrire_finances", etape_ecrire_finances,
          lit=("out", "budget_annuel", "budget_annexe", "budget_vote", "ofgl_data",
               "dvf_data", "marches_data", "approbations_data"),
          ecrit=("budget.json", "budget_vote.json", "ofgl.json", "dvf.json",
                 "marches.json", "approbations.json")),
    Etape("environnement", etape_environnement,
          lit=("conn", "out"), ecrit=("environnement.json",)),
    Etape("territoire", etape_territoire,
          lit=("conn", "out"), ecrit=("territoire.json",)),
    Etape("popolo", etape_popolo,
          lit=("out", "public_entities", "public_relations", "horloge"),
          ecrit=("popolo.json",)),
    Etape("elections", etape_elections,
          lit=("conn", "out"), produit=("elections",), ecrit=("elections.json",)),
    Etape("fiscalite", etape_fiscalite,
          lit=("conn", "out"), produit=("fiscalite",), ecrit=("fiscalite.json",)),
    Etape("intercommunalite", etape_intercommunalite,
          lit=("conn", "out", "horloge"), ecrit=("intercommunalite.json",)),
    Etape("elus", etape_elus,
          lit=("conn", "out", "public_ids"), produit=("elus",), ecrit=("elus_rne.json",)),
    Etape("urbanisme", etape_urbanisme,
          lit=("conn", "out", "public_ids"),
          produit=("urbanisme_public", "adresses_retirees"), ecrit=("urbanisme.json",)),
    Etape("croisement_foncier", etape_croisement_foncier,
          lit=("conn", "out"), produit=("croisement_foncier",),
          ecrit=("croisement_foncier.json",)),
    Etape("actualite", etape_actualite,
          lit=("out", "stats", "marches_data", "public_events", "public_flows",
               "perimetre_par_entite"),
          complete=("exclusions",),
          produit=("actualite", "a_venir"), ecrit=("actualite.json",)),
]
