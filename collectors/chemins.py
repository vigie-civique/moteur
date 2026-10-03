"""Un chemin construit à partir d'une requête ne sort jamais de sa racine.

Les appelants valident déjà ce qu'ils reçoivent (un slug par expression
régulière, un compte par type entier) : ce garde ne remplace pas ces contrôles,
il les double au seul endroit où une valeur devient un chemin. Il a deux
raisons d'être :

- une validation en amont peut être assouplie un jour sans que personne ne
  pense au chemin qu'elle protégeait — le garde, lui, ne dépend pas de la forme
  de la valeur ;
- l'analyse de code (CodeQL, `py/path-injection`) ne sait pas lire une
  expression régulière ni une vérification de type, et levait une alerte à
  chaque nouvelle écriture sur ces chemins (53 sur `main` au 03/10/2026). Elle
  reconnaît en revanche la forme `normpath` puis `startswith`, qui est
  précisément ce qui garantit l'appartenance.
"""
from __future__ import annotations

import os
from pathlib import Path


class CheminHorsRacine(ValueError):
    """La valeur reçue désignerait un fichier hors du répertoire attendu."""


def sous(racine: Path, *parties: str) -> Path:
    """`racine / parties…`, refusé s'il n'est pas STRICTEMENT sous `racine`.

    `normpath` résout `..` sans toucher au disque : un fichier qui n'existe pas
    encore (un dossier qu'on crée, un aperçu qu'on construit) se vérifie comme
    les autres. La comparaison se fait sur la racine suivie d'un séparateur,
    sans quoi `/srv/apercus-2` passerait pour un enfant de `/srv/apercus`.
    """
    base = os.path.normpath(os.path.abspath(racine))
    complet = os.path.normpath(os.path.join(base, *parties))
    if not complet.startswith(base + os.sep):
        raise CheminHorsRacine(f"Chemin refusé, hors de {base} : {os.path.join(*parties)!r}")
    return Path(complet)
