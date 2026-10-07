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

APERÇUS PAR COMPTE (17/09/2026, arbitré par Julien). Dans l'atelier, chaque
compte — quel que soit son rôle — génère SON aperçu, daté, dans
`audits/apercus/<compte>/` : les données contrôlées et le site construit dessus.
Il est écrasé par le prochain aperçu du même compte et effacé au bout de
`VIGIE_APERCU_JOURS` jours. Publier reste réservé à l'admin, et part de SON
aperçu, qui doit passer les contrôles. Le brouillon unique ci-dessus reste le
chemin de la ligne de commande (`deploy/publier-site.sh`, passe quotidienne).

Ce fichier n'ouvre pas la base : l'auditabilité (qui a généré, qui a publié)
est écrite par `api.py`, qui a les utilisateurs. Seule exception, en lecture :
`corrections_depuis_la_publication` reçoit la connexion de son appelant. Ici,
tout est chemin et processus — c'est ce qui permet aux tests de rejouer le flux sur des répertoires
jetables.
"""
from __future__ import annotations

import argparse
import atexit
import errno
import getpass
import hashlib
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from collectors import verrou as verrou_fichier  # noqa: E402
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

# Les aperçus de l'atelier, un répertoire par compte, et leur durée de vie.
APERCUS = ROOT / "audits" / "apercus"
APERCU_JOURS = int(os.environ.get("VIGIE_APERCU_JOURS") or 7)   # vide dans .env = défaut
# Le build du site public écrit dans `public/.svelte-kit/`, commun à TOUS les
# builds — ceux des aperçus comme celui de la mise en ligne. Jusqu'au 04/10/2026
# seuls les aperçus prenaient ce verrou : la mise en ligne (`publier-site.sh`)
# vidait `.svelte-kit/output` sous un aperçu en construction. Le nom du fichier
# date de ce temps-là ; il reste, pour qu'un moteur d'avant et un moteur d'après
# qui se croisent pendant une mise à jour se disputent le même verrou.
VERROU_BUILD = ROOT / "audits" / "apercu-build.lock"
# Ce que la mise en ligne accepte d'attendre : un aperçu de 1 500 pages se
# construit en quelques minutes. Au-delà, c'est une panne, et elle le dit.
ATTENTE_MISE_EN_LIGNE = 1800.0

# Combien de versions servies on garde en arrière. Une seule suffit à revenir
# en arrière ; en garder davantage occuperait le disque de l'atelier sans que
# personne n'y revienne jamais.
VERSIONS_GARDEES = 1

# Où vivent la version en construction (`.neuf`) et la version d'avant
# (`.precedent`) de chaque emplacement servi : HORS de tout répertoire qu'un
# build recopie. Elles vivaient à côté du répertoire servi, et pour le site
# c'était `public/static/` — que SvelteKit recopie en entier dans `build/`.
# Le 16/09/2026, lasalle.vigie-civique.fr servait ainsi `/.data.precedent/` :
# le snapshot du 23/08 au complet, contrôlé selon les règles du 23/08, trois
# semaines après que ces règles avaient été resserrées.
VERSIONS = ROOT / "audits" / "versions"

# Mais `VERSIONS` n'est pas dans le montage des destinations. Sous systemd
# (`ProtectSystem=strict`), chaque `ReadWritePaths` est un montage « bind » à
# part : `audits`, `dashboard/static` et `public` sont trois montages, et
# `rename(2)` de l'un à l'autre rend `EXDEV`. Le 04/10/2026, ni « Publier » ni
# la passe planifiée ne pouvaient promouvoir un snapshot.
#
# La mise en service doit pourtant rester un renommage, seul geste atomique :
# elle se fait donc DANS le montage de la destination, depuis un répertoire de
# transit voisin (`_logement`) où la version neuve a été COPIÉE puis vérifiée.
# Le transit est vidé à la fin de chaque opération, et au début de la suivante
# si un plantage l'a laissé. Rien de ce qui dure (`.precedent`) n'y habite.
LOGEMENT = ".bascule"

# Écrit dans chaque répertoire mis en service, et emporté par le déploiement.
# C'est la pièce qui distingue « publié » de « en ligne » : sans elle, l'atelier
# ne peut qu'affirmer avoir publié, jamais constater que c'est arrivé.
VERSION_SERVIE = "version.json"

# Les rebuts du poste — Finder, AppleDouble, Windows. `verify_snapshot.py` les
# refuse dans un répertoire publié, et il a raison. Mais le Finder en écrit
# PENDANT la publication dès qu'une fenêtre montre le dossier de l'instance :
# le 16/09/2026, deux promotions de Lasalle ont été refusées de suite pour un
# `.DS_Store` apparu dans la source APRÈS son contrôle, puis emporté par la
# copie. Le nettoyage de `publier-site.sh` passe avant, pas pendant. Une copie
# ne les emporte donc jamais ; le contrôle, lui, reste strict.
#
# Le 17/09/2026, la course a continué ailleurs : un `.DS_Store` écrit dans le
# brouillon entre sa construction et son contrôle (aperçu refusé à Saillans),
# un autre dans la version neuve du site entre son contrôle et son empreinte
# (`version.json` en ligne ≠ empreinte promue), et deux téléversés par rsync
# entre le dernier nettoyage et l'envoi — servis en 200 à Saillans et Brassac.
# D'où, en plus : chaque répertoire de travail en est vidé juste avant son
# contrôle, l'empreinte les ignore, et rsync ne les envoie jamais.
REBUT_DU_POSTE = re.compile(r"^(\.DS_Store|\._.*|Thumbs\.db)$", re.I)


def retirer_rebuts(dossier: Path) -> None:
    for fichier in Path(dossier).rglob("*"):
        if REBUT_DU_POSTE.match(fichier.name) and fichier.is_file():
            fichier.unlink(missing_ok=True)

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


# ── Ce qui a changé en base depuis la publication ────────────────────────────

# Ce que le journal d'audit contient sans que cela change une ligne du site : les
# gestes de publication eux-mêmes (republier à cause de sa propre trace
# boucle), les propositions de citoyens, qui n'entrent dans les données
# qu'une fois validées — la validation, elle, écrit son propre geste — et les
# réglages de l'atelier (le modèle branché), qui ne touchent aucune donnée. La liste
# est une EXCLUSION et non une liste de tables à surveiller : un nouveau geste
# journalisé doit republier par défaut. Le défaut inverse, c'est la panne
# d'origine — une correction qui reste en base sans jamais être mise en ligne.
GESTES_SANS_EFFET_SUR_LE_SITE = ("publication", "propositions", "reglages")


def horodatage_base(iso_local: str | None) -> str | None:
    """Une date de l'état en heure de la base.

    `audit_log.at` est écrit par SQLite en UTC (`datetime('now')`) ; l'état porte
    une date locale avec décalage. Comparer les deux chaînes telles quelles
    décale la liste de deux heures l'été.
    """
    if not iso_local:
        return None
    try:
        return (datetime.fromisoformat(iso_local).astimezone(timezone.utc)
                .strftime("%Y-%m-%d %H:%M:%S"))
    except ValueError:
        return None


def corrections_depuis_la_publication(conn, etat: dict | None = None) -> dict[str, int]:
    """Les gestes journalisés depuis que le contenu publié a été figé, par table.

    Sert à la passe planifiée (`deploy/collecte.sh`) : sans collecte neuve, elle
    ne republiait pas, et une fusion de fiches, un verdict ou une saisie faits en
    base restaient hors ligne jusqu'à la prochaine arrivée de données.

    Pourquoi le JOURNAL et non un aperçu comparé au publié : un aperçu coûte une
    minute de snapshot, et surtout il n'est pas comparable — il porte sa date de
    génération et des états qui dépendent du jour (péremption d'un dossier), donc
    il différerait chaque matin et la passe republierait chaque jour. Le journal
    ne bouge que lorsqu'un humain a agi. Ce qui part ensuite reste l'aperçu
    contrôlé de `publier-site.sh`, jamais la base telle quelle.

    Le repère est la génération de l'aperçu PUBLIÉ, pas l'heure de promotion : un
    geste fait entre les deux est dans la base mais pas dans la version servie.
    Borne incluse — à la seconde près on ne sait pas de quel côté tombe un geste,
    et republier pour rien coûte une minute, là où l'oublier coûte la panne.

    Rien n'a jamais été publié par ce flux : `{}`. La première mise en ligne
    d'une instance reste un geste humain, pas une conséquence d'un journal.
    """
    publie = (lire_etat() if etat is None else etat).get("publie") or {}
    borne = horodatage_base(publie.get("apercu_genere_le") or publie.get("publie_le"))
    if borne is None:
        return {}
    exclus = ",".join("?" * len(GESTES_SANS_EFFET_SUR_LE_SITE))
    lignes = conn.execute(
        "SELECT COALESCE(table_name, '?') AS table_name, COUNT(*) AS n"
        " FROM audit_log WHERE at >= ?"
        f" AND COALESCE(table_name, '') NOT IN ({exclus})"
        " GROUP BY 1 ORDER BY n DESC",
        (borne, *GESTES_SANS_EFFET_SUR_LE_SITE)).fetchall()
    return {r[0]: r[1] for r in lignes}


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


# Un brouillon n'est « généré » que si la génération est allée au bout.
# `stats.json` est le PREMIER fichier que `build_snapshot` écrit : sa présence ne
# dit donc rien de l'achèvement. Constaté : un plantage en cours de génération a
# laissé un brouillon tronqué, l'atelier a construit le site dessus, et
# l'utilisateur a lu « Le build de l'aperçu a échoué — 404 /entite/1129 » — une
# fausse piste, la cause était la génération. L'achèvement se déclare donc
# APRÈS le retour du builder (`complet: True`, dans l'état du brouillon ou la
# fiche de l'aperçu — jamais dans le snapshot, qui part chez l'hébergeur), et se
# retire AVANT de l'appeler : un plantage laisse un brouillon non déclaré.
#
# Compat : un brouillon écrit avant cette règle n'a pas `complet`, et rien ne
# permet de savoir s'il est entier (c'est précisément ce qu'on ne savait pas
# dire). Il est refusé : une régénération, un clic, le remet en état.
GENERATION_INACHEVEE = (
    "La dernière génération n'est pas allée au bout — le brouillon est peut-être "
    "tronqué. Générer un nouvel aperçu.")


def _generation_aboutie(cible: Path) -> bool:
    cible = Path(cible).resolve()
    racine = APERCUS.resolve()
    if racine in cible.parents:                  # l'aperçu d'un compte
        # La fiche se retrouve par le NUMÉRO du compte, validé entier par
        # `dossier_apercu`, et non par un chemin dérivé de `cible` : un chemin
        # qui vient de l'appelant n'a pas à devenir un chemin lu (CodeQL,
        # path-injection, relevé sur la première version de cette fonction).
        numero = cible.relative_to(racine).parts[0]
        if not numero.isdigit() or int(numero) <= 0:
            return False
        try:
            fiche = json.loads(_fiche_apercu(int(numero)).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return fiche.get("complet") is True
    brouillon = lire_etat().get("brouillon") or {}
    # Le répertoire est comparé : l'état ne décrit qu'UN brouillon, il ne
    # vaut pas pour un autre répertoire passé en argument.
    declare = brouillon.get("repertoire")
    return (brouillon.get("complet") is True and isinstance(declare, str)
            and declare != "" and os.path.realpath(declare) == str(cible))


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


def etat_publication(compte: int | None = None) -> dict:
    """L'état complet, tel que la page Publication le montre.

    Avec `compte`, l'aperçu montré est celui de ce compte ; sans, le brouillon
    de la ligne de commande.

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

    if compte is not None:
        brouillon = apercu_du_compte(compte)
    else:
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
        "apercu": (etat_serveur_apercu_du_compte(compte) if compte is not None
                   else etat_serveur_apercu()),
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
        etat = lire_etat()
        etat.pop("brouillon", None)         # avant le builder : cf. GENERATION_INACHEVEE
        ecrire_etat(etat)
        stats = builder(cible)
        retirer_rebuts(cible)
        controle = controleur(cible)

        resume = {
            "genere_le": maintenant(),
            "genere_par": auteur,
            "complet": True,
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


# ── Aperçus par compte ───────────────────────────────────────────────────────

def dossier_apercu(compte: int) -> Path:
    """`audits/apercus/<compte>` — le numéro est vérifié entier : il devient un
    chemin, et rien d'autre qu'un entier ne doit pouvoir y entrer."""
    if isinstance(compte, bool) or not isinstance(compte, int) or compte <= 0:
        raise PublicationRefusee(f"Compte invalide pour un aperçu : {compte!r}")
    from collectors.chemins import sous
    return sous(APERCUS, str(compte))


def _fiche_apercu(compte: int) -> Path:
    return dossier_apercu(compte) / "apercu.json"


def _expire_le(genere_le: str | None) -> str | None:
    if not genere_le:
        return None
    try:
        debut = datetime.fromisoformat(genere_le)
    except ValueError:
        return None
    return (debut + timedelta(days=APERCU_JOURS)).isoformat(timespec="seconds")


def apercu_du_compte(compte: int) -> dict:
    """L'aperçu d'un compte, tel que la page le montre — ou `existe: False`."""
    dossier = dossier_apercu(compte)
    donnees, site = dossier / "donnees", dossier / "site"
    try:
        fiche = json.loads(_fiche_apercu(compte).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        fiche = {}
    stats = _stats_du_repertoire(donnees)
    existe = bool(fiche.get("genere_le")) and stats is not None
    return {
        **fiche,
        "compte": compte,
        "existe": existe,
        "repertoire": str(donnees),
        "stats": fiche.get("stats") or stats,
        "exclusions": fiche.get("exclusions") or (stats or {}).get("exclusions", {}),
        "expire_le": _expire_le(fiche.get("genere_le")),
        "duree_jours": APERCU_JOURS,
        "site": {
            "repertoire": str(site),
            "existe": (site / "index.html").is_file(),
            "perime": _build_perime(site, donnees),
        },
    }


def _build_perime(site: Path, donnees: Path) -> bool:
    index, stats = site / "index.html", donnees / "stats.json"
    if not index.is_file():
        return True
    return stats.is_file() and index.stat().st_mtime < stats.stat().st_mtime


def purger_apercus(maintenant_: datetime | None = None) -> list[int]:
    """Efface les aperçus plus vieux que `APERCU_JOURS`. Rend les comptes purgés.

    Un aperçu sans fiche lisible (génération interrompue) est jugé sur la date
    du répertoire. Rien d'autre que des sous-répertoires numérotés n'est touché.
    """
    if not APERCUS.is_dir():
        return []
    instant = (maintenant_ or datetime.now(timezone.utc)).timestamp()
    limite = instant - APERCU_JOURS * 86400
    purges = []
    for dossier in APERCUS.iterdir():
        if not (dossier.is_dir() and dossier.name.isdigit()):
            continue
        try:
            genere = datetime.fromisoformat(json.loads(
                (dossier / "apercu.json").read_text(encoding="utf-8"))["genere_le"]).timestamp()
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            genere = dossier.stat().st_mtime
        if genere < limite:
            shutil.rmtree(dossier, ignore_errors=True)
            purges.append(int(dossier.name))
    return purges


def generer_apercu_du_compte(compte: int, auteur: str | None = None,
                             builder=None, controleur=None) -> dict:
    """L'aperçu de CE compte : construit, contrôlé, daté. Il remplace le précédent
    du même compte, et rien d'autre — ni le brouillon de la ligne de commande,
    ni l'aperçu d'un autre compte, ni ce qui est servi."""
    dossier = dossier_apercu(compte)
    donnees = _verifier_cible_brouillon(dossier / "donnees")
    builder = builder or build_snapshot
    controleur = controleur or controler
    purger_apercus()
    # Sous le verrou de publication : l'admin peut publier ce même répertoire.
    # Attente plus longue que pour la ligne de commande : plusieurs personnes
    # peuvent demander un aperçu dans la même minute.
    with verrou_de_publication(delai=300.0):
        # La fiche d'abord : sans elle, le répertoire n'est plus un aperçu.
        _fiche_apercu(compte).unlink(missing_ok=True)
        if donnees.exists():
            shutil.rmtree(donnees)          # écrasé, jamais complété
        donnees.mkdir(parents=True)
        stats = builder(donnees)
        retirer_rebuts(donnees)
        controle = controleur(donnees)
        resume = {
            "genere_le": maintenant(),
            "genere_par": auteur,
            "complet": True,
            "compte": compte,
            "stats": stats,
            "exclusions": (stats or {}).get("exclusions", {}),
            "controle": controle,
        }
        _fiche_apercu(compte).write_text(json.dumps(resume, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    return apercu_du_compte(compte)


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
                verrou_fichier.prendre(f, attendre=False)
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
            verrou_fichier.rendre(f)


def empreinte(dossier: Path) -> str:
    """Ce que contient un répertoire, en une chaîne comparable.

    Chemins ET contenus : deux versions qui ne diffèrent que par un fichier
    supprimé doivent avoir deux empreintes. Sert à dire QUELLE version est
    servie, et à vérifier après coup que c'est bien celle-là qui est en ligne.
    Les rebuts du poste n'en font pas partie : rsync ne les envoie pas.
    """
    h = hashlib.sha256()
    for fichier in sorted(dossier.rglob("*")):
        if (not fichier.is_file() or fichier.name == VERSION_SERVIE
                or REBUT_DU_POSTE.match(fichier.name)):
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


def _cle(dest: Path) -> str:
    """Le nom d'un emplacement servi, assez précis pour ne pas en confondre deux.

    Une empreinte du chemin : deux emplacements servis qui s'appelleraient
    pareil (`outputs.public_snapshot_dir` est réglable) s'écraseraient sinon
    leur retour arrière.
    """
    return f"{dest.name}-{hashlib.sha256(str(Path(dest).resolve()).encode()).hexdigest()[:8]}"


def _voisins(dest: Path) -> tuple[Path, Path]:
    """La version en construction et la version d'avant d'un emplacement servi.

    Dans `VERSIONS`, jamais à côté de `dest` : cf. la définition de `VERSIONS`.
    """
    cle = _cle(dest)
    return VERSIONS / f"{cle}.neuf", VERSIONS / f"{cle}.precedent"


def _logement(dest: Path) -> Path:
    """Le répertoire de transit d'un emplacement : DANS le montage de `dest`.

    Un renommage ne traverse pas deux `ReadWritePaths` : le transit doit être
    écrit dans celui de la destination — et nulle part qu'un build recopie.
      - le site (`public/static/data`) : `public/.bascule/`, au-dessus de
        `static/`. `public` est un seul montage, et SvelteKit ne recopie que
        `static/` : un build concurrent ne le voit pas. Il le faut — le build de
        `publier-site.sh` ne prend aucun verrou du moteur ;
      - l'emplacement de l'atelier (`dashboard/static/public_api`) : le montage
        EST `dashboard/static`, il n'y a pas d'au-dessus. Le transit y est à
        côté, et n'existe que le temps d'une opération, sous le verrou de
        publication. Rien dans le moteur ne construit le tableau de bord.
    """
    dest = Path(dest)
    if dest.resolve() == SITE.resolve():
        return SITE.parent.parent / LOGEMENT
    return dest.parent / LOGEMENT


def _transit(dest: Path) -> tuple[Path, Path, Path]:
    """`(entrant, sortant, rangement)` : la version neuve amenée dans le montage,
    l'ancienne écartée dans le montage, et l'ancienne en route vers `VERSIONS`."""
    cle = _cle(Path(dest))
    return (_logement(dest) / f"{cle}.entrant", _logement(dest) / f"{cle}.sortant",
            VERSIONS / f"{cle}.rangement")


def _nettoyer_le_transit(dest: Path, *en_plus: Path) -> None:
    """Retire ce qu'un plantage a pu laisser : au début de chaque opération.

    Un plantage entre les deux renommages de la mise en service laisse `dest`
    absent et l'ancienne version dans `sortant` : la remettre AVANT de vider,
    sans quoi le nettoyage effacerait la seule version qui existe.
    """
    _, sortant, _ = _transit(dest)
    if sortant.is_dir() and not Path(dest).exists():
        sortant.rename(dest)
    for trace in (*_transit(dest), *en_plus):
        _vider(trace)
    _retirer_le_logement(dest)


def _retirer_le_logement(dest: Path) -> None:
    """Le transit n'existe que pendant une opération : au repos, il n'y a rien."""
    try:
        _logement(dest).rmdir()
    except OSError:
        pass                              # absent, ou occupé par un autre emplacement


def _mettre_en_service(dest: Path, entrant: Path, sortant: Path) -> None:
    """Les deux renommages, dans le montage de `dest`. Un échec remet l'ancienne."""
    try:
        if dest.exists():
            dest.rename(sortant)
        entrant.rename(dest)
    except OSError:
        # Le renommage a échoué alors que l'ancien est peut-être déjà écarté : le
        # remettre en service vaut mieux que laisser l'emplacement vide. On ne
        # vide que l'entrant — `sortant` est peut-être la seule version qui reste.
        if sortant.exists() and not dest.exists():
            sortant.rename(dest)
        _vider(entrant)
        _retirer_le_logement(dest)
        raise


def _amener(src: Path, dst: Path, *, garder: bool = False) -> bool:
    """Place le répertoire `src` sous le nom `dst`, quel que soit le montage.

    Renommage quand le noyau l'accepte. Sinon (`EXDEV`) une copie, dont
    l'empreinte est comparée à celle de la source avant que celle-ci ne soit
    retirée : une copie tronquée ne remplace jamais la version qu'elle copie.
    `garder` : la source reste, et on copie même quand un renommage passerait.
    Rend vrai si c'était une copie.
    """
    if not garder:
        try:
            src.rename(dst)
            return False
        except OSError as e:
            if e.errno != errno.EXDEV:
                raise
    _vider(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    miroir(src, dst)
    if empreinte(dst) != empreinte(src):
        _vider(dst)
        raise OSError(errno.EIO, f"copie de {src.name} différente de sa source")
    if not garder:
        _vider(src)
    return True


def _garder_comme_precedent(sortant: Path, precedent: Path, rangement: Path) -> str | None:
    """L'ancienne version servie devient la version précédente, dans `VERSIONS`.

    Le montage de `VERSIONS` n'est pas celui de `sortant` : c'est une copie. Elle
    passe par `rangement` et ne remplace l'ancienne précédente que par un
    renommage dans `VERSIONS`. Si elle échoue (disque plein), la promotion
    reste faite — ce qui est servi est entier — mais l'ancienne précédente, qui
    ne serait plus celle d'avant, est retirée : mieux vaut « aucune version
    précédente » qu'un retour arrière vers une version vieille de deux
    publications. Rend le message d'échec, ou `None`.
    """
    if not sortant.is_dir():
        return None                         # première publication : rien d'avant
    try:
        _amener(sortant, rangement)
        _vider(precedent)
        rangement.rename(precedent)
        return None
    except OSError as e:
        _vider(rangement)
        _vider(precedent)
        return f"{type(e).__name__}: {e}"


def basculer(src: Path, dest: Path, controleur) -> dict:
    """Construit la version à côté, la contrôle, PUIS la met en service.

    Le défaut que ça corrige : `miroir()` remplaçait les fichiers servis un par
    un, et le contrôle venait après. Un contrôle rouge trouvait donc l'ancien
    snapshot déjà à moitié écrasé — sans rien pour revenir en arrière, et sans
    que le message « le site public est inchangé » soit encore vrai. Un visiteur
    tombant au milieu de la copie voyait, lui, un site mi-ancien mi-neuf.

    Ici, `dest` n'est touché qu'une fois la version neuve complète et contrôlée,
    et le changement se fait par deux renommages de répertoire — l'ancien
    s'efface au profit du transit, le neuf prend sa place. Un renommage est
    atomique pour le système de fichiers ; il reste une fenêtre de l'ordre de la
    microseconde entre les deux où `dest` n'existe pas, contre plusieurs
    secondes de contenu incohérent auparavant.

    Ce qui est servi reste donc toujours une version entière : soit l'ancienne,
    soit la nouvelle, jamais un mélange des deux.

    Trois lieux, parce que trois montages sous systemd : la version neuve est
    construite et contrôlée dans `VERSIONS` ; elle est amenée par copie
    vérifiée dans le transit du montage de `dest` (`_logement`), d'où le
    renommage final est possible ; l'ancienne version, écartée par un renommage
    dans ce même montage, est enfin rangée dans `VERSIONS` comme version
    précédente. L'appelant tient `verrou_de_publication`.
    """
    dest = Path(dest)
    neuf, precedent = _voisins(dest)
    entrant, sortant, rangement = _transit(dest)
    # L'ancien emplacement, à côté du répertoire servi : une instance publiée
    # avant le 16/09/2026 y garde une version que chaque build remet en ligne.
    # Il est remplacé par la version courante ci-dessous, donc rien ne s'y perd.
    for ancien in (dest.parent / f".{dest.name}.neuf",
                   dest.parent / f".{dest.name}.precedent"):
        _vider(ancien)
    _nettoyer_le_transit(dest, neuf)

    neuf.mkdir(parents=True)
    copie = miroir(src, neuf)

    # Le contrôle porte sur le répertoire NEUF, avant qu'il ne serve. Un refus
    # ici ne coûte qu'un répertoire temporaire.
    retirer_rebuts(neuf)
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

    # Sur une instance neuve, le parent du répertoire servi n'existe pas encore.
    dest.parent.mkdir(parents=True, exist_ok=True)
    _logement(dest).mkdir(parents=True, exist_ok=True)
    try:
        _amener(neuf, entrant)              # dans le montage de `dest`
    except Exception:
        _nettoyer_le_transit(dest, neuf)    # `dest` n'a pas été touché
        raise
    _mettre_en_service(dest, entrant, sortant)

    perdu = _garder_comme_precedent(sortant, precedent, rangement)
    _nettoyer_le_transit(dest)
    return {"ok": True, "controle": controle, "empreinte": marque,
            "precedent": str(precedent) if precedent.exists() else None,
            **({"precedent_perdu": perdu} if perdu else {}),
            **copie, "dest": str(dest)}


def revenir_a_la_version_precedente(dest: Path) -> dict:
    """Remet en service la version d'avant, si elle est encore là.

    Existe parce qu'un contrôle vert ne garantit pas qu'une version soit BONNE :
    il garantit qu'elle est étanche. Un chiffre faux, un découpage raté, une
    page vide passent le contrôle. Quelqu'un doit pouvoir revenir en arrière
    sans reconstruire.

    Même parcours que `basculer`, même raison : la version d'avant vit dans
    `VERSIONS`, elle est COPIÉE dans le transit du montage de `dest` — et reste
    où elle est tant que la mise en service n'a pas eu lieu. L'appelant tient
    `verrou_de_publication` (l'API le fait ; ce verrou n'est pas réentrant).
    """
    dest = Path(dest)
    _, precedent = _voisins(dest)
    if not precedent.is_dir():
        raise PublicationRefusee(
            f"Aucune version précédente conservée pour {dest.name} — "
            "rien à remettre en service.")
    entrant, sortant, rangement = _transit(dest)
    _nettoyer_le_transit(dest)
    _logement(dest).mkdir(parents=True, exist_ok=True)
    try:
        _amener(precedent, entrant, garder=True)
    except Exception:
        _nettoyer_le_transit(dest)
        raise
    _mettre_en_service(dest, entrant, sortant)
    # L'ancienne courante devient la précédente : revenir deux fois de suite
    # doit ramener là d'où l'on vient, pas creuser.
    perdu = _garder_comme_precedent(sortant, precedent, rangement)
    _nettoyer_le_transit(dest)
    return {"dest": str(dest), "empreinte": empreinte(dest),
            **({"precedent_perdu": perdu} if perdu else {})}


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
        if not fichier.is_file() or REBUT_DU_POSTE.match(fichier.name):
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
            source: Path | None = None, controleur=None,
            apercu: dict | None = None) -> dict:
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

    `apercu` : l'aperçu d'un compte (`apercu_du_compte`). Dans l'atelier, l'admin
    publie SON aperçu, généré par lui ; un aperçu expiré ne se publie pas.
    """
    if not peut_publier(role):
        raise PublicationRefusee(
            "Publier est réservé au rôle admin. L'état de publication et "
            "l'aperçu restent consultables.")
    if apercu is not None:
        if not apercu.get("existe"):
            raise PublicationRefusee(
                "Vous n'avez pas d'aperçu à publier — générer d'abord votre aperçu, "
                "le regarder, puis publier.")
        expire = apercu.get("expire_le")
        if expire and datetime.fromisoformat(expire) < datetime.now(timezone.utc):
            raise PublicationRefusee(
                "Votre aperçu a expiré — en générer un nouveau : il montrera l'état "
                "actuel de la base.")
        source = Path(apercu["repertoire"])

    with verrou_de_publication():
        return _publier_sous_verrou(auteur, source, controleur, apercu)


def _publier_sous_verrou(auteur, source, controleur, apercu=None) -> dict:
    source = (source or BROUILLON).resolve()
    controleur = controleur or controler
    etat = lire_etat()
    brouillon = apercu if apercu is not None else (etat.get("brouillon") or {})
    if not (source / "stats.json").is_file():
        raise PublicationRefusee(
            "Aucun aperçu à publier — générer un aperçu d'abord.")
    if not _generation_aboutie(source):
        raise PublicationRefusee(GENERATION_INACHEVEE)

    # 1. Le brouillon, à l'instant de publier. Un contrôle vert d'il y a une
    #    heure ne dit rien du répertoire d'aujourd'hui.
    retirer_rebuts(source)
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


# Les variables que lit `deploy/publier-site.sh`, par hébergeur, et ce qu'elles
# deviennent dans le bloc `publication` de `config/instance.json`.
CIBLES = {
    "rsync": {"hote": "VIGIE_CIBLE_HOTE", "chemin": "VIGIE_CIBLE_CHEMIN",
              "rsync_path": "VIGIE_CIBLE_RSYNC_PATH"},
    "cloudflare": {"projet": "CF_PROJECT"},
    # Le site est servi par la MACHINE qui porte l'atelier : une copie d'un
    # répertoire à l'autre. Ni ssh ni sudo — le compte de l'atelier n'a ni clé
    # ni droit d'élévation, et il n'a pas à en avoir pour écrire à côté de lui.
    "local": {"chemin": "VIGIE_CIBLE_CHEMIN"},
}
CHAMPS_EXIGES = {"rsync": ("hote", "chemin"), "cloudflare": ("projet",),
                 "local": ("chemin",)}


def destination() -> dict | None:
    """Où part le site public : déclaré UNE fois, lu par toutes les façons de publier.

    La destination vivait à trois endroits : `cf_project` dans l'instance pour
    le bouton de l'atelier, et un `case` recopié dans deux scripts personnels
    pour la ligne de commande. Les trois ont divergé — le 16/09/2026, le bouton
    visait encore Cloudflare Pages, abandonné depuis le 01/09, pendant que les
    scripts publiaient sur le VPS. Un clic aurait remis en ligne l'adresse
    qu'on avait fait mourir.

    Par ordre de priorité :
      1. l'environnement (`VIGIE_CIBLE`, `CF_PROJECT`…), pour qui l'utilise
         déjà ou publie ponctuellement ailleurs ;
      2. le bloc `publication` de `config/instance.json` :
             {"cible": "rsync", "hote": "…", "chemin": "…", "rsync_path": "…"}
             {"cible": "cloudflare", "projet": "…"}
             {"cible": "local", "chemin": "/srv/www/macommune"}
      3. l'ancienne clé `cf_project`, lue comme une cible Cloudflare.

    Rien de déclaré rend `None`. Une déclaration INCOMPLÈTE est refusée : la
    traiter comme une absence ferait publier ailleurs, ou nulle part, sans
    qu'une ligne le dise.
    """
    env = os.environ
    if env.get("VIGIE_CIBLE") or env.get("CF_PROJECT"):
        cible = env.get("VIGIE_CIBLE") or "cloudflare"
        declaree = {"cible": cible, "source": "environnement"}
        for champ, variable in CIBLES.get(cible, {}).items():
            if env.get(variable):
                declaree[champ] = env[variable]
    else:
        instance = _lire_instance()
        bloc = instance.get("publication")
        if isinstance(bloc, dict) and bloc.get("cible"):
            declaree = {k: v for k, v in bloc.items() if not k.startswith("_")}
            declaree["source"] = "config/instance.json"
        elif instance.get("cf_project"):
            declaree = {"cible": "cloudflare", "projet": instance["cf_project"],
                        "source": "config/instance.json (cf_project)"}
        else:
            return None

    cible = declaree["cible"]
    if cible not in CIBLES:
        raise PublicationRefusee(
            f"Hébergeur inconnu : « {cible} ». Les cibles connues sont "
            f"{', '.join(sorted(CIBLES))}.")
    manquants = [c for c in CHAMPS_EXIGES[cible] if not declaree.get(c)]
    if manquants:
        raise PublicationRefusee(
            f"Destination « {cible} » incomplète ({declaree['source']}) : "
            f"il manque {', '.join(manquants)}.")
    # Chaque valeur finit en argument de `rsync` ou de `wrangler` : un tiret de
    # tête y serait lu comme une option.
    for champ in CIBLES[cible]:
        if str(declaree.get(champ, "")).startswith("-"):
            raise PublicationRefusee(
                f"Destination refusée : « {champ} » commence par un tiret.")

    if cible == "local" and not str(declaree["chemin"]).startswith("/"):
        raise PublicationRefusee(
            f"Destination « local » refusée : « {declaree['chemin']} » n'est pas un "
            "chemin absolu. Un chemin relatif publierait là où le script est lancé.")

    declaree["libelle"] = {
        "rsync": lambda d: f"{d['hote']}:{d['chemin']}",
        "local": lambda d: f"ce serveur, {d['chemin']}",
        "cloudflare": lambda d: f"Cloudflare Pages « {d['projet']} »",
    }[cible](declaree)
    return declaree


def _lire_instance() -> dict:
    chemin = Path(os.environ.get("VIGIE_INSTANCE") or ROOT / "config" / "instance.json")
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def destination_pour_le_shell(declaree: dict) -> str:
    """La destination sous la forme que `deploy/publier-site.sh` évalue.

    Le script ne relit pas `instance.json` lui-même : deux lecteurs du même
    fichier, c'est deux ordres de priorité qui finissent par différer.
    """
    lignes = [f"export VIGIE_CIBLE={shlex.quote(declaree['cible'])}"]
    for champ, variable in CIBLES[declaree["cible"]].items():
        if declaree.get(champ):
            lignes.append(f"export {variable}={shlex.quote(str(declaree[champ]))}")
    return "\n".join(lignes)


def etat_mise_en_ligne() -> dict:
    """Où en est le déploiement — en cours, fini, ou jamais lancé."""
    actif = _deploiement is not None and _deploiement.poll() is None
    fini = _deploiement is not None and _deploiement.poll() is not None
    try:
        declaree = destination()
        vers, erreur = (declaree or {}).get("libelle"), None
    except PublicationRefusee as e:
        vers, erreur = None, e.message
    etat = {
        "actif": actif,
        "destination": vers,
        "destination_erreur": erreur,
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
    # Qui construit le site en ce moment. Un aperçu : la mise en ligne attend
    # qu'il ait fini, et la page le dit au lieu d'offrir le bouton.
    etat["build"] = build_en_cours()
    return etat


def mettre_en_ligne(auteur: str | None = None, role: str | None = None) -> dict:
    """Construit le site depuis la version PROMUE, et le téléverse.

    Par `deploy/publier-site.sh --deja-promu`, qui saute l'aperçu et la
    promotion : ce qui a été promu a été contrôlé, et le reconstruire depuis la
    base déploierait une version que personne n'a validée, différente dès qu'un
    collecteur a tourné entre-temps. On repart donc de `public/static/data` tel
    qu'il est servi.

    Le build et le téléversement ne sont écrits qu'une fois, dans le script.
    L'atelier avait les siens — `wrangler` en dur — et ils ont continué de viser
    Cloudflare Pages quinze jours après que le site en était parti.
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

    declaree = destination()
    if not declaree:
        raise PublicationRefusee(
            "Aucune destination déclarée pour le site public. Ajouter à "
            "config/instance.json un bloc `publication` — "
            '{"cible": "rsync", "hote": "…", "chemin": "…"}, '
            '{"cible": "local", "chemin": "…"} ou '
            '{"cible": "cloudflare", "projet": "…"}. Sans lui, le déploiement '
            "irait au hasard.")
    if not (ROOT / "public" / "node_modules").is_dir():
        raise PublicationRefusee(
            "Le site public n'a pas ses dépendances : `cd public && npm ci`.")

    DEPLOIEMENT_LOG.parent.mkdir(parents=True, exist_ok=True)
    DEPLOIEMENT_ETAT.write_text(json.dumps({
        "demarre_le": maintenant(), "demarre_par": auteur,
        "destination_visee": declaree["libelle"],
        "empreinte_visee": empreinte_promue,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    journal = DEPLOIEMENT_LOG.open("w", encoding="utf-8")
    journal.write(f"$ mise en ligne de {SITE} vers {declaree['libelle']}\n"
                  f"  empreinte promue : {empreinte_promue}\n\n")
    journal.flush()
    # `PY` : l'interpréteur de l'atelier, qui a les dépendances du moteur. Sans
    # lui, le script retombe sur le `python3` du système.
    _deploiement = subprocess.Popen(
        ["bash", str(ROOT / "deploy" / "publier-site.sh"),
         "--deployer", "--deja-promu"],
        cwd=str(ROOT), env={**os.environ, "PY": sys.executable},
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


def construire_apercu(cible: Path | None = None, build: Path | None = None) -> dict:
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
    build = build or APERCU_BUILD
    if not (cible / "stats.json").is_file():
        raise PublicationRefusee(
            "Aucun aperçu à construire — générer un aperçu d'abord.")
    if not _generation_aboutie(cible):
        raise PublicationRefusee(GENERATION_INACHEVEE)
    if not _vite().exists():
        raise PublicationRefusee(
            "Le site public n'a pas ses dépendances : `cd public && npm install`. "
            "L'aperçu construit le site lui-même, il lui faut de quoi tourner.")

    APERCU_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _verrou_de_build("un aperçu", genre="apercu"), \
            APERCU_LOG.open("w", encoding="utf-8") as journal:
        journal.write(f"$ npm run build  (VIGIE_DATA_DIR={cible})\n\n")
        journal.flush()
        issue = subprocess.run(
            [_npm(), "run", "build"],
            cwd=str(ROOT / "public"),
            env={**os.environ,
                 "VIGIE_DATA_DIR": str(cible),
                 "VIGIE_BUILD_DIR": str(build)},
            stdout=journal, stderr=subprocess.STDOUT,
        )
    if issue.returncode != 0:
        raise PublicationRefusee(
            "Le build de l'aperçu a échoué — c'est un défaut de l'artefact "
            "publiable, pas de l'atelier. Il n'y a rien à montrer tant qu'il "
            "n'est pas corrigé.", {"journal": _fin_du_journal(40)})
    if not (build / "index.html").is_file():
        raise PublicationRefusee(
            "Le build s'est terminé sans écrire de page d'accueil.",
            {"journal": _fin_du_journal(40)})

    # Les fichiers servis sous `/data/` sont ceux de `static/data` — ce qui est
    # en ligne. L'aperçu doit montrer ce qui SERA publié : le brouillon les
    # remplace, en miroir (01/10/2026 : les feuilles « en clair » retenues
    # n'existaient que dans le brouillon, leurs liens menaient au 404).
    miroir(cible, build / "data")

    pages = sum(1 for _ in build.rglob("*.html"))
    return {"repertoire": str(build), "pages": pages,
            "construit_le": maintenant(), "donnees": str(cible)}


def build_en_cours() -> dict | None:
    """Qui construit le site en ce moment — `None` si personne.

    Lu sur le verrou lui-même, pas sur un témoin : un verrou partagé pris sans
    attendre échoue tant qu'un build tient l'exclusif, et réussit dès qu'il est
    fini ou mort. Ce que le fichier CONTIENT (qui, depuis quand) n'est cru que
    dans le premier cas.
    """
    try:
        f = open(VERROU_BUILD, encoding="utf-8")
    except OSError:
        return None
    with f:
        try:
            verrou_fichier.prendre(f, partage=True, attendre=False)
        except BlockingIOError:
            try:
                tenant = json.loads(f.read())
            except (OSError, json.JSONDecodeError):
                tenant = {}
            return {"qui": tenant.get("qui") or "un autre build",
                    "genre": tenant.get("genre"),
                    "depuis": tenant.get("depuis")}
        verrou_fichier.rendre(f)
    return None


def _prendre_le_verrou_de_build(fd: int, qui: str, genre: str, delai: float,
                                dire=None) -> None:
    """Prend le verrou sur un descripteur DÉJÀ ouvert, en attendant son tour.

    Un build qui attend le dit (`dire`), une fois, en nommant qui il attend ;
    passé `delai`, il refuse sans avoir rien écrit.
    """
    debut = time.monotonic()
    annonce = False
    while True:
        try:
            verrou_fichier.prendre(fd, attendre=False)
            break
        except BlockingIOError:
            attendu = time.monotonic() - debut
            tenant = build_en_cours() or {}
            # Pas à la première seconde : `build_en_cours` prend le verrou en
            # partagé le temps de regarder, et ce n'est pas un build.
            if dire and not annonce and attendu >= 1 and tenant:
                dire(f"⏳ {tenant['qui']} construit déjà le site"
                     + (f" (depuis {tenant['depuis'][11:16]})"
                        if tenant.get("depuis") else "")
                     + f" — {qui} attend son tour : deux builds écrivent au même "
                       "endroit. Rien n'est touché d'ici là.")
                annonce = True
            if attendu >= delai:
                raise PublicationRefusee(
                    f"{tenant.get('qui') or 'Un autre build'} construit le site "
                    f"depuis plus de {int(delai // 60)} min : {qui} n'a pas eu "
                    "son tour. Rien n'a été construit — réessayer quand il aura fini.")
            time.sleep(0.5)
    if dire and annonce:
        dire(f"✓ le site est libre après {int(time.monotonic() - debut)} s — "
             f"{qui} commence.")
    # `lseek` + `write` et non `pwrite`, que Windows n'a pas.
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, json.dumps({"qui": qui, "genre": genre, "pid": os.getpid(),
                             "depuis": maintenant()},
                            ensure_ascii=False).encode("utf-8"))


@contextmanager
def _verrou_de_build(qui: str = "un aperçu", genre: str = "apercu",
                     delai: float = 600.0, dire=None):
    """Un build du site à la fois : tous écrivent dans `public/.svelte-kit/`."""
    VERROU_BUILD.parent.mkdir(parents=True, exist_ok=True)
    # `a+` et non `w` : ouvrir ne doit pas effacer ce qu'y a écrit celui qui
    # tient le verrou — c'est ce que lit celui qui attend.
    with open(VERROU_BUILD, "a+") as f:
        _prendre_le_verrou_de_build(f.fileno(), qui, genre, delai, dire)
        try:
            yield
        finally:
            verrou_fichier.rendre(f)


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
            "perime": _apercu_perime(BROUILLON),
        },
    }


# Le serveur sert soit UN build (ligne de commande, tests), soit TOUS les aperçus
# de l'atelier, chacun choisi par le cookie que pose le lien de l'atelier
# (`?apercu=<compte>`). `_serveur_racine` dit lequel tourne.
_serveur_racine = None


def etat_serveur_apercu_du_compte(compte: int) -> dict:
    actif = (_serveur is not None and _serveur.poll() is None
             and _serveur_racine == APERCUS)
    apercu = apercu_du_compte(compte)
    return {
        "actif": actif,
        "url": APERCU_URL if actif else None,
        # À ajouter à chaque lien : c'est lui qui dit au serveur QUEL aperçu montrer.
        "parametre": f"apercu={compte}",
        "port": APERCU_PORT,
        "installe": _vite().exists(),
        "journal": str(APERCU_LOG) if actif else None,
        "build": {
            "repertoire": apercu["site"]["repertoire"],
            "existe": apercu["site"]["existe"],
            "perime": apercu["site"]["perime"],
        },
    }


def demarrer_serveur_apercu_du_compte(compte: int) -> dict:
    """Construit le site de l'aperçu de ce compte s'il est absent ou périmé, et
    s'assure que le serveur des aperçus tourne. Il n'arrête jamais celui d'un
    autre compte : tous passent par le même port."""
    global _serveur, _serveur_racine
    apercu = apercu_du_compte(compte)
    if not apercu["existe"]:
        raise PublicationRefusee("Aucun aperçu à montrer — générer votre aperçu d'abord.")
    if not _vite().exists():
        raise PublicationRefusee(
            "Le site public n'a pas ses dépendances : `cd public && npm install`. "
            "L'aperçu construit le site lui-même, il lui faut de quoi tourner.")
    donnees = Path(apercu["repertoire"])
    site = Path(apercu["site"]["repertoire"])
    if apercu["site"]["perime"]:
        construire_apercu(donnees, build=site)

    if _serveur is not None and _serveur.poll() is None:
        if _serveur_racine == APERCUS:
            return etat_serveur_apercu_du_compte(compte)
        arreter_serveur_apercu()             # un aperçu de ligne de commande
    if _port_repond():
        raise PublicationRefusee(
            f"Le port {APERCU_PORT} est déjà occupé par un autre service. "
            "Choisir un autre port (VIGIE_APERCU_PORT), ou arrêter celui qui "
            "l'occupe.")
    APERCUS.mkdir(parents=True, exist_ok=True)
    journal = APERCU_LOG.open("a", encoding="utf-8")
    _serveur = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "servir_apercu.py"),
         str(APERCUS), "--par-compte", "--port", str(APERCU_PORT)],
        cwd=str(ROOT), stdout=journal, stderr=subprocess.STDOUT,
    )
    _serveur_racine = APERCUS
    if not _attendre_le_port():
        journal_lu = _fin_du_journal()
        arreter_serveur_apercu()
        raise PublicationRefusee(
            f"L'aperçu n'a pas démarré sur le port {APERCU_PORT} "
            f"(réglable par VIGIE_APERCU_PORT).\n\n{journal_lu}")
    return etat_serveur_apercu_du_compte(compte)


def _apercu_perime(cible: Path) -> bool:
    """Le build d'aperçu est-il plus vieux que le brouillon qu'il doit montrer ?

    Par les dates des fichiers, pas par l'état : un brouillon régénéré en ligne
    de commande (`publier-site.sh`) ne passe pas par l'atelier.
    """
    index, stats = APERCU_BUILD / "index.html", Path(cible) / "stats.json"
    if not index.is_file():
        return True
    return stats.is_file() and index.stat().st_mtime < stats.stat().st_mtime


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
    global _serveur, _serveur_racine
    cible = _verifier_cible_brouillon(cible or BROUILLON)
    if not (cible / "stats.json").is_file():
        raise PublicationRefusee("Aucun aperçu à montrer — générer un aperçu d'abord.")
    if _serveur is not None and _serveur.poll() is None:
        # Déjà en marche, il sert le build qu'il a sur le disque. Le 17/09/2026,
        # un aperçu régénéré ne s'y voyait donc pas : « Générer un aperçu »
        # rendait ses chiffres, le site ouvert montrait l'ancien, et la page
        # n'offrait qu'« Arrêter ». Le serveur relit le disque à chaque requête :
        # reconstruire suffit. Un build rouge arrête l'aperçu — servir le
        # précédent ferait croire qu'on regarde ses corrections.
        if _apercu_perime(cible):
            try:
                construire_apercu(cible)
            except PublicationRefusee:
                arreter_serveur_apercu()
                raise
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
    _serveur_racine = APERCU_BUILD

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
    global _serveur, _serveur_racine
    _serveur_racine = None
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


# ── Ligne de commande ────────────────────────────────────────────────────────
# Le même flux que la page Publication, pour `deploy/publier-site.sh` et les
# passes automatiques.
#
# Jusqu'au 16/09/2026, la ligne de commande avait son propre chemin :
# `build_public_snapshot.py` écrivait directement dans les deux répertoires
# servis. Le site était bien publié, mais sans brouillon, sans `version.json`
# à jour et sans rien dans l'état. L'atelier montrait un aperçu du 26/08 et une
# promotion du 23/08 devant un site du 16/09, et sa vérification en ligne
# comparait deux empreintes figées depuis trois semaines : « à jour », toujours.

DELAI_ENTRE_ESSAIS = 5


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Flux de publication : aperçu, promotion, constat en ligne.")
    gestes = parser.add_subparsers(dest="geste", required=True)
    gestes.add_parser("apercu", help="construire le snapshot dans le brouillon, "
                                     "et le contrôler")
    gestes.add_parser("publier", help="promouvoir le brouillon contrôlé vers les "
                                      "deux emplacements servis")
    verifier = gestes.add_parser("verifier", help="constater que le site en ligne "
                                                  "sert la version promue")
    verifier.add_argument("--essais", type=int, default=1,
                          help=f"tentatives, à {DELAI_ENTRE_ESSAIS} s d'écart")
    dest = gestes.add_parser("destination", help="dire où part le site public")
    dest.add_argument("--shell", action="store_true",
                      help="sous forme de variables que le script de publication évalue")
    verrou = gestes.add_parser(
        "verrou-de-build", help="prendre le verrou du build du site sur un "
                                "descripteur hérité (deploy/publier-site.sh)")
    verrou.add_argument("--chemin", action="store_true",
                        help="dire où est le fichier du verrou, sans le prendre")
    verrou.add_argument("--fd", type=int, help="descripteur ouvert par l'appelant")
    verrou.add_argument("--liberer", action="store_true")
    verrou.add_argument("--delai", type=float, default=ATTENTE_MISE_EN_LIGNE)
    args = parser.parse_args(argv)

    # Qui tape une commande sur la machine qui porte la base a déjà tous les
    # droits sur elle : le rôle ne départage quelqu'un que derrière l'API.
    auteur = f"{getpass.getuser()} (ligne de commande)"
    try:
        if args.geste == "apercu":
            from scripts.build_public_snapshot import PerimetreNonClasse
            try:
                resume = generer_apercu(auteur=auteur)
            except PerimetreNonClasse as e:
                print(f"✖ snapshot refusé — {e}", file=sys.stderr)
                return 2
            controle = resume.get("controle") or {}
            print(f"   brouillon : {resume['repertoire']} — "
                  f"{(resume.get('stats') or {}).get('entities_public')} entités publiques")
            print((controle.get("rapport") or "").strip())
            return 0 if controle.get("ok") else 1

        if args.geste == "verrou-de-build":
            # `flock` porte sur la DESCRIPTION de fichier ouverte, que le script
            # appelant garde après la fin de ce processus : le verrou pris ici
            # tient jusqu'à ce qu'il le rende ou meure. Pas de commande `flock`
            # dans le script : macOS n'en a pas.
            if args.chemin:
                VERROU_BUILD.parent.mkdir(parents=True, exist_ok=True)
                print(VERROU_BUILD)
            elif args.fd is None:
                parser.error("verrou-de-build : --fd ou --chemin")
            elif args.liberer:
                verrou_fichier.rendre(args.fd)
            else:
                _prendre_le_verrou_de_build(
                    args.fd, "la mise en ligne", "mise_en_ligne", args.delai,
                    dire=lambda ligne: print(f"   {ligne}", flush=True))
            return 0

        if args.geste == "publier":
            publie = publier(auteur=auteur, role="admin")
            print(f"   promu : empreinte {publie['empreinte']} → {PUBLIE}, {SITE}")
            if publie.get("differences"):
                print(f"   ⚠ écarts entre l'aperçu et la copie : {publie['differences']}")
            return 0

        if args.geste == "verifier":
            for essai in range(max(1, args.essais)):
                if essai:
                    time.sleep(DELAI_ENTRE_ESSAIS)
                verdict = verifier_en_ligne()
                if verdict["ok"] or not verdict.get("url") \
                        or not verdict.get("empreinte_attendue"):
                    break
            if not verdict.get("url"):
                # Une instance sans site n'a rien à constater : ce n'est pas un échec.
                print(f"   ⚠ {verdict['motif']}")
                return 0
            print(f"   {'✓' if verdict['ok'] else '✖'} {verdict['motif']} "
                  f"(servie : {verdict.get('empreinte')}, promue : "
                  f"{verdict.get('empreinte_attendue')})")
            return 0 if verdict["ok"] else 1

        declaree = destination()
        if not declaree:
            print("✖ Aucune destination déclarée : ajouter un bloc `publication` "
                  "à config/instance.json.", file=sys.stderr)
            return 1
        print(destination_pour_le_shell(declaree) if args.shell
              else f"{declaree['libelle']} ({declaree['source']})")
        return 0
    except PublicationRefusee as e:
        print(f"✖ {e.message}", file=sys.stderr)
        rapport = (e.detail.get("controle") or {}).get("rapport")
        if rapport:
            print(rapport, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
