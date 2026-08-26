"""Primitives du magasin partagé pour les gros jeux nationaux.

Le magasin peut être lu simultanément par plusieurs instances. Une écriture se
fait donc dans un fichier voisin temporaire, puis par remplacement atomique :
un lecteur ne voit jamais un téléchargement partiel. Deux téléchargements
concurrents du même fichier restent possibles, mais leur résultat complet est
identique et aucun verrou orphelin ne peut bloquer les collectes suivantes.
"""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path


def est_frais(path: Path, jours: int | None) -> bool:
    """Un fichier non vide est frais ; ``None`` signifie immuable."""
    if not path.is_file() or path.stat().st_size == 0:
        return False
    if jours is None:
        return True
    return (time.time() - path.stat().st_mtime) / 86400 < jours


def ecrire_atomiquement(path: Path, contenu: bytes) -> None:
    """Publie ``contenu`` sans exposer de fichier incomplet aux lecteurs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporaire = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.part")
    try:
        temporaire.write_bytes(contenu)
        os.replace(temporaire, path)
    finally:
        temporaire.unlink(missing_ok=True)
