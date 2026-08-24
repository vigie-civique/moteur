"""Une collecte tronquée ne doit pas se déclarer réussie.

Le 24/08/2026, le step `raa` d'une instance a lu 74 recueils sur 263 : la
préfecture ferme les connexions au bout de quelques dizaines de
téléchargements. Il s'est terminé sur « ✓ raa terminé » et une ligne `ok` dans
`collector_runs` — le seul endroit où l'on va voir si une source est morte.

Ces tests tiennent la distinction qui compte : un recueil RETIRÉ du site est
une lacune connue, la collecte reste complète ; une connexion COUPÉE ne dit
rien de ce qu'on n'a pas lu.
"""
from __future__ import annotations

import urllib.error

import pytest

from collectors import raa_prefecture as raa

URLS = ["https://prefecture.exemple.invalid/a.pdf",
        "https://prefecture.exemple.invalid/b.pdf",
        "https://prefecture.exemple.invalid/c.pdf"]


@pytest.fixture
def collecte(base, monkeypatch):
    """`run()` branché sur la base de test, sans réseau ni pause."""
    monkeypatch.setattr(raa, "get_conn", lambda *a, **k: base)
    monkeypatch.setattr(raa, "list_pdfs", lambda year: list(URLS))
    return base


def _scan(sorties: dict):
    """Fabrique un `scan_pdf` qui rend, ou lève, selon l'URL."""
    def scan_pdf(conn, url, dry_run=False):
        sortie = sorties[url]
        if isinstance(sortie, Exception):
            raise sortie
        return sortie
    return scan_pdf


def test_une_connexion_coupee_interrompt_le_step(collecte, monkeypatch, capsys):
    coupure = urllib.error.URLError("Remote end closed connection without response")
    monkeypatch.setattr(raa, "scan_pdf", _scan(
        {URLS[0]: 2, URLS[1]: coupure, URLS[2]: coupure}))

    with pytest.raises(raa.SourceInterrompue) as e:
        raa.run(2026, delay=0)

    assert "2 recueil(s) sur 3" in str(e.value)
    # Ce qui a été lu reste lu : l'exception ne défait rien.
    assert "1 recueils lus sur 3" in capsys.readouterr().out


def test_un_recueil_retire_du_site_nest_pas_une_interruption(collecte, monkeypatch,
                                                            capsys):
    """404 : on SAIT ce qui manque. La collecte, elle, est allée au bout."""
    absent = urllib.error.HTTPError(URLS[1], 404, "Not Found", {}, None)
    monkeypatch.setattr(raa, "scan_pdf", _scan(
        {URLS[0]: 1, URLS[1]: absent, URLS[2]: 0}))

    raa.run(2026, delay=0)

    sortie = capsys.readouterr().out
    assert "2 recueils lus sur 3" in sortie
    assert "1 retiré(s) du site" in sortie


def test_un_index_injoignable_nest_pas_une_collecte_vide(collecte, monkeypatch):
    """Sans l'index, on ne sait même pas ce qu'il y avait à lire."""
    def index_mort(year):
        raise urllib.error.URLError("timed out")
    monkeypatch.setattr(raa, "list_pdfs", index_mort)

    with pytest.raises(raa.SourceInterrompue, match="injoignable"):
        raa.run(2026, delay=0)


def test_une_collecte_complete_ne_leve_rien(collecte, monkeypatch, capsys):
    monkeypatch.setattr(raa, "scan_pdf", _scan(
        {URLS[0]: 1, URLS[1]: 0, URLS[2]: 3}))

    raa.run(2026, delay=0)

    sortie = capsys.readouterr().out
    assert "3 recueils lus sur 3, 2 avec mention" in sortie
    assert "sans réponse" not in sortie
