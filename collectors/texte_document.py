#!/usr/bin/env python3
"""texte_document.py — le texte d'un document, quel que soit son format.

Un procès-verbal n'est pas toujours un PDF. Sur la première commune portée, le
compte rendu de la séance budgétaire d'avril 2026 est une PAGE HTML, sans pièce
jointe : le catalogue la voyait, le lecteur la refusait — « pas un PDF » — et
la séance entière manquait, avec les huit budgets qu'elle votait. D'autres
collectivités déposent un traitement de texte, ou un simple fichier texte.

Le format se lit dans les OCTETS, jamais dans l'extension : les sites servent des
PDF sous des adresses sans suffixe, et des pages HTML sous des adresses en `.pdf`
quand le fichier a disparu et que le serveur répond par sa page d'erreur. Une
page d'erreur enregistrée comme un procès-verbal vide serait pire que rien.

Ce module ne lit pas les PDF : ils demandent un fichier sur disque, un cache et
parfois une reconnaissance optique — cf. `conseils.py`. Il reconnaît leur
signature, et laisse l'appelant faire.

Ce qui sort d'ici est du texte brut destiné à `pv_parsers`, avec une exigence
précise héritée des tableaux budgétaires : **deux cellules voisines restent
séparées par une espace, deux lignes par un saut de ligne**. C'est ce qui permet
de distinguer un budget voté (une colonne de montants) d'un compte financier
(deux colonnes) — coller les cellules ferait de « 177 717.01 » et « 175 149.78 »
un seul nombre, et de deux colonnes une seule.
"""
from __future__ import annotations

import re
import zipfile
from html.parser import HTMLParser
from io import BytesIO

# Balises qui ferment un bloc : leur fin doit produire un saut de ligne, sinon la
# dernière cellule d'une ligne de tableau colle au premier nombre de la suivante.
_BLOCS = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6",
          "table", "section", "article", "header", "footer", "blockquote", "pre"}
# Balises dont le contenu n'est pas du texte de page.
_MUETTES = {"script", "style", "noscript", "svg", "template"}


class _Texte(HTMLParser):
    """Extrait le texte d'une page en préservant les frontières de cellules."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.morceaux: list[str] = []
        self._muet = 0

    def handle_starttag(self, tag, attrs):
        if tag in _MUETTES:
            self._muet += 1
        elif tag in _BLOCS:
            self.morceaux.append("\n")
        elif tag in ("td", "th"):
            # Une espace, pas un saut : l'étiquette d'une ligne de tableau et son
            # montant sont deux cellules, et doivent se lire comme une phrase.
            self.morceaux.append(" ")

    def handle_endtag(self, tag):
        if tag in _MUETTES:
            self._muet = max(0, self._muet - 1)
        elif tag in _BLOCS:
            self.morceaux.append("\n")

    def handle_data(self, data):
        if not self._muet:
            self.morceaux.append(data)

    def texte(self) -> str:
        brut = "".join(self.morceaux)
        # Les espaces insécables des pages web deviennent des espaces ordinaires
        # DANS le texte rendu, mais les séparateurs de milliers des tableaux
        # budgétaires en sont : ils sont conservés tels quels par les analyseurs,
        # qui les acceptent déjà.
        brut = re.sub(r"[ \t\r\f\v]+", " ", brut)
        brut = re.sub(r" *\n[ \n]*", "\n", brut)
        return brut.strip()


def format_de(donnees: bytes, content_type: str = "") -> str:
    """« pdf », « html », « office », « texte » ou « inconnu ».

    La signature d'abord, l'en-tête HTTP ensuite. L'adresse ne sert jamais : un
    fichier disparu est souvent servi comme une page d'erreur sous une adresse
    qui finit toujours par `.pdf`.
    """
    debut = donnees[:2048]
    if donnees.startswith(b"%PDF-"):
        return "pdf"
    if donnees.startswith(b"PK\x03\x04"):
        return "office" if _est_office(donnees) else "inconnu"
    if donnees.startswith(b"{\\rtf"):
        # Reconnu pour n'être PAS pris pour du texte brut : décodé tel quel, un
        # RTF donne des pages de balises qui passeraient pour un procès-verbal.
        return "inconnu"

    tete = debut.lstrip().lower()
    if tete.startswith(b"<!doctype html") or tete.startswith(b"<html") \
            or b"<head" in tete or b"<meta" in tete:
        return "html"
    if "text/html" in content_type.lower():
        return "html"
    if content_type.lower().startswith("text/"):
        return "texte"
    # Une page servie sans en-tête ni doctype reste reconnaissable à ses balises.
    if b"<body" in debut.lower() or b"<div" in debut.lower():
        return "html"
    try:
        debut.decode("utf-8")
    except UnicodeDecodeError:
        return "inconnu"
    return "texte" if debut.strip() else "inconnu"


def _est_office(donnees: bytes) -> bool:
    try:
        with zipfile.ZipFile(BytesIO(donnees)) as z:
            noms = set(z.namelist())
        return "word/document.xml" in noms or "content.xml" in noms
    except (zipfile.BadZipFile, OSError):
        return False


def texte_html(donnees: bytes | str) -> str:
    if isinstance(donnees, bytes):
        donnees = donnees.decode("utf-8", errors="replace")
    parseur = _Texte()
    parseur.feed(donnees)
    parseur.close()
    return parseur.texte()


def texte_office(donnees: bytes) -> str:
    """.docx et .odt : deux ZIP dont un XML porte le texte.

    Sans bibliothèque tierce — ces deux formats sont des archives, et la seule
    chose qu'on leur demande est leur suite de paragraphes.
    """
    try:
        with zipfile.ZipFile(BytesIO(donnees)) as z:
            noms = z.namelist()
            interne = ("word/document.xml" if "word/document.xml" in noms
                       else "content.xml" if "content.xml" in noms else None)
            if not interne:
                return ""
            xml = z.read(interne).decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, OSError, KeyError):
        return ""
    # Fins de paragraphe et de cellule d'abord, pour la même raison qu'en HTML.
    xml = re.sub(r"</(w:p|text:p|w:tc|table:table-cell)>", " \n", xml)
    xml = re.sub(r"<[^>]+>", "", xml)
    return re.sub(r"[ \t]+", " ", xml).strip()


def texte_de(donnees: bytes, format_: str) -> str:
    """Texte d'un document déjà téléchargé, hors PDF (cf. le module docstring)."""
    if format_ == "html":
        return texte_html(donnees)
    if format_ == "office":
        return texte_office(donnees)
    if format_ == "texte":
        return donnees.decode("utf-8", errors="replace")
    return ""
