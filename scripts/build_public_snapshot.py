#!/usr/bin/env python3
"""
build_public_snapshot.py — Build a conservative public data layer.

This script does not modify the SQLite database. It reads the private working
database in read-only mode and exports a small, publication-oriented JSON
snapshot with strict filters and a review report.

Usage:
    venv/bin/python scripts/build_public_snapshot.py
    venv/bin/python scripts/build_public_snapshot.py --out audits/public_snapshot_preview
"""
from __future__ import annotations

import argparse
import os
import sys
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))

# Le socle — périmètre, règles, horloge, lecture de la base, écriture d'un
# fichier — vit dans `scripts/snapshot/socle.py`. Ses noms restent importables
# d'ici : `api.py`, `scripts/publication.py` et les essais les y cherchent.
from scripts.snapshot.socle import (  # noqa: E402,F401
    COMMUNES_EPCI,
    DB_PATH,
    DEFAULT_OUT,
    DEPARTEMENT,
    EPCI_NOM_C2,
    EPCI_SIREN_C2,
    INSEE_C1,
    RULES,
    RULES_PATH,
    TELECOMS_RAYON_KM,
    URL_COMMUNE,
    URL_EPCI,
    VARIABLE_HORLOGE,
    get_db,
    jour_utc,
    lire_horloge,
    load_rules,
    relation_exists,
    row,
    rows,
    safe_url,
    table_exists,
    write_json,
    write_json_compact,
)
from scripts.snapshot.popolo import (  # noqa: E402,F401
    build_popolo,
    POPOLO_ORG_CLASS,
    POPOLO_ROLES,
)
from scripts.snapshot.textes import (  # noqa: E402,F401
    ACRONYMES,
    compilateur_redaction,
    convocation_publique,
    joli_nom,
    masquer_donnees_personnelles,
    MENTION_PARTICULIER,
    MOTS_LIAISON,
    nettoyer_libelle,
    nettoyer_titre_evenement,
    noms_des_personnes_publiques,
    norm_nom,
    texte_publiable,
    TITRES_VIDES,
)
from scripts.snapshot.perimetre import (  # noqa: E402,F401
    exiger_perimetre_classe,
    PerimetreNonClasse,
    publiable_dans_perimetre,
    TYPES_INSTITUTIONNELS,
)
from scripts.snapshot.revue import (  # noqa: E402,F401
    appliquer_revue,
    charger_revue,
    TYPES_REVUS,
)
from scripts.snapshot.personnes import beneficiaires_argent_public  # noqa: E402,F401
from scripts.snapshot.fiches import (  # noqa: E402,F401
    FIN_DACTIVITE,
    NAF_IMMOBILIER,
    domain_for,
    etat_activite,
    in_center_box,
    in_commune_bbox,
    load_confirmed_urls,
    nature_entreprise,
    public_entity,
)
from scripts.snapshot.relations import (  # noqa: E402,F401
    RELATION_META_PUBLIQUE,
    is_public_relation,
    relation_meta_publique,
    relation_pertinente,
    sort_du_type,
)
from scripts.snapshot.actes import (  # noqa: E402,F401
    ACCORDE_RE,
    DEMANDE_RE,
    domaine,
    PORTEE_PAR_PERIMETRE,
    PORTEE_PAR_TYPE,
    portee_evenement,
    _annee_de_trace,
    MONTANT_MAX,
    MONTANT_MIN,
    TYPES_DELIBERES,
    TYPES_SEANCE,
    montant_de_la_decision,
    provenance,
    public_event_detail,
)
from scripts.snapshot.argent import (  # noqa: E402,F401
    beneficiaire_inconnu,
    _commune_entity_id,
    dedupliquer_flux,
    delier_extremites,
    delier_renvois_morts,
    flux_extremites_publiees,
    statut_extremites,
)
from scripts.snapshot.territoire import (  # noqa: E402,F401
    DECHETS_INDICATEURS,
    export_reperes_fiscaux,
    export_enfance,
    export_telecoms,
    INSEE_PUBLIABLES,
    RUPTURE_CUIVRE,
    export_dechets,
    export_eau_potable,
    export_incendie,
)
from scripts.snapshot.compteurs import mesurer_replicabilite  # noqa: E402,F401
from scripts.snapshot.couverture import STEP_META, export_couverture  # noqa: E402,F401
from scripts.snapshot.corrections import (  # noqa: E402,F401
    JOURNAL_PATH,
    export_corrections,
    lire_journal_corrections,
)
from scripts.snapshot.en_clair import export_dossiers, export_en_clair  # noqa: E402,F401
from scripts.snapshot.conflits import deports_par_deliberation, export_conflits  # noqa: E402,F401
from scripts.snapshot.fiches import comptes_syndicats_par_entite, write_entity_bundles  # noqa: E402,F401
from scripts.snapshot.actes import write_act_extracts  # noqa: E402,F401
from scripts.snapshot.etapes import ETAPES  # noqa: E402
from scripts.snapshot.registre import executer  # noqa: E402
from collectors.verdict import ecarte, verdict_de  # noqa: E402
# Ce que ce site EST, pour un lecteur qui y arrive sans rien savoir. Publié
# DANS LES DONNÉES et pas seulement dans le gabarit : une mention qui
# n'existe que dans la page disparaît de tout ce qui n'est pas la page —
# un export, une API, un moissonneur, un lecteur de flux.
from collectors.config import STATUT  # noqa: E402
from collectors.etat_flux import etat_du_flux  # noqa: E402


def write_search_index(out: Path, public_entities, communes: dict[int, str],
                       liens_count: dict[int, int]) -> int:
    """Index de recherche léger, et liste des ids pour le prérendu.

    Le site public exposait 2 673 acteurs sans le moindre champ de recherche :
    pour trouver une association il fallait la repérer à l'œil sur la carte ou
    dans une grille. L'index tient dans ~150 Ko et se filtre côté client, sans
    backend (le public est statique).

    `nb` (nombre d'actes rattachés) sert à classer les résultats : un acteur
    présent dans dix délibérations passe avant un homonyme dormant.
    """
    index = [
        {
            "id": e["id"],
            "n": e["name"],
            "t": e["type"],
            "s": e.get("short_name") or None,
            "c": communes.get(e["id"]) or None,
            # `p` : la commune ou l'intercommunalité. Un caractère de plus par
            # ligne, et l'annuaire peut trier les deux sans charger
            # `entities.json` (1,1 Mo) juste pour lire un champ.
            "p": PORTEE_PAR_PERIMETRE.get(e.get("perimetre") or "") or "territoire",
            # `a` : 1 en activité, 0 cessée, absent si les registres se taisent.
            **({"a": 1 if e["actif"] else 0} if e.get("actif") is not None else {}),
            **({"na": e["nature"]} if e.get("nature") else {}),
            **({"dt": e["derniere_trace"]} if e.get("derniere_trace") else {}),
            "nb": liens_count.get(e["id"], 0),
        }
        for e in public_entities
    ]
    index.sort(key=lambda r: (-r["nb"], r["n"] or ""))
    write_json_compact(out / "entity_index.json", {"entities": index, "total": len(index)})
    return len(index)


def write_recherche_index(out: Path, public_entities, public_events,
                          marches_data, public_flows, communes: dict[int, str],
                          liens_count: dict[int, int]) -> int:
    """Index de recherche transversal : acteurs, actes, marchés, versements.

    La recherche ne portait que sur les acteurs. Or on ne cherche pas seulement
    « qui » : on cherche « piscine », « école », « assainissement », « 15 000 »,
    une parcelle, une année. Chercher un mot et ne trouver que des noms
    d'entreprises donne l'impression que le site ne sait rien d'un sujet dont
    il a pourtant les actes.

    Format court volontaire (`k`, `t`, `n`, `d`, `u`, `m`) : l'index est
    embarqué dans la page et chaque clé est répétée à chaque ligne.
    Les champs :
      k  catégorie  acteur | acte | marche | versement
      t  titre affiché
      n  poids de tri (plus grand = remonte)
      d  date, quand elle existe
      u  URL interne de destination
      m  montant, quand il y en a un
      c  commune ou contexte
    """
    idx: list[dict] = []

    for e in public_entities:
        idx.append({
            "k": "acteur", "t": e["name"], "u": f"/entite/{e['id']}",
            "c": communes.get(e["id"]) or None,
            "n": 1000 + liens_count.get(e["id"], 0),
        })

    for ev in public_events:
        annee = (ev.get("date") or "")[:4] or "sans-date"
        idx.append({
            "k": "acte", "t": ev.get("title") or "(sans titre)",
            # L'ancre est la clé datée de l'acte quand elle est stable : un
            # résultat de recherche copié et partagé doit survivre au rejeu.
            "u": f"/deliberations/{annee}#{ev.get('ancre') or 'a' + str(ev['id'])}",
            "d": ev.get("date"), "m": ev.get("montant_principal"),
            "c": ev.get("source"),
            # Un acte portant un montant est plus souvent ce qu'on cherche.
            "n": 500 + (200 if ev.get("montant_principal") else 0),
        })

    for m in marches_data:
        titre = m.get("objet") or "Marché"
        if m.get("titulaire_nom"):
            titre = f"{titre} — {m['titulaire_nom']}"
        idx.append({
            "k": "marche", "t": titre, "u": "/marches",
            "d": m.get("date_notif"), "m": m.get("montant"),
            "c": m.get("acheteur_nom"), "n": 600,
        })

    for f in public_flows:
        if not f.get("to_name"):
            continue
        idx.append({
            "k": "versement",
            "t": f"{f.get('type_norm') or f.get('type') or 'Flux'} — {f['to_name']}",
            "u": "/finances", "d": str(f["year"]) if f.get("year") else None,
            "m": f.get("amount"), "c": f.get("from_name"), "n": 400,
        })

    idx.sort(key=lambda r: (-r["n"], r["t"] or ""))
    write_json_compact(out / "recherche_index.json",
                       {"index": idx, "total": len(idx)})
    return len(idx)


def synchroniser_site_public(src: Path, root: Path) -> dict:
    """Recopie le snapshot là où le site public le lit.

    Le builder écrit dans `outputs.public_snapshot_dir` (l'atelier le sert
    depuis là), le site public lit `public/static/data`. Le raccord entre les
    deux a longtemps vécu dans `api.py`, appelé depuis un script de
    déploiement qui n'était pas livré avec le moteur : une instance suivait le
    README, produisait un snapshot, et se retrouvait avec un site vide sans
    qu'aucune étape n'ait échoué.

    `entite/` et `extrait/` sont mis en MIROIR, pas seulement copiés : une
    entité ou un acte retiré de la publication doit disparaître du site, sinon
    il reste en ligne.
    """
    import shutil

    dest = root / "public" / "static" / "data"
    (dest / "layers").mkdir(parents=True, exist_ok=True)
    (dest / "entite").mkdir(parents=True, exist_ok=True)
    copied = []
    for f in sorted(src.glob("*.json")):
        shutil.copy2(f, dest / f.name)
        copied.append(f.name)
    # Le README est le dictionnaire de données : il accompagne les JSON, il ne
    # reste pas dans le dépôt. Il était exclu de la synchro, si bien que
    # `public/static/data/README.md` annonçait des chiffres faux à côté de
    # fichiers à jour.
    readme = src / "README.md"
    if readme.exists():
        shutil.copy2(readme, dest / "README.md")
        copied.append("README.md")
    for f in sorted((src / "layers").glob("*.geojson")):
        shutil.copy2(f, dest / "layers" / f.name)
        copied.append(f"layers/{f.name}")

    retirees: dict[str, list[str]] = {}
    # `conseils/` porte les feuilles « en clair » retenues, en HTML : même
    # miroir, une feuille qui n'est plus retenue doit quitter le site.
    for dossier, motif in (("entite", "*.json"), ("extrait", "*.json"), ("conseils", "*.html")):
        (dest / dossier).mkdir(parents=True, exist_ok=True)
        attendus = {f.name for f in (src / dossier).glob(motif)}
        for f in sorted((src / dossier).glob(motif)):
            shutil.copy2(f, dest / dossier / f.name)
            copied.append(f"{dossier}/{f.name}")
        retirees[dossier] = []
        for f in sorted((dest / dossier).glob(motif)):
            if f.name not in attendus:
                f.unlink()
                retirees[dossier].append(f.name)
    return {"dest": str(dest), "files": copied, "count": len(copied),
            "fiches_retirees": retirees["entite"],
            "extraits_retires": retirees["extrait"],
            "conseils_retires": retirees["conseils"]}


# Les indicateurs INSEE publiables — TOUS SAUF `DS_BPE`.
#
# 🔴 La base permanente des équipements a DÉMÉNAGÉ : `insee_social` la
# collectait sous des codes nus (`BPE_A129`, sans libellé, que rien ne lisait),
# et le step `equipements` l'a reprise avec sa nomenclature officielle. Mais
# cesser de collecter n'efface pas ce qui est déjà en base : le 03/09/2026, les
# trois instances portaient encore 502, 536 et 627 lignes `DS_BPE` fossiles —
# 12 à 14 % du jeu, dont 97 % sans libellé — publiées dans `territoire.json` à
# côté des lignes propres. Les mêmes faits deux fois, dont une illisible, et
# 146 Ko envoyés au navigateur pour ne rien afficher : la page filtre sur des
# codes précis et ne les rencontre jamais.
#
# Le filtre est posé ICI, au point de PUBLICATION, et non par une suppression
# en base : la donnée reste, le moteur n'a pas encore de migrations versionnées,
# et un `DELETE` à la main dans trois bases de production n'est pas un
# correctif. Le jour où les migrations existent, ce filtre devient inutile —
# et il ne fera alors que confirmer un jeu déjà propre.
def build_snapshot(out: Path, horloge: datetime | None = None) -> dict:
    # Avant toute lecture de la base : l'heure de cette construction, pour
    # tous les fichiers. Cf. `lire_horloge`.
    horloge = horloge or lire_horloge()
    conn = get_db()
    try:
        # Les étapes déclarées dans `scripts/snapshot/etapes.py`, dans l'ordre
        # de la liste. Ce qui suit leur exécution n'est pas encore découpé : il
        # reprend leurs produits sous les noms qu'il leur a toujours donnés.
        faits = executer(ETAPES, {"conn": conn, "out": out, "horloge": horloge,
                                  "exclusions": defaultdict(Counter)})
        revue = faits["revue"]
        exclusions = faits["exclusions"]


        civic_person_ids = faits["civic_person_ids"]
        beneficiaires = faits["beneficiaires"]
        public_person_ids = faits["public_person_ids"]
        redige, redactions = faits["redige"], faits["redactions"]
        noms_publics = faits["noms_publics"]
        ids_conseil_communautaire = faits["ids_conseil_communautaire"]

        entity_rows = faits["entity_rows"]
        ei_ids = faits["ei_ids"]
        public_entities = faits["public_entities"]
        entity_exclusions = faits["entity_exclusions"]
        ecartees_du_perimetre = faits["ecartees_du_perimetre"]
        location_quality = faits["location_quality"]
        public_ids = faits["public_ids"]

        relation_rows = faits["relation_rows"]
        public_relations = faits["public_relations"]
        relation_exclusions = faits["relation_exclusions"]

        event_rows = faits["event_rows"]
        public_events = faits["public_events"]
        event_exclusions = faits["event_exclusions"]
        textes_extraits = faits["textes_extraits"]
        masquages = faits["masquages"]

        public_event_ids = {e["id"] for e in public_events}
        public_links = faits["public_links"]
        perimetre_par_entite = faits["perimetre_par_entite"]

        index_actes = faits["index_actes"]
        affiches = faits["affiches"]
        cles_stats = faits["cles_stats"]

        flow_rows = faits["flow_rows"]
        public_flows = faits["public_flows"]

        public_layers = faits["public_layers"]

        budget_annuel = faits["budget_annuel"]
        budget_annexe = faits["budget_annexe"]
        ofgl_data = faits["ofgl_data"]
        budget_vote = faits["budget_vote"]
        dvf_data = faits["dvf_data"]
        marches_data = faits["marches_data"]
        approbations_data = faits["approbations_data"]

        stats = faits["stats"]

        elections = faits["elections"]

        fiscalite = faits["fiscalite"]

        elus = faits["elus"]

        urbanisme_public = faits["urbanisme_public"]
        adresses_retirees = faits["adresses_retirees"]

        croisement_foncier = faits["croisement_foncier"]

        actualite = faits["actualite"]
        a_venir = faits["a_venir"]
        stats["exclusions"] = faits["exclusions_publiees"]
        stats["revue_atelier"] = faits["revue_atelier"]
        corrections = faits["corrections"]
        graphe = faits["graphe"]
        stats["conseils_en_clair"] = faits["stats_en_clair"]
        stats["dossiers"] = faits["stats_dossiers"]
        stats["graphe"] = faits["stats_graphe"]
        stats["graphe"]["cles"] = cles_stats
        stats["corrections_site"] = len(corrections["site"])
        stats["actualite_items"] = min(len(actualite), 400)
        stats["actualite_a_venir"] = len(a_venir)
        stats["actualite_par_genre"] = dict(Counter(i["genre"] for i in actualite))
        stats["redactions_personnes"] = redactions.get("remplacements", 0)

        conflits = faits["conflits"]
        stats["conflits_cas"] = conflits["total"]
        stats["conflits_par_statut"] = dict(
            Counter(c["statut"] for c in conflits["cas"]))

        stats["elections_communes"] = len(elections.get("resultats", []))
        stats["fiscalite_taux"] = len(fiscalite)
        stats["elus_rne"] = len(elus)
        stats["urbanisme_autorisations"] = len(urbanisme_public)
        stats["urbanisme_adresses_retirees"] = adresses_retirees
        stats["croisement_foncier"] = len(croisement_foncier)

        # ── Un fichier par acteur + index de recherche ────────────────────────
        bundles = faits["bundles"]
        stats["extraits_actes"] = faits["extraits_actes"]
        stats["extraits_masquages"] = dict(masquages)
        communes = {r["id"]: r.get("commune") for r in entity_rows}
        liens_count = Counter(l["entity_id"] for l in public_links)
        indexed = write_search_index(out, public_entities, communes, liens_count)
        recherche = write_recherche_index(out, public_entities, public_events,
                                          marches_data, public_flows,
                                          communes, liens_count)
        stats["entity_bundles"] = bundles
        stats["search_index_entries"] = indexed
        stats["recherche_index_entries"] = recherche
        write_json(out / "stats.json", stats)   # réécrit avec les 2 compteurs

        # Rapport QA interne — JAMAIS dans le bundle public (contient les
        # exclusions nominatives = exactement les données filtrées). Écrit hors `out`.
        review_out = ROOT / "audits"
        review_out.mkdir(parents=True, exist_ok=True)
        graphe.ecrire_releve(review_out)
        write_json(review_out / "public_snapshot_review.json", {
            "stats": {**stats, "source_db": str(DB_PATH)},
            "entity_exclusions_sample": entity_exclusions[:250],
            "relation_exclusions_sample": relation_exclusions[:250],
            "event_exclusions_sample": event_exclusions[:250],
            "rules": {
                "public_confidence": sorted(RULES["confidence"]["public"]),
                "public_person_relation_types": sorted(RULES["people"]["publish_only_with_relation_types"]),
                "public_relation_types": sorted(RULES["relations"]["public_allowlist"]),
                "relevance_relation_types": sorted(
                    RULES["relations"].get("relevance_allowlist", [])),
                "public_money_relation_types": sorted(
                    RULES["relations"].get("public_money_relation_types", [])),
                "public_event_sources": sorted(RULES["events"]["public_sources"]),
                "generic_url_domains_excluded": sorted(RULES["urls"]["exclude_generic_domains"]),
                "location_policy": {
                    "person": "coordinates always hidden",
                    "outside_bbox": "coordinates hidden",
                    "center_fallback": "hidden except places/services",
                },
            },
        })

        # ── Dictionnaire de données ──────────────────────────────────────────
        # Servi À CÔTÉ des JSON, et régénéré à chaque exécution : un README
        # écrit à la main se périme en silence — celui d'avant le 12/08/2026
        # annonçait encore 2 876 entités publiques pour 1 807 réelles, et ne
        # disait rien du contenu des fichiers. Un jeu de données sans
        # dictionnaire n'est pas réutilisable, quelle que soit sa qualité.
        markdown = [
            f"# Données publiques — {RULES['project']['public_name']}",
            "",
            f"Généré le {stats['generated_at']} depuis la base de travail, "
            "sans la modifier.",
            "",
            "Ces fichiers sont le snapshot public : ce que le site sert, et rien "
            "d'autre. Ils sont produits par `scripts/build_public_snapshot.py` "
            "et contrôlés par `scripts/verify_snapshot.py`, qui refuse de "
            "publier tout type de relation absent de l'allowlist.",
            "",
            "## Licence",
            "",
            f"Ce jeu de données est publié sous **{RULES['outputs']['license']}** "
            f"([Open Database License]({RULES['outputs']['license_url']})).",
            "",
            "Vous pouvez le copier, le modifier et l'utiliser, y compris "
            "commercialement, à trois conditions : **citer** la source, "
            "**partager à l'identique** toute base dérivée que vous "
            "redistribuez, et ne pas la diffuser sous verrou technique sans "
            "en fournir aussi une version libre.",
            "",
            "Ce choix découle des sources : 333 des entités publiées sont des "
            "points d'intérêt OpenStreetMap et une large part des coordonnées "
            "vient d'un géocodage OSM. La contribution est substantielle et "
            "fondue dans le jeu — c'est donc une base dérivée au sens de "
            "l'ODbL, et le partage à l'identique s'applique.",
            "",
            "### Attribution",
            "",
            f"> {RULES['outputs']['attribution']}",
            "",
        ]
        markdown += [f"- {a}" for a in RULES["outputs"]["source_attributions"]]
        markdown += [
            "",
            "Le **site** et ses visualisations sont un « Produced Work » au "
            "sens de l'ODbL : les reprendre demande l'attribution, pas le "
            "partage à l'identique. Le **code** relève d'une licence distincte "
            "(MIT) — l'ODbL ne porte pas sur le logiciel.",
            "",
            "**La licence ne dit rien du RGPD.** Ces données restent soumises "
            "au droit des données personnelles : une réutilisation doit avoir "
            "sa propre base légale.",
            "",
            "## Réplication",
            "",
            "Ce modèle est conçu pour être rejoué sur une autre commune. Le "
            "périmètre se pilote dans `collectors/config.py` et nulle part "
            "ailleurs : commune, intercommunalité, communes membres. Les "
            "collecteurs, le schéma et le site n'ont pas à être touchés.",
            "",
            "## Fichiers",
            "",
            "| Fichier | Contenu | Clé racine |",
            "|---|---|---|",
            "| `entities.json` | Acteurs publiés : personnes, entreprises, "
            "associations, services, lieux | `entities` |",
            "| `relations.json` | Liens entre acteurs, datés et sourcés | "
            "`relations` |",
            "| `popolo.json` | Les **mandats** au format [Popolo]"
            "(https://www.popoloproject.com/) — format d'interopérabilité | "
            "`persons`, `organizations`, `memberships`, `areas` |",
            "| `events.json` | Actes : délibérations, arrêtés, annonces | "
            "`events` |",
            "| `event_links.json` | Quel acteur est cité dans quel acte | "
            "`links` |",
            "| `flows.json` | Flux financiers publics (subventions, "
            "participations) | `flows` |",
            "| `marches.json` | Marchés publics et attributaires | `marches` |",
            "| `budget.json` · `budget_vote.json` · `ofgl.json` | Budgets "
            "votés et agrégats financiers | `annuel`/`annexe`, `budget_vote`, "
            "`ofgl` |",
            "| `intercommunalite.json` | Compétences, délégués, sièges de "
            "l'EPCI | racine |",
            "| `elus_rne.json` | Conseils municipaux (Répertoire National des "
            "Élus) | `elus` |",
            "| `elections.json` | Résultats des municipales par commune | "
            "`resultats` |",
            "| `fiscalite.json` · `impots` | Taux d'imposition comparés, et "
            "leur rang parmi les communes | `taux`, `reperes` |",
            "| `dvf.json` | Transactions immobilières (DVF) | `dvf` |",
            "| `urbanisme.json` | Autorisations d'urbanisme | `autorisations` |",
            "| `environnement.json` | Eau (prix, contrôle sanitaire), déchets, "
            "forêt et feux, risques, ICPE, catastrophes naturelles | racine |",
            "| `territoire.json` | Indicateurs INSEE, équipements, télécoms, "
            "écoles et accueil du jeune enfant | racine |",
            "| `conflits.json` | Cas de conflits d'intérêts potentiels | "
            "`cas` |",
            "| `stats.json` | Compteurs et paramètres de publication | racine |",
            "| `layers/*.geojson` | Couches cartographiques | FeatureCollection |",
            "| `entite/<id>.json` | Fiche complète d'un acteur | racine |",
            "| `extrait/<id>.json` | Texte d'une délibération, lu dans le "
            "document | `texte` |",
            "| `liens.json` | Clé datée d'un acte (`c-2021-41`) → les dossiers "
            "et séances en clair qui le citent ; table d'alias `#a{id}` → clé | "
            "`actes`, `alias` |",
            "| `lacunes.json` | Questions ouvertes des dossiers publiés et "
            "citations sans acte publié | `lacunes` |",
            "| `personnes_morales.json` | Par clé d'acte, les personnes morales "
            "publiées qu'il concerne (SIREN) | `actes` |",
            "",
            "Chaque fichier à liste porte aussi un `total`.",
            "",
            "## Ce qui n'est jamais publié",
            "",
            "- les affirmations de niveau `probable` ou `hypothesis` — seuls "
            f"`{'`, `'.join(sorted(RULES['confidence']['public']))}` sortent ;",
            "- les liens de famille, de domicile partagé et les doublons "
            f"présumés (marqueurs : `{'`, `'.join(sorted(RULES['relations']['private_markers']))}`) ;",
            "- les coordonnées des personnes, et les adresses des demandeurs "
            "particuliers en urbanisme ;",
            "- la date de naissance des élus (le RNE la diffuse, pas nous) ;",
            "- dans le texte des délibérations, le domicile, la date et le lieu "
            "de naissance d'une personne — masqués ; pour une personne publique, "
            "la date de naissance devient son âge à la date de l'acte. Les noms, "
            "eux, sont cités : un acte officiel cite ses particuliers ;",
            "- les conseils municipaux des communes hors intercommunalité.",
            "",
            "## Compteurs",
            "",
            f"- entités : {stats['entities_public']} publiées "
            f"sur {stats['entities_total_private']} en base",
            f"- relations : {stats['relations_public']} sur "
            f"{stats['relations_total_private']}",
            f"- actes : {stats['events_public']} sur "
            f"{stats['events_total_private']}",
            f"- points cartographiés : {stats['map_features_public']}",
            f"- sites web vérifiés : {stats['urls_public_confirmed']}",
            "",
            "## Qualité de localisation",
            "",
        ]
        for key, count in sorted(location_quality.items()):
            markdown.append(f"- `{key}` : {count}")
        markdown.extend([
            "",
            "## Exclusions — pourquoi une donnée n'est pas là",
            "",
        ])
        for section, counts in stats["exclusions"].items():
            markdown.append(f"### {section}")
            for reason, count in sorted(counts.items()):
                markdown.append(f"- `{reason}` : {count}")
            markdown.append("")
        (out / "README.md").write_text("\n".join(markdown), encoding="utf-8")

        return stats
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a conservative public snapshot preview")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--no-sync", action="store_true",
                        help="ne pas recopier le snapshot vers public/static/data "
                             "(la recopie n'a lieu que si --out est le répertoire "
                             "publié : un brouillon ne se sert jamais)")
    parser.add_argument("--horloge", metavar="ISO",
                        help="l'heure de la construction, au lieu de celle qu'il "
                             f"est (ou variable {VARIABLE_HORLOGE}) : rejouer une "
                             "construction pour la comparer à une autre, cf. "
                             "scripts/comparer_snapshots.py")
    args = parser.parse_args()
    try:
        horloge = lire_horloge(args.horloge)
    except ValueError as e:
        parser.error(str(e))

    # Les libellés du site sont dérivés de la même instance que le snapshot :
    # les régénérer ici évite qu'un site publie le nom d'une commune et les
    # chiffres d'une autre.
    try:
        from generer_libelles import construire, ecrire
        ecrire(construire())
    except Exception as e:                      # ne doit jamais bloquer la publication
        print(f"  [libellés] non régénérés : {e}")

    # Une étape de collecte qui manque n'est pas une panne du programme : elle
    # se dit en une phrase, pas en pile d'appels.
    try:
        stats = build_snapshot(args.out, horloge)
    except PerimetreNonClasse as e:
        print(f"\n✖ snapshot refusé — {e}", file=sys.stderr)
        return 2

    # Produire le snapshot sans le porter jusqu'au site, c'était la moitié du
    # travail — et la moitié invisible : le site restait tel quel, sans erreur.
    #
    # Mais la synchro ne vaut QUE pour le répertoire publié. Construire un
    # brouillon (`--out audits/public_snapshot_preview`) poussait quand même le
    # résultat dans `public/static/data` : un aperçu se retrouvait servi sans
    # avoir été contrôlé ni publié, et sans qu'une ligne le dise. C'est le même
    # défaut que la publication en deux temps a corrigé côté atelier, resté
    # entier côté ligne de commande — là où l'exploitant travaille.
    #
    # Générer n'est pas publier : pour porter un brouillon jusqu'au site, il y a
    # le flux de publication, qui contrôle avant de mettre en service.
    vers_le_repertoire_publie = args.out.resolve() == DEFAULT_OUT.resolve()
    if args.no_sync:
        pass
    elif not vers_le_repertoire_publie:
        print(f"  [site] non synchronisé : --out désigne {args.out}, pas le "
              f"répertoire publié ({DEFAULT_OUT}). Un brouillon ne se sert pas.")
    else:
        sync = synchroniser_site_public(args.out, ROOT)
        stats["site_public_fichiers"] = sync["count"]
        stats["site_public_fiches_retirees"] = len(sync["fiches_retirees"])

    print(json.dumps({"out": str(args.out), **stats}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
