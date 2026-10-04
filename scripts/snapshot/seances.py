"""Les séances : une page par séance publiée, relue ou non.

Le site ne connaissait une séance que de deux façons : une ligne de l'accueil
qui menait au sommaire de toutes les années, ou une feuille « en clair » hors
du site pour les rares séances relues. Une séance n'avait pas de page à elle,
et elle portait deux nombres selon l'endroit — 39 délibérations sur l'accueil,
27 sur /conseils pour le même 28 mai 2026 (docs/refonte-du-contenu.md, § 2.2).

`seances.json` est l'index de ces pages. Il ne publie RIEN de nouveau : une
séance y figure parce que l'événement qui la porte est publié, ou parce que sa
feuille en clair l'est ; ses délibérations sont celles d'`events.json`, que la
page relit au build. L'index ne recopie donc pas les actes — il dit combien
il y en a, et, si la séance est relue, combien le relevé en compte.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from scripts.snapshot.actes import TYPES_DELIBERES, TYPES_SEANCE
from scripts.snapshot.socle import write_json

#: Le type d'une séance → son code de relevé, sa portée, son nom.
ASSEMBLEES = {
    "conseil_municipal": ("cm", "commune", "Conseil municipal", "conseil-municipal"),
    "conseil_communautaire": ("cc", "intercommunalite", "Conseil communautaire",
                              "conseil-communautaire"),
}
PAR_CODE = {v[0]: k for k, v in ASSEMBLEES.items()}


def identifiant(type_: str, date: str) -> str:
    """`2026-05-28_conseil-municipal` — le nom de la feuille en clair
    (`collectors.en_clair.seances.nom_de_fichier`), donc l'adresse
    `/conseils/<identifiant>` (décision 4)."""
    return f"{date}_{ASSEMBLEES[type_][3]}"


def index_des_seances(public_events: list[dict], seances_relues: list[dict]) -> list[dict]:
    """Une ligne par séance : celles dont l'événement est publié, plus celles
    dont seule la feuille en clair l'est. Plusieurs événements pour une même
    séance (le procès-verbal ET le compte rendu, collectés à part) font une
    seule séance, dont les pièces se cumulent."""
    # Les délibérations d'une séance : même date, même portée — la clé
    # qu'emploie déjà le fil d'actualité, parce que les deux conseils peuvent
    # siéger le même jour et que leurs actes ne s'additionnent pas.
    actes = Counter((e["date"], e.get("portee")) for e in public_events
                    if e["type"] in TYPES_DELIBERES and e.get("date"))

    seances: dict[str, dict] = {}
    pieces: dict[str, list] = defaultdict(list)
    for e in public_events:
        if e["type"] not in TYPES_SEANCE or not e.get("date"):
            continue
        code, portee, nom, _ = ASSEMBLEES[e["type"]]
        sid = identifiant(e["type"], e["date"])
        seances.setdefault(sid, {
            "id": sid, "date": e["date"], "code": code, "assemblee": nom,
            "portee": portee, "titre": e.get("title") or f"{nom} du {e['date']}",
            "nb_actes": actes.get((e["date"], portee), 0),
        })
        for p in e.get("pieces") or []:
            if p not in pieces[sid]:
                pieces[sid].append(p)

    for s in seances_relues:
        type_ = PAR_CODE.get(s.get("code") or "")
        if not type_:
            continue
        code, portee, nom, _ = ASSEMBLEES[type_]
        sid = identifiant(type_, s["date"])
        seances.setdefault(sid, {
            "id": sid, "date": s["date"], "code": code, "assemblee": nom,
            "portee": portee, "titre": f"{nom} du {s['date']}",
            "nb_actes": actes.get((s["date"], portee), 0),
        })["en_clair"] = {
            "fichier": s["fichier"], "titre": s["titre"], "relu_le": s["relu_le"],
            # Le nombre d'actes que le relevé a retrouvés dans le procès-verbal
            # et que la relecture a vérifiés. Il peut différer de `nb_actes`,
            # compté sur les délibérations publiées : la page donne les deux
            # (décision 10).
            "nb_actes": s["actes"],
        }

    for sid, s in seances.items():
        s["pieces"] = pieces.get(sid, [])
    return sorted(seances.values(), key=lambda s: (s["date"], s["code"]), reverse=True)


def etape_seances(out, public_events, seances_relues) -> dict:
    index = index_des_seances(public_events, seances_relues)
    write_json(out / "seances.json", {"seances": index, "total": len(index)})
    return {"stats_seances": {"seances": len(index),
                              "relues": sum(1 for s in index if s.get("en_clair"))}}
