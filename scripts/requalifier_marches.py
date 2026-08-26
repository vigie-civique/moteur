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

⚠ LIMITE, décisive sur les bases collectées avant le 20/08/2026.
`acheteur_nom` ne contenait pas le nom déclaré par la source : le collecteur y
écrivait le nom de l'entité qu'il avait cru reconnaître. La trace de ce qui
avait été lu était donc écrasée, et aucun réexamen n'est possible depuis la
base — toutes les lignes affirment le même acheteur, les justes comme les
fausses. Ce script le détecte et le dit. La seule sortie est alors de purger
les marchés de la source concernée et de relancer la collecte, qui les
reprendra avec l'attribution stricte et conservera l'énoncé de la source :

    python3 scripts/requalifier_marches.py --purger-source BOAMP --appliquer
    python3 -m collectors.run_all --step marches
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collectors.config import COMMUNE_NAME, COMMUNES_ADRESSE, EPCI_NOM  # noqa: E402
from collectors.db import get_conn  # noqa: E402
from collectors.marches_publics import _norme_acheteur  # noqa: E402
from collectors.marches_publics import attribution_acheteur  # noqa: E402

# Les autres noms du périmètre, pour qu'un nom tronqué par la source ne soit
# accepté que s'il ne convient qu'à une seule collectivité.
_HOMONYMES = tuple(c["nom"] for c in COMMUNES_ADRESSE.values())


def attribution(acheteur_nom: str) -> str:
    """'commune', 'epci', ou '' — la règle vit dans le collecteur, pas ici.

    Elle y était recopiée : une requalification pouvait donc trancher autrement
    que la collecte qui l'avait précédée, et le test de l'une ne disait rien de
    l'autre.
    """
    return attribution_acheteur(acheteur_nom, homonymes=_HOMONYMES)


def purger(conn, source: str, appliquer: bool) -> int:
    """Supprime les marchés d'une source, avec leurs actes et flux.

    À n'utiliser que lorsque le nom d'acheteur de la source a été écrasé et
    qu'aucun réexamen n'est possible en base. La recollecte les reprendra.
    """
    n = conn.execute("SELECT COUNT(*) FROM marches_publics WHERE source=?",
                     (source,)).fetchone()[0]
    if not n:
        print(f"Aucun marché de source « {source} ».")
        return 0
    if not appliquer:
        print(f"{n} marché(s) de source « {source} » seraient supprimés, "
              f"avec leurs actes et flux financiers.\n"
              f"Relancer avec --appliquer, puis :\n"
              f"    python3 -m collectors.run_all --step marches")
        return 0
    with conn:
        events = [r[0] for r in conn.execute(
            "SELECT event_id FROM marches_publics WHERE source=? AND event_id IS NOT NULL",
            (source,))]
        conn.execute("DELETE FROM marches_publics WHERE source=?", (source,))
        for ev in events:
            conn.execute("DELETE FROM financial_flows WHERE event_id=?", (ev,))
            conn.execute("DELETE FROM event_entities WHERE event_id=?", (ev,))
            conn.execute("DELETE FROM events WHERE id=?", (ev,))
    print(f"✓ {n} marché(s) « {source} » supprimés, avec {len(events)} acte(s) et "
          f"leurs flux.\n  Relancer :  python3 -m collectors.run_all --step marches")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--appliquer", action="store_true",
                    help="écrit en base (sans l'option : simulation)")
    ap.add_argument("--purger-source", metavar="SOURCE",
                    help="supprime les marchés de cette source (ex. BOAMP), avec "
                         "leurs actes et flux, pour qu'une recollecte les reprenne")
    args = ap.parse_args()

    conn = get_conn()
    colonnes = {r[1] for r in conn.execute("PRAGMA table_info(marches_publics)")}
    if "confidence" not in colonnes:
        print("✖ colonne `confidence` absente — lancer d'abord "
              "`python3 -m collectors.run_all --step init`", file=sys.stderr)
        return 1

    if args.purger_source:
        return purger(conn, args.purger_source, args.appliquer)

    lignes = conn.execute(
        "SELECT id, acheteur_nom, confidence, source, objet FROM marches_publics"
    ).fetchall()

    # La colonne porte-t-elle encore l'énoncé de la source, ou le libellé
    # résolu ? Le signe : TOUS les acheteurs d'une source se réduisent aux deux
    # libellés que le collecteur savait produire. Une source qui rendrait
    # vraiment ses noms en aurait autant que d'acheteurs distincts.
    par_source: dict[str, set[str]] = {}
    effectif: dict[str, int] = {}
    for _, nom, _, source, _ in lignes:
        s = source or "?"
        par_source.setdefault(s, set()).add((nom or "").strip())
        effectif[s] = effectif.get(s, 0) + 1
    resolus = {_norme_acheteur(COMMUNE_NAME), _norme_acheteur(EPCI_NOM)}
    ecrasees = [s for s, noms in par_source.items()
                if effectif[s] > 5 and {_norme_acheteur(n) for n in noms} <= resolus]
    if ecrasees:
        print("⚠ Le nom d'acheteur déclaré par la source a été écrasé pour :")
        for s in ecrasees:
            noms = " / ".join(sorted(n[:34] for n in par_source[s]))
            print(f"    {s} — {effectif[s]} marché(s), sous {len(par_source[s])} "
                  f"libellé(s) seulement : {noms}")
        print("\n  Aucune requalification n'est possible depuis la base : toutes les\n"
              "  lignes affirment le même acheteur, les justes comme les fausses.\n"
              "  Purger et recollecter :\n"
              f"      python3 scripts/requalifier_marches.py --purger-source {ecrasees[0]} --appliquer\n"
              "      python3 -m collectors.run_all --step marches\n")

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
