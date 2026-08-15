#!/usr/bin/env python3
"""
build_public_snapshot.py — Build a conservative public data layer.

This script does not modify the SQLite database. It reads the private working
database in read-only mode and exports a small, publication-oriented JSON
snapshot with strict filters and a review report.

Usage:
    ~/venvs/agents/bin/python scripts/build_public_snapshot.py
    ~/venvs/agents/bin/python scripts/build_public_snapshot.py --out audits/public_snapshot_preview
"""
from __future__ import annotations

import argparse
import sys
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))

# Le périmètre est décrit une seule fois, dans la config des collecteurs : le
# snapshot ne redéclare ni la liste des communes ni le SIREN de l'EPCI.
from collectors.config import (  # noqa: E402
    COMMUNE_INSEE as INSEE_C1,
    EPCI_COMMUNES as COMMUNES_EPCI,
    EPCI_NOM as EPCI_NOM_C2,
    EPCI_SIREN as EPCI_SIREN_C2,
)
from collectors.config import DB_PATH   # nommée dans la config
RULES_PATH = ROOT / "config" / "publication_rules.json"


def load_rules(path: Path = RULES_PATH) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    required = ["confidence", "locations", "people", "relations", "events", "urls", "outputs"]
    missing = [key for key in required if key not in data]
    if missing:
        raise ValueError(f"publication_rules.json incomplet: {', '.join(missing)}")
    return data


RULES = load_rules()
DEFAULT_OUT = ROOT / RULES["outputs"]["public_snapshot_dir"]


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def rows(conn: sqlite3.Connection, sql: str, params=()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def row(conn: sqlite3.Connection, sql: str, params=()) -> dict | None:
    r = conn.execute(sql, params).fetchone()
    return dict(r) if r else None


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def relation_exists(conn: sqlite3.Connection, name: str) -> bool:
    """Table OU vue. `table_exists` filtre sur `type='table'` et renvoie donc
    False pour une vue — ce qui faisait silencieusement retourner un export
    vide pour `v_conflits_potentiels`."""
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?",
        (name,)
    ).fetchone() is not None


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_json_compact(path: Path, data) -> None:
    """Sans indentation ni espaces — pour ce que le navigateur télécharge.

    Les fichiers relus par un humain (stats, review) restent indentés ; l'index
    de recherche et les 2 800 fiches, non : l'indentation y pèse ~40 % du poids
    transféré pour zéro lisibilité utile.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8")


def safe_url(url: str | None) -> str | None:
    """Garde-fou : aucun chemin local ne doit sortir dans le snapshot public.

    Un `file:///Users/...` est à la fois un lien mort pour le lecteur et une
    fuite de l'arborescence personnelle. Voir scripts/fix_file_urls.py pour la
    correction en base ; ici on refuse simplement de publier le reliquat.
    """
    if not url:
        return None
    value = url.strip()
    if value.lower().startswith(("file:", "/users/", "c:\\")):
        return None
    return value


# ── Présentation des libellés publics ────────────────────────────────────────
# Les noms viennent bruts du RNA / SIRENE, donc en capitales, et les libellés de
# flux viennent des collecteurs, donc sans casse ni accent homogènes. Publier
# « ASSOCIATION DE PARENTS D'ELEVES DES ECOLES PUBLIQUES DE … » à côté de
# « Le Grillon » donne un flux qui a l'air cassé alors que la donnée est juste.

MOTS_LIAISON = {"DE", "DES", "DU", "D", "LA", "LE", "LES", "L", "ET", "EN",
                "AU", "AUX", "POUR", "SUR", "PAR", "UN", "UNE", "A", "AVEC",
                "SOUS", "SANS", "OU"}

# Sigles à conserver en capitales : la règle « ≤ 3 lettres ou pas de voyelle »
# ne les attrape pas tous, et un sigle title-casé (« Ccas ») est illisible.
ACRONYMES = {
    "ADMR", "AFPPA", "ANS", "APE", "ASART", "ASL", "ATSEM", "BOAMP", "CAC",
    "CAF", "CCAS", "CCAS", "CC", "CD30", "CDG", "CERISE", "CIAS", "CLIC",
    "CNRS", "CVN", "DDFIP", "DETR", "DGCL", "DGF", "DSP", "EHPAD", "EPCI",
    "EPI", "ESAT", "EVEN", "FCTVA", "FSC", "MJC", "MSA", "OFGL", "ONF",
    "PLU", "PNC", "RAM", "RNA", "RPI", "SAS", "SARL", "SCI", "SCIC", "SCOP",
    "SIVU", "SPANC", "SYMTOMA", "UFOLEP", "USEP", "USPOP", "VTT", "ZAD",
}


def joli_nom(nom: str | None) -> str:
    """Nom d'acteur présentable : casse humaine, sigles préservés.

    N'intervient QUE sur les noms tout en capitales (ceux du RNA/SIRENE) : un
    nom déjà saisi avec une casse mixte a été arbitré par un humain, on n'y
    touche pas.
    """
    nom = (nom or "").strip().rstrip(".")
    if not nom or nom != nom.upper():
        return nom

    def bloc(nu: str, premier: bool) -> str:
        if nu in ACRONYMES:
            return nu
        if nu in MOTS_LIAISON:
            return nu.capitalize() if premier else nu.lower()
        # Sigle probable : trop court pour être un mot, ou sans voyelle (HJH).
        # Le seuil est à 2 et non 3 : « NEZ », « ART », « VIV » sont des mots.
        if len(nu) <= 2 or not set(nu) & set("AEIOUY"):
            return nu
        return nu.capitalize()

    sortie = []
    for i, mot in enumerate(nom.split()):
        avant = mot[:len(mot) - len(mot.lstrip("(«\"'"))]
        apres = mot[len(mot.rstrip(")».,;:\"")):]
        nu = mot[len(avant):len(mot) - len(apres)] if apres else mot[len(avant):]
        if not nu:
            sortie.append(mot)
            continue
        # Un mot seul entre parenthèses est le sigle de ce qui précède —
        # « (CCAS) », « (CEPLR) » : le title-case en ferait « Ccas ».
        if "(" in avant and ")" in apres:
            sortie.append(mot)
            continue
        # Apostrophe : élision (« D'ACTION » → « d'Action ») ou nom composé
        # (« VIV'ALTO » → « Viv'Alto »). Les deux parts sont traitées à part.
        parts = re.split(r"(['’])", nu)
        if len(parts) == 3 and parts[0] in {"D", "L", "N", "S", "C", "J", "QU"}:
            rendu = ((parts[0].capitalize() if not i else parts[0].lower())
                     + parts[1] + bloc(parts[2], False))
        elif len(parts) == 3:
            rendu = bloc(parts[0], not i) + parts[1] + bloc(parts[2], False)
        else:
            rendu = bloc(nu, not i)
        sortie.append(avant + rendu + apres)
    return " ".join(sortie)


# « 11 637,87 € » en fin de libellé alors que le montant est déjà affiché en
# face : deux écritures du même chiffre, arrondies différemment.
_MONTANT_FINAL = re.compile(
    r"\s*[—–-]\s*[\d   ]+(?:[.,]\d+)?\s*€\s*$")


def nettoyer_libelle(texte: str | None, acteur: str | None = None,
                     montant_affiche=None) -> str:
    """Libellé de flux débarrassé de ce que la ligne affiche déjà par ailleurs.

    Le nom du bénéficiaire apparaissait jusqu'à trois fois sur une même ligne
    (« USEP Écoles — Subvention communale 2026 — USEP Écoles », plus le lien
    acteur en dessous) parce que chaque collecteur préfixait le libellé qu'il
    écrivait. On retire les répétitions plutôt que le contexte.
    """
    t = " ".join((texte or "").split())
    if not t:
        return t
    if acteur:
        cible = norm_nom(acteur)
        # Les collecteurs écrivent l'acteur tantôt en sigle (« ASART »), tantôt
        # sans apostrophe (« L Art Scene ») : la comparaison se fait sur les
        # tokens, pas sur la chaîne.
        jetons = lambda s: {m for m in norm_nom(s).replace("'", " ")
                            .replace("’", " ").split() if len(m) >= 2}
        cible_jetons = jetons(acteur)

        def redondant(seg: str) -> bool:
            j = jetons(seg)
            return bool(j) and j <= cible_jetons

        def sans_acteur(seg: str) -> str:
            # « USEP Écoles (320 + 4 044 + …) » : le nom préfixe le détail, on
            # ne garde que le détail — l'acteur est déjà en face de la ligne.
            if norm_nom(seg).startswith(cible + " "):
                reste = seg.strip()[len(acteur):].strip()
                if reste.startswith("("):
                    return reste
            return seg

        for sep in (" — ", " – ", " - "):
            morceaux = t.split(sep)
            if len(morceaux) > 1:
                gardes = [sans_acteur(m) for m in morceaux
                          if norm_nom(m) != cible and not redondant(m)]
                if gardes:
                    t = sep.join(gardes)
    if montant_affiche is not None:
        t = _MONTANT_FINAL.sub("", t)
    return t.strip(" —–-")


# Titres qui ne portent aucune information hors du document dont ils sont
# extraits : dans un flux d'actualité, ils occupent une ligne pour rien.
TITRES_VIDES = {"questions diverses", "divers", "informations diverses",
                "informations et questions diverses", "point divers",
                "questions et informations diverses", "(sans titre)"}

# « CM du 2026-05-28 - Conseil municipal du 28 Mai 2026 - … » : le préfixe de
# classement interne du collecteur, redondant avec la date affichée.
_PREFIXE_CM = re.compile(r"^CM\s+du\s+\d{4}-\d{2}-\d{2}\s*[-—–]\s*")


def nettoyer_titre_evenement(titre: str | None) -> str:
    return " ".join(_PREFIXE_CM.sub("", titre or "").split())


# ── Couche de revue : ce que l'atelier a rejeté ou rectifié ──────────────────
# La table `annotations` existait, les endpoints existaient, l'écran de revue
# existait — mais la publication ne la lisait pas. Rejeter ou corriger une
# donnée dans l'atelier n'avait donc aucun effet sur le site : toute correction
# passait par un script Python. C'est ce qui rendait la boucle interminable.
#
# Les corrections ne sont PAS écrites dans les tables sources (règle n°1 :
# jamais écraser). Elles sont appliquées ici, à la sortie, sur une copie.

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
            "statut": a["review_status"],
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
    if verdict["statut"] == "rejected":
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


MENTION_PARTICULIER = "un particulier"
# « M » sans point est exclu : sans lui, « TEAM SET INVESTIGATION » devenait
# « TEAun particulier INVESTIGATION » (le motif « M SET » mordait à l'intérieur
# du mot). Une civilité abrégée s'écrit avec son point.
_CIVILITES = r"(?:M\.|Mme|Mlle|Melle|Monsieur|Madame|Mademoiselle)"


def compilateur_redaction(conn, ids_publics: set[int]):
    """Masque les personnes physiques non publiables citées DANS LES TEXTES.

    Le filtre entités écarte bien un particulier du graphe, mais son nom
    ressortait quand même par les libellés : « Aide façade — M. Farget »,
    « Cession … à Prénom NOM (veuve NOM) ». Le texte est une sortie
    comme une autre, il doit passer le même filtre.

    On ne masque que des formes non ambiguës — nom complet, ou civilité + nom
    de famille. Un patronyme seul est trop souvent aussi un toponyme ou un nom
    de société d'ici pour être remplacé sans arbitrage.
    """
    prives = [
        r for r in rows(conn, """
            SELECT e.id, e.name, p.firstname, p.lastname
            FROM entities e LEFT JOIN persons p ON p.entity_id = e.id
            WHERE e.type = 'person'
        """) if r["id"] not in ids_publics
    ]
    motifs: set[str] = set()
    for p in prives:
        nom_complet = " ".join((p["name"] or "").split())
        prenom = " ".join((p["firstname"] or "").split())
        # Le patronyme peut porter un nom d'usage : « AEMMER (HAUSLER) ».
        patronyme = " ".join((p["lastname"] or "").split())
        if not patronyme and nom_complet:
            morceaux = nom_complet.split(" ", 1)
            patronyme = morceaux[1] if len(morceaux) > 1 else ""
        for forme in (nom_complet, f"{prenom} {patronyme}".strip(),
                      f"{patronyme} {prenom}".strip()):
            if len(forme.split()) >= 2:
                motifs.add(re.escape(forme))
        # Un patronyme précédé d'une civilité ne peut pas être autre chose.
        premier = patronyme.split("(")[0].strip()
        if len(premier) >= 3:
            motifs.add(rf"{_CIVILITES}\s+{re.escape(premier)}")

    if not motifs:
        return (lambda t: t), Counter()

    # Les formes longues d'abord : sinon « Prénom NOM » consomme le texte
    # avant que « Prénom NOM (veuve NOM) » ait sa chance.
    # `(?<!\w)` / `(?!\w)` plutôt que `\b` : certains noms d'usage finissent par
    # une parenthèse — « AEMMER (HAUSLER) » — devant laquelle `\b` ne matche pas.
    motif = re.compile(
        r"(?<!\w)(?:" + "|".join(sorted(motifs, key=len, reverse=True)) + r")(?!\w)",
        re.IGNORECASE)
    compteur = Counter()

    def redige(texte: str | None) -> str | None:
        if not texte:
            return texte
        sortie, n = motif.subn(MENTION_PARTICULIER, texte)
        if n:
            compteur["remplacements"] += n
        return sortie

    return redige, compteur


# Fourchette de montants publiables pour un acte local : en dessous, c'est un
# numéro d'article pris pour un euro ; au-dessus, une concaténation OCR.
MONTANT_MIN = 10
MONTANT_MAX = 50_000_000


# Seules clés de `relations.metadata` publiables : elles qualifient le lien
# lui-même (« responsable » de la commission, « volet agricole ») et rien de la
# personne. Le reste du bloc porte des données de travail — nom complet,
# année de naissance, notes d'enquête — qui ne sortent pas.
RELATION_META_PUBLIQUE = ("role", "precision")


def relation_meta_publique(brut: str | None) -> dict:
    if not brut:
        return {}
    try:
        meta = json.loads(brut)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(meta, dict):
        return {}
    return {k: meta[k] for k in RELATION_META_PUBLIQUE
            if isinstance(meta.get(k), str)}


def public_event_detail(metadata: dict, event_type: str) -> dict:
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
        valeurs = []
        for m in montants:
            v = m.get("montant", m.get("value")) if isinstance(m, dict) else m
            # Bornes de plausibilité : l'extraction OCR rapporte des numéros
            # d'article comme des euros (« 1 € ») et des concaténations de
            # chiffres comme des montants (213 087 450 € pour une communauté de
            # communes dont le budget total tient en 10 M€). Publier ces valeurs
            # décrédibilise toute la colonne montants.
            if isinstance(v, (int, float)) and MONTANT_MIN <= v <= MONTANT_MAX:
                valeurs.append(v)
        if valeurs:
            detail["montant_principal"] = max(valeurs)
            detail["montants"] = sorted(valeurs, reverse=True)[:5]
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

    if isinstance(metadata.get("ordre_du_jour"), list) and metadata["ordre_du_jour"]:
        detail["ordre_du_jour"] = metadata["ordre_du_jour"][:40]
        detail["nb_deliberations"] = metadata.get("nb_deliberations")

    for key in ("organizer", "organisateur"):
        if metadata.get(key):
            detail["organisateur"] = metadata[key]
            break
    for key in ("lieu", "address"):
        if metadata.get(key):
            detail["lieu"] = metadata[key]
            break

    if metadata.get("archived_copy"):
        detail["copie_archivee"] = True
        detail["archive_note"] = metadata.get("archive_note")

    return detail


def in_commune_bbox(lat, lng) -> bool:
    if lat is None or lng is None:
        return False
    bbox = RULES["locations"]["bbox"]
    return (
        bbox["lat_min"] <= lat <= bbox["lat_max"]
        and bbox["lng_min"] <= lng <= bbox["lng_max"]
    )


def in_center_box(lat, lng) -> bool:
    if lat is None or lng is None:
        return False
    box = RULES["locations"]["center_fallback_box"]
    return (
        box["lat_min"] <= lat <= box["lat_max"]
        and box["lng_min"] <= lng <= box["lng_max"]
    )


def domain_for(url: str | None) -> str:
    if not url:
        return ""
    value = url.strip()
    if not value:
        return ""
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    return urlparse(value).netloc.lower().removeprefix("www.")


def load_confirmed_urls() -> dict[int, list[dict]]:
    path = ROOT / "config" / "sites_locaux.json"
    if not path.exists():
        return {}

    data = json.loads(path.read_text(encoding="utf-8"))
    entries: list[dict] = []
    if isinstance(data, dict):
        for category, items in data.items():
            for item in items or []:
                item = dict(item)
                item["_category"] = category
                entries.append(item)
    elif isinstance(data, list):
        entries = data

    by_entity: dict[int, list[dict]] = defaultdict(list)
    for item in entries:
        entity_id = item.get("entity_id")
        url = (item.get("url") or "").strip()
        if not entity_id or not url or item.get("confirmed") is not True:
            continue
        dom = domain_for(url)
        if dom in set(RULES["urls"]["exclude_generic_domains"]):
            continue
        by_entity[int(entity_id)].append({
            "url": url,
            "domain": dom,
            "label": item.get("name") or dom,
            "source": "sites_locaux.confirmed",
        })
    return by_entity


# Types d'entités publiés en fiche pour les communes de l'intercommunalité.
# Une mairie, l'EPCI, un syndicat d'eau : ce sont les institutions qui décident,
# elles doivent être identifiables. Pas les entreprises, associations et lieux
# des 14 autres communes — cf. `publiable_dans_perimetre`.
TYPES_INSTITUTIONNELS = {"service"}


# ── Popolo ───────────────────────────────────────────────────────────────────
# Correspondance entre nos types de relation et le vocabulaire Popolo. Seuls
# les MANDATS deviennent des `Membership` : un mandat est bien « une personne,
# dans une organisation, avec un rôle, entre deux dates », ce que Popolo décrit
# exactement. Les liens économiques (subventionné, prestataire, bail) n'entrent
# pas dans ce moule — ce ne sont pas des appartenances — et restent dans
# `relations.json` et `flows.json`.
POPOLO_ROLES = {
    "maire":             "Maire",
    "adjoint":           "Adjoint au maire",
    "élu_cm":            "Conseiller municipal",
    "élu_cc":            "Conseiller communautaire",
    "président_cc":      "Président du conseil communautaire",
    "vice_président_cc": "Vice-président du conseil communautaire",
    "membre_commission": "Membre de commission",
    "candidat":          "Candidat",
}
# Nos six types d'entités vers la dichotomie Popolo. Popolo ne connaît que
# `Person` et `Organization` : un lieu ou une parcelle n'y a pas sa place, ils
# sont donc absents de cet export (ils restent dans `entities.json` et les
# couches GeoJSON).
POPOLO_ORG_CLASS = {
    "service":     "public_body",
    "association": "association",
    "business":    "company",
}


def build_popolo(entities: list[dict], relations: list[dict],
                 rules: dict = RULES) -> dict:
    """Vue Popolo des mandats publiés — personnes, organisations, appartenances.

    Ne recalcule aucun filtrage : on part des listes DÉJÀ filtrées pour la
    publication. Toute règle RGPD ou de confidence appliquée en amont vaut donc
    ici sans avoir à être répétée — et ne peut pas diverger.
    """
    par_id = {e["id"]: e for e in entities}

    persons, organizations = [], []
    for e in entities:
        if e["type"] == "person":
            persons.append({
                "id": f"person/{e['id']}",
                "name": e["name"],
                # `sort_name` : Popolo prévoit le nom de tri séparément du nom
                # d'affichage. On n'a pas de découpage nom/prénom fiable pour
                # toutes les personnes, on ne l'invente pas.
                "identifiers": [{"scheme": "vigie-civique", "identifier": str(e["id"])}],
                "links": [{"url": u} for u in (e.get("urls") or []) if u],
            })
        elif e["type"] in POPOLO_ORG_CLASS:
            organizations.append({
                "id": f"organization/{e['id']}",
                "name": e["name"],
                "other_names": ([{"name": e["short_name"]}] if e.get("short_name") else []),
                "classification": POPOLO_ORG_CLASS[e["type"]],
                "area_id": f"area/{e['commune']}" if e.get("commune") else None,
                "founding_date": e.get("creation_date"),
                "identifiers": (
                    [{"scheme": "vigie-civique", "identifier": str(e["id"])}]
                    + ([{"scheme": "RNA", "identifier": e["rna_id"]}] if e.get("rna_id") else [])
                ),
                "links": [{"url": u} for u in (e.get("urls") or []) if u],
            })

    memberships = []
    for r in relations:
        role = POPOLO_ROLES.get(r["relation_type"])
        if role is None:
            continue
        source, cible = par_id.get(r["from_id"]), par_id.get(r["to_id"])
        if not source or not cible:
            continue
        if source["type"] != "person" or cible["type"] not in POPOLO_ORG_CLASS:
            continue
        memberships.append({
            "id": f"membership/{r['id']}",
            "person_id": f"person/{r['from_id']}",
            "organization_id": f"organization/{r['to_id']}",
            "role": role,
            "start_date": r.get("since"),
            "end_date": r.get("until"),
            # Hors spec Popolo, mais c'est la colonne vertébrale du projet :
            # aucune affirmation n'est publiée sans sa source ni son niveau de
            # certitude. Les retirer pour rester canonique appauvrirait
            # l'export de ce qui en fait la valeur.
            "sources": [{"note": r["source"]}] if r.get("source") else [],
            "vigie_confidence": r.get("confidence"),
        })

    areas = sorted({e["commune"] for e in entities if e.get("commune")})
    return {
        "@context": "https://www.popoloproject.com/contexts/organization.jsonld",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        # Licence et attributions : lues dans la config, jamais écrites ici.
        # Le raisonnement qui a conduit à l'ODbL est consigné dans
        # `config/publication_rules.json → outputs._license_note`.
        "license": rules["outputs"]["license"],
        "license_url": rules["outputs"]["license_url"],
        "attribution": rules["outputs"]["attribution"],
        "source_attributions": rules["outputs"]["source_attributions"],
        "note": (
            "Vue Popolo (popoloproject.com) des mandats publiés. Sous-ensemble "
            "de entities.json et relations.json, exporté dans un vocabulaire "
            "partagé pour être réutilisable hors de ce projet. Les liens "
            "économiques et les lieux n'entrent pas dans ce modèle et restent "
            "dans les fichiers d'origine. Pas de VoteEvent : les "
            "procès-verbaux publiés ne donnent pas les votes nominatifs."
        ),
        "persons": persons,
        "organizations": organizations,
        "memberships": memberships,
        "areas": [{"id": f"area/{a}", "name": a, "classification": "commune"}
                  for a in areas],
    }


def publiable_dans_perimetre(perimetre: str | None, entity_type: str | None,
                             siege_a_l_epci: bool) -> bool:
    """Le périmètre autorise-t-il une FICHE publique pour cette entité ?

    Le site public est celui de la commune. La collecte, elle, porte sur toute
    l'intercommunalité : sur une instance ordinaire la base contient deux à
    quatre fois plus d'entités C2 que de C1. Les publier toutes ferait passer un
    annuaire intercommunal pour l'annuaire communal, et un lecteur croirait que
    la boulangerie d'une commune membre est dans la commune-siège.

    Sont publiées en fiche :
      - C1   tout ce que les autres règles autorisent ;
      - C2   les institutions (mairies, EPCI, syndicats) et les seules
             personnes qui SIÈGENT au conseil communautaire — celles-là votent
             le budget et les compétences qui s'appliquent à la commune, les
             masquer amputerait la chaîne de décision de sa moitié
             intercommunale. En revanche, publier les conseils municipaux
             entiers des autres communes membres serait à la fois hors sujet et
             difficilement justifiable au regard du RGPD : ces élus n'ont
             aucun pouvoir de décision sur la commune ;
      - C3   les institutions supra-communales, même raison ;
      - lien les entités rattachées à un acteur de la commune (SCI d'élus,
             titulaires de marchés) : matériau du graphe d'influence, les
             règles de pertinence existantes s'appliquent inchangées.

    Les données des communes C2 restent publiées de façon AGRÉGÉE
    (`intercommunalite.json`, `fiscalite.json`, `territoire.json`) : comparer
    la commune à ses pairs informe, lister leurs commerces non.

    NULL n'est pas C1. Une entité non classée est une entité dont on ignore si
    elle appartient au territoire : la publier par défaut, c'est publier toute
    l'intercommunalité le jour où le classement n'a pas tourné. Mesuré le
    14/08/2026 sur deux instances neuves : 4 944 fiches publiées au lieu de
    1 807, et un site de commune dont 57 % des fiches relevaient d'une voisine.
    Le classement absent doit produire un site vide et un message, pas un
    annuaire de vallée — `exiger_perimetre_classe()` s'en charge en amont.
    """
    if perimetre in ("C1", "lien"):
        return True
    if perimetre in ("C2", "C3"):
        return entity_type in TYPES_INSTITUTIONNELS or siege_a_l_epci
    return False


class PerimetreNonClasse(RuntimeError):
    """`entities.perimetre` n'a jamais été renseignée sur cette base."""


def exiger_perimetre_classe(conn) -> int:
    """Refuse de construire un snapshot sur une base jamais classée.

    Retourne le nombre d'entités sans périmètre (exclues silencieusement de la
    publication, ce qui est le comportement sûr). Lève si AUCUNE ne l'a : ce
    n'est plus une lacune, c'est une étape qui n'a pas eu lieu, et le snapshot
    produit serait vide sans que rien ne le dise.
    """
    total = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    if not total:
        return 0
    classees = conn.execute(
        "SELECT COUNT(*) FROM entities WHERE perimetre IS NOT NULL").fetchone()[0]
    if not classees:
        raise PerimetreNonClasse(
            f"{total} entités en base, aucune classée par périmètre.\n"
            "  Le snapshot serait vide : sans classement, aucune entité n'est\n"
            "  publiable (et le défaut inverse publierait l'intercommunalité).\n"
            "  Lancer :  python3 scripts/classer_perimetre.py\n"
            "  Le step `perimetre` de `python3 -m collectors.run_all` le fait\n"
            "  en fin de collecte."
        )
    return total - classees


def public_entity(
    row_data: dict,
    urls: list[dict],
    public_person_ids: set[int],
    ids_conseil_communautaire: set[int] = frozenset(),
) -> tuple[dict | None, list[str]]:
    reasons: list[str] = []
    confidence = row_data.get("confidence")
    if confidence not in set(RULES["confidence"]["public"]):
        return None, ["private_confidence"]

    entity_type = row_data.get("type")
    if entity_type == "person" and row_data["id"] not in public_person_ids:
        return None, ["person_without_public_civic_role"]

    perimetre = row_data.get("perimetre")
    if not publiable_dans_perimetre(perimetre, entity_type,
                                    row_data["id"] in ids_conseil_communautaire):
        return None, [f"hors_fiche_perimetre_{perimetre}"]

    lat = row_data.get("lat")
    lng = row_data.get("lng")
    has_public_location = False
    location_quality = "missing"

    if entity_type == "person":
        location_quality = "hidden_person"
        lat = None
        lng = None
    elif row_data.get("lat") is None or row_data.get("lng") is None:
        location_quality = "missing"
    elif (entity_type == "business"
          and str(row_data.get("legal_form_code") or "") == "1000"
          and row_data.get("geocode_source") != "manual"):
        # RGPD : entrepreneur individuel — le siège est très souvent le domicile.
        # Coords retirées du public, sauf placement manuel délibéré à l'atelier
        # (structure avec un vrai local). cf. known-issues « vigilance RGPD ».
        location_quality = "hidden_ei_domicile"
        lat = None
        lng = None
    elif not in_commune_bbox(row_data["lat"], row_data["lng"]):
        location_quality = "outside_lasalle_bbox"
        lat = None
        lng = None
    elif in_center_box(row_data["lat"], row_data["lng"]):
        location_quality = "approx_center"
        has_public_location = entity_type in {"place", "service"}
        if not has_public_location:
            lat = None
            lng = None
    else:
        location_quality = "usable"
        has_public_location = True

    public = {
        "id": row_data["id"],
        "type": entity_type,
        "name": row_data["name"],
        "short_name": row_data.get("short_name"),
        # La commune de rattachement : la collecte couvre les 15 communes de
        # l'intercommunalité, et rien ne le disait sur une fiche — un lecteur
        # pouvait croire que tout était à Lasalle.
        "commune": row_data.get("commune"),
        # C1 = Lasalle, C2 = l'intercommunalité, C3 = autorité supra-communale,
        # lien = rattaché à un acteur suivi sans être sur le territoire.
        # L'UI doit le montrer : une fiche C2 ou `lien` ne se lit pas comme une
        # fiche lasalloise.
        "perimetre": row_data.get("perimetre"),
        "confidence": confidence,
        "location_quality": location_quality,
        "lat": lat,
        "lng": lng,
        "has_public_location": has_public_location,
        "urls": urls,
    }

    if entity_type == "business":
        public.update({
            "siren": row_data.get("siren"),
            "naf_code": row_data.get("naf_code"),
            "naf_label": row_data.get("naf_label"),
            "status": row_data.get("biz_status"),
            "creation_date": row_data.get("business_creation_date"),
        })
    elif entity_type == "association":
        public.update({
            "rna_id": row_data.get("rna_id"),
            "object": row_data.get("asso_object"),
            "creation_date": row_data.get("asso_creation_date"),
        })
    elif entity_type == "place":
        public.update({
            "osm_category": row_data.get("osm_category"),
            "osm_value": row_data.get("osm_value"),
        })
    elif entity_type == "service":
        public.update({
            "category": row_data.get("service_category"),
            "operator": row_data.get("operator"),
            "opening_hours": row_data.get("opening_hours"),
        })
    elif entity_type == "person":
        public.update({
            "firstname": row_data.get("firstname"),
            "lastname": row_data.get("lastname"),
        })

    return public, reasons


def write_entity_bundles(out: Path, public_entities, public_relations,
                         public_events, public_links, public_flows,
                         marches_data) -> int:
    """Un fichier par acteur : `entite/<id>.json`, tout pré-résolu.

    Avant ça, afficher une fiche imposait de télécharger `entities.json`
    (1,1 Mo) + `events.json` (1 Mo) + `event_links.json` (387 Ko) +
    `relations.json` + `flows.json` + `marches.json` — près de 3 Mo pour lire
    une association, et tout le filtrage fait dans le navigateur. Sur le réseau
    des Cévennes c'est disqualifiant. Chaque bundle fait quelques kilo-octets et
    contient exactement ce que la page affiche.

    Ces fichiers alimentent aussi le prérendu (`+page.server.js`) : le contenu
    part dans le HTML, donc les fiches sont enfin indexables et partageables.
    """
    names = {e["id"]: e["name"] for e in public_entities}
    events_by_id = {e["id"]: e for e in public_events}

    liens_par_entite: dict[int, list[dict]] = defaultdict(list)
    for link in public_links:
        event = events_by_id.get(link["event_id"])
        if event:
            liens_par_entite[link["entity_id"]].append({**event, "role": link["role"]})

    relations_par_entite: dict[int, list[dict]] = defaultdict(list)
    for rel in public_relations:
        for side, autre_id in (("from_id", rel["to_id"]), ("to_id", rel["from_id"])):
            eid = rel[side]
            relations_par_entite[eid].append({
                **rel,
                "autre_id": autre_id,
                "autre": names.get(autre_id),
            })

    flows_par_entite: dict[int, list[dict]] = defaultdict(list)
    for flow in public_flows:
        if flow.get("perimetre") == "agregat":
            continue
        for eid in {flow.get("from_id"), flow.get("to_id")} - {None}:
            flows_par_entite[eid].append(flow)

    marches_par_entite: dict[int, list[dict]] = defaultdict(list)
    for marche in marches_data:
        for eid in {marche.get("titulaire_id"), marche.get("acheteur_id")} - {None}:
            marches_par_entite[eid].append(marche)

    dest = out / "entite"
    dest.mkdir(parents=True, exist_ok=True)
    for entity in public_entities:
        eid = entity["id"]
        write_json_compact(dest / f"{eid}.json", {
            "entity": entity,
            "relations": relations_par_entite.get(eid, []),
            "liens": sorted(liens_par_entite.get(eid, []),
                            key=lambda e: (e.get("date") or ""), reverse=True),
            "flows": sorted(flows_par_entite.get(eid, []),
                            key=lambda f: (f.get("year") or 0), reverse=True),
            "marches": marches_par_entite.get(eid, []),
        })
    return len(public_entities)


def write_search_index(out: Path, public_entities, communes: dict[int, str],
                       liens_count: dict[int, int]) -> int:
    """Index de recherche léger, et liste des ids pour le prérendu.

    Le site public exposait 2 673 acteurs sans le moindre champ de recherche :
    pour trouver une association il fallait la repérer à l'œil sur la carte ou
    dans une grille. L'index tient dans ~150 Ko et se filtre côté client, sans
    backend (le public est statique).

    `nb` (nombre d'actes rattachés) sert à classer les résultats : un acteur
    présent dans dix délibérations passe avant un homonyme dormant.
    """
    index = [
        {
            "id": e["id"],
            "n": e["name"],
            "t": e["type"],
            "s": e.get("short_name") or None,
            "c": communes.get(e["id"]) or None,
            "nb": liens_count.get(e["id"], 0),
        }
        for e in public_entities
    ]
    index.sort(key=lambda r: (-r["nb"], r["n"] or ""))
    write_json_compact(out / "entity_index.json", {"entities": index, "total": len(index)})
    return len(index)


def norm_nom(s: str | None) -> str:
    """Nom normalisé pour comparaison : sans accents, majuscules, compacté."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return " ".join(s.upper().replace("-", " ").split())


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


def deports_par_deliberation(conn) -> list[dict]:
    """Déports consignés dans les comptes rendus : « X ne participe pas ».

    Découverte du 26/07/2026 : `metadata.conflit_interet` de 15 délibérations
    nomme les élus qui se sont retirés du vote. C'est décisif pour la page
    publique : un élu qui dirige une association subventionnée n'est pas en
    faute s'il ne participe pas au vote. Sans cette information, la page
    accuserait là où le conseil a précisément fait ce qu'il devait.
    """
    return rows(conn, """
        SELECT ev.id, ev.date, ev.title, ev.source_url,
               json_extract(ev.metadata,'$.conflit_interet') AS mention
        FROM events ev
        WHERE json_extract(ev.metadata,'$.conflit_interet') IS NOT NULL
          AND json_extract(ev.metadata,'$.conflit_interet') NOT IN ('false','0','')
        ORDER BY ev.date
    """)


def export_conflits(conn, public_ids: set[int]) -> dict:
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
    """
    if not relation_exists(conn, "v_conflits_potentiels"):
        return {"cas": [], "total": 0, "deports_repertories": 0, "methode": {}}

    brut = rows(conn, "SELECT * FROM v_conflits_potentiels")
    deports = deports_par_deliberation(conn)

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
    cas_final = []
    for cas in groupes.values():
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


def beneficiaires_argent_public(conn) -> set[int]:
    """Entités ayant reçu de l'argent public : subvention, marché, bail.

    Base de la règle de pertinence : le lien économique d'une personne avec une
    structure qui touche de l'argent public est d'intérêt général, celui avec une
    société sans rapport avec la commune ne l'est pas.

    Les flux sont sommés sur `perimetre='detail' AND statut='realise'` uniquement :
    les agrégats OFGL englobent la DGF présente en détail (double compte), et
    `statut='demande'` désigne une subvention **sollicitée**, pas obtenue.
    """
    ids: set[int] = set()
    for r in rows(conn, """
        SELECT DISTINCT to_id AS id FROM financial_flows
         WHERE to_id IS NOT NULL
           AND COALESCE(perimetre,'detail') = 'detail'
           AND COALESCE(statut,'realise')   = 'realise'
    """):
        ids.add(r["id"])
    if table_exists(conn, "marches_publics"):
        for r in rows(conn, "SELECT DISTINCT titulaire_id AS id FROM marches_publics"
                            " WHERE titulaire_id IS NOT NULL"):
            ids.add(r["id"])
    types = sorted(RULES["relations"]["public_money_relation_types"])
    for r in rows(conn, f"""
        SELECT DISTINCT from_id AS a, to_id AS b FROM relations
         WHERE relation_type IN ({",".join("?" for _ in types)})
           AND confidence IN ({",".join("?" for _ in RULES["confidence"]["public"])})
    """, [*types, *sorted(RULES["confidence"]["public"])]):
        ids.update({r["a"], r["b"]} - {None})
    return ids


def relation_pertinente(rel: dict, civic_ids: set[int],
                        beneficiaires: set[int],
                        ei_ids: set[int] | None = None) -> bool:
    """Un lien économique a-t-il un rapport avec l'action publique ?

    Vrai si une extrémité est un acteur civique (élu, candidat — ses intérêts
    économiques relèvent de la déclaration d'intérêts), ou si une extrémité a
    reçu de l'argent public (on publie alors qui dirige la structure payée).

    Exception : les **entreprises individuelles**. Une EI n'est pas une personne
    morale distincte de son exploitant : « Prénom NOM dirige PRENOM NOM » est
    une tautologie issue de SIRENE, qui n'informe personne et re-expose un
    particulier. Le projet traite déjà l'EI comme une donnée personnelle
    (679 domiciles masqués sur la carte) ; on reste cohérent.

    Deux détections, parce qu'aucune ne suffit seule :
      - forme juridique 1000 (907 entités) ;
      - **même nom normalisé aux deux bouts** — indispensable car 10 entités ont
        un `legal_form_code` NULL (l'enrichissement SIRENE ne l'a pas rempli) et
        passaient donc le premier filtre : « Prénom NOM → PRENOM NOM »,
        « Philippe BRISSAC → PHILIPPE BRISSAC »…
    """
    bouts = {rel.get("from_id"), rel.get("to_id")} - {None}
    if ei_ids and bouts & ei_ids:
        return False
    if norm_nom(rel.get("from_name")) == norm_nom(rel.get("to_name")):
        return False
    return bool(bouts & civic_ids) or bool(bouts & beneficiaires)


def is_public_relation(rel: dict, public_ids: set[int],
                       civic_ids: set[int] | None = None,
                       beneficiaires: set[int] | None = None,
                       ei_ids: set[int] | None = None) -> tuple[bool, str]:
    if rel.get("confidence") not in set(RULES["confidence"]["public"]):
        return False, "private_confidence"
    if rel["from_id"] not in public_ids or rel["to_id"] not in public_ids:
        return False, "endpoint_not_public"
    relation_type = rel.get("relation_type") or ""
    if any(marker in relation_type for marker in RULES["relations"]["private_markers"]):
        return False, "private_relation_type"
    if relation_type in set(RULES["relations"]["public_allowlist"]):
        return True, "public"
    # Liens économiques : publiés au cas par cas selon la pertinence, pas par type.
    if relation_type in set(RULES["relations"].get("relevance_allowlist", [])):
        if relation_pertinente(rel, civic_ids or set(), beneficiaires or set(),
                               ei_ids or set()):
            return True, "public_par_pertinence"
        return False, "economique_sans_lien_public"
    return False, "not_in_public_allowlist"


def _commune_entity_id(conn) -> int | None:
    """Id de l'entité « Commune de … », ou None si elle n'est pas en base."""
    from collectors.config import COMMUNE_NAME
    row = conn.execute(
        "SELECT id FROM entities WHERE type='service' AND name=? LIMIT 1",
        (f"Commune de {COMMUNE_NAME}",)).fetchone()
    return row["id"] if row else None


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



def export_couverture(conn, public_events: list[dict], stats: dict) -> dict:
    """Ce que la collecte couvre, et surtout ce qu'elle ne couvre pas.

    Un observatoire qui n'affiche que ce qu'il sait ressemble à une boîte
    noire : le lecteur ne peut pas distinguer « il ne s'est rien passé en
    2019 » de « nous n'avons pas collecté 2019 ». Publier les trous coûte peu
    et vaut mieux que de paraître complet.

    Trois choses différentes, à ne pas confondre :
      - la PÉRIODE réellement couverte par source ;
      - la FRAÎCHEUR, c'est-à-dire la dernière collecte et son issue ;
      - les EXCLUSIONS délibérées (périmètre, vie privée), qui ne sont pas
        des lacunes mais des choix, et qui sont déjà dans `stats`.
    """
    par_source: dict[str, dict] = {}
    for e in public_events:
        src = e.get("source") or "inconnue"
        d = par_source.setdefault(src, {"source": src, "actes": 0,
                                        "debut": None, "fin": None,
                                        "avec_document": 0})
        d["actes"] += 1
        if e.get("document") == "acte":
            d["avec_document"] += 1
        date = e.get("date")
        if date:
            if d["debut"] is None or date < d["debut"]:
                d["debut"] = date
            if d["fin"] is None or date > d["fin"]:
                d["fin"] = date

    # Dernier passage de chaque collecteur : un collecteur muet depuis des mois
    # est une lacune en formation, pas encore visible dans les compteurs.
    derniers = {}
    if table_exists(conn, "collector_runs"):
        for r in rows(conn, """
            SELECT collector, status, MAX(started_at) AS dernier
            FROM collector_runs GROUP BY collector
        """):
            derniers[r["collector"]] = {"statut": r["status"], "dernier": r["dernier"]}

    doc = stats.get("provenance", {}).get("document", {})
    total_actes = sum(doc.values()) or 1

    return {
        "arrete_le": stats.get("generated_at"),
        "sources": sorted(par_source.values(), key=lambda d: -d["actes"]),
        "collecteurs": derniers,
        # Le chiffre le plus inconfortable du site, donc celui qu'il faut donner
        # en premier : la proportion d'actes dont la pièce elle-même est
        # consultable, par opposition à la page qui la contient.
        "actes_avec_piece": doc.get("acte", 0),
        "actes_total": total_actes,
        "part_avec_piece": round(100 * doc.get("acte", 0) / total_actes, 1),
        "lacunes_connues": [
            {
                "sujet": "Documents des délibérations",
                "etat": "partiel",
                "detail": ("La très grande majorité des actes renvoient vers la page du "
                           "compte rendu qui les contient, et non vers la délibération "
                           "elle-même. Il faut donc chercher le passage dans le document."),
            },
            {
                "sujet": "Mandatures antérieures à 2020",
                "etat": "incomplet",
                "detail": ("L'historique des mandats est lacunaire avant 2020, ce qui empêche "
                           "de dire si une personne était élue à la date d'un versement "
                           "ancien. Les situations concernées sont signalées comme telles."),
            },
            {
                "sujet": "Dirigeants d'associations",
                "etat": "incomplet",
                "detail": ("Aucune source ouverte ne publie les dirigeants d'associations. "
                           "Ceux qui figurent ici proviennent de documents publics les "
                           "nommant, jamais d'un registre exhaustif."),
            },
            {
                "sujet": "Recoupement entre sources",
                "etat": "absent",
                "detail": ("Aucune donnée n'est aujourd'hui confirmée par deux sources "
                           "indépendantes : la chaîne ne sait pas encore le faire."),
            },
        ],
    }



def write_recherche_index(out: Path, public_entities, public_events,
                          marches_data, public_flows, communes: dict[int, str],
                          liens_count: dict[int, int]) -> int:
    """Index de recherche transversal : acteurs, actes, marchés, versements.

    La recherche ne portait que sur les acteurs. Or on ne cherche pas seulement
    « qui » : on cherche « piscine », « école », « assainissement », « 15 000 »,
    une parcelle, une année. Chercher un mot et ne trouver que des noms
    d'entreprises donne l'impression que le site ne sait rien d'un sujet dont
    il a pourtant les actes.

    Format court volontaire (`k`, `t`, `n`, `d`, `u`, `m`) : l'index est
    embarqué dans la page et chaque clé est répétée à chaque ligne.
    Les champs :
      k  catégorie  acteur | acte | marche | versement
      t  titre affiché
      n  poids de tri (plus grand = remonte)
      d  date, quand elle existe
      u  URL interne de destination
      m  montant, quand il y en a un
      c  commune ou contexte
    """
    idx: list[dict] = []

    for e in public_entities:
        idx.append({
            "k": "acteur", "t": e["name"], "u": f"/entite/{e['id']}",
            "c": communes.get(e["id"]) or None,
            "n": 1000 + liens_count.get(e["id"], 0),
        })

    for ev in public_events:
        annee = (ev.get("date") or "")[:4] or "sans-date"
        idx.append({
            "k": "acte", "t": ev.get("title") or "(sans titre)",
            "u": f"/deliberations/{annee}#a{ev['id']}",
            "d": ev.get("date"), "m": ev.get("montant_principal"),
            "c": ev.get("source"),
            # Un acte portant un montant est plus souvent ce qu'on cherche.
            "n": 500 + (200 if ev.get("montant_principal") else 0),
        })

    for m in marches_data:
        titre = m.get("objet") or "Marché"
        if m.get("titulaire_nom"):
            titre = f"{titre} — {m['titulaire_nom']}"
        idx.append({
            "k": "marche", "t": titre, "u": "/marches",
            "d": m.get("date_notif"), "m": m.get("montant"),
            "c": m.get("acheteur_nom"), "n": 600,
        })

    for f in public_flows:
        if not f.get("to_name"):
            continue
        idx.append({
            "k": "versement",
            "t": f"{f.get('type_norm') or f.get('type') or 'Flux'} — {f['to_name']}",
            "u": "/finances", "d": str(f["year"]) if f.get("year") else None,
            "m": f.get("amount"), "c": f.get("from_name"), "n": 400,
        })

    idx.sort(key=lambda r: (-r["n"], r["t"] or ""))
    write_json_compact(out / "recherche_index.json",
                       {"index": idx, "total": len(idx)})
    return len(idx)


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


def synchroniser_site_public(src: Path, root: Path) -> dict:
    """Recopie le snapshot là où le site public le lit.

    Le builder écrit dans `outputs.public_snapshot_dir` (l'atelier le sert
    depuis là), le site public lit `public/static/data`. Le raccord entre les
    deux a longtemps vécu dans `api.py`, appelé depuis un script de
    déploiement qui n'était pas livré avec le moteur : une instance suivait le
    README, produisait un snapshot, et se retrouvait avec un site vide sans
    qu'aucune étape n'ait échoué.

    `entite/` est mis en MIROIR, pas seulement copié : une entité retirée de la
    publication doit voir sa page disparaître, sinon elle reste en ligne.
    """
    import shutil

    dest = root / "public" / "static" / "data"
    (dest / "layers").mkdir(parents=True, exist_ok=True)
    (dest / "entite").mkdir(parents=True, exist_ok=True)
    copied = []
    for f in sorted(src.glob("*.json")):
        shutil.copy2(f, dest / f.name)
        copied.append(f.name)
    # Le README est le dictionnaire de données : il accompagne les JSON, il ne
    # reste pas dans le dépôt. Il était exclu de la synchro, si bien que
    # `public/static/data/README.md` annonçait des chiffres faux à côté de
    # fichiers à jour.
    readme = src / "README.md"
    if readme.exists():
        shutil.copy2(readme, dest / "README.md")
        copied.append("README.md")
    for f in sorted((src / "layers").glob("*.geojson")):
        shutil.copy2(f, dest / "layers" / f.name)
        copied.append(f"layers/{f.name}")

    fiches = {f.name for f in (src / "entite").glob("*.json")}
    for f in sorted((src / "entite").glob("*.json")):
        shutil.copy2(f, dest / "entite" / f.name)
        copied.append(f"entite/{f.name}")
    retirees = []
    for f in sorted((dest / "entite").glob("*.json")):
        if f.name not in fiches:
            f.unlink()
            retirees.append(f.name)
    return {"dest": str(dest), "files": copied, "count": len(copied),
            "fiches_retirees": retirees}


def build_snapshot(out: Path) -> dict:
    conn = get_db()
    try:
        # Avant toute lecture : une base non classée ne produit pas un snapshot,
        # elle produit une erreur. Cf. `publiable_dans_perimetre`.
        sans_perimetre = exiger_perimetre_classe(conn)

        confirmed_urls = load_confirmed_urls()
        counters = Counter()
        counters["entities_sans_perimetre"] = sans_perimetre
        exclusions = defaultdict(Counter)
        revue = charger_revue(conn)
        counters["revue_annotations"] = sum(len(v) for v in revue.values())

        entity_rows = rows(conn, """
            SELECT
                e.id, e.type, e.name, e.short_name, e.lat, e.lng, e.address, e.confidence,
                e.geocode_source, e.commune, e.perimetre,
                p.firstname, p.lastname, p.birth_year,
                b.siren, b.naf_code, b.naf_label, b.status AS biz_status,
                b.legal_form_code,
                b.creation_date AS business_creation_date,
                a.rna_id, a.object AS asso_object,
                a.creation_date AS asso_creation_date,
                pl.osm_category, pl.osm_value,
                s.category AS service_category, s.operator, s.opening_hours
            FROM entities e
            LEFT JOIN persons p ON p.entity_id = e.id
            LEFT JOIN businesses b ON b.entity_id = e.id
            LEFT JOIN associations a ON a.entity_id = e.id
            LEFT JOIN places pl ON pl.entity_id = e.id
            LEFT JOIN services s ON s.entity_id = e.id
            ORDER BY e.name
        """)

        # 1) Personnes à rôle civique : élus, candidats, membres de commission.
        civic_person_ids = {
            r["entity_id"] for r in rows(conn, f"""
                SELECT DISTINCT e.id AS entity_id
                FROM entities e
                JOIN relations r ON r.from_id = e.id OR r.to_id = e.id
                WHERE e.type = 'person'
                  AND e.confidence IN ({",".join("?" for _ in RULES["confidence"]["public"])})
                  AND r.confidence IN ({",".join("?" for _ in RULES["confidence"]["public"])})
                  AND r.relation_type IN ({",".join("?" for _ in RULES["people"]["publish_only_with_relation_types"])})
            """, [
                *sorted(RULES["confidence"]["public"]),
                *sorted(RULES["confidence"]["public"]),
                *sorted(RULES["people"]["publish_only_with_relation_types"]),
            ])
        }

        # 2) Règle de pertinence (arbitrage du 26/07/2026) : une personne devient
        # publiable si elle dirige une structure ayant reçu de l'argent public.
        # Publier « qui a touché » sans pouvoir dire « qui la dirige » n'informe
        # personne ; à l'inverse, le gérant d'une société sans lien avec la
        # commune reste privé.
        beneficiaires = beneficiaires_argent_public(conn)
        # Entreprises individuelles : le lien « dirigeant » y est tautologique.
        ei_ids = {r["id"] for r in entity_rows
                  if str(r.get("legal_form_code") or "") == "1000"}
        eco_types = sorted(RULES["relations"].get("relevance_allowlist", []))
        pertinent_person_ids: set[int] = set()
        if eco_types and beneficiaires:
            marks = ",".join("?" for _ in eco_types)
            benes = ",".join("?" for _ in beneficiaires)
            pertinent_person_ids = {
                r["entity_id"] for r in rows(conn, f"""
                    SELECT DISTINCT e.id AS entity_id
                    FROM entities e
                    JOIN relations r ON r.from_id = e.id OR r.to_id = e.id
                    WHERE e.type = 'person'
                      AND e.confidence IN ({",".join("?" for _ in RULES["confidence"]["public"])})
                      AND r.confidence IN ({",".join("?" for _ in RULES["confidence"]["public"])})
                      AND r.relation_type IN ({marks})
                      AND (r.from_id IN ({benes}) OR r.to_id IN ({benes}))
                      AND r.from_id NOT IN (SELECT entity_id FROM businesses
                                             WHERE legal_form_code = '1000')
                      AND r.to_id   NOT IN (SELECT entity_id FROM businesses
                                             WHERE legal_form_code = '1000')
                """, [
                    *sorted(RULES["confidence"]["public"]),
                    *sorted(RULES["confidence"]["public"]),
                    *eco_types,
                    *sorted(beneficiaires), *sorted(beneficiaires),
                ])
            }

        public_person_ids = civic_person_ids | pertinent_person_ids
        redige, redactions = compilateur_redaction(conn, public_person_ids)
        counters["persons_civic"] = len(civic_person_ids)
        counters["persons_par_pertinence"] = len(pertinent_person_ids - civic_person_ids)
        counters["beneficiaires_argent_public"] = len(beneficiaires)

        # Ceux qui siègent au conseil communautaire : seules personnes des
        # communes C2 publiables en fiche (cf. `publiable_dans_perimetre`).
        ids_conseil_communautaire = {
            r["entity_id"] for r in rows(conn, """
                SELECT DISTINCT from_id AS entity_id FROM relations
                WHERE relation_type IN ('élu_cc','vice_président_cc','président_cc')
                  AND confidence IN ('verified','confirmed')
            """)
        }

        public_entities: list[dict] = []
        entity_exclusions: list[dict] = []
        location_quality = Counter()
        for entity in entity_rows:
            item, reasons = public_entity(
                entity,
                confirmed_urls.get(entity["id"], []),
                public_person_ids,
                ids_conseil_communautaire,
            )
            if item is None:
                for reason in reasons:
                    exclusions["entities"][reason] += 1
                entity_exclusions.append({
                    "id": entity["id"],
                    "type": entity["type"],
                    "name": entity["name"],
                    "confidence": entity["confidence"],
                    "reasons": reasons,
                })
                continue
            public_entities.append(item)
            location_quality[item["location_quality"]] += 1

        public_ids = {e["id"] for e in public_entities}

        relation_rows = rows(conn, """
            SELECT r.id, r.from_id, r.to_id, r.relation_type, r.since, r.until,
                   r.source, r.confidence, r.metadata,
                   f.name AS from_name, t.name AS to_name
            FROM relations r
            LEFT JOIN entities f ON f.id = r.from_id
            LEFT JOIN entities t ON t.id = r.to_id
            ORDER BY r.id
        """)
        public_relations: list[dict] = []
        relation_exclusions: list[dict] = []
        for rel in relation_rows:
            ok, reason = is_public_relation(rel, public_ids,
                                            civic_person_ids, beneficiaires,
                                            ei_ids)
            if not ok:
                exclusions["relations"][reason] += 1
                relation_exclusions.append({
                    "id": rel["id"],
                    "from_id": rel["from_id"],
                    "to_id": rel["to_id"],
                    "relation_type": rel["relation_type"],
                    "confidence": rel["confidence"],
                    "source": rel["source"],
                    "reason": reason,
                })
                continue
            public_relations.append({
                "id": rel["id"],
                "from_id": rel["from_id"],
                "to_id": rel["to_id"],
                "relation_type": rel["relation_type"],
                "since": rel["since"],
                "until": rel["until"],
                "source": rel["source"],
                "confidence": rel["confidence"],
                "from_name": rel["from_name"],
                "to_name": rel["to_name"],
                # `relations.metadata` sert de fourre-tout aux collecteurs : on
                # y trouve aussi bien un rôle en commission qu'une année de
                # naissance. Liste blanche stricte, jamais le bloc entier.
                **relation_meta_publique(rel.get("metadata")),
            })

        event_rows = rows(conn, """
            SELECT id, type, date, title, source, source_url, metadata
            FROM events
            ORDER BY date DESC, id DESC
        """)
        public_events: list[dict] = []
        event_exclusions: list[dict] = []
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

            public_events.append({
                "id": event["id"],
                "type": event_type,
                "date": event["date"],
                "date_end": metadata.get("date_end"),
                "title": redige(nettoyer_titre_evenement(event["title"])),
                "source": source,
                "source_url": safe_url(event["source_url"]),
                "page_url": safe_url(metadata.get("page_url")),
                "pdf_url": safe_url(metadata.get("pdf_url")) or (
                    safe_url(event["source_url"])
                    if ".pdf" in (event["source_url"] or "").lower() else None
                ),
                # Le détail délibératif était produit par les parsers puis jeté à
                # l'export : 493 délibérations sur 508 portent le décompte du vote
                # et 471 un montant, et la page publique n'affichait qu'une ligne
                # date + titre. C'est la matière même du contrôle citoyen.
                **public_event_detail(metadata, event_type),
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
        counters["event_links_public"] = len(public_links)

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

        # Déduplication : doublons exacts (même année/montant/type/émetteur/destinataire)
        # et « jumeaux » non résolus (montant identique, bénéficiaire vide) laissés par
        # les collecteurs. On garde les bénéficiaires DISTINCTS de même montant.
        before = len(public_flows)
        _seen, _deduped = set(), []
        for f in public_flows:
            key = (f.get("year"), f.get("amount"), f.get("type"), f.get("from_id"), f.get("to_id"))
            if key in _seen:
                continue
            _seen.add(key)
            _deduped.append(f)
        def _unknown_benef(f) -> bool:
            return (str(f.get("to_name") or "").strip() in ("", "?", "∅")) or not f.get("to_id")
        _twin_key = lambda f: (f.get("year"), f.get("amount"), f.get("type"), f.get("from_id"))
        _named = {_twin_key(f) for f in _deduped if not _unknown_benef(f)}
        public_flows = [
            f for f in _deduped
            if not _unknown_benef(f) or _twin_key(f) not in _named
        ]
        exclusions["flows"]["duplicates"] = before - len(public_flows)

        # `sens` : la DGF encaissée par la commune (489 690 €) et la subvention
        # versée au Comité des fêtes (4 400 €) sortaient avec la même mise en
        # forme. Sans le sens du flux, la page se lit à contresens.
        for f in public_flows:
            f["description"] = redige(f.get("description"))
            if f.get("to_id") == COMMUNE_ID and f.get("from_id") != COMMUNE_ID:
                f["sens"] = "entrant"
            elif f.get("from_id") == COMMUNE_ID:
                f["sens"] = "sortant"
            else:
                f["sens"] = "tiers"
        counters["flows_par_sens"] = dict(Counter(f["sens"] for f in public_flows))
        counters["flows_par_statut"] = dict(Counter(f["statut"] for f in public_flows))

        public_layers = {
            "businesses": [],
            "associations": [],
            "places": [],
            "services": [],
        }
        for entity in public_entities:
            if not entity.get("has_public_location"):
                continue
            layer_key = {
                "business": "businesses",
                "association": "associations",
                "place": "places",
                "service": "services",
            }.get(entity["type"])
            if not layer_key:
                continue
            public_layers[layer_key].append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [entity["lng"], entity["lat"]]},
                "properties": {k: v for k, v in entity.items() if k not in {"lat", "lng"}},
            })

        # ── Données financières & foncières officielles (open data) ───────────
        # DGFiP, OFGL, Cerema (DVF), DECP : faits publics par nature → export complet.
        budget_annuel = rows(conn, """
            SELECT year, categorie, compte, libelle, montant, source
            FROM budget_annuel ORDER BY year DESC, categorie, montant DESC
        """)
        budget_annexe = rows(conn, """
            SELECT ba.year, ba.section, ba.sens, ba.libelle, ba.montant, ba.source,
                   ba.entity_id, e.name AS entity_name
            FROM budget_annexe ba LEFT JOIN entities e ON e.id = ba.entity_id
            ORDER BY ba.year DESC, ba.section
        """)
        ofgl_data = rows(conn, """
            SELECT year, agregat, montant, euros_par_habitant, population
            FROM ofgl_agregats ORDER BY year DESC, agregat
        """)
        # Budgets primitifs VOTÉS (prévisionnel) extraits des CR — comble le trou
        # après OFGL (>2024). Fait public (délibération) → export complet.
        budget_vote = rows(conn, """
            SELECT year, scope, agregat, value, unit, approx, note, source, source_url
            FROM budget_vote ORDER BY year DESC, scope, id
        """) if table_exists(conn, "budget_vote") else []
        dvf_data = rows(conn, """
            SELECT id, date, cadastre_ref, lieu_dit, nature_mutation, nature_bien,
                   surface_terrain, surface_bati, price, price_per_m2, lat, lng
            FROM dvf_transactions ORDER BY date DESC
        """)
        marches_data = rows(conn, """
            SELECT id, acheteur_id, acheteur_nom, titulaire_id, titulaire_nom, objet, nature,
                   procedure, montant, cpv_label, date_notif, lieu_exec, source, source_url
            FROM marches_publics ORDER BY date_notif DESC, montant DESC
        """)
        revue_marches = revue.get("marche", {})
        avant_revue = len(marches_data)
        marches_data = [m for m in (appliquer_revue(m, revue_marches.get(m["id"]))
                                    for m in marches_data) if m is not None]
        exclusions["marches"]["rejete_en_atelier"] = avant_revue - len(marches_data)

        # Plans de financement votés (participations aux opérations du syndicat
        # d'électrification). Exportés à part des marchés : aucune entreprise
        # n'est retenue, les mêler fausserait le décompte des attributions.
        approbations_data = rows(conn, """
            SELECT id, event_id, date, objet, montant_ht, montant_ttc,
                   maitre_ouvrage, citation, source, source_url
            FROM approbations_projets
            WHERE confidence IN ('verified', 'confirmed')
            ORDER BY date DESC
        """) if table_exists(conn, "approbations_projets") else []

        # ── Environnement : qualité de l'eau, risques, installations classées ──
        # 27 652 analyses, 75 risques recensés et 3 ICPE dormaient en base sans
        # aucune page publique. Les analyses sont agrégées par station, paramètre
        # et année : publier 27 000 mesures brutes n'informerait personne.
        eau_stations = rows(conn, """
            SELECT code_station, libelle, code_commune, cours_eau, latitude, longitude
            FROM eau_stations ORDER BY libelle
        """) if table_exists(conn, "eau_stations") else []
        # Le suivi porte sur un millier de paramètres (micropolluants, pesticides…).
        # Publier les 10 756 séries n'aiderait personne : on détaille les
        # indicateurs qu'un lecteur non spécialiste peut interpréter, et on
        # résume le reste par un décompte des recherches et des détections.
        PARAM_CLES = [
            "Nitrates", "Nitrites", "Ammonium", "Phosphore total",
            "Oxygène dissous", "Température de l'Eau", "Conductivité à 25°C",
            "Matières en suspension", "Carbone Organique",
            "Demande Biochimique en oxygène en 5 jours (D.B.O.5)",
            "Escherichia coli (E. coli)", "Enterocoques",
            "Plomb", "Nickel", "Arsenic", "Cadmium", "Mercure", "Zinc", "Cuivre",
        ]
        ph = ",".join("?" for _ in PARAM_CLES)
        eau_series = rows(conn, f"""
            SELECT s.code_station, s.libelle AS station,
                   a.libelle_parametre AS parametre, a.symbole_unite AS unite,
                   substr(a.date_prelevement, 1, 4) AS annee,
                   COUNT(*) AS n,
                   ROUND(AVG(a.resultat), 3) AS moyenne,
                   ROUND(MIN(a.resultat), 3) AS mini,
                   ROUND(MAX(a.resultat), 3) AS maxi,
                   MAX(a.date_prelevement) AS dernier_prelevement
              FROM eau_analyses a JOIN eau_stations s ON s.code_station = a.code_station
             WHERE a.resultat IS NOT NULL AND a.libelle_parametre IN ({ph})
             GROUP BY s.code_station, a.libelle_parametre, annee
             ORDER BY annee DESC, s.libelle, a.libelle_parametre
        """, PARAM_CLES) if table_exists(conn, "eau_analyses") else []
        eau_couverture = rows(conn, """
            SELECT substr(date_prelevement, 1, 4) AS annee,
                   COUNT(*) AS analyses,
                   COUNT(DISTINCT libelle_parametre) AS parametres_recherches,
                   COUNT(DISTINCT CASE WHEN resultat > 0 THEN libelle_parametre END) AS parametres_detectes
              FROM eau_analyses
             GROUP BY annee ORDER BY annee DESC
        """) if table_exists(conn, "eau_analyses") else []
        eau_qualif = rows(conn, """
            SELECT substr(date_prelevement, 1, 4) AS annee,
                   libelle_qualification AS qualification, COUNT(*) AS n
              FROM eau_analyses
             WHERE libelle_qualification IS NOT NULL AND libelle_qualification <> ''
             GROUP BY annee, qualification ORDER BY annee DESC
        """) if table_exists(conn, "eau_analyses") else []
        risques = rows(conn, """
            SELECT insee, commune, num_risque, libelle FROM risques_gaspar
            ORDER BY commune, libelle
        """) if table_exists(conn, "risques_gaspar") else []
        icpe = rows(conn, """
            SELECT code_aiot, raison_sociale, commune, adresse, regime, seveso,
                   etat_activite, lat, lng
            FROM icpe_installations ORDER BY commune, raison_sociale
        """) if table_exists(conn, "icpe_installations") else []
        catnat = rows(conn, """
            SELECT date, title, source_url FROM events
             WHERE type = 'arrete_catnat' ORDER BY date DESC
        """)

        # ── Portrait de territoire (INSEE) ────────────────────────────────────
        insee_data = rows(conn, """
            SELECT insee, commune, dataset, indicateur, libelle, annee, valeur, dims
            FROM insee_indicateurs ORDER BY dataset, indicateur, annee
        """) if table_exists(conn, "insee_indicateurs") else []

        stats = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
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
            "entities_sans_perimetre": counters["entities_sans_perimetre"],
            "conseil_communautaire": len(ids_conseil_communautaire),
            "relations_total_private": len(relation_rows),
            "relations_public": len(public_relations),
            "events_total_private": len(event_rows),
            "events_public": len(public_events),
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

        # ── Citations : l'acteur est-il nommé dans un acte public ? ───────────
        # « Cité » = nommé dans une décision publique : délibération, conseil,
        # marché, autorisation d'urbanisme, flux financier, mandat. Les ~1 800
        # entreprises importées de SIRENE n'y figurent pas et noyaient la page
        # publique (2 700 cartes à parcourir à l'œil). Tout le répertoire reste
        # publié, mais le compteur permet de mettre en avant ce qui est documenté.
        #
        # Les annonces BODACC (dépôts de comptes, immatriculations…) sont
        # exclues : purement déclaratives, elles font remonter n'importe quelle
        # société ayant déposé ses comptes devant les associations subventionnées.
        events_by_id_all = {e["id"]: e for e in public_events}
        citations = Counter()
        for lien in public_links:
            ev = events_by_id_all.get(lien["event_id"])
            if not ev or str(ev.get("type", "")).startswith("bodacc"):
                continue
            citations[lien["entity_id"]] += 1
        for source, paires in (
            (public_relations, ("from_id", "to_id")),
            (public_flows, ("from_id", "to_id")),
            (marches_data, ("acheteur_id", "titulaire_id")),
        ):
            for row in source:
                for eid in {row.get(k) for k in paires} - {None}:
                    citations[eid] += 1
        for e in public_entities:
            e["citations"] = citations.get(e["id"], 0)
        stats["entities_cited"] = sum(1 for e in public_entities if e["citations"])

        out.mkdir(parents=True, exist_ok=True)
        write_json(out / "stats.json", stats)
        write_json(out / "couverture.json", export_couverture(conn, public_events, stats))
        write_json(out / "entities.json", {"entities": public_entities, "total": len(public_entities)})
        write_json(out / "relations.json", {"relations": public_relations, "total": len(public_relations)})
        write_json(out / "events.json", {"events": public_events, "total": len(public_events)})
        write_json(out / "event_links.json",
                   {"links": public_links, "total": len(public_links)})
        write_json(out / "flows.json", {"flows": public_flows, "total": len(public_flows)})
        for layer, features in public_layers.items():
            write_json(out / "layers" / f"{layer}.geojson", {
                "type": "FeatureCollection",
                "features": features,
            })
        write_json(out / "budget.json", {"annuel": budget_annuel, "annexe": budget_annexe})
        write_json(out / "budget_vote.json", {"budget_vote": budget_vote, "total": len(budget_vote)})
        write_json(out / "ofgl.json", {"ofgl": ofgl_data, "total": len(ofgl_data)})
        write_json(out / "dvf.json", {"dvf": dvf_data, "total": len(dvf_data)})
        write_json(out / "marches.json", {"marches": marches_data, "total": len(marches_data)})
        write_json(out / "approbations.json",
                   {"approbations": approbations_data, "total": len(approbations_data)})
        write_json(out / "environnement.json", {
            "eau_stations": eau_stations,
            "eau_series": eau_series,
            "eau_couverture": eau_couverture,
            "eau_qualification": eau_qualif,
            "risques": risques,
            "icpe": icpe,
            "catnat": catnat,
        })
        write_json(out / "territoire.json", {"insee": insee_data, "total": len(insee_data)})

        # ── Export Popolo — l'interopérabilité, pas un doublon ────────────────
        # Popolo (popoloproject.com) est le vocabulaire commun des projets de
        # transparence parlementaire et municipale : Open Civic Data (le
        # standard derrière Councilmatic à Chicago, NYC et Philadelphie),
        # EveryPolitician, mySociety. Il décrit exactement ce que cette base
        # contient déjà — des personnes, des organisations, et des mandats
        # datés qui relient les deux.
        #
        # Pourquoi l'exporter en plus de `entities.json` : nos noms de champs
        # (`from_id`, `relation_type`, `since`) ne veulent rien dire hors du
        # projet. Un chercheur ou une autre commune qui veut comparer doit
        # d'abord lire notre code. En Popolo, `memberships[].person_id` et
        # `start_date` se lisent sans documentation, et les outils existants
        # consomment le fichier tel quel. C'est la contrepartie de l'objectif
        # de réplication : un modèle qui s'exporte doit sortir dans un format
        # que d'autres parlent déjà.
        #
        # Ce qui n'y est PAS : les votes nominatifs (`VoteEvent`/`Vote`). Les
        # procès-verbaux publiés ne donnent pas le détail des votes par élu, et
        # inventer un `Vote` à partir d'un « adopté à l'unanimité » serait une
        # affirmation que la source ne porte pas. Le jour où les PV nominatifs
        # existeront, la classe s'ajoute sans toucher au reste.
        write_json(out / "popolo.json", build_popolo(
            public_entities, public_relations, RULES))

        # ── Lot 2 : élections, fiscalité, élus officiels, urbanisme ───────────
        # Publication arbitrée le 26/07/2026. Aucune de ces sources ne portait de
        # page publique alors qu'elles répondent à des questions de premier plan
        # (« combien ont voté ? », « de combien sont mes impôts ? »).
        elections = {}
        if table_exists(conn, "elections_resultats"):
            elections["resultats"] = rows(conn, """
                SELECT scrutin, tour, date_tour, insee, commune, inscrits, votants,
                       abstentions, exprimes, blancs, nuls,
                       ROUND(100.0*votants/NULLIF(inscrits,0), 2) AS participation_pct
                FROM elections_resultats ORDER BY scrutin, tour, commune
            """)
            elections["listes"] = rows(conn, """
                SELECT scrutin, tour, insee, rang, libelle, libelle_abrege, nuance,
                       tete_de_liste, voix, pct_exprimes, sieges_cm, sieges_cc
                FROM elections_listes ORDER BY scrutin, tour, insee, voix DESC
            """)
        write_json(out / "elections.json", elections)

        # `portee` distingue la part votée par la commune du total acquitté :
        # attribuer le taux global au conseil municipal serait faux.
        fiscalite = rows(conn, """
            SELECT insee, commune, annee, indicateur, libelle, portee, taux, epci
            FROM fiscalite_taux ORDER BY annee DESC, commune, indicateur
        """) if table_exists(conn, "fiscalite_taux") else []
        write_json(out / "fiscalite.json", {"taux": fiscalite, "total": len(fiscalite)})

        # ── L'intercommunalité (périmètre C2) ────────────────────────────────
        # Réponse publique à « qu'est-ce qui ne se décide plus à la mairie ? ».
        # Trois briques : ce que l'EPCI exerce à la place de la commune, qui
        # siège pour en décider, et où Lasalle se situe parmi ses pairs.
        # Les entités des 14 autres communes ne sont pas publiées en fiche
        # (cf. `publiable_dans_perimetre`) : elles n'existent ici qu'agrégées.
        competences = rows(conn, """
            SELECT code, libelle, categorie, obligatoire, interet_communautaire
            FROM epci_competences
            ORDER BY obligatoire DESC, categorie, libelle
        """) if table_exists(conn, "epci_competences") else []

        # Un même délégué porte plusieurs relations `élu_cc` — une par source
        # (banatic, rne, cc_cac_site, élections_2026). Deux filtres, et l'ordre
        # entre les deux compte :
        #
        # 1. `until` — les mandats de source BANATIC (état du 15/10/2025) et du
        #    site de la CC (mandat 2020-2026) sont clos au 15/03/2026 par
        #    `scripts/fix_conseil_communautaire_2026.py`. Sans ce filtre, la page
        #    annonçait Gilles BEAUMANOIR président et Irène CHAPUIS
        #    vice-présidente : trois des quatre premiers noms de la liste
        #    n'étaient plus délégués depuis les municipales de mars 2026.
        # 2. déduplication par personne, en préférant la source la plus récente
        #    (RNE, publication du 11/08/2026) — sinon `nb_relations` double.
        delegues_bruts = rows(conn, """
            SELECT e.id, e.name, e.commune, r.relation_type, r.source, r.metadata
            FROM relations r
            JOIN entities e ON e.id = r.from_id
            WHERE r.relation_type IN ('élu_cc','vice_président_cc','président_cc')
              AND r.confidence IN ('verified','confirmed')
              AND e.confidence IN ('verified','confirmed')
              AND (r.until IS NULL OR r.until > date('now'))
            ORDER BY CASE r.source WHEN 'rne' THEN 0
                                   WHEN 'élections_2026' THEN 1 ELSE 2 END,
                     CASE r.relation_type
                       WHEN 'président_cc' THEN 0
                       WHEN 'vice_président_cc' THEN 1 ELSE 2 END
        """)
        # Commune d'élection du délégué, prise dans le fichier RNE des
        # conseillers MUNICIPAUX — pas dans le fichier EPCI, qui rattache 22 des
        # 27 délégués à Val-d'Aigoual, commune du siège de l'intercommunalité.
        # `entities.commune` ne suffit pas : elle est vide pour les 8 délégués
        # créés par le seul import EPCI (BALSAN, BOSIO, EL RHAZOUI, FOUGERAY,
        # LIRON, PIALOT, ROMAZZOTTI, SERRAL), qui apparaissaient donc sans
        # commune. Recoupé avec BANATIC, ce rattachement rend exactement la
        # répartition des sièges par commune.
        commune_election = {
            r["entity_id"]: r["commune"] for r in rows(conn, """
                SELECT entity_id, commune FROM elus_rne
                WHERE mandat = 'cm' AND entity_id IS NOT NULL AND commune IS NOT NULL
            """)
        } if table_exists(conn, "elus_rne") else {}

        par_personne: dict[int, dict] = {}
        for d in delegues_bruts:
            if d["id"] in par_personne:
                continue
            fonction = relation_meta_publique(d.get("metadata")).get("fonction_rne") \
                or {"président_cc": "Président",
                    "vice_président_cc": "Vice-président"}.get(d["relation_type"],
                                                               "Délégué")
            commune = commune_election.get(d["id"]) or d["commune"]
            par_personne[d["id"]] = {
                "name": d["name"],
                "commune": commune,
                # Vrai quand la commune vient du RNE des conseillers municipaux,
                # qui donne la commune d'élection. Faux quand elle n'est que le
                # rattachement de l'entité, non recoupé : l'UI ne doit pas
                # l'afficher comme un fait établi.
                "commune_fiable": d["id"] in commune_election,
                "relation_type": d["relation_type"],
                "fonction": fonction,
                "source": d["source"],
            }
        ordre = {"président_cc": 0, "vice_président_cc": 1}
        delegues = sorted(par_personne.values(),
                          key=lambda d: (ordre.get(d["relation_type"], 2),
                                         d["commune"] or "", d["name"]))

        # Comparaison de Lasalle à ses pairs. Le nombre de sièges au conseil
        # communautaire face au poids démographique est l'information la plus
        # parlante : c'est le pouvoir de vote réel de chaque commune.
        #
        # Il est compté sur la SEULE source BANATIC, et sur les relations CLOSES
        # aussi bien qu'actives — d'où une requête distincte de celle des
        # délégués. La répartition des sièges est fixée par arrêté préfectoral :
        # elle survit au scrutin, seuls les NOMS changent. Le RNE, lui, est
        # inexploitable pour ce décompte : il range 22 délégués sur 27 sous
        # Val-d'Aigoual, commune du siège de l'EPCI, et laisserait 13 communes
        # membres à zéro siège. Cf. memory-bank/known-issues.md.
        sieges = Counter(
            r["commune"] for r in rows(conn, """
                SELECT DISTINCT e.id, e.commune
                FROM relations r
                JOIN entities e ON e.id = r.from_id
                WHERE r.relation_type IN ('élu_cc','vice_président_cc','président_cc')
                  AND r.source = 'banatic'
                  AND e.confidence IN ('verified','confirmed')
            """) if r["commune"])
        delegues_hors_banatic = 0
        membres = []
        for insee, meta in COMMUNES_EPCI.items():
            nom = meta["nom"]
            membres.append({
                "insee": insee,
                "nom": nom,
                "population": meta.get("population"),
                "sieges": sieges.get(nom, 0),
                "est_commune_du_site": insee == INSEE_C1,
            })
        membres.sort(key=lambda m: -(m["population"] or 0))

        syndicats = rows(conn, """
            SELECT t.name, t.id
            FROM relations r
            JOIN entities t ON t.id = r.to_id
            WHERE r.relation_type = 'adhère_à' AND r.source = 'banatic'
              AND t.confidence IN ('verified','confirmed')
            ORDER BY t.name
        """)

        write_json(out / "intercommunalite.json", {
            "nom": EPCI_NOM_C2,
            "siren": EPCI_SIREN_C2,
            "population": sum((m["population"] or 0) for m in membres),
            "competences": competences,
            "competences_obligatoires": sum(1 for c in competences if c["obligatoire"]),
            "delegues": delegues,
            "membres": membres,
            "syndicats": syndicats,
            # Honnêteté de la source, à afficher tel quel par l'UI : les noms et
            # la répartition des sièges ne viennent pas du même endroit.
            "sieges_source": "BANATIC (répartition arrêtée le 15/10/2025)",
            "delegues_source": "Répertoire National des Élus (publication du 11/08/2026)",
            "delegues_a_confirmer": delegues_hors_banatic,
            "note_sources": (
                "Les délégués sont ceux du Répertoire National des Élus, "
                "postérieur aux élections municipales de mars 2026. La "
                "répartition des sièges par commune vient de BANATIC : elle est "
                "fixée par arrêté préfectoral et ne change pas avec le scrutin. "
                "La commune de chaque délégué est celle de son mandat municipal "
                "au RNE : le fichier RNE des conseillers communautaires, lui, "
                "rattache 22 des 27 délégués au siège de l'intercommunalité et "
                "non à leur commune d'élection."
            ),
        })

        # Élus : source autoritaire DGCL. `birth_year` et la CSP restent privés
        # (`publication_rules.people.publish_birth_year = false`).
        #
        # Filtrage sur les 15 communes de l'EPCI. `elus_rne` en contient
        # davantage : la collecte du 26/07/2026 portait sur l'ancien périmètre —
        # les 7 communes du vallon de la Salindrenque — et le recadrage du
        # 11/08 a délibérément conservé ces lignes en base (elles servent à
        # détecter les mandats croisés, cf. activeContext). Publiées telles
        # quelles, elles faisaient apparaître 20 conseils municipaux dont ceux
        # de Colognac, Vabres, Thoiras-Corbès, Sainte-Croix-de-Caderle et
        # Saint-Bonnet-de-Salendrinque, qui relèvent d'autres EPCI. Le filtre va
        # ici, pas dans une purge : la donnée reste exploitable en interne.
        elus = rows(conn, f"""
            SELECT mandat, insee, commune, nom, prenom, fonction,
                   date_debut_mandat, date_debut_fonction, epci_nom, entity_id
            FROM elus_rne
            WHERE insee IN ({",".join("?" * len(COMMUNES_EPCI))})
            ORDER BY commune, mandat, nom
        """, tuple(COMMUNES_EPCI)) if table_exists(conn, "elus_rne") else []
        write_json(out / "elus_rne.json", {"elus": elus, "total": len(elus)})

        urbanisme_rows = rows(conn, """
            SELECT num_dau, insee, commune, categorie, type_dau, type_label,
                   date_depot, date_autorisation, date_achevement,
                   demandeur_nom, demandeur_siren, demandeur_entity_id,
                   adresse, lieu_dit, cadastre_ref, superficie_terrain,
                   nb_logements, surface_hab_creee, surface_loc_creee, residence
            FROM urbanisme_autorisations ORDER BY date_depot DESC, commune
        """) if table_exists(conn, "urbanisme_autorisations") else []
        urbanisme_public = []
        adresses_retirees = 0
        for u in urbanisme_rows:
            u = dict(u)
            # Prudence : sans personne morale nommée, le demandeur est un
            # particulier. On garde le lieu-dit et la parcelle (le croisement DVF
            # et la lecture territoriale sont préservés) mais pas la voie exacte.
            if not u.get("demandeur_nom"):
                if u.get("adresse"):
                    adresses_retirees += 1
                u["adresse"] = None
            u["date_precision"] = "annee"   # cf. contrôle de divulgation SDES
            urbanisme_public.append(u)
        write_json(out / "urbanisme.json", {
            "autorisations": urbanisme_public,
            "total": len(urbanisme_public),
            "note_dates": "Dates ramenées à l'année pour les petites communes "
                          "(contrôle de divulgation statistique du SDES).",
        })

        # Parcelles portant à la fois une mutation DVF et une autorisation.
        croisement_foncier = rows(conn, """
            SELECT u.cadastre_ref, u.commune, u.num_dau, u.date_depot,
                   u.demandeur_nom, u.nb_logements, COUNT(d.id) AS mutations,
                   MIN(d.date) AS premiere_mutation, MAX(d.date) AS derniere_mutation
            FROM urbanisme_autorisations u
            JOIN dvf_transactions d ON d.cadastre_ref = u.cadastre_ref
            WHERE u.cadastre_ref IS NOT NULL
            GROUP BY u.id ORDER BY u.date_depot DESC
        """) if (table_exists(conn, "urbanisme_autorisations")
                 and table_exists(conn, "dvf_transactions")) else []
        write_json(out / "croisement_foncier.json", {
            "parcelles": croisement_foncier, "total": len(croisement_foncier)})

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
            })

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
                "corrige": e.get("corrige"), "note_revue": e.get("note_revue"),
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
        # `stats["exclusions"]` est figé plus haut, avant que le flux d'actualité
        # n'ait écarté ses doublons : on le réactualise, sinon le rapport de
        # revue tait précisément ce qui vient d'être filtré.
        stats["exclusions"] = {s: dict(c) for s, c in exclusions.items()}
        stats["revue_atelier"] = {
            "annotations": counters["revue_annotations"],
            "rejetes": sum(c.get("rejete_en_atelier", 0) for c in exclusions.values()),
            "corriges": sum(1 for e in public_events if e.get("corrige"))
                      + sum(1 for f in public_flows if f.get("corrige"))
                      + sum(1 for m in marches_data if m.get("corrige")),
        }
        stats["actualite_items"] = min(len(actualite), 400)
        stats["actualite_a_venir"] = len(a_venir)
        stats["actualite_par_genre"] = dict(Counter(i["genre"] for i in actualite))
        stats["redactions_personnes"] = redactions.get("remplacements", 0)

        conflits = export_conflits(conn, public_ids)
        write_json(out / "conflits.json", conflits)
        stats["conflits_cas"] = conflits["total"]
        stats["conflits_par_statut"] = dict(
            Counter(c["statut"] for c in conflits["cas"]))

        stats["elections_communes"] = len(elections.get("resultats", []))
        stats["fiscalite_taux"] = len(fiscalite)
        stats["elus_rne"] = len(elus)
        stats["urbanisme_autorisations"] = len(urbanisme_public)
        stats["urbanisme_adresses_retirees"] = adresses_retirees
        stats["croisement_foncier"] = len(croisement_foncier)

        # ── Un fichier par acteur + index de recherche ────────────────────────
        bundles = write_entity_bundles(out, public_entities, public_relations,
                                       public_events, public_links, public_flows,
                                       marches_data)
        communes = {r["id"]: r.get("commune") for r in entity_rows}
        liens_count = Counter(l["entity_id"] for l in public_links)
        indexed = write_search_index(out, public_entities, communes, liens_count)
        recherche = write_recherche_index(out, public_entities, public_events,
                                          marches_data, public_flows,
                                          communes, liens_count)
        stats["entity_bundles"] = bundles
        stats["search_index_entries"] = indexed
        stats["recherche_index_entries"] = recherche
        write_json(out / "stats.json", stats)   # réécrit avec les 2 compteurs

        # Rapport QA interne — JAMAIS dans le bundle public (contient les
        # exclusions nominatives = exactement les données filtrées). Écrit hors `out`.
        review_out = ROOT / "audits"
        review_out.mkdir(parents=True, exist_ok=True)
        write_json(review_out / "public_snapshot_review.json", {
            "stats": {**stats, "source_db": str(DB_PATH)},
            "entity_exclusions_sample": entity_exclusions[:250],
            "relation_exclusions_sample": relation_exclusions[:250],
            "event_exclusions_sample": event_exclusions[:250],
            "rules": {
                "public_confidence": sorted(RULES["confidence"]["public"]),
                "public_person_relation_types": sorted(RULES["people"]["publish_only_with_relation_types"]),
                "public_relation_types": sorted(RULES["relations"]["public_allowlist"]),
                "relevance_relation_types": sorted(
                    RULES["relations"].get("relevance_allowlist", [])),
                "public_money_relation_types": sorted(
                    RULES["relations"].get("public_money_relation_types", [])),
                "public_event_sources": sorted(RULES["events"]["public_sources"]),
                "generic_url_domains_excluded": sorted(RULES["urls"]["exclude_generic_domains"]),
                "location_policy": {
                    "person": "coordinates always hidden",
                    "outside_bbox": "coordinates hidden",
                    "center_fallback": "hidden except places/services",
                },
            },
        })

        # ── Dictionnaire de données ──────────────────────────────────────────
        # Servi À CÔTÉ des JSON, et régénéré à chaque exécution : un README
        # écrit à la main se périme en silence — celui d'avant le 12/08/2026
        # annonçait encore 2 876 entités publiques pour 1 807 réelles, et ne
        # disait rien du contenu des fichiers. Un jeu de données sans
        # dictionnaire n'est pas réutilisable, quelle que soit sa qualité.
        markdown = [
            f"# Données publiques — {RULES['project']['public_name']}",
            "",
            f"Généré le {stats['generated_at']} depuis la base de travail, "
            "sans la modifier.",
            "",
            "Ces fichiers sont le snapshot public : ce que le site sert, et rien "
            "d'autre. Ils sont produits par `scripts/build_public_snapshot.py` "
            "et contrôlés par `scripts/verify_snapshot.py`, qui refuse de "
            "publier tout type de relation absent de l'allowlist.",
            "",
            "## Licence",
            "",
            f"Ce jeu de données est publié sous **{RULES['outputs']['license']}** "
            f"([Open Database License]({RULES['outputs']['license_url']})).",
            "",
            "Vous pouvez le copier, le modifier et l'utiliser, y compris "
            "commercialement, à trois conditions : **citer** la source, "
            "**partager à l'identique** toute base dérivée que vous "
            "redistribuez, et ne pas la diffuser sous verrou technique sans "
            "en fournir aussi une version libre.",
            "",
            "Ce choix découle des sources : 333 des entités publiées sont des "
            "points d'intérêt OpenStreetMap et une large part des coordonnées "
            "vient d'un géocodage OSM. La contribution est substantielle et "
            "fondue dans le jeu — c'est donc une base dérivée au sens de "
            "l'ODbL, et le partage à l'identique s'applique.",
            "",
            "### Attribution",
            "",
            f"> {RULES['outputs']['attribution']}",
            "",
        ]
        markdown += [f"- {a}" for a in RULES["outputs"]["source_attributions"]]
        markdown += [
            "",
            "Le **site** et ses visualisations sont un « Produced Work » au "
            "sens de l'ODbL : les reprendre demande l'attribution, pas le "
            "partage à l'identique. Le **code** relève d'une licence distincte "
            "(MIT) — l'ODbL ne porte pas sur le logiciel.",
            "",
            "**La licence ne dit rien du RGPD.** Ces données restent soumises "
            "au droit des données personnelles : une réutilisation doit avoir "
            "sa propre base légale.",
            "",
            "## Réplication",
            "",
            "Ce modèle est conçu pour être rejoué sur une autre commune. Le "
            "périmètre se pilote dans `collectors/config.py` et nulle part "
            "ailleurs : commune, intercommunalité, communes membres. Les "
            "collecteurs, le schéma et le site n'ont pas à être touchés.",
            "",
            "## Fichiers",
            "",
            "| Fichier | Contenu | Clé racine |",
            "|---|---|---|",
            "| `entities.json` | Acteurs publiés : personnes, entreprises, "
            "associations, services, lieux | `entities` |",
            "| `relations.json` | Liens entre acteurs, datés et sourcés | "
            "`relations` |",
            "| `popolo.json` | Les **mandats** au format [Popolo]"
            "(https://www.popoloproject.com/) — format d'interopérabilité | "
            "`persons`, `organizations`, `memberships`, `areas` |",
            "| `events.json` | Actes : délibérations, arrêtés, annonces | "
            "`events` |",
            "| `event_links.json` | Quel acteur est cité dans quel acte | "
            "`links` |",
            "| `flows.json` | Flux financiers publics (subventions, "
            "participations) | `flows` |",
            "| `marches.json` | Marchés publics et attributaires | `marches` |",
            "| `budget.json` · `budget_vote.json` · `ofgl.json` | Budgets "
            "votés et agrégats financiers | `annuel`/`annexe`, `budget_vote`, "
            "`ofgl` |",
            "| `intercommunalite.json` | Compétences, délégués, sièges de "
            "l'EPCI | racine |",
            "| `elus_rne.json` | Conseils municipaux (Répertoire National des "
            "Élus) | `elus` |",
            "| `elections.json` | Résultats des municipales par commune | "
            "`resultats` |",
            "| `fiscalite.json` · `impots` | Taux d'imposition comparés | "
            "`taux` |",
            "| `dvf.json` | Transactions immobilières (DVF) | `dvf` |",
            "| `urbanisme.json` | Autorisations d'urbanisme | `autorisations` |",
            "| `environnement.json` | Eau, risques, ICPE, catastrophes "
            "naturelles | racine |",
            "| `territoire.json` | Indicateurs INSEE | `insee` |",
            "| `conflits.json` | Cas de conflits d'intérêts potentiels | "
            "`cas` |",
            "| `stats.json` | Compteurs et paramètres de publication | racine |",
            "| `layers/*.geojson` | Couches cartographiques | FeatureCollection |",
            "| `entite/<id>.json` | Fiche complète d'un acteur | racine |",
            "",
            "Chaque fichier à liste porte aussi un `total`.",
            "",
            "## Ce qui n'est jamais publié",
            "",
            "- les affirmations de niveau `probable` ou `hypothesis` — seuls "
            f"`{'`, `'.join(sorted(RULES['confidence']['public']))}` sortent ;",
            "- les liens de famille, de domicile partagé et les doublons "
            f"présumés (marqueurs : `{'`, `'.join(sorted(RULES['relations']['private_markers']))}`) ;",
            "- les coordonnées des personnes, et les adresses des demandeurs "
            "particuliers en urbanisme ;",
            "- la date de naissance des élus (le RNE la diffuse, pas nous) ;",
            "- les conseils municipaux des communes hors intercommunalité.",
            "",
            "## Compteurs",
            "",
            f"- entités : {stats['entities_public']} publiées "
            f"sur {stats['entities_total_private']} en base",
            f"- relations : {stats['relations_public']} sur "
            f"{stats['relations_total_private']}",
            f"- actes : {stats['events_public']} sur "
            f"{stats['events_total_private']}",
            f"- points cartographiés : {stats['map_features_public']}",
            f"- sites web vérifiés : {stats['urls_public_confirmed']}",
            "",
            "## Qualité de localisation",
            "",
        ]
        for key, count in sorted(location_quality.items()):
            markdown.append(f"- `{key}` : {count}")
        markdown.extend([
            "",
            "## Exclusions — pourquoi une donnée n'est pas là",
            "",
        ])
        for section, counts in stats["exclusions"].items():
            markdown.append(f"### {section}")
            for reason, count in sorted(counts.items()):
                markdown.append(f"- `{reason}` : {count}")
            markdown.append("")
        (out / "README.md").write_text("\n".join(markdown), encoding="utf-8")

        return stats
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a conservative public snapshot preview")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--no-sync", action="store_true",
                        help="ne pas recopier le snapshot vers public/static/data")
    args = parser.parse_args()

    # Les libellés du site sont dérivés de la même instance que le snapshot :
    # les régénérer ici évite qu'un site publie le nom d'une commune et les
    # chiffres d'une autre.
    try:
        from generer_libelles import construire, ecrire
        ecrire(construire())
    except Exception as e:                      # ne doit jamais bloquer la publication
        print(f"  [libellés] non régénérés : {e}")

    # Une étape de collecte qui manque n'est pas une panne du programme : elle
    # se dit en une phrase, pas en pile d'appels.
    try:
        stats = build_snapshot(args.out)
    except PerimetreNonClasse as e:
        print(f"\n✖ snapshot refusé — {e}", file=sys.stderr)
        return 2

    # Produire le snapshot sans le porter jusqu'au site, c'était la moitié du
    # travail — et la moitié invisible : le site restait tel quel, sans erreur.
    if not args.no_sync:
        sync = synchroniser_site_public(args.out, ROOT)
        stats["site_public_fichiers"] = sync["count"]
        stats["site_public_fiches_retirees"] = len(sync["fiches_retirees"])

    print(json.dumps({"out": str(args.out), **stats}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
