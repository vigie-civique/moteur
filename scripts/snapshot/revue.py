"""La revue de l'atelier : ce qu'un humain a écarté ou rectifié, appliqué à la sortie.

Deuxième étape du snapshot : les verdicts sont lus une fois, et chaque étape
qui publie une ligne revue (fiches, relations, actes, flux, marchés) les
reçoit sous le nom `revue`.
"""
from __future__ import annotations

import json
from collections import defaultdict

from collectors.verdict import ecarte, verdict_de
from scripts.snapshot.socle import rows, table_exists


# ── Couche de revue : ce que l'atelier a rejeté ou rectifié ──────────────────
# La table `annotations` existait, les endpoints existaient, l'écran de revue
# existait — mais la publication ne la lisait pas. Rejeter ou corriger une
# donnée dans l'atelier n'avait donc aucun effet sur le site : toute correction
# passait par un script Python. C'est ce qui rendait la boucle interminable.
#
# Les corrections ne sont PAS écrites dans les tables sources (règle n°1 :
# jamais écraser). Elles sont appliquées ici, à la sortie, sur une copie.

# Depuis le 21/09/2026 la table porte aussi le verdict des FICHES (`entity`) et
# des RELATIONS (`relation`), lus plus bas dans `build_snapshot`. Jusque-là le
# jugement d'une fiche vivait dans `entities.validation_status`, que rien ici ne
# lisait : cf. `collectors/verdict.py`.
#
# `annotations.object_type` ↔ table source.
TYPES_REVUS = {
    "deliberation": ("deliberation", "conseil_municipal", "délibérations_cc", "pv_cc"),
}


def charger_revue(conn) -> dict[str, dict[int, dict]]:
    """{object_type: {object_id: {statut, confidence, note, corrections}}}."""
    if not table_exists(conn, "annotations"):
        return {}
    colonnes = {r["name"] for r in rows(conn, "PRAGMA table_info(annotations)")}
    champ_corr = "corrections" if "corrections" in colonnes else "NULL AS corrections"
    revue: dict[str, dict[int, dict]] = defaultdict(dict)
    for a in rows(conn, f"""SELECT object_type, object_id, review_status,
                                   confidence, note, {champ_corr}
                            FROM annotations"""):
        try:
            corr = json.loads(a["corrections"]) if a["corrections"] else {}
        except (json.JSONDecodeError, TypeError):
            corr = {}
        revue[a["object_type"]][a["object_id"]] = {
            # Normalisé : une base non migrée garde `rejected` ou `validated`,
            # un export d'avant le 21/09 aussi. Un mot inconnu ne retire rien —
            # retirer du site exige que quelqu'un l'ait décidé.
            "statut": verdict_de(a["review_status"]) or "jamais_relu",
            "confidence": a["confidence"],
            "note": (a["note"] or "").strip(),
            "corrections": corr if isinstance(corr, dict) else {},
        }
    return revue


def appliquer_revue(ligne: dict, verdict: dict | None) -> dict | None:
    """Renvoie la ligne corrigée, ou None si l'atelier l'a rejetée.

    Une correction porte le nom du champ dans la table source ; on la pose sur
    la copie publiée et on garde trace de la valeur d'origine, pour que la page
    puisse dire « rectifié » plutôt que d'afficher un chiffre changé en silence.
    """
    if not verdict:
        return ligne
    if ecarte(verdict["statut"]):
        return None
    ligne = dict(ligne)
    corrigees = set()
    for champ, valeur in (verdict["corrections"] or {}).items():
        # Le champ peut être ABSENT de la ligne source : le montant d'un acte
        # est calculé depuis `metadata`, il n'existe pas comme colonne. Une
        # correction reste une correction même sans valeur d'origine en face.
        if ligne.get(champ) != valeur:
            corrigees.add(champ)
        ligne[champ] = valeur
    if corrigees:
        ligne["corrige"] = sorted(corrigees)
    if verdict["confidence"]:
        ligne["confidence"] = verdict["confidence"]
    if verdict["note"]:
        ligne["note_revue"] = verdict["note"]
    return ligne


def etape_revue(conn) -> dict:
    revue = charger_revue(conn)
    # Une relation écartée par l'atelier ne se publie pas — et ne JUSTIFIE
    # plus rien : un mandat jugé faux ne peut pas continuer de rendre une
    # personne publiable au titre de son rôle civique. Passée en JSON aux
    # requêtes des étapes suivantes (`json_each`), vide dans le cas courant.
    relations_ecartees = json.dumps(sorted(
        rid for rid, v in revue.get("relation", {}).items() if ecarte(v["statut"])))
    return {
        "revue": revue,
        "revue_annotations": sum(len(v) for v in revue.values()),
        "relations_ecartees": relations_ecartees,
    }
