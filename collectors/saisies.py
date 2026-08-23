#!/usr/bin/env python3
"""saisies.py — rejoue ce qu'un humain a saisi dans l'atelier.

POURQUOI UN FICHIER, ET PAS UN INSERT DIRECT
La base est reconstructible : n'importe qui la refait avec le code et un code
INSEE, puisque les collecteurs relisent des sources publiques. Le travail humain,
lui, ne se régénère pas. Écrire une saisie directement en base, ce serait la
perdre au premier `init_instance` — et c'est très exactement ce qui est arrivé à
la v1, dont 49 % des flux financiers vivaient dans onze scripts Python jetables.

Les saisies vivent donc dans `config/saisies.json`, non versionné, et ce module
les rejoue à chaque collecte. Même principe que `cm_events` / `seed_local.json`,
avec ce que celui-ci n'a pas : une source obligatoire par ligne, un auteur, un
identifiant stable entre machines, et le retrait plutôt que l'effacement.

CE QUE CE MODULE NE FAIT JAMAIS
Il n'écrit que des lignes dont il est l'auteur — reconnaissables à leur `source`
« atelier:<id> » et à leur `origine` = 'atelier'. Il ne modifie ni ne supprime
aucune ligne produite par un autre collecteur. La règle posée par Julien le
20/08/2026 tient donc par construction, pas seulement par discipline : « ne pas
corrompre tout ce qui est établi comme venant de collecteurs institutionnels ».

LA SOURCE EST OBLIGATOIRE
Une saisie sans document ne s'enregistre pas. Ce n'est pas de la rigueur pour
la forme : les procès-verbaux 2017-2019 de la commune ont disparu du site de la
mairie, et seule une copie locale les rend encore opposables. `raw_documents`
garde le fichier et son empreinte ; `sha256` accompagne chaque saisie pour que
le lien survive au transfert vers une autre machine, où les `id` diffèrent.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .db import transaction, upsert_entity, upsert_relation
from .origine import ATELIER

SAISIES = Path(__file__).resolve().parent.parent / "config" / "saisies.json"

VERSION = 1

#: Confiances qu'une saisie peut porter. `verified` est réservé aux collecteurs
#: institutionnels : un humain qui lit un PV *confirme*, il ne certifie pas.
CONFIANCES = ("confirmed", "probable", "hypothesis")

# ─── Contrat des champs ───────────────────────────────────────────────────────
# Exposé tel quel par l'API (`GET /api/atelier/saisies/champs`) : le formulaire
# ne devine pas ce qu'il a le droit d'envoyer, il le demande. Sans ça, le front
# propose un champ que l'API refuse, ou en oublie un qu'elle accepterait — le
# défaut qu'on avait déjà corrigé pour les corrections d'annotations.
#
#   genre : texte | texte_court | montant | annee | date | entite | choix:a,b,c
#   Un champ suffixé de `*` est obligatoire.

CHAMPS_SAISIE = {
    "flux": {
        "_libelle": "Flux financier",
        "_table": "financial_flows",
        "type*":        ("texte_court", "Nature (subvention, bail, cession…)"),
        "year*":        ("annee",       "Année"),
        "amount*":      ("montant",     "Montant en euros"),
        "sens*":        ("choix:verse,recu", "Versé par la commune, ou reçu par elle"),
        "tiers*":       ("entite",      "L'autre partie : bénéficiaire ou payeur"),
        "description*": ("texte",       "Ce que dit la source, en une phrase"),
        # « Réalisé » recouvrait le vote, l'engagement et le paiement : celui
        # qui saisit lit une pièce précise, il peut dire laquelle.
        "statut":       ("choix:vote,engage,paye,demande,annule",
                         "Ce que la pièce atteste : voté, engagé, payé, "
                         "seulement demandé, ou annulé"),
    },
    "acte": {
        "_libelle": "Délibération / acte",
        "_table": "events",
        "date*":    ("date",        "Date de la séance"),
        "title*":   ("texte_court", "Objet de la délibération"),
        "content":  ("texte",       "Texte ou résumé"),
    },
    "marche": {
        "_libelle": "Marché public",
        "_table": "marches_publics",
        "objet*":         ("texte",       "Objet du marché"),
        "acheteur_nom*":  ("texte_court", "Acheteur, tel que la source le nomme"),
        "titulaire_nom*": ("texte_court", "Titulaire retenu"),
        "montant":        ("montant",     "Montant en euros"),
        "date_notif":     ("date",        "Date de notification"),
        "procedure":      ("texte_court", "Procédure (adaptée, ouverte…)"),
    },
    "budget_vote": {
        "_libelle": "Ligne de budget voté",
        "_table": "budget_vote",
        "year*":    ("annee",       "Exercice"),
        "agregat*": ("texte_court", "Intitulé (recettes de fonctionnement…)"),
        "value*":   ("montant",     "Montant voté"),
        "scope":    ("texte_court", "Budget principal ou budget annexe"),
        "note":     ("texte",       "Précision, réserve, mention de vote"),
    },
    "dotation": {
        "_libelle": "Dotation de l'État",
        "_table": "dotations_etat",
        "year*":       ("annee",       "Exercice"),
        "composante*": ("texte_court", "Composante (DGF, DSR, DETR…)"),
        "montant*":    ("montant",     "Montant notifié"),
        "raw_label":   ("texte",       "Libellé exact de la source"),
    },
    "entite": {
        "_libelle": "Entité (association, entreprise, service, personne)",
        "_table": "entities",
        "name*":    ("texte_court", "Nom"),
        "type*":    ("choix:association,business,person,service,place",
                     "Nature de l'entité"),
        "address":  ("texte_court", "Adresse"),
        "commune":  ("texte_court", "Commune de rattachement"),
        "siren":    ("texte_court", "SIREN, s'il est connu"),
    },
}


def charger(chemin: Path | None = None) -> dict:
    """Le fichier de saisies, ou une structure vide s'il n'existe pas encore.

    Un atelier neuf n'a rien saisi : absence n'est pas erreur.
    """
    chemin = chemin or SAISIES
    try:
        with open(chemin, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {"version": VERSION, "saisies": []}
    except json.JSONDecodeError as e:
        # Refuser bruyamment : un fichier illisible qu'on remplacerait par du
        # vide, c'est du travail humain effacé sans que personne le voie.
        raise RuntimeError(f"{chemin} illisible : {e}") from e
    data.setdefault("saisies", [])
    return data


def enregistrer(data: dict, chemin: Path | None = None) -> None:
    """Écrit le fichier de façon atomique.

    Le passage par un fichier temporaire n'est pas de la superstition : l'API
    écrit ce fichier pendant qu'une collecte peut le lire, et un `write_text`
    interrompu laisserait un JSON tronqué — donc, d'après `charger()`, une
    erreur bloquante sur tout le travail saisi.
    """
    chemin = chemin or SAISIES
    chemin.parent.mkdir(parents=True, exist_ok=True)
    data["version"] = VERSION
    tmp = chemin.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(chemin)


def _source_de(saisie: dict) -> str:
    """La source d'une ligne saisie porte son identifiant.

    C'est ce qui rend le rejeu idempotent sans colonne supplémentaire, et ce qui
    permet à `origine_de()` de la reconnaître : le motif « atelier » du registre
    d'origines mord sur ce préfixe.
    """
    return f"atelier:{saisie['id']}"


def _horodate() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ─── Insertion, objet par objet ───────────────────────────────────────────────
# Chacune renvoie True si elle a écrit. Toutes commencent par vérifier qu'aucune
# ligne ne porte déjà cette source : les tables de faits n'ont pas de contrainte
# UNIQUE, et un `INSERT OR IGNORE` n'y ignore rien — piège déjà payé deux fois
# dans ce projet, où chaque exécution rejouait les mêmes versements et doublait
# les totaux publiés.

def _existe(conn, table: str, source: str) -> bool:
    return conn.execute(f"SELECT 1 FROM {table} WHERE source=?",
                        (source,)).fetchone() is not None


def _entite_du_tiers(conn, tiers: dict) -> int:
    """Retrouve ou crée l'entité désignée par une saisie.

    `tiers` vient du formulaire : soit un identifiant déjà choisi dans la
    recherche (`{"id": 4471}`), soit un nom et un type à créer. On ne devine
    jamais le type à partir du nom — une association et une entreprise
    s'écrivent pareil, et « Champ contre Champ » existe déjà en double dans
    cette base, une fois en entreprise et une fois en association.
    """
    if tiers.get("id"):
        return int(tiers["id"])
    return upsert_entity(
        conn,
        type=tiers.get("type") or "association",
        name=tiers["nom"],
        commune=tiers.get("commune"),
        confidence="confirmed",
    )


def _inserer_flux(conn, s: dict, commune_id: int, doc_id: int | None) -> bool:
    source = _source_de(s)
    if _existe(conn, "financial_flows", source):
        return False
    v = s["valeurs"]
    tiers_id = _entite_du_tiers(conn, v["tiers"])
    verse = v.get("sens", "verse") == "verse"
    conn.execute(
        "INSERT INTO financial_flows"
        " (type,year,amount,from_id,to_id,description,source,confidence,statut,"
        "  origine,raw_document_id,saisi_par,saisi_le)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (v["type"], v["year"], v["amount"],
         commune_id if verse else tiers_id,
         tiers_id if verse else commune_id,
         v["description"], source, s.get("confidence", "confirmed"),
         v.get("statut", "realise"),
         ATELIER, doc_id, s.get("saisi_par"), s.get("saisi_le")))
    upsert_relation(
        conn,
        from_id=commune_id if verse else tiers_id,
        to_id=tiers_id if verse else commune_id,
        rel_type="subventionné" if v["type"].startswith("subvention") else v["type"],
        source="atelier",
        confidence="confirmed",
        metadata=json.dumps({"year": v["year"], "amount": v["amount"]}))
    return True


def _inserer_acte(conn, s: dict, commune_id: int, doc_id: int | None) -> bool:
    source = _source_de(s)
    if _existe(conn, "events", source):
        return False
    v = s["valeurs"]
    conn.execute(
        "INSERT INTO events"
        " (type,date,title,content,source,source_url,origine,raw_document_id,"
        "  saisi_par,saisi_le)"
        " VALUES ('deliberation',?,?,?,?,?,?,?,?,?)",
        (v["date"], v["title"], v.get("content"), source,
         (s.get("source") or {}).get("url"),
         ATELIER, doc_id, s.get("saisi_par"), s.get("saisi_le")))
    return True


def _inserer_marche(conn, s: dict, commune_id: int, doc_id: int | None) -> bool:
    source = _source_de(s)
    if _existe(conn, "marches_publics", source):
        return False
    v = s["valeurs"]
    # `acheteur_siren` est NOT NULL au schéma ; une saisie ne connaît pas
    # toujours le SIREN de l'acheteur qu'elle nomme. La chaîne vide dit
    # « non renseigné » sans mentir sur un identifiant qui, lui, est vérifiable.
    conn.execute(
        "INSERT INTO marches_publics"
        " (acheteur_siren,acheteur_nom,titulaire_nom,objet,montant,date_notif,"
        "  procedure,source,source_url,raw_id,confidence,origine,raw_document_id,"
        "  saisi_par,saisi_le)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (v.get("acheteur_siren") or "", v["acheteur_nom"], v["titulaire_nom"],
         v["objet"], v.get("montant"), v.get("date_notif"), v.get("procedure"),
         source, (s.get("source") or {}).get("url"), source,
         s.get("confidence", "confirmed"), ATELIER, doc_id,
         s.get("saisi_par"), s.get("saisi_le")))
    return True


def _inserer_budget_vote(conn, s: dict, commune_id: int, doc_id: int | None) -> bool:
    source = _source_de(s)
    if _existe(conn, "budget_vote", source):
        return False
    v = s["valeurs"]
    conn.execute(
        "INSERT OR REPLACE INTO budget_vote"
        " (year,scope,agregat,value,unit,note,source,source_url,origine,"
        "  raw_document_id,saisi_par,saisi_le)"
        " VALUES (?,?,?,?,'EUR',?,?,?,?,?,?,?)",
        (v["year"], v.get("scope") or "principal", v["agregat"], v["value"],
         v.get("note"), source, (s.get("source") or {}).get("url"),
         ATELIER, doc_id, s.get("saisi_par"), s.get("saisi_le")))
    return True


def _inserer_dotation(conn, s: dict, commune_id: int, doc_id: int | None) -> bool:
    from .config import COMMUNE_INSEE, COMMUNE_NAME
    source = _source_de(s)
    if _existe(conn, "dotations_etat", source):
        return False
    v = s["valeurs"]
    conn.execute(
        "INSERT OR REPLACE INTO dotations_etat"
        " (year,insee,commune,composante,montant,source,raw_label,origine,"
        "  raw_document_id,saisi_par,saisi_le)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (v["year"], COMMUNE_INSEE, COMMUNE_NAME, v["composante"], v["montant"],
         source, v.get("raw_label"), ATELIER, doc_id,
         s.get("saisi_par"), s.get("saisi_le")))
    return True


def _inserer_entite(conn, s: dict, commune_id: int, doc_id: int | None) -> bool:
    v = s["valeurs"]
    eid = upsert_entity(conn, type=v["type"], name=v["name"],
                        address=v.get("address"), commune=v.get("commune"),
                        confidence=s.get("confidence", "confirmed"))
    # L'entité saisie n'a pas de colonne `origine` : le référentiel se décrit
    # déjà par `confidence` et `validation_status`, et lui ajouter une troisième
    # échelle brouillerait les deux autres. Une entité créée à la main est une
    # entité validée — c'est le sens du geste.
    conn.execute("UPDATE entities SET validation_status='validated' WHERE id=?",
                 (eid,))
    return True


_INSERTEURS = {
    "flux":        _inserer_flux,
    "acte":        _inserer_acte,
    "marche":      _inserer_marche,
    "budget_vote": _inserer_budget_vote,
    "dotation":    _inserer_dotation,
    "entite":      _inserer_entite,
}


def _retirer(conn, s: dict) -> bool:
    """Efface une ligne saisie — et seulement une ligne saisie.

    Le filtre porte sur `source = atelier:<id>` : aucune ligne de collecteur ne
    peut être atteinte par ce chemin, même si le fichier de saisies était
    trafiqué pour désigner un identifiant existant.
    """
    objet = s.get("objet")
    table = (CHAMPS_SAISIE.get(objet) or {}).get("_table")
    if not table or table == "entities":
        # Une entité saisie n'est PAS supprimée quand on retire sa saisie : des
        # flux, des relations et des marchés peuvent déjà s'y rattacher, y
        # compris venus de collecteurs. La retirer du répertoire se fait par le
        # statut de validation, dans la file de revue — pas ici.
        return False
    cur = conn.execute(f"DELETE FROM {table} WHERE source=?", (_source_de(s),))
    return cur.rowcount > 0


def import_saisies(chemin: Path | None = None) -> dict[str, int]:
    """Rejoue le fichier de saisies. Point d'entrée du step `saisies`."""
    data = charger(chemin)
    lignes = data.get("saisies") or []
    if not lignes:
        print("[saisies] aucune saisie — rien à rejouer.")
        return {"ecrites": 0, "retirees": 0, "ignorees": 0}

    from .db import pivot_ids
    ecrites = retirees = ignorees = 0

    with transaction() as conn:
        commune_id = pivot_ids(conn).get("commune")
        if not commune_id:
            raise RuntimeError(
                "[saisies] l'entité de la commune n'existe pas encore : "
                "lancer la collecte avant de rejouer les saisies.")

        for s in lignes:
            if s.get("retire"):
                retirees += 1 if _retirer(conn, s) else 0
                continue
            inserteur = _INSERTEURS.get(s.get("objet"))
            if inserteur is None:
                print(f"  [saisies] objet inconnu, ignoré : {s.get('objet')!r}")
                ignorees += 1
                continue
            doc_id = (s.get("source") or {}).get("raw_document_id")
            if inserteur(conn, s, commune_id, doc_id):
                ecrites += 1
            else:
                ignorees += 1

    print(f"[saisies] {ecrites} écrites, {retirees} retirées, "
          f"{ignorees} déjà en base")
    return {"ecrites": ecrites, "retirees": retirees, "ignorees": ignorees}
