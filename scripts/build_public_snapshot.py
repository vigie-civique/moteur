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
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))

# Le code du snapshot vit dans le paquet `scripts/snapshot/` : une étape par
# sortie ou famille de sorties, déclarées dans l'ordre dans
# `scripts/snapshot/etapes.py`. Ce fichier en reste la façade : `api.py`,
# `scripts/publication.py` et les essais continuent d'importer d'ici les noms
# qu'ils y ont toujours trouvés, réexportés ci-dessous.
from scripts.snapshot.actes import (  # noqa: E402,F401
    ACCORDE_RE,
    _annee_de_trace,
    DEMANDE_RE,
    domaine,
    montant_de_la_decision,
    MONTANT_MAX,
    MONTANT_MIN,
    portee_evenement,
    PORTEE_PAR_PERIMETRE,
    PORTEE_PAR_TYPE,
    provenance,
    public_event_detail,
    TYPES_DELIBERES,
    TYPES_SEANCE,
    write_act_extracts,
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
from scripts.snapshot.compteurs import mesurer_replicabilite  # noqa: E402,F401
from scripts.snapshot.conflits import deports_par_deliberation, export_conflits  # noqa: E402,F401
from scripts.snapshot.corrections import (  # noqa: E402,F401
    export_corrections,
    JOURNAL_PATH,
    lire_journal_corrections,
)
from scripts.snapshot.couverture import export_couverture, STEP_META  # noqa: E402,F401
from scripts.snapshot.en_clair import export_dossiers, export_en_clair  # noqa: E402,F401
from scripts.snapshot.fiches import (  # noqa: E402,F401
    comptes_syndicats_par_entite,
    domain_for,
    etat_activite,
    FIN_DACTIVITE,
    in_center_box,
    in_commune_bbox,
    load_confirmed_urls,
    NAF_IMMOBILIER,
    nature_entreprise,
    public_entity,
    write_entity_bundles,
)
from scripts.snapshot.perimetre import (  # noqa: E402,F401
    exiger_perimetre_classe,
    PerimetreNonClasse,
    publiable_dans_perimetre,
    TYPES_INSTITUTIONNELS,
)
from scripts.snapshot.personnes import beneficiaires_argent_public  # noqa: E402,F401
from scripts.snapshot.popolo import (  # noqa: E402,F401
    build_popolo,
    POPOLO_ORG_CLASS,
    POPOLO_ROLES,
)
from scripts.snapshot.recherche import write_recherche_index, write_search_index  # noqa: E402,F401
from scripts.snapshot.relations import (  # noqa: E402,F401
    is_public_relation,
    RELATION_META_PUBLIQUE,
    relation_meta_publique,
    relation_pertinente,
    sort_du_type,
)
from scripts.snapshot.revue import (  # noqa: E402,F401
    appliquer_revue,
    charger_revue,
    TYPES_REVUS,
)
from scripts.snapshot.socle import (  # noqa: E402,F401
    COMMUNES_EPCI,
    DB_PATH,
    DEFAULT_OUT,
    DEPARTEMENT,
    EPCI_NOM_C2,
    EPCI_SIREN_C2,
    get_db,
    INSEE_C1,
    jour_utc,
    lire_horloge,
    load_rules,
    relation_exists,
    row,
    rows,
    RULES,
    RULES_PATH,
    safe_url,
    table_exists,
    TELECOMS_RAYON_KM,
    URL_COMMUNE,
    URL_EPCI,
    VARIABLE_HORLOGE,
    write_json,
    write_json_compact,
)
from scripts.snapshot.territoire import (  # noqa: E402,F401
    DECHETS_INDICATEURS,
    export_dechets,
    export_eau_potable,
    export_enfance,
    export_incendie,
    export_reperes_fiscaux,
    export_telecoms,
    INSEE_PUBLIABLES,
    RUPTURE_CUIVRE,
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
from scripts.snapshot.etapes import ETAPES  # noqa: E402
from scripts.snapshot.registre import executer  # noqa: E402


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
    """Construit le snapshot public dans `out` ; rend ses compteurs (`stats.json`).

    Les étapes, ce qu'elles lisent, produisent et écrivent, et leur ordre sont
    déclarés dans `scripts/snapshot/etapes.py` : cette fonction ne fait que
    les exécuter sur une connexion en lecture seule.
    """
    # Avant toute lecture de la base : l'heure de cette construction, pour
    # tous les fichiers. Cf. `lire_horloge`.
    horloge = horloge or lire_horloge()
    conn = get_db()
    try:
        faits = executer(ETAPES, {"conn": conn, "out": out, "horloge": horloge,
                                  "exclusions": defaultdict(Counter)})
        return faits["stats"]
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
