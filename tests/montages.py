"""Un système de fichiers où `rename` traverse ou non un montage, comme sous systemd.

`ProtectSystem=strict` + plusieurs `ReadWritePaths` : chacun est un montage
« bind » séparé, et `rename(2)` entre deux montages rend `EXDEV`. Hors de tout
`ReadWritePaths`, c'est `EROFS`. Un essai ordinaire, qui tient dans un seul
répertoire jetable, ne voit ni l'un ni l'autre : c'est ce qui a laissé passer le
défaut du 04/10/2026 (la promotion ne pouvait pas se faire sous l'unité).

Ce que ça simule : le CODE D'ERREUR du noyau pour un renommage, d'après le
montage de chaque extrémité. Ce que ça ne simule pas : le reste de ce qu'un bac
à sable change (`open` en écriture hors des chemins ouverts, `link`, `symlink`).
`tests/test_bascule_entre_montages.py` joue en plus, quand l'exécuteur le permet,
la même opération dans de VRAIS montages (`unshare -m`).
"""
from __future__ import annotations

import errno
import os
from pathlib import Path


class Montages:
    def __init__(self, racines):
        self.racines = [Path(os.path.abspath(r)) for r in racines]
        self.renommages: list[tuple[str, str]] = []

    def de(self, chemin) -> Path | None:
        chemin = Path(os.path.abspath(chemin))
        candidats = [r for r in self.racines if chemin == r or r in chemin.parents]
        return max(candidats, key=lambda r: len(r.parts), default=None)

    def installer(self, monkeypatch) -> "Montages":
        vrai_rename, vrai_replace = os.rename, os.replace

        def garde(vrai):
            def renommer(src, dst, *a, **kw):
                self.renommages.append((os.fspath(src), os.fspath(dst)))
                de, vers = self.de(src), self.de(dst)
                if de is None or vers is None:
                    raise OSError(errno.EROFS, "Read-only file system", os.fspath(dst))
                if de != vers:
                    raise OSError(errno.EXDEV, "Invalid cross-device link", os.fspath(dst))
                # Un point de montage lui-même ne se renomme pas (EBUSY).
                if Path(os.path.abspath(src)) in self.racines:
                    raise OSError(errno.EBUSY, "Device or resource busy", os.fspath(src))
                return vrai(src, dst, *a, **kw)
            return renommer

        monkeypatch.setattr(os, "rename", garde(vrai_rename))
        monkeypatch.setattr(os, "replace", garde(vrai_replace))
        return self


def reloger(publication, racine: Path, monkeypatch) -> dict[str, Path]:
    """Les emplacements de `publication` sous `racine`, à leur place relative.

    `racine` joue `/opt/vigie`. Les chemins viennent des constantes du module
    (PUBLIE, SITE, VERSIONS…), pas d'une liste recopiée ici : un emplacement
    déplacé demain est déplacé aussi dans l'essai.
    """
    ancienne = publication.ROOT
    lieux = {nom: racine / getattr(publication, nom).relative_to(ancienne)
             for nom in ("PUBLIE", "SITE", "VERSIONS", "BROUILLON", "ETAT", "VERROU")}
    monkeypatch.setattr(publication, "ROOT", racine)
    for nom, chemin in lieux.items():
        monkeypatch.setattr(publication, nom, chemin)
    return lieux
