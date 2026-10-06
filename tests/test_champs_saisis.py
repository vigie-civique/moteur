"""Un champ court saisi ou extrait passe par le masque, comme le titre d'un acte.

L'objet d'un marché, la citation d'un plan de financement, la note d'un budget
voté, la précision d'un lien : du texte écrit par un acheteur, lu dans un
procès-verbal ou tapé à l'atelier, qui sortait tel qu'il était en base.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict

from scripts.snapshot.argent import etape_finances
from scripts.snapshot.relations import relation_meta_publique
from scripts.snapshot.textes import CHAMP_RETIRE, champ_publiable

PIEGE = "Réfection du mur de M. Gaston PIEGEMUR, né le 05/03/1961, demeurant 5 rue des Lilas"


def test_un_champ_garde_le_nom_et_perd_naissance_et_domicile():
    sortie = champ_publiable(PIEGE, "2026-01-10", set())
    assert "PIEGEMUR" in sortie
    assert "1961" not in sortie and "Lilas" not in sortie


def test_ce_que_le_masque_ne_sait_pas_ecrire_est_retire():
    # « né » puis une année du siècle dernier, sous une forme que le masque ne
    # connaît pas : le filet la voit, le champ ne sort pas.
    assert champ_publiable("M. PIEGEMUR né un matin de 1961", None, set()) == CHAMP_RETIRE


def test_un_champ_vide_ou_chiffre_reste_ce_quil_est():
    assert champ_publiable(None, None, set()) is None
    assert champ_publiable("", None, set()) == ""
    assert champ_publiable(1200, None, set()) == 1200


def test_la_precision_dun_lien_est_masquee():
    brut = json.dumps({"role": "responsable", "precision": PIEGE, "birth_year": 1961})
    sortie = relation_meta_publique(brut, set())
    assert sortie["role"] == "responsable"
    assert "1961" not in json.dumps(sortie) and "Lilas" not in sortie["precision"]


def _finances(base):
    exclusions = defaultdict(Counter)
    return etape_finances(base, {}, set(), [], {}, set(), exclusions)


def test_marches_approbations_et_budget_vote_sortent_masques_avec_leur_confiance(base):
    base.execute(
        "INSERT INTO marches_publics (acheteur_siren, acheteur_nom, titulaire_nom, objet,"
        " montant, date_notif, lieu_exec, source, confidence) VALUES ('219900010',"
        " 'Testonville', 'Maçonnerie d''épreuve', ?, 9000, '2026-03-01',"
        " 'chez M. PIEGEMUR, domicilié 5 rue des Lilas', 'DECP', 'verified')", (PIEGE,))
    base.execute(
        "INSERT INTO approbations_projets (date, objet, montant_ht, citation, source,"
        " confidence) VALUES ('2026-02-01', ?, 1000, ?, 'CM', 'verified')", (PIEGE, PIEGE))
    base.execute(
        "INSERT INTO budget_vote (year, agregat, value, note, source) VALUES"
        " (2026, 'fonctionnement', 1000, ?, 'CM')", (PIEGE,))
    base.commit()
    faits = _finances(base)
    publie = json.dumps([faits["marches_data"], faits["approbations_data"],
                         faits["budget_vote"]], ensure_ascii=False)
    assert "1961" not in publie and "Lilas" not in publie
    assert faits["marches_data"][0]["confidence"] == "verified"
    assert faits["approbations_data"][0]["confidence"] == "verified"


# ── Ce qui sort tel que relu : refusé, jamais masqué ─────────────────────────

from scripts.snapshot.textes import porte_une_donnee_personnelle  # noqa: E402


def test_un_texte_relu_qui_porte_naissance_ou_domicile_est_reconnu():
    assert porte_une_donnee_personnelle(
        "M. Gaston PIEGEDOSSIER, né le 05/03/1961, domicilié 5 rue des Lilas")
    assert porte_une_donnee_personnelle("Mme PIEGEDOSSIER demeurant à Testonville, 5 rue des Lilas")
    assert porte_une_donnee_personnelle("M. PIEGEDOSSIER né un matin de 1961")


def test_un_dossier_ordinaire_nest_pas_refuse():
    assert not porte_une_donnee_personnelle(None)
    assert not porte_une_donnee_personnelle(
        "Le service de l'eau est né en 2017 du transfert à la communauté de communes. "
        "L'association, domiciliée à Testonville, écrit à la régie (`contact.eau@exemple.fr`). "
        "Le conseil ne le fera qu'après le 12 mars 2022.")
