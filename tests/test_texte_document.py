"""Lire un procès-verbal quel que soit son format — et surtout, sans se tromper
sur le format.

Le lecteur de séances n'acceptait que les PDF. Sur la première commune, le
compte rendu de la séance budgétaire d'avril 2026 est une page HTML sans pièce
jointe : elle était cataloguée, refusée à la lecture, et la séance entière
manquait — vingt délibérations et huit budgets.

Deux exigences se cachent derrière « lire une page » :

  1. le format vient des OCTETS. Un fichier retiré est souvent servi sous son
     ancienne adresse en `.pdf` par une page d'erreur, qu'on enregistrerait
     sinon comme un procès-verbal vide ;
  2. les frontières de cellules survivent. Deux montants voisins collés l'un à
     l'autre ne se distinguent plus, et un tableau à deux colonnes se lit comme
     un tableau à une.
"""
from __future__ import annotations

import io
import zipfile

import pytest


@pytest.fixture(scope="module")
def td():
    from collectors import texte_document
    return texte_document


# ── Le format se lit dans les octets ─────────────────────────────────────────

def test_pdf_reconnu(td):
    assert td.format_de(b"%PDF-1.7\n%\xc3\xa4\xc3\xbc") == "pdf"


def test_page_derreur_servie_sous_une_adresse_pdf(td):
    """Le cas qui compte : le serveur répond 200 avec sa page d'erreur. Sans
    lecture des octets, elle deviendrait une séance sans texte."""
    assert td.format_de(b"<!DOCTYPE html><html><body>404</body></html>") == "html"


def test_content_type_en_second_recours(td):
    assert td.format_de(b"Conseil municipal du 12 mai", "text/plain; charset=utf-8") == "texte"


def test_rtf_nest_pas_du_texte_brut(td):
    """Décodé tel quel, un RTF donne des pages de balises qui passeraient pour
    un procès-verbal."""
    assert td.format_de(rb"{\rtf1\ansi Conseil municipal}") == "inconnu"


def test_zip_quelconque_refuse(td):
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w") as z:
        z.writestr("photo.jpg", b"...")
    assert td.format_de(tampon.getvalue()) == "inconnu"


def test_traitement_de_texte_reconnu_et_lu(td):
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w") as z:
        z.writestr("content.xml",
                   "<office><text:p>TOTAL DES DEPENSES</text:p>"
                   "<text:p>320 283,30</text:p></office>")
    donnees = tampon.getvalue()
    assert td.format_de(donnees) == "office"
    lu = td.texte_de(donnees, "office")
    assert "TOTAL DES DEPENSES" in lu and "320 283,30" in lu


# ── Les frontières de cellules survivent à l'extraction ──────────────────────

TABLEAU = """
<html><body>
<h3>DEPENSES D'INVESTISSEMENT</h3>
<table>
  <tr><th>Chap / Art</th><th>Intitulé</th><th>Restes à réaliser</th><th>BP 2026</th></tr>
  <tr><td>204</td><td>Subvention d'équipement</td><td>57 330,40</td><td>68 968,27</td></tr>
  <tr><td colspan="2">TOTAL DES DEPENSES</td><td>57 330,40</td><td>320 283,30</td></tr>
</table>
<script>var suivi = "ne doit pas sortir";</script>
</body></html>
"""


def test_deux_cellules_voisines_restent_separees(td):
    """Sans cette espace, « 57 330,40 » et « 320 283,30 » deviendraient un seul
    nombre, et deux colonnes une seule."""
    lu = td.texte_html(TABLEAU)
    assert "57 330,40 320 283,30" in " ".join(lu.split("\n"))
    assert "57 330,40320 283,30" not in lu


def test_letiquette_et_son_montant_se_lisent_ensemble(td):
    lu = " ".join(td.texte_html(TABLEAU).split())
    assert "TOTAL DES DEPENSES 57 330,40 320 283,30" in lu


def test_le_script_ne_sort_pas(td):
    assert "ne doit pas sortir" not in td.texte_html(TABLEAU)


def test_les_lignes_ne_se_collent_pas(td):
    """La dernière cellule d'une ligne et le premier chiffre de la suivante
    doivent rester séparés, sinon le total d'un tableau avale le chapitre du
    dessous."""
    lignes = [l for l in td.texte_html(TABLEAU).split("\n") if l.strip()]
    assert any(l.strip().startswith("204") for l in lignes)
