"""Les actes publiés : délibérations, séances, arrêtés, annonces.

L'étape `actes` lit les événements en base, applique le verdict de l'atelier
et les règles de publication, et rend les actes publiés avec leur détail
délibératif (vote, montant décidé), leur provenance sur trois axes, et le
texte des délibérations qui peut sortir — masqué, cf.
`scripts/snapshot/textes.py`.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter, defaultdict

from collectors.citations import acte_de_ligne, index_de, lignes_en_base
from scripts.snapshot.revue import TYPES_REVUS, appliquer_revue
from scripts.snapshot.socle import RULES, URL_COMMUNE, URL_EPCI, rows, safe_url
from scripts.snapshot.textes import (convocation_publique, masquer_donnees_personnelles,
                                     nettoyer_titre_evenement, texte_publiable)


# Ce qu'un conseil a effectivement délibéré — communal et intercommunal. Sert
# le compteur affiché à l'accueil : un site de contrôle de l'action publique
# doit pouvoir dire ce qu'il compte quand il écrit « délibérations ». Les
# séances (`conseil_municipal`, `conseil_communautaire`) sont des contenants,
# pas des décisions : les compter doublerait les actes qu'elles portent.
TYPES_DELIBERES = ("deliberation", "deliberation_cc")
# L'événement ombrelle d'une séance. Il n'est pas un acte : il ne décide rien,
# il rassemble ce qui a été décidé ce jour-là, et porte les pièces qui
# l'attestent — convocation, registre, procès-verbal.
TYPES_SEANCE = ("conseil_municipal", "conseil_communautaire")


# Fourchette de montants publiables pour un acte local : en dessous, c'est un
# numéro d'article pris pour un euro ; au-dessus, une concaténation OCR.
MONTANT_MIN = 10
MONTANT_MAX = 50_000_000


# Ce qu'un montant est, dans une délibération.
#
# Le contexte de chaque montant est capté à l'extraction (80 caractères avant,
# 40 après) : il dit souvent ce que le chiffre représente. Une délibération de
# subvention écrit « Montant demandé : 2 200 € ; Montant attribué : 500 € » —
# retenir le plus élevé, c'est publier la DEMANDE comme si le conseil l'avait
# votée. C'est ce qui affichait « 2 200 € » sur un acte où 100 € ont été votés.
DEMANDE_RE = re.compile(
    r"(demand\w+|sollicit\w+|estim\w+|propos\w+|devis|prévisionnel\w*)", re.I)
ACCORDE_RE = re.compile(
    r"(attribu\w+|accord\w+|allou\w+|vot\w+|vers\w+|octroi\w+)", re.I)


def _sans_accents(t: str) -> str:
    return unicodedata.normalize("NFKD", (t or "").lower()) \
        .encode("ascii", "ignore").decode()


def montant_de_la_decision(montants: list, titre: str | None = None) -> tuple[float | None, list]:
    """Le montant DÉCIDÉ, et les autres — plutôt que le plus gros du texte.

    Trois règles, de la plus sûre à la plus faible :

    1. si des montants sont dits ACCORDÉS (« DECIDE d'attribuer … 100 € »),
       la décision est parmi eux ;
    2. sinon, les montants explicitement DEMANDÉS sont écartés du calcul ;
    3. entre plusieurs candidats, celui dont le contexte nomme le titre de
       l'acte l'emporte — un bloc de subventions en contient plusieurs, un par
       association, et le titre dit de laquelle il s'agit.

    À défaut, on retombe sur le plus élevé, comme avant.
    """
    retenus = []
    for m in montants:
        v = m.get("montant", m.get("value")) if isinstance(m, dict) else m
        if not isinstance(v, (int, float)) or not (MONTANT_MIN <= v <= MONTANT_MAX):
            continue
        ctx = m.get("context", "") if isinstance(m, dict) else ""
        retenus.append((v, ctx, bool(ACCORDE_RE.search(ctx)), bool(DEMANDE_RE.search(ctx))))
    if not retenus:
        return None, []

    accordes = [r for r in retenus if r[2] and not r[3]]
    candidats = accordes or [r for r in retenus if not r[3]] or retenus

    cle = _sans_accents(titre or "")
    if len(cle) > 5:
        nommes = [r for r in candidats if cle in _sans_accents(r[1])]
        if nommes:
            candidats = nommes

    principal = max(c[0] for c in candidats)
    return principal, sorted({r[0] for r in retenus}, reverse=True)[:5]


def public_event_detail(metadata: dict, event_type: str, titre: str | None = None) -> dict:
    """Détail publiable d'un événement : vote, montants, thème, ordre du jour.

    Ne sort JAMAIS `personnes_citees` : ce sont des noms bruts extraits par OCR,
    non arbitrés. Les personnes n'apparaissent au public que via les liens
    event_entities, qui ne portent que des entités déjà publiques.
    """
    detail: dict = {}

    # Les parsers successifs n'ont pas écrit le même schéma : `abstention` ou
    # `abstentions`, `montant` ou `value`. On accepte les deux plutôt que de
    # perdre la moitié des décomptes.
    vote = metadata.get("vote")
    if isinstance(vote, dict):
        pour = vote.get("pour")
        contre = vote.get("contre")
        abst = vote.get("abstention", vote.get("abstentions"))
        if any(v is not None for v in (pour, contre, abst)) or vote.get("unanimite"):
            detail["vote"] = {
                "pour": pour, "contre": contre, "abstention": abst,
                "unanimite": bool(vote.get("unanimite")),
            }

    montants = metadata.get("montants")
    if isinstance(montants, list) and montants:
        # Bornes de plausibilité appliquées dans `montant_de_la_decision` :
        # l'extraction OCR rapporte des numéros d'article comme des euros
        # (« 1 € ») et des concaténations de chiffres comme des montants
        # (213 087 450 € pour une communauté de communes dont le budget tient en
        # 10 M€). Publier ces valeurs décrédibilise toute la colonne montants.
        principal, valeurs = montant_de_la_decision(montants, titre)
        if valeurs:
            detail["montant_principal"] = principal
            detail["montants"] = valeurs
            # `montant_principal` est le plus élevé des montants cités, pas le
            # coût de l'acte : sur un document qui porte 20 délibérations, il
            # affichait 2 197 037 € en face d'une ligne, comme si c'était son
            # montant propre. On le signale au lieu de le taire.
            if len(valeurs) > 1 or event_type in {
                    "conseil_municipal", "délibérations_cc", "pv_cc"}:
                detail["montant_indicatif"] = True

    if metadata.get("categorie"):
        detail["categorie"] = metadata["categorie"]
    if isinstance(metadata.get("tags"), list) and metadata["tags"]:
        detail["tags"] = metadata["tags"][:6]

    # RETIRÉ le 21/08/2026 : `ordre_du_jour`, `organisateur` et `lieu` étaient
    # recopiés tels quels depuis `metadata`, sans passer par `redige()` — le
    # masque « un particulier » qui protège `title` et les descriptions de flux.
    # Un ordre du jour porte des noms (« Demande de M. X », « recrutement de
    # Mme Y) ; ces trois champs les auraient publiés en clair.
    #
    # Supprimés plutôt que masqués : aucun collecteur du moteur n'écrit ces
    # clés — 0 événement sur les trois instances, en base comme au snapshot.
    # C'était du code mort qui portait un risque. S'ils reviennent un jour, ils
    # reviendront par `redige()`, comme tout texte publié.
    #
    # Relevé par un audit externe le 21/08/2026.

    if metadata.get("archived_copy"):
        detail["copie_archivee"] = True
        detail["archive_note"] = metadata.get("archive_note")

    return detail


def provenance(event: dict, source: str | None, event_type: str | None,
               pdf_url: str | None, source_url: str | None) -> dict:
    """Les trois axes de provenance d'un acte publié.

    Remplace le label unique `verified` / `confirmed`, retiré le 12/08/2026 :
    ces deux niveaux mélangeaient deux questions indépendantes — d'où vient
    l'information, et combien de sources le disent — sur une seule échelle.
    Empilées ainsi, elles obligeaient à choisir entre deux qualités qui n'ont
    pas de rapport, et `confirmed` n'a de fait jamais été attribué à une seule
    ligne.

    Trois questions séparées, chacune vérifiable par le lecteur :

    - `provenance`   d'où vient l'information ?
    - `document`     peut-il consulter la pièce ?
    - `traitement`   qu'avons-nous fait entre la source et l'affichage ?

    L'axe « concordance » (source unique / concordantes / contradictoires)
    proposé par la critique n'est délibérément PAS produit : rien dans la
    chaîne ne recoupe aujourd'hui deux sources indépendantes. Un axe qui
    vaudrait invariablement « source unique » répéterait exactement l'erreur
    de `confirmed` — annoncer au lecteur une garantie qui n'existe pas.
    """
    regles = RULES.get("provenance", {})

    # Une source inconnue tombe en `secondaire` : le doute joue contre nous.
    origine = regles.get("sources", {}).get(source or "", "secondaire")

    if pdf_url:
        document = "acte"          # la pièce elle-même
    elif source_url:
        document = "page_source"   # la page qui la contient
    else:
        document = "aucun"

    if event.get("corrige"):
        # Une rectification humaine tracée prime : c'est le seul cas où un
        # regard s'est posé sur la donnée.
        traitement = "rectifie"
    elif event_type in set(regles.get("types_extraits", [])):
        traitement = "extraction"  # lu dans un document rédigé — OCR ou LLM
    else:
        traitement = "structure"   # flux structuré, aucune étape d'interprétation

    return {"provenance": origine, "document": document, "traitement": traitement}


# ── Portée d'un acte : la commune, ou l'intercommunalité qui décide pour elle ─
#
# Un site communal qui mélange les deux sur sa page de garde dit au lecteur que
# tout se vaut. Or ce ne sont pas les mêmes élus, pas le même budget, pas le
# même bulletin de vote : c'est la distinction la plus utile qu'un habitant
# puisse faire, et elle disparaissait dans un compteur unique.
#
# Trois valeurs seulement, et la troisième est une honnêteté :
#   commune           la commune l'a décidé, ou l'acte la concerne directement ;
#   intercommunalite  l'EPCI l'a décidé, ou l'acte concerne une autre commune
#                     membre — ce sont des compétences transférées, pas
#                     confisquées, et le lecteur a le droit de les voir à part ;
#   territoire        ni l'un ni l'autre n'agit : une annonce BODACC, une
#                     autorisation d'urbanisme, un fait qui SE PASSE ici sans
#                     que personne d'élu l'ait voté. Les ranger sous « commune »
#                     gonflerait le compteur de l'action publique avec la vie
#                     des entreprises.
PORTEE_PAR_TYPE = {
    "deliberation":          "commune",
    "conseil_municipal":     "commune",
    "deliberation_cc":       "intercommunalite",
    "conseil_communautaire": "intercommunalite",
}


def domaine(url: str | None) -> str:
    """Domaine nu d'une adresse ou d'un libellé de source, sans `www.`."""
    d = (url or "").strip().lower()
    d = d.split("://", 1)[-1].split("/", 1)[0].split("?", 1)[0]
    return d[4:] if d.startswith("www.") else d


def _annee_de_trace(valeur) -> int | None:
    """Année d'une date ou d'un millésime, None si la valeur n'en porte pas.

    L'ANNÉE, et pas la date : un flux financier n'a que son millésime. Lui
    donner un jour le ferait passer pour plus précis qu'il n'est.
    """
    texte = str(valeur or "")[:4]
    return int(texte) if texte.isdigit() else None


def portee_evenement(event_type: str | None, perimetres: set[str],
                     source: str | None = None) -> str:
    """Portée d'un acte : son assemblée, sinon son éditeur, sinon ses acteurs.

    L'assemblée prime : une délibération du conseil communautaire est
    intercommunale même quand elle ne cite que des acteurs de la commune —
    c'est l'EPCI qui l'a votée.

    Vient ensuite L'ÉDITEUR, et c'est ce qui manquait : les 39 annonces
    d'agenda publiées par la mairie sur son propre site n'ont aucun acteur
    rattaché, et sortaient donc en « territoire ». L'agenda communal a
    disparu de la page de garde le jour où elle est devenue communale — un
    filtre correct sur une donnée incomplète. Ce que la mairie publie
    elle-même concerne la commune, c'est le sens même de le publier.

    En dernier ressort, les acteurs rattachés disent de qui l'acte parle, et
    C1 l'emporte sur C2 : un acte qui touche la commune et une voisine
    intéresse d'abord la commune.
    """
    connue = PORTEE_PAR_TYPE.get(event_type or "")
    if connue:
        return connue
    src = domaine(source)
    if src:
        if src == domaine(URL_COMMUNE):
            return "commune"
        if src == domaine(URL_EPCI):
            return "intercommunalite"
    if "C1" in perimetres:
        return "commune"
    if "C2" in perimetres:
        return "intercommunalite"
    return "territoire"


PORTEE_PAR_PERIMETRE = {"C1": "commune", "C2": "intercommunalite"}


def etape_actes(conn, revue, noms_publics, redige, exclusions) -> dict:
    # Un acte de marché ne se publie pas si son marché n'est pas publiable.
    #
    # Le filtre de confiance posé sur `marches_publics` ne suffisait pas :
    # la page d'accueil, le flux et les millésimes lisent les ACTES, pas la
    # table des marchés. Le 20/08/2026, le site servait 8 marchés et
    # 717 actes de marché — dont les avis d'un EPCI de Seine-Saint-Denis
    # attrapés par le mot « Terres ». Filtrer un côté et pas l'autre ne
    # ferme rien : les deux vues doivent dire la même chose.
    colonnes_mp = {r["name"] for r in rows(conn, "PRAGMA table_info(marches_publics)")}
    filtre_actes_marches = ("""
        AND NOT EXISTS (SELECT 1 FROM marches_publics mp
                         WHERE mp.event_id = events.id
                           AND mp.confidence NOT IN ('verified','confirmed'))
    """ if "confidence" in colonnes_mp else "")
    event_rows = rows(conn, f"""
        SELECT id, type, date, title, source, source_url, metadata,
               CASE WHEN type IN ({", ".join(f"'{t}'" for t in TYPES_DELIBERES)})
                    THEN content END AS texte_acte
        FROM events
        WHERE 1=1 {filtre_actes_marches}
        ORDER BY date DESC, id DESC
    """)
    public_events: list[dict] = []
    event_exclusions: list[dict] = []
    textes_extraits: dict[int, str] = {}
    masquages = Counter()
    revue_delib = revue.get("deliberation", {})
    for event in event_rows:
        # Verdict de l'atelier : ne s'applique qu'aux types qu'il présente
        # à la revue (`/atelier/donnees`), pour ne pas laisser un id partagé
        # avec une autre table rejeter un acte par accident.
        if event.get("type") in TYPES_REVUS["deliberation"]:
            event = appliquer_revue(event, revue_delib.get(event["id"]))
            if event is None:
                exclusions["events"]["rejete_en_atelier"] += 1
                continue
        source = event.get("source")
        event_type = event.get("type")
        try:
            metadata = json.loads(event.get("metadata") or "{}")
        except json.JSONDecodeError:
            metadata = {}
        reason = None
        if event_type in set(RULES["events"]["exclude_types"]):
            reason = "excluded_event_type"
        elif source not in set(RULES["events"]["public_sources"]):
            reason = "source_not_public_allowlist"

        if reason:
            exclusions["events"][reason] += 1
            event_exclusions.append({
                "id": event["id"],
                "type": event_type,
                "title": event["title"],
                "source": source,
                "reason": reason,
            })
            continue

        delibere = event_type in TYPES_DELIBERES
        if delibere and (event.get("texte_acte") or "").strip():
            texte, refus_extrait = texte_publiable(
                event["texte_acte"], event["date"], noms_publics, masquages)
            if refus_extrait:
                exclusions["extraits"][refus_extrait] += 1
            else:
                textes_extraits[event["id"]] = texte

        public_events.append({
            "id": event["id"],
            "type": event_type,
            "date": event["date"],
            "date_end": metadata.get("date_end"),
            # Un acte officiel cite ses particuliers (arbitré le 16/09) : le
            # titre d'une délibération n'est pas caviardé, seuls un domicile
            # ou une naissance y sont masqués.
            "title": (masquer_donnees_personnelles(
                          nettoyer_titre_evenement(event["title"]), event["date"],
                          noms_publics, masquages)
                      if delibere else redige(nettoyer_titre_evenement(event["title"]))),
            "source": source,
            "source_url": safe_url(event["source_url"]),
            "page_url": safe_url(metadata.get("page_url")),
            # Le texte de la délibération se déplie sous son titre ; il est
            # écrit à part, cf. `write_act_extracts`. Le drapeau dit à la
            # page qu'il y a quelque chose à déplier.
            **({"extrait": True} if event["id"] in textes_extraits else {}),
            # Les pièces d'une séance — registre, procès-verbal, convocation.
            # Elles n'existent que sur l'ombrelle, et c'est par elles que le
            # lecteur atteint l'archive : la fiche de séance ne peut pas
            # renvoyer à un seul document quand la séance en a produit trois.
            "pieces": [
                {"nature": p.get("nature"), "libelle": p.get("libelle"),
                 "url": safe_url(p.get("url"))}
                for p in (metadata.get("pieces") or [])
                if safe_url(p.get("url"))
            ] or None,
            # Ce que la convocation annonce (collectors/convocation.py) :
            # l'heure, le lieu, l'ordre du jour. C'est ce qui permet
            # d'annoncer un conseil AVANT qu'il ait lieu. Les points passent
            # par le même masquage que les titres d'actes.
            **({"convocation": convocation_publique(
                    metadata["convocation"], event["date"], noms_publics, masquages)}
               if event_type in TYPES_SEANCE and metadata.get("convocation") else {}),
            "pdf_url": safe_url(metadata.get("pdf_url")) or (
                safe_url(event["source_url"])
                if ".pdf" in (event["source_url"] or "").lower() else None
            ),
            # Le détail délibératif était produit par les parsers puis jeté à
            # l'export : 493 délibérations sur 508 portent le décompte du vote
            # et 471 un montant, et la page publique n'affichait qu'une ligne
            # date + titre. C'est la matière même du contrôle citoyen.
            **public_event_detail(metadata, event_type, event["title"]),
            # Trois axes vérifiables au lieu d'un label à croire.
            **provenance(
                event, source, event_type,
                safe_url(metadata.get("pdf_url")) or (
                    safe_url(event["source_url"])
                    if ".pdf" in (event["source_url"] or "").lower() else None
                ),
                safe_url(event["source_url"]),
            ),
        })

        # Le montant d'un acte est CALCULÉ (le plus élevé des montants
        # cités), il n'existe pas comme colonne : une correction de montant
        # doit donc écraser le résultat du calcul, pas un champ source. Elle
        # lève aussi le caractère « indicatif », puisqu'un humain a tranché.
        corrections_ev = set(event.get("corrige") or [])
        if "montant" in corrections_ev:
            public_events[-1]["montant_principal"] = event["montant"]
            public_events[-1].pop("montant_indicatif", None)
        if corrections_ev:
            public_events[-1]["corrige"] = sorted(corrections_ev)
        if event.get("note_revue"):
            public_events[-1]["note_revue"] = event["note_revue"]

    return {
        "event_rows": event_rows,
        "public_events": public_events,
        "event_exclusions": event_exclusions,
        "textes_extraits": textes_extraits,
        "masquages": masquages,
    }


def etape_liens_actes(conn, public_ids, public_entities, public_events,
                      exclusions) -> dict:
    # ── Croisements acteur ↔ événement ───────────────────────────────────
    # 6 154 liens existaient en base sans jamais être exportés : la fiche
    # publique d'un acteur n'affichait donc ni les délibérations qui le
    # concernent, ni les annonces le visant. On ne publie un lien que si
    # ses deux extrémités sont elles-mêmes publiques.
    public_event_ids = {e["id"] for e in public_events}
    link_rows = rows(conn, """
        SELECT ee.event_id, ee.entity_id, ee.role
        FROM event_entities ee
        ORDER BY ee.event_id
    """)
    public_links = [
        {"event_id": l["event_id"], "entity_id": l["entity_id"], "role": l["role"]}
        for l in link_rows
        if l["event_id"] in public_event_ids and l["entity_id"] in public_ids
    ]
    exclusions["event_links"]["endpoint_not_public"] = len(link_rows) - len(public_links)

    # ── Portée de chaque acte ────────────────────────────────────────────
    # Après les liens, parce que c'est un acte SANS type d'assemblée connu
    # qui a besoin de ses acteurs pour dire de qui il parle. Une annonce
    # BODACC visant une entreprise de Lasalle est communale ; la même
    # visant Val-d'Aigoual ne l'est pas.
    perimetre_par_entite = {e["id"]: e.get("perimetre") for e in public_entities}
    perimetres_par_acte: dict[int, set[str]] = defaultdict(set)
    for l in public_links:
        per = perimetre_par_entite.get(l["entity_id"])
        if per:
            perimetres_par_acte[l["event_id"]].add(per)
    for e in public_events:
        e["portee"] = portee_evenement(e["type"], perimetres_par_acte[e["id"]],
                                       e.get("source"))

    return {"public_links": public_links, "perimetre_par_entite": perimetre_par_entite}


def etape_cles_actes(conn, public_events) -> dict:
    public_event_ids = {e["id"] for e in public_events}
    # ── L'identité datée de chaque acte et séance ────────────────────────
    # `events.id` change à chaque rejeu : l'ancre publique d'un acte est sa
    # clé (`collectors/cle_acte.py`), calculée sur la ligne BRUTE de la base
    # — la même lecture que l'atelier au moment de sceller un dossier.
    # Une clé faible (date + titre) ou portée par deux actes publiés garde
    # l'ancre `a{id}` : elle n'est jamais présentée comme stable.
    lignes_actes = lignes_en_base(conn)
    index_actes = index_de(lignes_actes, public_event_ids)
    cles_brutes = {l["id"]: a for l in lignes_actes
                   if l["id"] in public_event_ids and (a := acte_de_ligne(l))}
    for e in public_events:
        a = cles_brutes.get(e["id"])
        if not a:
            continue
        e["cle"] = a.cle
        if a.faible:
            e["cle_faible"] = True
        e["ancre"] = a.ancre if a.cle not in index_actes.collisions else f"a{e['id']}"
    affiches = {e["id"]: e for e in public_events}
    for a in index_actes.par_cle.values():
        # Le titre affiché par le résolveur (infobulles) est le titre PUBLIÉ,
        # masques compris — jamais celui de la base.
        a.titre = affiches[a.id].get("title") or a.titre
    cles_stats = {
        "stables": sum(1 for e in public_events if e.get("cle") and e.get("ancre") == e["cle"]),
        "faibles": sum(1 for e in public_events if e.get("cle_faible")),
        "en_collision": len(index_actes.collisions),
    }

    return {"index_actes": index_actes, "affiches": affiches, "cles_stats": cles_stats}
