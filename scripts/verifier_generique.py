#!/usr/bin/env python3
"""
verifier_generique.py — Le moteur ne doit connaître aucune commune.

Ce contrôle échoue si une particularité locale se trouve dans le code plutôt
que dans la configuration. Il est passé AVANT la fabrication du kit et devrait
l'être avant chaque commit sur le moteur.

Il ne cherche pas le nom d'une commune en particulier : chercher « Lasalle »
n'aurait attrapé aucun des trois défauts qui ont réellement corrompu la base de
la première commune portée —

    COMMUNE_ID = 63          un numéro de ligne de la base d'origine
    DB_PATH = … / "xxx.db"   une base nommée en dur
    "la commune est sous RNU" un fait sur une commune, écrit comme du code

Ce sont donc des FORMES qui sont interdites, pas des mots :

  1. un code INSEE, un code postal, un SIREN ou un SIRET littéral ;
  2. un identifiant d'entité en dur (`… _ID = 63`) ;
  3. une URL de site officiel (mairie, EPCI, préfecture) ;
  4. un nom de fichier de base de données ;
  5. le nom d'une commune de France de plus de 3 caractères, quand il apparaît
     dans une chaîne de caractères exécutée (pas dans un commentaire).

Le contrôle porte aussi sur les fichiers non-Python du moteur : le schéma de la
base, les sources du site public et celles de l'atelier. Pour ceux-là, seul le
point 5 s'applique.

Le point 5 demande une liste de communes ; à défaut de la charger (réseau), le
contrôle se rabat sur les communes déclarées dans la configuration locale et le
signale. Les quatre premiers points, eux, sont autonomes.

Usage :
  python3 scripts/verifier_generique.py            # tout le moteur
  python3 scripts/verifier_generique.py --json     # sortie machine
  python3 scripts/verifier_generique.py collectors/rna.py
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Le moteur : ce qui doit être générique. La configuration et les exemples en
# sont exclus — c'est justement là que le particulier a le droit de vivre.
MOTEUR = ["collectors", "scripts", "api.py", "api_auth.py"]
# Fichiers non-Python du moteur : le schéma de la base et les sources du site
# public et de l'atelier. Le schéma a porté `DEFAULT 'Lasalle'` pendant des
# mois, et le site nommait la commune 125 fois — les exclure du contrôle, c'est
# laisser la moitié du dispositif hors de sa portée.
TEXTES = [
    ("db/schema.sql", (".sql",)),
    ("public/src", (".svelte", ".js", ".html")),
    ("dashboard/src", (".svelte", ".js", ".html")),
]
TEXTES_EXCLUS = {"instance.js"}
EXCLUS_FICHIERS = {
    "config.py",                     # la configuration de l'instance
    "verifier_generique.py",         # ce fichier : il contient les motifs
    "init_instance.py",              # l'amorçage écrit la configuration
}
EXCLUS_DOSSIERS = {"__pycache__", "node_modules", ".git", "data", "db"}

# ── Motifs interdits ─────────────────────────────────────────────────────────

INTERDITS = [
    (
        "code_insee",
        re.compile(r"^(?:0[1-9]|[1-9]\d|9[0-5]|97|2[AB])\d{3}$"),
        "code INSEE littéral — doit venir de la configuration",
    ),
    (
        "siren_siret",
        re.compile(r"^\d{9}(?:\d{5})?$"),
        "SIREN/SIRET littéral — doit venir de la configuration",
    ),
    (
        "base_nommee",
        re.compile(r"\.db$"),
        "nom de base de données en dur — utiliser config.DB_PATH",
    ),
    (
        "site_officiel",
        re.compile(r"https?://(?:www\.)?[a-z0-9-]+\.(?:fr|com)/?", re.I),
        "URL d'un site — les sites officiels se déclarent dans la configuration",
    ),
]

# Domaines nationaux : ce sont des API, pas des sites de commune. Les nommer
# dans le code est légitime — c'est même le propre du moteur.
DOMAINES_NATIONAUX = re.compile(
    r"(?:^|//)(?:[a-z0-9-]+\.)*("
    r"gouv\.fr|data\.gouv\.fr|insee\.fr|opendatasoft\.com|datadila\.[a-z.]+|"
    r"api-adresse\.data\.gouv\.fr|geo\.api\.gouv\.fr|openstreetmap\.org|"
    r"overpass-api\.de|cerema\.fr|journal-officiel\.gouv\.fr|laregion\.fr|"
    r"economie\.gouv\.fr|ign\.fr|geopf\.fr|pappers\.fr|opendatacommons\.org|"
    r"github\.com|tesseract-ocr\.github\.io|creativecommons\.org|"
    r"etalab\.gouv\.fr|legifrance\.gouv\.fr|service-public\.fr|cnil\.fr|"
    # Portails nationaux de la commande publique, et vocabulaires normalisés
    # cités par le format de publication : ce ne sont pas des sites de commune.
    r"boamp\.fr|marches-publics\.gouv\.fr|popoloproject\.com|w3\.org|"
    r"schema\.org|opendefinition\.org"
    r")\b", re.I)

# `XXX_ID = 63` : un identifiant d'entité figé. Le seuil est bas exprès — un
# identifiant de ligne est petit, une constante métier légitime (année, seuil
# en euros, TTL) ne s'appelle pas `_ID`.
IDENTIFIANT_FIGE = re.compile(r"^[A-Z][A-Z0-9_]*_ID$")


def _fichiers(cibles: list[str]) -> list[Path]:
    out: list[Path] = []
    for cible in cibles:
        chemin = ROOT / cible
        if chemin.is_file():
            out.append(chemin)
        elif chemin.is_dir():
            out += [f for f in sorted(chemin.rglob("*.py"))
                    if not (set(f.parts) & EXCLUS_DOSSIERS)]
    return [f for f in out if f.name not in EXCLUS_FICHIERS]


def _docstrings(arbre: ast.AST) -> set[int]:
    """Identités des constantes qui sont des docstrings — elles documentent,
    elles ne s'exécutent pas. Un piège expliqué en commentaire ne doit pas être
    compté comme le piège lui-même."""
    ids = set()
    for noeud in ast.walk(arbre):
        corps = getattr(noeud, "body", None)
        if (isinstance(noeud, (ast.Module, ast.ClassDef, ast.FunctionDef,
                               ast.AsyncFunctionDef))
                and corps and isinstance(corps[0], ast.Expr)
                and isinstance(corps[0].value, ast.Constant)
                and isinstance(corps[0].value.value, str)):
            ids.add(id(corps[0].value))
    return ids


def analyser(fichier: Path, communes: set[str]) -> list[dict]:
    """Constats sur un fichier : liste de {ligne, motif, extrait}."""
    try:
        source = fichier.read_text(encoding="utf-8")
        arbre = ast.parse(source)
    except (UnicodeDecodeError, SyntaxError):
        return []

    docs = _docstrings(arbre)
    constats: list[dict] = []
    rel = str(fichier.relative_to(ROOT))

    for noeud in ast.walk(arbre):
        # 1-4 : formes interdites dans les chaînes exécutées
        if (isinstance(noeud, ast.Constant) and isinstance(noeud.value, str)
                and id(noeud) not in docs):
            valeur = noeud.value
            for nom, motif, explication in INTERDITS:
                if not motif.search(valeur):
                    continue
                if nom == "site_officiel" and DOMAINES_NATIONAUX.search(valeur):
                    continue
                constats.append({"fichier": rel, "ligne": noeud.lineno,
                                 "motif": nom, "explication": explication,
                                 "extrait": valeur[:80]})
            for commune in communes:
                if re.search(rf"\b{re.escape(commune)}\b", valeur, re.I):
                    constats.append({
                        "fichier": rel, "ligne": noeud.lineno,
                        "motif": "nom_commune",
                        "explication": f"« {commune} » nommée dans le code",
                        "extrait": valeur[:80]})
                    break

        # 5 : identifiant d'entité figé
        if isinstance(noeud, ast.Assign):
            for cible in noeud.targets:
                if (isinstance(cible, ast.Name)
                        and IDENTIFIANT_FIGE.match(cible.id)
                        and isinstance(noeud.value, ast.Constant)
                        and isinstance(noeud.value.value, int)):
                    constats.append({
                        "fichier": rel, "ligne": noeud.lineno,
                        "motif": "identifiant_fige",
                        "explication": (f"{cible.id} = {noeud.value.value} : un "
                                        "identifiant de ligne, valable dans une "
                                        "seule base — résoudre par le nom"),
                        "extrait": f"{cible.id} = {noeud.value.value}"})
    return constats


def analyser_texte(fichier: Path, communes: set[str]) -> list[dict]:
    """Contrôle d'un fichier non-Python : on ne cherche que les noms propres.

    Pas d'analyse syntaxique ici : ni SQL ni Svelte ne se prêtent au découpage
    fait sur Python, et les formes techniques (identifiants de lignes, chemins
    de base) n'y ont pas cours. Ce qui compte, c'est qu'aucune commune n'y soit
    nommée — le reste est du texte éditorial, et il vit dans instance.js.
    """
    try:
        lignes = fichier.read_text(encoding="utf-8").splitlines()
    except (UnicodeDecodeError, OSError):
        return []
    rel = str(fichier.relative_to(ROOT))
    constats = []
    for numero, ligne in enumerate(lignes, 1):
        nu = ligne.strip()
        if nu.startswith(("--", "//", "#", "*")):
            continue          # commentaire : il documente, il ne s'affiche pas
        for commune in communes:
            if re.search(rf"\b{re.escape(commune)}\b", ligne, re.I):
                constats.append({
                    "fichier": rel, "ligne": numero, "motif": "nom_commune",
                    "explication": f"« {commune} » nommée hors configuration",
                    "extrait": nu[:80]})
                break
    return constats


def _fichiers_texte() -> list[Path]:
    out = []
    for cible, suffixes in TEXTES:
        chemin = ROOT / cible
        if chemin.is_file():
            out.append(chemin)
        elif chemin.is_dir():
            out += [f for f in sorted(chemin.rglob("*"))
                    if f.is_file() and f.suffix in suffixes
                    and f.name not in TEXTES_EXCLUS
                    and not (set(f.parts) & EXCLUS_DOSSIERS)]
    return out


def communes_locales() -> set[str]:
    """Noms de communes déclarés par la configuration de l'instance, s'il y en a.

    Le contrôle vise le moteur : si la configuration nomme Brassac, alors
    « Brassac » n'a rien à faire ailleurs que dans la configuration.
    """
    try:
        sys.path.insert(0, str(ROOT))
        from collectors.config import COMMUNE_NAME, COMMUNES, EPCI_NOM
    except Exception:
        return set()
    noms = {COMMUNE_NAME} | {c["nom"] for c in COMMUNES.values()}
    noms |= {mot for mot in EPCI_NOM.split() if len(mot) > 4}
    return {n for n in noms if len(n) > 3}


def main() -> int:
    ap = argparse.ArgumentParser(description="Le moteur ne doit connaître aucune commune")
    ap.add_argument("cibles", nargs="*", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    communes = communes_locales()
    fichiers = _fichiers(args.cibles or MOTEUR)
    constats = [c for f in fichiers for c in analyser(f, communes)]
    textes = [] if args.cibles else _fichiers_texte()
    constats += [c for f in textes for c in analyser_texte(f, communes)]

    if args.json:
        print(json.dumps(constats, ensure_ascii=False, indent=2))
        return 1 if constats else 0

    print(f"[générique] {len(fichiers) + len(textes)} fichiers du moteur analysés"
          + (f", {len(communes)} noms de communes issus de la configuration"
             if communes else " — configuration illisible, contrôle des noms ignoré"))

    if not constats:
        print("\n✓ aucune particularité locale dans le moteur.")
        return 0

    par_motif: dict[str, list[dict]] = {}
    for c in constats:
        par_motif.setdefault(c["motif"], []).append(c)

    print(f"\n✖ {len(constats)} constat(s) — le moteur n'est pas générique :\n")
    for motif, liste in sorted(par_motif.items(), key=lambda kv: -len(kv[1])):
        print(f"  {motif} ({len(liste)}) — {liste[0]['explication']}")
        for c in liste[:8]:
            print(f"      {c['fichier']}:{c['ligne']}  {c['extrait']}")
        if len(liste) > 8:
            print(f"      … et {len(liste) - 8} autres")
        print()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
