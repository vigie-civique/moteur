"""Le verrou de fichier — collectors/verrou.py.

🔴 `scripts/publication.py` importait `fcntl`, qui n'existe pas sous Windows :
l'API ne se chargeait pas, l'atelier ne démarrait pas, et le lanceur accusait
JWT_SECRET. Ces essais tournent aussi dans le job `windows` de la CI, où ils
exercent `msvcrt` pour de bon.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from collectors import verrou  # noqa: E402

TENIR = """
import sys, time
sys.path.insert(0, sys.argv[1])
from collectors import verrou
f = open(sys.argv[2], "a+")
verrou.prendre(f)
print("pris", flush=True)
time.sleep(60)
"""


def _tenant(chemin: Path) -> subprocess.Popen:
    p = subprocess.Popen([sys.executable, "-c", TENIR, str(ROOT), str(chemin)],
                         stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "pris"
    return p


def test_le_verrou_tenu_par_un_autre_processus_se_refuse_puis_se_rend(tmp_path):
    chemin = tmp_path / "essai.verrou"
    chemin.write_text("qui construit", encoding="utf-8")
    tenant = _tenant(chemin)
    try:
        with open(chemin, "a+") as f:
            with pytest.raises(BlockingIOError):
                verrou.prendre(f, attendre=False)
            with pytest.raises(BlockingIOError):
                verrou.prendre(f, partage=True, attendre=False)
        # Ce que le fichier contient reste lisible pendant qu'il est verrouillé :
        # c'est là que celui qui attend lit QUI construit.
        assert chemin.read_text(encoding="utf-8") == "qui construit"
    finally:
        tenant.kill()
        tenant.wait()
    # Le système rend le verrou d'un processus mort.
    with open(chemin, "a+") as f:
        verrou.prendre(f, attendre=False)
        verrou.rendre(f)


def test_le_verrou_se_prend_sur_un_descripteur_sans_deplacer_la_lecture(tmp_path):
    chemin = tmp_path / "essai.verrou"
    chemin.write_text("abcdef", encoding="utf-8")
    fd = os.open(chemin, os.O_RDWR)
    try:
        os.lseek(fd, 3, os.SEEK_SET)
        verrou.prendre(fd, attendre=False)
        assert os.lseek(fd, 0, os.SEEK_CUR) == 3
        verrou.rendre(fd)
        assert os.lseek(fd, 0, os.SEEK_CUR) == 3
    finally:
        os.close(fd)


def test_rien_dans_le_moteur_n_importe_un_module_absent_de_windows():
    """Le contrat : `fcntl` et ses pareils ne s'importent que dans verrou.py."""
    import ast
    interdits = {"fcntl", "pwd", "grp", "termios", "resource"}
    fautifs = []
    for dossier in ("collectors", "scripts", "installateur"):
        for py in sorted((ROOT / dossier).rglob("*.py")):
            if py == ROOT / "collectors" / "verrou.py":
                continue
            for noeud in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
                noms = ([a.name for a in noeud.names] if isinstance(noeud, ast.Import)
                        else [noeud.module or ""] if isinstance(noeud, ast.ImportFrom) else [])
                fautifs += [f"{py.relative_to(ROOT)} : {n}" for n in noms
                            if n.split(".")[0] in interdits]
    for py in sorted(ROOT.glob("*.py")):
        for noeud in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
            if isinstance(noeud, ast.Import):
                fautifs += [f"{py.name} : {a.name}" for a in noeud.names
                            if a.name.split(".")[0] in interdits]
    assert not fautifs, fautifs
