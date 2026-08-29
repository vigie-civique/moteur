"""
Analyseurs de comptes rendus de conseil municipal.

Bibliothèque de fonctions, sans pipeline : catégorisation d'un titre de
délibération, extraction du vote, des montants et des noms cités, découpage
d'un texte en sections, rattachement des personnes à un événement.

Les collecteurs qui l'utilisent — `conseils`, `cm_ocr` — apportent chacun leur
lecture de la source ; ce module ne connaît que du texte.
"""

import re
import json
import sqlite3
from datetime import datetime
from pathlib import Path

# ── Catégorisation des délibérations ──────────────────────────────────────────

CATEGORIE_RULES = [
    # (regex sur titre, catégorie, tags)
    (r'SUBVENTION|SUBV\b|AIDE.*FINANC|AIDE.*COMM',  'subvention',        ['finances','associations']),
    (r'BAIL|LOYER|TARIF.*SALON|TARIF.*VILLA|BAIL.*EMPH|EMPHYTEOTIQUE', 'bail_loyer', ['patrimoine','finances']),
    (r'CESSION|VENTE.*TERRAIN|ALIENATION|DESAFFECT', 'cession_patrimoine',['patrimoine','foncier']),
    (r'MARCHE|PRESTATAIRE|APPEL.*OFFRE|LANCEMENT.*APPEL|ATTRIBUTION.*MARCHE|CONSULTATION', 'marche_public', ['achats']),
    (r'EMPLOI|POSTE|RECRUTEMENT|EFFECTIF|SAISONNIER|TABLEAU.*EMPLOI|CONTRAT.*APPRENT|CONTRAT.*PROJET|CONTRAT.*ENGAGEMENT|SERVICE\s+CIVIQUE|TEMPS\s+PARTIEL|TEMPS\s+TRAV|HEURES.*COMP|HEURES.*SUPP|CYCLES.*TRAV|DUREE.*ANNUELLE', 'ressources_humaines', ['rh']),
    (r'BUDGET|DECISION MODIF|DM\b|AFFECTATION|EMPRUNT|LIGNE.*TRESOR|COMPTE\s+ADMIN|COMPTES\s+ADMIN|RESULTAT|ADMISSION.*NON.VALEUR|MODIFICATION.*CREDIT|CREDIT.*MODIF', 'budget', ['finances']),
    (r'INDEMNIT[EÉ]|PRIME|POUVOIR.*ACHAT|BON.*ACHAT|PREVOYANCE|PARTICIPATION.*PREVOYANCE', 'remuneration', ['rh','finances']),
    (r'PLU|URBANISME|PLAN.*LOCAL|DOCUMENT.*URBANISME', 'urbanisme',       ['foncier']),
    (r'TRAVAUX|VOIRIE|OUVRAGE|RESEAU|ECLAIRAGE|AMENAGEMENT|RENOVATION.*ECOLE|AUDIT.*ENERG|MAITRISE.*OEUVRE', 'travaux', ['infrastructure']),
    (r'CONVENTION|PARTENARIAT|PROTOCOLE',            'convention',        ['partenariat']),
    (r'FONDS.*CONCOURS|SUBV.*ETAT|FONDS.*VERT|DEMANDE.*SUBVENTION', 'subvention_recue', ['finances']),
    (r'MOTION|VOEU\b',                               'motion',            ['politique']),
    (r'CANTINE|RESTAURATION.*SCOLAIRE',              'cantine',           ['services']),
    (r'CRECHE|ENFANCE|PERISCOLAIRE|ACCUEIL.*JEUNES?', 'petite_enfance',   ['services']),
    (r'AIDE.*FACADE|RENOVATION.*FACADE',             'aide_habitat',      ['patrimoine']),
    (r'ASSURANCE|CDG\b|CENTRE.*GESTION|DENOMINATION.*VOIE|COMMISSION\s+EXTRA|COMMISSIONS?\s+COMMUNALE|COMPOSITION.*COMMISSION|ACTUALISATION.*COMM', 'administration', ['admin']),
    (r'TAUX.*IMPOSITION|TAXE|EXONERATION|FISCALIT|CFE\b|TFPB', 'fiscalite', ['finances']),
    (r'TARIFS?\b|LOCAT.*SALLE|SALLE.*MUNIC|UTILISATION.*MATER',  'tarifs',  ['services']),
    (r'ADHESION|PAYS\s+CEVENOL|SMEG\b|INTERCOMMUNAL|CAC\b|RECOMPOSIT', 'intercommunal', ['gouvernance']),
    (r'INFORMATION|COMPTE.?RENDU|RAPPORT|OBSERVATIONS.*PV',      'information', ['admin']),
    (r'QUESTIONS\s+DIVERSES',                        'questions_diverses', ['admin']),
    (r'NOMENCLATURE|M57\b|M14\b',                    'budget',            ['finances']),
    (r'CONCESSION.*CIMETIERE|DOMAINE.*PRIVE',        'cession_patrimoine',['patrimoine']),
    (r'ECOPOUSSE|PROGRAMME.*ENVIR|TRANSITION.*ECOL|DEBROUSSAILLAGE', 'environnement', ['environnement']),
    (r'VOYAGE.*PEDAGOG|COLLEGE|ECOLE\b|USEP\b',      'education',         ['services']),
    (r'MAISON.*SANTE|MSP\b|CPTS\b|MÉDECIN|AUXILIAIRE.*MED', 'sante',      ['services']),
    (r'SECURITE|POLICE|AMENDE',                      'securite',          ['admin']),
    (r'FETE\b|VOTIVE|CHATAIGNE|FORET.*CEV',          'evenement',         ['culture']),
]

def categorize(title: str):
    title_up = title.upper()
    for pattern, cat, tags in CATEGORIE_RULES:
        if re.search(pattern, title_up):
            return cat, tags
    return 'autre', []


# ── Extraction des montants ────────────────────────────────────────────────────

def extract_amounts(text: str) -> list[dict]:
    """Retourne liste de {value: float, context: str}.

    Le montant doit être ISOLÉ. L'ancien motif — « un chiffre, puis n'importe
    quelle suite de chiffres et d'espaces » — recollait ce qui précédait :

        « CD30 145 834,00 € »        →  30 145 834 €   (CD30 = le département)
        « FEDER 2021-2027 458 784,55 € » → 2 027 458 784 €
        « facture 25/5/2023 14 275.20€ » →   202 314 275 €

    Une commune de 1 200 habitants publiait ainsi des lignes à 30 M€. Les
    groupes de milliers font donc exactement trois chiffres, et rien
    d'alphanumérique ne peut coller le montant à gauche.
    """
    # 1 234,56 € · 1234.56€ · 1 234 € · 12 345 678,90 €
    #
    # Le tiret est ADMIS devant : « une baisse de -36 706,26 € » est un montant
    # signé, pas un collage — l'exclure faisait lire 706,26 €.
    #
    # ⚠️ Limite assumée : quand l'OCR mange l'espace d'un mot (« de6 185,92 € »),
    # le chiffre collé à la lettre est perdu et l'on lit 185,92 €. Rien ne
    # distingue ce cas de « CD30 145 834,00 € », où le 30 appartient au nom du
    # département. Entre lire 185,92 au lieu de 6 185,92 et publier 30 145 834
    # au lieu de 145 834, la première erreur est la moins trompeuse.
    pat = (r'(?<![\w,.])(\d{1,3}(?:[\s\xa0]\d{3})*(?:[,.]\d{2})?'
           r'|\d+(?:[,.]\d{2})?)\s*€')
    results = []
    for m in re.finditer(pat, text):
        raw = m.group(1).replace('\xa0','').replace(' ','').replace(',','.')
        try:
            val = float(raw)
            if val > 0:
                start = max(0, m.start()-80)
                ctx = text[start:m.end()+40].replace('\n',' ').strip()
                results.append({'value': val, 'context': ctx})
        except ValueError:
            pass
    return results


# ── Extraction des votes ───────────────────────────────────────────────────────

# Au-delà, ce n'est plus une assemblée : le plus grand conseil communautaire de
# France compte moins de deux cents délégués.
EFFECTIF_MAX = 200


def extract_vote(text: str) -> dict | None:
    """Lit un décompte de voix, quel que soit l'ORDRE des mentions.

    L'ancien motif n'acceptait qu'une seule tournure — « X voix pour et Y
    contre/abstention », dans cet ordre. Sur les 254 passages de vote des
    procès-verbaux de la commune, il en manquait 48, soit un sur cinq :

        21×  « par 3 voix contre (MF, JPE et AR) et 10 voix pour »
        10×  « par 1 « abstention » et 11 voix »          (le « pour » implicite)
         9×  « 1 voix contre (Jean Pierre ESPAZE), 1 … »
         8×  « abstention (Armelle ROUVERET) et 11 voix pour »

    Et le manque n'était pas neutre : une opposition écrite AVANT le « pour »
    était lue comme zéro. Les 26 délibérations dont le texte porte « N voix
    contre » étaient toutes enregistrées à 0 contre — la page publiait donc
    « 657 actes sur 729 adoptés sans une voix contre », un chiffre faux dans le
    sens rassurant.

    Chaque mention est donc lue pour elle-même. Un « N voix » resté sans
    qualificatif est compté « pour » — et seulement si aucun « pour » explicite
    n'a été trouvé, faute de quoi on doublerait le décompte.
    """
    if not text:
        return None

    # Le décompte se lit AUTOUR de sa première mention, dans le paragraphe qui
    # la porte. Un même bloc contient parfois deux délibérations, chacune avec
    # son vote : prendre le texte entier les additionnerait.
    #
    # ⚠️ Borner sur « après en avoir délibéré » puis couper à la première
    # ponctuation était trop serré : le « pour » tombait hors fenêtre et un
    # « 11 voix pour, 3 abstentions » devenait « 3 abstentions » sans pour.
    # La fenêtre part donc de la mention elle-même, s'étend des deux côtés, et
    # ne franchit pas la frontière de paragraphe.
    premiere = re.search(r"\d+[^\S\n]*(?:voix|votes?|abstentions?|contres?|pour)\b",
                         text, re.IGNORECASE)
    if premiere is None:
        if re.search(r"à l.unanimité", text, re.IGNORECASE):
            return {"pour": None, "contre": 0, "abstentions": 0, "unanimite": True}
        return None
    # La fenêtre est la LIGNE qui porte la première mention — pas un rayon de
    # caractères autour d'elle.
    #
    # Un bloc mal découpé enchaîne deux délibérations, chacune avec son vote.
    # Une fenêtre large les ADDITIONNE : « par 3 voix contre et 10 voix pour »,
    # deux fois, donnait 20 pour et 6 contre dans un conseil de treize membres.
    # Les huit tournures relevées tiennent toutes sur une ligne ; c'est donc la
    # bonne unité, et elle est infranchissable.
    i = premiere.start()
    debut = text.rfind("\n", 0, i) + 1
    fin_ligne = text.find("\n", i)
    fin_ligne = fin_ligne if fin_ligne != -1 else len(text)
    # La phrase de vote se ferme par « : », qui introduit les décisions. Elle
    # déborde parfois d'une ligne — la mise en page coupe au milieu d'une
    # parenthèse : « par 3 abstentions (M. ESPAZE et Mme\nROUVERET) et 11 voix
    # « Pour » : ». S'arrêter à la ligne perdait alors les 11 voix.
    #
    # Une ligne de débord au plus : au-delà, on retomberait sur la délibération
    # suivante et l'on additionnerait deux votes.
    deux_points = text.find(":", i)
    if deux_points != -1 and text.count("\n", i, deux_points) <= 1:
        fin = max(fin_ligne, deux_points)
    else:
        fin = fin_ligne
    passage = text[debut:fin]

    if not re.search(r"\d+[^\S\n]*(?:voix|votes?|abstentions?|contres?|pour)", passage, re.IGNORECASE):
        if re.search(r"à l.unanimité", text, re.IGNORECASE):
            return {"pour": None, "contre": 0, "abstentions": 0, "unanimite": True}
        return None

    # Un décompte s'écrit avec le mot qui le désigne. Sans « voix », « vote » ou
    # « suffrage » dans le passage, un nombre suivi de « pour » n'est pas un
    # vote : « Vu les articles L.153-36 à L.153-48 … pour le PLUi » donnait
    # 123 voix pour, et la borne d'effectif ne l'attrapait pas — 123 est un
    # nombre de délégués plausible.
    if not re.search(r"\b(?:voix|votes?|suffrages?|unanimité)\b", passage, re.IGNORECASE):
        return None

    vote = {"pour": None, "contre": 0, "abstentions": 0, "unanimite": False}
    trouve = False
    # « 12 voix « Pour » », « 1 abstention », « 2 voix Contre », « 3 votes contre »
    for n, mot in re.findall(
            r"(\d+)[^\S\n]*(?:voix|votes?)?[^\S\n]*[«\"“„]?[^\S\n]*(pour|contres?|abstentions?)\b",
            passage, re.IGNORECASE):
        n, mot = int(n), mot.lower()
        trouve = True
        if mot.startswith("abstention"):
            vote["abstentions"] += n
        elif mot.startswith("contre"):
            vote["contre"] += n
        else:
            vote["pour"] = (vote["pour"] or 0) + n

    # « par 1 abstention et 11 voix » : le « pour » n'est pas écrit. Il ne se
    # devine que si rien d'autre ne l'a déjà renseigné.
    if vote["pour"] is None:
        for n in re.findall(r"(\d+)[^\S\n]*voix(?![^\S\n]*[«\"“„]?[^\S\n]*(?:pour|contre|abstention))",
                            passage, re.IGNORECASE):
            vote["pour"] = int(n)
            trouve = True
            break

    if not trouve:
        if re.search(r"à l.unanimité", text, re.IGNORECASE):
            return {"pour": None, "contre": 0, "abstentions": 0, "unanimite": True}
        return None

    # Un décompte de voix ne dépasse pas l'effectif d'une assemblée.
    #
    # « Le total des dépenses 2016 s'élève à … » et « BUDGET 2024 pour la
    # commune » donnaient des votes à 2 016 et 2 024 voix : un MILLÉSIME suivi
    # d'un mot de vote. 232 actes de Lasalle en portaient un. Aucun conseil
    # communautaire de France n'a mille délégués ; au-delà de deux cents, ce
    # n'est pas un vote qu'on lit, c'est une année ou un montant.
    if any((v or 0) > EFFECTIF_MAX for v in
           (vote["pour"], vote["contre"], vote["abstentions"])):
        if re.search(r"à l.unanimité", text, re.IGNORECASE):
            return {"pour": None, "contre": 0, "abstentions": 0, "unanimite": True}
        return None

    # « à l'unanimité » et un décompte peuvent coexister : « adopté à
    # l'unanimité par 13 voix pour ». L'unanimité n'est vraie que sans opposition.
    if re.search(r"à l.unanimité", text, re.IGNORECASE) \
            and not vote["contre"] and not vote["abstentions"]:
        vote["unanimite"] = True

    # Votants nommés : uniquement dans la parenthèse qui SUIT une mention de
    # vote. L'ancienne version prenait toute parenthèse commençant par une
    # majuscule, et rangeait « (Anciennement Mandragora) » parmi les votants.
    named = re.findall(
        r"(?:contres?|abstentions?)\s*[»\"”]?\s*\(([^)]{2,60})\)", passage, re.IGNORECASE)
    if named:
        vote["nommés"] = [n.strip() for n in named]
    return vote


# ── Parsing du bloc présents/absents ──────────────────────────────────────────

_NOM_PATTERN = re.compile(
    r'\b(?:M\.|Mme|Mmes|MM\.)\s+(?:de\s+)?([A-ZÀÂÇÉÈÊËÎÏÔÙÛÜ][A-ZÀ-Ÿa-zà-ÿ\-]+)'
    r'(?:\s+(?:de\s+)?([A-ZÀÂÇÉÈÊËÎÏÔÙÛÜ][A-ZÀ-Ÿa-zà-ÿ\-]+))?',
    re.UNICODE
)

def extract_names(text: str) -> list[str]:
    """Extrait les noms propres (NOM ou Prénom NOM)"""
    names = []
    for m in _NOM_PATTERN.finditer(text):
        name = m.group(0).strip()
        names.append(name)
    return names


def parse_attendees(lines: list[str]) -> dict:
    """Retourne {presents: [], absents: [], pouvoirs: []}"""
    result = {'presents': [], 'absents': [], 'pouvoirs': []}
    mode = None
    for line in lines[:35]:
        line = line.replace('\xa0', ' ')
        is_pres = re.search(r'PRÉSENTS?\s*:', line, re.IGNORECASE)
        is_abs  = re.search(r'ABSENTS?\s*:', line, re.IGNORECASE)
        is_pow  = re.search(r'donne\s+pouvoir', line, re.IGNORECASE)
        is_sep  = re.match(r'^_{3,}$', line.strip())

        if is_pres:
            mode = 'presents'
            # Noms sur la même ligne que "PRÉSENTS :"
            names = extract_names(line)
            result['presents'].extend(names)
            continue
        elif is_abs:
            mode = 'absents'
            names = extract_names(line)
            result['absents'].extend(names)
            continue
        elif is_pow:
            result['pouvoirs'].append(line.strip())
            continue
        elif is_sep:
            mode = None
            continue

        # Ligne suivante dans le même mode
        if mode:
            names = extract_names(line)
            if names:
                result[mode].extend(names)
            elif line.strip() and not re.search(r'[a-z]{10,}', line):
                # Ligne sans noms et pas de texte courant = fin du bloc
                pass
    return result


# ── Découpage en délibérations ─────────────────────────────────────────────────

# Bruit PROPRE À UNE SOURCE : en-têtes de colonnes qui portent le nom d'une
# commune voisine, patronymes d'agents qui reviennent à chaque page, intitulés
# d'équipements locaux. Ces motifs dépendent de la mise en page des PV d'une
# mairie donnée, pas du français. Ils se déclarent dans `config/instance.json`
# sous `bruit_pv` et n'ont rien à faire dans le moteur : cinq patronymes y ont
# figuré en dur jusqu'au 14/08/2026, dans un dépôt destiné à la publication.
def _bruit_local() -> str:
    """Alternative de motifs locale, vide si l'instance n'en déclare pas.

    Les entrées sont des FRAGMENTS d'expression régulière et non du texte
    littéral : les motifs d'origine mêlaient formes ancrées en fin de ligne
    (`COLOGNAC\\s*$`, un nom de commune seul en tête de colonne) et formes
    libres (`STE\\s+CROIX`). Les échapper aurait changé le découpage sans que
    rien ne le signale. Un fragment invalide est ignoré plutôt que de casser
    l'analyse de tous les PV.
    """
    try:
        from .config import BRUIT_PV
    except Exception:      # module lu hors instance : il reste utilisable
        return ""
    valides = []
    for fragment in BRUIT_PV:
        if not fragment:
            continue
        try:
            re.compile(fragment)
        except re.error:
            continue
        valides.append(fragment)
    return "".join(f"{f}|" for f in valides)


_NOISE_PATTERNS = re.compile(
    r'^(PRÉSENTS?|ABSENTS?|PROCÈS-VERBAL|SECTION\s+D|SECTION\s+DE|RECETTES?|DÉPENSES?|TOTAL|'
    r'PAR\s+MOIS|FONCTIONNEMENT|INVESTISSEMENT|SOLDE|'
    r'COMMUNE\s*:|CG\s+EAU|SIAEP|EAU\s+SECT|'
    r'INESTISSEMENT|EXERCICE\s*$|A\s+REPRENDRE\s*$|SECTIONS?\s*$|RÉSULTAT\s*$|'
    + _bruit_local() +
    r'DU\s+\d+\s+\w+\s+\d{4}|DU\s+\d{1,2}\s+\w+\s+\d{4}|'  # "DU 15 NOVEMBRE 2023"
    r'CANDIDATS\s*$|CLASSEMENT\s*$|DENOMINATION\s*$|'
    r'PÉRIODE\s+SCOLAIRE|PÉRISCOLAIRE\s*$|SERVICE\s+(ADMIN|TECH|CULT)|'
    r'ENSEMBLE\s+DE\s+LA\s+COLLECT|'
    r'\[CD\d\]|\[CC\d\]|'
    r'DEPENSES\s*$|RECETTES\s*$|__+)',
    re.IGNORECASE | re.UNICODE
)

# Fragments purement numériques ou de tableaux budgétaires
_TABLE_FRAG = re.compile(
    r'^(?:[\d\s\xa0,\.€%\+\-/]+|TOTAL\s+(?:DES\s+)?(?:DEPENSES?|RECETTES?)'
    r'|(?:DEPENSES?|RECETTES?)\s+(?:DE\s+)?(?:FONCT|INVEST)\w*'
    r'|C\.?F\.?E\.?\s*[\.:…]'
    r')[\s:€%\.]*$',
    re.IGNORECASE
)

def is_section_header(text: str) -> bool:
    """True si le texte est une ligne de titre de délibération en MAJUSCULES."""
    t = text.strip()
    if len(t) < 10 or len(t) > 250:
        return False
    # Exclure les fragments bruit connus
    if _NOISE_PATTERNS.match(t):
        return False
    if _TABLE_FRAG.match(t):
        return False
    # Doit être majoritairement en majuscules
    alpha = [c for c in t if c.isalpha()]
    if not alpha:
        return False
    upper_ratio = sum(1 for c in alpha if c.isupper()) / len(alpha)
    if upper_ratio < 0.80:
        return False
    # Exclure les noms de conseillers seuls (M. BENEFICE :, Mme DELAUNAY, M. VALADIER…)
    # — avec ou sans point après M/Mme, suivi de 1-2 mots seulement (intervention)
    if re.match(r'^(?:M|MM|Mme|Mmes)\.?\s+[A-ZÀ-Ÿ][\wÀ-ÿ\-]+(?:\s+[A-ZÀ-Ÿ][\wÀ-ÿ\-]+)?\s*:?\s*$', t):
        return False
    # Exclure les fragments à points de conduite (tableaux : "C.F.E. ........ :")
    if '....' in t:
        return False
    # Exclure les lignes de chiffres purs
    if re.match(r'^[\d\s€,.+-]+$', t):
        return False
    # Exclure les lignes de séparation
    if re.match(r'^[_\-=*]+$', t):
        return False
    # Une LIGNE DE TABLEAU comptable n'est pas un titre de délibération.
    # « 1022 F.C.T.V.A. 52 710,01 », « 6061 EDF 500,00 », « ASART 1 500,00 » :
    # un libellé suivi d'un montant, dans un tableau budgétaire ou une liste de
    # subventions. Le découpeur en faisait des délibérations à part entière —
    # d'où les 43 actes intitulés d'un nom et d'un chiffre, et le contenu de la
    # vraie délibération réparti entre eux.
    if re.search(r'[\d\s]-?\d{1,3}(?:[\s\xa0]\d{3})*[,.]\d{2}\s*€?$', t):
        return False
    # Un FRAGMENT DE LISTE DE VOTANTS n'est pas un titre non plus :
    # « (MM. ESPAZE, FIGUIERE) », « Mme ROUVERET) », « (M. ESPAZE), DECIDE ».
    # Le découpeur coupait au milieu du décompte des voix, séparant une
    # délibération de son propre vote.
    if t.startswith('(') or re.match(r'^(?:MM?|Mme|Mmes)\.?\s+[A-ZÀ-Ÿ]', t):
        return False
    if t.endswith(')') and re.search(r'\b(?:MM?\.|Mme|Mmes)\s', t):
        return False
    # Exclure les sous-items de listes d'associations ou de candidats (ligne courte + ":")
    if re.match(r'^[A-ZÀÂÇÉÈÊËÎÏÔÙÛÜ\s\'\-\.]+\s*:\s*$', t) and len(t) < 50:
        return False
    return True


def split_into_deliberations(paragraphs: list[str]) -> list[dict]:
    """
    Découpe la liste de paragraphes en blocs de délibération.
    Chaque bloc = {'titre': str, 'paragraphes': [str]}
    """
    blocks = []
    current = None

    for para in paragraphs:
        clean = para.replace('\xa0', ' ').strip()
        if not clean:
            continue
        if is_section_header(clean):
            if current and current['paragraphes']:
                blocks.append(current)
            current = {'titre': clean, 'paragraphes': []}
        elif current is not None:
            current['paragraphes'].append(clean)

    if current and current['paragraphes']:
        blocks.append(current)

    return blocks


# ── Parsing d'un fichier CM ────────────────────────────────────────────────────

# ── Ce qui a été retiré ───────────────────────────────────────────────────────
#
# `parse_cm_file`, `upsert_cm_to_db`, `upsert_deliberation` et `run_cm_parser`
# lisaient les comptes rendus HTML déposés dans `data/cm_records/` et écrivaient
# `source='lasalle.fr'` en dur. Rien de tout cela ne s'applique ici : les PV
# sont des PDF catalogués sur le site et traités par `conseils`. Les
# supprimer plutôt que les garder inertes évite qu'un appel distrait ne
# réinjecte le nom d'une autre commune comme source dans cette base.
#
# Ce module ne fournit plus que ses ANALYSEURS, réutilisés tels quels par
# `conseils` et `cm_ocr` : catégorisation d'un titre,
# extraction des votes, des montants, des noms, découpage par sections en
# capitales, et rattachement des personnes à un événement. C'est la partie qui
# s'est portée sans retouche.
# ─────────────────────────────────────────────────────────────────────────────

def _paragraphs_from_pdf(filepath: Path) -> list[str]:
    """Extrait les paragraphes d'un CR PDF (pdfplumber). 1 ligne non vide = 1 paragraphe."""
    import pdfplumber
    paragraphs = []
    with pdfplumber.open(str(filepath)) as pdf:
        for page in pdf.pages:
            txt = page.extract_text() or ""
            for line in txt.split('\n'):
                line = line.replace('\xa0', ' ').strip()
                if line:
                    paragraphs.append(line)
    return paragraphs


def _parse_french_date(text: str) -> str | None:
    m = re.search(
        r'(\d{1,2})\s+(janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre)\s+(\d{4})',
        text, re.IGNORECASE)
    if m:
        day  = m.group(1).zfill(2)
        mon  = _MOIS[m.group(2).lower()]
        year = m.group(3)
        return f"{year}-{mon}-{day}"
    return None


def _date_from_filename(name: str) -> str | None:
    # conseil-municipal-du-13-septembre-2023.html
    m = re.search(
        r'(\d{1,2})[-_](janvier|fevrier|février|mars|avril|mai|juin|juillet|aout|août|septembre|octobre|novembre|decembre|décembre)[-_](\d{4})',
        name, re.IGNORECASE)
    if m:
        day  = m.group(1).zfill(2)
        mon  = _MOIS[m.group(2).lower()]
        year = m.group(3)
        return f"{year}-{mon}-{day}"
    # conseil-municipal-du-19-06-2025.html
    m2 = re.search(r'(\d{2})[-_](\d{2})[-_](\d{4})', name)
    if m2:
        return f"{m2.group(3)}-{m2.group(2)}-{m2.group(1)}"
    # cm_2025-06-19.html
    m3 = re.search(r'(\d{4})[-_](\d{2})[-_](\d{2})', name)
    if m3:
        return f"{m3.group(1)}-{m3.group(2)}-{m3.group(3)}"
    return None


# ── Insertion en DB ───────────────────────────────────────────────────────────


def link_persons_to_event(conn: sqlite3.Connection, event_id: int, names: list[str], role: str = 'présent'):
    """
    Tente de lier les noms extraits aux entités DB (par lastname match).
    Insère dans event_entities.
    """
    c = conn.cursor()
    for name_raw in names:
        # Normaliser : extraire le NOM (dernier mot en majuscules)
        parts = name_raw.replace('M.', '').replace('Mme', '').strip().split()
        # Chercher par lastname (en majuscules)
        for part in parts:
            if len(part) >= 3 and part.isupper():
                c.execute("""SELECT p.entity_id FROM persons p
                             WHERE UPPER(p.lastname)=? LIMIT 1""", (part.upper(),))
                row = c.fetchone()
                if row:
                    c.execute("""INSERT OR IGNORE INTO event_entities (event_id, entity_id, role)
                                 VALUES (?,?,?)""", (event_id, row[0], role))
                    break


# ── Entrée principale ─────────────────────────────────────────────────────────


