"""Copier une base SQLite vivante, entière.

La base est en WAL (`collectors/db.py::get_conn`) : ce qui vient d'être validé
vit dans `<base>-wal` tant qu'aucun point de contrôle ne l'a reversé dans le
fichier principal. Quatre scripts la sauvegardaient par `shutil.copy2` — le
fichier principal seul, donc sans les dernières écritures, et sans garantie
qu'une page ne soit pas copiée à moitié pendant qu'un collecteur écrit.

`sqlite3.Connection.backup` lit la base PAR SQLite : la copie est celle qu'un
lecteur verrait à l'instant du début, journal compris.

Bibliothèque standard seule, et pas de `collectors.config` : `reparer_encodage`
répare une base désignée par son chemin, sans instance configurée.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def sauvegarder(source: Path | str, dest: Path | str) -> Path:
    """Copie `source` vers `dest` par l'API de sauvegarde de SQLite.

    Écrit à côté puis renomme : une sauvegarde interrompue ne laisse pas un
    fichier au nom d'une sauvegarde entière.
    """
    source, dest = Path(source), Path(dest)
    if not source.is_file():
        raise FileNotFoundError(f"base à sauvegarder introuvable : {source}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    partiel = dest.with_name(dest.name + ".partiel")
    partiel.unlink(missing_ok=True)
    origine = sqlite3.connect(str(source))
    try:
        copie = sqlite3.connect(str(partiel))
        try:
            origine.backup(copie)
        finally:
            copie.close()
    finally:
        origine.close()
    os.replace(partiel, dest)
    return dest


def verifier(chemin: Path | str) -> list[str]:
    """Ce qui empêche de se fier à cette copie. Vide : elle est saine."""
    chemin = Path(chemin)
    if not chemin.is_file():
        return [f"{chemin} : fichier absent"]
    try:
        conn = sqlite3.connect(f"{chemin.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as e:
        return [f"{chemin} : ne s'ouvre pas ({e})"]
    try:
        constats = [r[0] for r in conn.execute("PRAGMA integrity_check")]
        if constats != ["ok"]:
            return [f"{chemin} : {c}" for c in constats[:10]]
        if not conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]:
            return [f"{chemin} : aucune table — une base vide n'est pas une sauvegarde"]
    except sqlite3.Error as e:
        return [f"{chemin} : illisible ({e})"]
    finally:
        conn.close()
    return []
