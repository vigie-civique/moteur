#!/usr/bin/env python3
"""Une sauvegarde qu'on n'a jamais rouverte n'en est pas une.

    python3 scripts/verifier_sauvegarde.py                # la plus récente
    python3 scripts/verifier_sauvegarde.py <copie.db>     # celle-ci

Ouvre la copie en lecture seule, joue `PRAGMA integrity_check`, et compare ses
tables à celles de la base vivante : une copie saine mais d'avant le dernier
schéma se voit. Sort en 1 si la copie ne peut pas servir à restaurer.

Sans argument, cherche là où le moteur sauvegarde : `VIGIE_BACKUPS` (défaut
`~/Claude/.backups`, écrit par `collect_loop` et `qa_loop`) et, à côté de la
base, les `*.avant-*` des scripts d'entretien.

Restaurer reste un geste à la main, service arrêté : copier la sauvegarde à la
place de la base, et retirer les fichiers `-wal` et `-shm` de l'ancienne.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from collectors.sauvegarde import verifier  # noqa: E402


def la_plus_recente(base: Path) -> Path | None:
    racine = Path(os.environ.get("VIGIE_BACKUPS") or Path.home() / "Claude" / ".backups")
    candidates = [p for p in racine.glob(f"*/{base.name}") if p.is_file()]
    candidates += [p for p in base.parent.glob(f"{base.name}.avant-*")
                   if p.is_file() and not p.name.endswith((".partiel", "-wal", "-shm"))]
    return max(candidates, key=lambda p: p.stat().st_mtime, default=None)


def tables(chemin: Path) -> set[str]:
    conn = sqlite3.connect(f"{chemin.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("copie", nargs="?", help="la sauvegarde à vérifier")
    ap.add_argument("--base", help="la base vivante (défaut : celle de l'instance)")
    args = ap.parse_args(argv)

    if args.base:
        base = Path(args.base)
    else:
        from collectors.config import DB_PATH
        base = Path(DB_PATH)
    copie = Path(args.copie) if args.copie else la_plus_recente(base)
    if copie is None:
        print(f"✖ aucune sauvegarde de {base.name} trouvée.", file=sys.stderr)
        return 1

    constats = verifier(copie)
    if constats:
        print(f"✖ {copie} ne peut pas servir à restaurer :", file=sys.stderr)
        for c in constats:
            print(f"    {c}", file=sys.stderr)
        return 1
    print(f"✓ {copie} — intègre, {copie.stat().st_size / 1e6:.1f} Mo")
    if base.is_file():
        manquantes = sorted(tables(base) - tables(copie))
        if manquantes:
            print(f"  ⚠ {len(manquantes)} table(s) de la base vivante absentes de la copie "
                  f"(schéma plus récent) : {', '.join(manquantes[:8])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
