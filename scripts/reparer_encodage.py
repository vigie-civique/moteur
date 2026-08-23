#!/usr/bin/env python3
"""Défait, dans une base existante, le mojibake livré par les sources.

Pourquoi un script séparé
-------------------------
La réparation vit désormais au point d'écriture — `collectors.nom_normalise.
reparer_encodage`, appelée par `db.upsert_entity`, par le collecteur Sitadel et
par le collecteur BODACC. Mais ce qui est DÉJÀ en base ne repassera par aucun
de ces points avant la prochaine collecte complète, et « L'EUZIAÃÂRE »
s'affichait sur la page d'accueil du site public.

Ce script est donc le pendant unique de la réparation à l'entrée : il balaie
toutes les colonnes texte de toutes les tables, applique EXACTEMENT la même
fonction, et journalise chaque valeur touchée.

Ce qu'il garde
--------------
La valeur brute, dans `rectifications_encodage` : table, colonne, ligne, avant,
après, date. Une réparation d'encodage se défait mécaniquement, mais elle reste
une écriture dans la base de quelqu'un d'autre — elle doit pouvoir se relire,
se vérifier et se défaire. C'est la même exigence que pour les rectifications
déclarées de `config/instance.json` : rectifier n'est pas inventer, à condition
que ce soit énoncé.

Ce qu'il ne touche pas
----------------------
Les tables FTS et leurs tables d'ombre : ce sont des index, tenus à jour par
les triggers `*_fts_update` dès que la table source change. Les écrire à la
main les désynchroniserait de leur contenu.

Usage
-----
    python3 scripts/reparer_encodage.py                # simulation, n'écrit rien
    python3 scripts/reparer_encodage.py --appliquer    # écrit, après sauvegarde
    python3 scripts/reparer_encodage.py --base autre.db --json
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from collectors.nom_normalise import reparer_encodage  # noqa: E402

JOURNAL = """
CREATE TABLE IF NOT EXISTS rectifications_encodage (
    id        INTEGER PRIMARY KEY,
    table_nom TEXT NOT NULL,
    colonne   TEXT NOT NULL,
    ligne     INTEGER NOT NULL,
    avant     TEXT NOT NULL,
    apres     TEXT NOT NULL,
    motif     TEXT NOT NULL,
    applique_le TEXT NOT NULL
)
"""

MOTIF = ("Mojibake livré par la source : de l'UTF-8 relu en latin-1 ou cp1252, "
         "défait octet par octet. Aucune lettre n'est devinée.")


def tables_a_balayer(conn) -> list[str]:
    """Les tables ordinaires — ni FTS, ni tables d'ombre, ni tables système."""
    noms = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    virtuelles = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND sql LIKE '%VIRTUAL TABLE%'")}
    ombres = {n for v in virtuelles for n in noms if n.startswith(v + "_")}
    return [n for n in noms
            if n not in virtuelles and n not in ombres
            and not n.startswith("sqlite_")
            and n != "rectifications_encodage"]


def colonnes_texte(conn, table: str) -> list[str]:
    """Les colonnes susceptibles de porter du texte.

    Le type déclaré ne suffit pas : SQLite range volontiers du JSON dans une
    colonne sans type. On retient donc tout ce qui n'est pas explicitement
    numérique, et la lecture des valeurs fera le tri — un entier ne porte pas
    de mojibake.
    """
    numeriques = ("INT", "REAL", "FLOA", "DOUB", "NUM", "BOOL", "DATE")
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")
            if not any(n in (r[2] or "").upper() for n in numeriques)]


def a_un_rowid(conn, table: str) -> bool:
    try:
        conn.execute(f"SELECT rowid FROM {table} LIMIT 1").fetchone()
        return True
    except sqlite3.OperationalError:
        return False


def balayer(conn) -> list[dict]:
    """Toutes les valeurs que la réparation change, sans rien écrire."""
    trouvailles = []
    for table in tables_a_balayer(conn):
        if not a_un_rowid(conn, table):
            continue
        cols = colonnes_texte(conn, table)
        if not cols:
            continue
        liste = ", ".join(f'"{c}"' for c in cols)
        for ligne in conn.execute(f"SELECT rowid, {liste} FROM {table}"):
            rowid = ligne[0]
            for col, valeur in zip(cols, ligne[1:]):
                if not isinstance(valeur, str):
                    continue
                repare = reparer_encodage(valeur)
                if repare != valeur:
                    trouvailles.append({
                        "table": table, "colonne": col, "ligne": rowid,
                        "avant": valeur, "apres": repare,
                    })
    return trouvailles


def appliquer(conn, trouvailles: list[dict]) -> None:
    conn.execute(JOURNAL)
    maintenant = datetime.now().isoformat(timespec="seconds")
    for t in trouvailles:
        conn.execute(
            f'UPDATE "{t["table"]}" SET "{t["colonne"]}" = ? WHERE rowid = ?',
            (t["apres"], t["ligne"]))
        conn.execute(
            "INSERT INTO rectifications_encodage"
            " (table_nom, colonne, ligne, avant, apres, motif, applique_le)"
            " VALUES (?,?,?,?,?,?,?)",
            (t["table"], t["colonne"], t["ligne"], t["avant"], t["apres"],
             MOTIF, maintenant))
    conn.commit()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", help="chemin de la base (défaut : celle de l'instance)")
    ap.add_argument("--appliquer", action="store_true",
                    help="écrit les réparations (sinon : simulation)")
    ap.add_argument("--json", action="store_true", help="rapport en JSON")
    args = ap.parse_args(argv)

    if args.base:
        base = Path(args.base)
    else:
        from collectors.config import DB_PATH
        base = Path(DB_PATH)
    if not base.is_file():
        print(f"Base introuvable : {base}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(base)
    trouvailles = balayer(conn)

    if args.appliquer and trouvailles:
        sauvegarde = base.with_suffix(
            base.suffix + f".avant-encodage-{datetime.now():%Y%m%d-%H%M%S}")
        shutil.copy2(base, sauvegarde)
        appliquer(conn, trouvailles)
    else:
        sauvegarde = None

    par_table: dict[str, int] = {}
    for t in trouvailles:
        cle = f'{t["table"]}.{t["colonne"]}'
        par_table[cle] = par_table.get(cle, 0) + 1

    if args.json:
        print(json.dumps({
            "base": str(base), "applique": bool(args.appliquer and trouvailles),
            "sauvegarde": str(sauvegarde) if sauvegarde else None,
            "valeurs": len(trouvailles), "par_colonne": par_table,
        }, ensure_ascii=False, indent=2))
        return 0

    if not trouvailles:
        print(f"{base.name} : aucun encodage abîmé.")
        return 0

    print(f"{base.name} — {len(trouvailles)} valeurs à réparer :")
    for cle, n in sorted(par_table.items(), key=lambda kv: -kv[1]):
        print(f"  {n:5d}  {cle}")
    print()
    for t in trouvailles[:12]:
        print(f'  {t["table"]}.{t["colonne"]} #{t["ligne"]}')
        print(f'      avant : {t["avant"][:110]}')
        print(f'      après : {t["apres"][:110]}')
    if len(trouvailles) > 12:
        print(f"  … et {len(trouvailles) - 12} autres.")
    print()
    if args.appliquer:
        print(f"Appliqué. Sauvegarde : {sauvegarde.name}")
        print("Valeurs d'origine conservées dans `rectifications_encodage`.")
    else:
        print("Simulation — rien n'a été écrit. Relancer avec --appliquer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
