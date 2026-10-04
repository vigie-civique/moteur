"""L'ordre de fabrication du snapshot, déclaré une fois.

Chaque ligne dit quelle fonction tourne, ce qu'elle lit, ce qu'elle modifie en
place, ce qu'elle produit et quels fichiers elle écrit (cf.
`scripts/snapshot/registre.py`). `build_snapshot()` n'a plus qu'à exécuter
cette liste ; le manifeste du snapshot pourra dire, pour chaque fichier, quelle
étape l'a écrit.
"""
from __future__ import annotations

from scripts.snapshot.perimetre import etape_perimetre
from scripts.snapshot.personnes import etape_personnes_publiques
from scripts.snapshot.registre import Etape
from scripts.snapshot.revue import etape_revue

#: Les faits que `build_snapshot()` donne à la première étape : la connexion
#: (lecture seule), le répertoire de sortie, l'heure de la construction, et le
#: relevé des exclusions — ce que chaque filtre a écarté et pourquoi, que les
#: étapes complètent au fil de l'eau et que `stats.json` publie.
FOURNIS = ("conn", "out", "horloge", "exclusions")

ETAPES: list[Etape] = [
    Etape("perimetre", etape_perimetre,
          lit=("conn",), produit=("sans_perimetre",)),
    Etape("revue", etape_revue,
          lit=("conn",), produit=("revue", "revue_annotations", "relations_ecartees")),
    Etape("personnes_publiques", etape_personnes_publiques,
          lit=("conn", "relations_ecartees"),
          produit=("civic_person_ids", "beneficiaires", "public_person_ids",
                   "redige", "redactions", "noms_publics", "ids_conseil_communautaire")),
]
