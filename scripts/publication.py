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
import fcntl
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
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

# Un seul flux de publication à la fois. Rien n'empêchait jusqu'ici deux
# générations concurrentes d'écrire dans le même brouillon, ni une publication
# de partir pendant qu'une autre recopiait : l'atelier est une API HTTP, deux
# clics valent deux requêtes. Le verrou est un fichier, pris en exclusif pour
# la durée de l'opération et relâché même si elle échoue — un verrou qui
# survivrait à un plantage bloquerait l'instance jusqu'au prochain redémarrage.
VERROU = ROOT / "audits" / "publication.lock"

# Combien de versions servies on garde en arrière. Une seule suffit à revenir
# en arrière ; en garder davantage occuperait le disque de l'atelier sans que
# personne n'y revienne jamais.
VERSIONS_GARDEES = 1

# Écrit dans chaque répertoire mis en service, et emporté par le déploiement.
# C'est la pièce qui distingue « publié » de « en ligne » : sans elle, l'atelier
# ne peut qu'affirmer avoir publié, jamais constater que c'est arrivé.
VERSION_SERVIE = "version.json"

# Combien de temps on attend la réponse du site public. Court : cette
# vérification est un confort d'atelier, pas une raison de bloquer une page.
DELAI_VERIFICATION = 8

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

# Où le build d'aperçu est écrit. Hors du dépôt servi, et distinct de `build/` :
# construire un aperçu ne doit pas écraser le build de production, qui peut être
# celui qui vient d'être déployé.
APERCU_BUILD = ROOT / "audits" / "apercu_build"

# Mise en ligne : le build de production et son téléversement chez l'hébergeur.
# Journal séparé de celui de l'aperçu — on veut pouvoir relire le déploiement
# d'hier sans qu'un aperçu construit depuis l'ait écrasé.
DEPLOIEMENT_LOG = ROOT / "audits" / "mise-en-ligne.log"
DEPLOIEMENT_ETAT = ROOT / "audits" / "mise-en-ligne.json"

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


# Les cinq étapes, dans l'ordre. Le mot « publié » recouvrait les deux
# dernières : la page annonçait « Ce qui est publié », puis expliquait plus bas
# que le build et la mise en ligne restaient à faire. Un exploitant qui lit
# « publié » et ferme l'onglet croit son site à jour ; il ne l'est pas.
ETAPES = ("aucun_apercu", "controles_en_echec", "pret_a_publier",
          "promu_localement", "en_ligne")

LIBELLES_ETAPES = {
    "aucun_apercu": "Aucun aperçu — les données brouillon n'ont pas été construites",
    "controles_en_echec": "Aperçu construit, mais refusé par le contrôle",
    "pret_a_publier": "Aperçu construit et contrôlé — rien n'est encore servi",
    "promu_localement": "Promu localement — reste à déployer sur le site public",
    "en_ligne": "Déployé et vérifié en ligne",
}


def etape(etat: dict) -> str:
    """Le nom de l'endroit où en est le flux. Cinq valeurs, pas de sous-entendu."""
    brouillon = etat.get("brouillon") or {}
    publie = etat.get("publie") or {}
    if not brouillon.get("genere_le"):
        return "aucun_apercu"
    if not (brouillon.get("controle") or {}).get("ok"):
        return "controles_en_echec"
    if publie.get("apercu_genere_le") != brouillon.get("genere_le"):
        return "pret_a_publier"
    # Promu ≠ en ligne. Le passage au dernier état demande une CONSTATATION :
    # le site public interrogé sert bien l'empreinte qui vient d'être promue.
    verif = etat.get("en_ligne") or {}
    if verif.get("ok") and verif.get("empreinte") == publie.get("empreinte"):
        return "en_ligne"
    return "promu_localement"


def site_url() -> str | None:
    """L'adresse publique déclarée par l'instance, ou rien.

    Rien est une réponse acceptable : une instance de test n'a pas de site en
    ligne, et l'atelier doit le dire plutôt que d'inventer une URL.
    """
    chemin = Path(os.environ.get("VIGIE_INSTANCE") or ROOT / "config" / "instance.json")
    if not chemin.is_file():
        return None
    try:
        return (json.loads(chemin.read_text(encoding="utf-8"))
                .get("site_url") or None)
    except (json.JSONDecodeError, OSError):
        return None


def verifier_en_ligne(url: str | None = None) -> dict:
    """Constate ce que le site public sert VRAIMENT, et le journalise.

    Le seul état que l'atelier ne peut pas déduire de ses propres écritures :
    entre la promotion locale et la mise en ligne, il y a un build et un
    déploiement que l'atelier ne fait pas. Tant que personne n'a interrogé le
    site, « déployé » reste une supposition.
    """
    import urllib.error
    import urllib.request

    url = (url or site_url() or "").rstrip("/")
    etat = lire_etat()
    attendue = (etat.get("publie") or {}).get("empreinte")
    verdict = {"verifie_le": maintenant(), "url": url or None,
               "empreinte_attendue": attendue}

    if not url:
        verdict.update(ok=False, motif="Aucune adresse publique déclarée "
                                       "(`site_url` dans config/instance.json).")
    else:
        cible = f"{url}/data/{VERSION_SERVIE}"
        verdict["url_interrogee"] = cible
        try:
            with urllib.request.urlopen(cible, timeout=DELAI_VERIFICATION) as r:
                verdict["http"] = r.status
                servie = json.loads(r.read().decode("utf-8")).get("empreinte")
            verdict["empreinte"] = servie
            if not attendue:
                verdict.update(ok=False, motif="Rien n'a encore été promu "
                                               "localement : rien à comparer.")
            elif servie == attendue:
                verdict.update(ok=True, motif="Le site en ligne sert bien la "
                                              "version promue.")
            else:
                verdict.update(ok=False, motif=(
                    "Le site en ligne sert une AUTRE version que celle promue "
                    "localement — le déploiement n'a pas eu lieu, ou il a "
                    "échoué."))
        except urllib.error.HTTPError as e:
            verdict.update(ok=False, http=e.code, motif=(
                f"Le site répond {e.code} sur {VERSION_SERVIE}. Si le site est "
                "en ligne, c'est qu'il sert un déploiement antérieur à ce "
                "flux — republier le mettra à niveau."))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
            verdict.update(ok=False, motif=f"Site injoignable ou illisible : {e}")

    etat["en_ligne"] = verdict
    ecrire_etat(etat)
    return verdict


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

    en_ligne = dict(etat.get("en_ligne") or {})
    # Une vérification faite AVANT la promotion en cours ne dit rien de ce qui
    # est servi maintenant : elle est montrée comme périmée, jamais comme verte.
    if en_ligne and en_ligne.get("empreinte_attendue") != publie.get("empreinte"):
        en_ligne["perimee"] = True
        en_ligne["ok"] = False

    etape_courante = etape({"brouillon": brouillon, "publie": publie,
                            "en_ligne": etat.get("en_ligne") or {}})
    return {
        "etape": etape_courante,
        "etape_libelle": LIBELLES_ETAPES.get(etape_courante, etape_courante),
        "etapes": list(ETAPES),
        "brouillon": brouillon,
        "publie": publie,
        "site": {"repertoire": str(SITE), "existe": (SITE / "stats.json").is_file(),
                 "url": site_url()},
        "en_ligne": en_ligne,
        "mise_en_ligne": etat_mise_en_ligne(),
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
    # Sous le même verrou que la publication : générer pendant qu'on publie
    # ferait lire au contrôleur un brouillon en train d'être réécrit.
    with verrou_de_publication():
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

@contextmanager
def verrou_de_publication(delai: float = 30.0):
    """Sérialise génération et publication, entre processus.

    `flock` et non un fichier-témoin : le verrou d'un processus tué est relâché
    par le noyau, alors qu'un témoin sur disque survit au plantage et immobilise
    l'instance jusqu'à ce que quelqu'un le supprime à la main.
    """
    VERROU.parent.mkdir(parents=True, exist_ok=True)
    fin = time.monotonic() + delai
    with open(VERROU, "w") as f:
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= fin:
                    raise PublicationRefusee(
                        "Une autre génération ou publication est en cours sur "
                        "cette instance. Rien n'a été touché — réessayer quand "
                        "elle sera finie.")
                time.sleep(0.2)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def empreinte(dossier: Path) -> str:
    """Ce que contient un répertoire, en une chaîne comparable.

    Chemins ET contenus : deux versions qui ne diffèrent que par un fichier
    supprimé doivent avoir deux empreintes. Sert à dire QUELLE version est
    servie, et à vérifier après coup que c'est bien celle-là qui est en ligne.
    """
    h = hashlib.sha256()
    for fichier in sorted(dossier.rglob("*")):
        if not fichier.is_file() or fichier.name == VERSION_SERVIE:
            continue
        h.update(str(fichier.relative_to(dossier)).encode("utf-8"))
        h.update(b"\0")
        h.update(hashlib.sha256(fichier.read_bytes()).digest())
    return h.hexdigest()[:16]


def _vider(dossier: Path) -> None:
    if dossier.is_dir():
        shutil.rmtree(dossier)
    elif dossier.exists():
        dossier.unlink()


def basculer(src: Path, dest: Path, controleur) -> dict:
    """Construit la version à côté, la contrôle, PUIS la met en service.

    Le défaut que ça corrige : `miroir()` remplaçait les fichiers servis un par
    un, et le contrôle venait après. Un contrôle rouge trouvait donc l'ancien
    snapshot déjà à moitié écrasé — sans rien pour revenir en arrière, et sans
    que le message « le site public est inchangé » soit encore vrai. Un visiteur
    tombant au milieu de la copie voyait, lui, un site mi-ancien mi-neuf.

    Ici, `dest` n'est touché qu'une fois la version neuve complète et contrôlée,
    et le changement se fait par deux renommages de répertoire — l'ancien
    s'efface au profit de `.precedent`, le neuf prend sa place. Un renommage est
    atomique pour le système de fichiers ; il reste une fenêtre de l'ordre de la
    microseconde entre les deux où `dest` n'existe pas, contre plusieurs
    secondes de contenu incohérent auparavant.

    Ce qui est servi reste donc toujours une version entière : soit l'ancienne,
    soit la nouvelle, jamais un mélange des deux.
    """
    dest = Path(dest)
    neuf = dest.parent / f".{dest.name}.neuf"
    precedent = dest.parent / f".{dest.name}.precedent"

    _vider(neuf)
    neuf.mkdir(parents=True)
    copie = miroir(src, neuf)

    # Le contrôle porte sur le répertoire NEUF, avant qu'il ne serve. Un refus
    # ici ne coûte qu'un répertoire temporaire.
    controle = controleur(neuf)
    if not controle.get("ok"):
        _vider(neuf)
        return {"ok": False, "controle": controle, "dest": str(dest)}

    marque = empreinte(neuf)
    # Le seul moyen de savoir, plus tard, ce que le site EN LIGNE sert
    # réellement : un fichier que le déploiement emporte avec les données et
    # qu'une requête HTTP peut relire. Sans lui, « publié » et « en ligne » se
    # confondent, et c'est exactement ce que la page Publication laissait croire.
    (neuf / VERSION_SERVIE).write_text(json.dumps({
        "empreinte": marque, "mise_en_service_le": maintenant(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    _vider(precedent)
    if dest.exists():
        dest.rename(precedent)
    try:
        neuf.rename(dest)
    except OSError:
        # Le renommage a échoué alors que l'ancien est déjà écarté : le remettre
        # en service vaut mieux que laisser l'emplacement vide.
        if precedent.exists() and not dest.exists():
            precedent.rename(dest)
        raise
    return {"ok": True, "controle": controle, "empreinte": marque,
            "precedent": str(precedent) if precedent.exists() else None,
            **copie, "dest": str(dest)}


def revenir_a_la_version_precedente(dest: Path) -> dict:
    """Remet en service la version d'avant, si elle est encore là.

    Existe parce qu'un contrôle vert ne garantit pas qu'une version soit BONNE :
    il garantit qu'elle est étanche. Un chiffre faux, un découpage raté, une
    page vide passent le contrôle. Quelqu'un doit pouvoir revenir en arrière
    sans reconstruire.
    """
    dest = Path(dest)
    precedent = dest.parent / f".{dest.name}.precedent"
    if not precedent.is_dir():
        raise PublicationRefusee(
            f"Aucune version précédente conservée pour {dest.name} — "
            "rien à remettre en service.")
    courant = dest.parent / f".{dest.name}.repris"
    _vider(courant)
    if dest.exists():
        dest.rename(courant)
    precedent.rename(dest)
    # L'ancienne courante devient la précédente : revenir deux fois de suite
    # doit ramener là d'où l'on vient, pas creuser.
    if courant.exists():
        courant.rename(precedent)
    return {"dest": str(dest), "empreinte": empreinte(dest)}


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
    sur chaque copie AVANT qu'elle ne serve. Ce n'est pas de la superstition :
    la copie vers le site met `entite/` en miroir et recopie le reste, et un
    fichier oublié ne se voit pas dans le répertoire d'origine, seulement à
    l'arrivée.

    Le troisième contrôle portait, jusqu'au 23/08/2026, sur un répertoire DÉJÀ
    en service : le trouver rouge signifiait que le site public servait
    l'anomalie depuis la première seconde de la copie. Chaque emplacement est
    maintenant construit à côté, contrôlé, puis mis en service par un renommage
    — cf. `basculer`.

    Toute l'opération tient sous un verrou : deux clics valent deux requêtes, et
    rien n'empêchait deux publications de se recouvrir.
    """
    if not peut_publier(role):
        raise PublicationRefusee(
            "Publier est réservé au rôle admin. L'état de publication et "
            "l'aperçu restent consultables.")

    with verrou_de_publication():
        return _publier_sous_verrou(auteur, source, controleur)


def _publier_sous_verrou(auteur, source, controleur) -> dict:
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

    # 2. Vers ce que l'atelier sert — construit à côté, contrôlé, puis mis en
    #    service d'un seul geste. Un refus laisse l'ancienne version entière et
    #    servie, ce que le message de refus promettait déjà sans le tenir.
    copie = basculer(source, PUBLIE, controleur)
    controle_publie = copie["controle"]
    if not copie["ok"]:
        raise PublicationRefusee(
            "La copie vers le répertoire publié ne passe pas le contrôle alors "
            "que l'aperçu passait — rien n'a été mis en service, la version "
            "précédente reste servie. Regarder la copie.",
            {"controle": controle_publie})

    # 3. Vers ce que le site public lit.
    #
    # Un miroir plein, et non `synchroniser_site_public` : celle-ci recopie les
    # fichiers qu'elle connaît (racine, README, layers, entite) et ne met en
    # miroir que `entite/`. Un fichier de racine devenu inutile entre deux
    # versions du moteur y resterait servi indéfiniment. La fonction historique
    # ne bouge pas — `deploy/publier-site.sh` et l'ancien endpoint s'en servent —
    # mais ce flux-ci, qui existe pour ne rien laisser passer, ne s'en contente pas.
    synchro = basculer(PUBLIE, SITE, controleur)
    controle_site = synchro["controle"]
    if not synchro["ok"]:
        # Le premier emplacement est déjà en service et il est propre : le
        # laisser tel quel plutôt que de revenir en arrière sur les deux. Ce
        # qu'il faut empêcher, c'est le déploiement — pas l'atelier.
        raise PublicationRefusee(
            "Le snapshot est propre mais sa copie vers le site ne l'est pas — "
            "NE PAS DÉPLOYER. Le site conserve sa version précédente.",
            {"controle": controle_site})

    publie = {
        "publie_le": maintenant(),
        "publie_par": auteur,
        "repertoire": str(PUBLIE),
        "apercu_genere_le": brouillon.get("genere_le"),
        "apercu_genere_par": brouillon.get("genere_par"),
        "stats": _stats_du_repertoire(PUBLIE),
        "exclusions": (_stats_du_repertoire(PUBLIE) or {}).get("exclusions", {}),
        # L'empreinte de ce qui vient d'être mis en service. « Publié » et « en
        # ligne » sont deux états distincts : c'est par cette empreinte qu'on
        # pourra dire, plus tard, si le site déployé sert bien cette version-là.
        "empreinte": copie.get("empreinte"),
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


# ── Mise en ligne ────────────────────────────────────────────────────────────
# Le dernier geste, et le seul qui sorte de la machine. Il est tenu à part de la
# promotion parce qu'il n'a ni les mêmes effets ni la même réversibilité :
# promouvoir écrit dans deux répertoires locaux, mettre en ligne change ce que
# le public voit.
_deploiement = None


def projet_hebergeur() -> str | None:
    """Le nom du projet chez l'hébergeur, déclaré par l'instance.

    `CF_PROJECT` en variable d'environnement reste prioritaire : c'est ce que
    `deploy/publier-site.sh` utilise, et deux façons de nommer la même chose
    qui divergeraient enverraient le site au mauvais endroit.
    """
    if os.environ.get("CF_PROJECT"):
        return os.environ["CF_PROJECT"]
    chemin = Path(os.environ.get("VIGIE_INSTANCE") or ROOT / "config" / "instance.json")
    if not chemin.is_file():
        return None
    try:
        return (json.loads(chemin.read_text(encoding="utf-8"))
                .get("cf_project") or None)
    except (json.JSONDecodeError, OSError):
        return None


def etat_mise_en_ligne() -> dict:
    """Où en est le déploiement — en cours, fini, ou jamais lancé."""
    actif = _deploiement is not None and _deploiement.poll() is None
    fini = _deploiement is not None and _deploiement.poll() is not None
    etat = {
        "actif": actif,
        "projet": projet_hebergeur(),
        "journal": str(DEPLOIEMENT_LOG) if DEPLOIEMENT_LOG.is_file() else None,
    }
    if DEPLOIEMENT_ETAT.is_file():
        try:
            etat |= json.loads(DEPLOIEMENT_ETAT.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    if fini:
        etat["code_retour"] = _deploiement.returncode
        etat["ok"] = _deploiement.returncode == 0
        etat["fin_du_journal"] = _fin_du_journal(25, DEPLOIEMENT_LOG)
    etat["actif"] = actif      # `|=` a pu l'écraser avec une valeur périmée
    return etat


def mettre_en_ligne(auteur: str | None = None, role: str | None = None) -> dict:
    """Construit le site depuis la version PROMUE, et le téléverse.

    Ne rejoue pas `deploy/publier-site.sh` en entier, et c'est délibéré : ce
    script commence par reconstruire le snapshot depuis la base. Or ce qui a été
    promu a été contrôlé ; le reconstruire déploierait une version que personne
    n'a validée, différente dès qu'un collecteur a tourné entre-temps. On repart
    donc de `public/static/data` tel qu'il est servi — étapes 3 et 4 du script,
    pas 1 à 4.
    """
    if not peut_publier(role):
        raise PublicationRefusee(
            "Mettre en ligne est réservé au rôle admin.")

    global _deploiement
    if _deploiement is not None and _deploiement.poll() is None:
        return etat_mise_en_ligne()

    etat = lire_etat()
    empreinte_promue = (etat.get("publie") or {}).get("empreinte")
    if not empreinte_promue:
        raise PublicationRefusee(
            "Rien n'a été promu localement — publier d'abord. Mettre en ligne "
            "ne construit pas de snapshot, il déploie celui qui a été contrôlé.")
    if not (SITE / "stats.json").is_file():
        raise PublicationRefusee(
            f"{SITE} est vide : le site n'a rien à construire.")

    projet = projet_hebergeur()
    if not projet:
        raise PublicationRefusee(
            "Aucun projet d'hébergement déclaré. Ajouter `cf_project` à "
            "config/instance.json, ou exporter CF_PROJECT avant de démarrer "
            "l'API. Sans lui, le déploiement irait au hasard.")
    if not (ROOT / "public" / "node_modules").is_dir():
        raise PublicationRefusee(
            "Le site public n'a pas ses dépendances : `cd public && npm ci`.")

    DEPLOIEMENT_LOG.parent.mkdir(parents=True, exist_ok=True)
    DEPLOIEMENT_ETAT.write_text(json.dumps({
        "demarre_le": maintenant(), "demarre_par": auteur,
        "projet": projet, "empreinte_visee": empreinte_promue,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    journal = DEPLOIEMENT_LOG.open("w", encoding="utf-8")
    journal.write(f"$ mise en ligne de {SITE} vers « {projet} »\n"
                  f"  empreinte promue : {empreinte_promue}\n\n")
    journal.flush()
    # `--branch=main` force l'environnement Production : sans lui, wrangler lit
    # la branche git courante et déploie en Preview — la production reste alors
    # inchangée, sans que rien n'échoue.
    _deploiement = subprocess.Popen(
        ["bash", "-c",
         "npm run build && "
         f"npx wrangler pages deploy build --project-name={projet} "
         "--branch=main --commit-dirty=true"],
        cwd=str(ROOT / "public"),
        stdout=journal, stderr=subprocess.STDOUT,
    )
    return etat_mise_en_ligne()


# ── Serveur d'aperçu : le site public branché sur le brouillon ───────────────
# Un seul processus à la fois, gardé ici parce que c'est l'API qui le démarre et
# qui doit pouvoir l'arrêter. Il sert le VRAI site — mêmes composants, même
# feuille de style, mêmes gabarits — avec les données du brouillon : c'est la
# seule façon qu'un aperçu ressemble à ce qui sera publié.
_serveur = None


def _vite() -> Path:
    return ROOT / "public" / "node_modules" / ".bin" / "vite"


def _npm() -> str:
    return shutil.which("npm") or "npm"


def construire_apercu(cible: Path | None = None) -> dict:
    """Construit le site public sur le brouillon, tel qu'il sera publié.

    L'aperçu montrait `vite dev` : rendu à la volée, modules non groupés, aucun
    prérendu. Ce qui part en ligne est un build statique de 1 449 pages écrites
    par `adapter-static`, et c'est là que se logent les défauts qui restent —
    une page qui rend bien en dev et se retrouve vide dans le HTML livré, un
    lien qui ne résout plus une fois les routes figées. Un aperçu qui ne montre
    pas l'artefact publiable ne préserve de rien.

    `npm run build` et non `vite build` seul : le script du paquet enchaîne sur
    `verifier_build.mjs`, qui refuse un build dont les pages sont vides. Cette
    vérification doit porter sur l'aperçu aussi, sans quoi elle n'arriverait
    qu'après la publication.

    Deux réglages, déjà prévus par le site : `VIGIE_DATA_DIR` lui dit où lire
    les données, `VIGIE_BUILD_DIR` où écrire. Rien n'est déplacé.
    """
    cible = _verifier_cible_brouillon(cible or BROUILLON)
    if not (cible / "stats.json").is_file():
        raise PublicationRefusee(
            "Aucun aperçu à construire — générer un aperçu d'abord.")
    if not _vite().exists():
        raise PublicationRefusee(
            "Le site public n'a pas ses dépendances : `cd public && npm install`. "
            "L'aperçu construit le site lui-même, il lui faut de quoi tourner.")

    APERCU_LOG.parent.mkdir(parents=True, exist_ok=True)
    with APERCU_LOG.open("w", encoding="utf-8") as journal:
        journal.write(f"$ npm run build  (VIGIE_DATA_DIR={cible})\n\n")
        journal.flush()
        issue = subprocess.run(
            [_npm(), "run", "build"],
            cwd=str(ROOT / "public"),
            env={**os.environ,
                 "VIGIE_DATA_DIR": str(cible),
                 "VIGIE_BUILD_DIR": str(APERCU_BUILD)},
            stdout=journal, stderr=subprocess.STDOUT,
        )
    if issue.returncode != 0:
        raise PublicationRefusee(
            "Le build de l'aperçu a échoué — c'est un défaut de l'artefact "
            "publiable, pas de l'atelier. Il n'y a rien à montrer tant qu'il "
            "n'est pas corrigé.", {"journal": _fin_du_journal(40)})
    if not (APERCU_BUILD / "index.html").is_file():
        raise PublicationRefusee(
            "Le build s'est terminé sans écrire de page d'accueil.",
            {"journal": _fin_du_journal(40)})

    pages = sum(1 for _ in APERCU_BUILD.rglob("*.html"))
    return {"repertoire": str(APERCU_BUILD), "pages": pages,
            "construit_le": maintenant(), "donnees": str(cible)}


def etat_serveur_apercu() -> dict:
    actif = _serveur is not None and _serveur.poll() is None
    index = APERCU_BUILD / "index.html"
    return {
        "actif": actif,
        "url": APERCU_URL if actif else None,
        "port": APERCU_PORT,
        "installe": _vite().exists(),
        "journal": str(APERCU_LOG) if actif else None,
        # Ce qui est servi est un BUILD, pas un serveur de développement : la
        # page le dit, et donne sa date — un aperçu vieux d'une heure ne montre
        # pas les corrections de la dernière demi-heure.
        "build": {
            "repertoire": str(APERCU_BUILD),
            "existe": index.is_file(),
            "construit_le": (datetime.fromtimestamp(index.stat().st_mtime)
                             .astimezone().isoformat(timespec="seconds")
                             if index.is_file() else None),
            "pages": sum(1 for _ in APERCU_BUILD.rglob("*.html"))
                     if index.is_file() else 0,
        },
    }


def demarrer_serveur_apercu(cible: Path | None = None,
                            reconstruire: bool = True) -> dict:
    """Construit l'artefact publiable, puis le sert — sur son propre port.

    Deux gestes, pas un : `npm run build` écrit les 1 449 pages telles qu'elles
    partiront en ligne et les fait passer par `verifier_build.mjs` ; le serveur
    ne fait ensuite que les servir, avec les règles de résolution d'URL d'un
    hébergeur statique (`scripts/servir_apercu.py`).

    Avant le 23/08/2026 l'aperçu lançait `vite dev` : il montrait le serveur de
    développement, jamais l'artefact. Or c'est là que se logent les défauts qui
    restent — une page qui rend bien en dev et se retrouve vide dans le HTML
    livré. On prévisualisait la seule version du site qui ne sera jamais
    publiée.

    Le prix est un build à chaque ouverture, une poignée de secondes. Le
    contrepoids est qu'on regarde enfin ce qu'on s'apprête à mettre en ligne.
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
            "L'aperçu construit le site lui-même, il lui faut de quoi tourner.")
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

    # Le build vient APRÈS les refus : construire 1 449 pages pour découvrir
    # ensuite que le port est pris ferait attendre une minute pour rien.
    if reconstruire or not (APERCU_BUILD / "index.html").is_file():
        construire_apercu(cible)

    # Le journal est ouvert en AJOUT : il porte déjà la sortie du build, et
    # c'est elle qu'on veut relire quand l'aperçu ne montre pas ce qu'on attend.
    APERCU_LOG.parent.mkdir(parents=True, exist_ok=True)
    journal = APERCU_LOG.open("a", encoding="utf-8")
    _serveur = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "servir_apercu.py"),
         str(APERCU_BUILD), "--port", str(APERCU_PORT)],
        cwd=str(ROOT),
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


def _fin_du_journal(lignes: int = 20, fichier: Path | None = None) -> str:
    try:
        texte = (fichier or APERCU_LOG).read_text(encoding="utf-8")
        return "\n".join(texte.splitlines()[-lignes:])
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
