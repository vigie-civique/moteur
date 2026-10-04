#!/usr/bin/env python3
"""Le snapshot de référence : ce que le builder produit sur la base de la CI.

`tests/fixtures/snapshot_reference/` est la sortie du builder sur la base
d'épreuve, dossier d'épreuve compris — construite depuis `main` avant le
découpage du builder en étapes. `tests/test_snapshot_reference.py` reconstruit
ce snapshot avec le code courant, à la même horloge, et exige qu'il soit
identique : c'est ce qui permet de déplacer du code sans déplacer un octet.

Le jour où la sortie doit changer — c'est le but de la refonte du contenu —,
la référence se régénère DANS la même modification, et son diff dit exactement
ce qui change pour le lecteur du site :

    python3 tests/snapshot_reference.py --ecrire

La construction se fait dans une COPIE du moteur, pas dans le dépôt. Le
builder lit sous sa racine ce qu'une instance y pose (`dossiers/`,
`data/conseils/`, `config/sites_locaux.json`, le journal des corrections) et y
écrit son rapport de revue (`audits/`) : construit sur place, le snapshot
dépendrait du poste où la suite tourne, et le dossier d'épreuve atterrirait à
la racine du dépôt.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = Path(__file__).resolve().parent / "fixtures" / "snapshot_reference"

# Ce qu'il faut du dépôt pour amorcer la base et construire : le moteur, le
# schéma, l'instance factice, les règles d'exemple, le dossier d'épreuve.
# `api.py`, `api_auth.py` et `installateur/` ne servent qu'à la mesure de
# réplicabilité (`stats.replicabilite`), qui parcourt tout le moteur.
COPIE = ("collectors", "scripts", "installateur", "api.py", "api_auth.py",
         "db/schema.sql", "config/publication_rules.exemple.json",
         "tests/amorcer_base_ci.py", "tests/instance_test.json",
         "tests/fixtures/dossiers")

# Variables qui changeraient la construction si le poste les porte.
_A_RETIRER = ("VIGIE_RULES", "VIGIE_HORLOGE", "VIGIE_JOURNAL_CORRECTIONS")


def moteur_isole(code: Path, dest: Path) -> Path:
    """Une racine jetable qui ne contient que le moteur de `code`."""
    for rel in COPIE:
        source, cible = code / rel, dest / rel
        if source.is_dir():
            shutil.copytree(source, cible, ignore=shutil.ignore_patterns("__pycache__"))
        elif source.is_file():
            cible.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, cible)
    return dest


def horloge_de_reference() -> str:
    return json.loads((REFERENCE / "stats.json").read_text(encoding="utf-8"))["generated_at"]


def construire(code: Path, travail: Path, horloge: str | None = None) -> Path:
    """Amorce la base de la CI et construit son snapshot avec le moteur de
    `code`, dans `travail`. Rend le répertoire du snapshot."""
    racine = moteur_isole(code, travail / "moteur")
    db = racine / "db" / "ci.db"
    env = {k: v for k, v in os.environ.items() if k not in _A_RETIRER}
    env.update(VIGIE_INSTANCE=str(racine / "tests" / "instance_test.json"),
               VIGIE_DB=str(db), VIGIE_CI_DOSSIERS="1")
    r = subprocess.run([sys.executable, "tests/amorcer_base_ci.py"], cwd=racine, env=env,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"amorçage de la base : {r.stderr[-2000:]}")
    env["VIGIE_RULES"] = str(db.with_suffix(".regles.json"))
    if horloge:
        env["VIGIE_HORLOGE"] = horloge
    out = travail / "snapshot"
    # `build_snapshot` et lui seul : `main()` régénère aussi les libellés du site.
    code_py = ("import sys; sys.path.insert(0, 'scripts'); "
               "import build_public_snapshot as b; from pathlib import Path; "
               f"b.build_snapshot(Path({str(out)!r}))")
    r = subprocess.run([sys.executable, "-c", code_py], cwd=racine, env=env,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"construction du snapshot : {r.stderr[-2000:]}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--code", type=Path, default=ROOT,
                        help="racine du moteur à faire tourner (défaut : ce dépôt)")
    parser.add_argument("--ecrire", action="store_true",
                        help="remplace tests/fixtures/snapshot_reference/")
    parser.add_argument("--horloge", help="heure de construction (ISO)")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        out = construire(args.code.resolve(), Path(tmp), args.horloge)
        n = sum(1 for f in out.rglob("*") if f.is_file())
        if not args.ecrire:
            print(f"{n} fichiers construits — rien d'écrit (--ecrire pour remplacer la référence)")
            return 0
        if REFERENCE.exists():
            shutil.rmtree(REFERENCE)
        shutil.copytree(out, REFERENCE)
        print(f"{REFERENCE.relative_to(ROOT)} : {n} fichiers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
