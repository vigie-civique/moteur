"""Les collecteurs ne parlent qu'à l'internet PUBLIC.

Un collecteur suit des adresses qu'il n'a pas choisies : le site d'un acteur
trouvé par une recherche, un lien relevé dans une page de mairie, une
redirection. Tant qu'il tourne sur le poste de celui qui tient l'instance, une
adresse interne ne mène nulle part d'intéressant. Sur un serveur, si : il y a
l'API de l'atelier sur la boucle locale, les services voisins, et le service de
métadonnées de l'hébergeur (`169.254.169.254`). Une adresse de site déclarée
`http://127.0.0.1:…/` serait lue par le collecteur, ARCHIVÉE comme un document
— donc relisible dans l'atelier par celui qui l'a déclarée.

Deux verrous, posés une fois au démarrage de la collecte (`garder()`) :

  * toute résolution de nom ne rend que des adresses publiques. Posé sur
    `socket.getaddrinfo`, par où passent urllib, requests et http.client : les
    cinquante-sept appels réseau des collecteurs sont couverts sans en modifier
    un seul, redirections comprises — chaque saut refait une résolution ;
  * `file://` et `ftp://` sont refusés par l'ouvreur d'urllib, qui les accepte
    par défaut : `file:///…/.env` passé pour l'adresse d'un site se lisait.

Ce module ne garde QUE le processus qui l'appelle. Un outil lancé en
sous-processus (`curl`, `ollama`, un navigateur piloté) n'est pas couvert.
"""
from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.request

_resolution_d_origine = socket.getaddrinfo


class AdresseInterdite(OSError):
    """Le nom demandé ne désigne aucune adresse publique."""


def publique(adresse: str) -> bool:
    """Vraie pour une adresse routable sur l'internet public — ni boucle locale,
    ni réseau privé, ni lien local (métadonnées d'hébergeur), ni réservée."""
    try:
        ip = ipaddress.ip_address(adresse.split("%", 1)[0])
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global


def _resoudre(hote, *args, **kwargs):
    resultats = _resolution_d_origine(hote, *args, **kwargs)
    publics = [r for r in resultats if publique(r[4][0])]
    if not publics:
        raise AdresseInterdite(
            f"« {hote} » ne désigne aucune adresse publique : un collecteur ne "
            f"lit pas le réseau interne de la machine qui le porte.")
    return publics


class _SansFichier(urllib.request.FileHandler):
    def file_open(self, req):
        raise urllib.error.URLError("file:// refusé : un collecteur lit le réseau, "
                                    "pas le disque de la machine qui le porte.")


class _SansFtp(urllib.request.FTPHandler):
    def ftp_open(self, req):
        raise urllib.error.URLError("ftp:// refusé : aucune source ne s'en sert.")


def garder() -> None:
    """Pose les deux verrous sur le processus courant. Sans effet si déjà posés."""
    if socket.getaddrinfo is not _resoudre:
        socket.getaddrinfo = _resoudre
    urllib.request.install_opener(urllib.request.build_opener(_SansFichier, _SansFtp))


def relacher() -> None:
    """Défait `garder()` — pour les essais, qui parlent à des serveurs locaux."""
    socket.getaddrinfo = _resolution_d_origine
    urllib.request.install_opener(None)
