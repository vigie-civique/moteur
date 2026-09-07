#!/usr/bin/env python3
"""etapes.py — ce que l'installateur FAIT, une étape à la fois.

L'assistant (assistant.py) ne fait qu'ordonner et raconter ; tout le travail est
ici, en fonctions qui prennent un `journal` et lèvent `Echec` avec un message
destiné à être lu par quelqu'un qui n'est pas informaticien.

Deux règles tiennent ce fichier :

1. **Chaque étape est rejouable.** Une installation s'interrompt — une coupure
   réseau, un ordinateur qu'on referme, une erreur. Rejouer ne doit rien casser :
   le venv existe déjà, `npm ci` refait la même chose, le compte existe déjà et
   le dit. La seule étape qui refuse de se rejouer aveuglément est celle du
   secret de session, et pour une raison écrite à sa ligne.

2. **Rien de secret ne passe par la ligne de commande ni par le journal.** Un
   mot de passe en argument est lisible dans la liste des processus de la
   machine, par n'importe quel utilisateur. Il passe par l'entrée standard.

Ce module n'importe que la bibliothèque standard : l'étape 1 s'exécute avant
que la moindre dépendance ne soit installée.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from outils import (Echec, RACINE, environnement_node, npm_de,  # noqa: E402
                    systeme, trouver_node, windows)

CONFIG = RACINE / "config"
INSTANCE = CONFIG / "instance.json"
ENV = RACINE / ".env"


# ── Lancer un programme et raconter ce qu'il dit ─────────────────────────────

def python_venv() -> Path:
    return RACINE / "venv" / ("Scripts/python.exe" if windows() else "bin/python3")


def courir(commande: list[str], journal, *, cwd: Path = RACINE,
           env: dict | None = None, entree: str | None = None,
           arret: threading.Event | None = None, quoi: str = "") -> None:
    """Exécute, retransmet ligne à ligne, refuse en cas d'échec.

    La sortie d'erreur est fondue dans la sortie standard : séparées, elles
    s'affichent dans le désordre et un message d'erreur se retrouve trois
    paragraphes avant la ligne qui l'a provoqué.

    L'encodage est FORCÉ en UTF-8 dans les deux sens. Sur Windows, la console
    est en cp1252 : les accents des messages du moteur — et il n'en manque
    pas — arrivaient en mojibake, quand ils ne levaient pas d'exception au
    milieu d'une collecte de trois heures.
    """
    environnement = dict(env or os.environ)
    # La racine du dépôt sur le chemin d'import. Un script du moteur lancé par
    # son CHEMIN — `…/scripts/init_instance.py` — reçoit `scripts/` comme
    # premier élément de `sys.path`, jamais la racine : `from collectors…`
    # échoue alors en plein milieu de l'amorçage, APRÈS que les règles de
    # publication ont été écrites. Le shell de celui qui a écrit ces scripts
    # avait la racine dans son chemin ; un dépôt fraîchement cloné, non.
    ancien = environnement.get("PYTHONPATH", "")
    environnement["PYTHONPATH"] = (str(RACINE) + (os.pathsep + ancien if ancien else ""))
    environnement.setdefault("PYTHONUTF8", "1")
    environnement.setdefault("PYTHONIOENCODING", "utf-8")
    environnement.setdefault("PYTHONUNBUFFERED", "1")

    journal(f"$ {' '.join(str(c) for c in commande)}")
    try:
        processus = subprocess.Popen(
            [str(c) for c in commande], cwd=str(cwd), env=environnement,
            stdin=subprocess.PIPE if entree is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1)
    except OSError as e:
        raise Echec(f"{quoi or commande[0]} n'a pas pu démarrer : {e}") from e

    if entree is not None and processus.stdin:
        processus.stdin.write(entree)
        processus.stdin.close()

    for ligne in processus.stdout or []:
        journal(ligne.rstrip("\n"))
        if arret is not None and arret.is_set():
            processus.terminate()
            journal("   … interrompu à la demande.")
            break
    code = processus.wait()
    if arret is not None and arret.is_set():
        raise Echec("Étape interrompue. Ce qui était fait reste fait : "
                    "relancer reprend là où on s'est arrêté.")
    if code != 0:
        raise Echec(f"{quoi or commande[0]} s'est arrêté en erreur (code {code}). "
                    "Le journal ci-dessus dit pourquoi.")


# ── 1. Les dépendances ───────────────────────────────────────────────────────

def creer_venv(journal, python_amorce: str | Path) -> None:
    """Le venv se crée DANS le dépôt, jamais ailleurs — cf. requirements.txt."""
    if python_venv().exists():
        journal("   venv déjà présent.")
    else:
        journal("   création de l'environnement Python (venv/)…")
        try:
            courir([python_amorce, "-m", "venv", str(RACINE / "venv")], journal,
                   quoi="création du venv")
        except Echec as e:
            raise Echec(
                f"{e}\n"
                "  Sur Debian et Ubuntu, `venv` est dans un paquet à part :\n"
                "    sudo apt install python3-venv\n"
                "  C'est le seul endroit de cette installation où le système\n"
                "  demande des droits d'administrateur."
            ) from e
    courir([python_venv(), "-m", "pip", "install", "--upgrade", "pip", "--quiet"],
           journal, quoi="pip")


def installer_dependances_python(journal) -> None:
    journal("   installation des dépendances Python (≈ 2 min la première fois)…")
    courir([python_venv(), "-m", "pip", "install", "-r",
            str(RACINE / "requirements.txt")], journal, quoi="pip install")


def installer_dependances_node(journal, node: Path) -> None:
    """`npm ci` et non `npm install` — les versions sont épinglées à l'exact.

    Le README dit pourquoi en détail : des plages de versions ont laissé
    SvelteKit dériver jusqu'à une version qui attend Svelte 5, et le build
    passait en crachant six avertissements que plus personne ne lisait.
    """
    env = environnement_node(node)
    for paquet, quoi in ((RACINE / "public", "le site public"),
                         (RACINE / "dashboard", "l'atelier")):
        journal(f"   npm ci — {quoi} (≈ 1 min)…")
        courir([npm_de(node), "ci", "--no-audit", "--no-fund"], journal,
               cwd=paquet, env=env, quoi=f"npm ci ({quoi})")


# ── 2. L'instance : quelle commune, et qui la tient ──────────────────────────

def amorcer_instance(journal, insee: str, ecraser: bool) -> None:
    """`init_instance.py` interroge les référentiels nationaux et écrit
    config/instance.json — le seul endroit du dispositif où une donnée de
    commune a le droit d'exister."""
    if not re.fullmatch(r"[0-9AB]{5}", insee.upper()):
        raise Echec(f"« {insee} » n'est pas un code INSEE : cinq caractères, "
                    "chiffres (ou 2A / 2B pour la Corse).")
    commande = [python_venv(), str(RACINE / "scripts" / "init_instance.py"), insee]
    if ecraser:
        commande.append("--force")
    courir(commande, journal, quoi="amorçage de l'instance")


def completer_instance(journal, reponses: dict) -> None:
    """Reporte dans l'instance ce qu'aucun référentiel ne publie.

    L'éditeur (qui publie, sous quel statut, joignable où, hébergé chez qui)
    n'est pas un ornement : les mentions légales l'affichent, et un site qui
    publie des actes administratifs sans dire qui l'édite met son auteur en
    faute. `init_instance.py` ne peut pas le deviner — c'est ici qu'on le
    demande, une fois, plutôt que dans un fichier JSON à ouvrir à la main.
    """
    if not INSTANCE.exists():
        raise Echec("config/instance.json absent : l'amorçage n'a pas abouti.")
    inst = json.loads(INSTANCE.read_text(encoding="utf-8"))

    editeur = {k: (reponses.get(f"editeur_{k}") or "").strip()
               for k in ("nom", "statut", "email", "hebergeur")}
    if not editeur["nom"] or not editeur["email"]:
        raise Echec("Le nom et le courriel de l'éditeur sont obligatoires : "
                    "les mentions légales les affichent.")
    inst["editeur"] = editeur

    for cle in ("commune_url", "epci_url", "depot_url", "site_url"):
        valeur = (reponses.get(cle) or "").strip()
        if valeur:
            inst[cle] = valeur
    if reponses.get("connecteur"):
        inst["connecteur"] = reponses["connecteur"]

    # Le statut de l'instance : ce qu'un lecteur doit savoir AVANT de lire un
    # chiffre. Le défaut reste « démonstration », qui est le plus modeste et le
    # plus vrai tant que personne n'a pris l'instance en charge.
    type_statut = reponses.get("statut_type") or "demonstration"
    tenue_par = (reponses.get("statut_tenue_par") or "").strip()
    if type_statut == "tenue" and not tenue_par:
        raise Echec("Une instance déclarée « tenue » doit dire par QUI : c'est "
                    "la seule chose qui distingue un portage tenu d'une "
                    "démonstration automatique.")
    inst["statut"] = {"_doc": inst.get("statut", {}).get("_doc", ""),
                      "type": type_statut, "tenue_par": tenue_par}

    INSTANCE.write_text(json.dumps(inst, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    journal("   ✓ config/instance.json complété (éditeur, statut, sites)")

    # Les fichiers d'instance que le dépôt ne livre qu'en exemple. Sans eux,
    # deux collecteurs partent sur un catalogue vide sans le dire.
    for exemple, reel in (("profils_locaux.exemple.json", "profils_locaux.json"),
                          ("seed_local.exemple.json", "seed_local.json")):
        cible = CONFIG / reel
        if not cible.exists() and (CONFIG / exemple).exists():
            shutil.copy(CONFIG / exemple, cible)
            journal(f"   ✓ config/{reel} créé depuis l'exemple")

    # Les règles de publication tiennent la liste des sources publiables : elle
    # inclut le domaine du site de la mairie, qu'on vient peut-être de corriger.
    # Sans ce rafraîchissement, les actes lus sur le site officiel sont collectés
    # et jamais publiés — sans erreur, sans avertissement.
    courir([python_venv(), str(RACINE / "scripts" / "init_instance.py"),
            inst["commune_insee"], "--regles"], journal, quoi="règles de publication")
    courir([python_venv(), str(RACINE / "scripts" / "generer_libelles.py")],
           journal, quoi="libellés")


def creer_base(journal) -> None:
    """Le schéma. `--step init` ne sort pas sur le réseau et ne collecte rien."""
    courir([python_venv(), "-m", "collectors.run_all", "--step", "init"],
           journal, quoi="création de la base")


# ── 3. Le secret de session et le premier compte ─────────────────────────────

def creer_env(journal) -> None:
    """Écrit `.env` avec un secret tiré au sort, et ne le refait JAMAIS.

    Le README porte l'avertissement en majuscules : rejouer le `cp` sur un
    `.env` déjà rempli remet le secret à vide et l'atelier redevient
    inaccessible. Un installateur qu'on relance est un cas NORMAL — il ne doit
    pas être le moyen de perdre ses sessions.
    """
    if ENV.exists() and re.search(r"^JWT_SECRET=.+$",
                                  ENV.read_text(encoding="utf-8"), re.M):
        journal("   .env déjà rempli — secret conservé.")
        return
    modele = (RACINE / "deploy" / "env.exemple").read_text(encoding="utf-8")
    contenu = re.sub(r"^JWT_SECRET=.*$", f"JWT_SECRET={secrets.token_hex(32)}",
                     modele, count=1, flags=re.M)
    # ALLOWED_ORIGINS ne sert qu'à un atelier EN LIGNE. L'exemple porte une
    # adresse de démonstration : la laisser ferait croire qu'elle compte.
    contenu = re.sub(r"^ALLOWED_ORIGINS=.*$", "ALLOWED_ORIGINS=", contenu,
                     count=1, flags=re.M)
    ENV.write_text(contenu, encoding="utf-8")
    if not windows():
        ENV.chmod(0o600)
    journal("   ✓ .env créé, secret de session tiré au sort (32 octets)")


def creer_compte(journal, email: str, motdepasse: str, role: str = "admin") -> None:
    """Le mot de passe passe par l'ENTRÉE STANDARD, jamais par un argument.

    `ps` montre la ligne de commande de tout processus à tout utilisateur de la
    machine. Un mot de passe en argument est un mot de passe publié.
    """
    if len(motdepasse) < 12:
        raise Echec("Mot de passe trop court : 12 caractères au minimum.")
    if "@" not in email:
        raise Echec("L'identifiant de connexion est une adresse de courriel.")
    if role not in ("admin", "validator", "contributor"):
        raise Echec(f"Rôle inconnu : {role}")
    code = (
        "import sys\n"
        "from scripts.create_user import create_user\n"
        "create_user(sys.argv[1], sys.argv[2], sys.stdin.readline().rstrip('\\n'))\n"
    )
    courir([python_venv(), "-c", code, email, role], journal,
           entree=motdepasse + "\n", quoi="création du compte")


# ── 4. Collecter, puis publier ───────────────────────────────────────────────

def collecter(journal, arret: threading.Event | None = None) -> None:
    """La collecte complète : 48 collecteurs, de quelques minutes à quelques
    heures selon la commune et ce que ses sites publient.

    Elle est REPRENABLE : chaque passage est journalisé dans `collector_runs`,
    et un collecteur interrogé récemment est sauté au lancement suivant. On peut
    donc l'arrêter et la reprendre le lendemain sans tout refaire.
    """
    courir([python_venv(), "-m", "collectors.run_all"], journal,
           arret=arret, quoi="collecte")


def publier(journal, node: Path) -> None:
    """Snapshot → invariants → build. Les trois étapes de deploy/publier-site.sh,
    rejouées ici en Python parce qu'un `.sh` ne s'exécute pas sous Windows.

    L'ordre et les refus sont les mêmes, et c'est ce qui compte : un snapshot
    qui viole un invariant n'atteint pas le build.
    """
    # Refuser AVANT de travailler, plutôt que d'échouer trois minutes plus tard
    # sur un message qui parle d'autre chose : sur une base vide, le snapshot se
    # construit, les invariants passent (il n'y a rien à faire fuir), et c'est
    # SvelteKit qui s'arrête — sur une trace Node parlant de routes non
    # explorées, où personne ne lit « vous n'avez pas encore collecté ».
    base = base_de_l_instance()
    if base is None:
        raise Echec("Aucune instance configurée : rien à publier.")
    if _compter(base, "entities") == 0:
        raise Echec(
            "Rien à publier : la base ne contient aucune fiche.\n"
            "  Le site est construit à partir de ce qui a été collecté — il faut\n"
            "  donc lancer la collecte d'abord (étape « Première collecte »).")

    courir([python_venv(), str(RACINE / "scripts" / "build_public_snapshot.py")],
           journal, quoi="snapshot public")

    # macOS sème des .DS_Store dans tout répertoire ouvert au Finder, et le
    # contrôle d'étanchéité les refuse — à juste titre : ce sont des fichiers du
    # poste, ils n'ont rien à faire dans un site publié.
    for racine in (RACINE / "public" / "static" / "data", RACINE / "public" / "build"):
        for parasite in racine.rglob(".DS_Store"):
            parasite.unlink(missing_ok=True)

    courir([python_venv(), str(RACINE / "scripts" / "verify_snapshot.py"),
            str(RACINE / "public" / "static" / "data")], journal,
           quoi="contrôle d'étanchéité")
    courir([npm_de(node), "run", "build"], journal, cwd=RACINE / "public",
           env=environnement_node(node), quoi="build du site public")
    journal("   ✓ site construit dans public/build/ — il se téléverse tel quel "
            "chez n'importe quel hébergeur de fichiers statiques.")


def construire_atelier(journal, node: Path) -> None:
    """Construit l'atelier en fichiers statiques, servis ensuite par l'API.

    Pourquoi construire plutôt que lancer le serveur de développement de Vite :
    parce que le mode développement exige DEUX processus et DEUX ports, et que
    la panne la plus fréquente du dispositif est précisément là — « Serveur
    inaccessible » quand l'interface n'atteint pas l'API. Construit, l'atelier
    est servi par l'API elle-même, sur un seul port, à une seule adresse. Il n'y
    a plus de proxy à traverser, donc plus rien à mal régler.
    """
    courir([npm_de(node), "run", "build"], journal, cwd=RACINE / "dashboard",
           env=environnement_node(node), quoi="build de l'atelier")


# ── 5. De quoi relancer sans jamais ouvrir un terminal ───────────────────────

LANCEURS = {
    "macos": ("Vigie Civique.command",
              '#!/bin/bash\n'
              '# Double-cliquer ce fichier ouvre l\'atelier Vigie Civique.\n'
              'cd "$(dirname "$0")"\n'
              'exec "./venv/bin/python3" installateur/lancer.py\n'),
    "linux": ("Vigie Civique.sh",
              '#!/bin/bash\n'
              '# Double-cliquer ce fichier ouvre l\'atelier Vigie Civique.\n'
              'cd "$(dirname "$0")"\n'
              'exec "./venv/bin/python3" installateur/lancer.py\n'),
    "windows": ("Vigie Civique.bat",
                '@echo off\r\n'
                'rem Double-cliquer ce fichier ouvre l\'atelier Vigie Civique.\r\n'
                'cd /d "%~dp0"\r\n'
                '"venv\\Scripts\\python.exe" installateur\\lancer.py\r\n'
                'pause\r\n'),
}


def ecrire_lanceurs(journal) -> list[str]:
    """Un fichier à double-cliquer, à la racine du dossier.

    C'est le point de tout ce répertoire : après l'installation, plus personne
    ne doit avoir à taper une commande pour ouvrir son atelier.
    """
    ecrits = []
    nom, contenu = LANCEURS[systeme()]
    chemin = RACINE / nom
    chemin.write_text(contenu, encoding="utf-8",
                      newline="" if windows() else None)
    if not windows():
        chemin.chmod(0o755)
    ecrits.append(nom)

    if systeme() == "linux":
        # Un `.desktop` pour les environnements de bureau, qui affichent un nom
        # et une icône là où un `.sh` n'affiche qu'un fichier. Il vit à côté du
        # dépôt et non dans ~/.local/share/applications : l'installateur ne
        # dépose rien hors de son dossier, c'est la règle du répertoire.
        bureau = RACINE / "Vigie Civique.desktop"
        bureau.write_text(
            "[Desktop Entry]\nType=Application\nName=Vigie Civique\n"
            "Comment=Atelier de l'observatoire citoyen\n"
            f"Exec={RACINE / 'venv' / 'bin' / 'python3'} "
            f"{RACINE / 'installateur' / 'lancer.py'}\n"
            f"Path={RACINE}\nTerminal=false\nCategories=Office;\n",
            encoding="utf-8")
        bureau.chmod(0o755)
        ecrits.append(bureau.name)

    journal("   ✓ " + " et ".join(f"« {n} »" for n in ecrits)
            + " — à double-cliquer pour ouvrir l'atelier.")
    return ecrits


def base_de_l_instance() -> Path | None:
    """La base de l'instance, telle que le moteur la nomme : db/<insee>.db."""
    if not INSTANCE.exists():
        return None
    try:
        insee = json.loads(INSTANCE.read_text(encoding="utf-8")).get("commune_insee")
    except ValueError:
        return None
    chemin = RACINE / "db" / f"{insee}.db" if insee else None
    return chemin if chemin and chemin.exists() else None


def _compter(base: Path, table: str, ou: str = "1=1") -> int:
    import sqlite3
    try:
        conn = sqlite3.connect(f"file:{base}?mode=ro", uri=True, timeout=2)
        try:
            return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {ou}").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error:
        return 0


def _passages_de_collecte(base: Path) -> int:
    """Combien de collecteurs ont déjà tourné, `init` mis à part.

    Lu en LECTURE SEULE : cette fonction est appelée à chaque rafraîchissement
    de la page d'installation, y compris pendant une collecte qui écrit.
    """
    return _compter(base, "collector_runs", "step != 'init'")


def etat_instance() -> dict:
    """Ce que l'installation a déjà fait, lu sur le disque et non dans un
    fichier d'état — un fichier d'état ment dès qu'on touche au dossier à la
    main, et c'est exactement ce que fait quelqu'un qui répare."""
    inst = {}
    if INSTANCE.exists():
        try:
            inst = json.loads(INSTANCE.read_text(encoding="utf-8"))
        except ValueError:
            inst = {}
    # Une base CRÉÉE n'est pas une base COLLECTÉE : le schéma se pose en une
    # seconde, la collecte prend des heures. Compter les fichiers ferait
    # afficher « collecte terminée » à une instance vide — le genre de faux
    # témoignage qui fait chercher une panne là où il n'y a rien à chercher.
    base, passages = "", 0
    if inst.get("commune_insee"):
        candidate = RACINE / "db" / f"{inst['commune_insee']}.db"
        if candidate.exists():
            base = str(candidate)
            passages = _passages_de_collecte(candidate)
    node = trouver_node()
    return {
        "venv": python_venv().exists(),
        "modules_site": (RACINE / "public" / "node_modules").is_dir(),
        "node": node,
        "instance": {"insee": inst.get("commune_insee", ""),
                     "nom": inst.get("commune_nom", ""),
                     "editeur": bool(inst.get("editeur", {}).get("nom")),
                     "a_faire": inst.get("_a_faire", [])} if inst else None,
        "base": base,
        "passages_collecte": passages,
        "env": ENV.exists(),
        "atelier_construit": (RACINE / "dashboard" / "dist" / "index.html").exists(),
        "site_construit": (RACINE / "public" / "build" / "index.html").exists(),
    }
