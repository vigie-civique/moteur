"""
syndicats_comptes.py — Les comptes des syndicats auxquels l'intercommunalité adhère.

Source : « Balances comptables des syndicats depuis 2010 », DGFiP, sur
data.economie.gouv.fr. Une ligne par syndicat, exercice, budget et compte.

`banatic` pose les syndicats — SIAEP, SYMTOMA, EPTB, syndicat d'énergie, PETR —
et la relation `adhère_à` qui les relie à l'EPCI. Il n'en disait rien d'autre :
à Lasalle, huit fiches sans un acte, sans un flux, sans un chiffre. Or c'est là
que passe l'eau, les déchets, les rivières et l'électrification — des budgets
que la commune ne vote plus, et qu'elle finance pourtant par sa cotisation.

Le syndicat se désigne par son SIREN, jamais par son nom : la fiche `businesses`
quand il y en a une, la note que `banatic` écrit sinon. Rien n'est cherché par
le libellé — « SIAEP de Lasalle » et « SYNDICAT AEP DE LA REGION DE LASALLE »
sont deux personnes morales.

Ce qui est retenu, poste par poste, est écrit dans `POSTES` ; les montants sont
les OPÉRATIONS BUDGÉTAIRES NETTES de l'exercice (`obnetdeb` / `obnetcre`), et le
SOLDE pour l'encours de la dette. Les opérations d'ordre (amortissements,
cessions, travaux en régie) sont écartées : ce sont des écritures, pas de
l'argent qui entre ou qui sort.

Ce collecteur ne crée aucun flux : ce que la balance montre est la somme de
TOUS les membres (« contributions des membres »), pas la part de cet EPCI. En
tirer un flux EPCI → syndicat serait attribuer un montant qu'aucune pièce
n'attribue.

Usage :
  python3 -m collectors.syndicats_comptes
  python3 -m collectors.syndicats_comptes --dry-run
"""

import argparse
import re
import sqlite3
import urllib.parse
from collections import defaultdict

from .archive import fetch_json
from .config import DB_PATH, HEADERS

API = ("https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/"
       "balances-comptables-des-syndicats-depuis-2010/exports/json")
SOURCE = "dgfip-syndicats"

# (poste, sens, préfixes retenus, préfixes écartés). Les préfixes valent pour
# les nomenclatures M14, M57 et M49 (eau) — la classe 6 est une charge et la
# classe 7 un produit dans les trois ; les subdivisions de 747 et 131 nomment le
# financeur dans les trois.
#   charge  : obnetdeb − obnetcre
#   produit : obnetcre − obnetdeb
#   encours : sc − sd, au 31/12
_ORDRE_6 = ("68", "675", "676")
_ORDRE_7 = ("72", "775", "776", "777", "78")
POSTES = (
    ("depenses_fonctionnement", "charge",  ("6",),  _ORDRE_6),
    ("recettes_fonctionnement", "produit", ("7",),  _ORDRE_7),
    ("personnel",               "charge",  ("64",), ()),
    ("subventions_versees",     "charge",  ("657",), ()),
    ("ventes_et_redevances",    "produit", ("70",), ()),
    # Ce que paient les membres — communes, EPCI — pour faire vivre le syndicat.
    ("contributions_membres",   "produit", ("7474", "7475"), ()),
    ("depenses_investissement", "charge",  ("20", "21", "23"), ("204",)),
    ("subventions_equipement_versees", "charge", ("204",), ()),
    ("encours_dette",           "encours", ("16",), ("1688",)),
    # Subventions REÇUES, fonctionnement (747x) et investissement (131x), par
    # financeur. L'Agence de l'eau n'a pas de compte à elle : elle tombe dans
    # « autres », 7478 / 1318.
    ("subventions_etat",        "produit", ("7471", "1311"), ()),
    ("subventions_region",      "produit", ("7472", "1312"), ()),
    ("subventions_departement", "produit", ("7473", "1313"), ()),
    ("subventions_europe",      "produit", ("7477", "1317"), ()),
    ("subventions_autres",      "produit", ("7478", "1318"), ()),
)

_SIREN_NOTE = re.compile(r"SIREN:\s*(\d{9})")


def syndicats_du_territoire(conn) -> list[tuple[int, str, str]]:
    """(entity_id, siren, nom) des syndicats auxquels l'EPCI adhère.

    Le SIREN vient de `businesses` ; à défaut, de la note BANATIC, pour une
    base où `banatic` n'a pas encore été rejoué depuis qu'il le range."""
    out = {}
    for r in conn.execute(
        "SELECT DISTINCT e.id, e.name, b.siren FROM relations r"
        " JOIN entities e ON e.id = r.to_id"
        " LEFT JOIN businesses b ON b.entity_id = e.id"
        " WHERE r.relation_type = 'adhère_à' AND r.source = 'banatic'"
    ):
        siren = r[2] if r[2] and len(r[2]) == 9 else None
        if siren is None:
            for (note,) in conn.execute(
                "SELECT note FROM entity_notes WHERE entity_id=? AND source='BANATIC'",
                (r[0],)
            ):
                m = _SIREN_NOTE.search(note or "")
                if m:
                    siren = m.group(1)
                    break
        if siren:
            out[siren] = (r[0], siren, r[1])
    return list(out.values())


def _f(rec: dict, cle: str) -> float:
    try:
        return float(rec.get(cle) or 0)
    except (TypeError, ValueError):
        return 0.0


def _retenu(compte: str, prefixes: tuple, ecartes: tuple) -> bool:
    return compte.startswith(prefixes) and not compte.startswith(ecartes)


def agreger(lignes: list[dict]) -> dict[tuple, dict]:
    """{(exercice, budget) : {libellé, nomenclature, postes{poste: montant}}}."""
    out: dict[tuple, dict] = {}
    for rec in lignes:
        compte = str(rec.get("compte") or "")
        annee = str(rec.get("exer") or "")[:4]
        budget = str(rec.get("ident") or "")
        if not (compte and annee.isdigit() and budget):
            continue
        cle = (int(annee), budget)
        bloc = out.setdefault(cle, {"libelle": rec.get("lbudg"),
                                    "nomenclature": rec.get("nomen"),
                                    "postes": defaultdict(float)})
        for poste, sens, prefixes, ecartes in POSTES:
            if not _retenu(compte, prefixes, ecartes):
                continue
            if sens == "charge":
                v = _f(rec, "obnetdeb") - _f(rec, "obnetcre")
            elif sens == "produit":
                v = _f(rec, "obnetcre") - _f(rec, "obnetdeb")
            else:
                v = _f(rec, "sc") - _f(rec, "sd")
            bloc["postes"][poste] += v
    return out


def telecharger(siren: str) -> list[dict]:
    if not re.fullmatch(r"\d{9}", siren):
        raise ValueError(f"SIREN illisible : {siren!r}")
    requete = urllib.parse.urlencode({"where": 'siren="%s"' % siren})
    url = f"{API}?{requete}"
    return fetch_json(url, source=SOURCE, timeout=120, headers=HEADERS)


def importer(conn, entity_id: int, siren: str, lignes: list[dict],
             dry_run: bool = False) -> int:
    n = 0
    for (annee, budget), bloc in sorted(agreger(lignes).items()):
        for poste, montant in bloc["postes"].items():
            n += 1
            if dry_run:
                continue
            conn.execute(
                "INSERT INTO comptes_syndicats (entity_id, siren, year, budget,"
                " libelle_budget, nomenclature, poste, montant, source)"
                " VALUES (?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(siren, year, budget, poste) DO UPDATE SET"
                " entity_id=excluded.entity_id, montant=excluded.montant,"
                " libelle_budget=excluded.libelle_budget,"
                " nomenclature=excluded.nomenclature",
                (entity_id, siren, annee, budget, bloc["libelle"],
                 bloc["nomenclature"], poste, round(montant, 2), SOURCE))
    return n


def run(dry_run: bool = False):
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON")
    syndicats = syndicats_du_territoire(conn)
    if not syndicats:
        # Zéro se lit : soit l'EPCI n'adhère à aucun syndicat mixte, soit
        # `banatic` n'a pas tourné.
        print("  Aucun syndicat adhérent connu (lancer d'abord `--step banatic`).")
        conn.close()
        return

    for entity_id, siren, nom in syndicats:
        try:
            lignes = telecharger(siren)
        except Exception as exc:
            print(f"  ⚠️ {nom} ({siren}) : {exc}")
            continue
        n = importer(conn, entity_id, siren, lignes, dry_run=dry_run)
        annees = sorted({str(l.get("exer") or "")[:4] for l in lignes} - {""})
        portee = f"{annees[0]}-{annees[-1]}" if annees else "aucun exercice publié"
        print(f"  {nom[:55]:<55} {siren}  {len(lignes):>5} comptes → {n:>4} postes  ({portee})")

    if not dry_run:
        conn.commit()
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
