"""Une convocation annonce une séance ; elle ne rapporte aucune délibération.

Relevé le 01/10/2026 sur la CC de Lasalle : lue comme un procès-verbal, chaque
convocation fabriquait des « délibérations » avec ses lignes en capitales
(« MERCREDI 23 SEPTEMBRE 2026 », « A LA SALLE DES FETES ») — 13 fiches sur 6
séances —, et quatre séances lues après leur PV annonçaient « 2 délibérations »
et aucun présent. Ce qu'on en garde désormais : l'heure, le lieu, l'ordre du
jour, la date d'envoi — ce qui permet d'annoncer le conseil.

Les textes ci-dessous reprennent ce que l'OCR rend vraiment : numéros perdus,
pied de page intercalé, débris isolés, en-tête défiguré.
"""
from __future__ import annotations

import json

import pytest

from collectors.convocation import est_convocation, lire

CONVOCATION = """\
Gimei®
j fertey Solidaires L'Espérou, le 15 septembre 2026.
Causse Bégon TT
Lasalle
Objet: Convocation Conseil Communautaire
J'ai l'honneur de vous convier à assister à la réunion du Conseil Communautaire qui aura lieu le :
MERCREDI 23 SEPTEMBRE 2026
A9H30
A SAUMANE
A LA SALLE DES FETES
Ordre du jour :
1. Rencontre avec les services de la Caisse d'Allocations Familiales (CAF) pour présentation de la
Convention Territoriale Globale (CTG) ;
Approbation du procès-verbal de réunion du conseil du 09/07/26 ;
FPIC (Fonds national de Péréquation des ressources Intercommunales et Communales) 2026 ;
8. Modification du règlement intérieur des déchetteries communautaires ;
)D
EROD
Communauté de Communes Causses Aigoual Cévennes - Terres Solidaires
L'Espérou - 83 Avenue Georges Fabre
30570 Val-d'Aigoual
Tél : 04.67.82.73.79
c.c@cac-ts.com
10. Création d'un GR de Pays ;
RTUGIES u mmu
16. Décisions du Président ;
17. Questions diverses.
Dans l'attente, veuillez agréer, Madame, Monsieur, l'expression de mes sentiments les meilleurs.
"""


def test_la_convocation_annonce_quand_ou_et_quoi():
    c = lire(CONVOCATION)
    assert (c["convoque_le"], c["heure"], c["lieu"]) == ("2026-09-15", "9 h 30",
                                                         "Saumane, la salle des fetes")
    assert c["ordre_du_jour"] == [
        "Rencontre avec les services de la Caisse d'Allocations Familiales (CAF) pour "
        "présentation de la Convention Territoriale Globale (CTG)",
        "Approbation du procès-verbal de réunion du conseil du 09/07/26",
        "FPIC (Fonds national de Péréquation des ressources Intercommunales et Communales) 2026",
        "Modification du règlement intérieur des déchetteries communautaires",
        "Création d'un GR de Pays",
        "Décisions du Président",
        "Questions diverses",
    ], "ni pied de page, ni débris, ni point coupé en deux"


def test_un_ordre_du_jour_sans_entete_et_clos_par_des_points():
    """La convocation du 16/04 n'a pas de ligne « Ordre du jour » ; celle du
    04/03 clôt ses points par « . » au lieu de « ; », et l'OCR mange un numéro."""
    texte = ("qui aura lieu le :\nJEUDI 16 AVRIL 2026\nA14H\nA L'ESPEROU\n"
             "1. Election du président ;\n2. Lecture de la charte de l'élu local.\n"
             ". Taxe GEMAPI 2026.\nDans l'attente, veuillez agréer…")
    c = lire(texte)
    assert c["heure"] == "14 h" and c["lieu"] == "L'Esperou"
    assert c["ordre_du_jour"] == ["Election du président", "Lecture de la charte de l'élu local",
                                  "Taxe GEMAPI 2026"]


def test_un_entete_defigure_par_locr_est_reconnu():
    texte = "Orddu jrouer :\nApprobation du procès-verbal du 30/04/26 ;\nQuestions diverses."
    assert lire(texte)["ordre_du_jour"] == ["Approbation du procès-verbal du 30/04/26",
                                            "Questions diverses"]


def test_une_piece_nommee_convocation_qui_porte_des_votes_est_lue_comme_un_pv():
    assert est_convocation("convocation", CONVOCATION)
    assert not est_convocation("convocation", "Après en avoir délibéré à l'unanimité, APPROUVE")
    assert not est_convocation("proces_verbal", CONVOCATION)


# ── dans le collecteur ───────────────────────────────────────────────────────

pdfplumber = pytest.importorskip("pdfplumber",
                                 reason="job « tests-deps » : pip install -r requirements.txt")
from collectors import conseils  # noqa: E402
from collectors.connecteurs.base import DocumentPublie  # noqa: E402

URL = "https://cc.invalid/Convocation-Conseil-du-23-septembre-2026.pdf"


def _doc(url, libelle):
    return DocumentPublie(date="2026-09-23", url=url, libelle=libelle, source="cc.invalid")


def test_la_convocation_garde_ce_que_le_pv_a_etabli_et_retire_ce_quelle_a_fabrique(base):
    pv = _doc("https://cc.invalid/PV-du-23.09.2026.pdf", "PV du 23.09.2026")
    sid = conseils.enregistrer_seance(base, pv, "epci",
                                      {"nb_deliberations": 16, "presents": ["ABRIC", "BALSAN"]})
    convoc = _doc(URL, "Convocation-Conseil-du-23-septembre-2026")
    # Ce que l'ancienne lecture avait fabriqué : deux « délibérations », dont
    # une qu'un humain a annotée — celle-là ne part pas en silence.
    fab = [conseils.enregistrer_deliberation(base, convoc, "epci",
                                             {"titre": t, "texte": t, "regime": "capitales", "categorie": None,
                                              "tags": [], "vote": None, "montants": [],
                                              "numero_seance": None, "numero_acte": None})
           for t in ("MERCREDI 23 SEPTEMBRE 2026", "A LA SALLE DES FETES")]
    base.execute("INSERT INTO annotations(object_type, object_id, review_status) "
                 "VALUES('deliberation', ?, 'a_revoir')", (fab[1],))

    r = conseils.traiter_convocation(base, convoc, "epci", CONVOCATION, verbose=False)

    meta = json.loads(base.execute("SELECT metadata FROM events WHERE id=?", (sid,)).fetchone()[0])
    assert (meta["nb_deliberations"], meta["presents"]) == (16, ["ABRIC", "BALSAN"])
    assert meta["libelle_source"] == "PV du 23.09.2026", "la convocation ne prend pas la place du PV"
    assert meta["convocation"]["heure"] == "9 h 30" and len(meta["convocation"]["ordre_du_jour"]) == 7
    assert meta["convocation"]["url"] == URL
    assert {p["nature"] for p in meta["pieces"]} == {"proces_verbal", "convocation"}
    restantes = [r[0] for r in base.execute("SELECT id FROM events WHERE source_url=?", (URL,))]
    assert (r["retirees"], restantes) == (1, [fab[1]])


def test_une_convocation_lue_avant_la_seance_la_cree_et_lannonce(base):
    conseils.traiter_convocation(base, _doc(URL, "Convocation Conseil du 23 septembre 2026"),
                                 "epci", CONVOCATION, verbose=False)
    row = base.execute("SELECT title, metadata FROM events WHERE type='conseil_communautaire'").fetchone()
    meta = json.loads(row[1])
    assert row[0] == "Conseil communautaire du 23 septembre 2026"
    assert meta["convocation"]["lieu"] == "Saumane, la salle des fetes"
    assert base.execute("SELECT COUNT(*) FROM events WHERE type='deliberation_cc'").fetchone()[0] == 0


# ── à la publication ─────────────────────────────────────────────────────────

def test_la_convocation_publique_ne_garde_que_ce_qui_sort():
    from collections import Counter
    from scripts.build_public_snapshot import convocation_publique
    c = convocation_publique({"heure": "9 h 30", "lieu": "Saumane", "url": "javascript:alert(1)",
                              "ordre_du_jour": ["FPIC 2026"], "inconnu": "x"},
                             "2026-09-23", set(), Counter())
    assert c == {"heure": "9 h 30", "lieu": "Saumane", "ordre_du_jour": ["FPIC 2026"]}
