"""Remettre les fiches d'entité d'accord avec leurs sources.

    python3 scripts/reparer_entites.py                      # simulation, tout
    python3 scripts/reparer_entites.py --appliquer
    python3 scripts/reparer_entites.py --etape types --appliquer
    python3 scripts/reparer_entites.py --journal audits/fusions.json --appliquer

Trois étapes, dans cet ordre — chacune prépare la suivante :

  noms     le nom RNA reconstruit depuis l'annonce. `titre` est vide sur une
           Modification et le collecteur repliait sur `titre_search`, un champ
           d'indexation : « VIVALTO » en ressortait « VIVALTO. VIV'ALTO ».
  types    le type que la forme juridique INSEE impose. SIRENE immatricule les
           associations et les communes ; les typer « entreprise » publiait une
           association subventionnée comme une société — et l'index unique
           portant sur (type, name), la même structure existait deux fois.
  grappes  les fiches qui restent identiques une fois le nom normalisé.

Simulation par défaut. `--appliquer` écrit, après avoir cloné la base.

Ce que le script NE FAIT PAS : fusionner deux fiches que deux identifiants
nationaux distincts séparent. Deux SIREN, ce sont deux personnes morales, et
aucune ressemblance de nom ne vaut contre ça. Ces cas sortent en liste à
arbitrer — c'est le travail humain que le reste sert à raccourcir.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from collectors.formes_juridiques import type_pour_forme, libelle_famille  # noqa: E402
from scripts.fusionner_entites import (  # noqa: E402
    choisir_garde, fusionner, grappes, identifiants, ouvrir)


def vert(t):  print(f"\033[32m{t}\033[0m")
def rouge(t): print(f"\033[31m{t}\033[0m")
def titre(t): print(f"\n\033[1m── {t} ──\033[0m")


def base_de(instance: Path) -> Path:
    bases = sorted(p for p in (instance / "db").glob("*.db"))
    if not bases:
        sys.exit(f"pas de base dans {instance}/db/")
    return bases[0]


def cloner(base: Path) -> Path:
    """Sauvegarde par référence — instantanée et sans coût sur APFS."""
    copie = base.with_name(f"{base.name}.avant-reparation-"
                           f"{datetime.now():%Y%m%d-%H%M%S}")
    try:
        subprocess.run(["cp", "-c", str(base), str(copie)], check=True)
    except subprocess.CalledProcessError:
        subprocess.run(["cp", str(base), str(copie)], check=True)
    return copie


# ── Étape 1 : les noms d'association ─────────────────────────────────────────

def etape_noms(conn, appliquer: bool) -> list[dict]:
    from collectors.rna import titre_du_record

    titre("1. Noms d'association reconstruits depuis l'annonce")
    actes = []
    for r in conn.execute(
            "SELECT e.id, e.name, a.raw_data FROM entities e"
            " JOIN associations a ON a.entity_id = e.id"
            " WHERE a.raw_data IS NOT NULL AND e.type='association'"):
        try:
            item = json.loads(r["raw_data"])
        except (ValueError, TypeError):
            continue
        if item.get("titre"):
            continue                      # le nom venait déjà du bon champ
        vrai = titre_du_record(item)
        if not vrai or vrai == r["name"]:
            continue
        pris = conn.execute(
            "SELECT id FROM entities WHERE type='association' AND name=? AND id<>?",
            (vrai, r["id"])).fetchone()
        actes.append({"etape": "noms", "id": r["id"], "avant": r["name"],
                      "apres": vrai, "bloque_par": pris["id"] if pris else None})

    for a in actes:
        if a["bloque_par"]:
            print(f"  #{a['id']:<6} {a['avant'][:56]:<56}")
            print(f"          ↳ « {a['apres'][:60]} » déjà porté par "
                  f"#{a['bloque_par']} — laissé à l'étape grappes")
            continue
        print(f"  #{a['id']:<6} {a['avant'][:56]:<56}\n          → {a['apres'][:60]}")
        if appliquer:
            from collectors.nom_normalise import normaliser
            conn.execute("UPDATE entities SET name=?, name_norm=? WHERE id=?",
                         (a["apres"], normaliser(a["apres"]), a["id"]))
    faits = sum(1 for a in actes if not a["bloque_par"])
    print(f"\n  {faits} noms rendus à leur libellé réel"
          f"{'' if appliquer else ' (simulation)'}, "
          f"{len(actes) - faits} en attente de fusion.")
    return actes


# ── Étape 2 : le type qu'impose la forme juridique ───────────────────────────

def etape_types(conn, appliquer: bool) -> list[dict]:
    titre("2. Types remis d'accord avec la forme juridique INSEE")
    actes = []
    for r in conn.execute(
            "SELECT e.id, e.name, e.type, e.commune, b.legal_form_code AS fj,"
            "       b.siren, b.status, b.creation_date"
            " FROM entities e JOIN businesses b ON b.entity_id = e.id"
            " WHERE b.legal_form_code IS NOT NULL AND b.legal_form_code <> ''"):
        attendu = type_pour_forme(r["fj"])
        if attendu == r["type"]:
            continue
        jumelle = conn.execute(
            "SELECT id FROM entities WHERE type=? AND name=?",
            (attendu, r["name"])).fetchone()
        actes.append({"etape": "types", "id": r["id"], "nom": r["name"],
                      "de": r["type"], "vers": attendu, "fj": r["fj"],
                      "famille": libelle_famille(r["fj"]),
                      "jumelle": jumelle["id"] if jumelle else None,
                      "siren": r["siren"], "status": r["status"],
                      "creation": r["creation_date"]})

    fusions, retypes = 0, 0
    for a in actes:
        if a["jumelle"]:
            garde = choisir_garde(conn, [a["id"], a["jumelle"]])
            absorbe = a["jumelle"] if garde == a["id"] else a["id"]
            print(f"  #{a['id']:<6} {a['nom'][:52]:<52} {a['fj']} {a['famille']}")
            print(f"          ↳ existe déjà en {a['vers']} #{a['jumelle']} — "
                  f"fusion, on garde #{garde}")
            if appliquer:
                detail = fusionner(conn, garde, absorbe)
                a["fusion"] = {"garde": garde, "absorbe": absorbe, "detail": detail}
                # La survivante doit porter le type que la forme juridique dit.
                conn.execute("UPDATE entities SET type=? WHERE id=?", (a["vers"], garde))
                _poser_extension(conn, garde, a)
            fusions += 1
        else:
            if appliquer:
                conn.execute("UPDATE entities SET type=? WHERE id=?",
                             (a["vers"], a["id"]))
                _poser_extension(conn, a["id"], a)
            retypes += 1

    print(f"\n  {retypes} fiches retypées, {fusions} fusionnées avec leur jumelle"
          f"{'' if appliquer else ' (simulation)'}.")
    for vers in ("association", "service"):
        n = sum(1 for a in actes if a["vers"] == vers)
        if n:
            print(f"    → {vers} : {n}")
    return actes


def _poser_extension(conn, eid: int, a: dict) -> None:
    """Donne à la fiche l'extension de son type, sans écraser ce qui est là.

    Pour une association, écrire le SIREN est ce qui la rend rapprochable du
    RNA : c'est le seul champ que les deux registres ont en commun.
    """
    if a["vers"] == "association":
        conn.execute(
            "INSERT OR IGNORE INTO associations (entity_id,siren,status,creation_date)"
            " VALUES (?,?,?,?)", (eid, a["siren"], a["status"], a["creation"]))
        conn.execute(
            "UPDATE associations SET siren=? WHERE entity_id=?"
            " AND (siren IS NULL OR siren='')", (a["siren"], eid))
    elif a["vers"] == "service":
        conn.execute("INSERT OR IGNORE INTO services (entity_id) VALUES (?)", (eid,))


# ── Étape 3 : les grappes qui restent ────────────────────────────────────────

def etape_grappes(conn, appliquer: bool, limite: int) -> list[dict]:
    titre("3. Grappes de fiches restées identiques")
    actes, arbitrer = [], []
    for g in grappes(conn):
        if g["obstacle"]:
            arbitrer.append(g)
            continue
        ids = [m["id"] for m in g["membres"]]
        garde = choisir_garde(conn, ids)
        acte = {"etape": "grappes", "garde": garde,
                "absorbes": [i for i in ids if i != garde],
                "nom": next(m["name"] for m in g["membres"] if m["id"] == garde),
                "membres": g["membres"]}
        if appliquer:
            acte["detail"] = {str(i): fusionner(conn, garde, i)
                              for i in acte["absorbes"]}
        actes.append(acte)

    for a in actes[:limite]:
        print(f"  garde #{a['garde']} « {a['nom'][:56]} »"
              f" ← {', '.join('#' + str(i) for i in a['absorbes'])}")
    if len(actes) > limite:
        print(f"  … et {len(actes) - limite} grappes de plus")
    print(f"\n  {len(actes)} grappes fusionnées"
          f"{'' if appliquer else ' (simulation)'},"
          f" {sum(len(a['absorbes']) for a in actes)} fiches absorbées.")

    if arbitrer:
        print(f"\n  \033[33m{len(arbitrer)} grappes LAISSÉES À ARBITRER\033[0m —"
              " des identifiants nationaux distincts les séparent :")
        for g in arbitrer[:limite]:
            noms = " / ".join(f"#{m['id']} {m['name'][:34]}" for m in g["membres"])
            print(f"    {noms}\n      {g['obstacle']}")
        if len(arbitrer) > limite:
            print(f"    … et {len(arbitrer) - limite} de plus")
    return actes + [{"etape": "arbitrer", **g} for g in arbitrer]


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--instance", type=Path, default=ROOT)
    ap.add_argument("--etape", choices=["noms", "types", "grappes", "tout"],
                    default="tout")
    ap.add_argument("--appliquer", action="store_true")
    ap.add_argument("--journal", type=Path, default=None,
                    help="écrire le détail des fusions en JSON")
    ap.add_argument("--limite", type=int, default=15,
                    help="lignes détaillées par étape (défaut 15)")
    args = ap.parse_args()

    base = base_de(args.instance.expanduser())
    print(f"\033[1mBase : {base}\033[0m")
    if args.appliquer:
        copie = cloner(base)
        vert(f"Sauvegarde : {copie.name}")
    else:
        rouge("SIMULATION — rien ne sera écrit. `--appliquer` pour agir.")

    conn = ouvrir(base)
    avant = dict(conn.execute("SELECT type, COUNT(*) FROM entities GROUP BY type"))
    journal = []
    try:
        if args.etape in ("noms", "tout"):
            journal += etape_noms(conn, args.appliquer)
        if args.etape in ("types", "tout"):
            journal += etape_types(conn, args.appliquer)
        if args.etape in ("grappes", "tout"):
            journal += etape_grappes(conn, args.appliquer, args.limite)
        if args.appliquer:
            conn.commit()
    except Exception:
        conn.rollback()
        raise

    apres = dict(conn.execute("SELECT type, COUNT(*) FROM entities GROUP BY type"))
    titre("Bilan")
    for t in sorted(set(avant) | set(apres)):
        a, b = avant.get(t, 0), apres.get(t, 0)
        fleche = f"{a:>6} → {b:<6}" if a != b else f"{a:>6}        "
        print(f"  {t:<12} {fleche} {'' if a == b else f'({b - a:+d})'}")

    if args.journal:
        args.journal.parent.mkdir(parents=True, exist_ok=True)
        args.journal.write_text(
            json.dumps({"base": str(base), "applique": args.appliquer,
                        "horodatage": datetime.now().isoformat(timespec="seconds"),
                        "actes": journal}, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8")
        print(f"\n  Journal : {args.journal}")
    print()


if __name__ == "__main__":
    main()
