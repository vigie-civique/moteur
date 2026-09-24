"""
jaune_associations.py — Subventions de l'ÉTAT aux associations du territoire.

Source : l'annexe « jaune » au projet de loi de finances, « Effort financier de
l'État en faveur des associations », publiée par les ministères économiques et
financiers sur data.economie.gouv.fr. Elle liste, association par association,
ce que chaque programme budgétaire lui a versé l'année écoulée : FDVA, culture,
cinéma, politique de la ville, sport, bourses scolaires…

C'est le seul registre national de l'argent de l'État aux associations. Les
autres steps n'en voient que ce qui passe par la commune (`subventions`,
`dotations`) ou par une collectivité qui publie (`subv_ouvertes`, `region`).

Le bénéficiaire se reconnaît à son identifiant, jamais à son nom : SIRET quand
le millésime donne le NIC, SIREN sinon, RNA quand il y est — et toujours par
`db.beneficiaires_locaux`, qui ne rattache un SIREN que si le SIÈGE est d'ici.
Chercher « Lasalle » dans ce jeu remonte l'ECAM LaSalle de Lyon et son million
d'euros de recherche universitaire : le nom ne prouve rien.

Les millésimes n'ont ni les mêmes colonnes ni la même profondeur
d'identification — cf. `MILLESIMES`. L'export 2022 (PLF 2024) est publié CASSÉ,
une seule colonne par ligne : il est écarté, et l'écart est écrit ici plutôt
que découvert à nouveau.

Usage :
  python3 -m collectors.jaune_associations
  python3 -m collectors.jaune_associations --dry-run
"""

import argparse
import csv
import io
import re
import sqlite3

import requests

from .archive import archive_fetch
from .config import DB_PATH, HEADERS
from .db import beneficiaire_local, beneficiaires_locaux, pivot_ids

API_BASE = "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets"
SOURCE = "jaune-associations"

# (exercice annoncé, jeu, colonnes). L'exercice est RELU dans la colonne
# `millesime` quand le jeu en porte une : le jeu nommé « plf-2016 » contient
# en réalité le jaune du PLF 2015, subventions 2014.
MILLESIMES = [
    (2023, "plf25-donnees-de-l-annexe-jaune-effort-financier-de-l-etat-en-faveur-des-associations",
     {"programme": "programme", "nom": "denomination", "montant": "montant",
      "objet": "objet_2023", "nic": "nic"}),
    (2016, "projet-de-loi-de-finances-pour-2018-plf-2018-donnees-de-lannexe-jaune-effort-fin",
     {"programme": "programme_2016", "nom": "denomination", "montant": "montant",
      "objet": "objet", "nic": "nic", "rna": "rna"}),
    # Ces deux-là ne donnent que le SIREN : seules les associations dont le
    # siège est d'ici s'y rapprochent — c'est le cas de presque toutes.
    (2014, "plf-2016-jaune-effort-financier-de-letat-en-faveur-des-associations-",
     {"programme": "programme", "nom": "association", "montant": "2014",
      "objet": "objet"}),
    (2012, "plf-2014-jaune-donnees-associations-subventionnees-2012",
     {"programme": "programme", "nom": "association", "montant": "subvention_2012",
      "objet": "objet"}),
]

_MILLESIME_RE = re.compile(r"Subventions\s+(\d{4})", re.I)


def _telecharger(session: requests.Session, jeu: str) -> list[dict]:
    """L'export intégral d'un millésime, filtré ici et non par l'API — même
    raison que `occitanie_region` : le compte de ce qui est écarté doit être
    mesurable. Une quinzaine de mégaoctets par millésime."""
    r = session.get(f"{API_BASE}/{jeu}/exports/csv",
                    params={"delimiter": ";"}, timeout=300)
    r.raise_for_status()
    archive_fetch(SOURCE, r.url, r.content,
                  content_type=r.headers.get("Content-Type"),
                  http_status=r.status_code)
    texte = r.content.decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(texte), delimiter=";"))


def _propre(valeur) -> str:
    """Le jeu 2023 sépare ses mots par des espaces INSÉCABLES et coupe certains
    libellés d'un saut de ligne au milieu d'un mot."""
    return re.sub(r"\s+", " ", str(valeur or "").replace("\xa0", " ")).strip()


def _montant(valeur) -> int | None:
    try:
        return int(round(float(str(valeur or "").replace(",", ".").replace(" ", ""))))
    except (TypeError, ValueError):
        return None


def identifiant(rec: dict, colonnes: dict) -> str:
    """SIRET si le NIC est là, SIREN sinon, chaîne vide si rien n'est lisible.

    « NR CHORUS » occupe la colonne SIREN quand l'association n'en a pas : ce
    n'est pas un identifiant, et le compléter par le nom est précisément ce que
    ce collecteur refuse."""
    siren = re.sub(r"\D", "", str(rec.get("siren") or ""))
    if len(siren) != 9:
        return ""
    nic = re.sub(r"\D", "", str(rec.get(colonnes.get("nic", ""), "") or ""))
    if nic and len(nic) <= 5:
        return siren + nic.zfill(5)
    return siren


def exercice(rec: dict, annonce: int) -> int:
    m = _MILLESIME_RE.search(str(rec.get("millesime") or ""))
    return int(m.group(1)) if m else annonce


def importer(conn, lignes: list[dict], annonce: int, colonnes: dict,
             etat_id: int, dry_run: bool = False) -> dict:
    index = beneficiaires_locaux(conn)
    stats = {"lignes": len(lignes), "retenues": 0, "inserees": 0, "deja": 0,
             "hors_perimetre": 0, "sans_identifiant": 0}

    for rec in lignes:
        ident = identifiant(rec, colonnes)
        rna = _propre(rec.get(colonnes.get("rna", ""), ""))
        if not ident and not rna:
            stats["sans_identifiant"] += 1
            continue
        to_id = beneficiaire_local(index, ident, rna=rna)
        if to_id is None:
            stats["hors_perimetre"] += 1
            continue
        stats["retenues"] += 1

        annee = exercice(rec, annonce)
        montant = _montant(rec.get(colonnes["montant"]))
        programme = _propre(rec.get(colonnes["programme"]))
        objet = _propre(rec.get(colonnes["objet"]))
        # Le programme ouvre la description : c'est lui qui dit quel ministère
        # a payé, et il sert de clé de dédoublonnage avec l'objet — une même
        # association reçoit souvent deux lignes du même programme la même
        # année (FDVA fonctionnement, puis FDVA formation).
        prog = programme.split(" ")[0] if programme else "?"
        description = f"[P{prog}] {objet}"[:250]

        if conn.execute(
            "SELECT 1 FROM financial_flows WHERE source=? AND to_id=? AND year=?"
            " AND amount IS ? AND description=? LIMIT 1",
            (SOURCE, to_id, annee, montant, description)
        ).fetchone():
            stats["deja"] += 1
            continue

        if dry_run:
            print(f"  [DRY] {annee} {montant if montant is not None else '?':>9} € "
                  f"→ #{to_id} {_propre(rec.get(colonnes['nom']))[:40]} — {description[:50]}")
            stats["inserees"] += 1
            continue

        # Une subvention figure au jaune parce qu'elle a été VERSÉE : l'annexe
        # liste les associations ayant reçu une subvention l'année écoulée, et
        # les montants sortent de Chorus, l'outil de paiement de l'État (la
        # colonne SIREN le dit elle-même quand elle vaut « NR CHORUS »).
        conn.execute(
            "INSERT INTO financial_flows"
            " (type, year, amount, from_id, to_id, description, source, confidence)"
            " VALUES ('subvention_etat_association', ?, ?, ?, ?, ?, ?, 'verified')",
            (annee, montant, etat_id, to_id, description, SOURCE))
        conn.execute(
            "INSERT OR IGNORE INTO relations"
            " (from_id, to_id, relation_type, source, confidence)"
            " VALUES (?,?,'subventionné',?,'verified')",
            (etat_id, to_id, SOURCE))
        stats["inserees"] += 1

    return stats


def run(dry_run: bool = False):
    session = requests.Session()
    session.headers.update(HEADERS)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    etat_id = pivot_ids(conn)["etat"]

    total = 0
    for annonce, jeu, colonnes in MILLESIMES:
        print(f"\n[jaune] Subventions {annonce} — {jeu}")
        try:
            lignes = _telecharger(session, jeu)
        except requests.RequestException as exc:
            # Un millésime qui ne répond pas n'empêche pas les autres ; le
            # compteur final dira qu'il manque.
            print(f"  ⚠️ millésime indisponible : {exc}")
            continue
        stats = importer(conn, lignes, annonce, colonnes, etat_id, dry_run=dry_run)
        total += stats["inserees"]
        print(f"  lignes du jeu       : {stats['lignes']}")
        print(f"  bénéficiaire local  : {stats['retenues']}")
        print(f"  insérées            : {stats['inserees']}")
        print(f"  déjà en base        : {stats['deja']}")
        # Pas des anomalies : le jeu couvre la France entière. Ils sont là pour
        # qu'un zéro se lise — jeu vide, ou périmètre sans identifiant ?
        print(f"  hors périmètre      : {stats['hors_perimetre']}")
        print(f"  sans identifiant    : {stats['sans_identifiant']}")

    if not dry_run:
        conn.commit()
    conn.close()
    prefix = "[DRY-RUN] " if dry_run else ""
    print(f"\n{prefix}✅ Jaune associations : {total} flux")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
