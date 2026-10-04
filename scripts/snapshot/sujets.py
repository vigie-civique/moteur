"""Les sujets : le pont entre un dossier thématique et les données qui en parlent.

Les dossiers renvoyaient aux actes, jamais aux pages de données ; les pages de
données (/environnement, /territoire) avaient des sections ancrées sur le même
sujet — l'eau, les déchets, la forêt, l'enfance, les télécoms — et ne citaient
aucun dossier. Trois îles (docs/refonte-du-contenu.md, § 1.5).

Le registre ci-dessous est générique : il ne nomme aucune commune. Ses
identifiants sont ceux des dossiers (décision 13), si bien qu'un dossier se
rattache à son sujet par son nom de fichier ; un en-tête `sujet:` peut le
rattacher autrement.

`sujets.json` dit, pour CETTE instance, si chaque sujet a des données publiées
et un dossier publié. Une instance sans dossier y trouve de quoi montrer « ce
que les données disent de… » sans rien écrire — donc sans rien à relire.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.snapshot.socle import INSEE_C1, write_json


def _lire(out: Path, nom: str) -> dict:
    try:
        return json.loads((out / nom).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


#: identifiant → titre, sections de données (page, ancre, titre de la section),
#: et ce qui dit qu'une section a du contenu — la même condition que la page
#: qui l'affiche. Les fichiers lus sont écrits par les étapes `environnement`
#: et `territoire`, qui précèdent celle-ci dans le registre.
SUJETS = (
    ("eau", "L'eau", (("/environnement", "eau-du-robinet", "L'eau du robinet"),),
     lambda env, ter: bool(env.get("sispea_services")
                           or (env.get("eau_controle") or {}).get("reseaux"))),
    ("dechets", "Les déchets", (("/environnement", "dechets", "Les déchets ménagers"),),
     lambda env, ter: bool((env.get("dechets") or {}).get("acteurs"))),
    ("incendie", "La forêt et le feu", (("/environnement", "foret-et-feu", "La forêt et le feu"),),
     lambda env, ter: bool(env.get("incendie"))),
    ("enfance", "L'enfance", (("/territoire", "enfance", "L'école et les tout-petits"),),
     lambda env, ter: bool(ter.get("enfance"))),
    ("telecoms", "Internet et téléphone", (("/territoire", "telecoms", "Internet et téléphone"),),
     lambda env, ter: bool(ter.get("telecoms"))),
    ("logement", "Le logement",
     (("/territoire", "logement", "Logement : la part des résidences secondaires"),
      ("/urbanisme", "", "Urbanisme & transactions foncières")),
     # La condition de la page : la série des logements DE LA COMMUNE.
     lambda env, ter: any(r.get("insee") == INSEE_C1 and r.get("indicateur") == "DWELLINGS"
                          and r.get("valeur") is not None for r in ter.get("insee") or [])),
    # Sans section de données : un dossier seul peut les porter.
    ("sante", "La santé", (), lambda env, ter: False),
    ("mourir", "La fin de vie", (), lambda env, ter: False),
)


def index_des_sujets(out: Path, dossiers_publies: list[dict]) -> list[dict]:
    env, ter = _lire(out, "environnement.json"), _lire(out, "territoire.json")
    par_sujet = {d.get("sujet") or d["slug"]: d["slug"] for d in dossiers_publies}
    return [{
        "id": sid, "titre": titre,
        "sections": [{"page": p, "ancre": a, "titre": t} for p, a, t in sections],
        "donnees": bool(sections) and presente(env, ter),
        "dossier": par_sujet.get(sid),
    } for sid, titre, sections, presente in SUJETS]


def etape_sujets(out, dossiers_publies) -> dict:
    index = index_des_sujets(out, dossiers_publies)
    write_json(out / "sujets.json", {"sujets": index, "total": len(index)})
    return {"stats_sujets": {"avec_donnees": sum(1 for s in index if s["donnees"]),
                             "avec_dossier": sum(1 for s in index if s["dossier"])}}
