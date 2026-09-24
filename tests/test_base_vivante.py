"""Les scripts d'entretien ouvrent la base vivante, jamais une sauvegarde."""
import pytest

from scripts.reparer_entites import base_de


def test_une_sauvegarde_plus_ancienne_ne_passe_pas_devant(tmp_path):
    (tmp_path / "db").mkdir()
    for nom in ("30140.avant-doublons-20260907-171734.db", "30140.db",
                "30140.db.avant-20260828-135906"):
        (tmp_path / "db" / nom).touch()
    assert base_de(tmp_path).name == "30140.db"


def test_deux_bases_vivantes_arretent(tmp_path):
    (tmp_path / "db").mkdir()
    for nom in ("30140.db", "26289.db"):
        (tmp_path / "db" / nom).touch()
    with pytest.raises(SystemExit):
        base_de(tmp_path)
