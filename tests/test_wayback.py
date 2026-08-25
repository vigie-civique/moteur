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


# ── Une source injoignable n'est pas une source vide ────────────────────────
# Le 25/08/2026 sur Brassac, les 12 instantanés ont échoué (panne DNS) et le
# collecteur a conclu « aucun procès-verbal archivé trouvé » puis « ✓ terminé ».
# Sur une commune dont le site n'a jamais été refondu, ce zéro est le résultat
# ATTENDU : c'est ce qui rend le mensonge indétectable à la lecture du journal.


def test_index_injoignable_ne_se_lit_pas_comme_page_jamais_capturee(monkeypatch):
    def tombe(*a, **k):
        raise OSError("nodename nor servname provided, or not known")

    monkeypatch.setattr(wayback, "_get", tombe)

    with pytest.raises(wayback.SourceInterrompue, match="index de l'archive"):
        wayback.instantanes(PAGE)


def test_tous_les_instantanes_injoignables_leve(monkeypatch):
    monkeypatch.setattr(wayback, "instantanes",
                        lambda page, limite=0: ["20230530044423", "20240227175656"])
    monkeypatch.setattr(wayback.time, "sleep", lambda s: None)

    def tombe(*a, **k):
        raise OSError("nodename nor servname provided, or not known")

    monkeypatch.setattr(wayback, "_get", tombe)

    with pytest.raises(wayback.SourceInterrompue, match="injoignables"):
        wayback.documents(PAGE, "brassac.fr")


def test_instantane_partiel_rend_ce_qui_a_ete_lu_et_signale(monkeypatch):
    """Un échec sur deux : les PV lus sont rendus, l'incident est reporté.

    Lever ici perdrait les documents catalogués avant la panne. C'est
    l'appelant qui refuse le passage, une fois les séances écrites.
    """
    monkeypatch.setattr(wayback, "instantanes",
                        lambda page, limite=0: ["20190722114724", "20240227175656"])
    monkeypatch.setattr(wayback.time, "sleep", lambda s: None)

    def parfois(url, *a, **k):
        if "20240227175656" in url:
            raise OSError("connection reset by peer")
        return INSTANTANE.encode()

    monkeypatch.setattr(wayback, "_get", parfois)
    incidents: list[str] = []

    docs = wayback.documents(PAGE, "lasalle.fr", incidents=incidents)

    assert [d.date for d in docs] == ["2019-06-26", "2019-05-22"]
    assert incidents == ["20240227175656"]


def test_collecter_archives_refuse_de_conclure_sur_une_archive_non_lue(monkeypatch):
    """Le cas Brassac, bout en bout : rien lu, rien catalogué → pas de « ✓ ».

    C'est le seul endroit où le mensonge était visible pour l'exploitant, et
    c'est celui qui doit échouer. Le step remonte l'échec dans `collector_runs`
    au lieu d'y écrire `ok`.
    """
    pytest.importorskip("pdfplumber", reason="job « tests-deps »")
    from collectors import conseils

    monkeypatch.setattr(conseils, "COMMUNE_NAME", "Brassac", raising=False)
    monkeypatch.setattr("collectors.wayback.catalogue_archive",
                        lambda portee="commune", incidents=None:
                        (incidents.extend(["20230530044423", "20240227175656"]), [])[1])

    with pytest.raises(wayback.SourceInterrompue, match="n'a pas été lue"):
        conseils.collecter_archives("commune")


def test_collecter_archives_annonce_le_vide_quand_il_est_reel(monkeypatch, capsys):
    """Sans incident, zéro document reste une réponse légitime — et fréquente :
    un site jamais refondu n'a rien perdu (Saillans, 25/08/2026)."""
    pytest.importorskip("pdfplumber", reason="job « tests-deps »")
    from collectors import conseils

    monkeypatch.setattr("collectors.wayback.catalogue_archive",
                        lambda portee="commune", incidents=None: [])

    conseils.collecter_archives("commune")

    assert "aucun procès-verbal archivé trouvé" in capsys.readouterr().out
