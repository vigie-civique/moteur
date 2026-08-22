#!/usr/bin/env python3
"""Le flux de publication en deux temps : aperçu, contrôle, puis publication.

Jusqu'au 22/08/2026 l'atelier n'avait qu'un bouton, « Générer & synchroniser le
snapshot », qui construisait par-dessus le snapshot servi et le poussait vers le
site dans la foulée. Le contrôle d'étanchéité arrivait bien avant la synchro —
c'est ce qui a sauvé la mise — mais le répertoire publié, lui, était déjà écrasé
au moment où le contrôle parlait. Un refus laissait donc en place non pas
« l'ancien », comme l'annonçait le message, mais le nouveau non contrôlé.

D'où trois emplacements, et non deux :

    BROUILLON  audits/public_snapshot_preview   ce qu'on vient de construire
    PUBLIE     dashboard/static/public_api      ce que l'atelier sert
    SITE       public/static/data               ce que le site public lit

« Générer un aperçu » n'écrit QUE dans le brouillon, et le module refuse de
construire ailleurs (`_verifier_cible_brouillon`) : la garantie ne repose pas
sur la bonne volonté de l'appelant. « Publier » recopie un brouillon déjà
contrôlé vers les deux autres, en recontrôlant à chaque arrivée — parce que ce
qui compte est ce qui est SERVI, jamais ce que le builder croit avoir produit.

Ce fichier ne touche pas à la base : l'auditabilité (qui a généré, qui a publié)
est écrite par `api.py`, qui a les utilisateurs. Ici, tout est chemin et
processus — c'est ce qui permet aux tests de rejouer le flux sur des répertoires
jetables.
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.build_public_snapshot import (  # noqa: E402
    DEFAULT_OUT,
    RULES,
    build_snapshot,
)

# ── Les trois emplacements ───────────────────────────────────────────────────
BROUILLON = ROOT / RULES["outputs"].get("preview_snapshot_dir",
                                        "audits/public_snapshot_preview")
PUBLIE = DEFAULT_OUT
SITE = ROOT / "public" / "static" / "data"

# L'état vit HORS des répertoires de snapshot. Il porte des chemins absolus, donc
# le nom de l'utilisateur de la machine : posé dans le snapshot, il ferait
# échouer le contrôle d'étanchéité sur sa propre règle « chaîne locale ou secret »
# — et à raison, puisqu'il partirait chez l'hébergeur.
ETAT = ROOT / "audits" / "publication_etat.json"

# Serveur d'aperçu : le site public lui-même, servi à la racine d'un port à lui,
# branché sur le brouillon. À la racine et pas sous un préfixe, parce que les
# liens du site sont absolus (`href="/deliberations"`) : le servir sous
# `/apercu/` les casserait tous et l'aperçu ne montrerait plus le site publié.
#
# 5180 et non 5175 : une machine de collecte porte souvent plusieurs instances,
# et leurs serveurs Vite occupent déjà 5173, 5174, puis la suite par
# incréments. Le port se change par `VIGIE_APERCU_PORT` — et `--strictPort`
# fait échouer bruyamment plutôt que dériver silencieusement vers un port dont
# l'atelier ignorerait le numéro.
APERCU_PORT = int(os.environ.get("VIGIE_APERCU_PORT", "5180"))
# Ce que le NAVIGATEUR doit joindre — `localhost`, pas `127.0.0.1` : Vite
# n'écoute que sur `::1` par défaut, et une URL en IPv4 littérale ne se
# connecterait à rien. Sur un atelier distant, l'exploitant déclare l'adresse
# que voit le poste qui consulte.
APERCU_URL = os.environ.get("VIGIE_APERCU_URL", f"http://localhost:{APERCU_PORT}")
APERCU_LOG = ROOT / "audits" / "apercu-site.log"

# Qui publie. Une seule liste, lue par l'API comme par les tests : le rôle est
# une règle du dispositif, pas un détail de la couche HTTP.
ROLES_QUI_PUBLIENT = frozenset({"admin"})


class PublicationRefusee(Exception):
    """Refus explicite, avec de quoi l'afficher.

    `detail` porte le rapport de contrôle quand il y en a un : un refus qui ne
    dit pas ce qui cloche finit contourné.
    """

    def __init__(self, message: str, detail: dict | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


def peut_publier(role: str | None) -> bool:
    return role in ROLES_QUI_PUBLIENT


def maintenant() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# ── Contrôle d'étanchéité ────────────────────────────────────────────────────

def controler(cible: Path) -> dict:
    """Rejoue `scripts/verify_snapshot.py` sur un répertoire produit.

    EN SOUS-PROCESSUS, jamais en import. Deux raisons, et la seconde a coûté
    une soirée le 21/08/2026 :

    1. Le contrôleur est écrit comme un adversaire du builder — il ne partage
       aucun code avec lui, c'est toute sa valeur. L'importer dans le processus
       qui vient d'appeler `build_snapshot()` les remettrait dans la même
       mémoire et les ferait vieillir ensemble.
    2. Un atelier lancé le matin exécute le code du matin. Ce jour-là, un clic
       sur « régénérer » a rejoué un builder d'avant un correctif et écrasé un
       bon snapshot par l'ancien — `{"ok": true}` en retour, 152 liens morts
       dans le fichier servi. Un interpréteur neuf lit le code du disque, pas
       celui du démarrage : c'est la seule façon que le contrôle ne mente pas
       sur le code qu'il contrôle.
    """
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_snapshot.py"),
         str(cible), "--json"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=900)
    brut = (proc.stdout or "").strip()
    try:
        rapport = json.loads(brut)
    except json.JSONDecodeError:
        # Le contrôleur n'a pas pu rendre son verdict : c'est un échec, jamais
        # un succès par défaut. Sa sortie brute part telle quelle — masquer ce
        # qu'on n'a pas su lire, c'est publier à l'aveugle.
        rapport = {
            "ok": False, "erreurs": [], "avertissements": [],
            "compte_erreurs": 0, "compte_avertissements": 0, "fichiers": 0,
            "rapport": (brut + "\n" + (proc.stderr or "")).strip()
                       or f"verify_snapshot.py n'a rien rendu (code {proc.returncode})",
        }
    if proc.returncode not in (0, 1):
        rapport["ok"] = False
        rapport["rapport"] = (rapport.get("rapport", "") + "\n"
                              + (proc.stderr or "")).strip()
    rapport["repertoire"] = str(cible)
    rapport["controle_le"] = maintenant()
    return rapport


# ── État persistant ──────────────────────────────────────────────────────────

def lire_etat() -> dict:
    try:
        return json.loads(ETAT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def ecrire_etat(etat: dict) -> None:
    ETAT.parent.mkdir(parents=True, exist_ok=True)
    ETAT.write_text(json.dumps(etat, ensure_ascii=False, indent=2), encoding="utf-8")


def _stats_du_repertoire(dossier: Path) -> dict | None:
    try:
        return json.loads((dossier / "stats.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def etape(etat: dict) -> str:
    """Le nom de l'endroit où en est le flux. Cinq valeurs, pas de sous-entendu."""
    brouillon = etat.get("brouillon") or {}
    publie = etat.get("publie") or {}
    if not brouillon.get("genere_le"):
        return "aucun_apercu"
    if not (brouillon.get("controle") or {}).get("ok"):
        return "controles_en_echec"
    if publie.get("apercu_genere_le") == brouillon.get("genere_le"):
        return "publie"
    return "pret_a_publier"


def etat_publication() -> dict:
    """L'état complet, tel que la page Publication le montre.

    Le répertoire publié est relu à chaque appel, pas seulement le journal : une
    instance qui publiait avant ce flux a un snapshot en place et aucun état.
    L'ignorer afficherait « rien de publié » devant un site en ligne.
    """
    etat = lire_etat()
    brouillon = dict(etat.get("brouillon") or {})
    publie = dict(etat.get("publie") or {})

    stats_publiees = _stats_du_repertoire(PUBLIE)
    if stats_publiees is not None:
        publie.setdefault("stats", stats_publiees)
        publie.setdefault("exclusions", stats_publiees.get("exclusions", {}))
        if not publie.get("publie_le"):
            horodatage = (PUBLIE / "stats.json").stat().st_mtime
            publie["publie_le"] = datetime.fromtimestamp(
                horodatage).astimezone().isoformat(timespec="seconds")
            publie["publie_par"] = None   # antérieur au journal de publication
    publie["existe"] = stats_publiees is not None
    publie["repertoire"] = str(PUBLIE)

    stats_brouillon = _stats_du_repertoire(BROUILLON)
    brouillon["existe"] = stats_brouillon is not None
    brouillon["repertoire"] = str(BROUILLON)
    if stats_brouillon is not None:
        brouillon.setdefault("stats", stats_brouillon)
        brouillon.setdefault("exclusions", stats_brouillon.get("exclusions", {}))

    return {
        "etape": etape({"brouillon": brouillon, "publie": publie}),
        "brouillon": brouillon,
        "publie": publie,
        "site": {"repertoire": str(SITE), "existe": (SITE / "stats.json").is_file()},
        "apercu": etat_serveur_apercu(),
        "roles_qui_publient": sorted(ROLES_QUI_PUBLIENT),
    }


# ── Aperçu ───────────────────────────────────────────────────────────────────

def _verifier_cible_brouillon(cible: Path) -> Path:
    """Le brouillon ne doit jamais désigner un répertoire servi.

    La règle est vérifiée ici plutôt que confiée à l'appelant : c'est tout
    l'intérêt du flux en deux temps, et une garantie qui dépend de la vigilance
    de qui appelle n'est pas une garantie.
    """
    cible = cible.resolve()
    for servi in (PUBLIE, SITE):
        servi = servi.resolve()
        if cible == servi or servi in cible.parents or cible in servi.parents:
            raise PublicationRefusee(
                f"L'aperçu ne peut pas être construit dans {cible} : c'est (ou "
                f"cela contient) un répertoire servi ({servi}). Un aperçu qui "
                "écrase ce qui est publié n'est pas un aperçu.")
    return cible


def generer_apercu(auteur: str | None = None, cible: Path | None = None,
                   builder=None, controleur=None) -> dict:
    """Construit le snapshot dans le brouillon et le contrôle. Rien d'autre.

    Aucune synchro, aucune copie : à la fin de cet appel, ce qui est servi est
    exactement ce qui l'était avant. Un contrôle rouge n'est pas une erreur de
    l'opération — l'aperçu a bien été produit, c'est son verdict qui est rouge,
    et c'est justement ce qu'on voulait pouvoir regarder avant de publier.
    """
    cible = _verifier_cible_brouillon(cible or BROUILLON)
    builder = builder or build_snapshot
    controleur = controleur or controler

    # RIEN d'autre que `cible` n'est écrit ici — pas même les libellés du site,
    # que la ligne de commande régénère avant de publier. Ils vivent dans
    # `public/src/lib/instance.js`, hors du brouillon : les régénérer ferait de
    # « générer un aperçu » un geste qui touche au dépôt, et la propriété que ce
    # flux existe pour tenir doit rester vraie sans exception à énoncer. Écrit
    # une première fois puis retiré le 22/08/2026, quand la suite de tests s'est
    # mise à réécrire les libellés du dépôt en tournant.
    cible.mkdir(parents=True, exist_ok=True)
    stats = builder(cible)
    controle = controleur(cible)

    resume = {
        "genere_le": maintenant(),
        "genere_par": auteur,
        "repertoire": str(cible),
        "stats": stats,
        "exclusions": (stats or {}).get("exclusions", {}),
        "controle": controle,
        "existe": True,
    }
    etat = lire_etat()
    etat["brouillon"] = resume
    ecrire_etat(etat)
    return resume


# ── Publication ──────────────────────────────────────────────────────────────

def miroir(src: Path, dest: Path) -> dict:
    """Recopie `src` dans `dest`, à l'identique — y compris les suppressions.

    Copier sans retirer, c'est le défaut du 19/08/2026 : les fiches d'entités
    écartées restaient servies parce que le builder écrivait par-dessus sans
    purger. Un miroir n'a pas d'ancien.
    """
    dest.mkdir(parents=True, exist_ok=True)
    copies, retires = [], []
    attendus = set()
    for fichier in sorted(src.rglob("*")):
        if not fichier.is_file():
            continue
        rel = fichier.relative_to(src)
        attendus.add(rel)
        arrivee = dest / rel
        arrivee.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fichier, arrivee)
        copies.append(str(rel))
    for fichier in sorted(dest.rglob("*")):
        if fichier.is_file() and fichier.relative_to(dest) not in attendus:
            fichier.unlink()
            retires.append(str(fichier.relative_to(dest)))
    return {"dest": str(dest), "count": len(copies), "files": copies,
            "fichiers_retires": retires}


def _differences(avant: dict | None, apres: dict | None) -> dict:
    """Ce qui a bougé entre l'aperçu contrôlé et la copie publiée.

    Attendu : rien. C'est bien pour ça qu'on le montre — un écart ici veut dire
    qu'une copie s'est mal passée, et c'est le seul endroit où ça se verrait.
    """
    avant, apres = avant or {}, apres or {}
    interessants = ("entities_public", "relations_public", "events_public",
                    "map_features_public", "urls_public_confirmed")
    ecarts = {}
    for cle in interessants:
        if avant.get(cle) != apres.get(cle):
            ecarts[cle] = {"apercu": avant.get(cle), "publie": apres.get(cle)}
    return ecarts


def publier(auteur: str | None = None, role: str | None = None,
            source: Path | None = None, controleur=None) -> dict:
    """Porte un aperçu DÉJÀ contrôlé vers les deux emplacements servis.

    Le contrôle est rejoué trois fois — sur le brouillon avant de bouger, puis
    à chaque arrivée. Ce n'est pas de la superstition : la synchro vers le site
    met `entite/` en miroir et recopie le reste, et un fichier oublié ne se voit
    pas dans le répertoire d'origine, seulement à l'arrivée.
    """
    if not peut_publier(role):
        raise PublicationRefusee(
            "Publier est réservé au rôle admin. L'état de publication et "
            "l'aperçu restent consultables.")

    source = (source or BROUILLON).resolve()
    controleur = controleur or controler
    etat = lire_etat()
    brouillon = etat.get("brouillon") or {}
    if not (source / "stats.json").is_file():
        raise PublicationRefusee(
            "Aucun aperçu à publier — générer un aperçu d'abord.")

    # 1. Le brouillon, à l'instant de publier. Un contrôle vert d'il y a une
    #    heure ne dit rien du répertoire d'aujourd'hui.
    controle_apercu = controleur(source)
    if not controle_apercu.get("ok"):
        raise PublicationRefusee(
            "Aperçu refusé par le contrôle d'étanchéité — rien n'a été publié, "
            "le site public est inchangé.", {"controle": controle_apercu})

    # 2. Vers ce que l'atelier sert.
    copie = miroir(source, PUBLIE)
    controle_publie = controleur(PUBLIE)
    if not controle_publie.get("ok"):
        raise PublicationRefusee(
            "La copie vers le répertoire publié ne passe pas le contrôle alors "
            "que l'aperçu passait — NE PAS DÉPLOYER, et regarder la copie.",
            {"controle": controle_publie})

    # 3. Vers ce que le site public lit.
    #
    # Un miroir plein, et non `synchroniser_site_public` : celle-ci recopie les
    # fichiers qu'elle connaît (racine, README, layers, entite) et ne met en
    # miroir que `entite/`. Un fichier de racine devenu inutile entre deux
    # versions du moteur y resterait servi indéfiniment. La fonction historique
    # ne bouge pas — `deploy/publier-site.sh` et l'ancien endpoint s'en servent —
    # mais ce flux-ci, qui existe pour ne rien laisser passer, ne s'en contente pas.
    synchro = miroir(PUBLIE, SITE)
    controle_site = controleur(SITE)
    if not controle_site.get("ok"):
        raise PublicationRefusee(
            "Le snapshot est propre mais sa copie vers le site ne l'est pas — "
            "NE PAS DÉPLOYER.", {"controle": controle_site})

    publie = {
        "publie_le": maintenant(),
        "publie_par": auteur,
        "repertoire": str(PUBLIE),
        "apercu_genere_le": brouillon.get("genere_le"),
        "apercu_genere_par": brouillon.get("genere_par"),
        "stats": _stats_du_repertoire(PUBLIE),
        "exclusions": (_stats_du_repertoire(PUBLIE) or {}).get("exclusions", {}),
        "copie": copie,
        "synchro": synchro,
        "controle": controle_publie,
        "controle_site": controle_site,
        "differences": _differences(brouillon.get("stats"),
                                    _stats_du_repertoire(PUBLIE)),
        "existe": True,
    }
    etat["publie"] = publie
    ecrire_etat(etat)
    return publie


# ── Serveur d'aperçu : le site public branché sur le brouillon ───────────────
# Un seul processus à la fois, gardé ici parce que c'est l'API qui le démarre et
# qui doit pouvoir l'arrêter. Il sert le VRAI site — mêmes composants, même
# feuille de style, mêmes gabarits — avec les données du brouillon : c'est la
# seule façon qu'un aperçu ressemble à ce qui sera publié.
_serveur = None


def _vite() -> Path:
    return ROOT / "public" / "node_modules" / ".bin" / "vite"


def etat_serveur_apercu() -> dict:
    actif = _serveur is not None and _serveur.poll() is None
    return {
        "actif": actif,
        "url": APERCU_URL if actif else None,
        "port": APERCU_PORT,
        "installe": _vite().exists(),
        "journal": str(APERCU_LOG) if actif else None,
    }


def demarrer_serveur_apercu(cible: Path | None = None) -> dict:
    """Lance le site public sur le brouillon, sur son propre port.

    `VIGIE_DATA_DIR` est le seul réglage : le site le lit pour ses pages
    prérendues comme pour ses appels `/data/`. Aucun fichier n'est déplacé —
    l'aperçu ne touche à rien, il regarde ailleurs.
    """
    global _serveur
    cible = _verifier_cible_brouillon(cible or BROUILLON)
    if not (cible / "stats.json").is_file():
        raise PublicationRefusee("Aucun aperçu à montrer — générer un aperçu d'abord.")
    if _serveur is not None and _serveur.poll() is None:
        return etat_serveur_apercu()
    if not _vite().exists():
        raise PublicationRefusee(
            "Le site public n'a pas ses dépendances : `cd public && npm install`. "
            "L'aperçu affiche le site lui-même, il lui faut de quoi tourner.")
    if _port_repond():
        # Quelqu'un écoute déjà, et ce n'est pas nous : une instance voisine, ou
        # l'aperçu d'une API précédente resté orphelin. Le dire vaut mieux que
        # lancer un Vite qui sortira sur « port already in use » — et bien mieux
        # que d'afficher dans l'atelier un aperçu qui montrerait le site d'à côté.
        raise PublicationRefusee(
            f"Le port {APERCU_PORT} est déjà occupé par un autre service. "
            "Choisir un autre port (VIGIE_APERCU_PORT), ou arrêter celui qui "
            "l'occupe — une machine qui porte plusieurs instances les empile "
            "à partir de 5173.")

    APERCU_LOG.parent.mkdir(parents=True, exist_ok=True)
    journal = APERCU_LOG.open("w", encoding="utf-8")
    _serveur = subprocess.Popen(
        [str(_vite()), "dev", "--port", str(APERCU_PORT), "--strictPort"],
        cwd=str(ROOT / "public"),
        env={**os.environ, "VIGIE_DATA_DIR": str(cible)},
        stdout=journal, stderr=subprocess.STDOUT,
    )

    # On ne rend pas la main sur un « c'est parti » : un port déjà pris fait
    # sortir Vite en une seconde, et l'atelier afficherait une prévisualisation
    # en marche devant un cadre vide. Ce qui compte est que le port RÉPONDE.
    if not _attendre_le_port():
        journal_lu = _fin_du_journal()
        arreter_serveur_apercu()
        raise PublicationRefusee(
            f"L'aperçu n'a pas démarré sur le port {APERCU_PORT} "
            f"(réglable par VIGIE_APERCU_PORT).\n\n{journal_lu}")
    return etat_serveur_apercu()


def _port_repond() -> bool:
    for hote in ("127.0.0.1", "::1"):
        try:
            with socket.create_connection((hote, APERCU_PORT), timeout=0.3):
                return True
        except OSError:
            pass
    return False


def _attendre_le_port(delai: float = 25.0) -> bool:
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if _serveur is None or _serveur.poll() is not None:
            return False
        if _port_repond():
            return True
        time.sleep(0.25)
    return False


def _fin_du_journal(lignes: int = 20) -> str:
    try:
        return "\n".join(APERCU_LOG.read_text(encoding="utf-8").splitlines()[-lignes:])
    except OSError:
        return "(journal illisible)"


def arreter_serveur_apercu() -> dict:
    global _serveur
    if _serveur is not None and _serveur.poll() is None:
        _serveur.terminate()
        try:
            _serveur.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _serveur.kill()
    _serveur = None
    return etat_serveur_apercu()


# Un aperçu qui survit à l'API qui l'a lancé occupe son port sans que rien ne
# sache l'arrêter — et la fois suivante, le démarrage échoue sans raison
# visible.
atexit.register(arreter_serveur_apercu)
