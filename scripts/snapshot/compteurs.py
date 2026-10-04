"""Les compteurs du snapshot : `stats.json`, et ce qui en découle.

`stats` est le seul fait que plusieurs étapes complètent : l'étape
`compteurs` le crée une fois tout sélectionné, `citations` y ajoute ce qu'elle
mesure, et l'étape finale y range le reste avant de l'écrire. L'ordre de ses
clés est celui de ces étapes, donc celui du registre.
"""
from __future__ import annotations

from collections import Counter

from collectors.config import STATUT
from scripts.snapshot.actes import TYPES_DELIBERES
from scripts.snapshot.socle import ROOT, rows, table_exists


def mesurer_replicabilite() -> dict:
    """Compte ce qui reste attaché à la commune, et le publie.

    /methode annonçait que « changer de commune tient dans un seul fichier de
    configuration » et que « ce site n'a pas à être modifié ». C'était faux, et
    publier le dépôt rendait l'écart vérifiable en trente secondes. Plutôt que
    de réécrire une promesse en la datant — elle dériverait à son tour — la page
    affiche une mesure refaite à chaque build.

    Le moteur est analysé par AST et non par expression régulière : documenter
    un piège oblige à écrire le nom de la commune dans une docstring, et un
    contrôle qui ne sait pas distinguer la doc du code se signale lui-même.
    Le site, lui, est du texte éditorial : toute occurrence y compte.
    """
    import importlib.util

    from collectors.config import COMMUNE_NAME

    # La mesure est déléguée à `verifier_generique.py`, qui est le contrôle
    # d'admission du kit : deux définitions du mot « moteur » finiraient par
    # diverger, et c'est arrivé. Celle d'ici listait `build_public_db.py`,
    # `migrate_perimetre.py` et `pipeline.py`, absents du dépôt depuis la
    # généricisation, sautés en silence par un `if not f.exists(): continue` —
    # la page /methode publiait donc une dette mesurée sur les trois quarts du
    # moteur. Elle ne comptait par ailleurs que le nom de la commune COURANTE,
    # là où le risque réel est le nom de la commune d'ORIGINE.
    chemin = ROOT / "scripts" / "verifier_generique.py"
    spec = importlib.util.spec_from_file_location("verifier_generique", chemin)
    vg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vg)

    communes = vg.communes_locales()
    constats_moteur = [c for f in vg._fichiers(vg.MOTEUR)
                       for c in vg.analyser(f, communes)
                       if c["motif"] == "nom_commune"]
    textes = [c for f in vg._fichiers_texte()
              for c in vg.analyser_texte(f, communes)]
    # Le site public et l'atelier sont deux dettes distinctes : l'une part en
    # production, l'autre non. Les additionner gonflerait le chiffre publié
    # d'un travail que le lecteur du site ne voit jamais.
    constats_site = [c for c in textes if c["fichier"].startswith("public/")]
    constats_atelier = [c for c in textes if c["fichier"].startswith("dashboard/")]

    def _compte(constats):
        return len({c["fichier"] for c in constats}), len(constats)

    moteur_f, moteur_o = _compte(constats_moteur)
    site_f, site_o = _compte(constats_site)
    atelier_f, atelier_o = _compte(constats_atelier)

    return {
        "commune": COMMUNE_NAME,
        "moteur_fichiers": moteur_f,
        "moteur_occurrences": moteur_o,
        "site_fichiers": site_f,
        "site_occurrences": site_o,
        "atelier_fichiers": atelier_f,
        "atelier_occurrences": atelier_o,
        # Ce que la mesure couvre, publié avec elle : un chiffre de dette sans
        # son périmètre se lit comme une garantie qu'il n'est pas.
        "noms_recherches": sorted(communes),
    }


def etape_compteurs(conn, horloge, sans_perimetre, entity_rows, public_entities,
                    ids_conseil_communautaire, relation_rows, public_relations,
                    event_rows, public_events, flow_rows, public_flows, flows_par_etat,
                    budget_annuel, budget_annexe, ofgl_data, dvf_data, marches_data,
                    approbations_data, public_layers, location_quality,
                    exclusions) -> dict:
    # Un statut déclaré est une promesse ; la date de dernière collecte est
    # un fait. C'est elle qui permet à un lecteur de vérifier le statut sans
    # croire personne : au bout de six mois, un portage de démonstration
    # affiche six mois. On prend la collecte, JAMAIS la publication — une
    # republication ne recollecte rien et ferait passer un site figé pour
    # un site vivant.
    derniere_collecte = None
    if table_exists(conn, "collector_runs"):
        _r = rows(conn, "SELECT MAX(started_at) AS d FROM collector_runs")
        derniere_collecte = (_r[0]["d"] or "")[:10] or None if _r else None

    stats = {
        "generated_at": horloge.isoformat(timespec="seconds"),
        "statut": {**STATUT, "derniere_collecte": derniere_collecte},
        "entities_total_private": len(entity_rows),
        "entities_public": len(public_entities),
        # Contrôle de publication : un site communal qui publierait
        # massivement du C2 aurait changé de nature sans qu'on le décide.
        "entities_public_par_perimetre": dict(
            Counter(e.get("perimetre") or "non_classe" for e in public_entities)),
        "entities_privees_par_perimetre": dict(
            Counter(e.get("perimetre") or "non_classe" for e in entity_rows)),
        # Entités jamais classées : exclues de la publication, comptées ici
        # pour que la lacune se voie au lieu de se deviner.
        "entities_sans_perimetre": sans_perimetre,
        "conseil_communautaire": len(ids_conseil_communautaire),
        "relations_total_private": len(relation_rows),
        "relations_public": len(public_relations),
        "events_total_private": len(event_rows),
        "events_public": len(public_events),
        # « 5 377 décisions » à l'accueil : le mot promettait un registre
        # des décisions locales et livrait le total des événements publics,
        # dont 3 061 annonces BODACC — la vie des entreprises, que personne
        # n'a votée — et 440 autorisations d'urbanisme individuelles. Un
        # habitant lisait « le conseil a pris 5 377 décisions ».
        # Ce qui a été délibéré se compte à part, et c'est ce chiffre-là que
        # l'accueil affiche. Le total reste publié, sous son vrai nom.
        "deliberations_public": sum(
            1 for e in public_events if e["type"] in TYPES_DELIBERES),
        # Le compteur unique disait « 1 997 délibérations » sur la page de
        # garde d'un site COMMUNAL, dont 833 votées par une autre assemblée.
        # Les deux chiffres existent, ils n'ont pas à être additionnés pour
        # être annoncés.
        "deliberations_public_par_portee": dict(Counter(
            e["portee"] for e in public_events if e["type"] in TYPES_DELIBERES)),
        "events_public_par_portee": dict(
            Counter(e.get("portee") for e in public_events)),
        # « 744 entreprises » comptait 377 fiches cessées. Le volume d'un
        # annuaire n'est pas l'état d'un territoire : les deux se comptent.
        "entities_public_par_activite": {
            t: dict(Counter(
                "en_activite" if e.get("actif") is True
                else "cessee" if e.get("actif") is False else "inconnu"
                for e in public_entities if e["type"] == t))
            for t in ("business", "association")},
        "entreprises_publiques_par_nature": dict(Counter(
            e.get("nature") for e in public_entities
            if e["type"] == "business")),
        "events_public_par_type": dict(
            Counter(e["type"] for e in public_events)),
        # Dette de réplication, mesurée et non promise (cf. /methode).
        "replicabilite": mesurer_replicabilite(),
        # Répartition sur les trois axes de provenance. C'est ce qui rend
        # la promesse mesurable : sans ces compteurs, « source primaire »
        # serait une affirmation de plus, invérifiable de l'extérieur.
        "provenance": {
            axe: dict(Counter(e.get(axe) for e in public_events))
            for axe in ("provenance", "document", "traitement")
        },
        "flows_total_private": len(flow_rows),
        "flows_public": len(public_flows),
        # Ce que les pièces attestent, en un coup d'oeil : sur Lasalle,
        # 123 votés, 36 payés, 2 engagés. Le compteur était calculé mais
        # restait dans un `Counter` local, donc invisible.
        "flows_par_etat": dict(flows_par_etat),
        "budget_annuel_rows": len(budget_annuel),
        "budget_annexe_rows": len(budget_annexe),
        "ofgl_rows": len(ofgl_data),
        "dvf_rows": len(dvf_data),
        "marches_rows": len(marches_data),
        "approbations_rows": len(approbations_data),
        "urls_public_confirmed": sum(len(e["urls"]) for e in public_entities),
        "map_features_public": sum(len(v) for v in public_layers.values()),
        "location_quality": dict(location_quality),
        "exclusions": {section: dict(counts) for section, counts in exclusions.items()},
    }

    return {"stats": stats}


def etape_bilan_revue(exclusions, revue_annotations, public_events, public_flows,
                      marches_data) -> dict:
    """Le relevé des exclusions tel que `stats.json` le publie, et ce que la
    revue de l'atelier a changé — arrêtés une fois le fil d'actualité filtré,
    dernière étape qui écarte quelque chose."""
    # `stats["exclusions"]` est figé plus haut, avant que le flux d'actualité
    # n'ait écarté ses doublons : on le réactualise, sinon le rapport de
    # revue tait précisément ce qui vient d'être filtré.
    exclusions_publiees = {s: dict(c) for s, c in exclusions.items()}
    revue_atelier = {
        "annotations": revue_annotations,
        "rejetes": sum(c.get("rejete_en_atelier", 0) for c in exclusions.values()),
        "corriges": sum(1 for e in public_events if e.get("corrige"))
                  + sum(1 for f in public_flows if f.get("corrige"))
                  + sum(1 for m in marches_data if m.get("corrige")),
    }

    return {"exclusions_publiees": exclusions_publiees, "revue_atelier": revue_atelier}
