"""Les textes qui sortent : libellés présentables, personnes masquées.

Deux familles, qui servent à plusieurs étapes du snapshot :

- la PRÉSENTATION des libellés — un nom de registre en capitales, un intitulé
  de flux, un titre d'acte préfixé — qui ne change rien à ce qui est dit ;
- le MASQUAGE de ce qui désigne une personne qui n'a pas à l'être : le nom d'un
  particulier hors des actes délibérés (`compilateur_redaction`), le domicile
  et la naissance dans le texte d'une délibération (`masquer_donnees_personnelles`).

Elles vivaient au milieu de `build_public_snapshot.py`. Elles n'y changent
pas : ce module les porte, la façade les réexporte.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

from scripts.snapshot.popolo import POPOLO_ROLES
from scripts.snapshot.socle import RULES, rows, safe_url


# ── Présentation des libellés publics ────────────────────────────────────────
# Les noms viennent bruts du RNA / SIRENE, donc en capitales, et les libellés de
# flux viennent des collecteurs, donc sans casse ni accent homogènes. Publier
# « ASSOCIATION DE PARENTS D'ELEVES DES ECOLES PUBLIQUES DE … » à côté de
# « Le Grillon » donne un flux qui a l'air cassé alors que la donnée est juste.

MOTS_LIAISON = {"DE", "DES", "DU", "D", "LA", "LE", "LES", "L", "ET", "EN",
                "AU", "AUX", "POUR", "SUR", "PAR", "UN", "UNE", "A", "AVEC",
                "SOUS", "SANS", "OU"}

# Sigles à conserver en capitales : la règle « ≤ 3 lettres ou pas de voyelle »
# ne les attrape pas tous, et un sigle title-casé (« Ccas ») est illisible.
ACRONYMES = {
    "ADMR", "AFPPA", "ANS", "APE", "ASART", "ASL", "ATSEM", "BOAMP", "CAC",
    "CAF", "CCAS", "CCAS", "CC", "CD30", "CDG", "CERISE", "CIAS", "CLIC",
    "CNRS", "CVN", "DDFIP", "DETR", "DGCL", "DGF", "DSP", "EHPAD", "EPCI",
    "EPI", "ESAT", "EVEN", "FCTVA", "FSC", "MJC", "MSA", "OFGL", "ONF",
    "PLU", "PNC", "RAM", "RNA", "RPI", "SAS", "SARL", "SCI", "SCIC", "SCOP",
    "SIVU", "SPANC", "SYMTOMA", "UFOLEP", "USEP", "USPOP", "VTT", "ZAD",
}


def joli_nom(nom: str | None) -> str:
    """Nom d'acteur présentable : casse humaine, sigles préservés.

    N'intervient QUE sur les noms tout en capitales (ceux du RNA/SIRENE) : un
    nom déjà saisi avec une casse mixte a été arbitré par un humain, on n'y
    touche pas.
    """
    nom = (nom or "").strip().rstrip(".")
    if not nom or nom != nom.upper():
        return nom

    def bloc(nu: str, premier: bool) -> str:
        if nu in ACRONYMES:
            return nu
        if nu in MOTS_LIAISON:
            return nu.capitalize() if premier else nu.lower()
        # Sigle probable : trop court pour être un mot, ou sans voyelle (HJH).
        # Le seuil est à 2 et non 3 : « NEZ », « ART », « VIV » sont des mots.
        if len(nu) <= 2 or not set(nu) & set("AEIOUY"):
            return nu
        return nu.capitalize()

    sortie = []
    for i, mot in enumerate(nom.split()):
        avant = mot[:len(mot) - len(mot.lstrip("(«\"'"))]
        apres = mot[len(mot.rstrip(")».,;:\"")):]
        nu = mot[len(avant):len(mot) - len(apres)] if apres else mot[len(avant):]
        if not nu:
            sortie.append(mot)
            continue
        # Un mot seul entre parenthèses est le sigle de ce qui précède —
        # « (CCAS) », « (CEPLR) » : le title-case en ferait « Ccas ».
        if "(" in avant and ")" in apres:
            sortie.append(mot)
            continue
        # Apostrophe : élision (« D'ACTION » → « d'Action ») ou nom composé
        # (« VIV'ALTO » → « Viv'Alto »). Les deux parts sont traitées à part.
        parts = re.split(r"(['’])", nu)
        if len(parts) == 3 and parts[0] in {"D", "L", "N", "S", "C", "J", "QU"}:
            rendu = ((parts[0].capitalize() if not i else parts[0].lower())
                     + parts[1] + bloc(parts[2], False))
        elif len(parts) == 3:
            rendu = bloc(parts[0], not i) + parts[1] + bloc(parts[2], False)
        else:
            rendu = bloc(nu, not i)
        sortie.append(avant + rendu + apres)
    return " ".join(sortie)


# « 11 637,87 € » en fin de libellé alors que le montant est déjà affiché en
# face : deux écritures du même chiffre, arrondies différemment.
_MONTANT_FINAL = re.compile(
    r"\s*[—–-]\s*[\d   ]+(?:[.,]\d+)?\s*€\s*$")


def nettoyer_libelle(texte: str | None, acteur: str | None = None,
                     montant_affiche=None) -> str:
    """Libellé de flux débarrassé de ce que la ligne affiche déjà par ailleurs.

    Le nom du bénéficiaire apparaissait jusqu'à trois fois sur une même ligne
    (« USEP Écoles — Subvention communale 2026 — USEP Écoles », plus le lien
    acteur en dessous) parce que chaque collecteur préfixait le libellé qu'il
    écrivait. On retire les répétitions plutôt que le contexte.
    """
    t = " ".join((texte or "").split())
    if not t:
        return t
    if acteur:
        cible = norm_nom(acteur)
        # Les collecteurs écrivent l'acteur tantôt en sigle (« ASART »), tantôt
        # sans apostrophe (« L Art Scene ») : la comparaison se fait sur les
        # tokens, pas sur la chaîne.
        jetons = lambda s: {m for m in norm_nom(s).replace("'", " ")
                            .replace("’", " ").split() if len(m) >= 2}
        cible_jetons = jetons(acteur)

        def redondant(seg: str) -> bool:
            j = jetons(seg)
            return bool(j) and j <= cible_jetons

        def sans_acteur(seg: str) -> str:
            # « USEP Écoles (320 + 4 044 + …) » : le nom préfixe le détail, on
            # ne garde que le détail — l'acteur est déjà en face de la ligne.
            if norm_nom(seg).startswith(cible + " "):
                reste = seg.strip()[len(acteur):].strip()
                if reste.startswith("("):
                    return reste
            return seg

        for sep in (" — ", " – ", " - "):
            morceaux = t.split(sep)
            if len(morceaux) > 1:
                gardes = [sans_acteur(m) for m in morceaux
                          if norm_nom(m) != cible and not redondant(m)]
                if gardes:
                    t = sep.join(gardes)
    if montant_affiche is not None:
        t = _MONTANT_FINAL.sub("", t)
    return t.strip(" —–-")


# Titres qui ne portent aucune information hors du document dont ils sont
# extraits : dans un flux d'actualité, ils occupent une ligne pour rien.
TITRES_VIDES = {"questions diverses", "divers", "informations diverses",
                "informations et questions diverses", "point divers",
                "questions et informations diverses", "(sans titre)"}

# « CM du 2026-05-28 - Conseil municipal du 28 Mai 2026 - … » : le préfixe de
# classement interne du collecteur, redondant avec la date affichée.
_PREFIXE_CM = re.compile(r"^CM\s+du\s+\d{4}-\d{2}-\d{2}\s*[-—–]\s*")


def nettoyer_titre_evenement(titre: str | None) -> str:
    return " ".join(_PREFIXE_CM.sub("", titre or "").split())


def norm_nom(s: str | None) -> str:
    """Nom normalisé pour comparaison : sans accents, majuscules, compacté."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return " ".join(s.upper().replace("-", " ").split())


MENTION_PARTICULIER = "un particulier"
# « M » sans point est exclu : sans lui, « TEAM SET INVESTIGATION » devenait
# « TEAun particulier INVESTIGATION » (le motif « M SET » mordait à l'intérieur
# du mot). Une civilité abrégée s'écrit avec son point.
_CIVILITES = r"(?:M\.|Mme|Mlle|Melle|Monsieur|Madame|Mademoiselle)"

# Siéger, c'est exercer un mandat. La collecte pose ces rôles sur les séances et
# sur les actes qu'elles votent, à partir des listes de présents.
_ROLES_DE_SEANCE = ("présent", "absent")
_TYPES_DE_SEANCE = ("conseil_municipal", "conseil_communautaire",
                    "deliberation", "deliberation_cc")


def _formes_du_nom(p: dict) -> tuple[list[str], str]:
    """Les formes complètes d'un nom de personne, et son patronyme nu."""
    nom_complet = " ".join((p["name"] or "").split())
    prenom = " ".join((p["firstname"] or "").split())
    # Le patronyme peut porter un nom d'usage : « AEMMER (HAUSLER) ».
    patronyme = " ".join((p["lastname"] or "").split())
    if not patronyme and nom_complet:
        morceaux = nom_complet.split(" ", 1)
        patronyme = morceaux[1] if len(morceaux) > 1 else ""
    formes = [f for f in (nom_complet, f"{prenom} {patronyme}".strip(),
                          f"{patronyme} {prenom}".strip()) if len(f.split()) >= 2]
    return formes, patronyme.split("(")[0].strip()


def _ids_nommables(conn, ids_publics: set[int]) -> set[int]:
    """Les personnes publiques : publiées en fiche, ou qui ont SIÉGÉ ou tenu un
    mandat — un mandat clos reste un mandat."""
    mandats = sorted(set(POPOLO_ROLES) | set(RULES["people"]["publish_only_with_relation_types"]))
    return ids_publics | {r["entity_id"] for r in rows(conn, f"""
        SELECT ee.entity_id
        FROM event_entities ee JOIN events ev ON ev.id = ee.event_id
        WHERE ee.role IN ({",".join("?" * len(_ROLES_DE_SEANCE))})
          AND ev.type IN ({",".join("?" * len(_TYPES_DE_SEANCE))})
        UNION
        SELECT from_id FROM relations
        WHERE relation_type IN ({",".join("?" * len(mandats))})
    """, [*_ROLES_DE_SEANCE, *_TYPES_DE_SEANCE, *mandats])}


def _personnes(conn) -> list[dict]:
    return rows(conn, """
        SELECT e.id, e.name, p.firstname, p.lastname
        FROM entities e LEFT JOIN persons p ON p.entity_id = e.id
        WHERE e.type = 'person'
    """)


def noms_des_personnes_publiques(conn, ids_publics: set[int]) -> set[str]:
    """Les formes complètes, en capitales, du nom de chaque personne publique."""
    nommables = _ids_nommables(conn, ids_publics)
    return {f.upper() for p in _personnes(conn) if p["id"] in nommables
            for f in _formes_du_nom(p)[0]}


def compilateur_redaction(conn, ids_publics: set[int]):
    """Masque les personnes physiques non publiables citées DANS LES TEXTES.

    Le filtre entités écarte bien un particulier du graphe, mais son nom
    ressortait quand même par les libellés : « Aide façade — M. Farget »,
    « Cession … à Prénom NOM (veuve NOM) ». Le texte est une sortie
    comme une autre, il doit passer le même filtre.

    On ne masque que des formes non ambiguës — nom complet, ou civilité + nom
    de famille. Un patronyme seul est trop souvent aussi un toponyme ou un nom
    de société d'ici pour être remplacé sans arbitrage.

    ⚖️ Qui a SIÉGÉ ou tenu un mandat n'est pas un particulier. `ids_publics` ne
    connaît que les mandats que les règles publient : un titre court n'en
    souffrait pas, le texte entier d'une délibération si. Relevé sur les
    extraits de la première commune portée, avant correction — 8 548 « un
    particulier », dont les conseillers des mandats précédents à chaque prise de
    parole, un ancien maire « Sous la présidence de Monsieur un particulier », et
    le maire en exercice dans chaque liste de présents : « Secrétaire de séance :
    un particulier » partait en ligne.

    ⚖️ Les DÉLIBÉRATIONS ne passent plus par ici (arbitré par Julien le 16/09) :
    un particulier cité dans un acte officiel est cité. Cf. `texte_publiable`,
    qui en masque le domicile et la naissance, jamais le nom.
    """
    nommables = _ids_nommables(conn, ids_publics)
    personnes = _personnes(conn)

    # Ce qu'une forme désigne n'est pas écrit dans la forme : « M. MARCHAL »,
    # ou « Thierry MARCHAL » quand la base porte deux fiches du même homme, peut
    # être l'élu autant que son homonyme privé. Une forme partagée avec une
    # personne nommable est ambiguë, et une personne publique ne se masque pas
    # sur un doute.
    formes_nommables, patronymes_nommables = set(), set()
    for p in personnes:
        if p["id"] in nommables:
            formes, premier = _formes_du_nom(p)
            formes_nommables.update(f.upper() for f in formes)
            patronymes_nommables.add(premier.upper())

    complets: set[str] = set()
    courts: set[str] = set()
    for p in personnes:
        if p["id"] in nommables:
            continue
        formes, premier = _formes_du_nom(p)
        for forme in formes:
            if forme.upper() not in formes_nommables:
                complets.add(re.escape(forme))
        # Un patronyme précédé d'une civilité désigne une personne — pas
        # forcément celle-ci, s'il est aussi celui d'un élu. Et pas si un NOM en
        # capitales le suit : c'est alors un prénom. « M. Thierry SCHWEDA »
        # devenait « un particulier SCHWEDA » parce qu'un particulier de la
        # base s'appelle THIERRY — la comparaison ignore la casse, d'où le
        # `(?-i:…)` qui la rétablit pour ce seul contrôle.
        if len(premier) >= 3 and premier.upper() not in patronymes_nommables:
            courts.add(rf"{_CIVILITES}\s+{re.escape(premier)}"
                       r"(?-i:(?!\s+[A-ZÀ-Ÿ][A-ZÀ-Ÿ'’\-]+\b))")

    if not complets and not courts:
        return (lambda texte: texte), Counter()

    # Les formes longues d'abord : sinon « Prénom NOM » consomme le texte
    # avant que « Prénom NOM (veuve NOM) » ait sa chance.
    # `(?<!\w)` / `(?!\w)` plutôt que `\b` : certains noms d'usage finissent par
    # une parenthèse — « AEMMER (HAUSLER) » — devant laquelle `\b` ne matche pas.
    motif = re.compile(
        r"(?<!\w)(?:" + "|".join(sorted(complets | courts, key=len, reverse=True)) + r")(?!\w)",
        re.IGNORECASE)
    compteur = Counter()

    def redige(texte: str | None) -> str | None:
        if not texte:
            return texte
        sortie, n = motif.subn(MENTION_PARTICULIER, texte)
        if n:
            compteur["remplacements"] += n
        return sortie

    return redige, compteur


# ⚖️ Ce qu'une délibération publie, arbitré par Julien le 16/09/2026 : un
# particulier cité dans un acte officiel est CITÉ — titres et textes des
# délibérations ne passent plus par `redige()`. Ce qui ne sort pas, c'est ce qui
# situe ou date une personne : son domicile, sa date et son lieu de naissance.
# L'âge d'une personne publique n'est pas interdit et a du sens : la date de
# naissance d'un élu devient son âge à la date de l'acte.
#
# Ces données sont MASQUÉES dans le texte, qui reste publié. Formes relevées le
# 16/09 sur les trois instances : « Philippe BERNA né le 05/03/1961 ; » (un
# délégué), « née le 12 octobre 1985 est nommée », « né le 01/10/1970 à
# Castres », « demeurant au 52 Grande Rue à Saillans », « domiciliée 6, rue ⏎ du
# Moulin », « domicilié 5, ⏎ chemin de Combessege à Brassac », « résidant à
# l'adresse « … – 8 Impasse … » à Bruges (33 520) », « M. et Mme X domiciliés à
# Croix de Castres », et le tableau du conseil « Date de naissance Adresse CP
# Ville » que l'océrisation mêle sur plusieurs lignes. Un courriel nominatif
# (prénom.nom@) est masqué au titre des coordonnées des personnes.
#
# 🔴 Le filet : ce que ces règles n'ont pas su masquer est cherché une seconde
# fois, et l'EXTRAIT n'est alors pas publié — l'acte, son titre et le lien vers
# la pièce restent.
_MOIS = ("janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet",
         "aout", "septembre", "octobre", "novembre", "decembre")
_MOIS_RE = r"(?:janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[ée]cembre)"
_DATE_COMPLETE = (r"(?:\d{1,2}\s*[/.\-]\s*\d{1,2}\s*[/.\-]\s*\d{4}"
                  rf"|\d{{1,2}}(?:er)?\s+{_MOIS_RE}\s+\d{{4}})")
# Une commune, un lieu-dit : des mots à majuscule reliés par les petits mots d'un
# toponyme. `(?-i:…)` : sous IGNORECASE, « à la maison de retraite » serait un lieu.
_MAJ, _MIN = "A-ZÀ-ÖØ-ÞŒŠŽŸ", "a-zß-öø-ÿœšž"
# Suite d'un toponyme : en casse de titre seulement — « à Castres PRÉCISE » ne
# doit pas emporter le verbe qui suit, écrit en capitales.
_LIEU = (rf"(?-i:[{_MAJ}])[\w'’\-]+"
         rf"(?:[ \-](?:sur|sous|en|de|du|des|la|le|les|lès|(?-i:[{_MAJ}][{_MIN}'’\-]+)))*"
         r"(?:\s*\(\s*\d[\d\s]*\))?")
_NAISSANCE = re.compile(
    rf"\b(?P<est>est\s+)?n(?P<genre>[ée]e?)\s+le\s+(?P<date>{_DATE_COMPLETE})"
    rf"(?P<lieu>\s+à\s+{_LIEU})?", re.I)
_VOIE = (r"(?:grande\s+rue|rue|chemin|all[ée]e|impasse|route|rte|avenue|place|"
         r"boulevard|quai|lotissement|mont[ée]e|traverse|passage|hameau|"
         r"quartier|domaine|r[ée]sidence)")
_ADRESSE_NUMEROTEE = (r"\s*(?:au|à|:)?\s*\d{1,4}\s*(?:bis|ter)?\s*,?[^\d,.;]{0,25}?"
                      rf"\b{_VOIE}\b")
_DOMICILE = re.compile(
    r"\b(?P<verbe>domicili[ée]e?s?|demeurant|r[ée]sidant)(?:"
    rf"\s+à\s+l['’]adresse\s*«[^»]{{0,160}}»(?:\s+à\s+{_LIEU})?"
    rf"|{_ADRESSE_NUMEROTEE}\s*[^,.;\n]{{0,80}}?(?=\s+à\s|\s*[,.;]|\s*\n|\s*$)"
    rf"(?:\s+à\s+{_LIEU})?"
    rf"|(?P<lieudit>\s+(?:à|au|aux|en)\s+{_LIEU})"
    r")", re.I)
# Un domicile sans numéro n'en est un que pour une PERSONNE : « M. et Mme X
# domiciliés à Croix de Castres » — mais « l'association domiciliée à Viane ».
_CIVILITE_AVANT = re.compile(r"(?:\bM\.|\bMM\.|\bMmes?\b|\bMonsieur\b|\bMadame\b)[^\n]{0,60}$")
_COURRIEL_NOMINATIF = re.compile(r"\b[a-z]{2,}\.[a-z]{2,}@[\w\-]+(?:\.[\w\-]+)+", re.I)
# Le téléphone qui accompagne un courriel nominatif est la même coordonnée : sur
# la même ligne, il est masqué. Seul, il est le plus souvent celui d'un lieu —
# un tiers-lieu, une mairie — et reste.
_TELEPHONE = re.compile(r"(?<![\d.])0[1-9](?:[ .\-]?\d{2}){4}(?![\d.])")
_TABLEAU_DES_ELUS = re.compile(
    r"^[^\n]*date\s+de\s+naissance\s+adresse[\s\S]{0,3000}?"
    r"(?=apr[èe]s\s+en\s+avoir\s+d[ée]lib[ée]r|\bD[ÉE]CIDE\b|^\s*Le\s+(?:maire|conseil)\b|\Z)",
    re.I | re.M)
_NOM_AVEC_CIVILITE = re.compile(
    rf"(?:Monsieur|Madame|M\.|Mme)\s+(?:[{_MAJ}][{_MIN}'’\-]+\s+){{0,2}}[{_MAJ}][{_MAJ}'’\-]+"
    rf"(?:\s+[{_MAJ}][{_MIN}'’\-]+)?")
_FONCTION_D_ELU = re.compile(
    r"\bMaire\b|\b\d+\s*(?:er|ère|e|ème|nd|nde)\s+adjointe?\b"
    r"|\bConseill(?:er|ère)\s+municipal(?:e)?\b", re.I)
_RESIDU = re.compile(
    rf"\bn[ée]e?\s+le\s+{_DATE_COMPLETE}|date\s+de\s+naissance\s+adresse"
    rf"|\b(?:domicili[ée]e?s?|demeurant|r[ée]sidant){_ADRESSE_NUMEROTEE}", re.I)


def _age(naissance: str, jour: str | None) -> int | None:
    """L'âge à la date de l'acte, ou rien si l'une des deux dates ne se lit pas."""
    from datetime import date
    m = re.match(r"(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{4})", naissance)
    if m:
        j, mois, annee = (int(x) for x in m.groups())
    else:
        m = re.match(rf"(\d{{1,2}})(?:er)?\s+({_MOIS_RE})\s+(\d{{4}})", naissance, re.I)
        if not m:
            return None
        cle = unicodedata.normalize("NFKD", m.group(2).lower()).encode("ascii", "ignore").decode()
        j, mois, annee = int(m.group(1)), _MOIS.index(cle) + 1, int(m.group(3))
    try:
        ne, acte = date(annee, mois, j), date.fromisoformat((jour or "")[:10])
    except ValueError:
        return None
    age = acte.year - ne.year - ((acte.month, acte.day) < (ne.month, ne.day))
    return age if 0 <= age < 120 else None


def _nomme_une_personne_publique(avant: str, noms_publics: set[str]) -> bool:
    """Le nom écrit juste avant « né le » est-il celui d'une personne publique ?"""
    mots = re.findall(r"[\w'’\-]+", avant[-100:].upper())[-6:]
    return any(" ".join(mots[i:j]) in noms_publics
               for i in range(len(mots)) for j in range(i + 2, len(mots) + 1))


def convocation_publique(c: dict, jour: str | None, noms_publics, masquages) -> dict:
    """Ce qu'une convocation annonce, tel qu'il peut sortir."""
    sortie = {k: c[k] for k in ("heure", "lieu", "convoque_le") if c.get(k)}
    url = safe_url(c.get("url"))
    if url and url.lower().startswith(("http://", "https://")):
        sortie["url"] = url
    points = [masquer_donnees_personnelles(p, jour, noms_publics, masquages)
              for p in c.get("ordre_du_jour") or []]
    if points:
        sortie["ordre_du_jour"] = points
    return sortie


def masquer_donnees_personnelles(texte: str, jour: str | None,
                                 noms_publics: set[str], compteur: Counter) -> str:
    """Masque domicile, date et lieu de naissance ; garde les noms."""
    def tableau(m):
        # L'océrisation mêle les colonnes sur plusieurs lignes : on ne garde de
        # chaque ligne que le nom de l'élu et sa fonction.
        compteur["tableau_des_elus"] += 1
        lignes = []
        for ligne in m.group(0).splitlines():
            noms = _NOM_AVEC_CIVILITE.findall(ligne)
            if noms:
                lignes.append(" ".join([*noms, *_FONCTION_D_ELU.findall(ligne)]))
            elif re.search(r"liste\s+des|\bélus\b|date\s+de\s+naissance", ligne, re.I):
                lignes.append(re.sub(
                    r"date\s+de\s+naissance\s+adresse(?:\s+CP)?(?:\s+Ville)?(?:\s+Titre)?",
                    "(dates de naissance et adresses masquées)", ligne, flags=re.I))
        return "\n".join(lignes) + "\n"

    def naissance(m):
        feminin = "e" if m.group("genre").lower().endswith("e") else ""
        est = m.group("est") or ""
        if _nomme_une_personne_publique(courant[:m.start()], noms_publics):
            age = _age(m.group("date"), jour)
            if age is not None:
                compteur["naissance_en_age"] += 1
                return f"{est}âgé{feminin} de {age} ans"
        compteur["naissance"] += 1
        masque = "[date et lieu masqués]" if m.group("lieu") else "[date masquée]"
        return f"{est}né{feminin} le {masque}"

    def domicile(m):
        if m.group("lieudit") is not None and not _CIVILITE_AVANT.search(courant[:m.start()]):
            return m.group(0)
        compteur["domicile"] += 1
        return f"{m.group('verbe')} [domicile masqué]"

    courant = _TABLEAU_DES_ELUS.sub(tableau, texte)
    courant = _NAISSANCE.sub(naissance, courant)
    courant = _DOMICILE.sub(domicile, courant)
    courant, n = _COURRIEL_NOMINATIF.subn("[courriel masqué]", courant)
    compteur["courriel"] += n
    if n:
        lignes = []
        for ligne in courant.split("\n"):
            if "[courriel masqué]" in ligne:
                ligne, k = _TELEPHONE.subn("[téléphone masqué]", ligne)
                compteur["telephone"] += k
            lignes.append(ligne)
        courant = "\n".join(lignes)
    return courant


def texte_publiable(texte: str, jour: str | None, noms_publics: set[str],
                    compteur: Counter) -> tuple[str | None, str | None]:
    """Le texte d'une délibération tel qu'il sort — ou le motif de son refus."""
    masque = masquer_donnees_personnelles(texte.strip(), jour, noms_publics, compteur)
    if _RESIDU.search(masque):
        return None, "donnee_personnelle_non_masquee"
    return masque, None
