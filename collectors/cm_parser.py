"""
Analyseurs de comptes rendus de conseil municipal.

Bibliothèque de fonctions, sans pipeline : catégorisation d'un titre de
délibération, extraction du vote, des montants et des noms cités, découpage
d'un texte en sections, rattachement des personnes à un événement.

Les collecteurs qui l'utilisent — `cm_brassac`, `ccsvp_scraper`, `cm_ocr` —
apportent chacun leur lecture de la source ; ce module ne connaît que du texte.
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
    """Retourne liste de {value: float, context: str}"""
    # Patterns : 1 234,56 € ou 1234.56€ ou 1 234 € (entier)
    pat = r'([\d][\d\s\xa0]*(?:[,.]\d{2,3})?)\s*€'
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

def extract_vote(text: str) -> dict | None:
    """Parse 'par X voix Pour et Y abstention(s)/contre'"""
    pat = (r'(?:par\s+)?(\d+)\s+voix\s+[«""]?\s*[Pp]our\s*[»""]?'
           r'(?:\s+et\s+(\d+)\s+(abstention|contre)s?)?'
           r'(?:\s+et\s+(\d+)\s+(abstention|contre)s?)?')
    m = re.search(pat, text, re.IGNORECASE)
    if not m:
        if re.search(r'à l.unanimité', text, re.IGNORECASE):
            return {'pour': None, 'contre': 0, 'abstentions': 0, 'unanimite': True}
        return None
    vote = {'pour': int(m.group(1)), 'contre': 0, 'abstentions': 0, 'unanimite': False}
    # parse optional groups
    for i in (2, 4):
        if m.group(i):
            n = int(m.group(i))
            typ = (m.group(i+1) or '').lower()
            if 'abstention' in typ:
                vote['abstentions'] = n
            elif 'contre' in typ:
                vote['contre'] = n
    # Named abstainers / against
    named = re.findall(r'\(([A-Z][A-Za-zÀ-ÿ\s\-]+)\)', text)
    if named:
        vote['nommés'] = named
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

_NOISE_PATTERNS = re.compile(
    r'^(PRÉSENTS?|ABSENTS?|PROCÈS-VERBAL|SECTION\s+D|SECTION\s+DE|RECETTES?|DÉPENSES?|TOTAL|'
    r'PAR\s+MOIS|FONCTIONNEMENT|INVESTISSEMENT|SOLDE|PARC\s+LOCAT|CHAUFFERIE\s+BOIS|'
    r'COMMUNE\s*:|CENTRE\s+(CULTUREL|DE|LOISIRS)|CG\s+EAU|SIAEP|EAU\s+SECT|'
    r'INESTISSEMENT|EXERCICE\s*$|A\s+REPRENDRE\s*$|SECTIONS?\s*$|RÉSULTAT\s*$|'
    r'COLOGNAC\s*$|LANUEJOLS\s*$|SOUDORGUES\s*$|VABRES\s*$|STE\s+CROIX|'
    r'DU\s+\d+\s+\w+\s+\d{4}|DU\s+\d{1,2}\s+\w+\s+\d{4}|'  # "DU 15 NOVEMBRE 2023"
    r'CANDIDATS\s*$|CLASSEMENT\s*$|DENOMINATION\s*$|'
    r'ANSEAUME|GARCIA|ARTIGUES|PIERESCHI|GIRAUD|COLAS\s+FRANCE|'
    r'PÔLE\s+MÉNAGE|PÉRIODE\s+SCOLAIRE|PÉRISCOLAIRE\s*$|SERVICE\s+(ADMIN|TECH|CULT)|'
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
# sont des PDF catalogués sur le site et traités par `cm_brassac`. Les
# supprimer plutôt que les garder inertes évite qu'un appel distrait ne
# réinjecte le nom d'une autre commune comme source dans cette base.
#
# Ce module ne fournit plus que ses ANALYSEURS, réutilisés tels quels par
# `cm_brassac`, `ccsvp_scraper` et `cm_ocr` : catégorisation d'un titre,
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


