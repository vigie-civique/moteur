"""
Dater un article de vie locale — commun à tous les connecteurs.

Un système de publication date la PUBLICATION, pas l'événement. Un article
« Concert à l'espace culturel » publié le 2 août peut annoncer un concert du 14.
On cherche donc une date dans le titre puis dans le corps ; faute de quoi on
retient la date de publication — et on dit laquelle des deux on a retenue.

Deux garde-fous, tirés de cas réels :

  - l'année manquante est celle de la publication, sauf si le mois est déjà
    passé : une annonce de décembre qui parle du « 12 janvier » parle de
    l'année suivante ;
  - une date lue n'est pas une date d'événement. Un article de fond sur la
    Résistance a fait entrer une animation municipale à l'agenda du 2 septembre
    1944. Toute date extraite d'un texte est donc bornée par le contexte qui la
    produit.
"""
from __future__ import annotations

import re

from .base import MOIS, date_fr

JOUR_MOIS = re.compile(
    r"\b(?:du\s+)?(\d{1,2})(?:\s*(?:er)?)?\s+(janvier|février|fevrier|mars|avril|"
    r"mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre)"
    r"(?:\s+(\d{4}))?", re.I)

# Fenêtre de plausibilité autour de la publication, en années.
AVANT, APRES = 1, 2


def date_evenement(titre: str, contenu: str, publie: str) -> tuple[str, str]:
    """(date ISO, origine) — origine vaut « texte » ou « publication »."""
    if not publie:
        return "", "publication"
    annee_pub, mois_pub = int(publie[:4]), int(publie[5:7])

    def plausible(iso: str) -> bool:
        return annee_pub - AVANT <= int(iso[:4]) <= annee_pub + APRES

    for texte in (titre, (contenu or "")[:1200]):
        iso = date_fr(texte)
        if iso and plausible(iso):
            return iso, "texte"
        m = JOUR_MOIS.search(texte or "")
        if not m:
            continue
        mois = MOIS.get(m.group(2).lower())
        if not mois:
            continue
        annee = int(m.group(3)) if m.group(3) else annee_pub
        if not m.group(3) and mois < mois_pub - 1:
            annee += 1
        iso = f"{annee}-{mois:02d}-{int(m.group(1)):02d}"
        if plausible(iso):
            return iso, "texte"
    return publie[:10], "publication"
