"""Les conventions de subvention publiées au schéma national (SCDL).

Le décret n° 2017-779 impose la publication, sous trois mois, des données
essentielles des conventions de subvention, au format `scdl/subventions`. Le
collecteur ne connaît aucun portail : il demande à data.gouv.fr quels jeux
déclarent ce schéma, et retient les lignes dont le bénéficiaire est du
périmètre.

Le schéma normalise les COLONNES, pas le soin apporté aux fichiers. Les cas
éprouvés ici viennent tous du catalogue réel.
"""
from __future__ import annotations

import pytest

# Ces deux collecteurs sortent sur le réseau, donc importent `requests`, que le
# job « tests » de la CI n'installe pas : il n'installe que pytest, pour
# démontrer que le cœur du moteur se teste sans réseau ni collecteur. Ce fichier
# y est donc SAUTÉ, et joué par le job « tests-deps », qui refuse le moindre
# test sauté. Même convention que `tests/test_dematdoc.py` pour pdfplumber.
pytest.importorskip("requests",
                    reason="job « tests-deps » : pip install -r requirements.txt")

from collectors.subventions_ouvertes import (_annee, _cle, _montant, _valeur,
                                             index_local)  # noqa: E402


# ── Lire un en-tête que cinquante organisations écrivent à leur façon ────────

def test_la_colonne_se_reconnait_malgre_la_casse_et_les_espaces():
    """Un seul jeu du catalogue porte « Montant » et « Montant » avec une
    espace finale, dans deux de ses fichiers."""
    assert _cle("Montant ") == _cle("montant") == "montant"
    assert _cle("idBeneficiaire") == "idbeneficiaire"


def test_les_deux_orthographes_du_beneficiaire_sont_la_meme_colonne():
    """« nomBeneficiere » est une faute de frappe du producteur, présente en
    production. La traiter comme une colonne inconnue perdait le nom."""
    assert _cle("nomBeneficiere") == _cle("nomBeneficiaire") == "nombeneficiaire"


def test_une_colonne_absente_ne_leve_pas():
    assert _valeur({}, "objet") == ""


# ── Montants et exercices ────────────────────────────────────────────────────

def test_le_montant_se_lit_avec_separateur_ou_symbole():
    assert _montant("1 500,00") == 1500
    assert _montant("2 300 €") == 2300


def test_un_montant_absent_ne_devient_pas_zero():
    """Une convention sans montant lisible et une convention à 0 € ne disent
    pas la même chose."""
    assert _montant("") is None
    assert _montant("n/c") is None


def test_lexercice_vient_de_la_date_de_convention():
    assert _annee({"dateconvention": "2024-03-12"}) == 2024


def test_lexercice_se_replie_sur_la_periode_de_versement():
    assert _annee({"dateconvention": "", "dateperiodeversement": "01/2023"}) == 2023


def test_sans_date_lisible_lannee_reste_inconnue():
    """Mieux vaut pas d'année qu'une année inventée : la page range les flux
    par exercice, et un exercice faux déplace de l'argent dans le temps."""
    assert _annee({"dateconvention": "à définir"}) is None


# ── Les deux clés de rapprochement, toutes deux des identifiants ─────────────

def test_lindex_local_porte_les_siren_et_les_identifiants_rna(base, entite):
    """Le RNA compte autant que le SIREN : le registre national ne publie un
    SIRET que pour 3 % des associations, et sans cette seconde clé la moitié
    du tissu associatif reste introuvable dans un registre qui parle de lui."""
    asso = entite("LES AMIS DU LAVOIR", "association")
    entreprise = entite("SARL DU PONT", "business")
    base.execute("INSERT INTO associations (entity_id, rna_id) VALUES (?,?)",
                 (asso, "W301234567"))
    base.execute("INSERT INTO businesses (entity_id, siren) VALUES (?,?)",
                 (entreprise, "812345678"))
    base.commit()

    sirens, rnas = index_local(base)
    assert sirens["812345678"] == entreprise
    assert rnas["W301234567"] == asso


def test_une_association_sans_identifiant_nentre_pas_dans_lindex(base, entite):
    """Sans identifiant, il n'y a rien à rapprocher — et surtout rien à
    rapprocher PAR LE NOM, qui poserait de faux bénéficiaires."""
    asso = entite("ASSOCIATION SANS PAPIERS", "association")
    base.execute("INSERT INTO associations (entity_id) VALUES (?)", (asso,))
    base.commit()
    sirens, rnas = index_local(base)
    assert asso not in sirens.values()
    assert asso not in rnas.values()
