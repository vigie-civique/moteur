"""La cadence : ce qui se relance, et ce qui a le droit de ne pas se relancer.

Deux contrôles bien distincts.

Le premier est le MIROIR de `test_no_engine_step_escapes_the_arbitration`
(portail) : là-bas, un step neuf pouvait rester hors du dossier national sans
que rien ne le signale ; ici, il peut rester hors de la table de FRAÎCHEUR — et
alors plus rien ne le relance ni ne signale son silence. C'est ce qui était
arrivé à `crc` (écrit le 01/09/2026, sans rythme) et à `education`.

Le second éprouve la règle qui décide, sur une vraie base : un `error`
NE rajeunit PAS une source. Sans cette clause, une API en panne paraîtrait
fraîche pour la seule raison qu'on a essayé, et la boucle cesserait de la
retenter le lendemain — la panne se refermerait sur elle-même.
"""
from __future__ import annotations

import ast
import importlib.util
import re
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# `collectors.config` se charge avec la seule bibliothèque standard ; c'est
# pour cela que la table de fraîcheur y vit, et que `qa_loop` la lit sans
# importer un collecteur.
from collectors.config import STEP_META      # noqa: E402


def _steps_du_moteur() -> list[str]:
    """Les noms des steps, lus par `ast` — sans IMPORTER `run_all`.

    L'importer tire les quarante collecteurs, donc `pdfplumber`, que le job
    « tests » de la CI n'installe pas : un contrôle qui n'a besoin que d'une
    liste de noms ferait rougir la CI légère pour une dépendance qu'il
    n'emploie pas. C'est le piège déjà rencontré côté portail, où le contrôle
    de l'arbitrage national lit lui aussi `run_all.STEPS` par `ast`.
    """
    arbre = ast.parse((ROOT / "collectors" / "run_all.py").read_text(encoding="utf-8"))
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Assign) and any(
                isinstance(c, ast.Name) and c.id == "STEPS" for c in noeud.targets):
            return [cle.value for cle in noeud.value.keys]
    raise AssertionError("STEPS introuvable dans collectors/run_all.py")


STEPS = _steps_du_moteur()


def _collect_loop():
    """`scripts/` est un répertoire d'outils, pas un paquet — chargé par chemin,
    comme `run_all` le fait lui-même pour `classer_perimetre`.

    Ici, en revanche, il faut bien le moteur entier : la boucle appelle
    `run_step`. Les essais qui passent par là sont donc SAUTÉS dans le job
    « tests » et joués par « tests-deps », qui refuse le moindre saut. Même
    convention que `tests/test_dematdoc.py`.
    """
    pytest.importorskip("pdfplumber",
                        reason="job « tests-deps » : pip install -r requirements.txt")
    chemin = ROOT / "scripts" / "collect_loop.py"
    spec = importlib.util.spec_from_file_location("collect_loop", chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Ce qui a le droit d'être hors de la table, et POURQUOI. Une liste sans motif
# se relit comme un oubli et se corrige de travers.
SANS_RYTHME = {
    "init":          "pas un collecteur : crée le schéma",
    "origine":       "dérivé — relit la `source` que les collecteurs viennent d'écrire",
    "perimetre":     "dérivé — classe les entités déjà collectées",
    "saisies":       "rejoue `config/saisies.json` : des décisions humaines, pas une source",
    "approbations":  "dérivé du texte des séances",
    "budgets_votes": "dérivé du texte des séances",
}


def test_aucun_step_n_echappe_a_la_table_de_fraicheur():
    """Un step qui collecte sans TTL n'est jamais relancé et son silence ne se
    voit nulle part — ni dans `collect_loop`, ni dans l'alerte de `qa_loop`."""
    orphelins = sorted(set(STEPS) - set(STEP_META) - set(SANS_RYTHME))
    assert orphelins == [], (
        f"step(s) sans rythme déclaré : {orphelins} — leur donner un TTL dans "
        "`STEP_META`, ou les inscrire dans SANS_RYTHME avec la raison")


def test_la_liste_des_exemptes_ne_survit_pas_a_ses_steps():
    """Une exemption qui nomme un step disparu masquerait le jour où un step
    du même nom revient, en collectant cette fois."""
    fantomes = sorted(set(SANS_RYTHME) - set(STEPS))
    assert fantomes == [], f"exemption(s) sans step correspondant : {fantomes}"


def test_un_rythme_declare_designe_une_table_qui_existe(base):
    """Le TTL ne sert à rien si le comptage échoue : `count_items` avale
    l'erreur et rend None, donc un step dont la table témoin est mal
    orthographiée paraîtrait ne jamais rien ajouter — et ses dérivés ne
    seraient plus rejoués. Un nom faux ne casse rien : il rend muet.

    La table est cherchée à DEUX endroits, parce qu'il y en a deux : le schéma
    de référence, et les quatorze tables qu'un collecteur crée lui-même par
    `CREATE TABLE IF NOT EXISTS` au premier passage (`justice_decisions`,
    `etablissements_scolaires`…). Les chercher dans la seule base de test
    ferait rougir un rythme parfaitement juste.
    """
    connues = {r[0] for r in base.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    code = "\n".join(f.read_text(encoding="utf-8")
                     for f in (ROOT / "collectors").glob("*.py"))
    manquantes = sorted(
        nom for nom in {meta[2] for meta in STEP_META.values()}
        if nom not in connues
        and not re.search(rf"CREATE TABLE IF NOT EXISTS\s+{re.escape(nom)}\b", code))
    assert manquantes == [], (
        f"table(s) témoin introuvables, ni au schéma ni créées par un "
        f"collecteur : {manquantes}")


@pytest.fixture
def base_avec_runs(base: sqlite3.Connection):
    """Trois sources, trois situations, dans la vraie table `collector_runs`."""
    base.executemany(
        "INSERT INTO collector_runs (collector, finished_at, status, items_added)"
        " VALUES (?, datetime('now', ?), ?, ?)",
        [
            ("events", "-1 day",   "ok",    4),      # TTL 3 j  → frais
            ("osm",    "-40 days", "ok",    0),      # TTL 30 j → périmé
            ("sirene", "-1 day",   "error", None),   # TTL 30 j → périmé quand même
        ])
    base.commit()
    return base


def test_une_source_essayee_sans_succes_reste_perimee(base_avec_runs):
    cl = _collect_loop()
    retard = cl.perimes(base_avec_runs)
    assert "sirene" in retard, (
        "un `error` d'hier a rajeuni la source : la panne se refermerait sur "
        "elle-même, plus personne ne retenterait")
    assert "osm" in retard
    assert "events" not in retard


def test_l_ordre_suit_la_priorite_declaree(base_avec_runs):
    """`events` avant `osm` n'est pas cosmétique : quand la fenêtre de collecte
    est coupée court, ce qui compte le plus doit être déjà passé."""
    cl = _collect_loop()
    retard = cl.perimes(base_avec_runs, force=True)
    priorites = [STEP_META[n][1] for n in retard]
    assert priorites == sorted(priorites)


def test_les_derives_nomment_des_steps_qui_existent():
    """Un dérivé mal orthographié ne casse rien : il ne se joue simplement
    jamais, et le défaut du 14/08/2026 revient en silence."""
    cl = _collect_loop()
    inconnus = sorted({d for derives in cl.DERIVES.values() for d in derives
                       if d not in STEPS} | {s for s in cl.DERIVES if s not in STEPS})
    assert inconnus == [], f"dérivé(s) ou source(s) inconnus : {inconnus}"
    assert set(cl.CLOTURE) <= set(STEPS)
