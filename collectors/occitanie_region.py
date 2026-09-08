"""
occitanie_region.py — Subventions de la Région Occitanie aux entités du territoire.

Source : data.laregion.fr — dataset subventions-du-conseil-regional

Le bénéficiaire se reconnaît à son SIRET, jamais à son nom. Le jeu porte une
colonne `idbeneficiaire` : c'est un SIRET, et le moteur connaît déjà le SIREN de
chaque entreprise et de chaque association de son périmètre. Les deux se
rejoignent sur les neuf premiers chiffres, sans ambiguïté.

Ce collecteur cherchait auparavant le seul EPCI, et par son NOM amputé de sa
forme juridique. Mesuré sur Lasalle : 18 lignes trouvées, un seul bénéficiaire.
Le même jeu, croisé sur les SIREN de la base, en rend 54 pour 15 bénéficiaires
et ~2,1 M€ — l'association Champ Contrechamp (40 000 €), l'ASA du canal
d'irrigation du Prat (76 000 €), sept communes membres. Chercher un nom, c'est
ne trouver que ce qu'on savait déjà chercher.

Ce collecteur reste RÉGIONAL : il n'a de sens qu'en Occitanie. Une instance
d'une autre région doit écrire l'équivalent pour la sienne — les portails
régionaux n'ont ni schéma ni adresse communs. Ce qui est générique ici, c'est
la MÉTHODE : l'export intégral, puis le croisement par identifiant.

Usage :
  python3 -m collectors.occitanie_region
  python3 -m collectors.occitanie_region --dry-run
"""

import argparse
import csv
import io
import sqlite3

import requests

from .archive import archive_fetch
from .config import DB_PATH, HEADERS   # la base est nommée dans la config
from .db import pivot_ids, upsert_entity

API_BASE = "https://data.laregion.fr/api/explore/v2.1/catalog/datasets"
DATASET = "subventions-du-conseil-regional"
EXPORT_URL = f"{API_BASE}/{DATASET}/exports/csv"


def _telecharger(session: requests.Session) -> list[dict]:
    """L'export intégral du jeu, en une requête.

    Le collecteur paginait 100 lignes à la fois derrière un filtre `where` sur
    le nom. Une API peut accepter un filtre qu'elle applique mal, et surtout ce
    filtre-là décidait du résultat AVANT qu'on ait pu le vérifier. L'export
    entier pèse une douzaine de mégaoctets : on le prend en entier, on le
    filtre ici, et le compte de ce qui a été écarté est mesurable.
    """
    r = session.get(EXPORT_URL, params={"delimiter": ";"}, timeout=180)
    r.raise_for_status()
    archive_fetch("occitanie-region", r.url, r.content,
                  content_type=r.headers.get("Content-Type"),
                  http_status=r.status_code)
    texte = r.content.decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(texte), delimiter=";"))


def sirens_locaux(conn) -> dict[str, int]:
    """{SIREN → entity_id} pour tout ce que la base connaît d'immatriculé.

    Les associations comptent autant que les entreprises : c'est par là que
    passent les subventions régionales à la vie associative, et une association
    sans SIREN reste invisible de ce jeu (cf. `rna_enrich`).
    """
    index: dict[str, int] = {}
    for table in ("businesses", "associations"):
        for row in conn.execute(
            f"SELECT entity_id, siren FROM {table} "
            "WHERE siren IS NOT NULL AND length(siren) = 9"
        ):
            index.setdefault(row["siren"], row["entity_id"])
    return index


def _montant(valeur: str) -> int | None:
    try:
        return int(round(float((valeur or "").replace(",", "."))))
    except (TypeError, ValueError):
        return None


def importer(conn, lignes: list[dict], dry_run: bool = False) -> dict:
    # Les deux parties du flux sont résolues par leur nom : les identifiants en
    # dur de l'instance d'origine désignaient d'autres entités dans cette base.
    region_id = upsert_entity(conn, type="service",
                              name="Conseil régional Occitanie",
                              confidence="verified")
    index = sirens_locaux(conn)
    stats = {"lignes": len(lignes), "retenues": 0, "inserees": 0,
             "deja": 0, "hors_perimetre": 0, "sans_siret": 0}

    for rec in lignes:
        siret = (rec.get("idbeneficiaire") or "").strip()
        if len(siret) < 9 or not siret[:9].isdigit():
            stats["sans_siret"] += 1
            continue
        to_id = index.get(siret[:9])
        if to_id is None:
            stats["hors_perimetre"] += 1
            continue
        stats["retenues"] += 1

        ref = (rec.get("referencedecision") or "").strip()
        objet = (rec.get("objet") or "").strip()
        annee = (rec.get("annee_decision") or (rec.get("date_de_decision") or "")[:4]).strip()
        year = int(annee) if annee.isdigit() else None
        montant = _montant(rec.get("montant_vote"))
        description = f"[{ref}] {objet}"[:250] if ref else objet[:250]

        # Dédoublonnage par la RÉFÉRENCE DE DÉCISION, qui identifie la
        # délibération régionale — pas par le montant, que deux subventions
        # d'une même année partagent volontiers.
        if ref and conn.execute(
            "SELECT 1 FROM financial_flows WHERE source='occitanie_region'"
            " AND to_id=? AND description LIKE ? LIMIT 1",
            (to_id, f"[{ref}]%")
        ).fetchone():
            stats["deja"] += 1
            continue

        if dry_run:
            print(f"  [DRY] {annee} {montant if montant is not None else '?':>9} € "
                  f"→ #{to_id} {objet[:60]}")
            stats["inserees"] += 1
            continue

        conn.execute(
            "INSERT INTO financial_flows"
            " (type, year, amount, from_id, to_id, description, source, confidence)"
            " VALUES ('subvention_region', ?, ?, ?, ?, ?, 'occitanie_region', 'verified')",
            (year, montant, region_id, to_id, description))
        conn.execute(
            "INSERT OR IGNORE INTO relations"
            " (from_id, to_id, relation_type, source, confidence)"
            " VALUES (?,?,'subventionné','occitanie_region','verified')",
            (region_id, to_id))
        stats["inserees"] += 1

    return stats


def run(dry_run: bool = False):
    session = requests.Session()
    session.headers.update(HEADERS)

    print("\n[1] Export des subventions du conseil régional Occitanie…")
    lignes = _telecharger(session)
    print(f"  {len(lignes)} lignes reçues")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    pivot_ids(conn)          # garantit l'existence des entités structurantes

    print("\n[2] Croisement par SIREN avec le périmètre…")
    stats = importer(conn, lignes, dry_run=dry_run)

    if not dry_run:
        conn.commit()
    conn.close()

    prefix = "[DRY-RUN] " if dry_run else ""
    print(f"\n{prefix}✅ Occitanie terminé")
    print(f"  lignes du jeu       : {stats['lignes']}")
    print(f"  bénéficiaire local  : {stats['retenues']}")
    print(f"  insérées            : {stats['inserees']}")
    print(f"  déjà en base        : {stats['deja']}")
    # Ces deux compteurs ne sont PAS des anomalies : le jeu couvre toute la
    # région. Ils sont là pour qu'un zéro de la ligne « bénéficiaire local » se
    # lise — source vide, ou périmètre sans SIREN ?
    print(f"  hors périmètre      : {stats['hors_perimetre']}")
    print(f"  sans SIRET lisible  : {stats['sans_siret']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
