#!/usr/bin/env python3
"""Relit les décomptes de voix ET les montants des actes déjà collectés.

Le texte des procès-verbaux est en base : rien à retélécharger. Seule la LECTURE
du décompte était fautive — elle n'acceptait qu'une tournure, « X voix pour et Y
contre », et rendait zéro opposition pour toutes les autres. Un acte adopté « par
3 voix contre et 10 voix pour » était publié comme adopté sans opposition.

Même chose pour les montants : le motif d'extraction recollait ce qui précédait
le chiffre — « CD30 145 834,00 € » devenait 30 145 834 €, sur une commune dont
le budget tient en 2 M€.

Ce script rejoue `extract_vote` et `extract_amounts` sur `events.content` et
n'écrit que là où le résultat CHANGE. Il affiche d'abord ce qu'il ferait.

    python3 scripts/relire_actes.py               # ce qui changerait
    python3 scripts/relire_actes.py --appliquer
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collectors.cm_parser import extract_amounts, extract_vote  # noqa: E402
from collectors.config import DB_PATH          # noqa: E402

TYPES = ("deliberation", "conseil_municipal", "deliberation_cc", "conseil_communautaire")


def compare(avant: dict | None, apres: dict | None) -> str | None:
    """Ce qui a changé, en clair — ou None si rien."""
    if (avant or None) == (apres or None):
        return None
    fmt = (lambda v: "aucun vote lu" if not v else
           ("unanimité" if v.get("unanimite") else
            f"{v.get('pour')} pour / {v.get('contre')} contre / "
            f"{v.get('abstentions')} abstention(s)"))
    return f"{fmt(avant)}  →  {fmt(apres)}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--appliquer", action="store_true")
    ap.add_argument("--db", default=str(DB_PATH))
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    marque = ",".join("?" * len(TYPES))
    lignes = conn.execute(
        f"SELECT id, date, title, content, metadata FROM events "
        f"WHERE type IN ({marque}) AND content IS NOT NULL", TYPES).fetchall()

    changements, opposition_revelee, pertes = [], 0, []
    for r in lignes:
        try:
            meta = json.loads(r["metadata"] or "{}")
        except json.JSONDecodeError:
            continue
        if not isinstance(meta, dict):
            continue
        avant = meta.get("vote")
        apres = extract_vote(r["content"])
        diff = compare(avant, apres)

        # Les montants : mêmes valeurs relues, sur le même texte.
        montants_avant = [m.get("value") for m in (meta.get("montants") or [])
                          if isinstance(m, dict)]
        montants_apres = [m["value"] for m in extract_amounts(r["content"])]
        if montants_avant != montants_apres:
            perdus = sorted(set(montants_avant) - set(montants_apres), reverse=True)[:2]
            diff = ((diff + " · ") if diff else "") + (
                f"montants : {len(montants_avant)} → {len(montants_apres)}"
                + (f" (écartés : {', '.join(f'{v:,.0f} €'.replace(',', ' ') for v in perdus)})"
                   if perdus else ""))
            meta["montants"] = extract_amounts(r["content"])

        if not diff:
            continue
        # Le cas qui compte : une opposition qui n'était pas comptée.
        if apres and (apres.get("contre") or apres.get("abstentions")) \
                and not ((avant or {}).get("contre") or (avant or {}).get("abstentions")):
            opposition_revelee += 1
        # Et le cas qu'il ne faut jamais accepter sans regarder : une lecture
        # qui EFFACE ce qu'on savait. Relire ne doit pas appauvrir.
        if avant and (
                (apres is None)
                or (avant.get("pour") is not None and apres.get("pour") is None)
                or (avant.get("unanimite") and not apres.get("unanimite")
                    and not apres.get("contre") and not apres.get("abstentions"))):
            pertes.append(f"   {r['date']}  {(r['title'] or '')[:32]:32}  {diff}")
        meta["vote"] = apres
        changements.append((r["id"], r["date"], r["title"] or "", diff,
                            json.dumps(meta, ensure_ascii=False)))

    print(f"{len(lignes)} actes relus, {len(changements)} décompte(s) modifié(s)")
    print(f"   dont {opposition_revelee} où une OPPOSITION n'était pas comptée\n")
    for _, date, titre, diff, _ in changements[:15]:
        print(f"   {date}  {titre[:32]:32}  {diff}")
    if len(changements) > 15:
        print(f"   … et {len(changements) - 15} autres")

    if pertes:
        print(f"\n⚠️  {len(pertes)} acte(s) où la relecture PERD une information "
              f"connue — à regarder avant d'appliquer :")
        for ligne in pertes[:10]:
            print(ligne)
        if len(pertes) > 10:
            print(f"   … et {len(pertes) - 10} autres")

    if not args.appliquer:
        print("\n(relancer avec --appliquer pour écrire)")
        return 0

    with conn:
        conn.executemany("UPDATE events SET metadata = ? WHERE id = ?",
                         [(m, i) for i, _, _, _, m in changements])
    print(f"\n{len(changements)} acte(s) mis à jour.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
