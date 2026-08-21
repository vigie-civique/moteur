#!/usr/bin/env python3
"""Rejoue le découpage des procès-verbaux sur une base déjà collectée.

    python3 scripts/redecouper_pv.py              # relit et montre ce qui périme
    python3 scripts/redecouper_pv.py --appliquer  # relit ET retire les périmés

La relecture écrit dans les deux cas — c'est une collecte, et elle est
idempotente. `--appliquer` ne commande que la SUPPRESSION des actes périmés,
la seule opération irréversible des deux.

Corriger `pv_parsers` ne corrige rien tant que la collecte n'est pas rejouée :
les actes du découpage précédent restent en base, et ce sont eux que le site
publie. Relancer `conseils` ne suffit pas non plus — il MET À JOUR les actes
qu'il retrouve, mais laisse en place ceux que le nouveau découpage ne produit
plus. Le 21/08/2026, c'étaient 78 % de la base de Lasalle : « Vu la saisine du
CT », « Thomas Vidal », un acte par ligne de procès-verbal.

La marche suivie :

  1. tous les actes COLLECTÉS reçoivent une marque dans leur `metadata` ;
  2. les procès-verbaux sont relus ; `conseils.enregistrer_deliberation`
     réécrit la métadonnée des actes qu'il retrouve, donc efface leur marque ;
  3. les actes encore marqués sont ceux que le nouveau découpage ne produit
     plus. Ils sont retirés — mais seulement si leur séance a bien été RELUE
     dans ce passage. Un document devenu inaccessible, ou scanné sans
     reconnaissance optique, ne doit rien faire disparaître.

Un acte qui porte un flux financier, un marché ou une annotation n'est jamais
retiré : quelque chose s'y accroche, c'est à un humain de trancher. Il est
listé à part.

Les actes SAISIS À LA MAIN (origine ≠ verbatim) ne sont ni marqués ni touchés.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collectors import conseils  # noqa: E402
from collectors.connecteurs import charger  # noqa: E402
from collectors.db import get_conn, transaction  # noqa: E402

MARQUE = "_redecoupage"
TYPES = tuple(p["delib"] for p in conseils.PORTEES.values())


def marquer(conn) -> int:
    cur = conn.execute(
        f"UPDATE events SET metadata = json_set(COALESCE(metadata,'{{}}'), "
        f"'$.{MARQUE}', 1) WHERE type IN ({','.join('?' * len(TYPES))}) "
        f"AND COALESCE(origine,'verbatim') = 'verbatim'", TYPES)
    return cur.rowcount


def relire(portee: str, avec_ocr: bool) -> set[str]:
    """Relit les procès-verbaux d'une portée ; rend les URL effectivement lues."""
    documents = charger().catalogue_pv(portee)
    print(f"\n[redécoupage] {portee} — {len(documents)} procès-verbaux catalogués")
    lues = set()
    for doc in documents:
        with transaction() as conn:
            r = conseils.traiter(conn, doc, portee, verbose=False, avec_ocr=avec_ocr)
        if r["statut"] == "ok":
            lues.add(doc.url)
    print(f"  {len(lues)} relus")
    return lues


def perimes(conn, lues: set[str]) -> tuple[list, list]:
    """(à retirer, retenus) parmi les actes encore marqués."""
    a_retirer, retenus = [], []
    for eid, date, titre, type_, url in conn.execute(
            f"SELECT id, date, title, type, source_url FROM events "
            f"WHERE type IN ({','.join('?' * len(TYPES))}) "
            f"AND json_extract(metadata, '$.{MARQUE}') = 1", TYPES):
        if url not in lues:
            continue          # séance non relue : on ne conclut rien
        accroches = sum(conn.execute(q, (eid,)).fetchone()[0] for q in (
            "SELECT COUNT(*) FROM financial_flows WHERE event_id=?",
            "SELECT COUNT(*) FROM marches_publics WHERE event_id=?",
            "SELECT COUNT(*) FROM annotations WHERE object_type='deliberation'"
            " AND object_id=?",
        ))
        (retenus if accroches else a_retirer).append((eid, date, titre, type_, accroches))
    return a_retirer, retenus


def demarquer(conn) -> None:
    conn.execute(
        f"UPDATE events SET metadata = json_remove(metadata, '$.{MARQUE}') "
        f"WHERE json_extract(metadata, '$.{MARQUE}') = 1")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--appliquer", action="store_true", help="écrit en base")
    ap.add_argument("--ocr", action="store_true",
                    help="reconnaissance optique des PDF scannés")
    ap.add_argument("--portee", choices=["commune", "epci"], action="append",
                    help="par défaut : les deux")
    args = ap.parse_args()
    portees = args.portee or ["commune", "epci"]

    conn = get_conn()
    avant = conn.execute(
        f"SELECT COUNT(*) FROM events WHERE type IN ({','.join('?' * len(TYPES))})",
        TYPES).fetchone()[0]

    with conn:
        marques = marquer(conn)
    print(f"{avant} actes en base, {marques} marqués (collectés)")

    lues: set[str] = set()
    for portee in portees:
        lues |= relire(portee, args.ocr)

    a_retirer, retenus = perimes(conn, lues)
    apres = conn.execute(
        f"SELECT COUNT(*) FROM events WHERE type IN ({','.join('?' * len(TYPES))})",
        TYPES).fetchone()[0]

    print(f"\n{apres} actes après relecture, dont {len(a_retirer)} périmés à retirer")
    for eid, date, titre, type_, _ in a_retirer[:12]:
        print(f"   {date or '?':<11} [{type_}] {(titre or '')[:60]}")
    if len(a_retirer) > 12:
        print(f"   … {len(a_retirer) - 12} autres")

    if retenus:
        print(f"\n{len(retenus)} acte(s) périmé(s) mais PORTANT quelque chose "
              f"— conservés, à trancher dans l'atelier :")
        for eid, date, titre, type_, n in retenus[:10]:
            print(f"   {date or '?':<11} {(titre or '')[:52]}  ({n} rattachement(s))")
        if len(retenus) > 10:
            print(f"   … {len(retenus) - 10} autres")

    if not args.appliquer:
        with conn:
            demarquer(conn)
        print("\nLes actes retrouvés ont été réécrits ; les périmés sont "
              "toujours là. Relancer avec --appliquer pour les retirer.")
        return 0

    with conn:
        for eid, *_ in a_retirer:
            conn.execute("DELETE FROM event_entities WHERE event_id=?", (eid,))
            conn.execute("DELETE FROM events WHERE id=?", (eid,))
        demarquer(conn)
    final = conn.execute(
        f"SELECT COUNT(*) FROM events WHERE type IN ({','.join('?' * len(TYPES))})",
        TYPES).fetchone()[0]
    print(f"\n✓ {len(a_retirer)} acte(s) retiré(s) — {avant} → {final}. "
          f"Régénérer le snapshot pour que le site en tienne compte.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
