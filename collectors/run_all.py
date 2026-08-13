#!/usr/bin/env python3
"""
run_all.py — Orchestrateur principal des collecteurs (instance Brassac).
Usage : python3 -m collectors.run_all [--step STEP] [--stats]
"""
import sys
import time
import argparse
from pathlib import Path

# Ajouter le parent au path pour les imports relatifs
sys.path.insert(0, str(Path(__file__).parent.parent))

from collectors.config        import (COMMUNE_NAME, COMMUNES, COMMUNES_INSEE,
                                      COMMUNES_CP, COMMUNES_ADRESSE,
                                      COMMUNES_INSEE_ADRESSE, DB_PATH, STEP_META)
from collectors.db            import (init_db, get_conn, stats,
                                      log_run_start, log_run_end)
from collectors.osm           import import_osm
from collectors.profiles      import import_profiles
from collectors.cm_events     import import_cm_events
from collectors.conseils      import (import_conseil_communautaire,
                                      import_conseil_municipal)
from collectors.sirene        import import_sirene
from collectors.rna           import import_rna
from collectors.bodacc        import run as run_bodacc
from collectors.dvf           import import_dvf
from collectors.insee_social  import run as run_insee_social
from collectors.georisques    import run as run_georisques
from collectors.raa_prefecture import run as run_raa
from collectors.pop_culture   import run as run_pop_culture
from collectors.rne          import run as run_rne
from collectors.fiscalite    import run as run_fiscalite
from collectors.urbanisme_sitadel import run as run_sitadel
from collectors.elections    import run as run_elections
from collectors.dirigeants_deports import run as run_dir_deports
from collectors.dirigeants_web     import run as run_dir_web
from collectors.events_scraper  import main as run_events_scraper
from collectors.web_scraper    import main as run_web_scraper
from collectors.marches_publics import main as run_marches_publics
from collectors.banatic        import run as run_banatic


STEPS = {
    "init":     ("Initialisation schéma",                lambda: init_db()),
    "osm":      ("POIs OpenStreetMap",                   import_osm),
    "profiles": ("Élus, candidats, entourage",            import_profiles),
    # Deux entrées distinctes : `cm` lit les PV publiés par la mairie (source
    # primaire, automatique), `seed` importe ce qui a été saisi à la main dans
    # config/seed_local.json (subventions, baux). Les confondre revenait à
    # faire dépendre la collecte des PV d'un fichier local à remplir.
    "cm":       ("Procès-verbaux du conseil municipal (PDF)", import_conseil_municipal),
    "seed":     ("Saisies locales : subventions, baux, transactions", import_cm_events),
    # sirene et dvf sont ADRESSÉS : ils bouclent sur COMMUNES_ADRESSE, qui
    # ajoute les communes déléguées — ici Ferrières et Le Margnès, absorbées
    # par Fontrieu en 2016 mais toujours indexées sous leur ancien code.
    "sirene":   ("Entreprises SIRENE (C1 — {})".format(", ".join(COMMUNES_INSEE_ADRESSE)),
                 lambda: [import_sirene(i, COMMUNES_ADRESSE[i]["nom"])
                          for i in COMMUNES_INSEE_ADRESSE]),
    # RNA et BODACC interrogent par CODE POSTAL, qui ne délimite pas une
    # commune : la collecte sur-remonte puis filtre sur COMMUNES. Ne pas
    # s'étonner du nombre d'enregistrements « hors périmètre ignorés » — sur le
    # 81100 (aire de Castres), ils sont la règle plutôt que l'exception.
    "rna":      ("Associations RNA/JO (C1 — CP {})".format(", ".join(COMMUNES_CP)),
                 lambda: [import_rna(cp) for cp in COMMUNES_CP]),
    "bodacc":   ("Annonces BODACC (C1 — CP {})".format(", ".join(COMMUNES_CP)),
                 lambda: [run_bodacc(cp=cp) for cp in COMMUNES_CP]),
    "dvf":      ("Transactions DVF (C1 — {})".format(", ".join(COMMUNES_INSEE_ADRESSE)),
                 lambda: [import_dvf(i) for i in COMMUNES_INSEE_ADRESSE]),
    "insee":    ("Indicateurs INSEE Melodi (C1)", run_insee_social),
    "georisques": ("Risques, ICPE, CATNAT (C1)", run_georisques),
    "raa":      ("RAA de la préfecture (année courante, incrémental)",
                 lambda: run_raa(__import__("datetime").date.today().year)),
    "patrimoine": ("Monuments historiques MH (C1)", run_pop_culture),
    # Source AUTORITAIRE des mandats (DGCL). Sert de contrôle des affirmations
    # tirées des sites municipaux, qui peuvent être périmés.
    "rne":      ("Élus — Répertoire National des Élus (C1 + délégués CC)", run_rne),
    "fiscalite": ("Taux d'imposition locaux votés (C1)", run_fiscalite),
    "sitadel":  ("Autorisations d'urbanisme Sitadel (C1)", run_sitadel),
    "elections": ("Résultats électoraux (Ministère de l'intérieur)", run_elections),
    # Dirigeants d'associations : absents de l'open data (RNA et JO ne les
    # publient pas). Ces deux steps produisent des CANDIDATS à valider, jamais
    # des relations directes.
    "dir_deports": ("Dirigeants d'assos — déports du conseil", run_dir_deports),
    "dir_web":     ("Dirigeants d'assos — sites web", run_dir_web),
    "marches":  ("Marchés publics DECP + avis des sites", run_marches_publics),
    "cc_epci":  ("Procès-verbaux du conseil communautaire",
                 import_conseil_communautaire),
    # Périmètre C2 : ce que l'EPCI exerce à la place de la commune.
    # Source faisant foi sur le rattachement des délégués (le RNE se trompe).
    "banatic":  ("Compétences, délégués et adhésions de l'EPCI (BANATIC)",
                 run_banatic),
    "events":   ("Vie locale (sites officiels)",          run_events_scraper),
    "web":      ("Sites web entités locales",             run_web_scraper),
}


def count_items(conn, name: str):
    """Nombre d'items produits par ce collecteur, ou None si non mesurable."""
    meta = STEP_META.get(name)
    if not meta:
        return None
    _, _, table, where = meta
    sql = f"SELECT COUNT(*) FROM {table}" + (f" WHERE {where}" if where else "")
    try:
        return conn.execute(sql).fetchone()[0]
    except Exception:
        return None


def run_step(name: str):
    label, fn = STEPS[name]
    print(f"\n{'='*60}")
    print(f"  {name.upper()} — {label}")
    print(f"{'='*60}")

    # Journal collector_runs — c'est le seul moyen de détecter une source morte.
    # Ouvert AVANT l'appel pour qu'un plantage laisse une trace 'error'.
    conn = run_id = before = None
    if name in STEP_META:
        try:
            conn = get_conn()
            before = count_items(conn, name)
            run_id = log_run_start(conn, name, before)
        except Exception as e:      # le journal ne doit jamais bloquer la collecte
            print(f"  ⚠ journal collector_runs indisponible : {e}")
            conn = run_id = None

    t0 = time.time()
    status, err = "ok", None
    try:
        fn()
    except Exception as e:
        status, err = "error", f"{type(e).__name__}: {e}"
        raise
    finally:
        elapsed = time.time() - t0
        if conn is not None and run_id is not None:
            try:
                log_run_end(conn, run_id, status, count_items(conn, name), before, err)
            except Exception as e:
                print(f"  ⚠ clôture du journal échouée : {e}")
            finally:
                conn.close()
        flag = "✓" if status == "ok" else "✗"
        print(f"  {flag} {name} terminé en {elapsed:.1f}s")


def print_stats():
    conn = get_conn()
    s = stats(conn)
    conn.close()
    if not s:
        print("Base vide.")
        return
    print(f"\n{'='*60}")
    print(f"  STATISTIQUES — {DB_PATH.name}")
    print(f"{'='*60}")
    print(f"  Personnes        : {s.get('persons', 0):>6}")
    print(f"  Entreprises      : {s.get('businesses', 0):>6}")
    print(f"  Associations     : {s.get('associations', 0):>6}")
    print(f"  Services publics : {s.get('services', 0):>6}")
    print(f"  Lieux / POIs     : {s.get('places', 0):>6}")
    print(f"  Relations        : {s.get('relations', 0):>6}")
    print(f"  Événements       : {s.get('events', 0):>6}")
    print(f"  Transactions DVF : {s.get('dvf_transactions', 0):>6}")
    print(f"  Flux financiers  : {s.get('financial_flows', 0):>6}")
    print(f"  Géolocalisés     : {s.get('geolocated', 0):>6}")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description=f"{COMMUNE_NAME} OSINT — collecteurs")
    parser.add_argument("--step", choices=list(STEPS.keys()),
                        help="Exécuter un seul step")
    parser.add_argument("--stats", action="store_true",
                        help="Afficher les statistiques de la base")
    parser.add_argument("--from-step", choices=list(STEPS.keys()),
                        help="Reprendre depuis ce step")
    args = parser.parse_args()

    if args.stats:
        print_stats()
        return

    if args.step:
        if args.step != "init":
            init_db()
        run_step(args.step)
        print_stats()
        return

    # Run complet
    steps = list(STEPS.keys())
    if args.from_step:
        idx = steps.index(args.from_step)
        steps = steps[idx:]

    print(f"\n  {COMMUNE_NAME.upper()} OSINT — collecte complète")
    print(f"  {len(steps)} steps : {', '.join(steps)}")
    t_total = time.time()

    for step in steps:
        run_step(step)

    print(f"\n  Collecte complète en {time.time()-t_total:.0f}s")
    print_stats()


if __name__ == "__main__":
    main()
