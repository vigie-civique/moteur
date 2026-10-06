"""Les conflits d'intérêts potentiels : un élu, une structure qu'il dirige, de l'argent public.

`conflits.json` ne dit pas qu'il y a faute — la loi n'interdit pas à un élu
de diriger une association subventionnée, elle lui impose de ne pas prendre
part au vote — : il met côte à côte le lien, les versements et les déports
consignés dans les comptes rendus.
"""
from __future__ import annotations

from scripts.snapshot.socle import relation_exists, rows, safe_url, write_json
from scripts.snapshot.textes import norm_nom


def _mots_significatifs(nom: str) -> set[str]:
    """Tokens discriminants d'un nom d'entité, pour rapprocher un titre de délib.

    On écarte les mots vides et les génériques (« ASSOCIATION », « COMITE »…) :
    sans ça, « Subvention — Comité des fêtes » se rapprocherait de n'importe
    quelle autre association portant le mot « comité ».
    """
    vides = {"ASSOCIATION", "ASSOC", "COMITE", "CLUB", "LES", "LE", "LA", "DE",
             "DES", "DU", "ET", "AMIS", "SOCIETE", "UNION", "L", "D", "EN", "AU"}
    return {m for m in norm_nom(nom).replace("(", " ").replace(")", " ").split()
            if len(m) >= 4 and m not in vides}


def deports_par_deliberation(conn, public_events: list[dict], redige) -> list[dict]:
    """Déports consignés dans les comptes rendus : « X ne participe pas ».

    Découverte du 26/07/2026 : `metadata.conflit_interet` de 15 délibérations
    nomme les élus qui se sont retirés du vote. C'est décisif pour la page
    publique : un élu qui dirige une association subventionnée n'est pas en
    faute s'il ne participe pas au vote. Sans cette information, la page
    accuserait là où le conseil a précisément fait ce qu'il devait.

    Seuls les actes PUBLIÉS : la base ne donne que la mention, le titre et le
    lien sont ceux qu'`events.json` porte — déjà masqués. Un acte que le
    snapshot ne retient pas ne peut pas ressortir par ici.
    """
    publies = {e["id"]: e for e in public_events}
    return [
        {"id": d["id"], "date": publies[d["id"]].get("date"),
         "title": publies[d["id"]].get("title") or "",
         "source_url": publies[d["id"]].get("source_url"),
         "mention": redige(str(d["mention"]))}
        for d in rows(conn, """
            SELECT ev.id,
                   json_extract(ev.metadata,'$.conflit_interet') AS mention
            FROM events ev
            WHERE json_extract(ev.metadata,'$.conflit_interet') IS NOT NULL
              AND json_extract(ev.metadata,'$.conflit_interet') NOT IN ('false','0','')
            ORDER BY ev.date
        """)
        if d["id"] in publies
    ]


def export_conflits(conn, public_ids: set[int], public_relations: list[dict],
                    public_flows: list[dict], public_events: list[dict], redige) -> dict:
    """Situations à vérifier : un élu lié à une structure qui reçoit de l'argent.

    Trois précautions structurent cet export :

    1. **Déduplication.** `v_conflits_potentiels` joint deux fois la table des
       relations : une personne cumulant `élu_cm` et `élu_cc` produit deux lignes
       pour un même versement. Publier « 14 situations » là où il y en a 7
       surévaluerait le phénomène. On regroupe sur (personne, entité, flux) et on
       agrège les rôles.
    2. **Le déport.** Chaque cas est confronté aux délibérations où l'élu est noté
       « ne participe pas ». Un déport constaté est la preuve que la règle a été
       respectée — c'est une information au moins aussi importante que le lien.
    3. **Périmètre.** Uniquement des relations `verified`/`confirmed` dont les
       deux extrémités sont publiques. `v_adresses_partagees` et
       `v_familles_potentielles` sont **exclues** (arbitrage du 26/07/2026) :
       une adresse commune n'établit rien et relève de la vie privée.

    ⚖️ La vue ne filtre rien — ni confiance, ni verdict de l'atelier, ni sort
    d'un acte. Elle ne sert qu'à croiser et à dater : un cas n'est retenu que
    si son mandat ET son lien avec la structure sont dans `relations.json`, un
    versement que s'il est dans `flows.json`, un déport que si l'acte est dans
    `events.json`. Cette précaution n'existait que dans le commentaire : une
    relation `hypothesis` sortait comme « situation à vérifier ».
    """
    if not relation_exists(conn, "v_conflits_potentiels"):
        return {"cas": [], "total": 0, "deports_repertories": 0, "methode": {}}

    brut = rows(conn, "SELECT * FROM v_conflits_potentiels")
    deports = deports_par_deliberation(conn, public_events, redige)
    liens_publies = {(frozenset((r["from_id"], r["to_id"])), r["relation_type"])
                     for r in public_relations}
    mandats_publies = {(bout, r["relation_type"])
                       for r in public_relations for bout in (r["from_id"], r["to_id"])}
    flux_publies = {f["id"] for f in public_flows}

    # Historique des mandats par personne. Indispensable pour ne PAS conclure.
    #
    # Cas typique : une personne n'a qu'un mandat en base (celui en cours),
    # aucun mandat clos, alors que les versements à la structure qu'elle dirige
    # remontent à plusieurs années. Conclure « antérieur au mandat » serait une
    # affirmation non fondée — le RNE ne diffuse que les mandats en cours, et
    # l'historique des mandatures précédentes est incomplet. Ces situations
    # sortent en `chronologie_incertaine`, jamais en « hors mandat ».
    mandats: dict[int, dict] = {}
    for m in rows(conn, """
        SELECT r.from_id AS pid, MIN(r.since) AS premier_debut,
               SUM(r.until IS NOT NULL) AS nb_clos
        FROM relations r
        WHERE r.relation_type IN ('élu_cm','élu_cc','adjoint','maire','candidat')
        GROUP BY r.from_id
    """):
        mandats[m["pid"]] = m
    ei_ids = {r["entity_id"] for r in rows(
        conn, "SELECT entity_id FROM businesses WHERE legal_form_code = '1000'")}

    groupes: dict[tuple, dict] = {}
    for r in brut:
        if r["person_id"] not in public_ids or r["entite_id"] not in public_ids:
            continue
        # Même filtre que pour le graphe : « Philippe BRISSAC dirige PHILIPPE
        # BRISSAC » n'est pas une situation à vérifier, c'est une entreprise
        # individuelle. 34 des 48 cas bruts étaient de cette nature — les
        # publier comme « liens à vérifier » aurait noyé les 4 cas réels et mis
        # en cause des élus pour avoir déclaré leur propre activité.
        if r["entite_id"] in ei_ids:
            continue
        if norm_nom(r["person_name"]) == norm_nom(r["entite_nom"]):
            continue
        if ((r["person_id"], r["role_elu"]) not in mandats_publies
                or (frozenset((r["person_id"], r["entite_id"])), r["role_entite"])
                not in liens_publies):
            continue
        # Un versement que `flows.json` ne publie pas (demande, piste, doublon
        # écarté) ne se cite pas : reste le lien, sans versement.
        if r["flux_id"] is not None and r["flux_id"] not in flux_publies:
            r = {**r, "flux_id": None, "flux_type": None, "flux_montant": None,
                 "flux_annee": None, "flux_date": None, "chronologie": "lien_sans_flux"}
        cle = (r["person_id"], r["entite_id"], r["flux_id"])
        cas = groupes.get(cle)
        if cas is None:
            cas = groupes[cle] = {
                "person_id": r["person_id"], "person_name": r["person_name"],
                "entite_id": r["entite_id"], "entite_nom": r["entite_nom"],
                "entite_type": r["entite_type"],
                "roles_elu": set(), "roles_entite": set(),
                "flux_id": r["flux_id"],
                "flux_type": r["flux_type"], "flux_montant": r["flux_montant"],
                "flux_annee": r["flux_annee"], "flux_date": r["flux_date"],
                "chronologies": set(),
                "mandat_debut": r["mandat_debut"], "mandat_fin": r["mandat_fin"],
            }
        cas["roles_elu"].add(r["role_elu"])
        cas["roles_entite"].add(r["role_entite"])
        cas["chronologies"].add(r["chronologie"])

    # Rapprochement des déports : nom de l'élu ET un mot discriminant de
    # l'entité dans le titre de la délibération, même année que le versement.
    avec_versement = {cle[:2] for cle in groupes if cle[2] is not None}
    cas_final = []
    for cle, cas in groupes.items():
        # « Lien sans versement » ne se dit que d'une paire qui n'en a aucun.
        if cle[2] is None and cle[:2] in avec_versement:
            continue
        nom_norm = norm_nom(cas["person_name"])
        tokens_pers = {m for m in nom_norm.split() if len(m) >= 3}
        tokens_entite = _mots_significatifs(cas["entite_nom"])
        trouve = None
        for d in deports:
            mention = norm_nom(d["mention"])
            if not tokens_pers & set(mention.split()):
                continue
            titre = norm_nom(d["title"])
            if tokens_entite and not (tokens_entite & set(titre.split())):
                continue
            if cas["flux_annee"] and d["date"] and str(cas["flux_annee"]) not in d["date"]:
                continue
            trouve = {"event_id": d["id"], "date": d["date"], "titre": d["title"],
                      "mention": d["mention"], "source_url": safe_url(d["source_url"])}
            break

        cas["roles_elu"] = sorted(cas["roles_elu"])
        cas["roles_entite"] = sorted(cas["roles_entite"])
        cas["deport"] = trouve

        # Chronologie : la vue produit une ligne par mandat. Un élu réélu a
        # plusieurs mandats, et le versement de 2021 est « antérieur » au mandat
        # de 2026 tout en étant contemporain de celui de 2020. La question posée
        # est « était-il élu quand l'argent a été voté ? » : il suffit donc
        # qu'UN mandat couvre le versement. Sans cette agrégation, des
        # subventions votées en pleine mandature ressortaient « hors mandat ».
        chronos = cas.pop("chronologies")
        for niveau in ("contemporain", "chevauchement_annee",
                       "anterieur_mandat", "hors_mandat", "dates_manquantes",
                       "lien_sans_flux"):
            if niveau in chronos:
                cas["chronologie"] = niveau
                break
        else:
            cas["chronologie"] = "indetermine"
        # Vocabulaire volontairement non accusatoire : l'absence de trace n'est
        # pas une preuve d'absence de déport, les CR ne sont pas tous exploités.
        if cas["flux_id"] is None or cas["flux_montant"] is None:
            cas["statut"] = "lien_sans_versement"
        elif trouve:
            cas["statut"] = "deport_constate"
        elif cas["chronologie"] == "anterieur_mandat":
            # Antérieur aux mandats CONNUS. Si la personne n'a aucun mandat clos
            # en base, son historique est incomplet : on ne conclut pas.
            m = mandats.get(cas["person_id"]) or {}
            cas["statut"] = ("hors_mandat" if (m.get("nb_clos") or 0) > 0
                             else "chronologie_incertaine")
        elif cas["chronologie"] == "hors_mandat":
            cas["statut"] = "hors_mandat"
        else:
            cas["statut"] = "deport_non_trouve"
        cas_final.append(cas)

    cas_final.sort(key=lambda c: (-(c["flux_montant"] or 0), c["person_name"]))
    return {
        "cas": cas_final,
        "total": len(cas_final),
        "deports_repertories": len(deports),
        "methode": {
            "source_liens": "relations vérifiées entre une personne à mandat "
                            "électif et une structure qu'elle dirige",
            "source_versements": "subventions et flux financiers de la commune "
                                 "(périmètre 'detail', statut 'réalisé')",
            "source_deports": "mentions « ne participe pas » relevées dans les "
                              "comptes rendus du conseil municipal",
            "exclusions": ["adresses partagées", "liens familiaux présumés",
                           "relations probable / hypothesis"],
            "avertissement": "Un lien n'est pas une faute. La loi n'interdit pas "
                             "à un élu de diriger une association subventionnée : "
                             "elle lui impose de ne pas participer au vote. "
                             "L'absence de déport constaté ici peut simplement "
                             "signifier que le compte rendu correspondant n'a pas "
                             "encore été exploité.",
        },
    }


def etape_conflits(conn, out, public_ids, public_relations, public_flows,
                   public_events, redige) -> dict:
    conflits = export_conflits(conn, public_ids, public_relations, public_flows,
                               public_events, redige)
    write_json(out / "conflits.json", conflits)
    return {"conflits": conflits}
