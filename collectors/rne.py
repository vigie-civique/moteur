"""
rne.py — Répertoire National des Élus (DGCL, via data.gouv.fr).

**Pourquoi ce collecteur existe.** Les mandats de la base venaient de
`lasalle.fr/les-elus` et de la presse. Le 25/07/2026, cette page n'avait pas été
actualisée après le scrutin de mars : le collecteur a estampillé les commissions
du mandat 2020-2026 avec `since=2026-03-15`, et 12 anciens élus — dont l'ancien
maire — figuraient comme membres actifs. Une source officielle périmée produit
des **affirmations fausses**, pas des trous, et rien ne pouvait le détecter.

Le RNE est la source **autoritaire** : tenue par la DGCL, datée, exhaustive,
avec les fonctions (maire, Ne adjoint). Il sert donc de **contrôle**, pas de
source supplémentaire à empiler :

  - `elus_rne` enregistre le fait officiel tel quel ;
  - une personne absente de la base est créée ;
  - une relation n'est créée que si **aucune relation active du même type**
    n'existe déjà (toute source confondue) — sinon on gonflerait artificiellement
    `nb_relations` et le score d'influence avec des doublons de source ;
  - les **écarts** partent dans `audits/rne_ecarts.json` : qui siège en base sans
    être au RNE (affirmation à vérifier), qui est au RNE sans être en base
    (manque), et les désaccords de fonction.

L'URL des fichiers est **résolue par l'API data.gouv** et jamais codée en dur :
elle est horodatée (`/20260609-130245/`) et change à chaque publication. On
récupère aussi `last_modified` — un jeu qui répond n'est pas un jeu à jour.

Usage :
  python3 -m collectors.rne                  # CM + EPCI, 7 communes
  python3 -m collectors.rne --mandat cm
  python3 -m collectors.rne --dry-run        # écarts seulement, aucune écriture
  python3 -m collectors.rne --stats
"""
from __future__ import annotations

import argparse
import codecs
import csv
import io
import json
import re
import unicodedata
import urllib.request
from datetime import date, datetime
from pathlib import Path

from .archive import archive_fetch
from .config import (COMMUNES, COMMUNES_INSEE, EPCI_COMMUNES, EPCI_NOM,
                     EPCI_SIREN, HEADERS, ROOT)
from .db import get_conn, upsert_entity, upsert_relation

DATAGOUV_DATASET = "5c34c4d1634f4173183a64f1"     # « Répertoire national des élus »
DATAGOUV_API = "https://www.data.gouv.fr/api/1/datasets"
AUDITS = ROOT / "audits"

# Un fichier par type de mandat. `commune_col` diffère : le fichier EPCI porte
# « Code de la commune de rattachement » et non « Code de la commune » — filtrer
# sur le mauvais nom rend 0 ligne en silence.
FICHIERS = {
    "cm": {
        "resource": "elus-conseillers-municipaux-cm.csv",
        "commune_col": "Code de la commune",
        "relation": "élu_cm",
        "label": "conseillers municipaux",
    },
    "epci": {
        "resource": "elus-conseillers-communautaires-epci.csv",
        "commune_col": "Code de la commune de rattachement",
        "relation": "élu_cc",
        "label": "conseillers communautaires",
        # Le conseil communautaire se filtre sur l'EPCI, PAS sur les communes du
        # vallon : la CC CAC dépasse largement nos sept communes, et ne garder
        # que les délégués rattachés à celles-ci donnait 5 noms — ceux de
        # Lasalle — au lieu de l'assemblée qui vote réellement le budget
        # intercommunal. On veut l'organe entier, sinon on ne montre pas qui
        # décide.
        "siren_col": "N° SIREN",
        "siren": {EPCI_SIREN} if EPCI_SIREN else set(),
    },
}

# `Libellé de la fonction` du RNE → type de relation. Le RNE écrit « 1er adjoint
# au Maire », « 2ème adjoint au Maire »… : on retient le rang en métadonnée.
FONCTION_MAIRE = "maire"
FONCTION_ADJOINT = "adjoint"


def norm(s: str | None) -> str:
    """Comparaison de noms : sans accents, majuscules, espaces compactés.

    Indispensable ici : le RNE écrit les prénoms sans accent (« Michele »)
    quand la base porte l'orthographe accentuée. Un match strict raterait la
    moitié du conseil.
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return " ".join(s.upper().replace("-", " ").split())


def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS elus_rne (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            mandat             TEXT NOT NULL,     -- cm | epci
            insee              TEXT NOT NULL,
            commune            TEXT,
            nom                TEXT NOT NULL,
            prenom             TEXT NOT NULL,
            sexe               TEXT,
            birth_year         INTEGER,           -- année seule : cf. RGPD ci-dessous
            csp                TEXT,
            date_debut_mandat  TEXT,
            fonction           TEXT,
            date_debut_fonction TEXT,
            epci_siren         TEXT,
            epci_nom           TEXT,
            entity_id          INTEGER REFERENCES entities(id) ON DELETE SET NULL,
            collected_at       TEXT DEFAULT (datetime('now')),
            UNIQUE(mandat, insee, nom, prenom, date_debut_mandat)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_elus_rne_insee ON elus_rne(insee, mandat)")
    conn.commit()


def resolve_resource(resource_title: str) -> tuple[str, str | None]:
    """(url, last_modified) d'une ressource du dataset RNE, via l'API data.gouv.

    Ne jamais coder l'URL en dur : `static.data.gouv.fr/.../20260609-130245/...`
    change à chaque publication du RNE.
    """
    req = urllib.request.Request(f"{DATAGOUV_API}/{DATAGOUV_DATASET}/", headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r:
        meta = json.load(r)
    for res in meta.get("resources", []):
        if res.get("title") == resource_title:
            return res["url"], res.get("last_modified")
    raise RuntimeError(
        f"ressource « {resource_title} » absente du dataset RNE — "
        f"titres disponibles : {[r.get('title') for r in meta.get('resources', [])]}"
    )


def fetch_rows(mandat: str, insee_list: list[str]) -> tuple[list[dict], str | None]:
    """Télécharge le CSV national en flux et ne garde que les communes visées.

    Le fichier des conseillers municipaux pèse ~72 Mo : on le lit en streaming
    plutôt que de le charger en mémoire, et on n'archive que le sous-ensemble
    du vallon (même convention que dvf-geodvf et rna-waldec — le bulk national
    est re-téléchargeable, seules ces lignes sont exploitées).
    """
    spec = FICHIERS[mandat]
    url, last_modified = resolve_resource(spec["resource"])
    cible = set(insee_list)
    print(f"  [rne] {spec['label']} — publication {str(last_modified)[:10]}")

    req = urllib.request.Request(url, headers=HEADERS)
    gardes: list[dict] = []
    with urllib.request.urlopen(req, timeout=180) as r:
        reader = csv.DictReader(codecs.getreader("utf-8")(r, errors="replace"),
                                delimiter=";")
        colonne = spec.get("siren_col") or spec["commune_col"]
        if colonne not in (reader.fieldnames or []):
            raise RuntimeError(
                f"colonne « {colonne} » absente — le schéma RNE a changé. "
                f"Colonnes : {reader.fieldnames}")
        retenus = spec.get("siren") or cible
        for row in reader:
            if (row.get(colonne) or "").strip() in retenus:
                gardes.append(row)

    if gardes:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(gardes[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(gardes)
        archive_fetch("rne", url, buf.getvalue().encode("utf-8"),
                      doc_type="csv", title=f"RNE {spec['label']} — vallon",
                      metadata={"mandat": mandat, "last_modified": last_modified,
                                "communes": sorted(cible), "lignes": len(gardes)})
    return gardes, last_modified


def _fonction_relation(fonction: str | None, mandat: str = "cm") -> tuple[str | None, str | None]:
    """(type_relation, rang) déduits du libellé de fonction du RNE.

    L'exécutif communautaire (« Président du conseil communautaire »,
    « 1er Vice-président… ») a longtemps été ignoré ici, au motif qu'il était
    « hors périmètre communal ». C'était une erreur : président et
    vice-présidents ne pouvaient alors venir que de BANATIC, dont l'état date du
    15/10/2025 — donc d'AVANT les municipales de mars 2026. La page publique a
    affiché jusqu'au 12/08/2026 un président qui n'était plus délégué.
    """
    f = norm(fonction)
    if not f:
        return None, None
    if mandat == "epci":
        if "VICE PRESIDENT" in f:
            m = re.match(r"^(\d+)", f)                 # « 1ER », « 5EME »…
            return "vice_président_cc", m.group(1) if m else None
        if "PRESIDENT" in f:
            return "président_cc", None
        return None, None
    if f == "MAIRE":
        return FONCTION_MAIRE, None
    if "ADJOINT" in f:
        rang = f.split()[0] if f.split() else None      # « 1ER », « 2EME »…
        return FONCTION_ADJOINT, rang
    return None, None


def _parse_row(mandat: str, row: dict) -> dict:
    spec = FICHIERS[mandat]
    insee = (row.get(spec["commune_col"]) or "").strip()
    naissance = (row.get("Date de naissance") or "").strip()
    # RGPD : le RNE diffuse la date de naissance complète. On ne conserve que
    # l'année — `publication_rules.json` interdit même de la publier, et le
    # schéma `persons` ne prévoit que birth_year/birth_month. Rien ne justifie
    # de stocker le jour.
    birth_year = None
    if len(naissance) >= 4 and naissance[:4].isdigit():
        birth_year = int(naissance[:4])
    return {
        "mandat": mandat,
        "insee": insee,
        "commune": COMMUNES.get(insee, {}).get("nom") or (
            row.get("Libellé de la commune")
            or row.get("Libellé de la commune de rattachement")),
        "nom": (row.get("Nom de l'élu") or "").strip(),
        "prenom": (row.get("Prénom de l'élu") or "").strip(),
        "sexe": (row.get("Code sexe") or "").strip() or None,
        "birth_year": birth_year,
        "csp": (row.get("Libellé de la catégorie socio-professionnelle") or "").strip() or None,
        "date_debut_mandat": (row.get("Date de début du mandat") or "").strip() or None,
        "fonction": (row.get("Libellé de la fonction") or "").strip() or None,
        "date_debut_fonction": (row.get("Date de début de la fonction") or "").strip() or None,
        "epci_siren": (row.get("N° SIREN") or "").strip() or None,
        "epci_nom": (row.get("Libellé de l'EPCI") or "").strip() or None,
        "relation": spec["relation"],
    }


def _index_entites(conn) -> dict[str, int]:
    """Nom normalisé → entity_id, pour les personnes déjà en base."""
    idx: dict[str, int] = {}
    for r in conn.execute("SELECT id, name FROM entities WHERE type='person'"):
        idx.setdefault(norm(r["name"]), r["id"])
    return idx


def _commune_entity(conn, commune: str | None, creer: bool = False) -> int | None:
    """Entité `service` de la commune — cible des relations de mandat.

    Seules Lasalle et Saint-Bonnet existaient sous cette forme : les 5 autres
    communes du vallon n'apparaissaient que comme entités `business` issues de
    SIRENE (« COMMUNE DE SOUDORGUES »), qui sont la personne morale et non
    l'institution. Sans entité `service`, les mandats des 57 élus nouvellement
    créés n'avaient aucune cible et n'étaient donc pas rattachés.
    """
    if not commune:
        return None
    for pattern in (f"Commune de {commune}", commune):
        r = conn.execute(
            "SELECT id FROM entities WHERE type='service' AND name=?", (pattern,)
        ).fetchone()
        if r:
            return r["id"]
    if creer and commune in {c["nom"] for c in COMMUNES.values()}:
        eid = upsert_entity(conn, type="service", name=f"Commune de {commune}",
                            commune=commune, confidence="verified")
        conn.execute(
            "INSERT OR IGNORE INTO services (entity_id, category, operator)"
            " VALUES (?,?,?)", (eid, "admin", f"Commune de {commune}"))
        return eid
    return None


def _epci_entity(conn) -> int | None:
    """Entité `service` de l'intercommunalité — cible des mandats communautaires.

    Recherchée d'abord par le SIREN porté dans les notes d'entité (identifiant
    stable), puis par le nom, qui varie selon les sources (« CC Causses Aigoual
    Cévennes », « Communauté de Communes Causses Aigoual Cévennes »,
    « … Terres Solidaires »).
    """
    r = conn.execute(
        """SELECT e.id FROM entities e
           JOIN entity_notes n ON n.entity_id = e.id
           WHERE e.type='service' AND n.note LIKE ?""",
        (f"%{EPCI_SIREN}%",)).fetchone()
    if r:
        return r["id"]
    noyau = EPCI_NOM.split(" ", 1)[-1]          # « Causses Aigoual Cévennes »
    r = conn.execute(
        "SELECT id FROM entities WHERE type='service' AND name LIKE ?",
        (f"%{noyau}%",)).fetchone()
    return r["id"] if r else None


def _relations_actives(conn, entity_id: int, rel_types: tuple[str, ...]) -> set[str]:
    """Types de relations de mandat déjà actives pour cette personne."""
    q = ",".join("?" for _ in rel_types)
    return {
        r["relation_type"] for r in conn.execute(
            f"""SELECT DISTINCT relation_type FROM relations
                 WHERE from_id=? AND relation_type IN ({q})
                   AND (until IS NULL OR until > date('now'))""",
            (entity_id, *rel_types)).fetchall()
    }


def import_rows(conn, mandat: str, rows: list[dict], dry_run: bool = False) -> dict:
    """Enregistre les faits RNE, complète ce qui manque, et relève les écarts."""
    faits = [_parse_row(mandat, r) for r in rows]
    faits = [f for f in faits if f["nom"] and f["insee"]]
    idx = _index_entites(conn)

    res = {"faits": len(faits), "personnes_creees": 0, "relations_creees": 0,
           "manquants": [], "fonctions_divergentes": []}

    for f in faits:
        nom_complet = f"{f['prenom']} {f['nom']}".strip()
        cle = norm(nom_complet)
        entity_id = idx.get(cle)

        # Périmètre (recadré le 11/08/2026) :
        #   - mandat `cm`   → seuls les conseillers de la commune C1 entrent
        #     dans le graphe. Les conseils municipaux des communes voisines
        #     restent des FAITS officiels (`elus_rne`), utiles pour détecter les
        #     mandats croisés, sans peupler l'annuaire du Gard.
        #   - mandat `epci` → TOUTE l'assemblée communautaire entre dans le
        #     graphe. Ces délégués votent le budget et les compétences exercées
        #     à la place de Lasalle (eau, assainissement, déchets) : ils
        #     décident pour la commune, ils sont donc dans le périmètre C2.
        #     Les réduire aux 5 délégués de Lasalle, c'était montrer un
        #     sixième de l'organe qui décide.
        if mandat == "epci":
            hors_perimetre = f["insee"] not in EPCI_COMMUNES
        else:
            hors_perimetre = f["insee"] not in COMMUNES
        if hors_perimetre:
            if not dry_run:
                conn.execute(
                    """INSERT OR IGNORE INTO elus_rne
                       (mandat, insee, commune, nom, prenom, sexe, birth_year, csp,
                        date_debut_mandat, fonction, date_debut_fonction,
                        epci_siren, epci_nom, entity_id)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)""",
                    (f["mandat"], f["insee"], f["commune"], f["nom"], f["prenom"],
                     f["sexe"], f["birth_year"], f["csp"], f["date_debut_mandat"],
                     f["fonction"], f["date_debut_fonction"],
                     f["epci_siren"], f["epci_nom"]))
            continue

        if entity_id is None and not dry_run:
            entity_id = upsert_entity(conn, type="person", name=nom_complet,
                                      commune=f["commune"], confidence="verified")
            conn.execute(
                "INSERT OR IGNORE INTO persons (entity_id, firstname, lastname, birth_year)"
                " VALUES (?,?,?,?)",
                (entity_id, f["prenom"], f["nom"], f["birth_year"]))
            idx[cle] = entity_id
            res["personnes_creees"] += 1
        if entity_id is None:
            res["manquants"].append({"nom": nom_complet, "commune": f["commune"],
                                     "raison": "personne absente de la base"})

        if not dry_run:
            conn.execute(
                """INSERT OR IGNORE INTO elus_rne
                   (mandat, insee, commune, nom, prenom, sexe, birth_year, csp,
                    date_debut_mandat, fonction, date_debut_fonction,
                    epci_siren, epci_nom, entity_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (f["mandat"], f["insee"], f["commune"], f["nom"], f["prenom"],
                 f["sexe"], f["birth_year"], f["csp"], f["date_debut_mandat"],
                 f["fonction"], f["date_debut_fonction"],
                 f["epci_siren"], f["epci_nom"], entity_id))

        # Relations : on ne crée que ce qui manque. Empiler une relation `rne`
        # par-dessus une relation `élections_2026` identique doublerait le
        # nb_relations de chaque élu et fausserait v_influence_score.
        if entity_id is None:
            continue
        # Un mandat communautaire s'exerce DANS l'EPCI, pas dans la commune de
        # rattachement : la relation doit pointer sur l'intercommunalité, sinon
        # la page « qui décide » de l'EPCI reste vide et le délégué apparaît
        # comme un élu municipal de plus.
        if mandat == "epci":
            cible_id = _epci_entity(conn)
        else:
            cible_id = _commune_entity(conn, f["commune"], creer=not dry_run)
        if cible_id is None:
            continue

        voulues: list[tuple[str, dict]] = [(f["relation"], {})]
        rel_fonction, rang = _fonction_relation(f["fonction"], mandat)
        if rel_fonction:
            voulues.append((rel_fonction, {"rang": rang} if rang else {}))

        deja = _relations_actives(conn, entity_id,
                                  tuple({v[0] for v in voulues} | {FONCTION_MAIRE, FONCTION_ADJOINT}))
        for rel_type, meta in voulues:
            if rel_type in deja:
                continue
            # Le RNE dit « adjoint » mais la base ne l'a pas : soit un manque,
            # soit une divergence de fonction → tracé dans tous les cas.
            if rel_type in (FONCTION_MAIRE, FONCTION_ADJOINT):
                res["fonctions_divergentes"].append({
                    "nom": nom_complet, "commune": f["commune"],
                    "fonction_rne": f["fonction"], "relation_absente": rel_type,
                })
            if dry_run:
                continue
            upsert_relation(conn, entity_id, cible_id, rel_type, source="rne",
                            since=f["date_debut_fonction"] or f["date_debut_mandat"],
                            confidence="verified",
                            metadata=json.dumps({**meta, "fonction_rne": f["fonction"]},
                                                ensure_ascii=False) if (meta or f["fonction"]) else None)
            res["relations_creees"] += 1

    if not dry_run:
        conn.commit()
    return res


def ecarts_base_vs_rne(conn, mandat: str, faits_noms: dict[str, set[str]]) -> list[dict]:
    """Qui siège encore en base alors que le RNE ne le connaît pas.

    C'est le contrôle qui manquait : une page municipale périmée avait laissé
    12 anciens élus « actifs ». Une relation de mandat active sans contrepartie
    au RNE est une affirmation à vérifier.

    ⚠️ **Mais seulement là où le RNE est effectivement peuplé.** Le fichier EPCI
    du 05/05/2026 ne contient que 2 des ~15 communes de la CC CAC (Lasalle et
    Val-d'Aigoual, 27 délégués) : les autres n'ont pas encore été transmises
    après le scrutin de mars. Comparer la base à ce fichier déclarerait suspects
    11 délégués parfaitement légitimes. C'est le piège « source officielle pas à
    jour » retourné contre nous : une source incomplète produit de fausses
    accusations, pas des trous. On ne juge donc que les communes couvertes, et
    la couverture est reportée explicitement.

    Le rattachement se lit différemment selon le mandat : pour un conseiller
    municipal, la cible de la relation est « Commune de X » ; pour un délégué
    communautaire, la cible est l'EPCI et la commune est celle de la personne.
    """
    rel = FICHIERS[mandat]["relation"]
    types = (rel, FONCTION_MAIRE, FONCTION_ADJOINT) if mandat == "cm" else (rel,)
    q = ",".join("?" for _ in types)

    # La commune du mandat se lit sur la CIBLE de la relation, pas sur le tag
    # `commune` de la personne : ce tag est sa domiciliation. Un élu peut
    # habiter une commune et siéger au conseil d'une autre — comparer sur son
    # tag le faisait ressortir comme un faux positif.
    #
    # (Le domicile d'un élu ne figure ni dans les commentaires ni sur le site :
    # c'est une donnée personnelle, distincte de son mandat.)
    tous_les_noms = set().union(*faits_noms.values()) if faits_noms else set()
    couvertes = {c for c, noms in faits_noms.items() if noms}

    # Rattachement fiable d'une personne à une commune = son mandat municipal
    # actif. On NE PEUT PAS utiliser `entities.commune` : la colonne vaut
    # `DEFAULT 'Lasalle'` au schéma, donc 11 délégués communautaires scrapés sur
    # le site de la CC CAC — en réalité élus d'autres communes membres —
    # portaient « Lasalle » sans que personne ne l'ait affirmé. Un défaut de
    # schéma n'est pas une donnée.
    rattachement: dict[int, str] = {}
    for r in conn.execute("""
        SELECT r.from_id AS eid, t.name AS cible FROM relations r
        JOIN entities t ON t.id = r.to_id
        WHERE r.relation_type IN ('élu_cm','maire','adjoint')
          AND (r.until IS NULL OR r.until > date('now'))
          AND t.name LIKE 'Commune de %'
    """):
        rattachement.setdefault(r["eid"], r["cible"].removeprefix("Commune de ").strip())

    suspects = []
    for r in conn.execute(f"""
        SELECT r.id, r.relation_type, r.since, r.source,
               f.id AS eid, f.name, f.commune AS commune_personne, t.name AS cible
        FROM relations r
        JOIN entities f ON f.id = r.from_id
        JOIN entities t ON t.id = r.to_id
        WHERE r.relation_type IN ({q})
          AND (r.until IS NULL OR r.until > date('now'))
          AND f.type = 'person'
        ORDER BY t.name, f.name
    """, types).fetchall():
        nom = norm(r["name"])
        if mandat == "cm":
            # Mandat municipal : la cible EST la commune.
            commune = (r["cible"] or "").removeprefix("Commune de ").strip() or None
        else:
            # Mandat communautaire : la cible est l'EPCI. Le rattachement se
            # déduit du mandat municipal (un délégué communautaire est élu d'une
            # commune membre), jamais du tag `commune` de l'entité.
            commune = rattachement.get(r["eid"])
            if commune is None:
                suspects.append({
                    "relation_id": r["id"], "entity_id": r["eid"], "nom": r["name"],
                    "commune": None, "relation_type": r["relation_type"],
                    "since": r["since"], "source": r["source"],
                    "severite": "rattachement inconnu",
                    "constat": "aucun mandat municipal actif en base : la commune "
                               "membre est inconnue, le contrôle RNE est impossible",
                })
                continue

        if commune not in couvertes:
            # Le RNE ne dit rien de cette commune pour ce mandat : son silence ne
            # prouve rien. On le signale sans accuser personne.
            suspects.append({
                "relation_id": r["id"], "entity_id": r["eid"], "nom": r["name"],
                "commune": commune, "relation_type": r["relation_type"],
                "since": r["since"], "source": r["source"], "severite": "non couvert",
                "constat": "commune absente du fichier RNE — contrôle impossible, "
                           "ne rien conclure",
            })
            continue

        if nom in faits_noms.get(commune, set()):
            continue                      # concordance parfaite
        if nom in tous_les_noms:
            suspects.append({
                "relation_id": r["id"], "entity_id": r["eid"], "nom": r["name"],
                "commune": commune, "relation_type": r["relation_type"],
                "since": r["since"], "source": r["source"], "severite": "à vérifier",
                "constat": "élu au RNE mais rattaché à une autre commune — "
                           "vérifier la cible de la relation",
            })
        else:
            suspects.append({
                "relation_id": r["id"], "entity_id": r["eid"], "nom": r["name"],
                "commune": commune, "relation_type": r["relation_type"],
                "since": r["since"], "source": r["source"], "severite": "suspect",
                "constat": "actif en base, inconnu du RNE alors que sa commune est "
                           "couverte — à vérifier puis clore",
            })
    return suspects


def run(mandats: list[str] | None = None, insee_list: list[str] | None = None,
        dry_run: bool = False) -> dict:
    conn = get_conn()
    ensure_table(conn)
    AUDITS.mkdir(exist_ok=True)
    rapport = {"generated_at": datetime.now().isoformat(timespec="seconds"),
               "dry_run": dry_run, "mandats": {}}
    try:
        for mandat in (mandats or list(FICHIERS)):
            print(f"[rne] {FICHIERS[mandat]['label']}")
            rows, last_modified = fetch_rows(mandat, insee_list or COMMUNES_INSEE)
            print(f"  {len(rows)} élus dans le périmètre")
            if not rows:
                rapport["mandats"][mandat] = {"faits": 0,
                                              "note": "aucune ligne — vérifier la colonne commune"}
                continue

            res = import_rows(conn, mandat, rows, dry_run=dry_run)

            # Index nom normalisé par commune, pour le contrôle inverse
            faits_noms: dict[str, set[str]] = {}
            for row in rows:
                f = _parse_row(mandat, row)
                faits_noms.setdefault(f["commune"] or "?", set()).add(
                    norm(f"{f['prenom']} {f['nom']}"))
            ecarts = ecarts_base_vs_rne(conn, mandat, faits_noms)
            res["ecarts"] = ecarts
            res["publication_rne"] = last_modified
            res["communes_couvertes"] = sorted(c for c, n in faits_noms.items() if n)
            res["communes_non_couvertes"] = sorted(
                set(COMMUNES[i]["nom"] for i in (insee_list or COMMUNES_INSEE))
                - set(res["communes_couvertes"]))
            rapport["mandats"][mandat] = res

            from collections import Counter
            par_sev = Counter(s["severite"] for s in ecarts)
            print(f"  personnes créées      : {res['personnes_creees']}")
            print(f"  relations créées      : {res['relations_creees']}")
            print(f"  fonctions à compléter : {len(res['fonctions_divergentes'])}")
            print(f"  communes couvertes    : {len(res['communes_couvertes'])}/"
                  f"{len(insee_list or COMMUNES_INSEE)}"
                  + (f" — hors contrôle : {', '.join(res['communes_non_couvertes'])}"
                     if res["communes_non_couvertes"] else ""))
            print(f"  écarts                : {dict(par_sev) or '—'}")
            for s in [x for x in ecarts if x["severite"] != "non couvert"][:10]:
                print(f"     ⚠ [{s['severite']}] {s['nom']} / {s['commune']}"
                      f" — {s['relation_type']} depuis {s['since']} [source {s['source']}]")
    finally:
        conn.close()

    (AUDITS / "rne_ecarts.json").write_text(
        json.dumps(rapport, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nRapport d'écarts : audits/rne_ecarts.json")
    return rapport


def stats():
    conn = get_conn()
    try:
        total = conn.execute("SELECT COUNT(*) FROM elus_rne").fetchone()[0]
        print(f"elus_rne : {total} enregistrements")
        for r in conn.execute("""
            SELECT mandat, commune, COUNT(*) n,
                   SUM(fonction IS NOT NULL) avec_fonction
            FROM elus_rne GROUP BY mandat, commune ORDER BY mandat, commune
        """):
            print(f"  {r['mandat']:<5} {(r['commune'] or '?'):<32} {r['n']:>3} élus"
                  f"  ({r['avec_fonction']} avec fonction)")
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mandat", choices=list(FICHIERS), action="append",
                    help="limiter à un type de mandat (répétable)")
    ap.add_argument("--insee", action="append", help="limiter à un code INSEE (répétable)")
    ap.add_argument("--dry-run", action="store_true",
                    help="calculer les écarts sans rien écrire")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()

    if args.stats:
        stats()
        return
    run(mandats=args.mandat, insee_list=args.insee, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
