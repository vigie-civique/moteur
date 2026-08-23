#!/usr/bin/env python3
"""Sert un build statique du site public, comme l'hébergeur le sert.

Pourquoi pas `vite dev`
-----------------------
L'aperçu de l'atelier montrait le serveur de DÉVELOPPEMENT : rendu à la volée,
modules non groupés, aucun prérendu. Or ce qui part en ligne est un build
statique — 1 449 pages écrites sur disque par `adapter-static`. C'est
précisément là que les défauts restants se logent : une page qui rend bien en
dev et se retrouve vide dans le HTML livré, un lien qui ne résout pas une fois
les routes figées, un contenu chargé en `onMount` qu'aucun moteur de recherche
ne verra. Un aperçu qui ne montre pas l'artefact publiable ne préserve de rien.

Pourquoi pas `python3 -m http.server`
-------------------------------------
Parce qu'il répondrait 404 sur `/finances`. `adapter-static` écrit
`finances.html`, et les hébergeurs de sites statiques — Cloudflare Pages ici —
résolvent l'URL sans extension vers ce fichier. Un serveur naïf donnerait un
aperçu où presque aucun lien ne marche, ce qui ferait chercher des défauts
inexistants dans le site.

Ce serveur applique donc les mêmes règles de résolution que l'hébergeur, et
rien de plus :

    /finances     → finances.html, sinon finances/index.html
    /             → index.html
    inconnu       → 404.html, avec un vrai code 404

Usage
-----
    python3 scripts/servir_apercu.py <répertoire> [--port 5180]
"""
from __future__ import annotations

import argparse
import functools
import http.server
import socketserver
import sys
from pathlib import Path


class Handler(http.server.SimpleHTTPRequestHandler):
    """Résolution d'URL d'un hébergeur statique, et rien de plus."""

    def translate_path(self, path: str) -> str:
        """`/finances` → `finances.html`, dans CET ordre.

        L'ordre n'est pas un détail : `adapter-static` écrit à la fois
        `finances.html` (la page) et `finances/__data.json` (ses données pour la
        navigation côté client). Un serveur qui regarde le répertoire d'abord
        trouve `finances/`, n'y voit pas d'`index.html`, et sert un listing de
        répertoire de 321 octets à la place d'une page de 60 Ko. L'aperçu
        montrait alors un site dont presque aucune page n'existait, ce qui
        ferait chercher des défauts inexistants dans le site.
        """
        chemin = super().translate_path(path)
        p = Path(chemin)
        if p.is_file():
            return chemin
        if not p.suffix:
            avec_html = p.with_suffix(".html") if p.name else None
            if avec_html and avec_html.is_file():
                return str(avec_html)
        index = p / "index.html"
        if index.is_file():
            return str(index)
        return chemin

    def list_directory(self, path):
        """Jamais de listing : un hébergeur statique n'en sert pas.

        En servir un donnerait un aperçu qui ne ressemble pas au site, et
        exposerait l'arborescence du build à qui atteint le port.
        """
        self.send_error(404)
        return None

    def send_error(self, code, message=None, explain=None):
        """La page 404 du site, pas celle du serveur.

        Un aperçu qui montre la page d'erreur de Python à la place de celle du
        site laisse croire à une panne du serveur là où il n'y a qu'un lien
        mort — et cache la vraie page 404, qui est du contenu comme un autre.
        """
        if code == 404:
            page = Path(self.directory) / "404.html"
            if page.is_file():
                corps = page.read_bytes()
                self.send_response(404)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(corps)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(corps)
                return
        super().send_error(code, message, explain)

    def log_message(self, fmt, *args):
        # Le journal part dans le fichier de l'atelier ; une ligne par requête
        # sur 1 449 pages le rendrait illisible. Seules les erreurs comptent.
        if args and str(args[1] if len(args) > 1 else "").startswith(("4", "5")):
            super().log_message(fmt, *args)


class Serveur(socketserver.TCPServer):
    # Redémarrer l'aperçu ne doit pas buter sur un TIME_WAIT.
    allow_reuse_address = True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repertoire", type=Path)
    ap.add_argument("--port", type=int, default=5180)
    args = ap.parse_args(argv)

    if not (args.repertoire / "index.html").is_file():
        print(f"Rien à servir : {args.repertoire}/index.html est absent.",
              file=sys.stderr)
        return 2

    handler = functools.partial(Handler, directory=str(args.repertoire.resolve()))
    with Serveur(("127.0.0.1", args.port), handler) as httpd:
        print(f"Aperçu servi sur http://localhost:{args.port} "
              f"depuis {args.repertoire}", flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
