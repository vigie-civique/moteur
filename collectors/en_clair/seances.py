"""Les relevés d'une instance, et la séance que chacun décrit.

Lu par l'atelier (la file « Conseils en clair ») et par la publication : un
seul rapprochement entre un relevé et sa séance, sinon l'atelier retiendrait
une feuille que la publication rattacherait à une autre.
"""
from __future__ import annotations

import json
from pathlib import Path

#: Le code d'un relevé (`2026-03-04-cc`) → le type de l'événement séance.
TYPE_DE_SEANCE = {"cm": "conseil_municipal", "cc": "conseil_communautaire"}


def dossier(root: Path) -> Path:
    return root / "data" / "conseils"


def releves(root: Path) -> list[tuple[Path, dict]]:
    """(chemin, relevé) de chaque séance relevée, par date. Un relevé illisible
    est tu ici : c'est le vérificateur qui le signale, pas la liste."""
    sortie = []
    for p in sorted(dossier(root).glob("*/releve.json")):
        try:
            sortie.append((p, json.loads(p.read_text())))
        except (OSError, json.JSONDecodeError):
            continue
    sortie.sort(key=lambda x: (x[1].get("seance", {}).get("date", ""), x[1].get("code", "")))
    return sortie


def seance_id(conn, releve: dict) -> int | None:
    """L'identifiant de la séance en base — la clé du verdict `en_clair`.

    Une séance est identifiée par sa date et son assemblée
    (`conseils.enregistrer_seance`) : c'est donc la même clé ici.
    """
    type_ = TYPE_DE_SEANCE.get(releve.get("code", ""))
    date = (releve.get("seance") or {}).get("date")
    if not type_ or not date:
        return None
    r = conn.execute("SELECT id FROM events WHERE type=? AND date=? ORDER BY id LIMIT 1",
                     (type_, date)).fetchone()
    return r[0] if r else None


def nom_de_fichier(releve: dict) -> str:
    """`2026-03-04_conseil-communautaire` — le nom publié, sans extension."""
    assemblee = "conseil-municipal" if releve.get("code") == "cm" else "conseil-communautaire"
    return f"{releve['seance']['date']}_{assemblee}"
