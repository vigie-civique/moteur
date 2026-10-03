"""lacunes.py — ce que le dispositif ne sait pas, sous une forme qu'on peut traiter.

Un dossier thématique dit ce qu'il ignore à deux endroits, et aucun des deux
n'était lisible par une machine :

  - la section « Ce qu'on ne sait pas », un tableau
    `| Question | Où on en est | Comment le savoir |` dont la deuxième colonne
    commence par un état en gras (`**ouvert**`, `**en partie**`…) ;
  - les citations d'actes qui ne mènent à rien (`collectors/citations.py`) :
    « (CM du 06/03/2023) » quand aucun acte de ce jour n'est publié. Une
    citation sans cible n'est pas une erreur de mise en forme, c'est une
    question — quel acte, et pourquoi n'est-il pas là ?

Les deux sortent ici sous un MÊME format, pour qu'une file de travail les
reprenne sans savoir d'où elles viennent :

    id            dossier + empreinte de la question normalisée
    dossier       le slug
    nature        question | citation
    question      la question telle qu'écrite (ou, pour une citation, posée)
    etat          ouvert | en_partie | … (la clé) ; etat_libelle (le mot écrit)
    ou_on_en_est  ce qui est déjà su
    comment       le moyen de la combler
    section, ancre

⚖️ L'identifiant survit à une retouche de ponctuation, de casse ou d'accent —
une virgule ajoutée ne doit pas fermer une tâche et en ouvrir une autre — et
ne survit pas à une AUTRE question. On compare donc la question réduite à ses
lettres et ses chiffres ; on ne cherche pas à reconnaître une question
reformulée : deviner qu'elle est « la même » relierait l'historique d'une
question à une autre.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

from .citations import ancre

#: L'ancre de la section, quel que soit l'apostrophe (droite ou courbe).
SECTION = "ce-qu-on-ne-sait-pas"


def normaliser(texte: str) -> str:
    """Ce qui fait l'identité d'une question : ses mots, rien d'autre."""
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", texte or "")
    t = "".join(c for c in unicodedata.normalize("NFD", t) if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9]+", " ", t.lower())
    return " ".join(t.split())


def identifiant(dossier: str, nature: str, texte: str) -> str:
    """`eau:q-1a2b3c4d5e` — stable tant que la question l'est."""
    h = hashlib.sha256(normaliser(texte).encode()).hexdigest()[:10]
    return f"{dossier}:{nature[0]}-{h}"


def _cellules(ligne: str) -> list[str]:
    morceaux = re.split(r"(?<!\\)\|", ligne.strip())
    if morceaux and not morceaux[0].strip():
        morceaux = morceaux[1:]
    if morceaux and not morceaux[-1].strip():
        morceaux = morceaux[:-1]
    return [m.strip().replace("\\|", "|") for m in morceaux]


def _sans_markdown(t: str) -> str:
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t or "")
    return re.sub(r"\*\*|__|`", "", t).strip()


def _etat(cellule: str) -> tuple[str | None, str | None, str]:
    """« **en partie** : dates connues » → ('en_partie', 'en partie', 'dates connues')."""
    m = re.match(r"^\*\*(.+?)\*\*\s*[:—–-]?\s*(.*)$", cellule or "")
    if not m:
        return None, None, _sans_markdown(cellule)
    libelle = m.group(1).strip().rstrip(":").strip()
    cle = normaliser(libelle).replace(" ", "_") or None
    return cle, libelle, _sans_markdown(m.group(2))


def questions(slug: str, texte: str) -> list[dict]:
    """Les lignes du tableau « Ce qu'on ne sait pas » d'un dossier.

    La première ligne du tableau est son en-tête, la deuxième son séparateur :
    ni l'une ni l'autre n'est une question. Un tableau absent rend [] — un
    dossier qui n'a pas (encore) cette section ne déclare aucune lacune, ce qui
    n'est pas la même chose que n'en avoir aucune ; c'est l'atelier qui le dit.
    """
    sortie, section, dans, vues = [], None, False, set()
    lignes_tableau = 0
    for ligne in texte.split("\n"):
        if h := re.match(r"^##\s+(.+?)\s*#*\s*$", ligne):
            section = h.group(1)
            dans = ancre(section).startswith(SECTION)
            lignes_tableau = 0
            continue
        if not dans or not ligne.lstrip().startswith("|"):
            if dans and ligne.strip() and lignes_tableau:
                lignes_tableau = 0      # un paragraphe ferme le tableau
            continue
        lignes_tableau += 1
        if lignes_tableau <= 2:         # en-tête, puis séparateur
            continue
        c = _cellules(ligne)
        if len(c) < 2 or not _sans_markdown(c[0]):
            continue
        question = _sans_markdown(c[0])
        cle, libelle, detail = _etat(c[1])
        lid = identifiant(slug, "question", question)
        if lid in vues:
            continue
        vues.add(lid)
        sortie.append({
            "id": lid, "dossier": slug, "nature": "question",
            # Telle que l'auteur l'a écrite : souvent un intitulé (« Le contrat
            # du syndicat avec Veolia »), pas une phrase interrogative. C'est la
            # file de travail qui la tourne en question, pas l'export.
            "question": question,
            "etat": cle or "non_dit", "etat_libelle": libelle,
            "ou_on_en_est": detail,
            "comment": _sans_markdown(c[2]) if len(c) > 2 else "",
            "section": section, "ancre": ancre(section),
        })
    return sortie


def citations(slug: str, non_resolues) -> list[dict]:
    """Une lacune par citation sans cible. `non_resolues` : les `Citation` du
    résolveur. Deux fois « CM du 06/03/2023 » dans la même partie, c'est une
    seule question."""
    sortie, vues = [], set()
    for c in non_resolues:
        lid = identifiant(slug, "citation", f"{c.texte} {c.objet} {c.section or ''}")
        if lid in vues:
            continue
        vues.add(lid)
        r = c.resolution
        sortie.append({
            "id": lid, "dossier": slug, "nature": "citation",
            "question": (f"À quel acte renvoie la ligne « {c.texte} — {c.objet} » de la frise ?"
                         if c.objet else f"À quel acte renvoie « {c.texte} » ?"),
            "etat": "ouvert", "etat_libelle": "ouvert",
            "ou_on_en_est": r.raison,
            "comment": ("choisir l'acte parmi les candidats" if r.candidats
                        else "retrouver l'acte (registre, procès-verbal), puis le "
                             "citer par sa clé : [texte](acte:c-AAAA-N)"),
            "section": c.section, "ancre": ancre(c.section) if c.section else None,
            "citation": {"texte": c.texte, "forme": c.forme, "ligne": c.ligne,
                         "candidats": r.candidats},
        })
    return sortie
