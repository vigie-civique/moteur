#!/usr/bin/env python3
"""lancer.py — ouvrir l'atelier, sans rien taper.

C'est ce que le fichier à double-cliquer appelle. Il tient en trois gestes :
démarrer l'API, attendre qu'elle réponde, ouvrir le navigateur dessus.

Une seule adresse, un seul port. L'atelier construit (`dashboard/dist`) est
servi par l'API elle-même : il n'y a plus ni serveur de développement, ni proxy,
ni seconde fenêtre. C'est la panne la plus fréquente du dispositif qui
disparaît — « Serveur inaccessible » affiché par une interface qui tourne très
bien mais n'atteint pas son API.

Ce fichier tourne dans le venv de l'instance (le lanceur l'appelle par
`venv/bin/python3`), donc uvicorn est là.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("VIGIE_PORT_ATELIER", "8765"))
ADRESSE = f"http://127.0.0.1:{PORT}/"


def repond() -> bool:
    """L'API répond-elle ? 401 est une bonne réponse — la route existe et
    refuse sans jeton. C'est même la seule preuve que le verrou est en place."""
    try:
        urllib.request.urlopen(f"{ADRESSE}api/stats", timeout=2)
        return True
    except urllib.error.HTTPError:
        return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def occupe() -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def main() -> int:
    if not (RACINE / ".env").exists():
        print("✖ .env absent : l'API refuserait de démarrer faute de secret de\n"
              "  session. Relancer l'installateur, étape « compte ».")
        input("\n  Entrée pour fermer. ")
        return 1

    if occupe():
        # L'atelier tourne déjà — deuxième double-clic, ou fenêtre oubliée.
        # Démarrer un second uvicorn échouerait sur le port, avec une trace
        # Python en travers de l'écran pour dire « tout va bien ».
        print("L'atelier est déjà ouvert : je rouvre simplement la page.")
        webbrowser.open(ADRESSE)
        return 0

    if not (RACINE / "dashboard" / "dist" / "index.html").exists():
        print("✖ L'atelier n'a pas été construit (dashboard/dist absent).\n"
              "  Relancer l'installateur, étape « atelier ».")
        input("\n  Entrée pour fermer. ")
        return 1

    print(f"  Démarrage de l'atelier sur {ADRESSE}")
    print("  ⚠ Garder cette fenêtre ouverte : la fermer arrête l'atelier.\n")
    api = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api:app",
         "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=str(RACINE),
        # C'est ce lanceur qui DEMANDE à l'API de servir l'atelier construit :
        # ailleurs, l'API ne le fait pas, même si `dashboard/dist` traîne sur le
        # disque depuis un vieux build.
        env={**os.environ, "VIGIE_ATELIER_STATIQUE": "1",
             "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})

    for _ in range(60):
        if repond():
            webbrowser.open(ADRESSE)
            break
        if api.poll() is not None:
            print("\n✖ L'API s'est arrêtée au démarrage. La cause est écrite\n"
                  "  juste au-dessus : le plus souvent, JWT_SECRET vide dans .env.")
            input("\n  Entrée pour fermer. ")
            return 1
        time.sleep(0.5)
    else:
        print("\n  L'API met un temps inhabituel à répondre — ouvrir "
              f"{ADRESSE} à la main.")

    try:
        return api.wait()
    except KeyboardInterrupt:
        api.terminate()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
