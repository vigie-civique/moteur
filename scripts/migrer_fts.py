#!/usr/bin/env python3
"""Remet à neuf les triggers FTS d'une base créée avant leur correction.

`events_fts` et `entities_fts` sont des tables FTS5 à CONTENU EXTERNE : l'index
ne stocke pas le texte, il pointe vers la table source. Leurs triggers faisaient
`UPDATE events_fts SET …` et `DELETE FROM entities_fts WHERE rowid=old.id`, deux
ordres qu'une telle table ne sait pas exécuter — elle relit la table source pour
retirer les termes de l'ancienne version, source qui, dans un trigger `AFTER`,
porte déjà la nouvelle. L'index retire donc des termes absents et garde ceux
qu'il fallait retirer.

Le schéma est corrigé, mais `CREATE TRIGGER IF NOT EXISTS` ne remplace rien :
une base déjà créée garde ses anciens triggers, et continue de dériver. Ce
script fait les trois gestes, dans cet ordre :

    1. DROP des quatre triggers d'UPDATE et de DELETE ;
    2. rejeu de db/schema.sql, qui les recrée dans leur forme correcte ;
    3. `rebuild` des deux index, qui les reconstruit depuis la table source.

Le `rebuild` est ce qui répare l'existant : sans lui, la dérive accumulée reste
en place. Il relit toute la base — quelques secondes sur douze mille
événements.

    python3 scripts/migrer_fts.py                  # état des lieux
    python3 scripts/migrer_fts.py --appliquer

Sur une autre instance que le dépôt courant :

    VIGIE_INSTANCE=~/Claude/Saillans/config/instance.json \\
    VIGIE_DB=~/Claude/Saillans/db/26289.db \\
    python3 scripts/migrer_fts.py --appliquer

Idempotent : une base déjà migrée est reconnue et laissée telle quelle.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collectors.config import DB_PATH, SCHEMA_PATH  # noqa: E402
from collectors.db import get_conn  # noqa: E402

# Les quatre triggers à reprendre. Ceux d'INSERT sont justes : insérer dans une
# table à contenu externe est la seule opération qu'elle accepte telle quelle.
TRIGGERS = ("events_fts_update", "events_fts_delete",
            "entities_fts_update", "entities_fts_delete")

# La marque d'un trigger corrigé : il passe par la commande `'delete'` de FTS5.
MARQUE = "'delete'"


def etat(conn) -> dict[str, str]:
    """Le SQL de chaque trigger présent, par nom."""
    return {r[0]: r[1] or "" for r in conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND name IN "
        f"({','.join('?' * len(TRIGGERS))})", TRIGGERS)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--appliquer", action="store_true",
                    help="écrit en base (sans l'option : état des lieux)")
    args = ap.parse_args()

    conn = get_conn()
    print(f"base : {DB_PATH}")
    presents = etat(conn)
    a_reprendre = [t for t in TRIGGERS
                   if t in presents and MARQUE not in presents[t]]
    absents = [t for t in TRIGGERS if t not in presents]

    for t in TRIGGERS:
        if t in a_reprendre:
            marque = "✖ ancienne forme"
        elif t in absents:
            marque = "— absent"
        else:
            marque = "✓ déjà corrigé"
        print(f"  {marque:18} {t}")

    if not a_reprendre:
        print("\nRien à reprendre.")
        return 0
    if not args.appliquer:
        print(f"\n{len(a_reprendre)} trigger(s) à reprendre, puis rebuild des deux "
              f"index.\n[état des lieux] rien écrit — relancer avec --appliquer")
        return 0

    with conn:
        for t in a_reprendre:
            conn.execute(f"DROP TRIGGER {t}")
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    restants = [t for t, sql in etat(conn).items() if MARQUE not in sql]
    if restants:
        print(f"\n✖ triggers toujours en ancienne forme : {', '.join(restants)} — "
              f"le schéma rejoué ne les a pas recréés. Rien reconstruit.")
        return 1

    # Le rebuild est à part : il ne doit tourner qu'une fois les triggers sains,
    # sinon il reconstruit un index que la première écriture fera dériver à
    # nouveau.
    for table in ("events_fts", "entities_fts"):
        conn.execute(f"INSERT INTO {table}({table}) VALUES('rebuild')")
        conn.execute(f"INSERT INTO {table}({table}) VALUES('integrity-check')")
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  ✓ {table} reconstruit et vérifié — {n} lignes")
    conn.commit()
    print(f"\n✓ {len(a_reprendre)} trigger(s) repris, deux index reconstruits.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
