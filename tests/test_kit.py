"""Ce que l'archive distribuable a le droit de contenir.

Ces tests existent à cause d'un défaut mesuré le 14/08/2026 : `fichiers()`
parcourait le disque et testait les suffixes à la main. Les sauvegardes de
collecte s'appelant `<insee>.db.avant-<date>`, le test sur `.db` les laissait
passer — 175 Mo de bases nominatives entraient dans l'archive publique. Et
`verifier()` sautait silencieusement tout fichier illisible en UTF-8, donc
précisément ces bases.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Les chaînes que le contrôle du kit interdit sont assemblées à l'exécution :
# écrites en clair, elles feraient refuser l'archive qui contient ces tests —
# et à raison, puisque la règle est qu'aucun chemin personnel n'y figure. Le
# détecteur est bien exercé, il reçoit la même chaîne.
CHEMIN_PERSONNEL = "/" + "Users/quelquun"


def _charger(nom: str):
    spec = importlib.util.spec_from_file_location(nom, ROOT / "scripts" / f"{nom}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


kit = _charger("build_kit")


@pytest.fixture
def depot(tmp_path):
    """Un dépôt git minimal, avec ce qu'on versionne et ce qu'on ignore."""
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args],
                       check=True, capture_output=True)

    (tmp_path / "collectors").mkdir()
    (tmp_path / "db").mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "collectors" / "rna.py").write_text("# collecteur\n")
    (tmp_path / ".gitignore").write_text("db/*.db\ndb/*.db.*\nlogs/\nconfig/instance.json\n")
    # Ce qui ne doit JAMAIS sortir, sous les noms exacts qui avaient fui.
    (tmp_path / "db" / "99001.db").write_bytes(b"SQLite format 3\x00base")
    (tmp_path / "db" / "99001.db.avant-20260814-144151").write_bytes(b"SQLite format 3\x00vieille")
    (tmp_path / "logs" / "collecte.log").write_text(CHEMIN_PERSONNEL + "/Claude\n")
    (tmp_path / "config" / "instance.json").write_text('{"commune_nom": "Testonville"}')

    git("init", "-q")
    git("config", "user.email", "t@t.invalid")
    git("config", "user.name", "test")
    git("add", "-A")
    git("commit", "-q", "-m", "état initial")
    return tmp_path


def test_ne_retient_que_le_versionne(depot):
    retenus = {p.relative_to(depot).as_posix() for p in kit.fichiers(depot)}
    assert "collectors/rna.py" in retenus
    assert ".gitignore" in retenus


def test_les_bases_ne_sortent_pas(depot):
    """Y compris les sauvegardes, dont le nom ne finit pas par .db."""
    retenus = {p.name for p in kit.fichiers(depot)}
    assert not any(".db" in nom for nom in retenus), retenus


def test_les_journaux_ne_sortent_pas(depot):
    retenus = {p.relative_to(depot).as_posix() for p in kit.fichiers(depot)}
    assert not any(r.startswith("logs/") for r in retenus)


def test_la_configuration_dinstance_ne_sort_pas(depot):
    retenus = {p.name for p in kit.fichiers(depot)}
    assert "instance.json" not in retenus


def test_une_base_versionnee_par_erreur_est_refusee(depot):
    """Deuxième filet : si .gitignore laissait passer, le contrôle refuse."""
    subprocess.run(["git", "-C", str(depot), "add", "-f", "db/99001.db"],
                   check=True, capture_output=True)
    liste = kit.fichiers(depot)
    assert any(p.name == "99001.db" for p in liste)
    problemes = kit.verifier(depot, liste)
    assert any("non contrôlable" in p for p in problemes), problemes


def test_un_chemin_personnel_est_refuse(depot):
    (depot / "collectors" / "fuite.py").write_text(
        f'CHEMIN = "{CHEMIN_PERSONNEL}/Claude/base.db"\n')
    subprocess.run(["git", "-C", str(depot), "add", "-A"], check=True, capture_output=True)
    problemes = kit.verifier(depot, kit.fichiers(depot))
    assert any("chemin absolu" in p for p in problemes), problemes


def test_hors_depot_git_refuse_plutot_que_deviner(tmp_path):
    """Sans git, il faudrait réénumérer à la main ce qu'il ne faut pas
    distribuer — c'est exactement ce qui avait laissé fuir les bases."""
    (tmp_path / "fichier.py").write_text("x = 1\n")
    with pytest.raises(SystemExit):
        kit.fichiers(tmp_path)


def test_le_kit_ne_semboite_pas(depot):
    """L'archive précédente est versionnée : elle ne doit pas entrer dans la
    suivante, sinon elle grossit à chaque publication."""
    (depot / "public" / "static" / "kit").mkdir(parents=True)
    (depot / "public" / "static" / "kit" / "vigie-civique.tar.gz").write_bytes(b"\x1f\x8b")
    subprocess.run(["git", "-C", str(depot), "add", "-A"], check=True, capture_output=True)
    retenus = {p.relative_to(depot).as_posix() for p in kit.fichiers(depot)}
    assert not any("static/kit" in r for r in retenus)



# ── L'exception des images (06/10/2026) ──────────────────────────────────────
# Le dépôt versionne quatre icônes PNG. Elles n'échappent pas au contrôle :
# elles sont nommées une par une, et ne peuvent porter que de l'image.

def _png(*morceaux_en_plus: tuple[bytes, bytes], suite: bytes = b"") -> bytes:
    import struct, zlib

    def morceau(genre: bytes, donnees: bytes) -> bytes:
        return (struct.pack(">I", len(donnees)) + genre + donnees
                + struct.pack(">I", zlib.crc32(genre + donnees)))

    corps = morceau(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
    for genre, donnees in morceaux_en_plus:
        corps += morceau(genre, donnees)
    corps += morceau(b"IDAT", zlib.compress(b"\x00\x00")) + morceau(b"IEND", b"")
    return b"\x89PNG\r\n\x1a\n" + corps + suite


def _verifier_image(depot, monkeypatch, octets: bytes, admise: bool = True):
    (depot / "icone.png").write_bytes(octets)
    subprocess.run(["git", "-C", str(depot), "add", "-f", "icone.png"],
                   check=True, capture_output=True)
    monkeypatch.setattr(kit, "IMAGES_ADMISES", {"icone.png"} if admise else set())
    return kit.verifier(depot, kit.fichiers(depot))


def test_une_image_nommee_et_propre_est_admise(depot, monkeypatch):
    assert _verifier_image(depot, monkeypatch, _png()) == []


def test_une_image_non_nommee_reste_refusee(depot, monkeypatch):
    problemes = _verifier_image(depot, monkeypatch, _png(), admise=False)
    assert any("non contrôlable" in p for p in problemes), problemes


def test_une_image_qui_porte_du_texte_est_refusee(depot, monkeypatch):
    problemes = _verifier_image(
        depot, monkeypatch, _png((b"tEXt", b"Author\x00Quelqu'un")))
    assert any("texte libre" in p for p in problemes), problemes


def test_des_octets_apres_limage_sont_refuses(depot, monkeypatch):
    problemes = _verifier_image(depot, monkeypatch, _png(suite=b"SQLite format 3"))
    assert any("suivent la fin" in p for p in problemes), problemes


def test_un_nom_admis_ne_couvre_pas_autre_chose_quun_png(depot, monkeypatch):
    problemes = _verifier_image(depot, monkeypatch, b"SQLite format 3\x00base")
    assert any("pas un PNG" in p for p in problemes), problemes


def test_les_images_admises_existent_et_passent():
    """La liste ne nomme que des fichiers présents, et chacun passe son contrôle."""
    for rel in sorted(kit.IMAGES_ADMISES):
        f = ROOT / rel
        assert f.is_file(), f"{rel} est admis mais absent du dépôt"
        assert kit.refus_image(f.read_bytes()) is None, rel
