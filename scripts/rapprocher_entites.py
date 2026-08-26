"""Proposer les fiches qui se ressemblent sans être identiques.

    python3 scripts/rapprocher_entites.py                 # tout, seuil 0.80
    python3 scripts/rapprocher_entites.py --seuil 0.85
    python3 scripts/rapprocher_entites.py --orphelines    # sans identifiant d'abord
    python3 scripts/rapprocher_entites.py --json audits/rapprochements.json

LECTURE SEULE, ET C'EST LE POINT. `reparer_entites.py --etape grappes` fusionne
ce dont il est sûr — l'identité exacte des jetons. Ici on est dans le domaine
du DOUTE : « Caravane Film » et « LA CARAVANE FILME » sont la même association,
« Amicale de l'école de Lanuéjols » et « Amicale de l'école des Poujeadettes »
ne le sont pas, et rien dans le calcul ne les distingue.

Ce que la machine apporte : ramener des millions de paires à une liste courte,
triée, avec sous les yeux ce qui permet de trancher — identifiants, argent
porté, adresse, dates. Ce qu'elle n'apporte pas : la décision.

Les paires retenues se déclarent ensuite comme les autres, dans
`~/Claude/scripts/vigie_arbitrage.py` (fusion) ou
`config/arbitrages_entites.json` (distinctes).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.fusionner_entites import (  # noqa: E402
    identifiants, ouvrir, rapprochements)


def _detail(conn, eid: int) -> dict:
    r = conn.execute(
        "SELECT e.name, e.type, e.commune, e.perimetre, e.address, e.created_at,"
        "       a.rna_id, a.object, b.siren, b.naf_label, b.legal_form_code,"
        "       b.status, b.creation_date"
        " FROM entities e"
        " LEFT JOIN associations a ON a.entity_id = e.id"
        " LEFT JOIN businesses b ON b.entity_id = e.id"
        " WHERE e.id = ?", (eid,)).fetchone()
    flux = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(amount),0) FROM financial_flows"
        " WHERE to_id = ?", (eid,)).fetchone()
    actes = conn.execute(
        "SELECT COUNT(*) FROM event_entities WHERE entity_id = ?", (eid,)).fetchone()[0]
    idt = identifiants(conn, eid)
    return {
        "id": eid, "nom": r["name"], "type": r["type"], "commune": r["commune"],
        "perimetre": r["perimetre"], "adresse": r["address"],
        "rna": idt["rna"], "siren": idt["siren"],
        "activite": r["naf_label"] or r["object"],
        "forme": r["legal_form_code"], "statut": r["status"],
        "creation": r["creation_date"], "vue_le": r["created_at"],
        "flux": flux[0], "euros": flux[1], "actes": actes,
        "identifie": bool(idt["rna"] or idt["siren"]),
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--instance", type=Path, default=ROOT)
    ap.add_argument("--seuil", type=float, default=0.80)
    ap.add_argument("--limite", type=int, default=40)
    ap.add_argument("--orphelines", action="store_true",
                    help="seulement les paires dont une fiche n'a aucun identifiant")
    ap.add_argument("--argent", action="store_true",
                    help="seulement les paires où les deux portent de l'argent")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    instance = args.instance.expanduser()
    base = sorted((instance / "db").glob("*.db"))[0]
    conn = ouvrir(base)
    print(f"\033[1mBase : {base}\033[0m   seuil {args.seuil}")

    paires = []
    for p in rapprochements(conn, seuil=args.seuil, racine=instance):
        a, b = (_detail(conn, m["id"]) for m in p["membres"])
        if args.orphelines and a["identifie"] and b["identifie"]:
            continue
        if args.argent and not (a["euros"] and b["euros"]):
            continue
        paires.append({"score": round(p["score"], 3), "a": a, "b": b})

    coupe = sum(1 for p in paires if p["a"]["euros"] and p["b"]["euros"])
    print(f"\n\033[1m{len(paires)} paire(s) à regarder\033[0m"
          f" — dont \033[33m{coupe} où les DEUX portent de l'argent\033[0m"
          " (une histoire de subvention coupée en deux).\n")

    for p in paires[:args.limite]:
        a, b = p["a"], p["b"]
        marque = " \033[33m← argent des deux côtés\033[0m" if (a["euros"] and b["euros"]) else ""
        print(f"  \033[1m{p['score']:.0%}\033[0m{marque}")
        for x in (a, b):
            ident = x["rna"] or x["siren"] or "\033[31msans identifiant\033[0m"
            print(f"    #{x['id']:<6} {x['type']:<11} {x['nom'][:44]:<44} {ident}")
            bas = [f"{x['commune'] or 'commune inconnue'} ({x['perimetre'] or '?'})"]
            if x["euros"]:
                bas.append(f"{x['flux']} flux / {x['euros']:.0f} €")
            if x["actes"]:
                bas.append(f"{x['actes']} acte(s)")
            if x["activite"]:
                bas.append(str(x["activite"])[:38])
            print(f"           {' · '.join(bas)}")
            if x["adresse"]:
                print(f"           {x['adresse'][:72]}")
        print()

    if len(paires) > args.limite:
        print(f"  … et {len(paires) - args.limite} de plus (--limite N)\n")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(paires, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        print(f"  Liste complète : {args.json}")


if __name__ == "__main__":
    main()
