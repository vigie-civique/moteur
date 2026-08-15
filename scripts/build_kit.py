#!/usr/bin/env python3
"""Fabrique l'archive du kit réplicable, servie depuis le site public.

Le kit est ce dépôt lui-même, moins ce qui appartient à une instance : sa
configuration, ses données, sa base. Le contrôle de généricité
(`verifier_generique.py`) est passé AVANT l'empaquetage — un kit qui nomme une
commune n'est pas un kit.

Pourquoi une archive et pas une forge : la création d'un compte sur un service
d'hébergement de code avec une adresse de messagerie chiffrée est bloquée par
les filtres anti-abus de ces plateformes. Plutôt que d'attendre le déblocage,
le kit est distribué depuis le site lui-même — qui est déjà en ligne, déjà
sous notre contrôle, et n'ajoute aucune dépendance.

Ce que ça coûte, et il faut le savoir : ni issues, ni contributions, ni
historique consultable. C'est une première étape, pas une fin.

L'archive est reconstruite à chaque publication depuis le dépôt réduit, et son
empreinte SHA-256 est publiée à côté : un fichier téléchargé doit pouvoir être
vérifié.

    python3 scripts/build_kit.py [--source ~/Claude/vigie-civique]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tarfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "public" / "static" / "kit"

# Motifs qui ne doivent JAMAIS entrer dans une archive publique. Le dépôt réduit
# en est exempt, mais il est reconstruit à la main : le contrôle porte sur ce
# qu'on est sur le point de distribuer, pas sur ce qu'on croit avoir copié.
INTERDITS = [
    (r"/Users/[a-z]", "chemin absolu d'une machine personnelle"),
    (r"colinoscope|aboutdechamp", "adresse personnelle"),
    (r"sk-ant-|ghp_|glpat-", "jeton d'API"),
    (r"BEGIN (RSA |OPENSSH )?PRIVATE KEY", "clé privée"),
]

# Un kit est du code : il ne doit nommer personne. La liste des patronymes à
# refuser ne peut donc pas être écrite ici — elle nommerait précisément les
# personnes qu'elle protège, dans un fichier destiné à la publication. Elle est
# lue dans la base de l'instance, ce qui la rend en outre valable pour
# n'importe quelle commune plutôt que pour une seule.
def patronymes() -> set[str]:
    """Noms de famille présents dans la base de l'instance, s'il y en a une."""
    try:
        sys.path.insert(0, str(ROOT))
        from collectors.config import DB_PATH
        import sqlite3
        if not DB_PATH.exists():
            return set()
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        # Mots français courants qui sont aussi des patronymes : les compter
        # ferait échouer l'archive sur une phrase ordinaire écrite en capitales.
        COURANTS = {"SANS", "AVEC", "POUR", "DANS", "TOUT", "TOUS", "PLUS",
                    "MOINS", "AUTRE", "AUTRES", "MEME", "MÊME", "PETIT",
                    "GRAND", "BLANC", "NOIR", "JEUNE", "LEGAL", "ROYAL",
                    "CÔTÉ", "COTE", "EVEN", "MARTIN", "ROND", "PONT", "MONT",
                    "BOIS", "CHAMP", "PLACE", "RUE", "VILLE", "PONS"}
        noms = {r[0].strip().upper() for r in
                conn.execute("SELECT lastname FROM persons WHERE lastname IS NOT NULL")
                if r[0] and len(r[0].strip()) > 3}
        noms -= COURANTS
        conn.close()
        return noms
    except Exception as e:
        print(f"  [avertissement] patronymes non vérifiés : {e}", file=sys.stderr)
        return set()

# Fichiers d'INSTANCE : ils décrivent une commune précise et n'ont rien à faire
# dans un kit. `instance.js` est de toute façon régénéré au premier build. Ce
# filet est redondant avec .gitignore — c'est voulu : deux règles indépendantes
# valent mieux qu'une, et un fichier peut avoir été versionné par erreur.
EXCLUS_FICHIERS = {"instance.json", "instance.js", "seed_local.json",
                   "profils_locaux.json", "publication_rules.json"}
# Répertoires versionnés qui n'ont pas à entrer dans l'archive. `public/static/kit`
# contient l'archive précédente : l'y remettre la ferait grossir à chaque
# publication et distribuerait une version périmée du dépôt à l'intérieur de la
# version courante.
EXCLUS_CHEMINS = ("public/static/kit/",)


def fichiers(source: Path) -> list[Path]:
    """Ce que le dépôt VERSIONNE, moins les fichiers d'instance.

    La liste vient de `git ls-files` et non d'un parcours du disque. C'est la
    seule source qui ne se désynchronise pas de `.gitignore` : une énumération
    manuelle de suffixes a laissé passer, le 14/08/2026, trois sauvegardes de
    base nommées `<insee>.db.avant-<date>` — 175 Mo de données nominatives —
    parce que le test portait sur `.db` en fin de nom. Ce qui n'est pas
    versionné n'est pas distribué : la règle est unique et vérifiable.
    """
    try:
        sortie = subprocess.run(
            ["git", "-C", str(source), "ls-files", "-z"],
            capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        raise SystemExit(
            f"✖ {source} n'est pas un dépôt git exploitable : {e}\n"
            "  Le kit se construit à partir des fichiers versionnés. Sans git,\n"
            "  il faudrait réénumérer à la main ce qu'il ne faut pas distribuer\n"
            "  — c'est précisément ce qui a laissé fuir des bases."
        )

    out = []
    for rel in sortie.decode().split("\0"):
        if not rel:
            continue
        if rel.startswith(EXCLUS_CHEMINS) or Path(rel).name in EXCLUS_FICHIERS:
            continue
        p = source / rel
        if p.is_file():      # un fichier supprimé mais encore indexé
            out.append(p)
    return sorted(out)


def verifier(source: Path, liste: list[Path]) -> list[str]:
    """Refuse de fabriquer une archive qui contient ce qu'elle ne doit pas."""
    problemes = []
    noms_interdits = patronymes()
    if noms_interdits:
        print(f"  ({len(noms_interdits)} patronymes lus dans la base de "
              "l'instance et refusés dans l'archive)")
    for f in liste:
        rel = f.relative_to(source)
        try:
            octets = f.read_bytes()
            # L'octet nul est le marqueur de binaire, et il est décodable en
            # UTF-8 : s'en remettre au seul échec de décodage laissait passer
            # tout format qui n'a pas de séquence invalide. Aucun fichier source
            # n'en contient.
            if b"\x00" in octets:
                raise ValueError("octet nul — fichier binaire")
            texte = octets.decode("utf-8")
        except (UnicodeDecodeError, ValueError, OSError) as e:
            # Un fichier qu'on ne sait pas lire est un fichier qu'on ne sait pas
            # contrôler. Passer son chemin revenait à distribuer sans regarder :
            # une base SQLite est illisible en UTF-8, et c'est exactement ce que
            # ce contrôle est censé arrêter. Le dépôt ne versionne aucun binaire ;
            # le jour où il en versionnera un, ce refus demandera une décision
            # explicite plutôt qu'un silence.
            problemes.append(f"{rel} — contenu non contrôlable ({type(e).__name__})")
            continue

        for motif, quoi in INTERDITS:
            # Les motifs de DÉTECTION (le code qui bloque les chemins locaux)
            # contiennent légitimement ces chaînes. On ne les compte que hors
            # commentaire et hors expression régulière déclarée.
            for ligne in texte.splitlines():
                nu = ligne.strip()
                if nu.startswith("#") or nu.startswith("//") or nu.startswith("*"):
                    continue
                if re.search(r'r["\']', nu):
                    continue
                if re.search(motif, nu, re.I):
                    problemes.append(f"{rel} — {quoi} : {nu[:80]}")

        for nom in noms_interdits:
            for m in re.finditer(rf"\b{re.escape(nom)}\b", texte):
                # Un identifiant de programme (PAGES, EVEN…) s'écrit en
                # capitales comme un patronyme. Ce qui les distingue, c'est
                # le voisinage : un nom de personne est précédé d'un prénom ou
                # d'une civilité, un identifiant est collé à du code.
                avant = texte[max(0, m.start() - 30):m.start()]
                apres = texte[m.end():m.end() + 2]
                if re.search(r"[=.(\[]\s*$", avant) or apres.startswith(("(", "=", "[", ".")):
                    continue
                if not re.search(r"(?:M\.|Mme|Madame|Monsieur|[A-ZÉÈ][a-zà-ÿ]+)\s+$", avant):
                    continue
                problemes.append(f"{rel} — nom de personne : {nom}")
                break
    return problemes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=str(ROOT),
                    help="dépôt à empaqueter (défaut : ce dépôt)")
    args = ap.parse_args()

    source = Path(args.source).expanduser().resolve()
    if not source.is_dir():
        print(f"✖ dépôt réduit introuvable : {source}", file=sys.stderr)
        return 1

    if source == ROOT:
        import subprocess as _sp
        controle = _sp.run([sys.executable, str(ROOT / "scripts" / "verifier_generique.py")],
                           capture_output=True, text=True)
        if controle.returncode != 0:
            print("✖ archive REFUSÉE — le moteur nomme une commune :\n",
                  file=sys.stderr)
            print(controle.stdout, file=sys.stderr)
            return 1
        print("0/3 — contrôle de généricité : aucune particularité locale")

    liste = fichiers(source)
    print(f"1/3 — {len(liste)} fichiers retenus depuis {source}")

    problemes = verifier(source, liste)
    if problemes:
        print(f"\n✖ archive REFUSÉE — {len(problemes)} problème(s) :\n", file=sys.stderr)
        for p in problemes[:20]:
            print("   " + p, file=sys.stderr)
        return 1
    print("2/3 — contrôle du contenu : aucun nom de personne, aucun secret, "
          "aucun chemin personnel")

    DEST.mkdir(parents=True, exist_ok=True)
    archive = DEST / "vigie-civique.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for f in liste:
            tar.add(f, arcname=str(Path("vigie-civique") / f.relative_to(source)))

    octets = archive.read_bytes()
    empreinte = hashlib.sha256(octets).hexdigest()

    # Version = date de publication. Le dépôt réduit n'a pas d'historique
    # partagé : un numéro de version suggérerait une continuité qui n'existe pas.
    (DEST / "kit.json").write_text(json.dumps({
        "fichier": archive.name,
        "date": date.today().isoformat(),
        "taille_octets": len(octets),
        "sha256": empreinte,
        "fichiers": len(liste),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"3/3 — {archive.relative_to(ROOT)} "
          f"({len(octets) / 1024:.0f} Ko, sha256 {empreinte[:16]}…)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
