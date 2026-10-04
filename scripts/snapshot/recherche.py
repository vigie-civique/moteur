"""Les index de recherche : ce que le navigateur télécharge pour chercher sans serveur.

`entity_index.json` liste les fiches publiées, les plus citées d'abord ;
`recherche_index.json` mêle acteurs, actes, marchés et versements. Écrits
compacts : l'indentation y pèserait sans servir personne.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from scripts.snapshot.actes import PORTEE_PAR_PERIMETRE
from scripts.snapshot.socle import write_json_compact


def write_search_index(out: Path, public_entities, communes: dict[int, str],
                       liens_count: dict[int, int]) -> int:
    """Index de recherche léger, et liste des ids pour le prérendu.

    Le site public exposait 2 673 acteurs sans le moindre champ de recherche :
    pour trouver une association il fallait la repérer à l'œil sur la carte ou
    dans une grille. L'index tient dans ~150 Ko et se filtre côté client, sans
    backend (le public est statique).

    `nb` (nombre d'actes rattachés) sert à classer les résultats : un acteur
    présent dans dix délibérations passe avant un homonyme dormant.
    """
    index = [
        {
            "id": e["id"],
            "n": e["name"],
            "t": e["type"],
            "s": e.get("short_name") or None,
            "c": communes.get(e["id"]) or None,
            # `p` : la commune ou l'intercommunalité. Un caractère de plus par
            # ligne, et l'annuaire peut trier les deux sans charger
            # `entities.json` (1,1 Mo) juste pour lire un champ.
            "p": PORTEE_PAR_PERIMETRE.get(e.get("perimetre") or "") or "territoire",
            # `a` : 1 en activité, 0 cessée, absent si les registres se taisent.
            **({"a": 1 if e["actif"] else 0} if e.get("actif") is not None else {}),
            **({"na": e["nature"]} if e.get("nature") else {}),
            **({"dt": e["derniere_trace"]} if e.get("derniere_trace") else {}),
            "nb": liens_count.get(e["id"], 0),
        }
        for e in public_entities
    ]
    index.sort(key=lambda r: (-r["nb"], r["n"] or ""))
    write_json_compact(out / "entity_index.json", {"entities": index, "total": len(index)})
    return len(index)


def write_recherche_index(out: Path, public_entities, public_events,
                          marches_data, public_flows, communes: dict[int, str],
                          liens_count: dict[int, int]) -> int:
    """Index de recherche transversal : acteurs, actes, marchés, versements.

    La recherche ne portait que sur les acteurs. Or on ne cherche pas seulement
    « qui » : on cherche « piscine », « école », « assainissement », « 15 000 »,
    une parcelle, une année. Chercher un mot et ne trouver que des noms
    d'entreprises donne l'impression que le site ne sait rien d'un sujet dont
    il a pourtant les actes.

    Format court volontaire (`k`, `t`, `n`, `d`, `u`, `m`) : l'index est
    embarqué dans la page et chaque clé est répétée à chaque ligne.
    Les champs :
      k  catégorie  acteur | acte | marche | versement
      t  titre affiché
      n  poids de tri (plus grand = remonte)
      d  date, quand elle existe
      u  URL interne de destination
      m  montant, quand il y en a un
      c  commune ou contexte
    """
    idx: list[dict] = []

    for e in public_entities:
        idx.append({
            "k": "acteur", "t": e["name"], "u": f"/entite/{e['id']}",
            "c": communes.get(e["id"]) or None,
            "n": 1000 + liens_count.get(e["id"], 0),
        })

    for ev in public_events:
        annee = (ev.get("date") or "")[:4] or "sans-date"
        idx.append({
            "k": "acte", "t": ev.get("title") or "(sans titre)",
            # L'ancre est la clé datée de l'acte quand elle est stable : un
            # résultat de recherche copié et partagé doit survivre au rejeu.
            "u": f"/deliberations/{annee}#{ev.get('ancre') or 'a' + str(ev['id'])}",
            "d": ev.get("date"), "m": ev.get("montant_principal"),
            "c": ev.get("source"),
            # Un acte portant un montant est plus souvent ce qu'on cherche.
            "n": 500 + (200 if ev.get("montant_principal") else 0),
        })

    for m in marches_data:
        titre = m.get("objet") or "Marché"
        if m.get("titulaire_nom"):
            titre = f"{titre} — {m['titulaire_nom']}"
        idx.append({
            "k": "marche", "t": titre, "u": "/marches",
            "d": m.get("date_notif"), "m": m.get("montant"),
            "c": m.get("acheteur_nom"), "n": 600,
        })

    for f in public_flows:
        if not f.get("to_name"):
            continue
        idx.append({
            "k": "versement",
            "t": f"{f.get('type_norm') or f.get('type') or 'Flux'} — {f['to_name']}",
            "u": "/finances", "d": str(f["year"]) if f.get("year") else None,
            "m": f.get("amount"), "c": f.get("from_name"), "n": 400,
        })

    idx.sort(key=lambda r: (-r["n"], r["t"] or ""))
    write_json_compact(out / "recherche_index.json",
                       {"index": idx, "total": len(idx)})
    return len(idx)


def etape_index_recherche(out, entity_rows, public_entities, public_events,
                          public_links, marches_data, public_flows) -> dict:
    communes = {r["id"]: r.get("commune") for r in entity_rows}
    liens_count = Counter(l["entity_id"] for l in public_links)
    indexed = write_search_index(out, public_entities, communes, liens_count)
    recherche = write_recherche_index(out, public_entities, public_events,
                                      marches_data, public_flows,
                                      communes, liens_count)
    return {"indexed": indexed, "recherche": recherche}
