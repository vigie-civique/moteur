"""L'ordre de fabrication du snapshot, déclaré une fois.

Chaque ligne dit quelle fonction tourne, ce qu'elle lit, ce qu'elle modifie en
place, ce qu'elle produit et quels fichiers elle écrit (cf.
`scripts/snapshot/registre.py`). `build_snapshot()` n'a plus qu'à exécuter
cette liste ; le manifeste du snapshot pourra dire, pour chaque fichier, quelle
étape l'a écrit.
"""
from __future__ import annotations

from scripts.snapshot.actes import (etape_actes, etape_cles_actes, etape_extraits,
                                    etape_liens_actes)
from scripts.snapshot.actualite import etape_actualite
from scripts.snapshot.argent import etape_finances, etape_flux
from scripts.snapshot.compteurs import (etape_bilan_revue, etape_compteurs, etape_revue_interne,
                                        etape_stats)
from scripts.snapshot.conflits import etape_conflits
from scripts.snapshot.corrections import etape_corrections
from scripts.snapshot.couverture import etape_compteurs_provisoires, etape_couverture
from scripts.snapshot.democratie import (etape_elections, etape_elus, etape_intercommunalite,
                                         etape_transparence)
from scripts.snapshot.dictionnaire import etape_dictionnaire
from scripts.snapshot.ecritures import (COUCHES, etape_ecrire_actes, etape_ecrire_acteurs,
                                        etape_ecrire_couches, etape_ecrire_finances,
                                        etape_ecrire_flux)
from scripts.snapshot.en_clair import etape_graphe
from scripts.snapshot.fiches import (etape_citations, etape_couches, etape_fiches,
                                     etape_fiches_acteurs)
from scripts.snapshot.manifeste import NOM as MANIFESTE
from scripts.snapshot.manifeste import etape_manifeste, etape_retirer_manifeste
from scripts.snapshot.perimetre import etape_perimetre
from scripts.snapshot.personnes import etape_personnes_publiques
from scripts.snapshot.popolo import etape_popolo
from scripts.snapshot.recherche import etape_index_recherche
from scripts.snapshot.registre import Etape
from scripts.snapshot.relations import etape_relations
from scripts.snapshot.revue import etape_revue
from scripts.snapshot.seances import etape_seances
from scripts.snapshot.sujets import etape_sujets
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
          lit=("conn", "revue", "public_ids", "public_entities", "perimetre_par_entite"),
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
    # Juste avant la première écriture : tant que la construction n'est pas
    # allée au bout, le répertoire ne déclare plus aucun contenu.
    Etape("retirer_manifeste", etape_retirer_manifeste, lit=("out",)),
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
    Etape("bilan_revue", etape_bilan_revue,
          lit=("exclusions", "revue_annotations", "public_events", "public_flows",
               "marches_data"),
          produit=("exclusions_publiees", "revue_atelier")),
    Etape("corrections", etape_corrections,
          lit=("out", "public_events", "public_flows", "marches_data"),
          produit=("corrections",), ecrit=("corrections.json",)),
    Etape("graphe", etape_graphe,
          lit=("conn", "out", "index_actes", "affiches", "public_events", "public_links",
               "public_entities"),
          produit=("graphe", "stats_en_clair", "stats_dossiers", "stats_graphe",
                   "seances_relues", "dossiers_publies"),
          ecrit=("conseils.json", "conseils/*.html", "dossiers.json", "liens.json",
                 "lacunes.json", "personnes_morales.json")),
    # Une page par séance publiée, relue ou non (docs/refonte-du-contenu.md,
    # lot 6). Après `graphe` : les séances relues y sont établies.
    Etape("seances", etape_seances,
          lit=("out", "public_events", "seances_relues"), produit=("stats_seances",),
          ecrit=("seances.json",)),
    # Les sujets : quel dossier, quelles données (lot 8). Lit les fichiers
    # qu'`environnement` et `territoire` ont écrits plus haut.
    Etape("sujets", etape_sujets,
          lit=("out", "dossiers_publies"), produit=("stats_sujets",),
          ecrit=("sujets.json",)),
    Etape("transparence", etape_transparence,
          lit=("conn", "out"), ecrit=("transparence.json",)),
    Etape("conflits", etape_conflits,
          lit=("conn", "out", "public_ids"), produit=("conflits",), ecrit=("conflits.json",)),
    Etape("fiches_acteurs", etape_fiches_acteurs,
          lit=("conn", "out", "public_entities", "public_relations", "public_events",
               "public_links", "public_flows", "marches_data"),
          produit=("bundles",), ecrit=("entite/*.json",)),
    Etape("extraits", etape_extraits,
          lit=("out", "textes_extraits"), produit=("extraits_actes",),
          ecrit=("extrait/*.json",)),
    Etape("index_recherche", etape_index_recherche,
          lit=("out", "entity_rows", "public_entities", "public_events", "public_links",
               "marches_data", "public_flows", "seances_relues", "dossiers_publies"),
          produit=("indexed", "recherche"),
          ecrit=("entity_index.json", "recherche_index.json")),
    Etape("stats", etape_stats,
          lit=("out", "exclusions_publiees", "revue_atelier", "stats_en_clair",
               "stats_dossiers", "stats_graphe", "cles_stats", "corrections", "actualite",
               "a_venir", "redactions", "conflits", "elections", "fiscalite", "elus",
               "urbanisme_public", "adresses_retirees", "croisement_foncier",
               "extraits_actes", "masquages", "bundles", "indexed", "recherche",
               "stats_seances", "stats_sujets"),
          complete=("stats",), ecrit=("stats.json",)),
    # Hors du snapshot : `audits/`, sous la racine du moteur. Le rapport porte
    # les exclusions NOMINATIVES — exactement ce que le filtre retient.
    Etape("revue_interne", etape_revue_interne,
          lit=("graphe", "stats", "entity_exclusions", "relation_exclusions",
               "event_exclusions")),
    Etape("dictionnaire", etape_dictionnaire,
          lit=("out", "stats", "location_quality"), ecrit=("README.md",)),
    # TOUJOURS la dernière : un snapshot sans manifeste est une construction
    # interrompue, et `verify_snapshot.py` le refuse.
    Etape("manifeste", etape_manifeste,
          lit=("out", "stats"), ecrit=(MANIFESTE,)),
]
