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
from collections import Counter

from scripts.snapshot.revue import TYPES_REVUS, appliquer_revue
from scripts.snapshot.socle import RULES, rows, safe_url
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
