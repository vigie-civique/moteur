"""Un step qui échoue le dit, et ne prend pas les suivants avec lui.

`run_step` rattrapait `Exception`. Un collecteur qui sortait par `sys.exit`
— `SystemExit` est une `BaseException` — passait donc au travers : la ligne de
`collector_runs` était close `ok` (donc `empty`, aucun item de plus), et la
collecte entière s'arrêtait là, les steps suivants jamais joués.
"""
from __future__ import annotations

import ast
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def run_all(tmp_path, schema_sql, monkeypatch):
    """Le vrai `run_step`, sur une base de fichier : il FERME sa connexion, la
    fixture `base` n'y survivrait pas. Sauté dans le job « tests » (le moteur
    entier tire `pdfplumber`), joué par « tests-deps »."""
    pytest.importorskip("pdfplumber",
                        reason="job « tests-deps » : pip install -r requirements.txt")
    from collectors import run_all as ra
    chemin = tmp_path / "essai.db"
    conn = sqlite3.connect(chemin)
    conn.executescript(schema_sql)
    conn.close()

    def get_conn():
        c = sqlite3.connect(chemin)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(ra, "get_conn", get_conn)
    monkeypatch.setattr(ra, "lire", lambda: [dict(r) for r in get_conn().execute(
        "SELECT collector, status, error FROM collector_runs ORDER BY id")], raising=False)
    return ra


def _poser(ra, monkeypatch, nom, fn):
    monkeypatch.setitem(ra.STEPS, nom, (f"step d'épreuve {nom}", fn))
    monkeypatch.setitem(ra.STEP_META, nom, (1, "épreuve", "entities", None))


def test_un_step_qui_sort_par_exit_est_une_erreur(run_all, monkeypatch):
    _poser(run_all, monkeypatch, "sortant", lambda: sys.exit("réglage manquant"))
    status, err = run_all.run_step("sortant")
    assert status == "error" and "réglage manquant" in err
    [ligne] = run_all.lire()
    assert ligne["status"] == "error" and "SystemExit" in ligne["error"]


def test_la_collecte_continue_apres_un_exit(run_all, monkeypatch):
    joues = []
    _poser(run_all, monkeypatch, "sortant", lambda: sys.exit(1))
    _poser(run_all, monkeypatch, "suivant", lambda: joues.append("suivant"))
    monkeypatch.setattr(run_all, "STEPS", {k: run_all.STEPS[k] for k in ("sortant", "suivant")})
    monkeypatch.setattr(run_all, "init_db", lambda: None)
    monkeypatch.setattr(run_all, "print_stats", lambda: None)
    monkeypatch.setattr(sys, "argv", ["run_all.py"])
    assert run_all.main() == 1, "une collecte partielle rend 1 au shell"
    assert joues == ["suivant"]
    assert [l["status"] for l in run_all.lire()] == ["error", "empty"]


def test_une_sortie_a_zero_reste_une_fin_normale(run_all, monkeypatch):
    _poser(run_all, monkeypatch, "poli", lambda: sys.exit(0))
    assert run_all.run_step("poli") == ("ok", None)


def test_une_interruption_au_clavier_remonte_et_se_note(run_all, monkeypatch):
    def interrompu():
        raise KeyboardInterrupt
    _poser(run_all, monkeypatch, "coupe", interrompu)
    with pytest.raises(KeyboardInterrupt):
        run_all.run_step("coupe")
    assert run_all.lire()[0]["status"] == "error"


# ── Le contrat : un collecteur ne sort pas du processus ──────────────────────
# Ce qui a le droit de le faire, et POURQUOI. Hors de cette liste, lever
# `collectors.erreurs.ConfigurationManquante` : `run_step` la journalise.
SORTIES_ADMISES = {
    ("config.py", "<module>"):  "à l'import, avant tout step : sans instance.json rien ne peut tourner",
    ("config.py", "_exiger"):   "idem — clé obligatoire d'instance.json, lue à l'import",
    ("config.py", "registre_du_step"): "réglage d'instance incohérent ; rattrapé par run_step",
    ("connecteurs/__init__.py", "charger"): "connecteur déclaré inconnu ; rattrapé par run_step",
    ("cm_ocr.py", "_check_ocr_tooling"): "outil en ligne de commande : ocrmypdf absent du poste",
    ("cm_ocr.py", "process_cr"): "outil en ligne de commande, hors run_all",
    ("pappers.py", "get_token"): "API payante, jamais dans la collecte complète",
    ("en_clair/verifier.py", "_instance"): "outil en ligne de commande, hors run_all",
}


def _sorties() -> set[tuple[str, str]]:
    trouvees = set()

    def visiter(noeud, fichier, ou):
        for enfant in ast.iter_child_nodes(noeud):
            ici = ou
            if isinstance(enfant, (ast.FunctionDef, ast.AsyncFunctionDef)):
                ici = enfant.name
            elif (isinstance(enfant, ast.If) and isinstance(enfant.test, ast.Compare)
                    and getattr(enfant.test.left, "id", "") == "__name__"):
                ici = "__main__"
            if isinstance(enfant, ast.Call):
                f = enfant.func
                sortie = (isinstance(f, ast.Attribute) and f.attr == "exit"
                          and getattr(f.value, "id", "") == "sys") or (
                    isinstance(f, ast.Name) and f.id in ("exit", "quit", "SystemExit"))
                if sortie and ici not in ("__main__", "main"):
                    trouvees.add((fichier, ici))
            visiter(enfant, fichier, ici)

    racine = ROOT / "collectors"
    for chemin in sorted(racine.rglob("*.py")):
        visiter(ast.parse(chemin.read_text(encoding="utf-8")),
                chemin.relative_to(racine).as_posix(), "<module>")
    return trouvees


def test_aucun_collecteur_ne_sort_du_processus():
    nouvelles = sorted(_sorties() - set(SORTIES_ADMISES))
    assert nouvelles == [], (
        f"sys.exit / SystemExit dans un collecteur : {nouvelles} — lever "
        "ConfigurationManquante, ou inscrire la sortie dans SORTIES_ADMISES avec sa raison")


def test_les_sorties_admises_existent_encore():
    fantomes = sorted(set(SORTIES_ADMISES) - _sorties())
    assert fantomes == [], f"exemption(s) sans sortie correspondante : {fantomes}"
