"""Lire une convocation : la séance qu'elle annonce, jamais des délibérations.

Une convocation dit QUAND une assemblée se réunit, OÙ, et pour délibérer de
QUOI. Elle ne rapporte aucune décision. Lue jusqu'au 01/10/2026 comme un
procès-verbal, elle fabriquait des « délibérations » avec ses lignes en
capitales — « MERCREDI 23 SEPTEMBRE 2026 », « A LA SALLE DES FETES » : 13 fiches
sur 6 séances de la CC de Lasalle. Et parce que les métadonnées d'une séance
FUSIONNENT pièce après pièce, une convocation lue après le procès-verbal
écrasait ce que celui-ci avait établi : quatre séances annonçaient « 2
délibérations » et aucun présent.

Ce qu'on en garde est ce qu'elle seule donne avant la séance, et qui manquait
au site : l'ordre du jour, l'heure, le lieu, la date d'envoi. C'est ce qui
permet d'annoncer un conseil, ce que lasalle.fr ne fait pas.

Lecture tolérante : ces pièces sont des scans océrisés. Les numéros des points
sautent, le pied de page s'intercale au milieu de la liste, des mots isolés
traînent. Les points sont donc découpés sur ce qui survit à l'OCR — le « ; »
qui clôt chacun d'eux —, pas sur leur numéro.
"""
from __future__ import annotations

import re
import unicodedata

# Une pièce nommée « convocation » qui porte des formules de vote est mal
# nommée : c'est un registre ou un procès-verbal, il se lit comme tel.
FORMULES_DE_VOTE = re.compile(
    r"apr[eè]s en avoir d[ée]lib[ée]r|voix pour|\bADOPT[ÉE]E?S?\b", re.I)

_MOIS = {"janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
         "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11,
         "decembre": 12}

# « Ordre du jour : », et ce que l'OCR en fait parfois (« Orddu jrouer : »).
_DEBUT_ODJ = re.compile(r"(?im)^\s*(?:ordre\s+du\s+jour|or\w*\s*d\w*\s+j\w{2,5})\s*:")
_PREMIER_POINT = re.compile(r"(?m)^\s*1\s*[.,)]\s+\S")
_FIN_ODJ = re.compile(r"veuillez\s+agr[ée]er|je\s+vous\s+prie|dans\s+l'attente|"
                      r"comptant\s+sur|salutations|^\s*le\s+pr[ée]sident\b", re.I | re.M)
_ANNONCE = re.compile(r"aura\s+lieu\s+le|se\s+r[ée]unira\s+le|est\s+convoqu[ée]", re.I)
# Le pied de page d'un courrier : adresse, téléphone, courriel, raison sociale.
# La raison sociale peut être précédée d'un débris d'OCR (« ERWEUNNOHL
# Communauté de Communes … - Terres Solidaires ») ; un point de l'ordre du jour
# qui CITE la communauté de communes, lui, ne commence pas par elle.
_PIED = re.compile(r"t[ée]l\s*[.:]|@|\b\d{5}\b|\bavenue\b|\brue\b|"
                   r"^\s*(?:\S+\s+)?communaut[ée] de communes\b.*[-–]", re.I)
# « A9H30 », « A9H 30 », « A14H » : la lettre collée au chiffre interdit \b.
_HEURE = re.compile(r"(?<!\d)(\d{1,2})\s*[hH]\s*(\d{2})?(?!\d)")
# Un numéro de point, ou ce qu'il en reste (« . Tarification… »).
_NUMERO = re.compile(r"^\s*(?:\d{1,2}\s*[.,)]|[.,])\s*")
_MOT = re.compile(r"\b(?:[A-ZÀ-Ý][a-zà-ÿ]{3,}|[a-zà-ÿ]{4,})\b")
_PETITS_MOTS = {"de", "du", "des", "la", "le", "les", "et", "au", "aux", "en", "sur", "sous"}


def est_convocation(nature: str, texte: str) -> bool:
    return nature == "convocation" and not FORMULES_DE_VOTE.search(texte or "")


def _sans_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _bruit(ligne: str) -> bool:
    """Un débris d'OCR : un mot isolé en capitales, une ponctuation seule."""
    l = ligne.strip()
    if len(l) <= 3:
        return True
    return " " not in l and len(l) <= 5 and not re.search(r"[a-zà-ÿ]", l)


def date_d_envoi(texte: str) -> str | None:
    """« L'Espérou, le 15 septembre 2026. » → « 2026-09-15 ». Lue AVANT
    l'annonce de la séance, sans quoi on lirait la date de la séance."""
    fin = _ANNONCE.search(texte)
    tete = _sans_accents(texte[: fin.start() if fin else 1500]).lower()
    m = re.search(r"\ble\s+(\d{1,2})(?:er)?\s+([a-z]+)\s+(20\d\d)\b", tete)
    if not m or m.group(2) not in _MOIS:
        return None
    return f"{m.group(3)}-{_MOIS[m.group(2)]:02d}-{int(m.group(1)):02d}"


def _lieu(segments: list[str]) -> str | None:
    """« A SAUMANE », « A LA SALLE DES FETES » → « Saumane, la salle des fetes »."""
    propres = []
    for s in segments:
        s = re.sub(r"^\s*(?:A|À|AU|AUX)\s+", lambda m: "" if m.group(0).strip() in ("A", "À")
                   else m.group(0).strip().lower() + " ", s.strip())
        s = _HEURE.sub("", s).strip(" ,.-–")
        if not s or _PIED.search(s) or _bruit(s):
            continue
        if not propres:      # le premier segment est un lieu-dit : il garde ses capitales
            mots = s.lower().split()
            s = " ".join(m if i and m in _PETITS_MOTS else
                         "-".join(p[:1].upper() + p[1:] for p in m.split("-"))
                         for i, m in enumerate(mots))
            s = re.sub(r"\b([LlDd])'(\w)", lambda m: m.group(1).upper() + "'" + m.group(2).upper(), s)
        else:
            s = s.lower()
        propres.append(s)
    return ", ".join(propres) or None


def ordre_du_jour(texte: str) -> list[str]:
    """Les points de l'ordre du jour, dans l'ordre, débarrassés des débris."""
    m = _DEBUT_ODJ.search(texte)
    if m:
        corps = texte[m.end():]
    else:
        p = _PREMIER_POINT.search(texte)
        if not p:
            return []
        corps = texte[p.start():]
    f = _FIN_ODJ.search(corps)
    if f:
        corps = corps[: f.start()]
    # Ligne à ligne : un point COMMENCE par un numéro (ou son débris) et FINIT
    # sur « ; », « . » ou « : » en fin de ligne. Entre les deux, les lignes se
    # recollent — un intitulé long tient sur deux ou trois lignes.
    points, courant = [], []

    def clore():
        p = re.sub(r"\s+", " ", " ".join(courant)).strip(" .;:")
        # Un point lisible a au moins un vrai mot — « Taxe », « Pays »,
        # « création ». « RTUGIES u mmu » n'en a aucun : l'OCR n'a pas su lire.
        if len(p) >= 4 and _MOT.search(p):
            points.append(p)
        courant.clear()

    for ligne in corps.splitlines():
        # « extérieur;s » : un « ; » peut tomber au milieu d'une ligne océrisée.
        morceaux = ligne.split(";")
        for i, m in enumerate(morceaux):
            m = m.strip()
            if not m or _PIED.search(m) or _bruit(m):
                if i < len(morceaux) - 1 and courant:
                    clore()
                continue
            if _NUMERO.match(m) and courant:
                clore()
            courant.append(_NUMERO.sub("", m))
            if i < len(morceaux) - 1 or m.endswith((".", ":")):
                clore()
    if courant:
        clore()
    return points


def lire(texte: str) -> dict:
    """Ce qu'une convocation annonce. Chaque clé est absente si elle n'a pas
    pu être lue : rien n'est deviné."""
    sortie: dict = {}
    if (envoi := date_d_envoi(texte)):
        sortie["convoque_le"] = envoi
    a = _ANNONCE.search(texte)
    if a:
        apres = texte[a.end():]
        fin = _DEBUT_ODJ.search(apres) or _PREMIER_POINT.search(apres)
        annonce = [l for l in apres[: fin.start() if fin else 400].splitlines() if l.strip()]
        # La première ligne est la date de séance, déjà connue par ailleurs.
        annonce = [l for l in annonce if not re.search(r"\b20\d\d\b", l) and l.strip() != ":"]
        h = next((_HEURE.search(l) for l in annonce if _HEURE.search(l)), None)
        if h:
            sortie["heure"] = f"{int(h.group(1))} h" + (f" {h.group(2)}" if h.group(2) else "")
        if (lieu := _lieu(annonce)):
            sortie["lieu"] = lieu
    if (points := ordre_du_jour(texte)):
        sortie["ordre_du_jour"] = points
    return sortie
