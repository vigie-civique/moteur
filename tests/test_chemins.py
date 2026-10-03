"""Le garde des chemins : ce qui reste sous la racine passe, le reste est refusé."""
from pathlib import Path

import pytest

from collectors.chemins import CheminHorsRacine, sous
from collectors import dossiers as D


def test_un_fichier_sous_la_racine_passe(tmp_path):
    assert sous(tmp_path, "eau.md") == tmp_path / "eau.md"
    assert sous(tmp_path, "2026-03-04-cm", "releve.json") == tmp_path / "2026-03-04-cm" / "releve.json"


def test_un_fichier_a_creer_se_verifie_sans_exister(tmp_path):
    assert not (tmp_path / "neuf" / "donnees").exists()
    assert sous(tmp_path, "neuf", "donnees") == tmp_path / "neuf" / "donnees"


@pytest.mark.parametrize("parties", [("..", "x"), ("a", "..", "..", "x"), ("/etc/passwd",), (".",), ("",)])
def test_ce_qui_sort_de_la_racine_ou_la_designe_est_refuse(tmp_path, parties):
    with pytest.raises(CheminHorsRacine):
        sous(tmp_path, *parties)


def test_un_voisin_au_meme_prefixe_n_est_pas_un_enfant(tmp_path):
    racine = tmp_path / "apercus"
    with pytest.raises(CheminHorsRacine):
        sous(racine, "..", "apercus-2", "x")


def test_le_chemin_d_un_dossier_reste_sous_dossiers(tmp_path):
    assert D.chemin(tmp_path, "eau") == tmp_path / "dossiers" / "eau.md"
    with pytest.raises(ValueError):
        D.chemin(tmp_path, "../eau")


def test_le_dossier_d_un_apercu_reste_sous_apercus():
    from scripts import publication as pub
    assert pub.dossier_apercu(7) == Path(pub.APERCUS) / "7"
    with pytest.raises(pub.PublicationRefusee):
        pub.dossier_apercu("../7")
