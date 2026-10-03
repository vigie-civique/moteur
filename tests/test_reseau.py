"""Les collecteurs ne parlent qu'à l'internet public — cf. collectors/reseau.py.

Sur un serveur, un collecteur qui suit l'adresse de site d'un acteur peut être
envoyé vers l'API de l'atelier, un service voisin ou les métadonnées de
l'hébergeur ; et ce qu'il lit est archivé, donc relisible dans l'atelier.

Aucun de ces tests ne sort sur le réseau : une adresse littérale et `localhost`
se résolvent sans DNS.
"""
from __future__ import annotations

import socket
import urllib.error
import urllib.request

import pytest

from collectors import reseau


@pytest.fixture
def garde():
    reseau.garder()
    yield
    reseau.relacher()


@pytest.mark.parametrize("adresse, attendu", [
    ("93.184.216.34", True), ("2606:2800:220:1:248:1893:25c8:1946", True),
    ("127.0.0.1", False), ("::1", False), ("10.0.0.5", False), ("192.168.1.10", False),
    ("172.20.10.3", False), ("169.254.169.254", False),      # métadonnées d'hébergeur
    ("100.64.0.1", False), ("0.0.0.0", False), ("fe80::1%eth0", False),
    ("::ffff:127.0.0.1", False),                              # boucle locale déguisée en IPv6
    ("pas-une-adresse", False),
])
def test_ce_qui_est_public(adresse, attendu):
    assert reseau.publique(adresse) is attendu


@pytest.mark.parametrize("hote", ["127.0.0.1", "localhost", "169.254.169.254", "10.0.0.5", "::1"])
def test_un_nom_interne_ne_se_resout_plus(garde, hote):
    with pytest.raises(reseau.AdresseInterdite):
        socket.getaddrinfo(hote, 80)


def test_une_adresse_publique_se_resout_toujours(garde):
    assert socket.getaddrinfo("93.184.216.34", 443, type=socket.SOCK_STREAM)[0][4][0] \
        == "93.184.216.34"


def test_urllib_ne_joint_plus_la_boucle_locale(garde):
    with pytest.raises(urllib.error.URLError) as refus:
        urllib.request.urlopen("http://127.0.0.1:8765/api/stats", timeout=2)
    assert "adresse publique" in str(refus.value)


def test_un_fichier_local_ne_se_lit_pas_comme_un_site(garde, tmp_path):
    secret = tmp_path / ".env"
    secret.write_text("JWT_SECRET=secret")
    with pytest.raises(urllib.error.URLError) as refus:
        urllib.request.urlopen(secret.as_uri())
    assert "file://" in str(refus.value)


def test_relacher_rend_le_reseau_local(tmp_path):
    reseau.garder()
    reseau.relacher()
    assert socket.getaddrinfo("127.0.0.1", 80)
    fichier = tmp_path / "a.txt"
    fichier.write_text("ok")
    assert urllib.request.urlopen(fichier.as_uri()).read() == b"ok"
