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
    export_dechets,
    export_eau_potable,
    export_incendie,
)
from scripts.snapshot.etapes import ETAPES  # noqa: E402
from scripts.snapshot.registre import executer  # noqa: E402
# Le rythme attendu de chaque collecteur. La page `/couverture` le publie :
# sans lui, elle jugeait tout le monde au même seuil (45 jours), et la source
# qui bouge le plus — le site municipal, déclaré à 3 jours — était celle que ce
# seuil couvrait le moins.
from collectors.config import STEP_META  # noqa: E402
from collectors.verdict import ecarte, verdict_de  # noqa: E402
# Ce que ce site EST, pour un lecteur qui y arrive sans rien savoir. Publié
# DANS LES DONNÉES et pas seulement dans le gabarit : une mention qui
# n'existe que dans la page disparaît de tout ce qui n'est pas la page —
# un export, une API, un moissonneur, un lecteur de flux.
from collectors.config import STATUT  # noqa: E402
from collectors.etat_flux import etat_du_flux  # noqa: E402


def write_act_extracts(out: Path, textes: dict[int, str]) -> int:
    """Un fichier par délibération publiée : `extrait/<id>.json`, son texte.

    La page d'un millésime ne montrait d'un acte que son titre, et renvoyait au
    PDF de la séance entière — une liasse de quarante pages où retrouver la
    sienne. Le texte de chaque délibération est pourtant en base depuis la
    collecte : le lecteur le déplie désormais sous le titre.

    Un fichier par acte plutôt que le texte dans `events.json` : chaque page de
    millésime embarque ses actes dans son HTML, et les 578 Ko de texte d'une
    seule année y seraient partis pour un lecteur qui n'en ouvre qu'un. Même
    motif que `entite/<id>.json`.

    Le texte est celui que `texte_publiable` rend : les noms y sont, domicile et
    naissance y sont masqués. Il garde la forme et les fautes de l'extraction :
    c'est une LECTURE du document, et la page le dit — la pièce qui fait foi
    reste celle de la collectivité.
    """
    dest = out / "extrait"
    dest.mkdir(parents=True, exist_ok=True)

    # PURGE AVANT ÉCRITURE, pour la raison écrite dans `write_entity_bundles` :
    # un acte retiré de la publication garderait sinon son texte en ligne.
    attendus = {f"{i}.json" for i in textes}
    for f in dest.glob("*.json"):
        if f.name not in attendus:
            f.unlink()

    for i, texte in textes.items():
        write_json_compact(dest / f"{i}.json", {"id": i, "texte": texte})
    return len(textes)


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


def _mots_significatifs(nom: str) -> set[str]:
    """Tokens discriminants d'un nom d'entité, pour rapprocher un titre de délib.

    On écarte les mots vides et les génériques (« ASSOCIATION », « COMITE »…) :
    sans ça, « Subvention — Comité des fêtes » se rapprocherait de n'importe
    quelle autre association portant le mot « comité ».
    """
    vides = {"ASSOCIATION", "ASSOC", "COMITE", "CLUB", "LES", "LE", "LA", "DE",
             "DES", "DU", "ET", "AMIS", "SOCIETE", "UNION", "L", "D", "EN", "AU"}
    return {m for m in norm_nom(nom).replace("(", " ").replace(")", " ").split()
            if len(m) >= 4 and m not in vides}


def deports_par_deliberation(conn) -> list[dict]:
    """Déports consignés dans les comptes rendus : « X ne participe pas ».

    Découverte du 26/07/2026 : `metadata.conflit_interet` de 15 délibérations
    nomme les élus qui se sont retirés du vote. C'est décisif pour la page
    publique : un élu qui dirige une association subventionnée n'est pas en
    faute s'il ne participe pas au vote. Sans cette information, la page
    accuserait là où le conseil a précisément fait ce qu'il devait.
    """
    return rows(conn, """
        SELECT ev.id, ev.date, ev.title, ev.source_url,
               json_extract(ev.metadata,'$.conflit_interet') AS mention
        FROM events ev
        WHERE json_extract(ev.metadata,'$.conflit_interet') IS NOT NULL
          AND json_extract(ev.metadata,'$.conflit_interet') NOT IN ('false','0','')
        ORDER BY ev.date
    """)


def export_conflits(conn, public_ids: set[int]) -> dict:
    """Situations à vérifier : un élu lié à une structure qui reçoit de l'argent.

    Trois précautions structurent cet export :

    1. **Déduplication.** `v_conflits_potentiels` joint deux fois la table des
       relations : une personne cumulant `élu_cm` et `élu_cc` produit deux lignes
       pour un même versement. Publier « 14 situations » là où il y en a 7
       surévaluerait le phénomène. On regroupe sur (personne, entité, flux) et on
       agrège les rôles.
    2. **Le déport.** Chaque cas est confronté aux délibérations où l'élu est noté
       « ne participe pas ». Un déport constaté est la preuve que la règle a été
       respectée — c'est une information au moins aussi importante que le lien.
    3. **Périmètre.** Uniquement des relations `verified`/`confirmed` dont les
       deux extrémités sont publiques. `v_adresses_partagees` et
       `v_familles_potentielles` sont **exclues** (arbitrage du 26/07/2026) :
       une adresse commune n'établit rien et relève de la vie privée.
    """
    if not relation_exists(conn, "v_conflits_potentiels"):
        return {"cas": [], "total": 0, "deports_repertories": 0, "methode": {}}

    brut = rows(conn, "SELECT * FROM v_conflits_potentiels")
    deports = deports_par_deliberation(conn)

    # Historique des mandats par personne. Indispensable pour ne PAS conclure.
    #
    # Cas typique : une personne n'a qu'un mandat en base (celui en cours),
    # aucun mandat clos, alors que les versements à la structure qu'elle dirige
    # remontent à plusieurs années. Conclure « antérieur au mandat » serait une
    # affirmation non fondée — le RNE ne diffuse que les mandats en cours, et
    # l'historique des mandatures précédentes est incomplet. Ces situations
    # sortent en `chronologie_incertaine`, jamais en « hors mandat ».
    mandats: dict[int, dict] = {}
    for m in rows(conn, """
        SELECT r.from_id AS pid, MIN(r.since) AS premier_debut,
               SUM(r.until IS NOT NULL) AS nb_clos
        FROM relations r
        WHERE r.relation_type IN ('élu_cm','élu_cc','adjoint','maire','candidat')
        GROUP BY r.from_id
    """):
        mandats[m["pid"]] = m
    ei_ids = {r["entity_id"] for r in rows(
        conn, "SELECT entity_id FROM businesses WHERE legal_form_code = '1000'")}

    groupes: dict[tuple, dict] = {}
    for r in brut:
        if r["person_id"] not in public_ids or r["entite_id"] not in public_ids:
            continue
        # Même filtre que pour le graphe : « Philippe BRISSAC dirige PHILIPPE
        # BRISSAC » n'est pas une situation à vérifier, c'est une entreprise
        # individuelle. 34 des 48 cas bruts étaient de cette nature — les
        # publier comme « liens à vérifier » aurait noyé les 4 cas réels et mis
        # en cause des élus pour avoir déclaré leur propre activité.
        if r["entite_id"] in ei_ids:
            continue
        if norm_nom(r["person_name"]) == norm_nom(r["entite_nom"]):
            continue
        cle = (r["person_id"], r["entite_id"], r["flux_id"])
        cas = groupes.get(cle)
        if cas is None:
            cas = groupes[cle] = {
                "person_id": r["person_id"], "person_name": r["person_name"],
                "entite_id": r["entite_id"], "entite_nom": r["entite_nom"],
                "entite_type": r["entite_type"],
                "roles_elu": set(), "roles_entite": set(),
                "flux_id": r["flux_id"],
                "flux_type": r["flux_type"], "flux_montant": r["flux_montant"],
                "flux_annee": r["flux_annee"], "flux_date": r["flux_date"],
                "chronologies": set(),
                "mandat_debut": r["mandat_debut"], "mandat_fin": r["mandat_fin"],
            }
        cas["roles_elu"].add(r["role_elu"])
        cas["roles_entite"].add(r["role_entite"])
        cas["chronologies"].add(r["chronologie"])

    # Rapprochement des déports : nom de l'élu ET un mot discriminant de
    # l'entité dans le titre de la délibération, même année que le versement.
    cas_final = []
    for cas in groupes.values():
        nom_norm = norm_nom(cas["person_name"])
        tokens_pers = {m for m in nom_norm.split() if len(m) >= 3}
        tokens_entite = _mots_significatifs(cas["entite_nom"])
        trouve = None
        for d in deports:
            mention = norm_nom(d["mention"])
            if not tokens_pers & set(mention.split()):
                continue
            titre = norm_nom(d["title"])
            if tokens_entite and not (tokens_entite & set(titre.split())):
                continue
            if cas["flux_annee"] and d["date"] and str(cas["flux_annee"]) not in d["date"]:
                continue
            trouve = {"event_id": d["id"], "date": d["date"], "titre": d["title"],
                      "mention": d["mention"], "source_url": safe_url(d["source_url"])}
            break

        cas["roles_elu"] = sorted(cas["roles_elu"])
        cas["roles_entite"] = sorted(cas["roles_entite"])
        cas["deport"] = trouve

        # Chronologie : la vue produit une ligne par mandat. Un élu réélu a
        # plusieurs mandats, et le versement de 2021 est « antérieur » au mandat
        # de 2026 tout en étant contemporain de celui de 2020. La question posée
        # est « était-il élu quand l'argent a été voté ? » : il suffit donc
        # qu'UN mandat couvre le versement. Sans cette agrégation, des
        # subventions votées en pleine mandature ressortaient « hors mandat ».
        chronos = cas.pop("chronologies")
        for niveau in ("contemporain", "chevauchement_annee",
                       "anterieur_mandat", "hors_mandat", "dates_manquantes",
                       "lien_sans_flux"):
            if niveau in chronos:
                cas["chronologie"] = niveau
                break
        else:
            cas["chronologie"] = "indetermine"
        # Vocabulaire volontairement non accusatoire : l'absence de trace n'est
        # pas une preuve d'absence de déport, les CR ne sont pas tous exploités.
        if cas["flux_id"] is None or cas["flux_montant"] is None:
            cas["statut"] = "lien_sans_versement"
        elif trouve:
            cas["statut"] = "deport_constate"
        elif cas["chronologie"] == "anterieur_mandat":
            # Antérieur aux mandats CONNUS. Si la personne n'a aucun mandat clos
            # en base, son historique est incomplet : on ne conclut pas.
            m = mandats.get(cas["person_id"]) or {}
            cas["statut"] = ("hors_mandat" if (m.get("nb_clos") or 0) > 0
                             else "chronologie_incertaine")
        elif cas["chronologie"] == "hors_mandat":
            cas["statut"] = "hors_mandat"
        else:
            cas["statut"] = "deport_non_trouve"
        cas_final.append(cas)

    cas_final.sort(key=lambda c: (-(c["flux_montant"] or 0), c["person_name"]))
    return {
        "cas": cas_final,
        "total": len(cas_final),
        "deports_repertories": len(deports),
        "methode": {
            "source_liens": "relations vérifiées entre une personne à mandat "
                            "électif et une structure qu'elle dirige",
            "source_versements": "subventions et flux financiers de la commune "
                                 "(périmètre 'detail', statut 'réalisé')",
            "source_deports": "mentions « ne participe pas » relevées dans les "
                              "comptes rendus du conseil municipal",
            "exclusions": ["adresses partagées", "liens familiaux présumés",
                           "relations probable / hypothesis"],
            "avertissement": "Un lien n'est pas une faute. La loi n'interdit pas "
                             "à un élu de diriger une association subventionnée : "
                             "elle lui impose de ne pas participer au vote. "
                             "L'absence de déport constaté ici peut simplement "
                             "signifier que le compte rendu correspondant n'a pas "
                             "encore été exploité.",
        },
    }


JOURNAL_PATH = Path(os.environ.get("VIGIE_JOURNAL_CORRECTIONS")
                    or ROOT / "config" / "journal_corrections.json")
_DATE_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def lire_journal_corrections(path: Path = JOURNAL_PATH) -> list[dict]:
    """Les erreurs DU SITE, reconnues et corrigées — écrites par l'instance.

    Une donnée rectifiée à la main se relève toute seule (`corrige`). Un
    calcul faux, un doublon qui comptait deux fois, un chiffre mal nommé ne
    laissent aucune trace dans les données : ils n'existent que si quelqu'un
    les écrit. Le fichier est facultatif ; une entrée incomplète est écartée,
    jamais complétée — un journal ne s'invente pas.
    """
    if not path.exists():
        return []
    try:
        brut = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  ⚠ {path.name} illisible ({exc}) : journal des corrections vide")
        return []
    entrees = []
    for e in brut if isinstance(brut, list) else []:
        if not isinstance(e, dict):
            continue
        date, constat, correction = (str(e.get(k) or "").strip()
                                     for k in ("date", "constat", "correction"))
        page = str(e.get("page") or "").strip()
        if not (_DATE_ISO.match(date) and constat and correction):
            continue
        entrees.append({
            "date": date,
            # Un chemin du site, jamais une URL : le journal ne renvoie pas ailleurs.
            "page": page if re.fullmatch(r"/[\w\-/]*", page) else None,
            "constat": constat, "correction": correction,
            "signale_par": str(e.get("signale_par") or "").strip() or None,
        })
    return sorted(entrees, key=lambda e: e["date"], reverse=True)


def export_corrections(public_events: list[dict], public_flows: list[dict],
                       marches: list[dict], journal: list[dict]) -> dict:
    """Le journal des corrections : ce que le site a reconnu faux, et réparé.

    « Rectifié » était promis sur /methode, avec « 0 » en face et aucun endroit
    où lire ce qui avait été corrigé (audit du 24/09/2026). Un zéro se publie
    aussi : c'est un fait, pas une absence de page.
    """
    donnees = []
    for e in public_events:
        if e.get("corrige"):
            donnees.append({"nature": "acte", "id": e["id"], "type": e.get("type"),
                            "date": e.get("date"), "ancre": e.get("ancre"),
                            "libelle": e.get("title"), "champs": e["corrige"],
                            "motif": e.get("note_revue")})
    for f in public_flows:
        if f.get("corrige"):
            donnees.append({"nature": "flux", "id": f.get("id"),
                            "date": f"{f['year']}" if f.get("year") else None,
                            "libelle": f.get("description") or f.get("to_name"),
                            "champs": f["corrige"], "motif": f.get("note_revue")})
    for m in marches:
        if m.get("corrige"):
            donnees.append({"nature": "marche", "id": m.get("id"),
                            "date": m.get("date_notif"), "libelle": m.get("objet"),
                            "champs": m["corrige"], "motif": m.get("note_revue")})
    donnees.sort(key=lambda d: d.get("date") or "", reverse=True)
    return {"site": journal, "donnees": donnees}


def export_couverture(conn, public_events: list[dict], stats: dict) -> dict:
    """Ce que la collecte couvre, et surtout ce qu'elle ne couvre pas.

    Un observatoire qui n'affiche que ce qu'il sait ressemble à une boîte
    noire : le lecteur ne peut pas distinguer « il ne s'est rien passé en
    2019 » de « nous n'avons pas collecté 2019 ». Publier les trous coûte peu
    et vaut mieux que de paraître complet.

    Trois choses différentes, à ne pas confondre :
      - la PÉRIODE réellement couverte par source ;
      - la FRAÎCHEUR, c'est-à-dire la dernière collecte et son issue ;
      - les EXCLUSIONS délibérées (périmètre, vie privée), qui ne sont pas
        des lacunes mais des choix, et qui sont déjà dans `stats`.
    """
    # La période couverte s'arrête à la date d'arrêt : un concert annoncé pour
    # le 14/11 faisait « couvrir » lasalle.fr jusqu'en novembre, deux mois après
    # la collecte (audit du 24/09/2026). L'agenda à venir est compté à part.
    arret = (stats.get("generated_at") or datetime.now().isoformat())[:10]
    par_source: dict[str, dict] = {}
    for e in public_events:
        src = e.get("source") or "inconnue"
        d = par_source.setdefault(src, {"source": src, "actes": 0,
                                        "debut": None, "fin": None,
                                        "avec_document": 0,
                                        "a_venir": 0, "annonce_jusqu_au": None})
        d["actes"] += 1
        if e.get("document") == "acte":
            d["avec_document"] += 1
        date = e.get("date")
        if date and date[:10] > arret:
            d["a_venir"] += 1
            if d["annonce_jusqu_au"] is None or date > d["annonce_jusqu_au"]:
                d["annonce_jusqu_au"] = date
        elif date:
            if d["debut"] is None or date < d["debut"]:
                d["debut"] = date
            if d["fin"] is None or date > d["fin"]:
                d["fin"] = date

    # Dernier passage de chaque collecteur : un collecteur muet depuis des mois
    # est une lacune en formation, pas encore visible dans les compteurs.
    derniers = {}
    if table_exists(conn, "collector_runs"):
        for r in rows(conn, """
            SELECT collector, status, MAX(started_at) AS dernier
            FROM collector_runs GROUP BY collector
        """):
            derniers[r["collector"]] = {
                "statut": r["status"],
                "dernier": r["dernier"],
                # Le seuil vient de la source unique de vérité, jamais d'un
                # nombre écrit dans la page : un collecteur dont on change le
                # rythme change de seuil le jour même.
                "ttl": STEP_META[r["collector"]][0] if r["collector"] in STEP_META else None,
            }

    doc = stats.get("provenance", {}).get("document", {})
    total_actes = sum(doc.values()) or 1

    return {
        "arrete_le": stats.get("generated_at"),
        "sources": sorted(par_source.values(), key=lambda d: -d["actes"]),
        "collecteurs": derniers,
        # Le chiffre le plus inconfortable du site, donc celui qu'il faut donner
        # en premier : la proportion d'actes dont la pièce elle-même est
        # consultable, par opposition à la page qui la contient.
        "actes_avec_piece": doc.get("acte", 0),
        "actes_total": total_actes,
        "part_avec_piece": round(100 * doc.get("acte", 0) / total_actes, 1),
        "lacunes_connues": [
            {
                "sujet": "Documents des délibérations",
                "etat": "partiel",
                "detail": ("La très grande majorité des actes renvoient vers la page du "
                           "compte rendu qui les contient, et non vers la délibération "
                           "elle-même. Il faut donc chercher le passage dans le document."),
            },
            {
                "sujet": "Mandatures antérieures à 2020",
                "etat": "incomplet",
                "detail": ("L'historique des mandats est lacunaire avant 2020, ce qui empêche "
                           "de dire si une personne était élue à la date d'un versement "
                           "ancien. Les situations concernées sont signalées comme telles."),
            },
            {
                "sujet": "Dirigeants d'associations",
                "etat": "incomplet",
                "detail": ("Aucune source ouverte ne publie les dirigeants d'associations. "
                           "Ceux qui figurent ici proviennent de documents publics les "
                           "nommant, jamais d'un registre exhaustif."),
            },
            {
                "sujet": "Recoupement entre sources",
                "etat": "absent",
                "detail": ("Aucune donnée n'est aujourd'hui confirmée par deux sources "
                           "indépendantes : la chaîne ne sait pas encore le faire."),
            },
        ],
    }



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


def mesurer_replicabilite() -> dict:
    """Compte ce qui reste attaché à la commune, et le publie.

    /methode annonçait que « changer de commune tient dans un seul fichier de
    configuration » et que « ce site n'a pas à être modifié ». C'était faux, et
    publier le dépôt rendait l'écart vérifiable en trente secondes. Plutôt que
    de réécrire une promesse en la datant — elle dériverait à son tour — la page
    affiche une mesure refaite à chaque build.

    Le moteur est analysé par AST et non par expression régulière : documenter
    un piège oblige à écrire le nom de la commune dans une docstring, et un
    contrôle qui ne sait pas distinguer la doc du code se signale lui-même.
    Le site, lui, est du texte éditorial : toute occurrence y compte.
    """
    import importlib.util

    from collectors.config import COMMUNE_NAME

    # La mesure est déléguée à `verifier_generique.py`, qui est le contrôle
    # d'admission du kit : deux définitions du mot « moteur » finiraient par
    # diverger, et c'est arrivé. Celle d'ici listait `build_public_db.py`,
    # `migrate_perimetre.py` et `pipeline.py`, absents du dépôt depuis la
    # généricisation, sautés en silence par un `if not f.exists(): continue` —
    # la page /methode publiait donc une dette mesurée sur les trois quarts du
    # moteur. Elle ne comptait par ailleurs que le nom de la commune COURANTE,
    # là où le risque réel est le nom de la commune d'ORIGINE.
    chemin = ROOT / "scripts" / "verifier_generique.py"
    spec = importlib.util.spec_from_file_location("verifier_generique", chemin)
    vg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vg)

    communes = vg.communes_locales()
    constats_moteur = [c for f in vg._fichiers(vg.MOTEUR)
                       for c in vg.analyser(f, communes)
                       if c["motif"] == "nom_commune"]
    textes = [c for f in vg._fichiers_texte()
              for c in vg.analyser_texte(f, communes)]
    # Le site public et l'atelier sont deux dettes distinctes : l'une part en
    # production, l'autre non. Les additionner gonflerait le chiffre publié
    # d'un travail que le lecteur du site ne voit jamais.
    constats_site = [c for c in textes if c["fichier"].startswith("public/")]
    constats_atelier = [c for c in textes if c["fichier"].startswith("dashboard/")]

    def _compte(constats):
        return len({c["fichier"] for c in constats}), len(constats)

    moteur_f, moteur_o = _compte(constats_moteur)
    site_f, site_o = _compte(constats_site)
    atelier_f, atelier_o = _compte(constats_atelier)

    return {
        "commune": COMMUNE_NAME,
        "moteur_fichiers": moteur_f,
        "moteur_occurrences": moteur_o,
        "site_fichiers": site_f,
        "site_occurrences": site_o,
        "atelier_fichiers": atelier_f,
        "atelier_occurrences": atelier_o,
        # Ce que la mesure couvre, publié avec elle : un chiffre de dette sans
        # son périmètre se lit comme une garantie qu'il n'est pas.
        "noms_recherches": sorted(communes),
    }


# ── Internet et téléphone (ARCEP, `collectors/telecoms.py`) ──────────────────
#
# Cinq relevés, cinq façons de se tromper en les affichant — chacune qualifiée
# ici, pour que la page n'ait rien à décider :
#   - le nombre de LOCAUX varie d'un trimestre à l'autre (le plan d'adressage
#     nettoie la base) : on publie la PART fibrée, jamais le seul compte ;
#   - l'éligibilité au cuivre tombe à zéro au 2ᵉ trimestre 2026 dans 25 805
#     communes à la fois : une rupture de méthode, pas une fermeture ;
#   - la qualité de la fibre n'existe que PAR RÉSEAU (tout un département hors
#     villes) : elle se dit comme telle, et ne se classe qu'à période et
#     périmètre égaux ;
#   - un site mobile est une ligne par opérateur : le site physique est
#     `id_site_partage` (sinon `num_site`) ;
#   - « 0 panne » ne vaut que sur des jours LUS : sans jour lu, rien n'est dit.

def _fin_de_periode(periode: str) -> tuple:
    """« 10/25 - 03/26 » → (26, 3) : une période se trie par sa fin."""
    m = re.search(r"(\d{2})/(\d{2})\s*$", periode or "")
    return (int(m.group(2)), int(m.group(1))) if m else (0, 0)


def _situer(conn, periode: str, perimetre: str, colonne: str, valeur) -> dict | None:
    """Rang (du meilleur au moins bon) et médiane parmi les réseaux de même
    période et même périmètre."""
    if valeur is None:
        return None
    autres = sorted(r[0] for r in conn.execute(
        f"SELECT {colonne} FROM telecoms_qualite_ftth WHERE periode=? AND perimetre=? "
        f"AND {colonne} IS NOT NULL", (periode, perimetre)))
    if not autres:
        return None
    n = len(autres)
    mediane = autres[n // 2] if n % 2 else (autres[n // 2 - 1] + autres[n // 2]) / 2
    return {"taux": valeur, "rang": sum(1 for x in autres if x < valeur) + 1,
            "sur": n, "mediane": round(mediane, 6)}


#: Les trimestres où l'ARCEP a changé de méthode pour le cuivre (le zéro y
#: apparaît dans des dizaines de milliers de communes, selon leur calendrier de
#: mise à jour). Un zéro apparu HORS de cette fenêtre n'est pas qualifié : la
#: page n'en dit rien plutôt que de l'expliquer à tort.
RUPTURE_CUIVRE = ("2026_T1", "2026_T2")


def _cuivre_a_zero(serie: list[dict]) -> dict | None:
    """Le trimestre où l'éligibilité au cuivre tombe à zéro, s'il est dans la
    fenêtre de rupture et le reste depuis."""
    for avant, apres in zip(serie, serie[1:]):
        if avant["cuivre"] and apres["cuivre"] == 0:
            if apres["trimestre"] in RUPTURE_CUIVRE and serie[-1]["cuivre"] == 0:
                return {"trimestre": apres["trimestre"], "date": apres["date"],
                        "avant": avant["cuivre"], "date_avant": avant["date"]}
    return None


def export_telecoms(conn, insee: str, departement: str, rayon_km: float) -> dict | None:
    if not table_exists(conn, "telecoms_fixe"):
        return None
    serie = rows(conn, """
        SELECT trimestre, date, locaux, elig_ftth AS fibre, elig_cu AS cuivre,
               mt_ftth, mt_4gf, mt_sat, mt_autre
          FROM telecoms_fixe WHERE insee=? ORDER BY trimestre
    """, (insee,))
    if not serie:
        return None
    for s in serie:
        s["part"] = round(100 * s["fibre"] / s["locaux"], 1) \
            if s["locaux"] and s["fibre"] is not None else None
    dernier = serie[-1]
    ouverture = next((s for s in serie if s["fibre"]), None)
    fixe = {
        "serie": [{k: s[k] for k in ("trimestre", "date", "locaux", "fibre", "part")}
                  for s in serie],
        "dernier": {**dernier, "sans_fibre": (dernier["locaux"] or 0) - (dernier["fibre"] or 0)},
        "ouverture": ouverture and {k: ouverture[k] for k in ("trimestre", "date", "fibre")},
        "cuivre_a_zero": _cuivre_a_zero(serie),
    }

    reseau = None
    if table_exists(conn, "telecoms_fixe_oi"):
        oi = row(conn, """
            SELECT f.trimestre, f.zone, f.oi, o.nom, f.locaux, f.ftth
              FROM telecoms_fixe_oi f LEFT JOIN telecoms_operateurs o ON o.code = f.oi
             WHERE f.insee=? ORDER BY f.trimestre DESC LIMIT 1
        """, (insee,))
        if oi:
            reseau = {**oi, "qualite": None}
            nom = oi.get("nom")
            if nom and table_exists(conn, "telecoms_qualite_ftth"):
                # L'ARCEP nomme le même opérateur « Wigard » ici, « Wigard
                # Fibre » là : la jointure se fait par préfixe.
                lignes = rows(conn, "SELECT * FROM telecoms_qualite_ftth WHERE oi LIKE ?",
                              (nom + "%",))
                periodes = sorted({r["periode"] for r in lignes}, key=_fin_de_periode)
                if periodes:
                    p = periodes[-1]
                    res = next((r for r in lignes if r["periode"] == p
                                and r["perimetre"] == "reseau"), None)
                    dep = next((r for r in lignes if r["periode"] == p
                                and r["perimetre"] == "departement"
                                and r["dep_code"] == departement), None)
                    reseau["qualite"] = {
                        "periode": p, "oi": (res or dep or {}).get("oi"),
                        "maison_mere": (res or dep or {}).get("maison_mere"),
                        "pannes": res and _situer(conn, p, "reseau", "taux_pannes",
                                                  res["taux_pannes"]),
                        "echecs_raccordement": res and _situer(
                            conn, p, "reseau", "taux_echecs_raccordement",
                            res["taux_echecs_raccordement"]),
                        # Publié au seul périmètre départemental par l'ARCEP.
                        "abonnes_avec_panne": dep and _situer(
                            conn, p, "departement", "taux_abonnes_avec_panne",
                            dep["taux_abonnes_avec_panne"]),
                    }

    mobile = None
    if table_exists(conn, "telecoms_sites_mobiles"):
        lignes = rows(conn, """
            SELECT *, COALESCE(id_site_partage, num_site) AS site FROM telecoms_sites_mobiles
             WHERE trimestre=(SELECT MAX(trimestre) FROM telecoms_sites_mobiles)
             ORDER BY distance_km, nom_op
        """)
        if lignes:
            sites: dict[str, dict] = {}
            for l in lignes:
                s = sites.setdefault(l["site"], {
                    "site": l["site"], "commune": l["nom_com"], "insee": l["insee_com"],
                    "distance_km": l["distance_km"], "zones_blanches": False,
                    "couverture_ciblee": False, "cinq_g": False, "operateurs": []})
                s["zones_blanches"] |= bool(l["site_zb"])
                s["couverture_ciblee"] |= bool(l["site_dcc"])
                s["cinq_g"] |= bool(l["site_5g"])
                s["operateurs"].append({"nom": l["nom_op"], **{
                    t: bool(l[f"site_{t}"]) for t in ("2g", "3g", "4g", "5g")}})
            tous = list(sites.values())
            cinq_g = [s for s in tous if s["cinq_g"]]
            mobile = {
                "trimestre": lignes[0]["trimestre"], "rayon_km": rayon_km,
                "sites": len(tous),
                "dans_la_commune": [s for s in tous if s["insee"] == insee],
                "plus_proche_5g": cinq_g[0] if cinq_g else None,
                "zones_blanches": sum(1 for s in tous if s["zones_blanches"]),
                "couverture_ciblee": sum(1 for s in tous if s["couverture_ciblee"]),
            }

    pannes = None
    if table_exists(conn, "telecoms_indispo_jours"):
        j = row(conn, "SELECT COUNT(*) AS jours, MIN(jour) AS du, MAX(jour) AS au "
                      "FROM telecoms_indispo_jours")
        if j and j["jours"]:
            pannes = {**j, "declarees": conn.execute(
                "SELECT COUNT(*) FROM telecoms_indisponibilites WHERE code_insee=? "
                "AND jour BETWEEN ? AND ?", (insee, j["du"], j["au"])).fetchone()[0]}

    return {"insee": insee, "fixe": fixe, "reseau": reseau, "mobile": mobile, "pannes": pannes}


def export_enfance(conn, insee: str, epci: str, departement: str) -> dict | None:
    """Les écoles de la commune, rentrée par rentrée, et l'accueil des moins de
    trois ans dans l'intercommunalité."""
    ecoles = []
    if table_exists(conn, "ecoles_effectifs") and table_exists(conn, "etablissements_scolaires"):
        for e in rows(conn, """
                -- Le nom de l'ANNUAIRE, pas celui de la fiche : la fiche a pu être
                -- adoptée d'une autre source (« École élémentaire »), alors que
                -- les effectifs sont ceux de l'école entière, maternelle comprise.
                SELECT s.uai, json_extract(s.raw_data, '$.nom_etablissement') AS nom,
                       s.nature, s.secteur, s.etat
                  FROM etablissements_scolaires s
                 WHERE json_extract(s.raw_data, '$.code_commune') = ?
                   AND s.uai IN (SELECT uai FROM ecoles_effectifs) ORDER BY s.uai""", (insee,)):
            ecoles.append({
                **e,
                "serie": rows(conn, "SELECT rentree, eleves, maternelle, classes"
                                    " FROM ecoles_effectifs WHERE uai=? ORDER BY rentree", (e["uai"],)),
                "ips": rows(conn, """
                    SELECT rentree, ips, ips_france_public AS france_public,
                           ips_departement_public AS departement_public
                      FROM ecoles_ips WHERE uai=? AND ips IS NOT NULL ORDER BY rentree""",
                            (e["uai"],)) if table_exists(conn, "ecoles_ips") else [],
            })
    accueil = None
    if epci and table_exists(conn, "accueil_petite_enfance"):
        serie = rows(conn, """
            SELECT annee, creche, assistantes, domicile, ecole, total, taux
              FROM accueil_petite_enfance WHERE portee='epci' AND code=? ORDER BY annee""", (epci,))
        if serie:
            # Les repères ne valent qu'à ANNÉE ÉGALE : la CAF publie le
            # département et la France sur moins d'années que l'intercommunalité.
            repere = lambda portee, code, annee: (row(conn, """
                SELECT taux FROM accueil_petite_enfance WHERE portee=? AND code=? AND annee=?""",
                                                      (portee, code, annee)) or {}).get("taux")
            for s in serie:
                s["departement"] = repere("departement", departement, s["annee"])
                s["france"] = repere("france", "", s["annee"])
            accueil = {"serie": serie, "dernier": serie[-1]}
    if not ecoles and not accueil:
        return None
    return {"insee": insee, "ecoles": ecoles, "accueil": accueil}


def export_reperes_fiscaux(conn) -> list[dict]:
    """Où se place un taux parmi les communes qui lèvent la même taxe."""
    if not table_exists(conn, "fiscalite_reperes"):
        return []
    reperes = rows(conn, """
        SELECT insee, annee, indicateur, portee, code, taux, communes, mediane, au_moins_autant
          FROM fiscalite_reperes ORDER BY insee, indicateur, annee, portee DESC""")
    for r in reperes:
        r["part_au_moins_autant"] = (round(100 * r["au_moins_autant"] / r["communes"], 1)
                                     if r["communes"] and r["au_moins_autant"] is not None else None)
    return reperes


# ── Le conseil en clair : ce que l'atelier a RETENU, et rien d'autre ─────────
#
# Une feuille « en clair » est un texte rédigé sur une séance — souvent par un
# LLM sur le poste de l'opérateur —, pas un fait collecté. Elle suit donc la
# règle inverse des lignes importées (`collectors/verdict.py`,
# OBJETS_A_RETENIR) : publiée seulement si un validateur l'a retenue, ET si le
# vérificateur ne lui trouve aucune faute au moment de publier. Une source
# corrigée depuis la relecture peut rendre fausse une feuille retenue : elle
# sort alors du site jusqu'à nouvelle relecture, et le compte-rendu le dit.
# Depuis le 01/10/2026, elle sort aussi telle qu'elle a été RELUE : un relevé
# modifié après avoir été retenu ne porte plus l'empreinte retenue, et attend
# une nouvelle relecture (`verdict.publiable_tel_quel`).

def _liens_en_clair(releve: dict, graphe) -> dict:
    """n° d'acte d'une séance relevée → l'acte publié, par sa clé datée. Une
    séance en clair relève ses actes par leur NUMÉRO : c'est la clé
    (`c-2026-41`), pas l'identifiant en base, qui les relie. Un numéro dont
    l'acte n'est pas publié reste du texte."""
    from collectors.cle_acte import TYPE_ACTE, cle_acte
    prefixe = {"cm": "c", "cc": "cc"}.get(releve.get("code", ""))
    date = (releve.get("seance") or {}).get("date")
    if not prefixe or not date or graphe is None:
        return {}
    liens = {}
    for acte in releve.get("actes", []):
        c = cle_acte(TYPE_ACTE[prefixe], date, str(acte.get("n")))
        a = graphe.index.acte(c.valeur) if c else None
        if a:
            liens[acte["n"]] = a
    return liens


def export_en_clair(conn, out: Path, root: Path, graphe=None) -> dict:
    from collectors.en_clair.rendu import document, feuilles, page_erreurs
    from collectors.en_clair.seances import nom_de_fichier, releves, seance_id
    from collectors.en_clair.verifier import verifier
    from collectors.dossiers import a_la_colonne_empreinte
    from collectors.verdict import empreinte, publiable_si_retenu

    dossier = out / "conseils"
    dossier.mkdir(parents=True, exist_ok=True)
    for f in dossier.glob("*.html"):         # miroir : une feuille retirée sort
        f.unlink()
    index, ecartes = [], {"non_retenus": 0, "en_faute": [], "sans_seance": [],
                          "modifies": []}
    emp = "empreinte" if a_la_colonne_empreinte(conn) else "NULL AS empreinte"
    for chemin, r in releves(root):
        sid = seance_id(conn, r)
        if sid is None:
            ecartes["sans_seance"].append(chemin.parent.name)
            continue
        a = row(conn, f"SELECT review_status, reviewed_at, {emp} FROM annotations "
                      "WHERE object_type='en_clair' AND object_id=?", (sid,))
        if not a or not publiable_si_retenu(a["review_status"]):
            ecartes["non_retenus"] += 1
            continue
        if a["empreinte"] != empreinte(chemin.read_bytes()):
            # Retenu sur un autre texte (ou avant que l'empreinte existe, et
            # pas encore repris par scripts/reprendre_empreintes.py).
            ecartes["modifies"].append(chemin.parent.name)
            continue
        if verifier(chemin):
            ecartes["en_faute"].append(chemin.parent.name)
            continue
        # La mention publique ne porte pas l'adresse du relecteur : une date suffit
        # à dire que quelqu'un a regardé et l'assume.
        relu = f"relu à l'atelier le {(a['reviewed_at'] or '')[:10]}"
        nom = nom_de_fichier(r)
        s = r["seance"]
        actes_lies = _liens_en_clair(r, graphe)
        for acte in actes_lies.values():
            graphe.citer(acte.cle, {"type": "en_clair", "date": s["date"],
                                 "assemblee": s["assemblee_court"],
                                 "fichier": f"conseils/{nom}.html"})
        (dossier / f"{nom}.html").write_text(document(
            f"Le conseil en clair · {s['assemblee_court']} · {s['date']}",
            feuilles(r, relu=relu, liens={n: x.url for n, x in actes_lies.items()})
            + page_erreurs(r),
            retour=("/conseils", "Toutes les séances")), encoding="utf-8")
        ap = r["en_clair"]["apres"]
        index.append({
            "date": s["date"],
            "assemblee": s["assemblee_court"],
            "code": r.get("code"),
            "titre": ap.get("titre") if ap.get("statut") != "non_publie" else "Actes non publiés",
            "actes": len(r.get("actes", [])),
            "unanimite": sum(1 for x in r.get("actes", []) if (x.get("vote") or {}).get("unanimite")),
            "fichier": f"conseils/{nom}.html",
            "relu_le": (a["reviewed_at"] or "")[:10],
        })
    index.sort(key=lambda x: (x["date"], x["code"] or ""))
    write_json(out / "conseils.json", {"seances": index, "total": len(index)})
    return {"publiees": len(index), **ecartes}


# Les dossiers thématiques suivent la même règle depuis le 01/10/2026 : publiés
# RETENUS à l'atelier, et tels qu'ils ont été relus. Le site ne lit plus le
# répertoire `dossiers/` de l'instance : il lit `dossiers.json`, écrit ici, qui
# ne contient que ce qui sort. Un dossier écarté ou en cours de réécriture n'y
# figure pas — il n'a ni page ni URL.

#
# Depuis le 03/10/2026, chaque dossier publié passe par le résolveur de
# citations (`collectors/citations.py`) : son markdown sort RELIÉ — les « (CM du
# 14/04/2021) » deviennent des liens vers l'acte publié —, avec la liste de ses
# citations pour les infobulles, et, si un acte cité a changé depuis la
# relecture, l'état de péremption (`collectors/dossiers.py::peremption`). Le
# dossier reste publié dans ce cas : il a été relu, et le bandeau le dit.

def export_dossiers(conn, out: Path, root: Path, graphe=None) -> dict:
    from collectors.dossiers import entete, identifiant, peremption, publiables
    from collectors.graphe import Graphe
    graphe = graphe or Graphe()
    sortis, ecartes = publiables(conn, root)
    citations = Counter()
    perimes = []
    for d in sortis:
        meta, _ = entete(d["texte"])
        if meta.get("statut") == "a_developper":
            continue            # son corps ne sort pas : rien à relier
        r = graphe.dossier(d["slug"], meta.get("titre") or d["slug"], d["texte"])
        d["texte"] = r["relie"].texte
        if r["citations"]:
            d["citations"] = r["citations"]
        for c in r["relie"].citations:
            citations[c.resolution.statut] += 1
        p = peremption(conn, identifiant(conn, d["slug"]), d["empreinte"], graphe.index)
        if p and p["elements"]:
            for el in p["elements"]:
                if el["quoi"] == "modifie" and (t := graphe.titre_public(el["cle"])):
                    el["titre"] = t
            d["perime"] = p
            perimes.append(d["slug"])
    write_json(out / "dossiers.json", {"dossiers": sortis, "total": len(sortis)})
    return {"publies": len(sortis), **ecartes, "citations": dict(citations),
            "perimes": perimes}


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
INSEE_PUBLIABLES = """
    SELECT insee, commune, dataset, indicateur, libelle, annee, valeur, dims
      FROM insee_indicateurs
     WHERE dataset <> 'DS_BPE'
     ORDER BY dataset, indicateur, annee
"""


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

        counters = Counter()
        counters["entities_sans_perimetre"] = faits["sans_perimetre"]
        counters["revue_annotations"] = faits["revue_annotations"]

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
        counters["flows_par_etat"] = faits["flows_par_etat"]

        public_layers = faits["public_layers"]

        budget_annuel = faits["budget_annuel"]
        budget_annexe = faits["budget_annexe"]
        ofgl_data = faits["ofgl_data"]
        budget_vote = faits["budget_vote"]
        dvf_data = faits["dvf_data"]
        marches_data = faits["marches_data"]
        approbations_data = faits["approbations_data"]

        # ── Portrait de territoire (INSEE) ────────────────────────────────────
        insee_data = rows(conn, INSEE_PUBLIABLES) \
            if table_exists(conn, "insee_indicateurs") else []

        # Équipements et services (BPE). `geo_type` distingue le communal de
        # l'intercommunal : l'INSEE ne publie l'ÉVOLUTION qu'à partir de l'EPCI,
        # et une page qui présenterait cette trajectoire comme communale
        # mentirait. Le champ voyage donc jusqu'au JSON.
        equipements = rows(conn, """
            SELECT geo_type, geo_code, geo_nom, annee, niveau, code, libelle, nombre
              FROM equipements ORDER BY geo_type, annee, niveau, code
        """) if table_exists(conn, "equipements") else []

        # Transport déclaré et dispositifs de l'État. Seuls les arrêts DANS la
        # commune sortent : ceux que la boîte englobante a ramassés chez le
        # voisin gonfleraient la desserte communale. Leur nombre est publié à
        # part, pour que l'écart reste lisible.
        mobilite_aom = rows(conn, """
            SELECT insee, nom, siren, forme, departement FROM mobilite_aom
        """) if table_exists(conn, "mobilite_aom") else []
        mobilite_arrets = rows(conn, """
            SELECT insee, reseau, arret, lat, lng FROM mobilite_arrets
             WHERE dans_commune = 1 ORDER BY reseau, arret
        """) if table_exists(conn, "mobilite_arrets") else []
        arrets_hors_commune = (conn.execute(
            "SELECT COUNT(*) FROM mobilite_arrets WHERE dans_commune = 0").fetchone()[0]
            if table_exists(conn, "mobilite_arrets") else 0)
        dispositifs = rows(conn, """
            SELECT insee, code, libelle, reference FROM dispositifs_etat
             ORDER BY insee, libelle
        """) if table_exists(conn, "dispositifs_etat") else []

        # Cadastre : le parcellaire ne se publie pas parcelle par parcelle (des
        # milliers de lignes qu'aucune page ne lit), mais son RÉSUMÉ situe le
        # territoire — combien de parcelles, quelle surface cadastrée.
        cadastre_resume = rows(conn, """
            SELECT insee, COUNT(*) AS parcelles, COUNT(DISTINCT section) AS sections,
                   SUM(contenance) AS contenance_m2
              FROM cadastre_parcelles GROUP BY insee
        """) if table_exists(conn, "cadastre_parcelles") else []

        # Un statut déclaré est une promesse ; la date de dernière collecte est
        # un fait. C'est elle qui permet à un lecteur de vérifier le statut sans
        # croire personne : au bout de six mois, un portage de démonstration
        # affiche six mois. On prend la collecte, JAMAIS la publication — une
        # republication ne recollecte rien et ferait passer un site figé pour
        # un site vivant.
        derniere_collecte = None
        if table_exists(conn, "collector_runs"):
            _r = rows(conn, "SELECT MAX(started_at) AS d FROM collector_runs")
            derniere_collecte = (_r[0]["d"] or "")[:10] or None if _r else None

        stats = {
            "generated_at": horloge.isoformat(timespec="seconds"),
            "statut": {**STATUT, "derniere_collecte": derniere_collecte},
            "entities_total_private": len(entity_rows),
            "entities_public": len(public_entities),
            # Contrôle de publication : un site communal qui publierait
            # massivement du C2 aurait changé de nature sans qu'on le décide.
            "entities_public_par_perimetre": dict(
                Counter(e.get("perimetre") or "non_classe" for e in public_entities)),
            "entities_privees_par_perimetre": dict(
                Counter(e.get("perimetre") or "non_classe" for e in entity_rows)),
            # Entités jamais classées : exclues de la publication, comptées ici
            # pour que la lacune se voie au lieu de se deviner.
            "entities_sans_perimetre": counters["entities_sans_perimetre"],
            "conseil_communautaire": len(ids_conseil_communautaire),
            "relations_total_private": len(relation_rows),
            "relations_public": len(public_relations),
            "events_total_private": len(event_rows),
            "events_public": len(public_events),
            # « 5 377 décisions » à l'accueil : le mot promettait un registre
            # des décisions locales et livrait le total des événements publics,
            # dont 3 061 annonces BODACC — la vie des entreprises, que personne
            # n'a votée — et 440 autorisations d'urbanisme individuelles. Un
            # habitant lisait « le conseil a pris 5 377 décisions ».
            # Ce qui a été délibéré se compte à part, et c'est ce chiffre-là que
            # l'accueil affiche. Le total reste publié, sous son vrai nom.
            "deliberations_public": sum(
                1 for e in public_events if e["type"] in TYPES_DELIBERES),
            # Le compteur unique disait « 1 997 délibérations » sur la page de
            # garde d'un site COMMUNAL, dont 833 votées par une autre assemblée.
            # Les deux chiffres existent, ils n'ont pas à être additionnés pour
            # être annoncés.
            "deliberations_public_par_portee": dict(Counter(
                e["portee"] for e in public_events if e["type"] in TYPES_DELIBERES)),
            "events_public_par_portee": dict(
                Counter(e.get("portee") for e in public_events)),
            # « 744 entreprises » comptait 377 fiches cessées. Le volume d'un
            # annuaire n'est pas l'état d'un territoire : les deux se comptent.
            "entities_public_par_activite": {
                t: dict(Counter(
                    "en_activite" if e.get("actif") is True
                    else "cessee" if e.get("actif") is False else "inconnu"
                    for e in public_entities if e["type"] == t))
                for t in ("business", "association")},
            "entreprises_publiques_par_nature": dict(Counter(
                e.get("nature") for e in public_entities
                if e["type"] == "business")),
            "events_public_par_type": dict(
                Counter(e["type"] for e in public_events)),
            # Dette de réplication, mesurée et non promise (cf. /methode).
            "replicabilite": mesurer_replicabilite(),
            # Répartition sur les trois axes de provenance. C'est ce qui rend
            # la promesse mesurable : sans ces compteurs, « source primaire »
            # serait une affirmation de plus, invérifiable de l'extérieur.
            "provenance": {
                axe: dict(Counter(e.get(axe) for e in public_events))
                for axe in ("provenance", "document", "traitement")
            },
            "flows_total_private": len(flow_rows),
            "flows_public": len(public_flows),
            # Ce que les pièces attestent, en un coup d'oeil : sur Lasalle,
            # 123 votés, 36 payés, 2 engagés. Le compteur était calculé mais
            # restait dans un `Counter` local, donc invisible.
            "flows_par_etat": dict(counters["flows_par_etat"]),
            "budget_annuel_rows": len(budget_annuel),
            "budget_annexe_rows": len(budget_annexe),
            "ofgl_rows": len(ofgl_data),
            "dvf_rows": len(dvf_data),
            "marches_rows": len(marches_data),
            "approbations_rows": len(approbations_data),
            "urls_public_confirmed": sum(len(e["urls"]) for e in public_entities),
            "map_features_public": sum(len(v) for v in public_layers.values()),
            "location_quality": dict(location_quality),
            "exclusions": {section: dict(counts) for section, counts in exclusions.items()},
        }

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

        out.mkdir(parents=True, exist_ok=True)
        write_json(out / "stats.json", stats)
        write_json(out / "couverture.json", export_couverture(conn, public_events, stats))
        write_json(out / "entities.json", {"entities": public_entities, "total": len(public_entities)})
        write_json(out / "relations.json", {"relations": public_relations, "total": len(public_relations)})
        write_json(out / "events.json", {"events": public_events, "total": len(public_events)})
        write_json(out / "event_links.json",
                   {"links": public_links, "total": len(public_links)})
        write_json(out / "flows.json", {"flows": public_flows, "total": len(public_flows)})
        for layer, features in public_layers.items():
            write_json(out / "layers" / f"{layer}.geojson", {
                "type": "FeatureCollection",
                "features": features,
            })
        write_json(out / "budget.json", {"annuel": budget_annuel, "annexe": budget_annexe})
        write_json(out / "budget_vote.json", {"budget_vote": budget_vote, "total": len(budget_vote)})
        write_json(out / "ofgl.json", {"ofgl": ofgl_data, "total": len(ofgl_data)})
        write_json(out / "dvf.json", {"dvf": dvf_data, "total": len(dvf_data)})
        write_json(out / "marches.json", {"marches": marches_data, "total": len(marches_data)})
        write_json(out / "approbations.json",
                   {"approbations": approbations_data, "total": len(approbations_data)})
        write_json(out / "territoire.json", {
            "insee": insee_data,
            "total": len(insee_data),
            "equipements": equipements,
            "mobilite_aom": mobilite_aom,
            "mobilite_arrets": mobilite_arrets,
            "mobilite_arrets_hors_commune": arrets_hors_commune,
            "dispositifs_etat": dispositifs,
            "cadastre": cadastre_resume,
            "telecoms": export_telecoms(conn, INSEE_C1, DEPARTEMENT, TELECOMS_RAYON_KM),
            "enfance": export_enfance(conn, INSEE_C1, EPCI_SIREN_C2, DEPARTEMENT),
        })

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

        # ── Lot 2 : élections, fiscalité, élus officiels, urbanisme ───────────
        # Publication arbitrée le 26/07/2026. Aucune de ces sources ne portait de
        # page publique alors qu'elles répondent à des questions de premier plan
        # (« combien ont voté ? », « de combien sont mes impôts ? »).
        elections = {}
        if table_exists(conn, "elections_resultats"):
            elections["resultats"] = rows(conn, """
                SELECT scrutin, tour, date_tour, insee, commune, inscrits, votants,
                       abstentions, exprimes, blancs, nuls,
                       ROUND(100.0*votants/NULLIF(inscrits,0), 2) AS participation_pct
                FROM elections_resultats ORDER BY scrutin, tour, commune
            """)
            elections["listes"] = rows(conn, """
                SELECT scrutin, tour, insee, rang, libelle, libelle_abrege, nuance,
                       tete_de_liste, voix, pct_exprimes, sieges_cm, sieges_cc
                FROM elections_listes ORDER BY scrutin, tour, insee, voix DESC
            """)
        write_json(out / "elections.json", elections)

        # `portee` distingue la part votée par la commune du total acquitté :
        # attribuer le taux global au conseil municipal serait faux.
        fiscalite = rows(conn, """
            SELECT insee, commune, annee, indicateur, libelle, portee, taux, epci
            FROM fiscalite_taux ORDER BY annee DESC, commune, indicateur
        """) if table_exists(conn, "fiscalite_taux") else []
        write_json(out / "fiscalite.json", {"taux": fiscalite, "total": len(fiscalite),
                                            "reperes": export_reperes_fiscaux(conn)})

        # ── L'intercommunalité (périmètre C2) ────────────────────────────────
        # Réponse publique à « qu'est-ce qui ne se décide plus à la mairie ? ».
        # Trois briques : ce que l'EPCI exerce à la place de la commune, qui
        # siège pour en décider, et où Lasalle se situe parmi ses pairs.
        # Les entités des 14 autres communes ne sont pas publiées en fiche
        # (cf. `publiable_dans_perimetre`) : elles n'existent ici qu'agrégées.
        competences = rows(conn, """
            SELECT code, libelle, categorie, obligatoire, interet_communautaire
            FROM epci_competences
            ORDER BY obligatoire DESC, categorie, libelle
        """) if table_exists(conn, "epci_competences") else []

        # Un même délégué porte plusieurs relations `élu_cc` — une par source
        # (banatic, rne, cc_cac_site, élections_2026). Deux filtres, et l'ordre
        # entre les deux compte :
        #
        # 1. `until` — les mandats de source BANATIC (état du 15/10/2025) et du
        #    site de la CC (mandat 2020-2026) sont clos au 15/03/2026 par
        #    une reprise ponctuelle des mandats. Sans ce filtre, la page
        #    annonçait Gilles BEAUMANOIR président et Irène CHAPUIS
        #    vice-présidente : trois des quatre premiers noms de la liste
        #    n'étaient plus délégués depuis les municipales de mars 2026.
        # 2. déduplication par personne, en préférant la source la plus récente
        #    (RNE, publication du 11/08/2026) — sinon `nb_relations` double.
        delegues_bruts = rows(conn, """
            SELECT e.id, e.name, e.commune, r.relation_type, r.source, r.metadata
            FROM relations r
            JOIN entities e ON e.id = r.from_id
            WHERE r.relation_type IN ('élu_cc','vice_président_cc','président_cc')
              AND r.confidence IN ('verified','confirmed')
              AND e.confidence IN ('verified','confirmed')
              AND (r.until IS NULL OR r.until > ?)
            ORDER BY CASE r.source WHEN 'rne' THEN 0
                                   WHEN 'élections_2026' THEN 1 ELSE 2 END,
                     CASE r.relation_type
                       WHEN 'président_cc' THEN 0
                       WHEN 'vice_président_cc' THEN 1 ELSE 2 END
        """, (jour_utc(horloge),))
        # Commune d'élection du délégué, prise dans le fichier RNE des
        # conseillers MUNICIPAUX — pas dans le fichier EPCI, qui rattache 22 des
        # 27 délégués à Val-d'Aigoual, commune du siège de l'intercommunalité.
        # `entities.commune` ne suffit pas : elle est vide pour les 8 délégués
        # créés par le seul import EPCI (BALSAN, BOSIO, EL RHAZOUI, FOUGERAY,
        # LIRON, PIALOT, ROMAZZOTTI, SERRAL), qui apparaissaient donc sans
        # commune. Recoupé avec BANATIC, ce rattachement rend exactement la
        # répartition des sièges par commune.
        commune_election = {
            r["entity_id"]: r["commune"] for r in rows(conn, """
                SELECT entity_id, commune FROM elus_rne
                WHERE mandat = 'cm' AND entity_id IS NOT NULL AND commune IS NOT NULL
            """)
        } if table_exists(conn, "elus_rne") else {}

        # Un RENOUVELLEMENT invalide toute liste antérieure.
        #
        # Le filtre `until` ci-dessus ne suffit pas : aucune source ne clôt les
        # mandats qu'elle publie, et la clôture posée à la main le 15/03/2026
        # avait disparu à la recollecte suivante. BANATIC, lui, DATE son état
        # (`etat_au`, écrit par le collecteur) : il suffit de le comparer à la
        # dernière élection municipale connue de la base. Un état arrêté au
        # 15/10/2025 décrit la mandature d'avant mars 2026 — ses 28 délégués
        # s'ajoutaient aux 22 du RNE et la page en annonçait 45.
        #
        # Les sources non datées sont conservées : on n'écarte que ce qu'on sait
        # périmé, jamais ce qu'on ignore.
        dernier_scrutin = (conn.execute(
            "SELECT MAX(date) FROM events WHERE type = 'election'").fetchone() or [None])[0]

        par_personne: dict[int, dict] = {}
        perimes: list[str] = []
        for d in delegues_bruts:
            if d["id"] in par_personne:
                continue
            etat_au = relation_meta_publique(d.get("metadata")).get("etat_au")
            if dernier_scrutin and etat_au and etat_au < dernier_scrutin:
                perimes.append(f"{d['name']} ({d['source']}, état du {etat_au})")
                continue
            fonction = relation_meta_publique(d.get("metadata")).get("fonction_rne") \
                or {"président_cc": "Président",
                    "vice_président_cc": "Vice-président"}.get(d["relation_type"],
                                                               "Délégué")
            commune = commune_election.get(d["id"]) or d["commune"]
            par_personne[d["id"]] = {
                "name": d["name"],
                "commune": commune,
                # Vrai quand la commune vient du RNE des conseillers municipaux,
                # qui donne la commune d'élection. Faux quand elle n'est que le
                # rattachement de l'entité, non recoupé : l'UI ne doit pas
                # l'afficher comme un fait établi.
                "commune_fiable": d["id"] in commune_election,
                "relation_type": d["relation_type"],
                "fonction": fonction,
                "source": d["source"],
            }
        ordre = {"président_cc": 0, "vice_président_cc": 1}
        delegues = sorted(par_personne.values(),
                          key=lambda d: (ordre.get(d["relation_type"], 2),
                                         d["commune"] or "", d["name"]))

        # Comparaison de Lasalle à ses pairs. Le nombre de sièges au conseil
        # communautaire face au poids démographique est l'information la plus
        # parlante : c'est le pouvoir de vote réel de chaque commune.
        #
        # Il est compté sur la SEULE source BANATIC, et sur les relations CLOSES
        # aussi bien qu'actives — d'où une requête distincte de celle des
        # délégués. La répartition des sièges est fixée par arrêté préfectoral :
        # elle survit au scrutin, seuls les NOMS changent. Le RNE, lui, est
        # inexploitable pour ce décompte : il range 22 délégués sur 27 sous
        # Val-d'Aigoual, commune du siège de l'EPCI, et laisserait 13 communes
        # membres à zéro siège. Cf. memory-bank/known-issues.md.
        sieges = Counter(
            r["commune"] for r in rows(conn, """
                SELECT DISTINCT e.id, e.commune
                FROM relations r
                JOIN entities e ON e.id = r.from_id
                WHERE r.relation_type IN ('élu_cc','vice_président_cc','président_cc')
                  AND r.source = 'banatic'
                  AND e.confidence IN ('verified','confirmed')
            """) if r["commune"])
        delegues_hors_banatic = 0
        membres = []
        for insee, meta in COMMUNES_EPCI.items():
            nom = meta["nom"]
            membres.append({
                "insee": insee,
                "nom": nom,
                "population": meta.get("population"),
                "sieges": sieges.get(nom, 0),
                "est_commune_du_site": insee == INSEE_C1,
            })
        membres.sort(key=lambda m: -(m["population"] or 0))

        syndicats = rows(conn, """
            SELECT t.name, t.id
            FROM relations r
            JOIN entities t ON t.id = r.to_id
            WHERE r.relation_type = 'adhère_à' AND r.source = 'banatic'
              AND t.confidence IN ('verified','confirmed')
            ORDER BY t.name
        """)

        write_json(out / "intercommunalite.json", {
            "nom": EPCI_NOM_C2,
            "siren": EPCI_SIREN_C2,
            "population": sum((m["population"] or 0) for m in membres),
            "competences": competences,
            "competences_obligatoires": sum(1 for c in competences if c["obligatoire"]),
            "delegues": delegues,
            "membres": membres,
            "syndicats": syndicats,
            # Honnêteté de la source, à afficher tel quel par l'UI : les noms et
            # la répartition des sièges ne viennent pas du même endroit.
            "sieges_source": "BANATIC (répartition arrêtée le 15/10/2025)",
            "delegues_source": "Répertoire National des Élus (publication du 11/08/2026)",
            # Ce qui a été écarté comme périmé, et pourquoi : un compteur qui
            # tombe de 45 à 22 doit pouvoir s'expliquer sans relire le code.
            "delegues_ecartes": len(perimes),
            "delegues_ecartes_motif": (
                f"listes antérieures au scrutin du {dernier_scrutin}" if perimes else ""),
            "delegues_a_confirmer": delegues_hors_banatic,
            "note_sources": (
                "Les délégués sont ceux du Répertoire National des Élus, "
                "postérieur aux élections municipales de mars 2026. La "
                "répartition des sièges par commune vient de BANATIC : elle est "
                "fixée par arrêté préfectoral et ne change pas avec le scrutin. "
                "La commune de chaque délégué est celle de son mandat municipal "
                "au RNE : le fichier RNE des conseillers communautaires, lui, "
                "rattache 22 des 27 délégués au siège de l'intercommunalité et "
                "non à leur commune d'élection."
            ),
        })

        # Élus : source autoritaire DGCL. `birth_year` et la CSP restent privés
        # (`publication_rules.people.publish_birth_year = false`).
        #
        # Filtrage sur les 15 communes de l'EPCI. `elus_rne` en contient
        # davantage : la collecte du 26/07/2026 portait sur l'ancien périmètre —
        # les 7 communes du vallon de la Salindrenque — et le recadrage du
        # 11/08 a délibérément conservé ces lignes en base (elles servent à
        # détecter les mandats croisés, cf. activeContext). Publiées telles
        # quelles, elles faisaient apparaître 20 conseils municipaux dont ceux
        # de Colognac, Vabres, Thoiras-Corbès, Sainte-Croix-de-Caderle et
        # Saint-Bonnet-de-Salendrinque, qui relèvent d'autres EPCI. Le filtre va
        # ici, pas dans une purge : la donnée reste exploitable en interne.
        elus = rows(conn, f"""
            SELECT mandat, insee, commune, nom, prenom, fonction,
                   date_debut_mandat, date_debut_fonction, epci_nom, entity_id
            FROM elus_rne
            WHERE insee IN ({",".join("?" * len(COMMUNES_EPCI))})
            ORDER BY commune, mandat, nom
        """, tuple(COMMUNES_EPCI)) if table_exists(conn, "elus_rne") else []

        # `fiche` : cet élu a-t-il une page `/entite/<id>` sur le site ?
        #
        # NON pour la plupart. `publiable_dans_perimetre()` n'accorde de fiche à
        # une personne C2 que si elle SIÈGE au conseil communautaire ; les
        # conseillers municipaux des autres communes membres n'en ont pas, et
        # c'est délibéré (leur fiche agrégerait mandats, sociétés et marchés
        # pour des élus sans pouvoir de décision sur la commune).
        #
        # L'export les portait quand même avec leur `entity_id`, et la page en
        # faisait un lien : 152 liens morts sur Lasalle, 176 sur Brassac, 191
        # sur Saillans — soit 78 à 90 % des élus affichés, en production, vers
        # un 404. Relevé par un audit externe le 21/08/2026.
        #
        # La composition d'un conseil municipal reste publiée : c'est une donnée
        # du Répertoire National des Élus, registre public rediffusable. C'est
        # la FICHE qui est refusée, pas le nom. Seul cet endroit connaît
        # `public_ids` — la page ne peut pas recalculer ce booléen, et ne doit
        # pas essayer.
        elus = [{**e, "fiche": e.get("entity_id") in public_ids} for e in elus]
        write_json(out / "elus_rne.json", {
            "elus": elus,
            "total": len(elus),
            "total_avec_fiche": sum(1 for e in elus if e["fiche"]),
            "note_fiche": (
                "`fiche: false` signale un élu publié sans page dédiée : sa "
                "commune relève de l'intercommunalité et il ne siège pas au "
                "conseil communautaire. Ne pas construire de lien "
                "/entite/<entity_id> pour ces lignes."
            ),
        })

        urbanisme_rows = rows(conn, """
            SELECT num_dau, insee, commune, categorie, type_dau, type_label,
                   date_depot, date_autorisation, date_achevement,
                   demandeur_nom, demandeur_siren, demandeur_entity_id,
                   adresse, lieu_dit, cadastre_ref, superficie_terrain,
                   nb_logements, surface_hab_creee, surface_loc_creee, residence
            FROM urbanisme_autorisations ORDER BY date_depot DESC, commune
        """) if table_exists(conn, "urbanisme_autorisations") else []
        urbanisme_public = []
        adresses_retirees = 0
        renvois_retires = 0
        for u in urbanisme_rows:
            u = dict(u)
            # Prudence : sans personne morale nommée, le demandeur est un
            # particulier. On garde le lieu-dit et la parcelle (le croisement DVF
            # et la lecture territoriale sont préservés) mais pas la voie exacte.
            if not u.get("demandeur_nom"):
                if u.get("adresse"):
                    adresses_retirees += 1
                u["adresse"] = None
            # Un identifiant d'entité PROMET une fiche. Le demandeur d'un permis
            # est très souvent hors périmètre publiable — 66 lignes sur Lasalle,
            # 199 sur Brassac, 168 sur Saillans pointaient vers une fiche
            # absente. Aucune page du site ne lit ce champ ; il ne sert donc
            # qu'au lecteur du JSON, à qui il ment. On le retire plutôt que de
            # le laisser désigner un 404.
            if u.get("demandeur_entity_id") and u["demandeur_entity_id"] not in public_ids:
                u["demandeur_entity_id"] = None
                renvois_retires += 1
            u["date_precision"] = "annee"   # cf. contrôle de divulgation SDES
            urbanisme_public.append(u)
        # Le document d'urbanisme au GPU, et ce qu'il fait du territoire. Les
        # parts ne sortent QUE si la couverture a été vérifiée — le collecteur
        # les laisse à NULL sinon, et le JSON transporte le contrôle avec elles.
        plu_documents = rows(conn, """
            SELECT insee, partition, titre, du_type, portee, date_appro,
                   gpu_status, gpu_maj
              FROM urbanisme_documents WHERE couvre = 1 ORDER BY insee, date_appro
        """) if table_exists(conn, "urbanisme_documents") else []
        plu_zonage = rows(conn, """
            SELECT insee, typezone, famille, zones, aire_m2, part_pct, couverture
              FROM urbanisme_zonage ORDER BY insee, part_pct DESC
        """) if table_exists(conn, "urbanisme_zonage") else []
        plu_statut = rows(conn, """
            SELECT insee, nom, rnu, aire_km2, documents, releve_le
              FROM urbanisme_statut ORDER BY insee
        """) if table_exists(conn, "urbanisme_statut") else []

        write_json(out / "urbanisme.json", {
            "documents": plu_documents,
            "zonage": plu_zonage,
            "statut": plu_statut,
            "autorisations": urbanisme_public,
            "total": len(urbanisme_public),
            "note_dates": "Dates ramenées à l'année pour les petites communes "
                          "(contrôle de divulgation statistique du SDES).",
            "renvois_demandeur_retires": renvois_retires,
        })

        # Parcelles portant à la fois une mutation DVF et une autorisation.
        croisement_foncier = rows(conn, """
            SELECT u.cadastre_ref, u.commune, u.num_dau, u.date_depot,
                   u.demandeur_nom, u.nb_logements, COUNT(d.id) AS mutations,
                   MIN(d.date) AS premiere_mutation, MAX(d.date) AS derniere_mutation
            FROM urbanisme_autorisations u
            JOIN dvf_transactions d ON d.cadastre_ref = u.cadastre_ref
            WHERE u.cadastre_ref IS NOT NULL
            GROUP BY u.id ORDER BY u.date_depot DESC
        """) if (table_exists(conn, "urbanisme_autorisations")
                 and table_exists(conn, "dvf_transactions")) else []
        write_json(out / "croisement_foncier.json", {
            "parcelles": croisement_foncier, "total": len(croisement_foncier)})

        # ── « Ce qui a changé » ───────────────────────────────────────────────
        # Le pipeline calcule déjà des deltas internes (audits/pipeline-digest.md),
        # mais un habitant ne veut pas savoir ce qui a changé dans notre base : il
        # veut savoir ce qui s'est passé dans sa commune. On construit donc le flux
        # à partir des DATES des actes publiés, ce qui a deux avantages : aucun
        # état à conserver entre deux exécutions, et un résultat toujours juste.
        aujourdhui = stats["generated_at"][:10]

        # Le genre pilote les filtres de la page. Il était fixé à « acte » pour
        # TOUS les événements : les 200 lignes d'agenda et les annonces BODACC
        # restaient invisibles au filtrage, sans onglet où les retrouver.
        def genre_evenement(t: str | None) -> str:
            t = t or ""
            if t == "local_event":
                return "vie"
            if t.startswith("bodacc"):
                return "légal"
            if t == "marché_public":
                return "marché"
            return "acte"

        actualite = []
        # Un même avis BOAMP existe en `events` ET en `marches_publics`, et la
        # table `events` porte en plus 164 doublons stricts (même URL, même
        # date) laissés par des passes de collecte successives. Sans clé de
        # dédup, la même benne à ordures s'affichait trois fois.
        vus: set[str] = set()

        def cle(url, titre, date):
            # Le titre fait TOUJOURS partie de la clé. L'URL seule regroupait
            # les 18 délibérations d'un même conseil, qui pointent toutes la
            # page du compte rendu : 17 d'entre elles disparaissaient du flux.
            return f"{safe_url(url) or ''}|{norm_nom(titre)}|{date}"

        # Les marchés d'abord : la fiche `marches_publics` porte le titulaire et
        # le montant, l'événement BOAMP équivalent ne porte que l'objet.
        for m in marches_data:
            if not m.get("date_notif"):
                continue
            k = cle(m.get("source_url"), m.get("objet"), m["date_notif"])
            if k in vus:
                continue
            vus.add(k)
            actualite.append({
                "date": m["date_notif"], "genre": "marché",
                "type": "marché_public",
                "titre": nettoyer_libelle(m.get("objet")),
                "url": safe_url(m.get("source_url")), "montant": m.get("montant"),
                "acteur_id": m.get("titulaire_id"),
                "acteur_nom": joli_nom(m.get("titulaire_nom") or m.get("acheteur_nom")),
                # C'est l'ACHETEUR qui donne la portée d'un marché, jamais le
                # titulaire : une entreprise de Nîmes qui remporte un marché de
                # la commune ne le rend pas nîmois.
                "portee": m.get("portee"),
            })

        # Combien d'actes chaque séance rassemble — (date, portée), parce que le
        # conseil municipal et le conseil communautaire peuvent siéger le même
        # jour et que leurs actes ne s'additionnent pas.
        actes_par_seance: Counter = Counter(
            (e["date"], e.get("portee")) for e in public_events
            if e["type"] in TYPES_DELIBERES and e.get("date"))

        for e in public_events:
            if not e.get("date"):
                continue
            titre = (e.get("title") or "").strip()
            if titre.lower().strip(" .:-—") in TITRES_VIDES:
                exclusions["actualite"]["titre_non_informatif"] += 1
                continue
            k = cle(e.get("source_url") or e.get("page_url"), titre, e["date"])
            if k in vus:
                exclusions["actualite"]["doublon"] += 1
                continue
            vus.add(k)
            actualite.append({
                "date": e["date"], "genre": genre_evenement(e.get("type")),
                "type": e.get("type"), "titre": titre,
                "url": e.get("source_url") or e.get("page_url"),
                "montant": e.get("montant_principal"),
                "montant_indicatif": e.get("montant_indicatif"),
                "categorie": e.get("categorie"), "id": e["id"],
                "portee": e.get("portee"),
                "corrige": e.get("corrige"), "note_revue": e.get("note_revue"),
                # Ce qu'une séance rassemble, et par quoi on l'atteint. Compté
                # ici parce que c'est le seul endroit qui voie tous les actes
                # publiés à la fois : un décompte pris en base compterait aussi
                # ceux que la publication écarte, et la page de garde
                # annoncerait plus d'actes qu'elle n'en donne à lire.
                **({"nb_actes": actes_par_seance.get(
                        (e["date"], e.get("portee")), 0),
                    "pieces": e.get("pieces"),
                    "convocation": e.get("convocation")}
                   if e.get("type") in TYPES_SEANCE else {}),
            })

        for f in public_flows:
            if not f.get("year"):
                continue
            # Le flux entrant (dotation, fonds de concours) a pour contrepartie
            # celui qui verse, pas la commune qui encaisse : afficher
            # « Commune de Lasalle » en face de la DGF n'apprend rien.
            if f.get("sens") == "entrant":
                acteur_id, acteur_nom = f.get("from_id"), f.get("from_name")
            else:
                acteur_id, acteur_nom = f.get("to_id"), f.get("to_name")
            acteur_nom = joli_nom(acteur_nom)
            libelle = nettoyer_libelle(
                f.get("description") or f.get("type_norm") or f.get("type"),
                acteur_nom, f.get("amount"))
            actualite.append({
                # Un flux n'a que son millésime : le dater au 31/12 le projetait
                # dans le futur et lui donnait la tête du flux (26 lignes au
                # 31/12/2026 sur une page « ce qui a changé » arrêtée en juillet).
                # La page les sort de la frise et les regroupe par année.
                "date": f"{f['year']}-12-31", "annee": f["year"],
                "date_approx": True, "genre": "argent",
                "type": f.get("type_norm") or f.get("type"),
                "titre": libelle or "Flux financier",
                "montant": f.get("amount"),
                "acteur_id": acteur_id, "acteur_nom": acteur_nom,
                # Une demande de subvention n'est pas une subvention reçue :
                # 240 600 € de Fonds Vert *demandés* s'affichaient comme acquis.
                "statut": f.get("statut"),
                "perimetre": f.get("perimetre"),
                # À ne pas confondre avec `perimetre` juste au-dessus, qui dit
                # « detail » ou « agregat ». `portee` dit qui agit.
                "portee": PORTEE_PAR_PERIMETRE.get(
                    perimetre_par_entite.get(acteur_id) or "") or "territoire",
                "sens": f.get("sens"),
                "corrige": f.get("corrige"), "note_revue": f.get("note_revue"),
            })

        # Tri sur une date bornée à la date d'arrêt des données : sans ça, les
        # dates approchées de l'année en cours passent devant tout le reste.
        # Tri en deux passes : le titre en ordre croissant d'abord, puis la date
        # en ordre décroissant (tri stable). Sans ça, les 18 délibérations du
        # même conseil sortaient dans l'ordre des id en base — DEL _18, _08,
        # _20, _19… — alors que leur numéro est leur ordre de séance.
        actualite.sort(key=lambda x: (x.get("titre") or ""))
        actualite.sort(
            key=lambda x: (min(x["date"], aujourdhui) if x.get("date_approx")
                           else x["date"]),
            reverse=True)
        a_venir = [i for i in actualite if i["date"] > aujourdhui and not i.get("date_approx")]
        write_json(out / "actualite.json", {
            "items": actualite[:400],
            "total": len(actualite),
            "arrete_le": aujourdhui,
            "genere_le": stats["generated_at"],
            "note": "Flux construit à partir des dates des actes publiés. "
                    "Les flux financiers n'ont qu'une année : ils portent "
                    "`date_approx` et sont regroupés par année, hors de la "
                    "frise mensuelle. Les éléments datés après `arrete_le` sont "
                    "des événements à venir.",
        })
        # `stats["exclusions"]` est figé plus haut, avant que le flux d'actualité
        # n'ait écarté ses doublons : on le réactualise, sinon le rapport de
        # revue tait précisément ce qui vient d'être filtré.
        stats["exclusions"] = {s: dict(c) for s, c in exclusions.items()}
        stats["revue_atelier"] = {
            "annotations": counters["revue_annotations"],
            "rejetes": sum(c.get("rejete_en_atelier", 0) for c in exclusions.values()),
            "corriges": sum(1 for e in public_events if e.get("corrige"))
                      + sum(1 for f in public_flows if f.get("corrige"))
                      + sum(1 for m in marches_data if m.get("corrige")),
        }
        corrections = export_corrections(public_events, public_flows, marches_data,
                                         lire_journal_corrections())
        write_json(out / "corrections.json", corrections)
        # Le graphe des liens se remplit pendant que séances et dossiers
        # s'écrivent : ce sont eux qui citent. Il ne connaît que les actes
        # PUBLIÉS (`index_actes`), jamais la base entière.
        from collectors.graphe import Graphe, personnes_morales_par_acte
        graphe = Graphe(index_actes, affiches)
        stats["conseils_en_clair"] = export_en_clair(conn, out, ROOT, graphe)
        stats["dossiers"] = export_dossiers(conn, out, ROOT, graphe)
        stats["graphe"] = graphe.ecrire(
            out,
            alias={f"a{e['id']}": e["ancre"] for e in public_events
                   if e.get("ancre") and e["ancre"] != f"a{e['id']}"},
            personnes_morales=personnes_morales_par_acte(
                conn, public_events, public_links, public_entities))
        stats["graphe"]["cles"] = cles_stats
        stats["corrections_site"] = len(corrections["site"])
        stats["actualite_items"] = min(len(actualite), 400)
        stats["actualite_a_venir"] = len(a_venir)
        stats["actualite_par_genre"] = dict(Counter(i["genre"] for i in actualite))
        stats["redactions_personnes"] = redactions.get("remplacements", 0)

        conflits = export_conflits(conn, public_ids)
        # ── Transparence : qui doit déclarer, et où en est sa déclaration ────
        # ⚖️ Ce fichier NOMME des personnes. Elles y figurent au titre d'une
        # fonction publique et d'un registre que la loi ordonne de publier —
        # c'est le même registre qui les nomme, et le lien y renvoie. Le contenu
        # des déclarations n'est pas collecté, donc pas publié.
        # Une absence de ligne ne dit pas « personne n'a déclaré » : sous
        # 20 000 habitants, la loi n'exige rien. La page doit l'écrire.
        hatvp = rows(conn, """
            SELECT portee, prenom, nom, qualite, type_document, statut,
                   date_depot, date_publication, url
              FROM hatvp_declarations ORDER BY portee, nom
        """) if table_exists(conn, "hatvp_declarations") else []
        # Les décisions de justice administrative citant la commune. Le TITRE,
        # la juridiction, la date, le numéro et le lien vers Légifrance — jamais
        # l'extrait conservé en base. Les textes de JADE sont pseudonymisés, mais
        # un extrait de quatre cents caractères reste du récit d'affaire : le
        # lien renvoie au texte intégral chez celui qui l'établit.
        justice = rows(conn, """
            SELECT portee, juridiction, date_dec, numero, titre, type_recours, url
              FROM justice_decisions ORDER BY date_dec DESC
        """) if table_exists(conn, "justice_decisions") else []
        write_json(out / "transparence.json", {
            "hatvp": hatvp,
            "justice": justice,
            "total": len(hatvp),
            "note": "Liste des responsables publics soumis à l'obligation de "
                    "déclaration (HATVP). Sous 20 000 habitants, l'obligation ne "
                    "s'applique généralement pas : une liste vide ne signale "
                    "aucun manquement.",
        })

        write_json(out / "conflits.json", conflits)
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
        bundles = write_entity_bundles(out, public_entities, public_relations,
                                       public_events, public_links, public_flows,
                                       marches_data,
                                       comptes_syndicats_par_entite(conn))
        stats["extraits_actes"] = write_act_extracts(out, textes_extraits)
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
