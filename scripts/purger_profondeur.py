#!/usr/bin/env python3
"""Retire de la base ce que la profondeur de collecte n'ira plus chercher.

    python3 scripts/purger_profondeur.py              # simulation
    python3 scripts/purger_profondeur.py --appliquer

Le moteur ne collecte plus les commerces, les associations, les mutations
immobilières ni les points d'intérêt des communes membres de
l'intercommunalité (cf. `PROFONDEUR_STEP` dans collectors/config.py). Réduire la
collecte n'efface pas ce qu'elle a déjà rapporté : ces fiches resteraient en
base et continueraient d'être servies **sans jamais se rafraîchir**. Une fiche
figée est pire qu'une fiche absente — elle a l'air à jour.

Ce qu'il retire, et à quelle condition :

  * les fiches dont la table fille désigne un collecteur passé en `fond`
    (businesses → sirene, associations → rna, places → osm, écoles →
    education), dont la commune n'est pas suivie en profondeur, ET auxquelles
    RIEN n'est accroché ;
  * les mutations DVF des communes qui ne sont plus suivies ;
  * les annonces BODACC qui ne concernent plus aucune fiche de la base ;
  * les caches Overpass des communes qui ne sont plus interrogées.

Ce qu'il ne retire JAMAIS :

  * les personnes. Le Répertoire National des Élus reste collecté sur tout le
    périmètre : les délégués communautaires sont élus dans les communes
    membres, et purger leurs fiches viderait le conseil communautaire ;
  * les services, ni rien dont la forme juridique INSEE relève du droit public.
    La mairie d'une commune membre est C2 de plein droit — une institution du
    territoire, pas un commerce de passage — et SIRENE l'immatricule comme le
    reste ;
  * une fiche à laquelle quelque chose est accroché : un marché, un flux
    financier, une relation, une note d'atelier, un site web. Une entreprise
    d'ailleurs qui a remporté un marché de la commune est le matériau même du
    graphe de la commande publique. Elle reste, et `classer_perimetre` la
    reclasse en `lien` ;
  * les tables des steps `institution` — fiscalité, élections, risques,
    indicateurs, urbanisme, dotations —, qui portent tout le périmètre à
    dessein.

La liste des tables purgeables se DÉRIVE de `PROFONDEUR_STEP` : une instance qui
remet `sirene` en `institution` voit ce script cesser de toucher aux
entreprises, sans qu'une ligne change ici. Une liste écrite en dur aurait
contredit la configuration au premier réglage.

APRÈS avoir appliqué, rejouer le classement — les fiches retenues pour une
accroche doivent passer de C2 à `lien` :

    python3 -m collectors.run_all --step perimetre
"""
from __future__ import annotations

import argparse
import importlib.util
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from collectors.config import (COMMUNES_FOND, DB_PATH, PROFONDEUR_STEP,  # noqa: E402
                               STEP_META, communes_du_step, registre_du_step)
from collectors.db import get_conn  # noqa: E402
from collectors.formes_juridiques import type_pour_forme  # noqa: E402


def _charger(nom: str):
    """`scripts/` est un répertoire d'outils, pas un paquet : on charge par chemin.

    Le repérage des accroches et des cascades est écrit une fois, dans
    `nettoyer_entites`. Le réécrire ici, c'était accepter que les deux scripts
    divergent le jour où une table s'ajoute — et que celui-ci supprime ce que
    l'autre aurait retenu.
    """
    spec = importlib.util.spec_from_file_location(nom, ROOT / "scripts" / f"{nom}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_nettoyer = _charger("nettoyer_entites")

# Table fille → step qui la remplit. C'est la table fille qui dit d'où vient une
# fiche : `entities` ne porte pas de colonne de source, et le type ne suffit pas
# (un `service` peut venir d'OSM comme du site de la mairie).
# Table fille → (step qui la remplit, type que ce step produit).
#
# Le type compte autant que la table. Une commune membre a une ligne
# `businesses` — c'est sa fiche d'immatriculation, SIREN et code NAF compris —
# mais son type est `service`, posé d'après sa forme juridique. Partir de la
# seule table fille mettait seize mairies, l'intercommunalité et le Parc
# national dans le lot à supprimer.
TABLES_ENTITES = {
    "businesses":               ("sirene",    "business"),
    "associations":             ("rna",       "association"),
    "places":                   ("osm",       "place"),
    "etablissements_scolaires": ("education", "service"),
}

# Tables de TRACE : ce que NOUS avons fait de la fiche, pas ce qui la rattache
# au territoire. Un vecteur d'index, une visite de scraper, une ligne de journal
# ne sont pas des motifs de garder quoi que ce soit — et toutes trois se
# régénèrent (`build_rag_index`, le prochain passage du scraper).
#
# Sans cette distinction, la première base essayée retenait 726 entreprises sur
# 3 013, uniquement parce qu'elles avaient été indexées : une fiche se serait
# sauvée en ayant été lue. Elles pointent vers `entities` sans ON DELETE
# CASCADE, il faut donc les vider explicitement avant la suppression.
TRACES = ("embeddings", "scrape_runs", "audit_log")


def _en_fond(step: str) -> bool:
    return PROFONDEUR_STEP.get(step) == "fond"


def _clauses_events_fond() -> list[str]:
    """Clauses SQL des événements produits par un step passé en `fond`.

    Lues dans `STEP_META`, qui dit déjà pour chaque step la table et le filtre
    où compter ses lignes. Écrire « source=\'bodacc\' » ici aurait fait de ce
    script le second endroit où se déclare la provenance des annonces, et le
    premier à se tromper le jour où une autre source d'événements passe en fond.
    """
    return [where for step, (_, _, table, where) in STEP_META.items()
            if table == "events" and where and _en_fond(step)]


def _droit_public(conn, eid: int) -> bool:
    """La forme juridique INSEE range-t-elle cette fiche dans le droit public ?

    Second garde, volontairement redondant avec le croisement de type ci-dessus :
    le retypage par la forme juridique a bien tourné sur les trois bases, mais
    une purge est irréversible et une base qui ne l'aurait pas reçu perdrait ses
    mairies. Une branche jamais empruntée est une branche fausse jusqu'à preuve
    du contraire — celle-ci se vérifie en une requête.
    """
    row = conn.execute(
        "SELECT legal_form_code FROM businesses WHERE entity_id=?", (eid,)).fetchone()
    return bool(row) and type_pour_forme(row[0]) == "service"


def fiches_a_retirer(conn) -> tuple[dict, dict, list]:
    """(à retirer par table, retenues par table, tables ignorées).

    Une retenue porte quelque chose : elle sort du lot et sera reclassée.
    """
    accroches = [(t, c) for t, c in _nettoyer._tables_liees(conn)[0]
                 if t not in TRACES]
    noms_fond = {c["nom"] for c in COMMUNES_FOND.values()}
    a_retirer: dict[str, list] = {}
    retenues: dict[str, list] = {}
    ignorees: list[str] = []

    for table, (step, type_attendu) in TABLES_ENTITES.items():
        if not _en_fond(step):
            ignorees.append(f"{table} (step `{step}` en « {PROFONDEUR_STEP[step]} »)")
            continue
        # `places` est remplie par deux steps. Tant que les deux ne sont pas à
        # la même profondeur, on ne peut pas distinguer un POI d'un monument
        # historique par la seule table : on s'abstient plutôt que de deviner.
        if table == "places" and not _en_fond("patrimoine"):
            ignorees.append("places (osm et patrimoine à des profondeurs différentes)")
            continue
        lot_retirer, lot_retenu = [], []
        for r in conn.execute(
                f'SELECT e.id, e.type, e.name, e.commune FROM "{table}" t '
                'JOIN entities e ON e.id = t.entity_id WHERE e.type = ?',
                (type_attendu,)):
            # Une commune inconnue (NULL) n'est pas une commune hors fond : on
            # ne sait pas où elle est. `classer_perimetre` la traitera comme
            # telle, et une purge n'a pas à trancher ce qu'un classement refuse
            # de trancher.
            if not r["commune"] or r["commune"] in noms_fond:
                continue
            if _droit_public(conn, r["id"]):
                continue
            n = _nettoyer._accroches(conn, r["id"], accroches)
            (lot_retenu if n else lot_retirer).append(
                (r["id"], r["type"], r["name"], r["commune"], n))
        a_retirer[table] = lot_retirer
        retenues[table] = lot_retenu
    return a_retirer, retenues, ignorees


def mutations_a_retirer(conn) -> list:
    """Mutations DVF des communes qui ne sont plus suivies."""
    if not _en_fond("dvf"):
        return []
    codes = communes_du_step("dvf", adresse=True)
    marques = ",".join("?" * len(codes))
    return conn.execute(
        f"SELECT insee, COUNT(*) FROM dvf_transactions "
        f"WHERE insee NOT IN ({marques}) OR insee IS NULL GROUP BY insee",
        codes).fetchall()


def annonces_orphelines(conn, ids_supprimes: set[int]) -> list[int]:
    """Annonces BODACC qui ne concerneront plus aucune fiche.

    `event_entities` part en cascade avec la fiche : l'annonce, elle, resterait
    seule et sans sujet. Ce sont bien les annonces d'entreprises purgées, pas
    des annonces « hors périmètre » — celles-là n'ont jamais été collectées.
    """
    clauses = _clauses_events_fond()
    if not clauses:
        return []
    filtre = " OR ".join(f"({c})" for c in clauses)
    orphelines = []
    for (eid,) in conn.execute(f"SELECT id FROM events WHERE {filtre}"):
        rattachees = [r[0] for r in conn.execute(
            "SELECT entity_id FROM event_entities WHERE event_id=?", (eid,))]
        if rattachees and all(e in ids_supprimes for e in rattachees):
            orphelines.append(eid)
    return orphelines


def caches_a_retirer() -> list[Path]:
    """Caches Overpass des communes qui ne sont plus interrogées.

    Le dossier se déduit de la BASE et non de la racine du moteur : les caches
    appartiennent à l'instance, comme elle, et `db/` et `territoire/` sont
    côte à côte. Passer par `config.TERRITOIRE` visait le dépôt depuis lequel on
    lance le script — c'est-à-dire, quand on purge une instance à distance avec
    `VIGIE_DB`, un dossier qui n'a rien à voir avec la base qu'on purge.
    """
    if not _en_fond("osm"):
        return []
    territoire = DB_PATH.parent.parent / "territoire"
    if not territoire.exists():
        return []
    gardes = {f"pois_{c}.geojson" for c in communes_du_step("osm")}
    return sorted(p for p in territoire.glob("pois_*.geojson")
                  if p.name not in gardes)


# Ce qu'une fiche du lot ne peut pas porter. Le calcul des accroches l'exclut
# déjà — ces tables en font partie —, mais le contrôle est refait ici sans
# passer par lui : si `_tables_liees` changeait, ou si une table s'ajoutait sans
# contrainte déclarée, la purge emporterait de l'argent ou un acte en silence.
# Une purge se vérifie par un chemin qui n'est pas celui qui l'a décidée.
IRREMPLACABLE = (
    ("financial_flows",         "from_id"),
    ("financial_flows",         "to_id"),
    ("marches_publics",         "titulaire_id"),
    ("marches_publics",         "acheteur_id"),
    ("elus_rne",                "entity_id"),
    ("budget_indicators",       "entity_id"),
    ("urbanisme_autorisations", "demandeur_entity_id"),
    ("budget_annexe",           "entity_id"),
)


def controle_final(conn, ids: set[int]) -> list[str]:
    """Ce que le lot emporterait et qui ne se recollecte pas. Doit être vide.

    `event_entities` y figure au titre des actes : une fiche citée par une
    délibération est un sujet du conseil, quelle que soit sa commune. Le lien
    partirait en cascade sans rien dire.
    """
    if not ids:
        return []
    marques = ",".join("?" * len(ids))
    valeurs = list(ids)
    alertes = []
    for table, colonne in IRREMPLACABLE:
        try:
            n = conn.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE "{colonne}" IN ({marques})',
                valeurs).fetchone()[0]
        except Exception:          # table absente d'une base ancienne
            continue
        if n:
            alertes.append(f"{table}.{colonne} : {n} ligne(s)")

    # Les ACTES, à part : une fiche citée par une délibération est un sujet du
    # conseil, quelle que soit sa commune, et son lien partirait en cascade sans
    # rien dire. Les annonces que le step ne collectera plus ne comptent pas —
    # ce sont elles qu'on retire.
    clauses = _clauses_events_fond()
    hors = (" AND NOT (" + " OR ".join(f"({c})" for c in clauses) + ")") if clauses else ""
    n = conn.execute(
        f'SELECT COUNT(*) FROM event_entities ee JOIN events e ON e.id = ee.event_id '
        f'WHERE ee.entity_id IN ({marques}){hors}', valeurs).fetchone()[0]
    if n:
        alertes.append(f"event_entities (actes) : {n} lien(s)")
    return alertes


def run(appliquer: bool = False) -> int:
    conn = get_conn()
    noms_fond = sorted(c["nom"] for c in COMMUNES_FOND.values())
    print(f"base      : {DB_PATH}")
    print(f"profondeur: {', '.join(noms_fond)} "
          f"({len(registre_du_step('rne'))} communes au périmètre)")
    print()

    a_retirer, retenues, ignorees = fiches_a_retirer(conn)
    ids = {ligne[0] for lot in a_retirer.values() for ligne in lot}
    mutations = mutations_a_retirer(conn)
    orphelines = annonces_orphelines(conn, ids)
    caches = caches_a_retirer()

    print("── fiches ───────────────────────────────────────────────────────")
    for table in TABLES_ENTITES:
        if table not in a_retirer:
            continue
        r, k = len(a_retirer[table]), len(retenues[table])
        print(f"  {table:26} {r:6} à retirer"
              + (f"   {k} retenues (accrochées)" if k else ""))
    for note in ignorees:
        print(f"  — ignorée : {note}")

    print("\n── autres tables ────────────────────────────────────────────────")
    total_dvf = sum(n for _, n in mutations)
    print(f"  dvf_transactions           {total_dvf:6} mutations"
          + (f" sur {len(mutations)} communes" if mutations else ""))
    print(f"  events (bodacc orphelines) {len(orphelines):6}")
    print(f"  caches territoire/         {len(caches):6} fichiers")

    if retenues and any(retenues.values()):
        print("\n── retenues, à reclasser en « lien » ────────────────────────────")
        for table, lot in retenues.items():
            for eid, _t, nom, commune, n in sorted(lot, key=lambda x: -x[4])[:8]:
                print(f"  [{eid:6}] {nom[:44]:44} {commune[:18]:18} {n} accroche(s)")
            if len(lot) > 8:
                print(f"  … et {len(lot) - 8} autres dans {table}")

    alertes = controle_final(conn, ids)
    if alertes:
        print("\n✗ REFUS — le lot emporterait ce qui ne se recollecte pas :")
        for a in alertes:
            print(f"    {a}")
        print("  Aucune écriture. Le calcul des accroches est à revoir avant "
              "de rejouer ce script.")
        conn.close()
        return 1
    print("\n✓ contrôle : le lot ne touche ni flux financier, ni marché, ni "
          "mandat, ni acte.")
    print(f"  ({len(ids)} fiches vérifiées sur {len(IRREMPLACABLE)} tables "
          "plus les actes)")

    if not appliquer:
        print("\nSimulation. Rien n'a été écrit — relancer avec --appliquer.")
        conn.close()
        return 0

    # Une base écrasée ne se retrouve pas. `cp -c` demande une copie par
    # référence : instantanée sur APFS, et sans occuper d'espace tant que la
    # base n'est pas réécrite. Même convention que `vigie_collecte.sh`.
    horodatage = datetime.now().strftime("%Y%m%d-%H%M%S")
    sauvegarde = DB_PATH.with_suffix(DB_PATH.suffix + f".avant-purge-{horodatage}")
    shutil.copy2(DB_PATH, sauvegarde)
    print(f"\nsauvegarde : {sauvegarde.name}")

    try:
        conn.execute("BEGIN")
        for eid in ids:
            # Les traces d'abord : elles pointent vers la fiche sans cascade, et
            # la suppression échouerait sur la contrainte au lieu de dire
            # pourquoi.
            for table in TRACES:
                try:
                    conn.execute(f'DELETE FROM "{table}" WHERE entity_id=?', (eid,))
                except Exception:      # table absente d'une base ancienne
                    pass
            conn.execute("DELETE FROM entities WHERE id=?", (eid,))
        for eid in orphelines:
            conn.execute("DELETE FROM events WHERE id=?", (eid,))
        if _en_fond("dvf"):
            codes = communes_du_step("dvf", adresse=True)
            marques = ",".join("?" * len(codes))
            conn.execute(
                f"DELETE FROM dvf_transactions "
                f"WHERE insee NOT IN ({marques}) OR insee IS NULL", codes)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    for p in caches:
        p.unlink()

    print(f"\n✓ {len(ids)} fiches, {total_dvf} mutations, {len(orphelines)} annonces, "
          f"{len(caches)} caches retirés.")
    print("  Rejouer le classement : python3 -m collectors.run_all --step perimetre")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--appliquer", action="store_true",
                        help="écrire (défaut : simulation)")
    return run(appliquer=parser.parse_args().appliquer)


if __name__ == "__main__":
    raise SystemExit(main())
