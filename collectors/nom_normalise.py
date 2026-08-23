"""
nom_normalise.py — Forme normalisée d'un nom d'entité, source unique de vérité.

Pourquoi
--------
SIRENE renvoie tantôt « Frédéric VERGNAUD », tantôt « Frederic VERGNAUD » selon
l'enregistrement, le JO des associations tantôt « Club d'aïkido de Lasalle »
tantôt « CLUB D'AIKIDO DE LASALLE ». `upsert_entity` déduplique sur
`(type, name)` EXACT : chaque variante créait une fiche, et le graphe d'un même
acteur se retrouvait coupé en deux. 27 personnes concernées au 11/08/2026.

`entities.name_norm` stocke cette forme, et `db.upsert_entity` la renseigne à
l'insertion. Une colonne GÉNÉRÉE en SQL a été essayée puis abandonnée le
12/08/2026 : dépiler les accents en SQL demande une soixantaine de REPLACE
imbriqués, et SQLite refuse ensuite de relire son propre schéma — « malformed
database schema (entities) - parser stack overflow ». La base devenait
illisible depuis le client `sqlite3`.

Conséquence à connaître : les scripts qui écrivent dans `entities` SANS passer
par `upsert_entity` (imports ponctuels de `scripts/`) laissent `name_norm` vide.
Un recalcul groupé rattrape ce qui manque ; le pire
qu'une valeur absente puisse produire est un doublon, jamais une confusion.

Règle : minuscules, sans accents, tirets/apostrophes/points → espace, espaces
multiples réduits, extrémités élaguées.
"""
from __future__ import annotations

import re
import unicodedata

# Caractères remplacés par un espace : ce sont des variantes de saisie, pas du
# sens. « Jean-Michel » et « Jean Michel », « L'ART SCENE. » et « L'ART SCÈNE »
# désignent la même chose.
# Les guillemets ont été ajoutés le 22/08/2026 : le RNA publie 25 titres
# d'associations entre guillemets — « "AMIS DE LA BIBLIOTHEQUE DE LASALLE" » —
# et `"amis de la bibliotheque"` ne rejoignait pas `amis de la bibliotheque`.
# Deux fiches pour une association.
SEPARATEURS = "-'’.,\"«»“”"

LIGATURES = {"Œ": "OE", "œ": "oe", "Æ": "AE", "æ": "ae"}


def sans_accents(texte: str | None) -> str:
    """Accents dépliés, ligatures défaites. La casse et la ponctuation restent."""
    s = unicodedata.normalize("NFD", texte or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    for lig, remp in LIGATURES.items():
        s = s.replace(lig, remp)
    return s


def normaliser(nom: str | None) -> str:
    """Forme normalisée d'un nom, utilisée pour retrouver une entité déjà en base."""
    s = sans_accents(nom)
    for ch in SEPARATEURS:
        s = s.replace(ch, " ")
    return " ".join(s.lower().split())


# ─── Libellé affichable ────────────────────────────────────────────────────────

# `normaliser` fabrique une CLÉ : elle écrase tout, et ce qu'elle rend n'est
# montrable à personne. `nettoyer_libelle` fabrique un NOM : il reste lisible,
# et seule la ponctuation de saisie de la source disparaît. Les deux existent
# parce qu'on a besoin des deux, et confondre les deux, c'est publier
# « amis de la bibliotheque de lasalle » sur une page de commune.

_GUILLEMETS = '"«»“”'

# « L' Estréchure », « rue de l' Église » : le RNA sépare l'élision de son mot.
# L'apostrophe est rendue telle qu'elle a été écrite — droite ou courbe : ce
# n'est pas une faute de saisie, et « Les Douceurs d’Emy » est le nom que le
# commerce s'est donné.
_ELISION = re.compile(r"\b(\w{1,2}['’])\s+")

# Un point ou une virgule collés au mot précédent, jamais l'inverse.
_PONCTUATION_ESPACEE = re.compile(r"\s+([,.])")


def _ossature(nom: str) -> str:
    """Forme normalisée sans ses espaces — sert à reconnaître une répétition
    quand les deux moitiés ne sont pas écrites pareil."""
    return normaliser(nom).replace(" ", "")


def _deplier_repetition(nom: str) -> str:
    """« X X » → « X ». Un nom qui est deux fois le même nom est un nom.

    Relevé en base le 22/08/2026 (entité 8209) :
    « "APE INTERCOMMUNALE" APE PONT-D'HERAULT "APE INTERCOMMUNALE" APE
    PONT-DHERAULT » — la source a concaténé deux graphies du même titre, qui
    ne diffèrent que par une apostrophe. La comparaison porte donc sur
    l'ossature, pas sur les mots : sinon les deux moitiés ne se reconnaissent
    pas entre elles.
    """
    mots = nom.split()
    if len(mots) < 4 or len(mots) % 2:
        return nom
    milieu = len(mots) // 2
    gauche, droite = " ".join(mots[:milieu]), " ".join(mots[milieu:])
    if _ossature(gauche) and _ossature(gauche) == _ossature(droite):
        return gauche
    return nom


def _elaguer_point_final(nom: str) -> str:
    """Retire le point final — sauf celui d'un sigle.

    280 titres du RNA finissent par un point (« A MAIN NUE. »), et
    « A.A.P.P.M.A. » finit par un point qui lui appartient. Ce qui les sépare :
    ce qui précède le dernier point est un mot, ou une seule lettre.
    """
    while nom.endswith("."):
        # Points de suspension : ils font partie du nom, et « EN ATTENDANT... »
        # amputé de ses points ne s'appelle plus comme ça.
        if nom.endswith(".."):
            break
        radical = nom[:-1].rstrip()
        if not radical:
            return ""
        # Une lettre seule précédée d'un point est la dernière d'un sigle, et
        # le point qui la suit lui appartient. Une parenthèse fermante, elle,
        # ne retient rien : « (A.C.L.G.). » perd bien son point final.
        if radical[-1].isalpha() and (len(radical) < 2 or radical[-2] == "."):
            break
        nom = radical
    return nom


def nettoyer_libelle(nom: str | None) -> str:
    """Nom ou adresse tels qu'on peut les afficher : la ponctuation de saisie
    de la source retirée, les mots intacts.

    Ce qui est retiré : guillemets, point final surnuméraire, espaces
    multiples, élision décollée de son mot, répétition du nom entier.

    Ce qui n'est PAS touché, et c'est délibéré : la CASSE. 599 des 721 titres
    d'associations sont tout en capitales parce que le RNA les publie ainsi.
    Les remettre en bas de casse demanderait de reconnaître les sigles —
    ACVEN, 4L, A.A.P.P.M.A. — et un sigle abîmé n'est plus le nom de personne.
    Un nom qui crie vaut mieux qu'un nom faux.
    """
    s = nom or ""
    for guillemet in _GUILLEMETS:
        s = s.replace(guillemet, " ")
    s = _ELISION.sub(r"\1", s)
    s = _PONCTUATION_ESPACEE.sub(r"\1", s)
    s = " ".join(s.split())
    s = _deplier_repetition(s)
    return _elaguer_point_final(s).strip()


def rectifier(texte: str | None) -> str | None:
    """Applique les rectifications déclarées de l'instance (`config/instance.json`).

    « place Louuis Léonard » → « place Louis Léonard ». Ce n'est pas une
    graphie de la source, c'est une lettre doublée au clavier, et la corriger
    n'invente rien. Ce qui l'inventerait, ce serait une règle : « uu se lit u »
    abîmerait « continuum » ou un patronyme flamand. D'où une LISTE, où chaque
    entrée est datée, motivée, et lisible par quelqu'un d'autre que son auteur.

    Deux formes sont reconnues : la source telle qu'elle est écrite dans la
    liste, et sa variante en capitales sans accents — SIRENE livre ses adresses
    ainsi, et une rectification qui ne vaudrait que pour une casse laisserait
    la moitié des fiches fautives. Une source qui s'écrirait encore autrement
    demande sa propre entrée : mieux vaut une liste explicite un peu plus
    longue qu'une correspondance approximative qui attrape ce qu'on ne lui a
    pas demandé.
    """
    if not texte:
        return texte
    from .config import RECTIFICATIONS
    for r in RECTIFICATIONS:
        source, lecture = r.get("source"), r.get("lecture")
        if not source or lecture is None:
            continue
        texte = texte.replace(source, lecture)
        # SIRENE écrit ses adresses en capitales SANS accents : la variante ne
        # se déduit pas d'un simple .upper(), « LÉONARD » n'y figure jamais.
        texte = texte.replace(sans_accents(source).upper(),
                              sans_accents(lecture).upper())
    return texte


# ── Encodage abîmé par la source ─────────────────────────────────────────────
#
# « L'EUZIAÃÂRE » s'affichait tel quel sur le site public le 23/08/2026, dans le
# fil d'accueil. Le défaut n'est pas dans le collecteur : le CSV brut de Sitadel
# archivé sous `data/raw/sitadel/` contient DÉJÀ les octets
# `C3 83 C2 82 C3 82 C2 88`, et c'est de l'UTF-8 parfaitement valide. C'est le
# CONTENU qui est du mojibake, livré ainsi par DIDO.
#
# Deux dégâts distincts, deux réparations :
#
# 1. Le double encodage ordinaire — « MickaÃ«l », « prononÃ§ant » — où de l'UTF-8
#    a été relu comme du latin-1, une ou deux fois. Il se défait exactement : les
#    octets sont tous là, dans l'ordre. Ce n'est pas une interprétation.
#
# 2. Le repli Sitadel, plus abîmé : l'octet de tête `C3` a en plus été rabattu
#    sur « A » par un dépilage d'accents en amont, et seul l'octet de queue a
#    survécu, en caractère de contrôle. « NAÎMES » pour « NÎMES »,
#    « TRAÈVES » pour « TRÈVES », « L'EUZIAÈRE » pour « L'EUZIÈRE ». La
#    reconstruction est déterministe — `C3` est le seul octet de tête qui rende
#    une lettre — et vérifiable : le même fichier écrit ailleurs « EUZIERE
#    VIEILLE » et « NIMES » en clair.
#
# Ce que ces fonctions ne font PAS : deviner. Un texte sans motif de mojibake en
# ressort identique, et une séquence qui ne se décode pas est laissée telle
# quelle plutôt que remplacée par un caractère de remplacement. Réparer à
# l'affichage seulement aurait laissé le défaut dans les exports, dans la
# recherche plein texte et dans les fiches d'entités — c'est pour ça que la
# réparation est ici, au point d'écriture, et pas dans une feuille de style.

# Une séquence de mojibake latin-1 : un octet de tête UTF-8 (C2/C3) devenu
# caractère, suivi de sa continuation.
# Les octets de continuation, tels qu'ils ressortent d'une relecture fautive.
# Latin-1 les rend en caractères de contrôle ; cp1252 range à la place 27
# symboles de typographie — c'est d'ailleurs à ça qu'on reconnaît « â€™ »,
# l'apostrophe courbe passée par Windows.
_CONT = ("\x80-\xbf"
         "\u20ac\u201a\u0192\u201e\u2026\u2020\u2021\u02c6\u2030\u0160"
         "\u2039\u0152\u017d\u2018\u2019\u201c\u201d\u2022\u2013\u2014"
         "\u02dc\u2122\u0161\u203a\u0153\u017e\u0178")
# Deux têtes seulement, et c'est ce qui évite les faux positifs : « Â » et « Ã »
# ne précèdent jamais un symbole en français (ÂGE, ÂNE, CHÂTEAU sont suivis
# d'une lettre), tandis que « É… » ou « À » suivis d'une ponctuation seraient du
# texte correct — une classe de tête large aurait cassé « CAFÉ… ».
# « â » ouvre les caractères à trois octets (ponctuation générale) : on en exige
# DEUX de suite, sans quoi « château » suffirait à déclencher la règle.
_MOJIBAKE_SEQ = re.compile(
    f"(?:[\xc2\xc3][{_CONT}]|\xe2[{_CONT}]{{2}})+")
# Le repli Sitadel : « A » (ce que devient « Ã » dépilé) suivi de l'octet de
# queue resté en contrôle C1. \x97 est écarté : il rendrait « × », pas une
# lettre. Seules les capitales sont traitées — Sitadel n'écrit qu'en capitales,
# et « a » suivi d'un contrôle n'a jamais été observé.
_REPLI_TETE = re.compile("A([\x80-\x96\x98-\x9f])")


def _defaire_une_couche(texte: str) -> str:
    def _decoder(m: re.Match) -> str:
        # cp1252 d'abord : c'est l'encodage par lequel passent la plupart des
        # chaînes de publication françaises, et le seul qui sache remettre « € »
        # sur l'octet 0x80. latin-1 ensuite, pour les octets que cp1252 n'a pas.
        for codec in ("cp1252", "latin-1"):
            try:
                return m.group().encode(codec).decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
        return m.group()
    return _MOJIBAKE_SEQ.sub(_decoder, texte)


def reparer_encodage(texte: str | None) -> str | None:
    """Défait le mojibake livré par une source, sans rien deviner.

    Trois couches au maximum : le corpus n'en a jamais montré plus de deux, et
    une borne évite qu'un texte pathologique fasse tourner la boucle.
    """
    if not texte or not _MOJIBAKE_SEQ.search(texte):
        return texte
    for _ in range(3):
        suivant = _defaire_une_couche(texte)
        if suivant == texte:
            break
        texte = suivant
    return _REPLI_TETE.sub(
        lambda m: bytes([0xC3, ord(m.group(1))]).decode("utf-8"), texte)


def porte_du_mojibake(texte: str | None) -> bool:
    """Vrai si le texte porte encore une signature d'encodage abîmé.

    Sert au contrôle du snapshot : ce qui a échappé à la réparation ne part pas
    en ligne sans que quelqu'un l'ait vu. Le critère est une SÉQUENCE, jamais un
    caractère isolé : « CHÂTEAU », « THÉÂTRE » et « Âne » sont du français
    correct, et une règle qui bloquerait sur « Â » seul refuserait de publier la
    moitié des lieux-dits du Gard.
    """
    if not texte:
        return False
    return bool(_MOJIBAKE_SEQ.search(texte) or _REPLI_TETE.search(texte)
                or "�" in texte)
