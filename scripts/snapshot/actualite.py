"""« Ce qui a changé » : le fil d'actualité, construit sur les dates des actes publiés.

Marchés, actes et flux publiés, dédoublonnés et datés, triés du plus récent
au plus ancien ; les flux, qui n'ont qu'une année, regroupés à part. Aucun
état n'est gardé d'une construction à l'autre : le fil se recalcule.
"""
from __future__ import annotations

from collections import Counter

from scripts.snapshot.actes import PORTEE_PAR_PERIMETRE, TYPES_DELIBERES, TYPES_SEANCE
from scripts.snapshot.socle import safe_url, write_json
from scripts.snapshot.textes import TITRES_VIDES, joli_nom, nettoyer_libelle, norm_nom


def etape_actualite(out, stats, marches_data, public_events, public_flows,
                    perimetre_par_entite, exclusions) -> dict:
    # ── « Ce qui a changé » ───────────────────────────────────────────────
    # Le pipeline calcule déjà des deltas internes (audits/pipeline-digest.md),
    # mais un habitant ne veut pas savoir ce qui a changé dans notre base : il
    # veut savoir ce qui s'est passé dans sa commune. On construit donc le flux
    # à partir des DATES des actes publiés, ce qui a deux avantages : aucun
    # état à conserver entre deux exécutions, et un résultat toujours juste.
    aujourdhui = stats["generated_at"][:10]

    # Le genre pilote les filtres de la page. Il était fixé à « acte » pour
    # TOUS les événements : les 200 lignes d'agenda et les annonces BODACC
    # restaient invisibles au filtrage, sans onglet où les retrouver.
    def genre_evenement(t: str | None) -> str:
        t = t or ""
        if t == "local_event":
            return "vie"
        if t.startswith("bodacc"):
            return "légal"
        if t == "marché_public":
            return "marché"
        return "acte"

    actualite = []
    # Un même avis BOAMP existe en `events` ET en `marches_publics`, et la
    # table `events` porte en plus 164 doublons stricts (même URL, même
    # date) laissés par des passes de collecte successives. Sans clé de
    # dédup, la même benne à ordures s'affichait trois fois.
    vus: set[str] = set()

    def cle(url, titre, date):
        # Le titre fait TOUJOURS partie de la clé. L'URL seule regroupait
        # les 18 délibérations d'un même conseil, qui pointent toutes la
        # page du compte rendu : 17 d'entre elles disparaissaient du flux.
        return f"{safe_url(url) or ''}|{norm_nom(titre)}|{date}"

    # Les marchés d'abord : la fiche `marches_publics` porte le titulaire et
    # le montant, l'événement BOAMP équivalent ne porte que l'objet.
    for m in marches_data:
        if not m.get("date_notif"):
            continue
        k = cle(m.get("source_url"), m.get("objet"), m["date_notif"])
        if k in vus:
            continue
        vus.add(k)
        actualite.append({
            "date": m["date_notif"], "genre": "marché",
            "type": "marché_public",
            "titre": nettoyer_libelle(m.get("objet")),
            "url": safe_url(m.get("source_url")), "montant": m.get("montant"),
            "acteur_id": m.get("titulaire_id"),
            "acteur_nom": joli_nom(m.get("titulaire_nom") or m.get("acheteur_nom")),
            # C'est l'ACHETEUR qui donne la portée d'un marché, jamais le
            # titulaire : une entreprise de Nîmes qui remporte un marché de
            # la commune ne le rend pas nîmois.
            "portee": m.get("portee"),
        })

    # Combien d'actes chaque séance rassemble — (date, portée), parce que le
    # conseil municipal et le conseil communautaire peuvent siéger le même
    # jour et que leurs actes ne s'additionnent pas.
    actes_par_seance: Counter = Counter(
        (e["date"], e.get("portee")) for e in public_events
        if e["type"] in TYPES_DELIBERES and e.get("date"))

    for e in public_events:
        if not e.get("date"):
            continue
        titre = (e.get("title") or "").strip()
        if titre.lower().strip(" .:-—") in TITRES_VIDES:
            exclusions["actualite"]["titre_non_informatif"] += 1
            continue
        k = cle(e.get("source_url") or e.get("page_url"), titre, e["date"])
        if k in vus:
            exclusions["actualite"]["doublon"] += 1
            continue
        vus.add(k)
        actualite.append({
            "date": e["date"], "genre": genre_evenement(e.get("type")),
            "type": e.get("type"), "titre": titre,
            "url": e.get("source_url") or e.get("page_url"),
            "montant": e.get("montant_principal"),
            "montant_indicatif": e.get("montant_indicatif"),
            "categorie": e.get("categorie"), "id": e["id"],
            "portee": e.get("portee"),
            "corrige": e.get("corrige"), "note_revue": e.get("note_revue"),
            # Ce qu'une séance rassemble, et par quoi on l'atteint. Compté
            # ici parce que c'est le seul endroit qui voie tous les actes
            # publiés à la fois : un décompte pris en base compterait aussi
            # ceux que la publication écarte, et la page de garde
            # annoncerait plus d'actes qu'elle n'en donne à lire.
            **({"nb_actes": actes_par_seance.get(
                    (e["date"], e.get("portee")), 0),
                "pieces": e.get("pieces"),
                "convocation": e.get("convocation")}
               if e.get("type") in TYPES_SEANCE else {}),
        })

    for f in public_flows:
        if not f.get("year"):
            continue
        # Le flux entrant (dotation, fonds de concours) a pour contrepartie
        # celui qui verse, pas la commune qui encaisse : afficher
        # « Commune de Lasalle » en face de la DGF n'apprend rien.
        if f.get("sens") == "entrant":
            acteur_id, acteur_nom = f.get("from_id"), f.get("from_name")
        else:
            acteur_id, acteur_nom = f.get("to_id"), f.get("to_name")
        acteur_nom = joli_nom(acteur_nom)
        libelle = nettoyer_libelle(
            f.get("description") or f.get("type_norm") or f.get("type"),
            acteur_nom, f.get("amount"))
        actualite.append({
            # Un flux n'a que son millésime : le dater au 31/12 le projetait
            # dans le futur et lui donnait la tête du flux (26 lignes au
            # 31/12/2026 sur une page « ce qui a changé » arrêtée en juillet).
            # La page les sort de la frise et les regroupe par année.
            "date": f"{f['year']}-12-31", "annee": f["year"],
            "date_approx": True, "genre": "argent",
            "type": f.get("type_norm") or f.get("type"),
            "titre": libelle or "Flux financier",
            "montant": f.get("amount"),
            "acteur_id": acteur_id, "acteur_nom": acteur_nom,
            # Une demande de subvention n'est pas une subvention reçue :
            # 240 600 € de Fonds Vert *demandés* s'affichaient comme acquis.
            "statut": f.get("statut"),
            "perimetre": f.get("perimetre"),
            # À ne pas confondre avec `perimetre` juste au-dessus, qui dit
            # « detail » ou « agregat ». `portee` dit qui agit.
            "portee": PORTEE_PAR_PERIMETRE.get(
                perimetre_par_entite.get(acteur_id) or "") or "territoire",
            "sens": f.get("sens"),
            "corrige": f.get("corrige"), "note_revue": f.get("note_revue"),
        })

    # Tri sur une date bornée à la date d'arrêt des données : sans ça, les
    # dates approchées de l'année en cours passent devant tout le reste.
    # Tri en deux passes : le titre en ordre croissant d'abord, puis la date
    # en ordre décroissant (tri stable). Sans ça, les 18 délibérations du
    # même conseil sortaient dans l'ordre des id en base — DEL _18, _08,
    # _20, _19… — alors que leur numéro est leur ordre de séance.
    actualite.sort(key=lambda x: (x.get("titre") or ""))
    actualite.sort(
        key=lambda x: (min(x["date"], aujourdhui) if x.get("date_approx")
                       else x["date"]),
        reverse=True)
    a_venir = [i for i in actualite if i["date"] > aujourdhui and not i.get("date_approx")]
    write_json(out / "actualite.json", {
        "items": actualite[:400],
        "total": len(actualite),
        "arrete_le": aujourdhui,
        "genere_le": stats["generated_at"],
        "note": "Flux construit à partir des dates des actes publiés. "
                "Les flux financiers n'ont qu'une année : ils portent "
                "`date_approx` et sont regroupés par année, hors de la "
                "frise mensuelle. Les éléments datés après `arrete_le` sont "
                "des événements à venir.",
    })

    return {"actualite": actualite, "a_venir": a_venir}
