"""Primitives du magasin partagé pour les gros jeux nationaux.

Le magasin peut être lu simultanément par plusieurs instances. Une écriture se
fait donc dans un fichier voisin temporaire, puis par remplacement atomique :
un lecteur ne voit jamais un téléchargement partiel. Deux téléchargements
concurrents du même fichier restent possibles, mais leur résultat complet est
identique et aucun verrou orphelin ne peut bloquer les collectes suivantes.

Le magasin est un CACHE, jamais une source. Il peut être monté en lecture seule
— partagé par plusieurs instances dont une seule l'alimente, posé sur un disque
externe débranché, appartenant à un autre utilisateur. Ne pas pouvoir y écrire
n'est donc PAS une erreur de collecte : l'appelant vient d'obtenir son contenu,
il le garde, il ne le partage simplement pas.
"""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path


# Un step écrit des dizaines de fichiers : un magasin refusé le serait autant
# de fois. On n'avertit qu'une fois par dossier.
_refus_signales: set[str] = set()


def est_frais(path: Path, jours: int | None) -> bool:
    """Un fichier non vide est frais ; ``None`` signifie immuable."""
    if not path.is_file() or path.stat().st_size == 0:
        return False
    if jours is None:
        return True
    return (time.time() - path.stat().st_mtime) / 86400 < jours


def _signaler_refus(path: Path, erreur: OSError) -> None:
    cle = str(path.parent)
    if cle in _refus_signales:
        return
    _refus_signales.add(cle)
    print(f"  [magasin] écriture refusée dans {cle} ({type(erreur).__name__}) — "
          f"la collecte continue, le fichier n'est pas partagé")


def ecrire_atomiquement(path: Path, contenu: bytes) -> bool:
    """Publie ``contenu`` sans exposer de fichier incomplet aux lecteurs.

    Rend ``True`` si le fichier est désormais dans le magasin, ``False`` si
    celui-ci a refusé l'écriture. Ne lève jamais : c'est ce qui garantit qu'un
    magasin en lecture seule ne fait pas échouer une collecte.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        _signaler_refus(path, e)
        return False

    temporaire = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.part")
    try:
        temporaire.write_bytes(contenu)
        os.replace(temporaire, path)
        return True
    except OSError as e:
        _signaler_refus(path, e)
        return False
    finally:
        try:
            temporaire.unlink(missing_ok=True)
        except OSError:
            pass
