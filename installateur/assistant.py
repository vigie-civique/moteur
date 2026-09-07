#!/usr/bin/env python3
"""assistant.py — l'installateur, servi dans le navigateur.

Pourquoi une page web plutôt qu'une fenêtre native : parce qu'il n'existe pas
d'interface graphique commune aux trois systèmes qu'on soit sûr de trouver.
Tkinter est absent d'un Python posé par uv et vit dans un paquet séparé sur
Debian ; Qt et GTK sont des installations de plusieurs centaines de mégaoctets.
Le navigateur, lui, est là partout — et le dispositif s'en sert déjà pour tout
le reste : le site public comme l'atelier. L'installateur parle donc la même
langue que ce qu'il installe.

Ce fichier n'importe QUE la bibliothèque standard. Il démarre avant le venv.

── Ce qui protège cette page ────────────────────────────────────────────────

Un serveur local est joignable par toute page web ouverte dans le même
navigateur : un site quelconque peut envoyer des requêtes à 127.0.0.1 sans que
personne ne le voie. Ce serveur-là installe des logiciels et écrit des fichiers ;
il se défend en trois points, et aucun n'est de trop :

  1. il n'écoute QUE sur 127.0.0.1 — rien du réseau local n'y accède ;
  2. chaque requête porte un jeton tiré au sort au démarrage, imprimé dans
     l'adresse ouverte. Une page tierce ne peut pas le lire (elle n'a pas le
     droit de lire une réponse d'une autre origine), donc elle ne peut pas
     l'envoyer ;
  3. l'en-tête `Host` est vérifié. Sans ce contrôle, un nom de domaine qui
     résout vers 127.0.0.1 (« DNS rebinding ») transformerait un site distant
     en client de ce serveur.
"""
from __future__ import annotations

import json
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))

import etapes  # noqa: E402
import outils  # noqa: E402
from outils import Echec, RACINE  # noqa: E402

PORTS = range(8790, 8800)
GEO = "https://geo.api.gouv.fr"
JETON = secrets.token_urlsafe(24)


# ── Le travail en cours ──────────────────────────────────────────────────────

class Travail:
    """Une seule étape à la fois, et son journal.

    Un seul travail simultané est une contrainte volontaire : deux `npm ci` en
    parallèle sur le même cache, ou une collecte pendant une publication, se
    marchent dessus d'une façon qu'on ne saurait pas diagnostiquer depuis une
    page web.
    """

    def __init__(self) -> None:
        self.verrou = threading.Lock()
        self.lignes: list[str] = []
        self.etape = ""
        self.etat = "repos"          # repos | en_cours | fini | echec
        self.message = ""
        self.arret = threading.Event()

    def journal(self, ligne: str) -> None:
        with self.verrou:
            self.lignes.append(ligne)

    def depuis(self, indice: int) -> dict:
        with self.verrou:
            return {"lignes": self.lignes[indice:], "total": len(self.lignes),
                    "etape": self.etape, "etat": self.etat, "message": self.message}

    def lancer(self, etape: str, fonction) -> None:
        if self.etat == "en_cours":
            raise Echec(f"Une étape est déjà en cours ({self.etape}).")
        with self.verrou:
            self.lignes = []
            self.etape, self.etat, self.message = etape, "en_cours", ""
        self.arret.clear()

        def tourner() -> None:
            debut = time.time()
            try:
                fonction(self.journal, self.arret)
                duree = time.time() - debut
                self.journal(f"\n✓ terminé en {duree / 60:.1f} min"
                             if duree > 90 else f"\n✓ terminé en {duree:.0f} s")
                with self.verrou:
                    self.etat = "fini"
            except Echec as e:
                # Un arrêt DEMANDÉ n'est pas une panne. L'afficher en rouge à
                # côté d'une croix ferait chercher une erreur là où il n'y a
                # qu'une décision — celle de reprendre plus tard.
                interrompu = self.arret.is_set()
                self.journal(f"\n{'■' if interrompu else '✖'} {e}")
                with self.verrou:
                    self.etat = "interrompu" if interrompu else "echec"
                    self.message = str(e)
            except Exception as e:                       # noqa: BLE001
                # Un défaut de l'installateur lui-même. Il ne doit pas laisser
                # la page tourner indéfiniment sur « en cours » : la panne qu'on
                # ne voit pas est celle qu'on ne répare pas.
                self.journal(f"\n✖ défaut interne de l'installateur : "
                             f"{type(e).__name__} — {e}")
                with self.verrou:
                    self.etat, self.message = "echec", f"{type(e).__name__}: {e}"

        threading.Thread(target=tourner, daemon=True, name=etape).start()


TRAVAIL = Travail()


# ── Les étapes, telles que la page les demande ───────────────────────────────

def _node(journal) -> Path:
    trouve = outils.trouver_node()
    if not trouve:
        trouve = outils.installer_node(journal)
    return Path(trouve["chemin"])


def etape_outils(journal, arret) -> None:
    journal("Outils nécessaires :")
    journal(f"   Python {sys.version.split()[0]} — {sys.executable}")
    # Dire ce qu'on a TROUVÉ, et pas seulement ce qu'on installe : une étape
    # qui n'affiche rien quand tout va bien laisse croire qu'elle n'a rien fait.
    trouve = outils.trouver_node()
    if trouve:
        journal(f"   Node {trouve['version']} — {trouve['chemin']}")
    else:
        outils.installer_node(journal)
    for f in outils.facultatifs():
        if f["present"]:
            journal(f"   ✓ {f['nom']}")
        else:
            journal(f"   — {f['nom']} absent : {f['sans_lui']}")
            journal(f"     (pour l'ajouter plus tard : {f['poser']})")
    journal("\nAucun outil facultatif ne bloque l'installation.")


def etape_dependances(journal, arret) -> None:
    etapes.creer_venv(journal, sys.executable)
    etapes.installer_dependances_python(journal)
    etapes.installer_dependances_node(journal, _node(journal))


def etape_instance(reponses: dict):
    def faire(journal, arret) -> None:
        etapes.amorcer_instance(journal, reponses["insee"],
                                bool(reponses.get("ecraser")))
        etapes.completer_instance(journal, reponses)
        etapes.creer_base(journal)
    return faire


def etape_compte(reponses: dict):
    def faire(journal, arret) -> None:
        etapes.creer_env(journal)
        etapes.creer_compte(journal, reponses.get("email", ""),
                            reponses.get("motdepasse", ""))
    return faire


def etape_collecte(journal, arret) -> None:
    etapes.collecter(journal, arret)


def etape_publication(journal, arret) -> None:
    etapes.publier(journal, _node(journal))


def etape_atelier(journal, arret) -> None:
    etapes.construire_atelier(journal, _node(journal))
    etapes.ecrire_lanceurs(journal)


def etape_ouvrir(journal, arret) -> None:
    """Démarre l'atelier comme le fera le lanceur, et rend la main."""
    import subprocess
    journal("Démarrage de l'atelier…")
    subprocess.Popen([str(etapes.python_venv()), str(ICI / "lancer.py")],
                     cwd=str(RACINE))
    journal("   L'atelier s'ouvre dans un nouvel onglet — il peut mettre "
            "quelques secondes à répondre.")


ETAPES_SANS_DONNEES = {
    "outils": etape_outils,
    "dependances": etape_dependances,
    "collecte": etape_collecte,
    "publication": etape_publication,
    "atelier": etape_atelier,
    "ouvrir": etape_ouvrir,
}
ETAPES_AVEC_DONNEES = {"instance": etape_instance, "compte": etape_compte}


# ── Recherche de commune ─────────────────────────────────────────────────────

def chercher_commune(q: str) -> list[dict]:
    """Une commune se cherche par son nom, pas par son code INSEE.

    Personne ne connaît le code INSEE de sa commune, et le demander d'entrée
    est la première marche sur laquelle une installation s'arrête. La saisie
    accepte donc les deux, et c'est geo.api.gouv.fr — le référentiel que le
    moteur interroge de toute façon — qui tranche.
    """
    q = q.strip()
    if not q:
        return []
    champs = "nom,code,codesPostaux,population,departement,epci"
    if len(q) == 5 and q.upper().rstrip("AB").isdigit():
        # Cinq caractères, c'est un code INSEE OU un code postal — et personne
        # ne sait lequel il a sous les yeux. On interroge les deux : ne tenter
        # que le premier fait rendre « commune inconnue » à une saisie
        # parfaitement juste, ce qui arrête l'installation sur un malentendu.
        insee = _geo(f"{GEO}/communes/{urllib.parse.quote(q)}?fields={champs}")
        postal = _geo(f"{GEO}/communes?codePostal={urllib.parse.quote(q)}"
                      f"&fields={champs}") or []
        sortie = ([insee] if isinstance(insee, dict) else []) + list(postal)
    else:
        sortie = _geo(f"{GEO}/communes?nom={urllib.parse.quote(q)}&fields={champs}"
                      f"&boost=population&limit=12") or []
    vues, propres = set(), []
    for c in sortie:
        if not isinstance(c, dict) or c.get("code") in vues:
            continue
        vues.add(c.get("code"))
        propres.append({
            "code": c.get("code", ""), "nom": c.get("nom", ""),
            "cp": (c.get("codesPostaux") or [""])[0],
            "population": c.get("population"),
            "departement": (c.get("departement") or {}).get("nom", ""),
            "epci": (c.get("epci") or {}).get("nom", ""),
        })
    return propres[:12]


def _geo(url: str):
    if not url:
        return None
    requete = urllib.request.Request(
        url, headers={"User-Agent": "VigieCivique/installateur"})
    try:
        with urllib.request.urlopen(requete, timeout=15) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None


# ── Le serveur ───────────────────────────────────────────────────────────────

class Poignee(BaseHTTPRequestHandler):
    server_version = "VigieCivique-installateur"

    # Le journal par défaut écrit une ligne par requête sur la sortie d'erreur :
    # la page interroge le serveur chaque seconde, la fenêtre serait illisible.
    def log_message(self, *_args) -> None:
        return

    # ── contrôles d'entrée ───────────────────────────────────────────────────
    def _autorise(self) -> bool:
        hote = (self.headers.get("Host") or "").split(":")[0]
        if hote not in ("127.0.0.1", "localhost", "[::1]"):
            self._json({"erreur": "hôte refusé"}, 403)
            return False
        jeton = (self.headers.get("X-Jeton")
                 or urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                 .get("jeton", [""])[0])
        if not secrets.compare_digest(jeton, JETON):
            self._json({"erreur": "jeton absent ou faux — rouvrir l'adresse "
                                  "affichée dans la fenêtre de l'installateur"}, 403)
            return False
        return True

    def _json(self, charge: dict, code: int = 200) -> None:
        corps = json.dumps(charge, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corps)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corps)

    def _corps(self) -> dict:
        taille = int(self.headers.get("Content-Length") or 0)
        if taille > 1 << 20:
            raise Echec("requête trop grande")
        try:
            return json.loads(self.rfile.read(taille).decode("utf-8")) if taille else {}
        except ValueError:
            return {}

    # ── routes ───────────────────────────────────────────────────────────────
    def do_GET(self) -> None:                              # noqa: N802
        chemin = urllib.parse.urlparse(self.path).path
        parametres = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

        if chemin in ("/", "/index.html"):
            if not self._autorise():
                return
            page = (ICI / "assistant.html").read_text(encoding="utf-8")
            corps = page.replace("__JETON__", JETON).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(corps)))
            # Cette page ne charge rien de l'extérieur : aucune police, aucun
            # script, aucune image distante. La politique le dit et l'impose.
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                             "script-src 'self' 'unsafe-inline'; connect-src 'self'")
            self.end_headers()
            self.wfile.write(corps)
            return

        if not self._autorise():
            return

        if chemin == "/api/etat":
            self._json({"machine": {"systeme": outils.systeme(),
                                    "python": sys.version.split()[0],
                                    "racine": str(RACINE)},
                        "instance": etapes.etat_instance(),
                        "facultatifs": outils.facultatifs(),
                        "travail": TRAVAIL.depuis(10 ** 9)})
            return
        if chemin == "/api/journal":
            depuis = int((parametres.get("depuis") or ["0"])[0])
            self._json(TRAVAIL.depuis(depuis))
            return
        if chemin == "/api/communes":
            self._json({"communes": chercher_commune((parametres.get("q") or [""])[0])})
            return
        self._json({"erreur": "route inconnue"}, 404)

    def do_POST(self) -> None:                             # noqa: N802
        if not self._autorise():
            return
        chemin = urllib.parse.urlparse(self.path).path
        try:
            donnees = self._corps()
            if chemin == "/api/travail":
                etape = donnees.get("etape", "")
                if etape in ETAPES_SANS_DONNEES:
                    TRAVAIL.lancer(etape, ETAPES_SANS_DONNEES[etape])
                elif etape in ETAPES_AVEC_DONNEES:
                    TRAVAIL.lancer(etape, ETAPES_AVEC_DONNEES[etape](donnees))
                else:
                    raise Echec(f"étape inconnue : {etape}")
                self._json({"lance": etape})
                return
            if chemin == "/api/arreter":
                TRAVAIL.arret.set()
                self._json({"arret": True})
                return
            if chemin == "/api/quitter":
                self._json({"au_revoir": True})
                threading.Timer(0.5, lambda: self.server.shutdown()).start()
                return
        except Echec as e:
            self._json({"erreur": str(e)}, 400)
            return
        self._json({"erreur": "route inconnue"}, 404)


def servir() -> None:
    for port in PORTS:
        try:
            serveur = ThreadingHTTPServer(("127.0.0.1", port), Poignee)
            break
        except OSError:
            continue
    else:
        raise SystemExit(f"Aucun port libre entre {PORTS.start} et {PORTS.stop - 1}.")

    adresse = f"http://127.0.0.1:{port}/?jeton={JETON}"
    print("\n  ┌─ Vigie Civique — installation ─────────────────────────────┐")
    print("  │  L'installateur s'ouvre dans votre navigateur.             │")
    print("  │  Cette fenêtre doit rester ouverte pendant l'installation. │")
    print("  └────────────────────────────────────────────────────────────┘\n")
    print(f"  Si rien ne s'ouvre, copier cette adresse dans le navigateur :\n\n"
          f"    {adresse}\n", flush=True)   # flush : quand la sortie n'est pas
    # un terminal (journal, lanceur graphique), Python la garde en mémoire par
    # blocs — et l'adresse de secours n'apparaît qu'à la fermeture, c'est-à-dire
    # au moment exact où elle ne sert plus à rien.
    # Ouvrir le navigateur après le démarrage du serveur, sinon la première
    # requête arrive avant qu'il n'écoute et l'onglet affiche une erreur de
    # connexion que l'utilisateur prend pour une panne.
    threading.Timer(0.4, lambda: webbrowser.open(adresse)).start()
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        pass
    print("\n  Installateur fermé.")


if __name__ == "__main__":
    servir()
