"""Les lacunes : ce qu'un dossier ne sait pas, sous un format qu'une file reprend.

Ce que ces tests protègent (03/10/2026) : deux sources — le tableau « Ce qu'on
ne sait pas » et les citations sans cible — sortent sous UN format ; l'identité
d'une lacune survit à une retouche de ponctuation et pas à une autre question.
"""
from __future__ import annotations

from pathlib import Path

from collectors.citations import Index, relier
from collectors.lacunes import citations, identifiant, questions

FIXTURE = (Path(__file__).parent / "fixtures" / "dossiers" / "eau.md").read_text(encoding="utf-8")

LIGNE_REELLE = ("| Le contrat du syndicat avec Veolia | **en partie** : dates et part de Veolia "
                "connues ; forme, conditions du renouvellement de 2025, avenants et rapports de "
                "Veolia inconnus | courrier au syndicat, puis demande à la CADA |")


def _dossier(*lignes):
    return ("## Ce qu’on ne sait pas\n\n| Question | Où on en est | Comment le savoir |\n"
            "|---|---|---|\n" + "\n".join(lignes) + "\n\n## Les mots du dossier\n\n| a | b |\n|--|--|\n| x | y |\n")


def test_une_ligne_reelle_du_tableau():
    [l] = questions("eau", _dossier(LIGNE_REELLE))
    assert l["question"] == "Le contrat du syndicat avec Veolia"
    assert (l["etat"], l["etat_libelle"]) == ("en_partie", "en partie")
    assert l["ou_on_en_est"].startswith("dates et part de Veolia connues")
    assert l["comment"] == "courrier au syndicat, puis demande à la CADA"
    assert (l["nature"], l["dossier"], l["ancre"]) == ("question", "eau", "ce-qu-on-ne-sait-pas")


def test_seul_le_tableau_de_la_section_compte():
    """L'en-tête, le séparateur, et le tableau d'une autre section ne sont pas
    des questions."""
    assert [l["question"] for l in questions("eau", _dossier(LIGNE_REELLE))] == \
        ["Le contrat du syndicat avec Veolia"]


def test_un_etat_absent_se_dit():
    [l] = questions("eau", _dossier("| Le budget annexe | rien n'est publié | demande |"))
    assert l["etat"] == "non_dit" and l["ou_on_en_est"] == "rien n'est publié"


def test_l_identite_survit_a_la_ponctuation_pas_a_une_autre_question():
    a = identifiant("eau", "question", "Le contrat du syndicat avec Veolia")
    assert a == identifiant("eau", "question", "Le contrat du syndicat, avec Veolia ?")
    assert a == identifiant("eau", "question", "le contrat du syndicat avec **Véolia**")
    assert a != identifiant("eau", "question", "Le contrat du syndicat avec la régie")
    assert a != identifiant("dechets", "question", "Le contrat du syndicat avec Veolia")


def test_l_etat_change_l_identite_reste():
    avant = questions("eau", _dossier(LIGNE_REELLE.replace("**en partie**", "**ouvert**")))
    apres = questions("eau", _dossier(LIGNE_REELLE))
    assert avant[0]["id"] == apres[0]["id"]
    assert (avant[0]["etat"], apres[0]["etat"]) == ("ouvert", "en_partie")


def test_une_citation_sans_cible_est_une_question_du_meme_format():
    r = relier(FIXTURE, Index([]))     # aucun acte publié : rien ne se résout
    ls = citations("eau", r.non_resolues)
    assert ls and all(l["nature"] == "citation" and l["etat"] == "ouvert" for l in ls)
    assert set(ls[0]) >= {"id", "dossier", "question", "etat", "ou_on_en_est", "comment",
                          "section", "ancre"}
    frises = [l["question"] for l in ls if l["citation"]["forme"] == "frise"]
    assert any("Motion pour le maintien du syndicat" in q for q in frises), \
        "une ligne de frise se pose avec ce qu'elle dit de l'acte"
    assert len({l["id"] for l in ls}) == len(ls)


def test_le_dossier_d_epreuve_declare_ses_deux_questions():
    assert [l["etat"] for l in questions("eau", FIXTURE)] == ["en_partie", "ouvert"]
