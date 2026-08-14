#!/usr/bin/env python3
"""
generer_profils.py — Propose `profils_locaux.json` et `seed_local.json` à partir
de ce que la collecte a déjà trouvé.

Ces deux fichiers sont la part humaine de l'amorçage : sans eux, les steps
`profiles` et `seed` tournent à vide en 0,0 s sans rien signaler. Les écrire à
la main pour chaque commune, c'est plusieurs heures ; or la base contient déjà
la matière — le RNE donne les élus, SIRENE et le RNA donnent les dirigeants,
`cm_finances` a extrait les subventions du texte des séances.

Ce script ne remplace pas la relecture, il la prépare. Tout ce qu'il écrit porte
un `_source` et un `confidence` : ce qui vient d'un registre national est
`verified`, ce qui vient d'un rapprochement est `probable`, et ce qui n'a pas pu
être établi est laissé vide plutôt que deviné.

  python3 scripts/generer_profils.py                 # les deux fichiers
  python3 scripts/generer_profils.py --profils       # seulement les profils
  python3 scripts/generer_profils.py --seed          # seulement le catalogue
  python3 scripts/generer_profils.py --web           # + recherche web par personne
  python3 scripts/generer_profils.py --force         # écrase un fichier existant

Sans `--force`, un fichier déjà présent n'est jamais écrasé : la proposition
part dans `<nom>.propose.json`, à comparer puis à renommer.

RGPD — ces fichiers ne sont pas versionnés et ne sont pas publiables tels quels.
L'atelier collecte large, le filtre de publication tranche au moment de publier
(cf. config/publication_rules.json). Une personne n'entre ici qu'au titre d'un
mandat électif, d'une fonction dans une association ou d'une responsabilité
inscrite dans un registre public — jamais au titre d'un lien de famille, d'une
adresse ou d'une date de naissance.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from collectors.config import (COMMUNE_INSEE, COMMUNE_NAME, COMMUNE_URL,  # noqa: E402
                               DB_PATH)

PROFILS = ROOT / "config" / "profils_locaux.json"
SEED    = ROOT / "config" / "seed_local.json"

# Fonctions RNE ramenées à un rôle. Le RNE écrit « 1er adjoint au Maire »,
# « 5eme Vice-président du conseil communautaire »… avec une casse et une
# numérotation qui varient d'une commune à l'autre.
def _role(fonction: str | None) -> str:
    f = (fonction or "").strip().lower()
    if not f:
        return "conseiller"
    if "maire" in f and "adjoint" not in f and "vice" not in f:
        return "maire"
    if "adjoint" in f:
        return "adjoint"
    if "vice-président" in f or "vice-president" in f or "vice président" in f:
        return "vice-président communautaire"
    if "président" in f or "president" in f:
        return "président communautaire"
    return "conseiller"


ORDRE_ROLE = {"maire": 0, "adjoint": 1, "président communautaire": 2,
              "vice-président communautaire": 3, "conseiller": 4}


def ouvrir() -> sqlite3.Connection:
    if not Path(DB_PATH).exists():
        sys.exit(f"base introuvable : {DB_PATH} — lancer la collecte d'abord.")
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _table_existe(conn, nom: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (nom,)
    ).fetchone() is not None


# ── Entité « commune » ───────────────────────────────────────────────────────
def entite_commune(conn) -> dict:
    """La mairie telle que la base la connaît, à défaut telle que l'instance la déclare."""
    ligne = conn.execute(
        "SELECT name, short_name, lat, lng, address FROM entities"
        " WHERE type='service' AND (name LIKE ? OR name LIKE ?)"
        " ORDER BY length(name) LIMIT 1",
        (f"Commune de {COMMUNE_NAME}%", f"Mairie de {COMMUNE_NAME}%")
    ).fetchone()
    if ligne:
        return {"type": "service", "name": ligne["name"],
                "short_name": ligne["short_name"] or f"Mairie de {COMMUNE_NAME}",
                "lat": ligne["lat"] or 0.0, "lng": ligne["lng"] or 0.0,
                "address": ligne["address"] or ""}
    return {"type": "service", "name": f"Commune de {COMMUNE_NAME}",
            "short_name": f"Mairie de {COMMUNE_NAME}",
            "lat": 0.0, "lng": 0.0, "address": ""}


# ── Élus ─────────────────────────────────────────────────────────────────────
def elus(conn) -> tuple[list[dict], str | None]:
    """Élus de la commune d'après le RNE, fusionnés sur (nom, prénom).

    Une même personne y figure deux fois quand elle siège aussi à
    l'intercommunalité : c'est un mandat de plus, pas une personne de plus.
    """
    if not _table_existe(conn, "elus_rne"):
        return [], None
    par_personne: dict[tuple, dict] = {}
    debuts: list[str] = []
    for r in conn.execute(
        "SELECT nom, prenom, fonction, mandat, date_debut_mandat"
        "  FROM elus_rne WHERE insee=?", (COMMUNE_INSEE,)
    ):
        cle = (r["nom"].strip().upper(), r["prenom"].strip())
        e = par_personne.setdefault(cle, {
            "firstname": r["prenom"].strip(),
            "lastname": r["nom"].strip().upper(),
            "cm": False, "cc": False, "role": "conseiller",
            "confidence": "verified", "_source": "RNE",
        })
        if r["mandat"] == "cm":
            e["cm"] = True
        else:
            e["cc"] = True
        role = _role(r["fonction"])
        if ORDRE_ROLE[role] < ORDRE_ROLE[e["role"]]:
            e["role"] = role
        if r["date_debut_mandat"]:
            debuts.append(r["date_debut_mandat"])

    sortie = sorted(par_personne.values(),
                    key=lambda e: (ORDRE_ROLE[e["role"]], e["lastname"]))
    for rang, e in enumerate(sortie, 1):
        e["rank"] = rang
    # Date d'installation = le début de mandat le plus fréquent.
    installation = max(set(debuts), key=debuts.count) if debuts else None
    return sortie, installation


def liste_majoritaire(conn) -> tuple[str, dict]:
    """Nom de la liste arrivée en tête au dernier scrutin municipal."""
    if not _table_existe(conn, "elections_listes"):
        return "conseil municipal", {}
    r = conn.execute(
        "SELECT scrutin, libelle, tete_de_liste, voix, pct_exprimes"
        "  FROM elections_listes WHERE insee=?"
        " ORDER BY scrutin DESC, tour DESC, voix DESC LIMIT 1", (COMMUNE_INSEE,)
    ).fetchone()
    if not r or not r["libelle"]:
        return "conseil municipal", {}
    return r["libelle"], {
        "scrutin": r["scrutin"], "tete_de_liste": r["tete_de_liste"],
        "voix": r["voix"], "pct_exprimes": r["pct_exprimes"],
    }


# ── Entourage : les autres personnes qui exercent une responsabilité ─────────
MOTIFS = {
    "association": "dirigeant d'une association du territoire",
    "subventionné": "dirigeant d'une structure subventionnée par la commune",
    "prestataire": "dirigeant d'un titulaire de marché public",
    "bailleur_commune": "bailleur de la commune",
    "locataire_commune": "locataire de la commune",
}


def entourage(conn, noms_elus: set[tuple]) -> list[dict]:
    """Personnes physiques exerçant une responsabilité publique, hors élus.

    Deux portes d'entrée, et deux seulement :
      - diriger une association du territoire (registre RNA, statuts publiés) ;
      - diriger une structure en relation d'argent avec la commune (subvention,
        marché, bail).

    La troisième porte possible — diriger n'importe quelle entreprise de la
    commune — est volontairement fermée : SIRENE compte ici plus de trois mille
    « dirigeants » qui sont en réalité des entrepreneurs individuels portant
    leur propre nom. Les verser dans un fichier de personnalités publiques
    reviendrait à ficher la population active de la commune.
    """
    resultats: dict[tuple, dict] = {}

    def _ajouter(r, motif_cle: str):
        cle = ((r["lastname"] or "").strip().upper(), (r["firstname"] or "").strip())
        if not cle[0] or cle in noms_elus:
            return
        e = resultats.get(cle)
        if e is None:
            e = resultats[cle] = {
                "firstname": cle[1], "lastname": cle[0],
                "roles": [], "confidence": "probable",
                "_source": r["source"] or "?",
            }
        role = {"organisation": r["organisation"], "fonction": r["relation_type"],
                "motif": MOTIFS[motif_cle]}
        if role not in e["roles"]:
            e["roles"].append(role)

    # 1. Dirigeants d'associations
    for r in conn.execute("""
        SELECT p.firstname, p.lastname, r.relation_type, r.source,
               e2.name AS organisation
          FROM relations r
          JOIN persons  p  ON p.entity_id = r.from_id
          JOIN entities e2 ON e2.id       = r.to_id
         WHERE e2.type = 'association'
           AND r.relation_type IN ('président','dirigeant','gérant',
                                   'trésorier','secrétaire')
    """):
        _ajouter(r, "association")

    # 2. Dirigeants d'une structure liée à la commune par l'argent public.
    #    Ces relations ne vont pas toutes dans le même sens : `subventionné`
    #    part de la commune vers le bénéficiaire, `prestataire` part du
    #    titulaire vers la commune. Filtrer sur un seul côté ne rendait rien.
    #    On collecte donc l'autre extrémité, quelle qu'elle soit.
    commune_id = (conn.execute(
        "SELECT id FROM entities WHERE type='service' AND name LIKE ?"
        " ORDER BY length(name) LIMIT 1", (f"Commune de {COMMUNE_NAME}%",)
    ).fetchone() or {"id": -1})["id"]

    for motif in ("subventionné", "prestataire", "bailleur_commune",
                  "locataire_commune"):
        structures = set()
        for r in conn.execute(
            "SELECT from_id, to_id FROM relations WHERE relation_type=?", (motif,)
        ):
            for côté in (r["from_id"], r["to_id"]):
                if côté != commune_id:
                    structures.add(côté)
        if not structures:
            continue
        trous = ",".join("?" * len(structures))
        for r in conn.execute(f"""
            SELECT p.firstname, p.lastname, rd.relation_type, rd.source,
                   e2.name AS organisation
              FROM relations rd
              JOIN entities e2 ON e2.id       = rd.to_id
              JOIN persons  p  ON p.entity_id = rd.from_id
             WHERE rd.to_id IN ({trous})
               AND rd.relation_type IN ('président','dirigeant','gérant')
        """, tuple(structures)):
            _ajouter(r, motif)

    sortie = sorted(resultats.values(),
                    key=lambda e: (e["lastname"], e["firstname"]))
    return sortie


# ── Recherche web ────────────────────────────────────────────────────────────
def rechercher_web(personnes: list[dict], commune: str, pause: float = 2.0,
                   limite: int = 3) -> int:
    """Ajoute à chaque personne les premiers résultats d'une recherche web.

    Ce sont des PISTES, pas des faits : elles ne sont ni écrites en base ni
    publiées. Elles servent à la relecture humaine du fichier — reconnaître un
    homonyme, retrouver le site d'une association, dater une prise de fonction.
    """
    try:
        from ddgs import DDGS
    except ImportError:
        print("  [web] ddgs absent — `pip install ddgs`. Recherche ignorée.")
        return 0

    trouves = 0
    with DDGS() as ddgs:
        for i, p in enumerate(personnes, 1):
            requete = f'"{p["firstname"]} {p["lastname"]}" {commune}'
            print(f"  [web] {i}/{len(personnes)} {requete}", flush=True)
            try:
                res = list(ddgs.text(requete, region="fr-fr", max_results=limite))
            except Exception as e:
                print(f"        échec : {e}")
                res = []
            p["recherche_web"] = [
                {"titre": r.get("title"), "url": r.get("href"),
                 "extrait": (r.get("body") or "")[:200]}
                for r in res
            ]
            trouves += len(p["recherche_web"])
            time.sleep(pause)          # DuckDuckGo coupe vite si on insiste
    return trouves


# ── Catalogue : comptes rendus, subventions, baux ────────────────────────────
def cr_catalogue(conn) -> list[dict]:
    lignes = conn.execute("""
        SELECT date, source_url, title FROM events
         WHERE type IN ('conseil_municipal','conseil_communautaire')
           AND source_url IS NOT NULL AND source_url <> ''
         GROUP BY date, source_url
         ORDER BY date DESC
    """).fetchall()
    return [{"date": r["date"], "url": r["source_url"], "note": r["title"] or ""}
            for r in lignes]


def subventions(conn) -> dict[str, list]:
    par_annee: dict[str, list] = defaultdict(list)
    for r in conn.execute("""
        SELECT f.year, f.amount, e.name
          FROM financial_flows f
          LEFT JOIN entities e ON e.id = f.to_id
         WHERE f.type = 'subvention' AND f.year IS NOT NULL
         ORDER BY f.year DESC, f.amount DESC
    """):
        par_annee[str(r["year"])].append([r["name"] or "(bénéficiaire inconnu)",
                                          r["amount"]])
    return dict(par_annee)


def baux(conn) -> list[dict]:
    return [{"annee": r["year"], "montant": r["amount"],
             "partie": r["name"] or "", "description": r["description"] or ""}
            for r in conn.execute("""
        SELECT f.year, f.amount, f.description, e.name
          FROM financial_flows f
          LEFT JOIN entities e ON e.id = f.to_id
         WHERE f.type IN ('bail','loyer') ORDER BY f.year DESC
    """)]


# ── Écriture ─────────────────────────────────────────────────────────────────
def ecrire(cible: Path, contenu: dict, force: bool) -> Path:
    destination = cible
    if cible.exists() and not force:
        destination = cible.with_suffix(".propose.json")
        print(f"  {cible.name} existe déjà → proposition dans {destination.name}")
    destination.write_text(json.dumps(contenu, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    return destination


def main() -> int:
    ap = argparse.ArgumentParser(description="Proposer profils_locaux et seed_local")
    ap.add_argument("--profils", action="store_true", help="seulement les profils")
    ap.add_argument("--seed", action="store_true", help="seulement le catalogue")
    ap.add_argument("--web", action="store_true",
                    help="recherche web sur chaque personne (lent, opt-in)")
    ap.add_argument("--pause", type=float, default=2.0,
                    help="secondes entre deux recherches web (défaut 2)")
    ap.add_argument("--force", action="store_true", help="écraser un fichier existant")
    args = ap.parse_args()

    les_deux = not (args.profils or args.seed)
    conn = ouvrir()
    commune = entite_commune(conn)
    aujourdhui = date.today().isoformat()

    if args.profils or les_deux:
        liste_elus, installation = elus(conn)
        nom_liste, scrutin = liste_majoritaire(conn)
        noms = {(e["lastname"], e["firstname"]) for e in liste_elus}
        proches = entourage(conn, noms)

        if args.web:
            n = rechercher_web(liste_elus + proches, COMMUNE_NAME, args.pause)
            print(f"  [web] {n} pistes collectées")

        contenu = {
            "_doc": ("Proposé par scripts/generer_profils.py, à relire avant usage. "
                     "Jamais versionné : contient des noms de personnes physiques."),
            "_genere_le": aujourdhui,
            "_avertissement": (
                "Le RNE ne publie pas l'appartenance d'un élu à une liste : tous "
                "les élus sont regroupés sous la liste arrivée en tête, ce qui est "
                "faux dès qu'un siège revient à l'opposition. À corriger à la main. "
                "Les candidats non élus ne sont pas déductibles de la base."),
            "commune": commune,
            "date_installation": installation or "",
            "_scrutin": scrutin,
            "listes": {nom_liste: {"elus": liste_elus, "non_elus": []}},
            "entourage": proches,
        }
        d = ecrire(PROFILS, contenu, args.force)
        print(f"✓ {d.relative_to(ROOT)} — {len(liste_elus)} élus, "
              f"{len(proches)} autres responsables")

    if args.seed or les_deux:
        cat, subs, bx = cr_catalogue(conn), subventions(conn), baux(conn)
        contenu = {
            "_doc": ("Proposé par scripts/generer_profils.py à partir de ce que la "
                     "collecte a trouvé. À relire et à compléter. Jamais versionné."),
            "_genere_le": aujourdhui,
            "base_url": COMMUNE_URL or "",
            "commune": commune,
            "cr_catalogue": cat,
            "subventions": subs,
            "baux": bx,
            "transactions_saisies": [],
        }
        d = ecrire(SEED, contenu, args.force)
        total = sum(len(v) for v in subs.values())
        print(f"✓ {d.relative_to(ROOT)} — {len(cat)} séances, "
              f"{total} subventions sur {len(subs)} exercices, {len(bx)} baux")

    return 0


if __name__ == "__main__":
    sys.exit(main())
