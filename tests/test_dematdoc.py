"""Portail d'actes DematDOC : catalogue, date de séance, écriture en base.

Aucun appel réseau : les réponses de l'API sont celles relevées le 24/08/2026
sur un portail réel, réduites à ce qui compte. Ce que ces tests protègent tient
en une phrase — un portail d'actes publie des DÉLIBÉRATIONS UNE PAR UNE, et la
date qu'il affiche n'est pas celle de la séance.
"""
from __future__ import annotations

import json

import pytest

# `collectors.conseils` lit des PDF, donc importe pdfplumber, que le job
# « tests » de la CI n'installe pas — il n'installe que pytest, pour démontrer
# que le cœur du moteur se teste sans réseau ni collecteur. Ce fichier y est
# donc SAUTÉ, et joué par le job « tests-deps », qui refuse le moindre test
# sauté. Même convention que `tests/test_api_saisie.py` pour fastapi.
pytest.importorskip("pdfplumber",
                    reason="job « tests-deps » : pip install -r requirements.txt")

from collectors import conseils  # noqa: E402
from collectors.connecteurs import charger  # noqa: E402
from collectors.connecteurs.base import DocumentPublie  # noqa: E402
from collectors.connecteurs.dematdoc import ConnecteurDematDOC, champs  # noqa: E402
from collectors.pv_parsers import acte_unique, reference_actes  # noqa: E402

PORTAIL = "https://portail.exemple.invalid/public/14"

# Un acte tel que l'API le rend : les valeurs indexées sont enveloppées.
def _document(id_: int, numero: str, type_acte: str, objet: str,
              dateacte: str, chemin: str | None = "/repository/2026/07/P1.pdf"):
    return {
        "id": id_,
        "name": f"{type_acte} {numero} du {dateacte}",
        "path": chemin,
        "bifferPath": None,
        "values": {
            "TYPE_DACTE_ACTE": {"indexField": {"caption": "Type d'acte"},
                                "displayValue": type_acte},
            "NUMEROACTE": {"indexField": {"caption": "Numéro"},
                           "displayValue": numero},
            "OBJET": {"indexField": {"caption": "Objet"}, "displayValue": objet},
            "DATEACTE": {"indexField": {"caption": "Date"},
                         "displayValue": dateacte},
        },
    }


DOCUMENTS = [
    _document(1913, "DC2026032", "Décision du Président", "Demande de subvention",
              "2026-08-17"),
    _document(1833, "DE2026116BIS", "Délibération du conseil communautaire",
              "BUDGET SUPPLEMENTAIRE 2026", "2026-07-06"),
    _document(1801, "DE2026098", "Délibération du conseil communautaire",
              "CONVENTION DE PARTENARIAT", "2026-06-30"),
    _document(1799, "DE2026099", "Délibération du conseil communautaire",
              "Acte encore sans pièce", "2026-06-30", chemin=None),
]

# Le texte d'un acte, tel que pdftotext le rend : le tampon du contrôle de
# légalité en tête, puis l'en-tête de séance.
TEXTE_ACTE = """AR CONTROLE DE LEGALITE en date du 06/07/2026
026-209900019-20260625-DE2026116bis-BF
7.1 Décisions budgétaires

DELIBERATION DU CONSEIL COMMUNAUTAIRE
Séance du 25 juin 2026 à 18h00
Date de convocation : 18 juin 2026

Le 25 juin 2026, le Conseil Communautaire, régulièrement convoqué, s'est réuni
à la salle polyvalente en session ordinaire, sous la présidence du Président.

Présents : Camille ARMAGNAT, Dominique BLANCHOT, Claude ESCANDE

Le conseil communautaire, après en avoir délibéré, DECIDE d'adopter le budget
supplémentaire 2026 du budget annexe pour un montant de 128 400,00 €.
""" + "Considérant ce qui précède, le conseil approuve. " * 12


@pytest.fixture
def connecteur(monkeypatch):
    """Le connecteur, branché sur les réponses relevées plutôt que sur le réseau."""
    c = ConnecteurDematDOC()
    c.pages = {"epci": {"portail": PORTAIL}}
    monkeypatch.setattr(
        "collectors.connecteurs.dematdoc.Portail.documents",
        lambda self, doctype: DOCUMENTS if doctype == 14 else [])
    return c


# ── catalogue ────────────────────────────────────────────────────────────────

def test_champs_aplatit_les_valeurs_indexees():
    assert champs(DOCUMENTS[0])["NUMEROACTE"] == "DC2026032"
    assert champs({"values": None}) == {}


def test_catalogue_ne_retient_que_les_deliberations(connecteur, capsys):
    docs = connecteur.catalogue_pv("epci")

    numeros = [d.acte["numero"] for d in docs]
    assert numeros == ["DE2026116BIS", "DE2026098"], (
        "une décision du Président n'est pas une délibération, et un acte sans "
        "pièce jointe n'a pas de texte à lire")
    # Ce qui est écarté est dit, jamais tu.
    assert "1 acte(s) hors conseil" in capsys.readouterr().out


def test_catalogue_construit_url_et_acte(connecteur):
    doc = connecteur.catalogue_pv("epci")[0]

    assert doc.url == "https://portail.exemple.invalid/repository/2026/07/P1.pdf"
    assert doc.libelle == "BUDGET SUPPLEMENTAIRE 2026"
    assert doc.acte["type"] == "Délibération du conseil communautaire"
    assert doc.acte["portail"] == PORTAIL
    # La date du portail est transmise POUR CE QU'ELLE EST.
    assert doc.acte["date_teletransmission"] == "2026-07-06"


def test_catalogue_vide_sans_corbeille_declaree(connecteur, monkeypatch):
    """Choisir une corbeille à la place de l'exploitant serait deviner."""
    connecteur.pages = {"epci": {"portail": "https://portail.exemple.invalid"}}
    monkeypatch.setattr("collectors.connecteurs.dematdoc.Portail.corbeilles",
                        lambda self: [{"id": 14, "caption": "ACTES ComCom"}])

    assert connecteur.catalogue_pv("epci") == []


def test_connecteur_epci_distinct_de_celui_de_la_commune(monkeypatch):
    """Une commune et son intercommunalité peuvent publier sur deux outils."""
    monkeypatch.setattr("collectors.config.CONNECTEUR_EPCI", "dematdoc")
    monkeypatch.setattr("collectors.connecteurs._cache", {})

    assert charger(portee="epci").nom == "dematdoc"
    assert charger(portee="commune").nom != "dematdoc"


# ── la date ──────────────────────────────────────────────────────────────────

def test_reference_actes_donne_la_date_de_lacte():
    ref = reference_actes(TEXTE_ACTE)

    assert ref["date"] == "2026-06-25"          # et non le 06/07 du portail
    assert ref["siren"] == "209900019"
    assert ref["numero"] == "DE2026116bis"
    assert reference_actes("un texte sans référence") is None


def test_date_de_seance_prefere_la_reference_au_portail():
    doc = DocumentPublie(date="2026-07-06", url="u", acte={"numero": "DE2026116BIS"})

    date, provenance, controle = conseils.date_de_seance(TEXTE_ACTE, doc, "epci")

    assert date == "2026-06-25"
    assert provenance == "reference_actes"
    assert controle["reference_actes"].startswith("026-209900019-")


def test_date_de_seance_retombe_sur_len_tete_puis_sur_le_portail():
    doc = DocumentPublie(date="2026-07-06", url="u", acte={})
    sans_reference = TEXTE_ACTE.replace("026-209900019-20260625-DE2026116bis-BF", "")

    date, provenance, _ = conseils.date_de_seance(sans_reference, doc, "epci")
    assert (date, provenance) == ("2026-06-25", "entete")

    date, provenance, _ = conseils.date_de_seance("aucune date lisible", doc, "epci")
    assert (date, provenance) == ("2026-07-06", "teletransmission")


def test_siren_etranger_signale_sans_refuser_la_piece(capsys):
    """Un portail d'EPCI publie aussi les actes de son CCAS : le dire suffit."""
    doc = DocumentPublie(date="2026-07-06", url="u", acte={})
    autre = TEXTE_ACTE.replace("209900019", "200011111")

    _, _, controle = conseils.date_de_seance(autre, doc, "epci")

    assert controle["siren_inattendu"] == "200011111"
    assert "émetteur à vérifier" in capsys.readouterr().out


# ── écriture ─────────────────────────────────────────────────────────────────

def test_acte_unique_ne_decoupe_rien_et_le_dit():
    d = acte_unique("  BUDGET SUPPLEMENTAIRE 2026 ", TEXTE_ACTE, "DE2026116BIS")

    assert d["regime"] == "acte_seul"
    assert d["numero_acte"] == "DE2026116BIS"
    assert d["titre"] == "BUDGET SUPPLEMENTAIRE 2026"
    assert d["montants"], "l'enrichissement reste celui d'une délibération"


@pytest.fixture
def sans_reseau(monkeypatch):
    """`lire_document` rend le texte relevé, sans rien télécharger."""
    monkeypatch.setattr(conseils, "lire_document",
                        lambda doc, avec_ocr=False: (TEXTE_ACTE, "pdf", False))


def _acte(numero: str, date_portail: str) -> DocumentPublie:
    return DocumentPublie(
        date=date_portail,
        url=f"https://portail.exemple.invalid/repository/{numero}.pdf",
        libelle="BUDGET SUPPLEMENTAIRE 2026",
        source="portail.exemple.invalid",
        acte={"numero": numero, "objet": "BUDGET SUPPLEMENTAIRE 2026",
              "type": "Délibération du conseil communautaire",
              "date_teletransmission": date_portail, "portail": PORTAIL},
    )


def test_un_acte_donne_une_deliberation_datee_de_la_seance(base, sans_reseau):
    r = conseils.traiter_acte(base, _acte("DE2026116BIS", "2026-07-06"), "epci",
                              verbose=False)

    assert r == {"statut": "ok", "delibs": 1}
    delib = base.execute(
        "SELECT date, title, metadata FROM events WHERE type='deliberation_cc'"
    ).fetchone()
    assert delib["date"] == "2026-06-25"
    assert "BUDGET SUPPLEMENTAIRE" in delib["title"]
    meta = json.loads(delib["metadata"])
    assert meta["date_source"] == "reference_actes"
    assert meta["date_teletransmission"] == "2026-07-06"
    assert meta["type_acte"] == "Délibération du conseil communautaire"


def test_les_actes_dun_meme_jour_font_UNE_seance(base, sans_reseau):
    """Quarante actes déposés séparément ne sont pas quarante séances."""
    for numero in ("DE2026098", "DE2026099", "DE2026100"):
        conseils.traiter_acte(base, _acte(numero, "2026-06-30"), "epci",
                              verbose=False)

    seances = base.execute(
        "SELECT id, source_url, metadata FROM events WHERE type='conseil_communautaire'"
    ).fetchall()
    assert len(seances) == 1
    # La séance renvoie au portail, pas au premier acte arrivé.
    assert seances[0]["source_url"] == PORTAIL
    assert json.loads(seances[0]["metadata"])["nb_deliberations"] == 3
    assert base.execute(
        "SELECT COUNT(*) FROM events WHERE type='deliberation_cc'").fetchone()[0] == 3


def test_recollecter_le_meme_acte_ne_le_duplique_pas(base, sans_reseau):
    for _ in range(2):
        conseils.traiter_acte(base, _acte("DE2026116BIS", "2026-07-06"), "epci",
                              verbose=False)

    assert base.execute(
        "SELECT COUNT(*) FROM events WHERE type='deliberation_cc'").fetchone()[0] == 1


def test_une_piece_sans_couche_texte_nest_pas_enregistree(base, monkeypatch):
    """Mieux vaut une lacune signalée qu'une délibération vide qui passe pour lue."""
    monkeypatch.setattr(conseils, "lire_document",
                        lambda doc, avec_ocr=False: ("trop court", "pdf", False))

    r = conseils.traiter_acte(base, _acte("DE2026098", "2026-06-30"), "epci",
                              verbose=False)

    assert r == {"statut": "sans_couche_texte", "delibs": 0}
    assert base.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
