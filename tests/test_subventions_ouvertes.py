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

import json

import pytest

# Ces deux collecteurs sortent sur le réseau, donc importent `requests`, que le
# job « tests » de la CI n'installe pas : il n'installe que pytest, pour
# démontrer que le cœur du moteur se teste sans réseau ni collecteur. Ce fichier
# y est donc SAUTÉ, et joué par le job « tests-deps », qui refuse le moindre
# test sauté. Même convention que `tests/test_dematdoc.py` pour pdfplumber.
requests = pytest.importorskip("requests",
                    reason="job « tests-deps » : pip install -r requirements.txt")

from collectors.db import beneficiaire_local, beneficiaires_locaux  # noqa: E402
from collectors.subventions_ouvertes import (JEUX_NON_DECLARES,  # noqa: E402
                                             _annee, _cle, _montant, _valeur,
                                             jeux_du_schema)


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


def test_lattribuant_se_reconnait_sous_sa_forme_ademe():
    """L'ADEME écrit « Nom de l attribuant ». Sans alias, toutes ses aides
    seraient parties sous le nom générique « Collectivité »."""
    assert _cle("Nom de l attribuant") == _cle("nomAttribuant") == "nomattribuant"


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


def test_lexercice_se_lit_dans_le_champ_officiel_de_la_periode():
    """Le schéma nomme le champ `datesPeriodeVersement`, au pluriel : le
    collecteur ne cherchait que le singulier, et ce repli ne servait jamais."""
    assert _annee({"dateconvention": "",
                   "datesperiodeversement": "2022-01-15"}) == 2022


def test_sans_date_lisible_lannee_reste_inconnue():
    """Mieux vaut pas d'année qu'une année inventée : la page range les flux
    par exercice, et un exercice faux déplace de l'argent dans le temps."""
    assert _annee({"dateconvention": "à définir"}) is None


# ── Les clés de rapprochement, toutes des identifiants ───────────────────────

def _entreprise(base, entite, nom, siren, siege, locaux):
    """Une entreprise telle que SIRENE la rend : son siège, et les
    établissements appariés dans le périmètre."""
    eid = entite(nom, "business")
    brut = {"siren": siren, "siege": {"siret": siege},
            "matching_etablissements": [{"siret": s} for s in locaux]}
    base.execute("INSERT INTO businesses (entity_id, siren, siret_siege, raw_data)"
                 " VALUES (?,?,?,?)", (eid, siren, siege, json.dumps(brut)))
    base.commit()
    return eid


def test_le_siege_dailleurs_ne_verse_rien_a_son_etablissement_dici(base, entite):
    """Cas réel, Saillans : une coopérative lyonnaise tient un magasin au
    village. La Métropole de Lyon subventionne son SIÈGE. Croisé sur le SIREN,
    l'argent atterrissait au village — 20 flux, 19 publiés."""
    cooperative = _entreprise(base, entite, "COOPERATIVE DE LYON", "790058572",
                              siege="79005857200047",
                              locaux=["79005857200237"])
    index = beneficiaires_locaux(base)
    assert beneficiaire_local(index, "79005857200047") is None
    assert beneficiaire_local(index, "790058572") is None
    assert beneficiaire_local(index, "79005857200237") == cooperative


def test_une_personne_morale_dici_recoit_par_tous_ses_guichets(base, entite):
    """Siège dans le périmètre : c'est elle qui reçoit, même si la convention
    vise un autre de ses établissements, ou ne donne que le SIREN."""
    sarl = _entreprise(base, entite, "SARL DU PONT", "812345678",
                       siege="81234567800012", locaux=["81234567800012"])
    index = beneficiaires_locaux(base)
    assert beneficiaire_local(index, "81234567800012") == sarl
    assert beneficiaire_local(index, "812 345 678 00099") == sarl
    assert beneficiaire_local(index, "812345678") == sarl


def test_une_entreprise_sans_trace_sirene_ne_rattache_rien(base, entite):
    """Un SIREN sans établissement apparié ne prouve pas une présence ici."""
    eid = entite("SANS TRACE", "business")
    base.execute("INSERT INTO businesses (entity_id, siren) VALUES (?,?)",
                 (eid, "812345678"))
    base.commit()
    assert beneficiaire_local(beneficiaires_locaux(base), "812345678") is None


def test_une_association_se_rapproche_par_son_siren_ou_son_rna(base, entite):
    """Le RNA compte autant que le SIREN : le registre national ne publie un
    SIRET que pour 3 % des associations, et sans cette seconde clé la moitié
    du tissu associatif reste introuvable dans un registre qui parle de lui.
    Son siège est d'ici par construction — le RNA la trouve par son adresse."""
    asso = entite("LES AMIS DU LAVOIR", "association")
    base.execute("INSERT INTO associations (entity_id, siren, rna_id)"
                 " VALUES (?,?,?)", (asso, "450499447", "W301234567"))
    base.commit()
    index = beneficiaires_locaux(base)
    assert beneficiaire_local(index, "45049944700018") == asso
    assert beneficiaire_local(index, "", rna="w301234567") == asso


def test_une_association_sans_identifiant_nentre_pas_dans_lindex(base, entite):
    """Sans identifiant, il n'y a rien à rapprocher — et surtout rien à
    rapprocher PAR LE NOM, qui poserait de faux bénéficiaires."""
    asso = entite("ASSOCIATION SANS PAPIERS", "association")
    base.execute("INSERT INTO associations (entity_id) VALUES (?)", (asso,))
    base.commit()
    index = beneficiaires_locaux(base)
    assert asso not in {**index["siret"], **index["siren"], **index["rna"]}.values()


# ── Découvrir les jeux ───────────────────────────────────────────────────────

class _Reponse:
    def __init__(self, charge):
        self._charge = charge

    def raise_for_status(self):
        pass

    def json(self):
        return self._charge


class _Catalogue:
    """Le catalogue data.gouv, réduit à ce que le collecteur lui demande."""

    def __init__(self, declares, nommes):
        self.declares, self.nommes = declares, nommes

    def get(self, url, timeout=None, params=None):
        if params:
            return _Reponse({"data": self.declares, "next_page": None})
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        if slug not in self.nommes:
            raise requests.HTTPError("404")
        return _Reponse(self.nommes[slug])


def test_un_jeu_qui_applique_le_schema_sans_le_declarer_est_lu():
    slug = JEUX_NON_DECLARES[0]
    jeux = jeux_du_schema(_Catalogue([{"id": "declare"}], {slug: {"id": "nomme"}}))
    assert [j["id"] for j in jeux] == ["declare", "nomme"]


def test_un_jeu_nomme_et_declare_nentre_quune_fois():
    """Le jour où le producteur déclare enfin le schéma, ses aides ne doivent
    pas entrer deux fois."""
    slug = JEUX_NON_DECLARES[0]
    jeux = jeux_du_schema(_Catalogue([{"id": "x"}], {slug: {"id": "x"}}))
    assert [j["id"] for j in jeux] == ["x"]


def test_un_jeu_nomme_disparu_nemporte_pas_les_autres():
    jeux = jeux_du_schema(_Catalogue([{"id": "declare"}], {}))
    assert [j["id"] for j in jeux] == ["declare"]
