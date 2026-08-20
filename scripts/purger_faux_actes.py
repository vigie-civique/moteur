#!/usr/bin/env python3
"""Retire les « actes » qui ne sont que des lignes de tableau de financement.

    python3 scripts/purger_faux_actes.py              # simulation
    python3 scripts/purger_faux_actes.py --appliquer

Les procès-verbaux contiennent des tableaux de plan de financement, et le
découpage coupait dedans : chaque ligne devenait un acte. Le 20/08/2026, la base
de Lasalle en comptait 275, tous publiés, dont un en première page du site —
« 2 506,51 € TTC (TVA: 20%) ».

Le découpage refuse désormais de les créer (`pv_parsers._titre_plausible`), mais
les actes déjà en base y restent : ce script les retire, avec leurs
rattachements. Il applique EXACTEMENT le même critère que le découpage, pour que
les deux ne puissent pas diverger.

Il refuse de toucher un acte qui porte un flux financier, une annotation ou un
marché : si quelque chose s'y accroche, c'est qu'il n'était pas du bruit, et
c'est à un humain de trancher.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collectors.db import get_conn  # noqa: E402
from collectors.pv_parsers import _titre_plausible  # noqa: E402


def reperer(conn) -> tuple[list[tuple], list[tuple]]:
    """(à retirer, retenus) — les retenus portent quelque chose, on n'y touche pas."""
    a_retirer, retenus = [], []
    for eid, date, titre, type_ in conn.execute(
            "SELECT id, date, title, type FROM events WHERE title IS NOT NULL"):
        if _titre_plausible(titre):
            continue
        accroches = sum(conn.execute(q, (eid,)).fetchone()[0] for q in (
            "SELECT COUNT(*) FROM financial_flows WHERE event_id=?",
            "SELECT COUNT(*) FROM marches_publics WHERE event_id=?",
            "SELECT COUNT(*) FROM annotations WHERE object_type='deliberation' AND object_id=?",
        ))
        (retenus if accroches else a_retirer).append((eid, date, titre, type_, accroches))
    return a_retirer, retenus


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--appliquer", action="store_true", help="écrit en base")
    args = ap.parse_args()

    conn = get_conn()
    a_retirer, retenus = reperer(conn)

    print(f"{len(a_retirer)} acte(s) à retirer — titre sans mots, seulement des montants")
    for eid, date, titre, type_, _ in a_retirer[:10]:
        print(f"   {date or '?':<11} [{type_}] {titre[:56]}")
    if len(a_retirer) > 10:
        print(f"   … {len(a_retirer) - 10} autres")

    if retenus:
        print(f"\n{len(retenus)} acte(s) au titre douteux mais PORTANT quelque chose "
              f"— conservés, à trancher dans l'atelier :")
        for eid, date, titre, type_, n in retenus[:6]:
            print(f"   {date or '?':<11} {titre[:48]}  ({n} rattachement(s))")

    if not args.appliquer:
        print("\nSimulation. Relancer avec --appliquer pour écrire.")
        return 0
    if not a_retirer:
        return 0

    with conn:
        for eid, *_ in a_retirer:
            conn.execute("DELETE FROM event_entities WHERE event_id=?", (eid,))
            conn.execute("DELETE FROM events WHERE id=?", (eid,))
    print(f"\n✓ {len(a_retirer)} acte(s) retiré(s). "
          f"Régénérer le snapshot pour que le site en tienne compte.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
