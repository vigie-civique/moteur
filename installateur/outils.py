#!/usr/bin/env python3
"""outils.py — trouver, ou poser sans droits d'administrateur, ce que le
dispositif exige : un Python récent et Node.

Ce module n'importe QUE la bibliothèque standard. Il tourne avant le venv,
avant `pip`, avant tout : ce qu'il réclamerait, personne ne l'aurait encore.

Le principe qui gouverne tout ce répertoire : **rien ne s'installe SUR la
machine**. Ce qui est téléchargé atterrit dans `installateur/.outils/`, dans le
dépôt, et s'en va avec lui. Pas de `sudo`, pas de PATH modifié, pas de paquet
système, pas de gestionnaire de paquets à apprendre. Quelqu'un qui essaie le
dispositif et l'abandonne doit pouvoir jeter un dossier, et que sa machine soit
exactement comme avant.

Corollaire : ce qui est DÉJÀ sur la machine est préféré. Un Node installé par
Homebrew ou par la logithèque de la distribution fait le travail ; le
télécharger une seconde fois serait 50 Mo pour rien.
"""
from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ICI = Path(__file__).resolve().parent
RACINE = ICI.parent
OUTILS = ICI / ".outils"

# La borne basse du moteur, celle de `pyproject.toml`. Elle n'est pas
# décorative : `X | None` en annotation d'exécution et `tomllib` sont
# postérieurs à 3.10.
PYTHON_MINIMAL = (3, 11)

# Node : la CI joue le build du site en 20, et Vite 5 réclame au moins 18. On
# accepte donc tout ce qui est ≥ 18 et déjà là, mais ce qu'on TÉLÉCHARGE est
# épinglé — une version flottante, c'est un build qui casse un jour sans que
# rien n'ait changé chez celui à qui il casse.
NODE_MINIMAL = 18
NODE_VERSION = "22.11.0"
NODE_DIST = "https://nodejs.org/dist"


# ── Le système, tel que les archives de Node le nomment ──────────────────────

def systeme() -> str:
    return {"Darwin": "macos", "Windows": "windows"}.get(platform.system(), "linux")


def windows() -> bool:
    return systeme() == "windows"


def architecture() -> str:
    m = platform.machine().lower()
    if m in ("arm64", "aarch64"):
        return "arm64"
    if m in ("x86_64", "amd64"):
        return "x64"
    return m


def _archive_node() -> tuple[str, str]:
    """(nom de l'archive, répertoire une fois déployée)."""
    sys_node = {"macos": "darwin", "linux": "linux", "windows": "win"}[systeme()]
    base = f"node-v{NODE_VERSION}-{sys_node}-{architecture()}"
    return (base + (".zip" if windows() else ".tar.gz" if sys_node == "darwin"
                    else ".tar.xz"), base)


# ── Interroger un exécutable sans réveiller le piège de macOS ────────────────

def _sortie(commande: list[str], secondes: int = 20) -> str | None:
    try:
        r = subprocess.run(commande, capture_output=True, text=True,
                           timeout=secondes)
    except (OSError, subprocess.SubprocessError):
        return None
    return (r.stdout or r.stderr).strip() if r.returncode == 0 else None


def _numero(texte: str | None) -> tuple[int, ...]:
    if not texte:
        return ()
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", texte)
    return tuple(int(g) for g in m.groups() if g) if m else ()


def _amorce_xcode(chemin: Path) -> bool:
    """`/usr/bin/python3` de macOS est un LEURRE tant que les outils de
    développement ne sont pas installés : l'appeler ouvre une fenêtre « voulez-vous
    installer les outils en ligne de commande ? » et rend un échec.

    Pour un installateur qui promet de ne rien demander, c'est le pire moment
    possible : une boîte de dialogue système, en anglais, qui parle de compilateur.
    On ne l'interroge donc jamais — on le saute, et on prend un vrai Python
    ailleurs (Homebrew, python.org, ou celui qu'on aura posé nous-mêmes).

    Le stub existe aussi pour `git` et `make`, mais nous ne les exigeons pas.
    """
    return (systeme() == "macos" and str(chemin) == "/usr/bin/python3"
            and not Path("/Library/Developer/CommandLineTools/usr/bin/python3").exists())


# ── Python ───────────────────────────────────────────────────────────────────

def pythons_candidats() -> list[Path]:
    """Les Python plausibles, du plus sûr au plus douteux.

    L'ordre compte : un Python de Homebrew ou de python.org est complet, celui
    d'un système Linux minimal peut l'être moins (`ensurepip` absent sur Debian
    sans `python3-venv`) — mais il reste préférable à rien, et l'échec de
    `venv` le dira clairement.
    """
    # `uv` range ses interpréteurs dans un sous-dossier versionné
    # (`cpython-3.12.…-macos-aarch64-none/`) : le chemin exact n'est pas
    # prévisible, il se cherche.
    poses = sorted(OUTILS.glob("python/*/" + ("python.exe" if windows()
                                              else "bin/python3")), reverse=True)
    vus: list[Path] = []
    for candidat in (
        *poses,
        Path("/opt/homebrew/bin/python3"), Path("/usr/local/bin/python3"),
        *(Path(p) for p in _pythons_du_chemin()),
    ):
        if candidat.exists() and candidat not in vus and not _amorce_xcode(candidat):
            vus.append(candidat)
    return vus


def _pythons_du_chemin() -> list[str]:
    noms = ["python3.14", "python3.13", "python3.12", "python3.11", "python3", "python"]
    return [c for c in (shutil.which(n) for n in noms) if c]


def python_convenable() -> Path | None:
    """Le premier Python assez récent, ou rien."""
    for candidat in pythons_candidats():
        if _numero(_sortie([str(candidat), "--version"]))[:2] >= PYTHON_MINIMAL:
            return candidat
    return None


# ── Node ─────────────────────────────────────────────────────────────────────

def node_local() -> Path | None:
    _, dossier = _archive_node()
    chemin = (OUTILS / dossier / "node.exe" if windows()
              else OUTILS / dossier / "bin" / "node")
    return chemin if chemin.exists() else None


def trouver_node() -> dict | None:
    """Node utilisable : celui qu'on a posé, sinon celui de la machine."""
    for chemin in (node_local(), Path(shutil.which("node") or "/introuvable")):
        if not chemin or not chemin.exists():
            continue
        version = _numero(_sortie([str(chemin), "--version"]))
        if version and version[0] >= NODE_MINIMAL:
            return {"chemin": str(chemin), "version": ".".join(map(str, version)),
                    "npm": str(npm_de(chemin)), "pose_par_nous": chemin == node_local()}
    return None


def npm_de(node: Path) -> Path:
    """npm vit à côté de node, et c'est un SCRIPT — pas un binaire.

    Sur Windows c'est `npm.cmd`, qu'il faut appeler tel quel ; ailleurs c'est un
    shell script. Le chercher dans le PATH quand on vient de poser un Node local
    reviendrait à lancer le npm d'une AUTRE installation de Node, avec les
    modules natifs compilés pour elle.
    """
    voisin = node.parent / ("npm.cmd" if windows() else "npm")
    if voisin.exists():
        return voisin
    # Un Node installé par un gestionnaire de paquets peut ranger `npm`
    # ailleurs ; à défaut de voisin, celui du PATH vaut mieux qu'un chemin qui
    # n'existe pas et une erreur « fichier introuvable » sans explication.
    return Path(shutil.which("npm") or voisin)


def environnement_node(node: Path | None) -> dict:
    """Un environnement où `node` posé par nous passe devant celui du système.

    npm relance `node` par le PATH : sans ce préfixe, un npm local pilote le
    node du système, et les deux versions se mélangent.
    """
    env = dict(os.environ)
    if node:
        env["PATH"] = str(Path(node).parent) + os.pathsep + env.get("PATH", "")
    # npm écrit son cache dans le profil de l'utilisateur, hors du dépôt. C'est
    # voulu : le cache est partagé entre instances et survit à une désinstallation.
    return env


# ── Téléchargements ──────────────────────────────────────────────────────────

class Echec(Exception):
    """Une étape qui n'a pas abouti, avec un message destiné à être LU."""


def telecharger(url: str, destination: Path, journal, quoi: str = "") -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    journal(f"   téléchargement : {url}")
    requete = urllib.request.Request(url, headers={"User-Agent": "VigieCivique/installateur"})
    try:
        with urllib.request.urlopen(requete, timeout=120) as flux, \
             open(destination, "wb") as sortie:
            total = int(flux.headers.get("Content-Length") or 0)
            recu = 0
            jalon = 0
            while True:
                bloc = flux.read(1 << 16)
                if not bloc:
                    break
                sortie.write(bloc)
                recu += len(bloc)
                if recu - jalon > 5 << 20:
                    jalon = recu
                    part = f" / {total / 1e6:.0f}" if total else ""
                    journal(f"   … {recu / 1e6:.0f}{part} Mo")
    except OSError as e:
        raise Echec(
            f"Téléchargement impossible ({quoi or url}) : {e}\n"
            "  La machine est-elle connectée ? Un proxy ou un pare-feu d'entreprise\n"
            "  bloque-t-il la sortie ? Rien n'a été modifié sur la machine."
        ) from e
    return destination


def empreinte(fichier: Path) -> str:
    h = hashlib.sha256()
    with open(fichier, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def _verifier_node(archive: Path, nom: str, journal) -> None:
    """L'empreinte publiée à côté de l'archive, comparée à celle reçue.

    Ce n'est PAS une vérification de signature : qui contrôlerait le serveur
    contrôlerait les deux fichiers. C'est un contrôle d'INTÉGRITÉ — un
    téléchargement tronqué par une coupure réseau produit une archive qui se
    déploie à moitié, et l'erreur apparaît alors trois étapes plus loin, sur un
    module manquant que personne ne rattache à la coupure.
    """
    liste = OUTILS / f"SHASUMS256-{NODE_VERSION}.txt"
    telecharger(f"{NODE_DIST}/v{NODE_VERSION}/SHASUMS256.txt", liste, journal,
                "empreintes Node")
    attendue = ""
    for ligne in liste.read_text(encoding="utf-8", errors="replace").splitlines():
        morceaux = ligne.split()
        if len(morceaux) == 2 and morceaux[1] == nom:
            attendue = morceaux[0]
    if not attendue:
        raise Echec(f"L'archive {nom} n'est pas listée dans les empreintes publiées.")
    obtenue = empreinte(archive)
    if obtenue != attendue:
        archive.unlink(missing_ok=True)
        raise Echec(f"Empreinte de {nom} incorrecte — archive écartée.\n"
                    f"  attendue {attendue[:16]}…, obtenue {obtenue[:16]}…")
    journal(f"   empreinte vérifiée ({obtenue[:16]}…)")


def installer_node(journal) -> dict:
    """Pose Node dans `installateur/.outils/`, sans toucher au système."""
    deja = trouver_node()
    if deja:
        journal(f"   Node {deja['version']} déjà présent — rien à télécharger.")
        return deja

    nom, dossier = _archive_node()
    journal(f"   Node {NODE_VERSION} pour {systeme()}/{architecture()} "
            f"(≈ 50 Mo, dans installateur/.outils/)")
    archive = telecharger(f"{NODE_DIST}/v{NODE_VERSION}/{nom}", OUTILS / nom,
                          journal, "Node")
    _verifier_node(archive, nom, journal)

    cible = OUTILS / dossier
    if cible.exists():
        shutil.rmtree(cible, ignore_errors=True)
    journal("   déploiement…")
    if nom.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(OUTILS)
    else:
        with tarfile.open(archive) as t:
            # `filter="data"` (3.12+) refuse les chemins absolus, les liens qui
            # sortent du répertoire et les fichiers spéciaux. Sur les versions
            # antérieures il n'existe pas ; l'archive vient de nodejs.org et son
            # empreinte est vérifiée, mais un contrôle qu'on peut avoir se prend.
            try:
                t.extractall(OUTILS, filter="data")
            except TypeError:
                t.extractall(OUTILS)
    archive.unlink(missing_ok=True)

    pose = trouver_node()
    if not pose:
        raise Echec(f"Node déployé dans {cible} mais introuvable ensuite — "
                    "l'archive n'avait pas la forme attendue.")
    journal(f"   ✓ Node {pose['version']}")
    return pose


# ── Ce qui est FACULTATIF, et ce qu'on perd sans ─────────────────────────────

def facultatifs() -> list[dict]:
    """Outils que le dispositif utilise s'il les trouve, et se passe sinon.

    Aucun n'empêche l'installation. Les lister sert à dire ce qui MANQUERA :
    un dispositif qui collecte moins sans le dire est pire qu'un dispositif qui
    annonce sa lacune — c'est la doctrine du site, elle vaut pour l'installateur.
    """
    def la(nom: str) -> bool:
        return bool(shutil.which(nom))

    langues = _sortie(["tesseract", "--list-langs"]) or ""
    return [
        {"nom": "ocrmypdf", "present": la("ocrmypdf"),
         "sans_lui": "les procès-verbaux SCANNÉS restent illisibles : le "
                     "dispositif les collecte, les affiche, mais n'en extrait "
                     "aucune délibération.",
         "poser": {"macos": "brew install ocrmypdf",
                   "linux": "apt install ocrmypdf",
                   "windows": "https://ocrmypdf.readthedocs.io"}[systeme()]},
        {"nom": "tesseract (français)", "present": la("tesseract") and "fra" in langues,
         "sans_lui": "l'OCR tournerait en anglais et rendrait un texte inexploitable.",
         "poser": {"macos": "brew install tesseract-lang",
                   "linux": "apt install tesseract-ocr-fra",
                   "windows": "https://tesseract-ocr.github.io"}[systeme()]},
        {"nom": "bsdtar", "present": la("bsdtar") or la("tar"),
         "sans_lui": "les extractions SISPEA (eau et assainissement) s'arrêtent "
                     "aux millésimes publiés par Hub'Eau.",
         "poser": {"macos": "fourni par le système",
                   "linux": "apt install libarchive-tools",
                   "windows": "fourni par le système"}[systeme()]},
    ]
