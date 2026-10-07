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
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import verrou as verrou_fichier
from .db import pivot_ids, transaction, upsert_entity, upsert_relation
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
        # Une saisie ne pouvait porter que la commune : la subvention d'une
        # convention intercommunale y devenait une dépense communale.
        "assemblee":    ("choix:commune,epci",
                         "L'assemblée qui a voté : la commune (par défaut) "
                         "ou l'intercommunalité"),
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
        # Le SIREN rattache l'acheteur à SA fiche, quelle que soit la graphie
        # saisie : sans lui, la communauté de communes de Lasalle s'affichait
        # sous cinq noms (cf. `marches_publics.acheteur_par_siren`).
        "acheteur_siren": ("texte_court", "SIREN de l'acheteur, s'il est connu"),
        "nature":         ("texte_court", "Travaux, fournitures ou services"),
        "montant_base":   ("choix:HT,TTC", "Le montant est-il hors taxes ou TTC ?"),
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
    """Écrit le fichier de façon atomique. NE VERROUILLE PAS : passer par
    `modifier()` dès que ce qu'on écrit dépend de ce qu'on a lu.

    Le passage par un fichier temporaire n'est pas de la superstition : l'API
    écrit ce fichier pendant qu'une collecte peut le lire, et un `write_text`
    interrompu laisserait un JSON tronqué — donc, d'après `charger()`, une
    erreur bloquante sur tout le travail saisi.

    Le temporaire porte un nom UNIQUE. Il s'appelait `saisies.json.tmp` pour
    tout le monde : deux écritures simultanées se le disputaient, la première à
    renommer l'emportait et la seconde échouait sur un fichier disparu.
    """
    chemin = chemin or SAISIES
    chemin.parent.mkdir(parents=True, exist_ok=True)
    data["version"] = VERSION
    fd, tmp = tempfile.mkstemp(dir=chemin.parent, prefix=f"{chemin.name}.",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2))
        os.replace(tmp, chemin)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


@contextmanager
def _verrou(chemin: Path):
    """Verrou exclusif sur `<fichier>.verrou`, entre fils ET entre processus.

    Un verrou de fil ne suffirait pas : `vigie_marches_cr.py --vers-saisies` et
    `importer_decisions.py` écrivent le même fichier depuis un autre processus
    que l'API. Le verrou porte sur un fichier voisin, jamais sur `saisies.json`
    lui-même, que `enregistrer()` remplace par renommage.
    """
    verrou = chemin.with_name(chemin.name + ".verrou")
    verrou.parent.mkdir(parents=True, exist_ok=True)
    with open(verrou, "a+b") as f:
        verrou_fichier.prendre(f)
        try:
            yield
        finally:
            verrou_fichier.rendre(f)


@contextmanager
def modifier(chemin: Path | None = None, *, ecrire: bool = True):
    """Lire, modifier, réécrire — sans que personne n'écrive entre-temps.

        with saisies.modifier() as data:
            data["saisies"].append(nouvelle)

    `charger()` puis `enregistrer()` à la suite laissaient une fenêtre : deux
    éditeurs lisaient le même fichier, chacun ajoutait sa ligne, et le second à
    écrire effaçait celle du premier. Mesuré le 17/09 : quatre éditeurs
    simultanés, 100 saisies envoyées, 31 conservées — sans une erreur visible
    pour ceux dont la saisie avait disparu.

    Une exception levée dans le bloc n'écrit rien. `ecrire=False` garde le
    verrou pour une lecture à blanc qui doit voir un état stable.
    """
    chemin = chemin or SAISIES
    with _verrou(chemin):
        data = charger(chemin)
        yield data
        if ecrire:
            enregistrer(data, chemin)


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


#: Ce qu'une saisie peut écrire de publiable. Tout le reste attend un verdict.
PUBLIABLES = ("verified", "confirmed")


def _entite_du_tiers(conn, tiers: dict, confiance: str) -> int:
    """Retrouve ou crée l'entité désignée par une saisie.

    Créée, elle porte la confiance de la SAISIE. Elle naissait `confirmed`
    quelle que soit la saisie : un contributeur proposait un flux `probable`,
    et son bénéficiaire avait une fiche publiable avant qu'un validateur n'ait
    rien vu. Une entité déjà en base n'est pas touchée.

    `tiers` vient du formulaire : soit un identifiant déjà choisi dans la
    recherche (`{"id": 4471}`), soit un nom et un type à créer. On ne devine
    jamais le type à partir du nom — une association et une entreprise
    s'écrivent pareil, et « Champ contre Champ » existe déjà en double dans
    cette base, une fois en entreprise et une fois en association.
    """
    if tiers.get("id"):
        return int(tiers["id"])
    dernier = conn.execute("SELECT COALESCE(MAX(id), 0) FROM entities").fetchone()[0]
    eid = upsert_entity(
        conn,
        type=tiers.get("type") or "association",
        name=tiers["nom"],
        commune=tiers.get("commune"),
        confidence=confiance,
    )
    if eid > dernier:
        # Née de cette saisie : d'origine `atelier`, comme une fiche saisie —
        # c'est aussi ce qui autorise le retrait à l'emporter.
        conn.execute("UPDATE entities SET origine=? WHERE id=?", (ATELIER, eid))
    return eid


def _relier(conn, s: dict, from_id: int, to_id: int) -> None:
    """La relation qu'un flux saisi justifie, à la confiance de la saisie.

    Sa source est celle de la saisie (`atelier:<id>`), pour que le retrait
    l'emporte avec le flux. Une seule relation par couple et par type : si une
    autre, publiable ou d'égale confiance, dit déjà la même chose, on n'en
    ajoute pas — deux subventions saisies ne font pas deux liens sur la fiche.
    Rejouée à chaque passage : si la relation qui dispensait d'écrire celle-ci
    est retirée, celle-ci revient.
    """
    v = s["valeurs"]
    type_ = "subventionné" if v["type"].startswith("subvention") else v["type"]
    confiance = s.get("confidence", "confirmed")
    source = _source_de(s)
    deja = [r[0] for r in conn.execute(
        "SELECT confidence FROM relations WHERE from_id=? AND to_id=?"
        " AND relation_type=? AND source != ?", (from_id, to_id, type_, source))]
    if any(c in PUBLIABLES for c in deja) or (deja and confiance not in PUBLIABLES):
        return
    upsert_relation(
        conn, from_id=from_id, to_id=to_id, rel_type=type_,
        source=source, confidence=confiance,
        metadata=json.dumps({"year": v["year"], "amount": v["amount"]}))


def _inserer_flux(conn, s: dict, commune_id: int, doc_id: int | None) -> bool:
    source = _source_de(s)
    deja = conn.execute("SELECT from_id, to_id FROM financial_flows WHERE source=?",
                        (source,)).fetchone()
    if deja:
        _relier(conn, s, deja[0], deja[1])
        return False
    v = s["valeurs"]
    tiers_id = _entite_du_tiers(conn, v["tiers"], s.get("confidence", "confirmed"))
    cote_id = pivot_ids(conn)["epci"] if v.get("assemblee") == "epci" else commune_id
    verse = v.get("sens", "verse") == "verse"
    conn.execute(
        "INSERT INTO financial_flows"
        " (type,year,amount,from_id,to_id,description,source,confidence,statut,"
        "  origine,raw_document_id,saisi_par,saisi_le)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (v["type"], v["year"], v["amount"],
         cote_id if verse else tiers_id,
         tiers_id if verse else cote_id,
         v["description"], source, s.get("confidence", "confirmed"),
         v.get("statut", "realise"),
         ATELIER, doc_id, s.get("saisi_par"), s.get("saisi_le")))
    _relier(conn, s, cote_id if verse else tiers_id, tiers_id if verse else cote_id)
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


def _acte_de_la_saisie(conn, source: dict) -> int | None:
    """L'acte d'où une saisie a été lue, retrouvé sur CETTE base.

    Par sa clé datée d'abord — `events.id` change d'une machine et d'un rejeu à
    l'autre, la clé non. Une clé que portent deux actes ne désigne aucun des
    deux. À défaut, l'identifiant noté à la saisie, s'il désigne toujours un
    acte de la même date. Sinon rien : un rattachement faux ferait afficher le
    marché sous un acte qui n'en parle pas, pire que pas de rattachement.
    """
    cle, date = source.get("acte_cle"), source.get("acte_date")
    if cle:
        trouves = conn.execute("SELECT id FROM events WHERE cle_acte=? LIMIT 2",
                               (cle,)).fetchall()
        if len(trouves) == 1:
            return trouves[0][0]
    eid = source.get("event_id")
    if eid and date:
        r = conn.execute("SELECT id FROM events WHERE id=? AND substr(date,1,10)=?",
                         (int(eid), date)).fetchone()
        return r[0] if r else None
    return None


def _document_de_la_saisie(conn, source: dict, doc_id: int | None) -> int | None:
    """La pièce archivée, par son empreinte quand elle est connue : sur une
    autre machine, `raw_document_id` désigne un autre document, ou aucun."""
    if source.get("sha256"):
        r = conn.execute("SELECT id FROM raw_documents WHERE sha256=?",
                         (source["sha256"],)).fetchone()
        return r[0] if r else None
    return doc_id


def _inserer_marche(conn, s: dict, commune_id: int, doc_id: int | None) -> bool:
    from .marches_publics import acheteur_par_siren, siren_de
    source = _source_de(s)
    if _existe(conn, "marches_publics", source):
        return False
    v = s["valeurs"]
    src = s.get("source") or {}
    colonnes = {r[1] for r in conn.execute("PRAGMA table_info(marches_publics)")}
    # `acheteur_siren` est NOT NULL au schéma ; une saisie ne connaît pas
    # toujours le SIREN de l'acheteur qu'elle nomme. La chaîne vide dit
    # « non renseigné » sans mentir sur un identifiant qui, lui, est vérifiable.
    siren = siren_de(v.get("acheteur_siren"))
    valeurs = {
        "acheteur_id": acheteur_par_siren(conn, siren),
        "acheteur_siren": siren, "acheteur_nom": v["acheteur_nom"],
        "titulaire_nom": v.get("titulaire_nom"), "objet": v["objet"],
        "nature": v.get("nature"), "montant": v.get("montant"),
        "date_notif": v.get("date_notif"), "procedure": v.get("procedure"),
        "source": source, "source_url": src.get("url"), "raw_id": source,
        "event_id": _acte_de_la_saisie(conn, src),
        "confidence": s.get("confidence", "confirmed"), "origine": ATELIER,
        "raw_document_id": _document_de_la_saisie(conn, src, doc_id),
        "saisi_par": s.get("saisi_par"), "saisi_le": s.get("saisi_le"),
        "montant_base": v.get("montant_base"),
    }
    # Une base d'avant le 04/10/2026 n'a pas `montant_base` tant qu'`init_db`
    # n'est pas repassé : la saisie s'écrit sans, plutôt que d'échouer.
    valeurs = {c: x for c, x in valeurs.items() if c in colonnes}
    conn.execute(
        f"INSERT INTO marches_publics ({','.join(valeurs)}) "
        f"VALUES ({','.join('?' for _ in valeurs)})", tuple(valeurs.values()))
    return True


def ajouter(saisie: dict, chemin: Path | None = None) -> bool:
    """Ajoute une saisie au fichier, sauf si son identifiant y est déjà.

    Pour les écrivains dont l'identifiant est DÉRIVÉ (une ligne extraite
    acceptée, `collectors/marches_extraits.py`) : deux acceptations simultanées
    de la même ligne n'en écrivent qu'une. Rend True si elle a été ajoutée.
    """
    with modifier(chemin) as data:
        if any(s.get("id") == saisie["id"] for s in data.setdefault("saisies", [])):
            return False
        data["saisies"].append(saisie)
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
    # Une fiche créée à la main est d'origine `atelier` — ce que le commentaire
    # d'ici refusait jusqu'au 21/09/2026 au motif que `confidence` et
    # `validation_status` la décrivaient déjà. Ils ne la décrivaient pas : le
    # second n'était lu par rien, et l'on y écrivait `validated`, un mot que
    # l'API refusait elle-même. Le VERDICT, lui, n'est pas posé ici : saisir,
    # c'est proposer ; retenir revient à qui tranche (collectors/verdict.py).
    # Colonne absente sur une base pas encore passée par `init_db` : rien écrit
    # plutôt qu'une saisie qui échoue.
    if any(r[1] == "origine" for r in conn.execute("PRAGMA table_info(entities)")):
        conn.execute("UPDATE entities SET origine=? WHERE id=?", (ATELIER, eid))
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
    source = _source_de(s)
    tiers_id = None
    if table == "financial_flows":
        tiers_id = _tiers_cree_par(conn, s)
    cur = conn.execute(f"DELETE FROM {table} WHERE source=?", (source,))
    if table == "financial_flows":
        # Le flux parti, ce qu'il avait fait naître part avec lui : la relation
        # restait `confirmed` en base, et la passe suivante la republiait.
        conn.execute("DELETE FROM relations WHERE source=?", (source,))
        if tiers_id is not None and not _encore_cite(conn, tiers_id):
            conn.execute("DELETE FROM entities WHERE id=?", (tiers_id,))
    return cur.rowcount > 0


# Ce qui retient une fiche en base. Une table absente d'une base ancienne ne
# retient rien ; une table qu'on aurait oubliée ici, si — d'où la liste longue.
_ACCROCHES = (
    ("financial_flows", "from_id"), ("financial_flows", "to_id"),
    ("relations", "from_id"), ("relations", "to_id"),
    ("marches_publics", "titulaire_id"), ("marches_publics", "acheteur_id"),
    ("event_entities", "entity_id"), ("entity_notes", "entity_id"),
    ("elus_rne", "entity_id"), ("budget_indicators", "entity_id"),
    ("budget_annexe", "entity_id"),
    ("urbanisme_autorisations", "demandeur_entity_id"),
)


def _tiers_cree_par(conn, s: dict) -> int | None:
    """Le tiers que CETTE saisie a fait naître, s'il n'a pas été jugé depuis.

    Lu sur le flux avant qu'il parte. Trois conditions, toutes nécessaires : la
    saisie nommait un tiers au lieu d'en choisir un, la fiche est d'origine
    `atelier`, et elle n'est pas publiable — une fiche confirmée a été tranchée,
    elle ne disparaît pas avec la saisie qui l'a proposée.
    """
    v = s.get("valeurs") or {}
    if (v.get("tiers") or {}).get("id") or not (v.get("tiers") or {}).get("nom"):
        return None
    flux = conn.execute("SELECT from_id, to_id FROM financial_flows WHERE source=?",
                        (_source_de(s),)).fetchone()
    if not flux:
        return None
    tiers_id = flux[1] if v.get("sens", "verse") == "verse" else flux[0]
    fiche = conn.execute("SELECT origine, confidence FROM entities WHERE id=?",
                         (tiers_id,)).fetchone()
    if not fiche or fiche[0] != ATELIER or fiche[1] in PUBLIABLES:
        return None
    return tiers_id


def _encore_cite(conn, entite_id: int) -> bool:
    import sqlite3
    if conn.execute("SELECT 1 FROM annotations WHERE object_type='entity'"
                    " AND object_id=?", (entite_id,)).fetchone():
        return True
    for table, colonne in _ACCROCHES:
        try:
            if conn.execute(f"SELECT 1 FROM {table} WHERE {colonne}=?",
                            (entite_id,)).fetchone():
                return True
        except sqlite3.OperationalError:
            continue
    return False


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

        # Les retraits d'abord : une relation retirée peut être celle qui
        # dispensait une autre saisie d'écrire la sienne (cf. `_relier`).
        for s in lignes:
            if s.get("retire"):
                retirees += 1 if _retirer(conn, s) else 0
        for s in lignes:
            if s.get("retire"):
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
