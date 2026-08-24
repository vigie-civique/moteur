"""Reprendre dans l'archive du web les procès-verbaux que le site ne sert plus.

Aucun appel réseau : les fragments sont ceux d'un instantané réel, réduits.
Ce que ces tests tiennent : l'ÉDITEUR d'un PV archivé reste la commune — s'il
entrait sous « web.archive.org », l'allowlist de publication l'écarterait, et
trente séances retrouvées resteraient invisibles.
"""
from __future__ import annotations

import pytest

from collectors import wayback

# Un instantané tel que l'archive le réécrit : l'adresse d'origine se lit après
# l'horodatage. Le règlement intérieur est là pour être écarté.
INSTANTANE = """
<ul class="liste">
 <li><a href="https://web.archive.org/web/20190722114724/https://www.lasalle.fr/sites/default/files/medias/fichiers/cm%2026juin2019.pdf">CM du 26 juin</a></li>
 <li><a href="/web/20190722114724/https://www.lasalle.fr/sites/default/files/medias/fichiers/CM%2022%20mai%202019_0.pdf">CM du 22 mai</a></li>
 <li><a href="/web/20190722114724/https://www.lasalle.fr/sites/default/files/medias/fichiers/reglement-interieur.pdf">Règlement</a></li>
 <li><a href="/web/20190722114724/https://www.lasalle.fr/agendas">Agenda</a></li>
</ul>
"""

PAGE = "https://www.lasalle.fr/compte-rendus-des-conseils"


def test_liens_pdf_retient_ladresse_dorigine():
    liens = wayback.liens_pdf(INSTANTANE)

    assert set(liens) == {
        "https://www.lasalle.fr/sites/default/files/medias/fichiers/cm 26juin2019.pdf",
        "https://www.lasalle.fr/sites/default/files/medias/fichiers/CM 22 mai 2019_0.pdf",
        "https://www.lasalle.fr/sites/default/files/medias/fichiers/reglement-interieur.pdf",
    }
    assert all(ts == "20190722114724" for ts in liens.values())


def test_instantanes_ecarte_les_captures_derreur(monkeypatch):
    """Une capture 404 ne contient pas la liste des PV — l'ouvrir ne rend rien."""
    monkeypatch.setattr(wayback, "_get", lambda *a, **k: (
        b"20160324224050 200\n20170101000000 404\n20190722114724 200\n"))

    assert wayback.instantanes(PAGE) == ["20160324224050", "20190722114724"]


@pytest.fixture
def sans_reseau(monkeypatch):
    monkeypatch.setattr(wayback, "instantanes",
                        lambda page, limite=0: ["20190722114724"])
    monkeypatch.setattr(wayback, "_get", lambda *a, **k: INSTANTANE.encode())
    monkeypatch.setattr(wayback.time, "sleep", lambda s: None)


def test_documents_ne_retient_que_les_pv_datés(sans_reseau, capsys):
    docs = wayback.documents(PAGE, "lasalle.fr")

    assert [d.date for d in docs] == ["2019-06-26", "2019-05-22"]
    assert "reglement" not in capsys.readouterr().out


def test_ladresse_est_celle_du_rejeu_et_lediteur_la_commune(sans_reseau):
    doc = wayback.documents(PAGE, "lasalle.fr")[0]

    assert doc.url.startswith("https://web.archive.org/web/20190722114724id_/")
    assert doc.url.endswith("cm 26juin2019.pdf")
    # Le PV a été publié par la mairie ; l'archive n'est que le chemin.
    assert doc.source == "lasalle.fr"
    assert doc.meta["archive"] == "web.archive.org"
    assert doc.meta["url_origine"].startswith("https://www.lasalle.fr/")


def test_une_seance_par_date(sans_reseau, monkeypatch):
    """« CM 22 mai 2019.pdf » et « CM 22 mai 2019_0.pdf » sont la même séance."""
    doublon = INSTANTANE.replace("CM%2022%20mai%202019_0.pdf",
                                 "CM%2022%20mai%202019.pdf")
    monkeypatch.setattr(wayback, "_get",
                        lambda *a, **k: (INSTANTANE + doublon).encode())

    docs = wayback.documents(PAGE, "lasalle.fr")

    assert [d.date for d in docs] == ["2019-06-26", "2019-05-22"]


def test_document_archive_lit_lediteur_dans_ladresse_de_rejeu():
    url = ("https://web.archive.org/web/20211229003601id_/"
           "https://www.lasalle.fr/sites/default/files/medias/fichiers/cm%2015fev2017.pdf")

    doc = wayback.document_archive(url, "2017-02-15")

    assert doc.source == "lasalle.fr", (
        "sous « web.archive.org », l'allowlist de publication écarte la séance")
    assert doc.meta["archive_horodatage"] == "20211229003601"
    assert doc.libelle == "cm 15fev2017.pdf"


def test_document_archive_ne_deforme_pas_une_adresse_ordinaire():
    assert wayback.document_archive("https://www.lasalle.fr/cm.pdf", "2026-01-01") is None


def test_catalogue_utilise_la_page_que_le_connecteur_lit_deja(monkeypatch, sans_reseau):
    """Rien de plus à déclarer : c'est cette page-là que l'archive a capturée."""
    monkeypatch.setattr(wayback, "PAGES",
                        {"commune": {"conseil": "/compte-rendus-des-conseils"}})
    monkeypatch.setattr(wayback, "COMMUNE_URL", "https://www.lasalle.fr")

    docs = wayback.catalogue_archive("commune")

    assert [d.date for d in docs] == ["2019-06-26", "2019-05-22"]
    assert all(d.source == "lasalle.fr" for d in docs)
