"""Les fichiers qui ne sont que la liste publiée, telle que les étapes l'ont arrêtée.

Aucune décision ici : chaque étape écrit ce qu'une étape précédente a
sélectionné, sous la clé racine que le site lit, avec son `total`.
"""
from __future__ import annotations

from scripts.snapshot.socle import write_json


def etape_ecrire_acteurs(out, public_entities, public_relations) -> None:
    write_json(out / "entities.json", {"entities": public_entities, "total": len(public_entities)})
    write_json(out / "relations.json", {"relations": public_relations, "total": len(public_relations)})


def etape_ecrire_actes(out, public_events) -> None:
    # `event_links.json` (quel acteur dans quel acte, 493 Ko à Lasalle) n'est
    # plus écrit depuis le 04/10/2026 : aucune page ne le lisait depuis que
    # chaque fiche porte ses actes (`entite/<id>.json`), et le retirer est la
    # décision 12 de docs/refonte-du-contenu.md.
    write_json(out / "events.json", {"events": public_events, "total": len(public_events)})


def etape_ecrire_flux(out, public_flows) -> None:
    write_json(out / "flows.json", {"flows": public_flows, "total": len(public_flows)})


#: Les couches de la carte, une par type d'acteur localisé (cf. `etape_couches`).
COUCHES = ("businesses", "associations", "places", "services")


def etape_ecrire_couches(out, public_layers) -> None:
    for layer, features in public_layers.items():
        write_json(out / "layers" / f"{layer}.geojson", {
            "type": "FeatureCollection",
            "features": features,
        })


def etape_ecrire_finances(out, budget_annuel, budget_annexe, budget_vote, ofgl_data,
                          dvf_data, marches_data, approbations_data) -> None:
    write_json(out / "budget.json", {"annuel": budget_annuel, "annexe": budget_annexe})
    write_json(out / "budget_vote.json", {"budget_vote": budget_vote, "total": len(budget_vote)})
    write_json(out / "ofgl.json", {"ofgl": ofgl_data, "total": len(ofgl_data)})
    write_json(out / "dvf.json", {"dvf": dvf_data, "total": len(dvf_data)})
    write_json(out / "marches.json", {"marches": marches_data, "total": len(marches_data)})
    write_json(out / "approbations.json",
               {"approbations": approbations_data, "total": len(approbations_data)})
