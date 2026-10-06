"""Verrou de fichier entre processus, sous POSIX comme sous Windows.

`fcntl` n'existe pas sous Windows : importé nu par `scripts/publication.py`, il
empêchait l'API — donc l'atelier — de démarrer sur un poste que l'installateur
vise pourtant. Tout verrou de fichier du moteur passe par ici.

Dans les deux mondes, le système rend le verrou d'un processus mort : c'est ce
qui le distingue d'un fichier-témoin, qui survit au plantage.

Sous Windows, `msvcrt.locking` ne sait ni partager ni attendre plus de dix
secondes, et son verrou est IMPÉRATIF — l'octet verrouillé ne se lit plus. On
verrouille donc un octet loin après la fin du fichier, pour que ce qu'il
contient (qui construit, depuis quand) reste lisible par celui qui attend ; un
verrou « partagé » y est exclusif, ce qui suffit à qui ne le prend que pour
regarder.
"""
from __future__ import annotations

import os
import time

try:                                    # POSIX
    import fcntl
except ImportError:                     # Windows
    fcntl = None
    try:
        import msvcrt
    except ImportError:                 # ni l'un ni l'autre : dit à l'usage
        msvcrt = None

_OCTET = 1 << 30


def _fd(f) -> int:
    return f if isinstance(f, int) else f.fileno()


def _msvcrt(fd: int, mode: int) -> None:
    ici = os.lseek(fd, 0, os.SEEK_CUR)
    os.lseek(fd, _OCTET, os.SEEK_SET)
    try:
        msvcrt.locking(fd, mode, 1)
    finally:
        os.lseek(fd, ici, os.SEEK_SET)


def prendre(f, *, partage: bool = False, attendre: bool = True) -> None:
    """Prend le verrou sur un fichier ouvert (objet ou descripteur).

    Sans `attendre`, lève `BlockingIOError` s'il est tenu ailleurs.
    """
    fd = _fd(f)
    if fcntl:
        fcntl.flock(fd, (fcntl.LOCK_SH if partage else fcntl.LOCK_EX)
                    | (0 if attendre else fcntl.LOCK_NB))
        return
    if msvcrt is None:
        raise OSError("aucun verrou de fichier sur ce système (ni fcntl ni msvcrt)")
    while True:
        try:
            _msvcrt(fd, msvcrt.LK_NBLCK)
            return
        except OSError as e:
            if not attendre:
                raise BlockingIOError(e.errno, "verrou tenu par un autre processus") from e
            time.sleep(0.1)


def rendre(f) -> None:
    fd = _fd(f)
    if fcntl:
        fcntl.flock(fd, fcntl.LOCK_UN)
    else:
        _msvcrt(fd, msvcrt.LK_UNLCK)
