"""Le résolveur des citations d'actes : de quoi chaque phrase d'un dossier est faite.

Ce que ces tests protègent (03/10/2026) :
  - les citations telles que les dossiers les écrivent VRAIMENT (relevé sur
    l'instance d'origine) se relient sans qu'on les réécrive ;
  - trois issues seulement : précis, imprécis (la séance), non résolu ;
  - ⚖️ l'extraction n'est pas la publication : jamais un lien vers un acte
    que le site ne publie pas ;
  - rien de ce que le résolveur pose ne rouvre une brèche dans `markdownSur`.

Les actes vivent dans une vraie base au schéma réel ; l'index est construit
par les mêmes fonctions que le snapshot.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from collectors.citations import (ancre, index_de, index_selon_regles, lignes_en_base,
                                  relier)

FIXTURE = Path(__file__).parent / "fixtures" / "dossiers" / "eau.md"

ACTES = (
    # type, date, numéro, titre, texte, montants, source
    ("deliberation", "2021-04-14", "41", "Protection des captages : périmètres et servitudes",
     "Le conseil décide la protection à 80 % de la ressource en eau du captage.", [], "ex.invalid"),
    ("deliberation", "2021-04-14", "42", "Budget primitif 2021 du service de l'eau",
     "Budget équilibré à 61 500 €.", [{"montant": 61500.0}], "ex.invalid"),
    ("deliberation", "2022-05-11", "41", "Tarifs de l'eau", "Abonnement à 45 €.", [45.0], "ex.invalid"),
    ("deliberation_cc", "2025-04-02", "12", "Redevance pour pollution domestique",
     "Reversement de 2 064 € à l'Agence de l'eau.", [{"montant": 2064.0}], "epci.ex.invalid"),
    # Collecté, mais d'une source que les règles ne publient pas.
    ("deliberation", "2019-12-12", "7", "Rapport sur l'eau 2018", "Texte.", [], "source.privee"),
)
REGLES = {"events": {"public_sources": ["ex.invalid", "epci.ex.invalid"], "exclude_types": []}}


@pytest.fixture
def actes(base):
    for type_, date, num, titre, texte, montants, source in ACTES:
        base.execute("INSERT INTO events(type, date, title, content, source, source_url, metadata) "
                     "VALUES(?,?,?,?,?,?,?)",
                     (type_, date, titre, texte, source, f"https://{source}/{date}-{num}.pdf",
                      json.dumps({"numero_acte": num, "montants": montants})))
    base.execute("INSERT INTO events(type, date, title, source) VALUES('conseil_municipal', "
                 "'2021-04-14', 'Conseil municipal du 14 avril 2021', 'ex.invalid')")
    base.commit()
    return index_selon_regles(base, REGLES)


def _une(texte, index):
    r = relier(texte, index)
    assert len(r.citations) == 1, [c.releve() for c in r.citations]
    return r, r.citations[0]


# ── les citations naturelles ─────────────────────────────────────────────────

def test_une_citation_entre_parentheses_et_sa_phrase_en_guillemets(actes):
    """« (CM du 14/04/2021) » : la séance a pris deux actes, la phrase cite
    l'un d'eux mot pour mot — c'est lui."""
    r, c = _une("« protection à 80 % de la ressource » (CM du 14/04/2021)", actes)
    assert (c.resolution.statut, c.resolution.cible.cle) == ("precis", "c-2021-41")
    assert "([CM du 14/04/2021](/deliberations/2021#c-2021-41 " in r.texte


def test_un_montant_designe_l_acte_qui_l_a_vote(actes):
    r, c = _une("Budget de 61 500 € (CM du 14/04/2021).", actes)
    assert c.resolution.cible.cle == "c-2021-42"


def test_une_deliberation_communautaire(actes):
    _, c = _une("2 064 € de redevance à l'Agence de l'eau (délibération CC du 02/04/2025)", actes)
    assert (c.resolution.statut, c.resolution.cible.cle) == ("precis", "cc-2025-12")


def test_plusieurs_actes_et_rien_pour_choisir_mene_a_la_seance_signale_imprecis(actes):
    r, c = _une("Le CM du 14/04/2021 a tout voté.", actes)
    assert (c.resolution.statut, c.resolution.type, c.resolution.cible.cle) == \
        ("imprecis", "seance", "c-2021-04-14")
    assert set(c.resolution.candidats) == {"c-2021-41", "c-2021-42"}
    assert "renvoi imprécis" in r.texte


def test_aucune_correspondance_aucun_lien(actes):
    r, c = _une("27 980 € en 2022 (compte administratif, CM du 06/03/2023)", actes)
    assert c.resolution.statut == "non_resolu"
    assert r.texte == "27 980 € en 2022 (compte administratif, CM du 06/03/2023)"


def test_jamais_de_lien_vers_un_acte_non_publie(actes):
    """L'acte existe en base, mais sa source n'est pas publiée : la citation
    n'est PAS résolue, même explicite."""
    r = relier("Le rapport (CM du 12/12/2019) et [le même](acte:c-2019-7).", actes)
    assert [c.resolution.statut for c in r.citations] == ["non_resolu", "non_resolu"]
    assert "/deliberations/2019" not in r.texte
    assert "[le même]" not in r.texte and "le même" in r.texte, "le lien tombe, le texte reste"


def test_le_meme_numero_une_autre_annee(actes):
    _, c = _une("Le tarif a été revu par la délibération n°41/2022.", actes)
    assert c.resolution.cible.cle == "c-2022-41"


def test_une_ligne_de_frise(actes):
    r, c = _une("| 14/04/2021 | Protection des captages : périmètres | CM |", actes)
    assert (c.forme, c.resolution.cible.cle) == ("frise", "c-2021-41")
    assert r.texte.startswith("| [14/04/2021](/deliberations/2021#c-2021-41 ")


def test_l_en_tete_et_le_separateur_d_un_tableau_ne_sont_pas_des_citations(actes):
    assert relier("| Date | Acte | Assemblée |\n|------|------|----|\n", actes).citations == []


def test_une_date_seule_n_est_pas_une_citation(actes):
    assert relier("Le syndicat existe depuis le 14/04/2021.", actes).citations == []


# ── la syntaxe explicite ─────────────────────────────────────────────────────

def test_la_syntaxe_explicite_leve_l_ambiguite(actes):
    r = relier("Son [budget](acte:c-2021-42), sa [séance](seance:c-2021-04-14), "
               "sa [pièce](piece:c-2021-42).", actes)
    assert [(c.resolution.statut, c.resolution.type) for c in r.citations] == \
        [("precis", "acte"), ("precis", "seance"), ("precis", "piece")]
    assert "[budget](/deliberations/2021#c-2021-42 " in r.texte
    assert "[pièce](https://ex.invalid/2021-04-14-42.pdf " in r.texte
    assert "acte:" not in r.texte and "seance:" not in r.texte and "piece:" not in r.texte


# ── ce qu'on ne touche pas ───────────────────────────────────────────────────

def test_ni_les_titres_ni_les_liens_ni_le_code(actes):
    texte = ("## Le CM du 14/04/2021\n\n"
             "[CM du 14/04/2021](https://ex.invalid/pv.pdf)\n\n"
             "`CM du 14/04/2021`\n\n```\nCM du 14/04/2021\n```\n")
    r = relier(texte, actes)
    assert r.texte == texte and r.citations == []


def test_l_en_tete_du_dossier_est_rendu_intact(actes):
    texte = "---\ntitre: L'eau (CM du 14/04/2021)\n---\n\nTexte.\n"
    assert relier(texte, actes).texte == texte


def test_l_infobulle_ne_sort_pas_de_son_attribut(base):
    """Un titre d'acte peut contenir des guillemets : le lien posé ne doit pas
    permettre d'en sortir (le reste est échappé par marked, cf.
    public/scripts/verifier_markdown.mjs)."""
    base.execute("INSERT INTO events(type, date, title, source, metadata) VALUES('deliberation', "
                 "'2021-04-14', 'Titre \"piégé\" \\ ) ](x)', 'ex.invalid', '{\"numero_acte\": \"9\"}')")
    r = relier("Voir [ici](acte:c-2021-9).", index_selon_regles(base, REGLES))
    [c] = r.citations
    lien = r.texte[len("Voir "):-1]
    assert lien.count('"') == 2, lien
    assert '\\' not in lien


# ── l'index ──────────────────────────────────────────────────────────────────

def test_l_index_du_snapshot_ne_prend_que_les_identifiants_publies(base, actes):
    lignes = lignes_en_base(base)
    publies = {l["id"] for l in lignes if l["date"] == "2025-04-02"}
    index = index_de(lignes, publies)
    assert set(index.par_cle) == {"cc-2025-12"}


def test_deux_actes_publies_sous_la_meme_cle_ne_sont_la_cible_d_aucun_lien(base):
    for d in ("2021-04-14", "2021-06-01"):
        base.execute("INSERT INTO events(type, date, title, source, metadata) VALUES("
                     "'deliberation', ?, 'x', 'ex.invalid', '{\"numero_acte\": \"5\"}')", (d,))
    index = index_selon_regles(base, REGLES)
    assert "c-2021-5" in index.collisions
    [c] = relier("[x](acte:c-2021-5)", index).citations
    assert c.resolution.statut == "non_resolu"


def test_un_acte_ecarte_a_l_atelier_n_est_pas_publiable(base, actes):
    eid = base.execute("SELECT id FROM events WHERE title LIKE 'Tarifs%'").fetchone()[0]
    base.execute("INSERT INTO annotations(object_type, object_id, review_status) "
                 "VALUES('deliberation', ?, 'ecarte')", (eid,))
    assert index_selon_regles(base, REGLES).acte("c-2022-41") is None


# ── l'ancre d'une partie ─────────────────────────────────────────────────────

@pytest.mark.parametrize("titre,attendu", [
    ("Ce qu'on ne sait pas", "ce-qu-on-ne-sait-pas"),
    ("Ce qu’on ne sait pas", "ce-qu-on-ne-sait-pas"),
    ("L'essentiel", "l-essentiel"),
    ("Le prix de l'**eau** en 2024", "le-prix-de-l-eau-en-2024"),
    ("Œuvres", "uvres"),
])
def test_l_ancre_est_celle_du_site(titre, attendu):
    """Le site calcule l'ancre en JavaScript (dossiers.server.js::ancre) :
    NFD, diacritiques retirés, le reste en tirets."""
    assert ancre(titre) == attendu


def test_le_dossier_d_epreuve_se_relie_comme_attendu(actes):
    r = relier(FIXTURE.read_text(encoding="utf-8"), actes)
    statuts = {(c.texte, c.resolution.statut) for c in r.citations}
    assert ("CM du 14/04/2021", "precis") in statuts
    assert ("CM du 14/04/2021", "imprecis") in statuts
    assert ("CM du 12/12/2019", "non_resolu") in statuts
    assert {c.section for c in r.citations} >= {"L'essentiel", "Qui décide", "La frise"}
