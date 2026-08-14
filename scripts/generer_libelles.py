#!/usr/bin/env python3
"""
generer_libelles.py — Écrit `public/src/lib/instance.js` depuis l'instance.

Le site public nommait la commune 125 fois dans 39 fichiers : titres, chapeaux,
descriptions, courriel de contact, mentions légales. Aucun de ces textes n'est
du code, mais tous étaient dans le code.

Ce script les remplace par un module généré, importé partout. Il ne se contente
pas d'exposer le nom : il calcule les FORMES GRAMMATICALES, parce que « de
Lasalle » ne se dérive pas mécaniquement en « de Alès », ni « à Le Bez ».

    Brassac        → de Brassac,   à Brassac
    Alès           → d'Alès,       à Alès
    Le Bez         → du Bez,       au Bez
    Les Plantiers  → des Plantiers, aux Plantiers
    La Salvetat    → de La Salvetat, à La Salvetat

Le h muet n'étant pas devinable (« d'Hérépian » mais « de Hautefort »), une
instance peut imposer ses formes dans `config/instance.json` :

    "libelles": {"de": "d'Hérépian", "a": "à Hérépian", "gentile": "Hérépianais"}

Lancé automatiquement par `build_public_snapshot.py`. À relancer à la main
après avoir changé le nom public du site ou le courriel de contact :

    python3 scripts/generer_libelles.py
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTANCE = ROOT / "config" / "instance.json"
REGLES = ROOT / "config" / "publication_rules.json"
CIBLE = ROOT / "public" / "src" / "lib" / "instance.js"

VOYELLES = "aeiouyàâäéèêëîïôöûüÿ"


def _sans_accent(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def formes(nom: str) -> dict:
    """Formes « de … » et « à … » d'un nom de commune.

    L'article initial se contracte (Le Bez → du Bez, au Bez ; Les Plantiers →
    des Plantiers, aux Plantiers), sauf « La » qui ne se contracte pas. Un nom
    commençant par une voyelle élide le « de ».
    """
    nom = (nom or "").strip()
    if not nom:
        return {"de": "", "a": ""}

    if nom.startswith("Les "):
        reste = nom[4:]
        return {"de": f"des {reste}", "a": f"aux {reste}"}
    if nom.startswith("Le "):
        reste = nom[3:]
        return {"de": f"du {reste}", "a": f"au {reste}"}
    if nom.startswith(("La ", "L'", "L’")):
        return {"de": f"de {nom}", "a": f"à {nom}"}

    premiere = _sans_accent(nom[0]).lower()
    if premiere in VOYELLES:
        return {"de": f"d'{nom}", "a": f"à {nom}"}
    return {"de": f"de {nom}", "a": f"à {nom}"}


def sigle(nom: str) -> str:
    """Sigle d'un nom d'intercommunalité : « CC Sidobre Vals et Plateaux » → CCSVP.

    Sert aux endroits où le nom complet ne tient pas (fil d'ariane, colonnes de
    tableau). Une instance peut l'imposer par `libelles.epci_court`.
    """
    mots = [m for m in re.split(r"[\s'’-]+", nom or "") if m]
    if not mots:
        return ""
    if mots[0].upper() in ("CC", "CA", "CU", "CC.", "COMMUNAUTÉ", "COMMUNAUTE"):
        tete = mots[0].upper().rstrip(".")
        if tete.startswith("COMMUNAUT"):
            tete = "CC"
        suite = [m for m in mots[1:]
                 if m.lower() not in ("de", "des", "du", "d", "la", "le", "les",
                                      "et", "en", "communes", "agglomération",
                                      "agglomeration")]
        return tete + "".join(m[0].upper() for m in suite)
    return "".join(m[0].upper() for m in mots if len(m) > 2)


def construire() -> dict:
    if not INSTANCE.exists():
        raise SystemExit("config/instance.json absent — lancer init_instance.py")
    inst = json.loads(INSTANCE.read_text(encoding="utf-8"))
    regles = json.loads(REGLES.read_text(encoding="utf-8")) if REGLES.exists() else {}
    projet = regles.get("project", {})
    surcharge = inst.get("libelles", {})

    nom = inst["commune_nom"]
    f = formes(nom)
    epci = inst.get("epci_nom", "")
    editeur = inst.get("editeur", {})

    return {
        "COMMUNE": nom,
        "COMMUNE_DE": surcharge.get("de", f["de"]),
        "COMMUNE_A": surcharge.get("a", f["a"]),
        "GENTILE": surcharge.get("gentile", ""),
        "INSEE": inst["commune_insee"],
        "CODE_POSTAL": inst["code_postal"],
        "DEPARTEMENT": inst["departement"],
        "DEPARTEMENT_NOM": surcharge.get("departement_nom", ""),
        "EPCI": epci,
        "EPCI_COURT": surcharge.get("epci_court", sigle(epci)),
        # Le nombre d'autres communes : « la commune et les 15 autres communes
        # de l'intercommunalité » se lit partout sur le site.
        "EPCI_NB_COMMUNES": len(inst.get("communes", {})),
        "EPCI_NB_AUTRES": max(len(inst.get("communes", {})) - 1, 0),
        # Le nom public vient des règles de publication, SAUF si elles n'ont
        # pas suivi un changement de commune : un site qui titre du nom d'une
        # commune et affiche les chiffres d'une autre est pire qu'un site sans
        # titre. Dans ce cas on retombe sur un nom dérivé, et l'écart se voit.
        "SITE_NOM": (projet.get("public_name") or f"Vigie Civique {nom}")
                    if projet.get("commune", nom) == nom else f"Vigie Civique {nom}",
        "SITE_URL": inst.get("site_url", ""),
        "SITE_BASELINE": surcharge.get("baseline", f"{nom}, au clair"),
        "CONTACT_EMAIL": editeur.get("email", ""),
        "EDITEUR_NOM": editeur.get("nom", ""),
        "EDITEUR_STATUT": editeur.get("statut", ""),
        "HEBERGEUR": editeur.get("hebergeur", ""),
        "PREFECTURE": inst.get("prefecture_nom", ""),
    }


def ecrire(valeurs: dict) -> None:
    lignes = [
        "// Fichier GÉNÉRÉ par scripts/generer_libelles.py — ne pas éditer.",
        "//",
        "// Identité de l'instance : tout ce que le site doit dire de la commune",
        "// sans que le code le sache. Les formes grammaticales sont calculées :",
        "// un nom commençant par une voyelle élide le « de », un nom précédé",
        "// d'un article le contracte (« du », « des », « au », « aux »). Une",
        "// chaîne « de {COMMUNE} » écrite à la main finit toujours par produire",
        "// une faute d'accord sur la commune suivante.",
        "//",
        "// Régénérer :  python3 scripts/generer_libelles.py",
        "",
    ]
    for cle, valeur in valeurs.items():
        if isinstance(valeur, int):
            lignes.append(f"export const {cle} = {valeur}")
        else:
            echappe = str(valeur).replace("\\", "\\\\").replace("'", "\\'")
            lignes.append(f"export const {cle} = '{echappe}'")
    lignes += [
        "",
        "// Raccourci : « la commune de X » avec l'élision correcte.",
        "export const LA_COMMUNE = `la commune ${COMMUNE_DE}`",
        "",
        "// L'intercommunalité, nommée puis reprise en sigle.",
        "export const L_EPCI = EPCI || \"l'intercommunalité\"",
        "",
    ]
    CIBLE.parent.mkdir(parents=True, exist_ok=True)
    CIBLE.write_text("\n".join(lignes), encoding="utf-8")


def main() -> int:
    valeurs = construire()
    ecrire(valeurs)
    print(f"✓ {CIBLE.relative_to(ROOT)}")
    for cle in ("COMMUNE", "COMMUNE_DE", "COMMUNE_A", "EPCI", "EPCI_COURT",
                "SITE_NOM", "CONTACT_EMAIL"):
        print(f"    {cle:16} {valeurs[cle] or '— à renseigner dans instance.json'}")
    manquants = [c for c in ("CONTACT_EMAIL", "EDITEUR_NOM", "HEBERGEUR")
                 if not valeurs[c]]
    if manquants:
        print("\n  À renseigner dans config/instance.json, clé « editeur » "
              "(les mentions légales les affichent) :")
        for c in manquants:
            print(f"    - {c.lower()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
