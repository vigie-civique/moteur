"""La sauvegarde d'une base en WAL est entière, et se rouvre.

Quatre scripts copiaient le fichier de la base (`shutil.copy2`). En WAL, ce qui
vient d'être validé vit dans le journal tant qu'aucun point de contrôle ne l'a
reversé : la copie ne le contenait pas.
"""
from __future__ import annotations

import importlib.util
import shutil
import sqlite3
from pathlib import Path

import pytest

from collectors.sauvegarde import sauvegarder, verifier

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def base_en_wal(tmp_path):
    """Une base dont les dernières lignes ne sont QUE dans le journal : la
    connexion reste ouverte, comme celle d'un collecteur en cours."""
    chemin = tmp_path / "vivante.db"
    conn = sqlite3.connect(chemin)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("CREATE TABLE actes (id INTEGER PRIMARY KEY, titre TEXT)")
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.executemany("INSERT INTO actes(titre) VALUES (?)",
                     [(f"délibération {i}",) for i in range(200)])
    conn.commit()
    yield chemin
    conn.close()


def _lignes(chemin: Path) -> int:
    conn = sqlite3.connect(chemin)
    try:
        return conn.execute("SELECT COUNT(*) FROM actes").fetchone()[0]
    finally:
        conn.close()


def test_la_copie_de_fichier_perd_ce_qui_est_dans_le_journal(base_en_wal, tmp_path):
    """Le défaut, tel qu'il était : la preuve que l'essai suivant éprouve bien
    quelque chose."""
    copie = tmp_path / "copie-de-fichier.db"
    shutil.copy2(base_en_wal, copie)
    assert _lignes(copie) == 0


def test_la_sauvegarde_porte_ce_qui_est_dans_le_journal(base_en_wal, tmp_path):
    copie = sauvegarder(base_en_wal, tmp_path / "sauvegardes" / "copie.db")
    assert _lignes(copie) == 200
    assert verifier(copie) == []
    assert not copie.with_name(copie.name + ".partiel").exists()


def test_une_copie_abimee_est_refusee(base_en_wal, tmp_path):
    copie = sauvegarder(base_en_wal, tmp_path / "copie.db")
    octets = bytearray(copie.read_bytes())
    octets[100:4096] = b"\x00" * 3996
    copie.write_bytes(bytes(octets))
    assert verifier(copie) != []
    assert verifier(tmp_path / "absente.db") != []


def test_sans_base_rien_n_est_ecrit(tmp_path):
    with pytest.raises(FileNotFoundError):
        sauvegarder(tmp_path / "absente.db", tmp_path / "copie.db")
    assert not (tmp_path / "copie.db").exists()


def test_le_script_rouvre_la_copie(base_en_wal, tmp_path, capsys):
    spec = importlib.util.spec_from_file_location(
        "verifier_sauvegarde", ROOT / "scripts" / "verifier_sauvegarde.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    copie = sauvegarder(base_en_wal, tmp_path / "copie.db")
    assert module.main([str(copie), "--base", str(base_en_wal)]) == 0
    assert "intègre" in capsys.readouterr().out
    assert module.main([str(tmp_path / "absente.db"), "--base", str(base_en_wal)]) == 1


def test_plus_aucun_script_ne_copie_la_base_comme_un_fichier():
    fautifs = [nom for nom in ("collect_loop", "qa_loop", "purger_profondeur", "reparer_encodage")
               if "copy2" in (ROOT / "scripts" / f"{nom}.py").read_text(encoding="utf-8")]
    assert fautifs == []
