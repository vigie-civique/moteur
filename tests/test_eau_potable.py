"""L'eau du robinet : réseaux desservis et contrôle sanitaire (Hub'Eau).

Aucun appel réseau. Les lignes reproduites ont la forme exacte que Hub'Eau a
rendue le 30/09/2026 sur `communes_udi` et `resultats_dis` pour Lasalle.

Ce que ces essais protègent :
  1. un prélèvement demandé au titre d'un réseau reste rattaché à ce réseau,
     même si la réponse ne le liste pas ;
  1 bis. la reprise d'un réseau ne se règle que sur SA requête : un prélèvement
     partagé, arrivé par un voisin, lui faisait sauter 2016-2020 (30/09/2026) ;
  2. un prélèvement commun à deux réseaux vaut pour les deux ;
  3. « <0,005 » n'est pas zéro : Hub'Eau publie 0.0 en numérique, le texte
     publié doit survivre ;
  4. rejouer une page n'écrit rien deux fois ;
  5. trois fractions d'un même paramètre (microcystine totale, dissoute, dans
     la biomasse) sont trois résultats, pas un.
"""
from __future__ import annotations

from collectors.eau_potable import (depart, enregistrer_resultats, ensure_tables,
                                    ligne_udi, noter_suivi)


def _resultat(prel="03000199114", param="7010", reseaux=("030000476",),
              date="2026-07-13T13:14:00Z", alpha="<0,005", num=0.0):
    return {
        "code_prelevement": prel, "code_parametre": param,
        "libelle_parametre": "Chlordane alpha", "code_type_parametre": "N",
        "code_lieu_analyse": "L", "resultat_alphanumerique": alpha,
        "resultat_numerique": num, "libelle_unite": "µg/L",
        "limite_qualite_parametre": "<=0,1 µg/L", "reference_qualite_parametre": None,
        "code_commune": "30329", "nom_commune": "THOIRAS-CORBÈS",
        "nom_uge": "SYNDICAT DE LASALLE", "nom_distributeur": "VEOLIA GARD - LOZÈRE",
        "nom_moa": "SYNDICAT DE LASALLE", "date_prelevement": date,
        "conclusion_conformite_prelevement": "Eau d'alimentation conforme.",
        "conformite_limites_bact_prelevement": "C",
        "conformite_limites_pc_prelevement": "C",
        "conformite_references_bact_prelevement": "C",
        "conformite_references_pc_prelevement": "N",
        "reseaux": [{"code": c, "nom": "—"} for c in reseaux],
    }


def _reseaux_de(base, prel):
    return {r[0] for r in base.execute(
        "SELECT code_reseau FROM eau_potable_prelevement_reseaux"
        " WHERE code_prelevement=?", (prel,))}


def test_un_quartier_absent_ne_casse_pas_la_cle():
    u = {"code_commune": "30140", "nom_quartier": None, "code_reseau": "030000473",
         "nom_reseau": "LASALLE", "debut_alim": "2010-12-30", "annee": "2026"}
    assert ligne_udi(u)[2] == ""


def test_le_reseau_interroge_est_toujours_rattache(base):
    ensure_tables(base)
    enregistrer_resultats(base, [_resultat(reseaux=())], "030000476")
    assert _reseaux_de(base, "03000199114") == {"030000476"}


def test_un_prelevement_commun_vaut_pour_les_deux_reseaux(base):
    ensure_tables(base)
    enregistrer_resultats(base, [_resultat(reseaux=("030000473", "030008363"))],
                          "030000473")
    assert _reseaux_de(base, "03000199114") == {"030000473", "030008363"}


def test_sous_le_seuil_n_est_pas_zero(base):
    ensure_tables(base)
    enregistrer_resultats(base, [_resultat()], "030000476")
    alpha, num = base.execute(
        "SELECT resultat_alpha, resultat_numerique FROM eau_potable_resultats").fetchone()
    assert (alpha, num) == ("<0,005", 0.0)


def test_rejouer_une_page_n_ecrit_rien_deux_fois(base):
    ensure_tables(base)
    page = [_resultat(param="7010"), _resultat(param="1340")]
    assert enregistrer_resultats(base, page, "030000476") == 2
    assert enregistrer_resultats(base, page, "030000476") == 0
    assert base.execute("SELECT COUNT(*) FROM eau_potable_prelevements").fetchone()[0] == 1


def test_la_reprise_part_du_dernier_prelevement_lu_pour_le_reseau(base):
    ensure_tables(base)
    page = [_resultat(prel="A", date="2024-03-01T08:00:00Z"),
            _resultat(prel="B", date="2026-07-13T13:14:00Z")]
    enregistrer_resultats(base, page, "030000476")
    noter_suivi(base, "030000476", page, None)
    assert depart(base, "030000476", None) == "2026-07-13"
    assert depart(base, "030000476", "2020-01-01") == "2020-01-01"


def test_un_rattachement_venu_d_un_voisin_ne_fait_pas_sauter_l_histoire(base):
    """Le bourg (473) rapporte un prélèvement de 2026 partagé avec Thoiras
    (476) : Thoiras n'a encore rien lu lui-même, il repart de 2016."""
    ensure_tables(base)
    page = [_resultat(reseaux=("030000473", "030000476"))]
    enregistrer_resultats(base, page, "030000473")
    noter_suivi(base, "030000473", page, None)
    assert "030000476" in _reseaux_de(base, "03000199114")
    assert depart(base, "030000476", None) == "2016-01-01"


def test_une_annee_vide_ne_recule_pas_le_suivi(base):
    ensure_tables(base)
    noter_suivi(base, "030000476", [_resultat(date="2025-06-01T08:00:00Z")], None)
    noter_suivi(base, "030000476", [], "2025-06-01T08:00:00Z")
    assert depart(base, "030000476", None) == "2025-06-01"


def test_trois_fractions_d_un_meme_parametre_sont_trois_resultats(base):
    ensure_tables(base)
    page = [dict(_resultat(param="5489"), libelle_parametre=f"Microcystine-YR {f}")
            for f in ("totale", "dissoute", "dans la biomasse")]
    assert enregistrer_resultats(base, page, "030000476") == 3
