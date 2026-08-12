"""
nom_normalise.py — Forme normalisée d'un nom d'entité, source unique de vérité.

Pourquoi
--------
SIRENE renvoie tantôt « Frédéric VERGNAUD », tantôt « Frederic VERGNAUD » selon
l'enregistrement, le JO des associations tantôt « Club d'aïkido de Lasalle »
tantôt « CLUB D'AIKIDO DE LASALLE ». `upsert_entity` déduplique sur
`(type, name)` EXACT : chaque variante créait une fiche, et le graphe d'un même
acteur se retrouvait coupé en deux. 27 personnes concernées au 11/08/2026.

`entities.name_norm` stocke cette forme, et `db.upsert_entity` la renseigne à
l'insertion. Une colonne GÉNÉRÉE en SQL a été essayée puis abandonnée le
12/08/2026 : dépiler les accents en SQL demande une soixantaine de REPLACE
imbriqués, et SQLite refuse ensuite de relire son propre schéma — « malformed
database schema (entities) - parser stack overflow ». La base devenait
illisible depuis le client `sqlite3`.

Conséquence à connaître : les scripts qui écrivent dans `entities` SANS passer
par `upsert_entity` (imports ponctuels de `scripts/`) laissent `name_norm` vide.
`scripts/migrate_nom_normalise.py --reparer` recalcule ce qui manque ; le pire
qu'une valeur absente puisse produire est un doublon, jamais une confusion.

Règle : minuscules, sans accents, tirets/apostrophes/points → espace, espaces
multiples réduits, extrémités élaguées.
"""
from __future__ import annotations

import unicodedata

# Caractères remplacés par un espace : ce sont des variantes de saisie, pas du
# sens. « Jean-Michel » et « Jean Michel », « L'ART SCENE. » et « L'ART SCÈNE »
# désignent la même chose.
SEPARATEURS = "-'’.,"

LIGATURES = {"Œ": "OE", "œ": "oe", "Æ": "AE", "æ": "ae"}


def normaliser(nom: str | None) -> str:
    """Forme normalisée d'un nom, utilisée pour retrouver une entité déjà en base."""
    s = unicodedata.normalize("NFD", nom or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    for lig, remp in LIGATURES.items():
        s = s.replace(lig, remp)
    for ch in SEPARATEURS:
        s = s.replace(ch, " ")
    return " ".join(s.lower().split())
