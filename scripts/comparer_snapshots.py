#!/usr/bin/env python3
"""Comparateur de deux snapshots publics — ce qui a changé, fichier par fichier.

À quoi il sert : prouver qu'une modification du builder ne change RIEN à ce
qu'il produit, ou montrer exactement ce qu'elle change. On construit une
référence avant, un snapshot après, et on compare — sur la base de la CI comme
sur celle d'une instance.

Comme `verify_snapshot.py`, il n'importe ni le builder ni le contrôleur : un
outil qui juge la sortie du builder avec le code du builder hériterait de ses
défauts, et dirait « identique » chaque fois que les deux se trompent pareil.
Il ne lit que des fichiers, et ne connaît du snapshot que la liste ci-dessous.

Usage :
    python3 scripts/comparer_snapshots.py <ancien> <nouveau> [--json]

Le verdict se rend sur les OCTETS : deux fichiers sont identiques si, une fois
les champs volatils neutralisés, leur texte est le même au caractère près —
ordre des clés, indentation et ordre de tri compris. L'analyse de structure
(objets ajoutés, retirés, modifiés ; premier chemin de clé qui diffère) ne sert
qu'à EXPLIQUER un écart, jamais à en absoudre un.

Sortie : 0 si les deux snapshots sont identiques (volatils neutralisés), 1
sinon, 2 si un des deux répertoires manque. Avec `--json`, le rapport sort
entier : tous les identifiants, tous les chemins qui diffèrent — le format
machine n'est pas un résumé.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path
from typing import NamedTuple


class Volatil(NamedTuple):
    fichiers: str          # motif de chemin relatif au snapshot (fnmatch)
    cle: str | None        # chemin de clé dans un JSON (« a.b.c »)…
    motif: str | None      # …ou expression régulière dans un fichier texte
    pourquoi: str


# ── Les champs volatils — LE SEUL endroit où ils se déclarent ────────────────
#
# Un champ volatil change d'une construction à l'autre sans que rien n'ait
# changé dans la base ni dans le code : c'est l'heure qu'il était. Tout le
# reste est comparé. Ajouter une ligne ici, c'est décider qu'un écart ne compte
# pas : chaque entrée dit donc pourquoi.
#
# Ce qui n'y figure PAS, et c'est voulu : ce que la date de construction
# DÉCIDE. Le fil d'actualité se trie contre le jour d'arrêt, la couverture
# range un acte « à venir » ou non selon ce même jour, et un mandat clos hier
# sort de la liste des délégués. Deux constructions faites à deux dates
# peuvent donc différer pour de bon — et le comparateur le dit. Pour comparer
# deux codes plutôt que deux jours, on donne au second l'horloge du premier :
# `VIGIE_HORLOGE`, cf. `build_public_snapshot.py`.
VOLATILS = (
    Volatil("stats.json", "generated_at", None,
            "l'heure de la construction, lue à l'horloge"),
    Volatil("popolo.json", "generated_at", None,
            "l'heure de la construction, recopiée dans l'export Popolo"),
    Volatil("actualite.json", "genere_le", None,
            "recopie de `stats.generated_at`"),
    Volatil("actualite.json", "arrete_le", None,
            "le jour de la construction ; ce qu'il décide (tri, éléments à "
            "venir) n'est pas neutralisé"),
    Volatil("couverture.json", "arrete_le", None,
            "recopie de `stats.generated_at` ; les périodes qu'il borne ne "
            "sont pas neutralisées"),
    Volatil("README.md", None, r"(?m)^Généré le \S+ depuis la base de travail",
            "la même heure, écrite dans le dictionnaire de données"),
    Volatil("conseils/*.html", None, r"vérifié le (?:1er|\d{1,2}) \S+ \d{4}",
            "le rendu d'une séance en clair date sa vérification du jour de la "
            "construction (`collectors/en_clair/rendu.py`), pas de l'horloge "
            "du builder"),
)

NEUTRE = "<volatil>"
SUFFIXES_JSON = (".json", ".geojson")
MAX_EXEMPLES = 3       # dans le rapport texte seulement ; `--json` rend tout
LARGEUR_VALEUR = 90


# ── Lecture ──────────────────────────────────────────────────────────────────

def fichiers_de(racine: Path) -> dict[str, Path]:
    """Tous les fichiers du snapshot, sous-dossiers compris, par chemin relatif."""
    return {f.relative_to(racine).as_posix(): f
            for f in sorted(racine.rglob("*")) if f.is_file()}


def volatils_de(rel: str) -> list[Volatil]:
    return [v for v in VOLATILS if fnmatch.fnmatchcase(rel, v.fichiers)]


def _valeur_au_chemin(donnees, cle: str):
    """La valeur portée par `a.b.c`, ou `KeyError` si le chemin n'existe pas."""
    noeud = donnees
    for partie in cle.split("."):
        if not isinstance(noeud, dict) or partie not in noeud:
            raise KeyError(cle)
        noeud = noeud[partie]
    return noeud


def _poser_au_chemin(donnees, cle: str, valeur) -> None:
    *parents, derniere = cle.split(".")
    noeud = donnees
    for partie in parents:
        noeud = noeud[partie]
    noeud[derniere] = valeur


def neutraliser_texte(texte: str, donnees, volatils: list[Volatil]) -> str:
    """Le texte du fichier, ses champs volatils remplacés par un jeton.

    La neutralisation se fait dans le TEXTE et non dans la structure relue :
    reconstruire le JSON pour le comparer effacerait ce qu'on veut justement
    voir — une indentation qui change, des clés qui changent d'ordre. On
    remplace donc, là où elle est écrite, la valeur que porte la clé.
    """
    for v in volatils:
        if v.motif:
            texte = re.sub(v.motif, NEUTRE, texte)
        elif v.cle and donnees is not None:
            try:
                valeur = _valeur_au_chemin(donnees, v.cle)
            except KeyError:
                continue
            nom = v.cle.split(".")[-1]
            for ecrite in {json.dumps(valeur, ensure_ascii=False), json.dumps(valeur)}:
                texte = re.sub(
                    rf'("{re.escape(nom)}"\s*:\s*){re.escape(ecrite)}',
                    lambda m: m.group(1) + json.dumps(NEUTRE), texte)
    return texte


def neutraliser_donnees(donnees, volatils: list[Volatil]) -> None:
    for v in volatils:
        if not v.cle:
            continue
        try:
            _valeur_au_chemin(donnees, v.cle)
        except KeyError:
            continue
        _poser_au_chemin(donnees, v.cle, NEUTRE)


# ── Structure : ce qui explique un écart ─────────────────────────────────────

ABSENT = "<absent>"


def _liste_a_id(liste) -> bool:
    """Une liste d'objets qui portent tous un `id`, sans doublon."""
    if not isinstance(liste, list) or not liste:
        return False
    ids = []
    for objet in liste:
        if not isinstance(objet, dict) or "id" not in objet:
            return False
        if isinstance(objet["id"], (dict, list)) or objet["id"] is None:
            return False
        ids.append(objet["id"])
    return len(set(ids)) == len(ids)


def _meme_scalaire(a, b) -> bool:
    # `1 == 1.0` et `True == 1` en Python, mais pas dans le fichier écrit :
    # un entier devenu flottant est un changement de forme du JSON.
    return type(a) is type(b) and a == b


def comparer(a, b, chemin: str, rapport: dict) -> bool:
    """Vrai si `a` et `b` diffèrent. Les écarts s'ajoutent à `rapport`, dans
    l'ordre du document : `rapport["ecarts"][0]` est le premier chemin de clé
    qui diffère, `rapport["listes"]` les listes d'objets à `id`."""
    if isinstance(a, dict) and isinstance(b, dict):
        differe = False
        if list(a) != list(b) and set(a) == set(b):
            rapport["ecarts"].append({"chemin": chemin or ".", "nature": "ordre_des_cles",
                                      "ancien": list(a), "nouveau": list(b)})
            differe = True
        for cle in [*a, *(k for k in b if k not in a)]:
            sous = f"{chemin}.{cle}" if chemin else str(cle)
            if cle not in b:
                rapport["ecarts"].append({"chemin": sous, "ancien": a[cle], "nouveau": ABSENT})
                differe = True
            elif cle not in a:
                rapport["ecarts"].append({"chemin": sous, "ancien": ABSENT, "nouveau": b[cle]})
                differe = True
            elif comparer(a[cle], b[cle], sous, rapport):
                differe = True
        return differe

    if isinstance(a, list) and isinstance(b, list):
        if (_liste_a_id(a) or _liste_a_id(b)) and all(
                _liste_a_id(x) or x == [] for x in (a, b)):
            return _comparer_par_id(a, b, chemin, rapport)
        differe = False
        for i in range(min(len(a), len(b))):
            if comparer(a[i], b[i], f"{chemin}[{i}]", rapport):
                differe = True
        if len(a) != len(b):
            rapport["ecarts"].append({"chemin": chemin or ".", "nature": "longueur",
                                      "ancien": len(a), "nouveau": len(b)})
            differe = True
        return differe

    if isinstance(a, (dict, list)) or isinstance(b, (dict, list)) or not _meme_scalaire(a, b):
        rapport["ecarts"].append({"chemin": chemin or ".", "ancien": a, "nouveau": b})
        return True
    return False


def _comparer_par_id(a: list, b: list, chemin: str, rapport: dict) -> bool:
    par_a = {o["id"]: o for o in a}
    par_b = {o["id"]: o for o in b}
    bloc = {
        "chemin": chemin or ".",
        "ajoutes": [i for i in par_b if i not in par_a],
        "retires": [i for i in par_a if i not in par_b],
        "modifies": [],
        # L'ordre de tri fait partie de la sortie : une liste dont les objets
        # sont les mêmes mais rangés autrement n'est PAS identique.
        "ordre_change": ([i for i in par_a if i in par_b]
                         != [i for i in par_b if i in par_a]),
    }
    for i, objet in par_a.items():
        if i not in par_b:
            continue
        interne = {"ecarts": [], "listes": []}
        if comparer(objet, par_b[i], f"{chemin}[id={i}]", interne):
            bloc["modifies"].append({"id": i, "ecarts": interne["ecarts"]})
            rapport["listes"] += interne["listes"]
    differe = bool(bloc["ajoutes"] or bloc["retires"] or bloc["modifies"]
                   or bloc["ordre_change"])
    if differe:
        rapport["listes"].append(bloc)
    return differe


def _premiere_ligne_differente(ancien: str, nouveau: str) -> dict:
    la, lb = ancien.split("\n"), nouveau.split("\n")
    for n, (x, y) in enumerate(zip(la, lb), start=1):
        if x != y:
            return {"ligne": n, "ancien": x, "nouveau": y}
    n = min(len(la), len(lb)) + 1
    return {"ligne": n,
            "ancien": la[n - 1] if len(la) >= n else ABSENT,
            "nouveau": lb[n - 1] if len(lb) >= n else ABSENT}


# ── Un fichier ───────────────────────────────────────────────────────────────

def _lire(chemin: Path) -> tuple[bytes, str | None]:
    brut = chemin.read_bytes()
    try:
        return brut, brut.decode("utf-8")
    except UnicodeDecodeError:
        return brut, None


def comparer_fichier(rel: str, ancien: Path, nouveau: Path) -> dict | None:
    """`None` si les deux fichiers sont identiques, volatils neutralisés ;
    sinon ce qui les sépare. La clé `neutralise` signale un fichier identique
    seulement APRÈS neutralisation."""
    brut_a, texte_a = _lire(ancien)
    brut_b, texte_b = _lire(nouveau)
    if brut_a == brut_b:
        return None
    if texte_a is None or texte_b is None:
        return {"fichier": rel, "nature": "binaire",
                "taille": {"ancien": len(brut_a), "nouveau": len(brut_b)}}

    volatils = volatils_de(rel)
    donnees_a = donnees_b = None
    est_json = rel.endswith(SUFFIXES_JSON)
    if est_json:
        try:
            donnees_a, donnees_b = json.loads(texte_a), json.loads(texte_b)
        except json.JSONDecodeError:
            est_json = False

    neutre_a = neutraliser_texte(texte_a, donnees_a, volatils)
    neutre_b = neutraliser_texte(texte_b, donnees_b, volatils)
    if neutre_a == neutre_b:
        return {"fichier": rel, "neutralise": True}

    if not est_json:
        return {"fichier": rel, "nature": "texte",
                "premier_ecart": _premiere_ligne_differente(neutre_a, neutre_b)}

    neutraliser_donnees(donnees_a, volatils)
    neutraliser_donnees(donnees_b, volatils)
    rapport = {"ecarts": [], "listes": []}
    if not comparer(donnees_a, donnees_b, "", rapport):
        # Les mêmes données, pas les mêmes octets : indentation, séparateurs,
        # échappement. Le lecteur du JSON ne verra rien, mais « pas un octet »
        # n'est pas tenu, et on le dit.
        return {"fichier": rel, "nature": "forme",
                "premier_ecart": _premiere_ligne_differente(neutre_a, neutre_b)}
    return {"fichier": rel, "nature": "json", **rapport}


# ── Deux répertoires ─────────────────────────────────────────────────────────

def comparer_snapshots(ancien: Path, nouveau: Path) -> dict:
    fa, fb = fichiers_de(ancien), fichiers_de(nouveau)
    modifies, neutralises = [], []
    communs = [rel for rel in fa if rel in fb]
    for rel in communs:
        ecart = comparer_fichier(rel, fa[rel], fb[rel])
        if ecart is None:
            continue
        if ecart.get("neutralise"):
            neutralises.append(rel)
        else:
            modifies.append(ecart)
    absents = [rel for rel in fa if rel not in fb]
    nouveaux = [rel for rel in fb if rel not in fa]
    return {
        "identiques": not (absents or nouveaux or modifies),
        "ancien": str(ancien),
        "nouveau": str(nouveau),
        "fichiers": {"ancien": len(fa), "nouveau": len(fb), "communs": len(communs),
                     "identiques": len(communs) - len(modifies)},
        "absents": absents,
        "nouveaux": nouveaux,
        "modifies": modifies,
        # Ceux qui ne sont identiques que parce qu'un champ volatil a été
        # neutralisé : les nommer permet de vérifier que la liste des volatils
        # ne couvre pas plus qu'elle ne dit.
        "identiques_apres_neutralisation": neutralises,
        "volatils": [v._asdict() for v in VOLATILS],
    }


# ── Rapport texte ────────────────────────────────────────────────────────────

def _court(valeur) -> str:
    texte = valeur if valeur in (ABSENT,) else json.dumps(valeur, ensure_ascii=False)
    return texte if len(texte) <= LARGEUR_VALEUR else texte[:LARGEUR_VALEUR - 1] + "…"


def _ligne_ecart(e: dict) -> str:
    nature = {"ordre_des_cles": " (ordre des clés)", "longueur": " (longueur)"}.get(
        e.get("nature"), "")
    return f"{e['chemin']}{nature} : {_court(e['ancien'])} → {_court(e['nouveau'])}"


def _exemples(valeurs: list) -> str:
    vus = ", ".join(str(v) for v in valeurs[:MAX_EXEMPLES])
    return vus + (", …" if len(valeurs) > MAX_EXEMPLES else "")


def lignes_du_rapport(r: dict) -> list[str]:
    f = r["fichiers"]
    lignes = [f"Ancien  : {r['ancien']} ({f['ancien']} fichiers)",
              f"Nouveau : {r['nouveau']} ({f['nouveau']} fichiers)", ""]
    for titre, noms in (("Fichiers absents du nouveau", r["absents"]),
                        ("Fichiers nouveaux", r["nouveaux"])):
        if noms:
            lignes.append(f"{titre} ({len(noms)}) :")
            lignes += [f"  {n}" for n in noms]
            lignes.append("")
    if r["modifies"]:
        lignes.append(f"Fichiers modifiés ({len(r['modifies'])}) :")
    for m in r["modifies"]:
        lignes.append(f"  {m['fichier']}")
        if m["nature"] == "binaire":
            t = m["taille"]
            lignes.append(f"    binaire : {t['ancien']} → {t['nouveau']} octets")
        elif m["nature"] in ("texte", "forme"):
            p = m["premier_ecart"]
            quoi = ("mêmes données, écrites autrement" if m["nature"] == "forme"
                    else "texte")
            lignes.append(f"    {quoi} — ligne {p['ligne']} : "
                          f"{_court(p['ancien'])} → {_court(p['nouveau'])}")
        else:
            for bloc in m["listes"]:
                lignes.append(
                    f"    {bloc['chemin']} : {len(bloc['ajoutes'])} ajouté(s), "
                    f"{len(bloc['retires'])} retiré(s), {len(bloc['modifies'])} modifié(s)"
                    + (", ordre changé" if bloc["ordre_change"] else ""))
                if bloc["ajoutes"]:
                    lignes.append(f"      ajoutés  : {_exemples(bloc['ajoutes'])}")
                if bloc["retires"]:
                    lignes.append(f"      retirés  : {_exemples(bloc['retires'])}")
                for objet in bloc["modifies"][:MAX_EXEMPLES]:
                    if objet["ecarts"]:
                        lignes.append(f"      modifié  : {_ligne_ecart(objet['ecarts'][0])}")
                    else:
                        lignes.append(f"      modifié  : id={objet['id']} (dans une liste imbriquée)")
                if len(bloc["modifies"]) > MAX_EXEMPLES:
                    lignes.append("      …")
            if m["ecarts"]:
                reste = len(m["ecarts"]) - 1
                lignes.append(f"    premier écart : {_ligne_ecart(m['ecarts'][0])}"
                              + (f" (et {reste} autre(s))" if reste else ""))
    if r["modifies"]:
        lignes.append("")
    n = len(r["identiques_apres_neutralisation"])
    lignes.append(f"{f['identiques']} fichier(s) identique(s) sur {f['communs']} en commun"
                  + (f", dont {n} une fois les champs volatils neutralisés" if n else "") + ".")
    lignes.append("IDENTIQUES — aucun écart hors champs volatils." if r["identiques"]
                  else "DIFFÉRENTS.")
    return lignes


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare deux répertoires de snapshot public, fichier par fichier.")
    parser.add_argument("ancien", type=Path)
    parser.add_argument("nouveau", type=Path)
    parser.add_argument("--json", action="store_true",
                        help="le rapport complet en JSON, pas un résumé")
    args = parser.parse_args(argv)

    for d in (args.ancien, args.nouveau):
        if not d.is_dir():
            print(f"✖ répertoire introuvable : {d}", file=sys.stderr)
            return 2

    rapport = comparer_snapshots(args.ancien, args.nouveau)
    if args.json:
        print(json.dumps(rapport, ensure_ascii=False, indent=2))
    else:
        print("\n".join(lignes_du_rapport(rapport)))
    return 0 if rapport["identiques"] else 1


if __name__ == "__main__":
    sys.exit(main())
