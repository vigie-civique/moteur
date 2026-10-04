"""Le manifeste du snapshot : ce qu'une construction a écrit, fichier par fichier.

Le 04/10/2026, un plantage au milieu de la génération a laissé un brouillon
tronqué : `stats.json` y était — c'est le premier fichier écrit — mais ni
`entite/` ni `entity_index.json`, et l'atelier a construit le site dessus.
Rien dans le répertoire ne disait qu'il était incomplet : un fichier présent
ne prouve pas que la construction est allée au bout.

Le manifeste le prouve. C'est le DERNIER fichier écrit : un répertoire qui
n'en a pas est une construction interrompue. Il liste chaque fichier du
snapshot avec son empreinte SHA-256, sa taille, le nombre d'objets qu'il
porte et l'étape du registre qui l'a écrit, plus la révision du moteur qui
l'a construit. `scripts/verify_snapshot.py` refuse un snapshot sans manifeste,
un fichier présent qu'il ne liste pas, un fichier listé absent, une empreinte
qui ne concorde pas.

L'ancien manifeste est retiré AVANT la première écriture (`retirer_manifeste`) :
une construction qui plante dans un répertoire réutilisé ne laisse pas derrière
elle le manifeste de la précédente, qui couvrirait des fichiers à moitié
réécrits.

Hors manifeste, comme hors de l'empreinte de `scripts/publication.py` :
`version.json`, que la publication écrit APRÈS le contrôle dans chaque
répertoire mis en service, et les rebuts du poste (`.DS_Store`…), que la
publication retire et que le contrôle refuse de toute façon.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from fnmatch import fnmatchcase
from pathlib import Path

from scripts.snapshot.socle import ROOT

NOM = "manifeste.json"
FORMAT = "vigie-manifeste/1"
# Écrit par la publication après le contrôle (`publication.VERSION_SERVIE`).
VERSION_SERVIE = "version.json"
# Mêmes rebuts que `publication.REBUT_DU_POSTE` : le Finder en sème pendant
# qu'on travaille, la publication les retire avant de contrôler.
REBUT_DU_POSTE = re.compile(r"^(\.DS_Store|\._.*|Thumbs\.db)$", re.I)


def hors_manifeste(rel: str) -> bool:
    nom = rel.rsplit("/", 1)[-1]
    return rel in (NOM, VERSION_SERVIE) or bool(REBUT_DU_POSTE.match(nom))


def compter_objets(chemin: Path, brut: bytes) -> int | None:
    """Ce que porte un fichier, en un nombre — de quoi voir d'un coup d'œil un
    `entities.json` vide là où il y en avait mille.

    Un tableau JSON : ses éléments. Un objet JSON : la somme des éléments de
    ses tableaux de premier niveau (`entities`, `features`, `annuel` +
    `annexe`…), ou 1 s'il n'en a aucun — une fiche, des compteurs. Un fichier
    qui n'est pas du JSON (README, feuilles HTML) : `null`.
    """
    if chemin.suffix not in (".json", ".geojson"):
        return None
    try:
        donnees = json.loads(brut)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if isinstance(donnees, list):
        return len(donnees)
    if isinstance(donnees, dict):
        listes = [v for v in donnees.values() if isinstance(v, list)]
        return sum(len(v) for v in listes) if listes else 1
    return 1


def revision_du_moteur(racine: Path = ROOT) -> tuple[str | None, bool | None]:
    """Le commit du moteur qui construit, et s'il porte des modifications non
    validées. `(None, None)` hors d'un dépôt git (une archive du kit) : le dire
    vaut mieux que d'inventer un numéro."""
    def git(*args):
        return subprocess.run(["git", "-C", str(racine), *args], capture_output=True,
                              text=True, timeout=20)
    try:
        tete = git("rev-parse", "HEAD")
        if tete.returncode != 0:
            return None, None
        etat = git("status", "--porcelain", "--untracked-files=no")
        return tete.stdout.strip(), (bool(etat.stdout.strip()) if etat.returncode == 0 else None)
    except (OSError, subprocess.SubprocessError):
        return None, None


def etape_retirer_manifeste(out) -> None:
    """Avant la première écriture : le répertoire ne déclare plus rien tant que
    la construction n'est pas allée au bout."""
    (Path(out) / NOM).unlink(missing_ok=True)


def etape_manifeste(out, stats) -> None:
    """Le dernier fichier du snapshot : tous les autres, et qui les a écrits."""
    # Le registre importe ce module : la liste des étapes se lit à l'appel.
    from scripts.snapshot.etapes import ETAPES

    out = Path(out)
    fichiers = []
    for f in sorted(out.rglob("*")):
        rel = f.relative_to(out).as_posix()
        if not f.is_file() or hors_manifeste(rel):
            continue
        brut = f.read_bytes()
        auteurs = [e.nom for e in ETAPES if any(fnmatchcase(rel, m) for m in e.ecrit)]
        fichiers.append({
            "chemin": rel,
            # `null` : un fichier qu'aucune étape ne déclare — laissé là par
            # une construction précédente dans un répertoire réutilisé.
            "etape": auteurs[0] if len(auteurs) == 1 else None,
            "objets": compter_objets(f, brut),
            "octets": len(brut),
            "sha256": hashlib.sha256(brut).hexdigest(),
        })
    revision, modifie = revision_du_moteur()
    entete = {
        "format": FORMAT,
        "genere_le": stats.get("generated_at"),
        "revision_moteur": revision,
        "moteur_modifie": modifie,
        "total": len(fichiers),
    }
    # Une ligne par fichier : le manifeste se relit et se compare ligne à ligne.
    lignes = [json.dumps(entete, ensure_ascii=False, indent=2)[:-2] + ","]
    lignes.append('  "fichiers": [')
    lignes += [f"    {json.dumps(f, ensure_ascii=False)}," for f in fichiers]
    if fichiers:
        lignes[-1] = lignes[-1][:-1]
    lignes += ["  ]", "}"]
    (out / NOM).write_text("\n".join(lignes) + "\n", encoding="utf-8")
