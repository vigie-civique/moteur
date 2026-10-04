"""Le registre des étapes du snapshot tient debout sans rien exécuter.

Chaque étape ne lit que ce qu'une étape précédente a produit (ou ce que
`build_snapshot` fournit), aucun fait n'est produit deux fois, aucun fichier
n'est revendiqué par deux étapes. Et l'exécuteur refuse une étape qui ment sur
ce qu'elle rend : une déclaration fausse casse la construction au lieu de
laisser le registre dire autre chose que le code.
"""
from __future__ import annotations

import pytest

from scripts.snapshot.etapes import ETAPES, FOURNIS
from scripts.snapshot.registre import Etape, RegistreIncoherent, executer, incoherences


def test_le_registre_du_snapshot_est_coherent():
    assert incoherences(ETAPES, set(FOURNIS)) == []


def test_une_etape_ne_lit_pas_ce_qu_une_etape_suivante_produit():
    etapes = [
        Etape("b", lambda a: {"b": a}, lit=("a",), produit=("b",)),
        Etape("a", lambda: {"a": 1}, produit=("a",)),
    ]
    assert incoherences(etapes, set()) == [
        "b : lit « a », que rien ne produit avant elle"]


def test_deux_etapes_ne_revendiquent_pas_le_meme_fichier():
    etapes = [Etape("x", lambda: None, ecrit=("stats.json",)),
              Etape("y", lambda: None, ecrit=("stats.json",))]
    assert incoherences(etapes, set()) == ["y : écrit stats.json, que x écrit déjà"]


def test_l_executeur_refuse_une_etape_qui_rend_ce_qu_elle_ne_declare_pas():
    etapes = [Etape("menteuse", lambda: {"a": 1, "b": 2}, produit=("a",))]
    with pytest.raises(RegistreIncoherent, match="menteuse"):
        executer(etapes, {})


def test_l_executeur_donne_a_chaque_etape_exactement_ce_qu_elle_declare():
    vus = []

    def b(a, journal):
        journal.append(a)
        return {"b": a + 1}

    faits = executer([Etape("a", lambda: {"a": 1}, produit=("a",)),
                      Etape("b", b, lit=("a",), complete=("journal",), produit=("b",))],
                     {"journal": vus})
    assert faits["b"] == 2 and vus == [1]
