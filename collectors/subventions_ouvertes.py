"""
subventions_ouvertes.py — Les subventions que les collectivités publient elles-mêmes.

L'article 10 de la loi du 12 avril 2000 et le décret n° 2017-779 du 5 mai 2017
obligent toute autorité administrative à publier en ligne, sous trois mois, les
données essentielles des conventions de subvention. Le format est normalisé :
schéma `scdl/subventions` d'OpenDataFrance. Sont exemptées les collectivités
territoriales de moins de 3 500 habitants.

Ce collecteur ne connaît AUCUN portail. Il demande à data.gouv.fr quels jeux
déclarent ce schéma — ils étaient 53 le 08/09/2026 — puis retient les lignes
dont le bénéficiaire appartient au périmètre de l'instance. C'est ce qui le rend
générique : la même requête sert une commune de la Drôme et une du Tarn, et le
jour où un département se met à publier, il entre sans qu'on touche au code.

Deux clés de rapprochement, et deux seulement, toutes deux des IDENTIFIANTS :
`idBeneficiaire` (un SIRET) et `rnaBeneficiaire` (un identifiant RNA). La
seconde compte autant que la première : le RNA ne publie un SIRET que pour 3 %
des associations (cf. `rna_enrich`), et sans elle la moitié du tissu associatif
resterait introuvable dans un registre qui parle pourtant de lui.

⚠️ Un zéro est ici une RÉPONSE, pas une panne : il dit qu'aucune collectivité
versant de l'argent sur ce territoire ne respecte l'obligation de publication —
ou qu'elles en sont toutes exemptées. Le compte rendu distingue les deux.

Usage :
  python3 -m collectors.subventions_ouvertes
  python3 -m collectors.subventions_ouvertes --dry-run
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sqlite3

import requests

from .archive import archive_fetch
from .config import DB_PATH, HEADERS
from .db import pivot_ids, upsert_entity

CATALOGUE = "https://www.data.gouv.fr/api/1/datasets/"
SCHEMA = "scdl/subventions"

# Un fichier de conventions de subvention se compte en dizaines de kilooctets.
# Au-delà, ce n'est plus ce schéma — et une collecte ne doit pas pouvoir se
# faire aspirer un gigaoctet par une ressource mal étiquetée.
TAILLE_MAX = 20 * 1024 * 1024


def _cle(nom: str) -> str:
    """La colonne, réduite à ce qui ne varie pas.

    Le schéma est normalisé, son application ne l'est pas : un seul jeu porte
    déjà « Montant » et « Montant » avec une espace finale, « nomBeneficiaire »
    et « nomBeneficiere ». On compare donc en minuscules, sans accents, sans
    espaces — et on accepte les deux orthographes du bénéficiaire.
    """
    n = re.sub(r"[^a-z0-9]", "", (nom or "").strip().lower())
    return {"nombeneficiere": "nombeneficiaire"}.get(n, n)


def _valeur(ligne: dict, *cles: str) -> str:
    for c in cles:
        v = ligne.get(c)
        if v not in (None, ""):
            return str(v).strip()
    return ""


def _montant(valeur: str) -> int | None:
    v = re.sub(r"[^\d,.\-]", "", valeur or "").replace(",", ".")
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def _annee(ligne: dict) -> int | None:
    for champ in ("dateconvention", "dateperiodeversement"):
        m = re.search(r"(?<!\d)(19|20)\d{2}(?!\d)", _valeur(ligne, champ))
        if m:
            return int(m.group(0))
    return None


def jeux_du_schema(session: requests.Session) -> list[dict]:
    """Tous les jeux data.gouv qui déclarent le schéma des subventions."""
    jeux, page = [], 1
    while True:
        r = session.get(CATALOGUE, timeout=60,
                        params={"schema": SCHEMA, "page_size": 50, "page": page})
        r.raise_for_status()
        charge = r.json()
        jeux.extend(charge.get("data", []))
        if not charge.get("next_page"):
            break
        page += 1
    return jeux


def index_local(conn) -> tuple[dict[str, int], dict[str, int]]:
    """({SIREN → entity_id}, {identifiant RNA → entity_id}) du périmètre."""
    sirens: dict[str, int] = {}
    rnas: dict[str, int] = {}
    for table in ("businesses", "associations"):
        for row in conn.execute(
            f"SELECT entity_id, siren FROM {table} "
            "WHERE siren IS NOT NULL AND length(siren) = 9"
        ):
            sirens.setdefault(row["siren"], row["entity_id"])
    for row in conn.execute(
        "SELECT entity_id, rna_id FROM associations "
        "WHERE rna_id IS NOT NULL AND rna_id <> ''"
    ):
        rnas.setdefault(row["rna_id"].strip().upper(), row["entity_id"])
    return sirens, rnas


def _lignes(session: requests.Session, ressource: dict) -> list[dict]:
    if (ressource.get("filesize") or 0) > TAILLE_MAX:
        return []
    r = session.get(ressource["url"], timeout=120)
    r.raise_for_status()
    if len(r.content) > TAILLE_MAX:
        return []
    archive_fetch("scdl-subventions", r.url, r.content,
                  content_type=r.headers.get("Content-Type"),
                  http_status=r.status_code)
    texte = r.content.decode("utf-8-sig", errors="replace")
    entete = texte.split("\n", 1)[0]
    sep = ";" if entete.count(";") >= entete.count(",") else ","
    # `newline=""` : plusieurs fichiers du catalogue portent un retour à la
    # ligne DANS un champ non protégé par des guillemets. Sans ça, le module
    # csv lève, et un seul fichier mal formé emportait la collecte entière.
    lues = csv.DictReader(io.StringIO(texte, newline=""), delimiter=sep)
    return [{_cle(k): v for k, v in ligne.items()} for ligne in lues]


def collecter(conn, session: requests.Session, dry_run: bool = False) -> dict:
    sirens, rnas = index_local(conn)
    pivot_ids(conn)
    stats = {"jeux": 0, "ressources": 0, "lignes": 0, "retenues": 0,
             "inserees": 0, "deja": 0, "illisibles": 0, "attribuants": set()}

    for jeu in jeux_du_schema(session):
        stats["jeux"] += 1
        for res in jeu.get("resources", []):
            if (res.get("format") or "").lower() != "csv":
                continue
            try:
                lignes = _lignes(session, res)
            except (requests.RequestException, csv.Error, UnicodeError,
                    ValueError) as e:
                # Une ressource morte OU MAL FORMÉE n'arrête pas la collecte des
                # autres : ce catalogue est tenu par cinquante organisations
                # différentes, et le schéma normalise les colonnes, pas le soin
                # apporté au fichier. Les échecs sont comptés, pas tus.
                stats["illisibles"] += 1
                print(f"    ⚠ illisible — {jeu.get('title','?')[:46]} "
                      f"({type(e).__name__})")
                continue
            stats["ressources"] += 1
            stats["lignes"] += len(lignes)

            for ligne in lignes:
                siret = re.sub(r"\D", "", _valeur(ligne, "idbeneficiaire"))
                rna = _valeur(ligne, "rnabeneficiaire").upper()
                to_id = (sirens.get(siret[:9]) if len(siret) >= 9 else None)
                if to_id is None and rna:
                    to_id = rnas.get(rna)
                if to_id is None:
                    continue
                stats["retenues"] += 1

                nom_attribuant = _valeur(ligne, "nomattribuant") or "Collectivité"
                stats["attribuants"].add(nom_attribuant)
                objet = _valeur(ligne, "objet")
                ref = _valeur(ligne, "referencedecision")
                montant = _montant(_valeur(ligne, "montant"))
                annee = _annee(ligne)
                description = (f"[{ref}] {objet}" if ref else objet)[:250]

                if conn.execute(
                    "SELECT 1 FROM financial_flows WHERE source='SCDL'"
                    " AND to_id=? AND year IS ? AND description=? LIMIT 1",
                    (to_id, annee, description)
                ).fetchone():
                    stats["deja"] += 1
                    continue

                if dry_run:
                    print(f"  [DRY] {annee} {montant if montant else '?':>9} € "
                          f"{nom_attribuant[:28]:28} → #{to_id} {objet[:40]}")
                    stats["inserees"] += 1
                    continue

                from_id = upsert_entity(conn, type="service", name=nom_attribuant,
                                        confidence="verified")
                conn.execute(
                    "INSERT INTO financial_flows"
                    " (type, year, amount, from_id, to_id, description, source, confidence)"
                    " VALUES ('subvention_publique',?,?,?,?,?,'SCDL','verified')",
                    (annee, montant, from_id, to_id, description))
                stats["inserees"] += 1

    return stats


def run(dry_run: bool = False):
    session = requests.Session()
    session.headers.update(HEADERS)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    print("\n[1] Jeux déclarant le schéma des données essentielles de subvention…")
    stats = collecter(conn, session, dry_run=dry_run)

    if not dry_run:
        conn.commit()
    conn.close()

    prefix = "[DRY-RUN] " if dry_run else ""
    print(f"\n{prefix}✅ Subventions publiées en données ouvertes")
    print(f"  jeux au schéma      : {stats['jeux']}")
    print(f"  fichiers lus        : {stats['ressources']}")
    print(f"  lignes lues         : {stats['lignes']}")
    print(f"  bénéficiaire local  : {stats['retenues']}")
    print(f"  insérées            : {stats['inserees']}  |  déjà en base : {stats['deja']}")
    if stats["illisibles"]:
        print(f"  fichiers illisibles : {stats['illisibles']} "
              f"(sur {stats['ressources'] + stats['illisibles']})")
    if stats["attribuants"]:
        print(f"  collectivités       : {', '.join(sorted(stats['attribuants']))}")
    elif stats["jeux"]:
        # Un zéro qui vient d'une ABSENCE de publication, pas d'une panne.
        print("  Aucune collectivité versant sur ce territoire ne publie ses "
              "conventions de subvention\n  au schéma national — ou toutes en "
              "sont exemptées (moins de 3 500 habitants).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
