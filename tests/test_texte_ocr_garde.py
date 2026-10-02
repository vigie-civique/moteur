"""Le texte reconnu se garde à côté du PDF océrisé — `x.ocr.pdf` → `x.ocr.txt`.

02/10/2026, avant de porter la collecte sur un serveur. Le cache de la
reconnaissance optique était le PDF océrisé lui-même : 10 Go sur l'instance de
référence, pour 11 Mo de texte, rouverts à chaque passe. Une machine qui n'a
que les textes doit lire le corpus sans océriser — et sans savoir océriser.

Aucun PDF réel ici : ce qui se teste est le choix entre le texte gardé, le PDF
océrisé et l'outil, pas la lecture d'un PDF.
"""
from __future__ import annotations

import os
import shutil

import pytest

from collectors import cm_ocr, conseils


@pytest.fixture
def pv(tmp_path, monkeypatch):
    """Un original scanné, et de quoi savoir qui a été ouvert."""
    original = tmp_path / "pv-2019.pdf"
    original.write_bytes(b"%PDF-1.4 scan")
    ouverts = []

    def lecture(chemin):
        ouverts.append(chemin.name)
        return "TEXTE LU DANS LE PDF OCÉRISÉ" if chemin.name.endswith(".ocr.pdf") else ""
    monkeypatch.setattr(conseils, "texte_pdf", lecture)
    monkeypatch.setattr(cm_ocr, "_extract_text", lecture)
    # Aucun outil d'OCR sur cette machine : un appel serait une erreur du test.
    monkeypatch.setattr(shutil, "which", lambda nom: None)
    return original, ouverts


def test_la_premiere_lecture_garde_le_texte(pv):
    original, ouverts = pv
    original.with_suffix(".ocr.pdf").write_bytes(b"%PDF-1.4 ocr")
    assert conseils.ocr(original) == "TEXTE LU DANS LE PDF OCÉRISÉ"
    assert original.with_suffix(".ocr.txt").read_text() == "TEXTE LU DANS LE PDF OCÉRISÉ"


def test_la_suivante_ne_rouvre_plus_le_pdf(pv):
    original, ouverts = pv
    original.with_suffix(".ocr.pdf").write_bytes(b"%PDF-1.4 ocr")
    conseils.ocr(original)
    ouverts.clear()
    assert conseils.ocr(original) == "TEXTE LU DANS LE PDF OCÉRISÉ"
    assert ouverts == []


def test_le_texte_seul_suffit_sans_pdf_ocerise_ni_outil(pv):
    """Le cas du serveur : ni `.ocr.pdf` (10 Go restés ailleurs), ni ocrmypdf."""
    original, ouverts = pv
    original.with_suffix(".ocr.txt").write_text("TEXTE VENU D'UNE AUTRE MACHINE")
    assert conseils.ocr(original) == "TEXTE VENU D'UNE AUTRE MACHINE"
    assert cm_ocr.ensure_text(original) == "TEXTE VENU D'UNE AUTRE MACHINE"
    assert [n for n in ouverts if n.endswith(".ocr.pdf")] == []


def test_une_reocerisation_adoptee_l_emporte_sur_l_ancien_texte(pv):
    original, _ = pv
    garde, ocerise = original.with_suffix(".ocr.txt"), original.with_suffix(".ocr.pdf")
    garde.write_text("TEXTE DE L'ANCIENNE OCÉRISATION")
    ocerise.write_bytes(b"%PDF-1.4 ocr refait")
    os.utime(garde, (1_000_000, 1_000_000))            # le texte date d'avant le PDF
    assert conseils.ocr(original) == "TEXTE LU DANS LE PDF OCÉRISÉ"
    assert garde.read_text() == "TEXTE LU DANS LE PDF OCÉRISÉ"


def test_un_texte_vide_ne_se_garde_pas(pv, monkeypatch):
    """Il dirait « déjà lu, rien dedans » d'un document qu'on n'a pas su lire."""
    original, _ = pv
    original.with_suffix(".ocr.pdf").write_bytes(b"%PDF-1.4 ocr")
    monkeypatch.setattr(conseils, "texte_pdf", lambda chemin: "   \n")
    conseils.ocr(original)
    assert not original.with_suffix(".ocr.txt").exists()


def test_sans_texte_ni_pdf_ni_outil_rien_n_est_invente(pv):
    original, _ = pv
    assert conseils.ocr(original) == ""
    assert not original.with_suffix(".ocr.txt").exists()
