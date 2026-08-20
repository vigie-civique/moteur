#!/usr/bin/env python3
"""Recalcule la certitude d'attribution des marchés déjà collectés.

Le collecteur BOAMP concluait sur un mot commun : « terres » attrapait les
Terres australes, « cévennes » le GHT Cévennes Gard Camargue. Tout ce qui
matchait un jeton du nom de l'EPCI se retrouvait attribué à l'intercommunalité.
Corrigé à la collecte le 20/08/2026 — mais `INSERT OR IGNORE` ne revient pas sur
les lignes déjà en base, et elles prennent `verified` par défaut à l'ajout de la
colonne. Ce script les relit et tranche à nouveau, sur le nom complet.

Il ne supprime rien : un marché non attribuable passe en `probable`, donc hors
publication, et attend un arbitrage dans l'atelier.

    python3 scripts/requalifier_marches.py            # simulation
    python3 scripts/requalifier_marches.py --appliquer

Idempotent : le relancer ne change plus rien.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collectors.config import COMMUNE_NAME, EPCI_NOM  # noqa: E402
from collectors.db import get_conn  # noqa: E402
from collectors.marches_publics import _norme_acheteur  # noqa: E402


def attribution(acheteur_nom: str) -> str:
    """'commune', 'epci', ou '' si le nom ne permet pas de conclure."""
    n = _norme_acheteur(acheteur_nom)
    if _norme_acheteur(COMMUNE_NAME) in n:
        return "commune"
    if _norme_acheteur(EPCI_NOM) in n:
        return "epci"
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--appliquer", action="store_true",
                    help="écrit en base (sans l'option : simulation)")
    args = ap.parse_args()

    conn = get_conn()
    colonnes = {r[1] for r in conn.execute("PRAGMA table_info(marches_publics)")}
    if "confidence" not in colonnes:
        print("✖ colonne `confidence` absente — lancer d'abord "
              "`python3 -m collectors.run_all --step init`", file=sys.stderr)
        return 1

    lignes = conn.execute(
        "SELECT id, acheteur_nom, confidence, source, objet FROM marches_publics"
    ).fetchall()

    a_degrader, a_promouvoir = [], []
    for mid, nom, actuelle, source, objet in lignes:
        voulue = "verified" if attribution(nom or "") else "probable"
        if voulue == actuelle:
            continue
        (a_degrader if voulue == "probable" else a_promouvoir).append(
            (mid, nom or "", source, objet or ""))

    print(f"{len(lignes)} marché(s) en base")
    print(f"  → {len(a_degrader)} à passer en « probable » (acheteur non établi)")
    print(f"  → {len(a_promouvoir)} à repasser en « verified »")

    if a_degrader:
        print("\nExemples de ce qui sortira de la publication :")
        for _, nom, source, objet in a_degrader[:6]:
            print(f"  [{source}] acheteur déclaré : {nom[:44]}")
            print(f"           {objet[:68]}")

    if not args.appliquer:
        print("\nSimulation. Relancer avec --appliquer pour écrire.")
        return 0

    with conn:
        for mid, *_ in a_degrader:
            conn.execute("UPDATE marches_publics SET confidence='probable' WHERE id=?", (mid,))
        for mid, *_ in a_promouvoir:
            conn.execute("UPDATE marches_publics SET confidence='verified' WHERE id=?", (mid,))
        # Le flux financier porte le même montant attribué au même acheteur :
        # le laisser publié pendant que le marché ne l'est plus prêterait de
        # l'argent à une collectivité sur la foi de rien.
        conn.execute("""
            UPDATE financial_flows SET confidence='probable'
             WHERE type='marché' AND event_id IN (
                   SELECT event_id FROM marches_publics WHERE confidence='probable')
        """)
    print(f"\n✓ {len(a_degrader) + len(a_promouvoir)} ligne(s) requalifiée(s). "
          "Régénérer le snapshot pour que le site en tienne compte.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
