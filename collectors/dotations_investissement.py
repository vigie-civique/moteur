"""
dotations_investissement.py — Ce que l'État a ACCORDÉ, opération par opération.

Deux registres nationaux, tous deux à la maille de la commune :

  1. DGCL — « Projets financés par les dotations de soutien à l'investissement
     des collectivités territoriales » : DETR, DSIL et DSID, un fichier par
     exercice depuis 2018. Colonnes utiles : `dispositif`, `beneficiaire_siren`,
     `beneficiaire_code_insee`, `intitule`, `cout_ht`, `subvention`, `taux`.
  2. Ministère de la transition écologique — « Fonds vert, liste des projets
     subventionnés » : `code_commune`, `siret_beneficiaire`, `montant_engage`.

Pourquoi ce collecteur existe alors que `subventions_etat` parlait déjà de
DETR : celui-là lit les TITRES des délibérations et y reconnaît une DEMANDE.
Une demande n'est pas une attribution — le conseil décide de solliciter, l'État
décide d'accorder, et entre les deux il y a le refus, le rabotage et l'abandon.
Sur Lasalle, la base ne contenait que des demandes : 5 DSIL, 3 DETR, 1 Fonds
vert, dont les montants sont devinés par le plus petit nombre rencontré dans la
délibération (0,04 € pour l'une d'elles). Ici les montants sont ceux que
l'administration publie.

Générique par construction : le filtre est le registre INSEE de l'instance,
qu'aucune ligne de ce fichier ne nomme.

Usage :
  python3 -m collectors.dotations_investissement
  python3 -m collectors.dotations_investissement --dry-run
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sqlite3

import requests

from .archive import archive_fetch
from .config import (COMMUNES, COMMUNES_INSEE, DB_PATH, HEADERS)
from .db import pivot_ids, upsert_entity
from .rne import _commune_entity, _epci_entity

API_DATASET = "https://www.data.gouv.fr/api/1/datasets/{}/"
JEU_DGCL = "projets-finances-par-les-dotations-de-soutien-a-linvestissement-des-collectivites-territoriales"
JEU_FONDS_VERT = "fonds-vert-liste-des-projets-subventionnes"

# Les quatre dotations, telles que la DGCL les nomme. Elle ne les écrit pas de
# la même façon d'une année sur l'autre : 2020 ajoute « DSIL Exceptionnelle »,
# 2021 « DSIL RT » et « DSID RT » (rénovation thermique), et ces libellés
# disparaissent ensuite. Prendre le libellé entier pour type produisait un
# `dotation_dsil exceptionnelle` — un type avec une espace dedans, et une
# DSIL que rien ne rattache aux autres DSIL.
#
# On garde donc la FAMILLE pour type, et la variante dans la description : le
# lecteur qui totalise les DSIL les trouve toutes, celui qui veut savoir
# laquelle le lit sur la ligne.
FAMILLES = {"DETR", "DSIL", "DSID", "DPV"}


def _ressources(session: requests.Session, slug: str) -> list[dict]:
    """Les fichiers CSV d'un jeu data.gouv, par son identifiant stable.

    Les URL des ressources portent un horodatage de dépôt
    (`…/20250721-173636/…csv`) : les écrire en dur, c'est épingler la version du
    jour où on a regardé. On demande donc au catalogue.
    """
    r = session.get(API_DATASET.format(slug), timeout=60)
    r.raise_for_status()
    return [res for res in r.json().get("resources", [])
            if (res.get("format") or "").lower() == "csv"]


def _lire_csv(session: requests.Session, url: str, source: str) -> list[dict]:
    r = session.get(url, timeout=180)
    r.raise_for_status()
    archive_fetch(source, r.url, r.content,
                  content_type=r.headers.get("Content-Type"),
                  http_status=r.status_code)
    texte = r.content.decode("utf-8-sig", errors="replace")
    # La DGCL écrit en point-virgule, le Fonds vert en virgule. Le séparateur se
    # DÉDUIT de l'en-tête : une extraction annuelle change de forme sans le dire.
    entete = texte.split("\n", 1)[0]
    sep = ";" if entete.count(";") > entete.count(",") else ","
    return list(csv.DictReader(io.StringIO(texte), delimiter=sep))


def _famille(dispositif: str) -> tuple[str, str]:
    """(type de flux, variante) — « DSIL Exceptionnelle » → ('DSIL', 'DSIL Exceptionnelle').

    Une famille inconnue devient un type à elle seule, en minuscules et sans
    espace : un dispositif que la DGCL créerait demain doit se VOIR en base,
    pas se ranger sous un fourre-tout ni faire échouer la collecte.
    """
    # Normalisé ICI, pas chez l'appelant : une fonction qui compte sur son
    # appelant pour lui passer du propre est fausse dès le deuxième appelant.
    dispositif = " ".join((dispositif or "").split())
    tete = (dispositif.split(" ", 1)[0] or "").upper()
    if tete in FAMILLES:
        return tete, (dispositif if dispositif.upper() != tete else "")
    return ("dotation_" + re.sub(r"[^a-z0-9]+", "_", dispositif.lower()).strip("_")
            if dispositif else "dotation_inconnue"), dispositif


def _annee_du_titre(titre: str) -> int | None:
    """L'exercice lu dans le nom d'un fichier, en écartant les numéros de
    programme budgétaire (« p113 ») qui ressemblent à tout sauf à une année."""
    annees = [int(a) for a in re.findall(r"(?<!\d)(20\d{2})(?!\d)", titre or "")]
    return max(annees) if annees else None


def _nombre(valeur) -> int | None:
    try:
        return int(round(float(str(valeur).replace(",", ".").replace(" ", ""))))
    except (TypeError, ValueError):
        return None


def _beneficiaire(conn, insee: str, siren: str, nom: str,
                  pivots: dict, siren_epci: str) -> int | None:
    """L'entité qui a reçu l'argent : une commune du périmètre, ou l'EPCI.

    L'ordre compte. Le SIREN de l'intercommunalité passe EN PREMIER : la DGCL
    laisse `beneficiaire_code_insee` vide pour un EPCI, mais quand elle le
    remplit c'est celui de la commune du siège — et l'opération serait portée au
    compte de cette commune alors qu'elle a été votée par l'intercommunalité.
    """
    if siren and siren_epci and siren == siren_epci:
        return _epci_entity(conn) or pivots["epci"]
    if insee and insee in COMMUNES:
        nom_commune = COMMUNES[insee]["nom"]
        return _commune_entity(conn, nom_commune, creer=True)
    if siren:
        # Un bénéficiaire du périmètre qui n'est ni la commune ni l'EPCI : un
        # syndicat, un CCAS. On ne le retrouve que par son SIREN.
        for table in ("businesses", "associations"):
            row = conn.execute(
                f"SELECT entity_id FROM {table} WHERE siren=?", (siren,)).fetchone()
            if row:
                return row["entity_id"]
    return None


def _dans_le_perimetre(insee: str, siren: str, siren_epci: str) -> bool:
    return bool((insee and insee in COMMUNES_INSEE)
                or (siren and siren_epci and siren == siren_epci))


def collecter(conn, session: requests.Session, dry_run: bool = False) -> dict:
    from .config import EPCI_SIREN
    siren_epci = (EPCI_SIREN or "").strip()
    pivots = pivot_ids(conn)
    etat_id = pivots["etat"]
    stats = {"lignes": 0, "retenues": 0, "inserees": 0, "deja": 0,
             "sans_beneficiaire": 0}

    lots: list[tuple[str, list[dict], str]] = []
    for res in _ressources(session, JEU_DGCL):
        lots.append(("dgcl", _lire_csv(session, res["url"], "dgcl-dotations"),
                     res.get("title", "")))
    for res in _ressources(session, JEU_FONDS_VERT):
        lots.append(("fonds_vert", _lire_csv(session, res["url"], "fonds-vert"),
                     res.get("title", "")))

    for origine, lignes, titre in lots:
        stats["lignes"] += len(lignes)
        for ligne in lignes:
            if origine == "dgcl":
                insee = (ligne.get("beneficiaire_code_insee") or "").strip()
                siren = (ligne.get("beneficiaire_siren") or "").strip()
                nom = (ligne.get("beneficiaire_nom") or "").strip()
                objet = (ligne.get("intitule") or "").strip()
                montant = _nombre(ligne.get("subvention"))
                annee = _nombre(ligne.get("exercice"))
                dispositif = " ".join((ligne.get("dispositif") or "").split())
                type_flux, variante = _famille(dispositif)
                if variante:
                    objet = f"{variante} — {objet}"
                cout = _nombre(ligne.get("cout_ht"))
                source = "DGCL"
            else:
                insee = (ligne.get("code_commune") or "").strip()
                siret = (ligne.get("siret_beneficiaire") or "").strip()
                siren = siret[:9] if len(siret) >= 9 else ""
                nom = (ligne.get("raison_sociale_beneficiaire") or "").strip()
                objet = (ligne.get("nom_du_projet") or "").strip()
                montant = _nombre(ligne.get("montant_engage"))
                # Le Fonds vert ne porte l'exercice dans aucune colonne : il est
                # dans le NOM du fichier (`fonds-vert-2025-export.csv`,
                # `fonds-vert-p113-2024-export.csv`). Un flux sans année n'est
                # pas seulement incomplet — la page des finances le range hors
                # de toute période et le total d'un exercice l'ignore.
                annee = _annee_du_titre(titre)
                type_flux = "Fonds_vert"
                cout = None
                source = "Fonds vert (MTE)"

            if not _dans_le_perimetre(insee, siren, siren_epci):
                continue
            stats["retenues"] += 1

            to_id = _beneficiaire(conn, insee, siren, nom, pivots, siren_epci)
            if to_id is None:
                stats["sans_beneficiaire"] += 1
                continue

            description = objet[:250]
            if cout:
                description = f"{description} (coût {cout:,} € HT)".replace(",", " ")

            # Dédoublonnage sur l'opération : même dispositif, même exercice,
            # même bénéficiaire, même objet. Le montant n'y entre pas — il est
            # précisément ce qui peut être corrigé d'une publication à l'autre.
            if conn.execute(
                "SELECT 1 FROM financial_flows WHERE type=? AND year=? AND to_id=?"
                " AND description=? LIMIT 1",
                (type_flux, annee, to_id, description)
            ).fetchone():
                stats["deja"] += 1
                continue

            if dry_run:
                print(f"  [DRY] {annee} {type_flux:12} {montant if montant else '?':>9} € "
                      f"→ #{to_id} {objet[:56]}")
                stats["inserees"] += 1
                continue

            conn.execute(
                "INSERT INTO financial_flows"
                " (type, year, amount, from_id, to_id, description, source, confidence)"
                " VALUES (?,?,?,?,?,?,?,'verified')",
                (type_flux, annee, montant, etat_id, to_id, description, source))
            stats["inserees"] += 1

    return stats


def run(dry_run: bool = False):
    session = requests.Session()
    session.headers.update(HEADERS)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    print("\n[1] Dotations d'investissement accordées (DGCL + Fonds vert)…")
    stats = collecter(conn, session, dry_run=dry_run)

    if not dry_run:
        conn.commit()
    conn.close()

    prefix = "[DRY-RUN] " if dry_run else ""
    print(f"\n{prefix}✅ Dotations d'investissement terminé")
    print(f"  lignes lues         : {stats['lignes']}")
    print(f"  dans le périmètre   : {stats['retenues']}")
    print(f"  insérées            : {stats['inserees']}")
    print(f"  déjà en base        : {stats['deja']}")
    # Ce compteur-là est le seul qui soit une ANOMALIE : une opération du
    # périmètre dont on ne sait pas nommer le bénéficiaire.
    if stats["sans_beneficiaire"]:
        print(f"  ⚠ bénéficiaire non résolu : {stats['sans_beneficiaire']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
