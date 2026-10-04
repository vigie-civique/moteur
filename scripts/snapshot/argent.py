"""L'argent public : les flux financiers publiés, et dans quel sens ils vont.

L'étape `flux` lit les flux en base, applique le verdict de l'atelier puis les
filtres de publication — confiance, cessions privées, extrémités non publiées
(écartées ou déliées), doublons — et donne à chaque flux son sens (entrant,
sortant, tiers) et son état (ce que les pièces attestent).
"""
from __future__ import annotations

import sys
from collections import Counter

from collectors.etat_flux import etat_du_flux
from scripts.snapshot.revue import appliquer_revue
from scripts.snapshot.socle import RULES, rows


def flux_extremites_publiees(flow: dict, public_ids: set[int]) -> bool:
    """Les deux extrémités NOMMÉES d'un flux désignent-elles des fiches publiées ?

    `is_public_relation` tient cette règle depuis toujours pour les relations
    (`endpoint_not_public`) ; les flux financiers ne l'avaient jamais eue. Le
    filtre voisin, lui, ne regarde que les personnes physiques — il laissait donc
    passer les flux dont l'extrémité est une entité MORALE non publiée, une
    association d'une commune voisine par exemple. La page des flux en faisait un
    lien vers une fiche que le snapshot n'écrit pas, et le build du site échouait
    sur `404 /entite/<id> (linked from /finances)` : l'instance entière devenait
    impubliable à cause de trois associations. Mesuré le 21/08/2026 sur la
    première commune : 10 flux, 3 440 €.

    Le flux est écarté, et non simplement délié : publier un montant dont le
    bénéficiaire n'a pas de fiche reviendrait à nommer une entité que le filtre
    de périmètre vient d'écarter, en la privant du contexte qui rendrait ce nom
    lisible.

    Une extrémité vide (`NULL`) ne bloque rien : un flux dont le bénéficiaire est
    inconnu ne prétend renvoyer nulle part. C'est le cas des lignes que les
    collecteurs n'ont pas su rattacher, traitées plus loin par la déduplication.
    """
    for cle in ("from_id", "to_id"):
        eid = flow.get(cle)
        if eid and eid not in public_ids:
            return False
    return True


def statut_extremites(flow: dict, public_ids: set[int],
                      ecartees_du_perimetre: set[int]) -> str:
    """« garde », « delie » ou « ecarte » — le sort d'un flux dont une extrémité
    n'a pas de fiche.

    Une subvention votée par la commune à une association dont le siège est dans
    une commune voisine est un fait COMMUNAL : c'est le budget d'ici qui la
    paie. Elle était pourtant écartée avec tout le reste, parce que le
    bénéficiaire est classé C2 et n'a donc pas de fiche
    (`publiable_dans_perimetre`). Mesuré le 16/09/2026 : 15 lignes sur 44 à
    Saillans, 21 à Lasalle — l'argent public le plus proche du lecteur, absent
    du site qui parle de son argent.

    Le flux est donc DÉLIÉ plutôt qu'écarté, comme l'est déjà un marché dont le
    titulaire n'a pas de fiche : le nom reste, le lien tombe, et aucune fiche
    n'est créée pour autant — la règle du périmètre n'est pas entamée.

    Deux bornes, et elles font tout le sens de cette exception :
      - l'extrémité sans fiche doit être écartée POUR LE SEUL PÉRIMÈTRE. Une
        personne physique sans rôle civique, une entité en `probable` sont
        écartées pour ce qu'elles sont : rien n'en sort, pas même un nom ;
      - l'autre extrémité doit, elle, être publiée. Un flux entre deux entités
        sans fiche ne dit rien de la commune.
    """
    if flux_extremites_publiees(flow, public_ids):
        return "garde"
    for cle in ("from_id", "to_id"):
        eid = flow.get(cle)
        if eid and eid not in public_ids and eid not in ecartees_du_perimetre:
            return "ecarte"
    publiee = any(flow.get(cle) in public_ids for cle in ("from_id", "to_id"))
    return "delie" if publiee else "ecarte"


def delier_extremites(flow: dict, public_ids: set[int]) -> None:
    """Coupe le renvoi vers une fiche que le snapshot n'écrit pas, en gardant le
    nom : `/finances` affiche déjà le nom nu quand l'identifiant manque."""
    for cle in ("from_id", "to_id"):
        eid = flow.get(cle)
        if eid and eid not in public_ids:
            flow[cle] = None


def _cle_beneficiaire(flow: dict):
    """L'identité du bénéficiaire, pour dédoublonner : sa fiche, ou son NOM.

    Un flux délié (bénéficiaire hors périmètre, cf. `statut_extremites`) n'a plus
    d'identifiant mais garde son nom. Dédoublonner sur le seul identifiant faisait
    alors disparaître une association derrière une autre : RASED et Prévention
    routière, 100 € chacune en 2023, ne laissaient qu'une ligne.
    """
    if flow.get("to_id"):
        return ("id", flow["to_id"])
    return ("nom", " ".join(str(flow.get("to_name") or "").split()).lower())


def beneficiaire_inconnu(flow: dict) -> bool:
    """Le flux ne nomme personne — ce que les collecteurs laissent quand ils n'ont
    pas su rattacher une ligne.

    L'absence de FICHE n'est pas l'absence de NOM. Les confondre écartait les flux
    déliés comme s'ils ne désignaient personne : sur la première instance, 9 des
    15 subventions rendues au public repartaient aussitôt.
    """
    return str(flow.get("to_name") or "").strip() in ("", "?", "∅")


def dedupliquer_flux(flows: list[dict]) -> list[dict]:
    """Les doublons exacts, puis les « jumeaux » sans bénéficiaire nommé.

    Deux passes distinctes : la même décision écrite deux fois par deux
    collecteurs, et la ligne anonyme qu'un collecteur laisse à côté d'une ligne
    nommée du même montant.
    """
    vus, dedup = set(), []
    for f in flows:
        cle = (f.get("year"), f.get("amount"), f.get("type"), f.get("from_id"),
               _cle_beneficiaire(f))
        if cle in vus:
            continue
        vus.add(cle)
        dedup.append(f)
    jumeau = lambda f: (f.get("year"), f.get("amount"), f.get("type"), f.get("from_id"))
    nommes = {jumeau(f) for f in dedup if not beneficiaire_inconnu(f)}
    return [f for f in dedup
            if not beneficiaire_inconnu(f) or jumeau(f) not in nommes]


def _commune_entity_id(conn) -> int | None:
    """Id de l'entité « Commune de … », ou None si elle n'est pas en base.

    Cherchée par nom NORMALISÉ, comme le fait `upsert_entity` : SIRENE l'écrit
    « COMMUNE DE LASALLE », et l'égalité exacte de SQLite respecte la casse.
    Le nom exact ne trouvait donc rien, sur les trois instances : aucun flux ne
    sortait `sortant`, `/finances` affichait « 0 € versé » pour chaque année
    alors que les fiches publiaient les subventions (audit du 24/09/2026).
    """
    from collectors.config import COMMUNE_NAME
    from collectors.nom_normalise import normaliser
    row = conn.execute(
        "SELECT id FROM entities WHERE type='service' AND name_norm=? "
        "ORDER BY (commune=?) DESC, id LIMIT 1",
        (normaliser(f"Commune de {COMMUNE_NAME}"), COMMUNE_NAME)).fetchone()
    return row["id"] if row else None


def etape_flux(conn, revue, entity_rows, public_person_ids, public_ids,
               ecartees_du_perimetre, redige, exclusions) -> dict:
    flow_rows = rows(conn, """
        SELECT ff.id, ff.type, ff.year, ff.amount, ff.description,
               ff.source, ff.confidence,
               COALESCE(ff.type_norm, ff.type) AS type_norm,
               COALESCE(ff.perimetre, 'detail') AS perimetre,
               COALESCE(ff.statut, 'realise') AS statut,
               ff.from_id, ff.to_id,
               f.name AS from_name, t.name AS to_name
        FROM financial_flows ff
        LEFT JOIN entities f ON f.id = ff.from_id
        LEFT JOIN entities t ON t.id = ff.to_id
        ORDER BY ff.year DESC, ff.amount DESC
    """)
    # La revue passe AVANT le filtre de confiance : c'est précisément son
    # rôle de faire passer un flux de `probable` à `verified` après contrôle
    # humain, ou l'inverse.
    revue_flux = revue.get("flow", {})
    revus = []
    for flow in flow_rows:
        flow = appliquer_revue(flow, revue_flux.get(flow["id"]))
        if flow is None:
            exclusions["flows"]["rejete_en_atelier"] += 1
            continue
        revus.append(flow)
    flow_rows = revus

    public_flows = [
        flow for flow in flow_rows
        if flow.get("confidence") in set(RULES["confidence"]["public"])
    ]
    exclusions["flows"]["private_confidence"] = len(flow_rows) - len(public_flows)

    # Cessions strictement privées (aucune des parties n'est la commune) :
    # ce sont des mutations commerciales (fonds de commerce), pas des flux
    # de finances publiques → hors périmètre de cette page.
    # Identifiant résolu par le nom : `63` était le numéro de ligne de la
    # commune dans la base de Lasalle. Sur une autre base il désigne une
    # entité quelconque, et le filtre des cessions privées laisse alors
    # passer ce qu'il devait écarter — silencieusement.
    COMMUNE_ID = _commune_entity_id(conn)
    if COMMUNE_ID is None and flow_rows:
        # Sans elle, aucun flux n'a de sens et toute cession passe pour
        # privée : le dire, plutôt que publier des zéros.
        print("⚠ entité « Commune de … » introuvable : sens des flux non "
              "déterminé, cessions communales écartées", file=sys.stderr)
    before = len(public_flows)
    public_flows = [
        f for f in public_flows
        if not (str(f.get("type", "")).startswith("cession")
                and COMMUNE_ID not in (f.get("from_id"), f.get("to_id")))
    ]
    exclusions["flows"]["private_cession"] = before - len(public_flows)

    # Un flux dont une extrémité est une personne physique non publiable
    # publiait son nom en clair (`to_name`) alors que l'entité elle-même est
    # écartée du snapshot : le filtre entités était contourné par les flux.
    personnes_privees = {
        r["id"] for r in entity_rows
        if r["type"] == "person" and r["id"] not in public_person_ids
    }
    before = len(public_flows)
    public_flows = [
        f for f in public_flows
        if not ({f.get("from_id"), f.get("to_id")} & personnes_privees)
    ]
    exclusions["flows"]["private_person_endpoint"] = before - len(public_flows)

    # Même contournement, une marche plus haut : le filtre ci-dessus ne voit
    # que les personnes physiques, et laissait passer les flux dont
    # l'extrémité est une entité morale non publiée — cf.
    # `flux_extremites_publiees`, qui porte la règle et son histoire.
    before = len(public_flows)
    gardes, delies = [], 0
    for f in public_flows:
        etat = statut_extremites(f, public_ids, ecartees_du_perimetre)
        if etat == "ecarte":
            continue
        if etat == "delie":
            delier_extremites(f, public_ids)
            delies += 1
        gardes.append(f)
    public_flows = gardes
    exclusions["flows"]["endpoint_not_public"] = before - len(public_flows)

    # Déduplication : doublons exacts (même année/montant/type/émetteur/destinataire)
    # et « jumeaux » non résolus (montant identique, bénéficiaire vide) laissés par
    # les collecteurs. On garde les bénéficiaires DISTINCTS de même montant.
    before = len(public_flows)
    public_flows = dedupliquer_flux(public_flows)
    exclusions["flows"]["duplicates"] = before - len(public_flows)

    # `sens` : la DGF encaissée par la commune (489 690 €) et la subvention
    # versée au Comité des fêtes (4 400 €) sortaient avec la même mise en
    # forme. Sans le sens du flux, la page se lit à contresens.
    # Un flux délié a perdu son identifiant (`None`) : tant que COMMUNE_ID
    # valait `None` lui aussi, il sortait « entrant ».
    for f in public_flows:
        f["description"] = redige(f.get("description"))
        if COMMUNE_ID is None:
            f["sens"] = "tiers"
        elif f.get("to_id") == COMMUNE_ID and f.get("from_id") != COMMUNE_ID:
            f["sens"] = "entrant"
        elif f.get("from_id") == COMMUNE_ID:
            f["sens"] = "sortant"
        else:
            f["sens"] = "tiers"

    # `statut` valait `realise` sur la totalité des flux — la subvention
    # votée, la dotation lue dans les comptes et la demande de DSIL avec le
    # même mot. La page en tirait « la commune a versé ». L'état se déduit
    # de ce qui documente le montant : cf. `collectors/etat_flux`.
    for f in public_flows:
        f["etat"] = etat_du_flux(f.get("type"), f.get("source"), f.get("statut"))
    flows_par_etat = dict(Counter(f["etat"] for f in public_flows))

    # Également calculés, jamais publiés : `flux_delies_hors_perimetre`,
    # `flows_par_sens`, `flows_par_statut`. Seul l'état sort, dans `stats.json`.
    return {"flow_rows": flow_rows, "public_flows": public_flows,
            "flows_par_etat": flows_par_etat}
