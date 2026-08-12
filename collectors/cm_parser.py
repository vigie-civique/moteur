"""
Parseur exhaustif des comptes-rendus CM (HTML lasalle.fr).

Pour chaque CM archivé dans data/cm_records/ :
  - Extrait les présents/absents/pouvoirs
  - Découpe en délibérations individuelles (sections en MAJUSCULES)
  - Pour chaque délibération : titre, texte complet, vote, montants, catégorie
  - Insère dans events (1 ligne par délibération) + event_entities (présents/cités)
  - Lie les flux financiers déjà connus aux bonnes délibérations
"""

import os, re, json, sqlite3
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup

CM_DIR   = Path(__file__).parent.parent / "data" / "cm_records"
DB_PATH  = Path(__file__).parent.parent / "db" / "lasalle.db"

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

def _paragraphs_from_html(soup) -> list[str]:
    """
    Extrait les paragraphes d'un CR HTML.
    1) Voie normale : <article>/<main> via <p>/<li>/<h2..6>.
    2) Fallback : si trop peu de paragraphes (layout en <span>, ex. CR 2026
       lasalle.fr), on extrait tous les nœuds-feuilles porteurs de texte du body
       (span/strong/p/li/h2..6) dans l'ordre du document.
    """
    article = soup.find('article')
    if not article:
        article = soup.find('main') or soup.body

    paragraphs = []
    if article:
        for tag in article.find_all(['p', 'li', 'h2', 'h5', 'h6']):
            t = tag.get_text(separator=' ').replace('\xa0', ' ').strip()
            if t:
                paragraphs.append(t)

    if len(paragraphs) < 5:  # layout non standard → fallback spans
        body = soup.body or soup
        paragraphs = []
        for tag in body.find_all(['span', 'strong', 'p', 'li', 'h2', 'h3', 'h5', 'h6']):
            if tag.find(['span', 'strong', 'p', 'li']):  # éviter les conteneurs (doublons)
                continue
            t = tag.get_text(separator=' ').replace('\xa0', ' ').strip()
            if t:
                paragraphs.append(t)
    return paragraphs


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


def parse_cm_file(filepath: Path) -> dict:
    """Parse un fichier CM (HTML ou PDF). Retourne un dict complet."""
    if filepath.suffix.lower() == '.pdf':
        paragraphs = _paragraphs_from_pdf(filepath)
        soup = None
    else:
        html = filepath.read_text(encoding='utf-8', errors='replace')
        soup = BeautifulSoup(html, 'html.parser')
        paragraphs = _paragraphs_from_html(soup)

    # Date depuis le nom de fichier (fallback : chercher dans le texte)
    date = _date_from_filename(filepath.name)
    if not date:
        for p in paragraphs[:10]:
            m = re.search(r'(\d{1,2})\s+(janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+(\d{4})', p, re.IGNORECASE)
            if m:
                date = _parse_french_date(m.group(0))
                break

    # Présents/absents
    attendees = parse_attendees(paragraphs)

    # Délibérations
    deliberations = split_into_deliberations(paragraphs)
    parsed_delibs = []
    for d in deliberations:
        full_text = '\n'.join(d['paragraphes'])
        vote = extract_vote(full_text)
        amounts = extract_amounts(full_text)
        cat, tags = categorize(d['titre'])
        cited_names = extract_names(full_text)
        parsed_delibs.append({
            'titre': d['titre'],
            'texte': full_text[:4000],  # tronqué à 4000 chars pour la DB
            'vote': vote,
            'montants': amounts[:20],
            'categorie': cat,
            'tags': tags,
            'personnes_citees': list(set(cited_names)),
        })

    return {
        'date': date,
        'fichier': filepath.name,
        'source_url': f"https://www.lasalle.fr/CR/{filepath.stem}",
        'presents': attendees['presents'],
        'absents': attendees['absents'],
        'pouvoirs': attendees['pouvoirs'],
        'nb_deliberations': len(parsed_delibs),
        'deliberations': parsed_delibs,
    }


# ── Helpers date ──────────────────────────────────────────────────────────────

_MOIS = {
    'janvier':'01','février':'02','fevrier':'02','mars':'03','avril':'04',
    'mai':'05','juin':'06','juillet':'07','août':'08','aout':'08',
    'septembre':'09','octobre':'10','novembre':'11','décembre':'12','decembre':'12'
}

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

def upsert_cm_to_db(conn: sqlite3.Connection, cm: dict) -> int:
    """
    Insère ou met à jour le CM principal dans events.
    Retourne l'event_id du CM principal.
    """
    c = conn.cursor()
    date = cm['date']

    meta = {
        'fichier': cm['fichier'],
        'nb_deliberations': cm['nb_deliberations'],
        'presents': cm['presents'],
        'absents': cm['absents'],
        'pouvoirs': cm['pouvoirs'],
    }

    # Résumé automatique des délibérations
    summary_lines = []
    for d in cm['deliberations']:
        line = d['titre']
        if d['vote']:
            v = d['vote']
            if v.get('unanimite'):
                line += ' [unanimité]'
            else:
                line += f" [{v.get('pour','?')} pour"
                if v.get('abstentions'):
                    line += f", {v['abstentions']} abst."
                if v.get('contre'):
                    line += f", {v['contre']} contre"
                line += ']'
        summary_lines.append(line)
    content = '\n'.join(summary_lines)

    # Vérifier si un event CM existe déjà pour cette date
    c.execute("SELECT id FROM events WHERE date=? AND type='deliberation' AND title LIKE 'CM du%'", (date,))
    row = c.fetchone()
    if row:
        event_id = row[0]
        c.execute("""UPDATE events SET content=?, metadata=?, source='lasalle.fr', source_url=?
                     WHERE id=?""",
                  (content, json.dumps(meta, ensure_ascii=False), cm['source_url'], event_id))
    else:
        c.execute("""INSERT INTO events (type,date,title,content,source,source_url,metadata)
                     VALUES ('deliberation',?,?,?,'lasalle.fr',?,?)""",
                  (date, f"CM du {date}", content,
                   cm['source_url'], json.dumps(meta, ensure_ascii=False)))
        event_id = c.lastrowid

    return event_id


def upsert_deliberation(conn: sqlite3.Connection, cm_date: str, cm_url: str, delib: dict) -> int:
    """Insère une délibération individuelle dans events. Retourne son id."""
    c = conn.cursor()

    meta = {
        'categorie': delib['categorie'],
        'tags': delib['tags'],
        'vote': delib['vote'],
        'montants': delib['montants'],
        'personnes_citees': delib['personnes_citees'],
    }

    title = delib['titre'][:255]
    c.execute("""SELECT id FROM events WHERE date=? AND title=? AND type='deliberation'""",
              (cm_date, title))
    row = c.fetchone()
    if row:
        eid = row[0]
        c.execute("""UPDATE events SET content=?, metadata=?, source='lasalle.fr', source_url=?
                     WHERE id=?""",
                  (delib['texte'], json.dumps(meta, ensure_ascii=False), cm_url, eid))
    else:
        c.execute("""INSERT INTO events (type,date,title,content,source,source_url,metadata)
                     VALUES ('deliberation',?,?,?,'lasalle.fr',?,?)""",
                  (cm_date, title, delib['texte'],
                   cm_url, json.dumps(meta, ensure_ascii=False)))
        eid = c.lastrowid

    return eid


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

def _peek_pdf_date(filepath: Path) -> str | None:
    """Date d'un PDF dont le nom ne contient pas de date parsable (1ère page)."""
    try:
        import pdfplumber
        with pdfplumber.open(str(filepath)) as pdf:
            txt = (pdf.pages[0].extract_text() or "")[:1500] if pdf.pages else ""
        return _parse_french_date(txt)
    except Exception:
        return None


def run_cm_parser(verbose: bool = True) -> dict:
    """Parse tous les CMs (HTML + PDF) et insère en DB."""
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    # Fichiers candidats : HTML + PDF dans cm_records/ et cm_records_pdf/
    candidates = list(CM_DIR.glob("*.html")) + list(CM_DIR.glob("*.pdf"))
    pdf_dir = CM_DIR.parent / "cm_records_pdf"
    if pdf_dir.exists():
        candidates += list(pdf_dir.glob("*.pdf"))
    candidates = sorted(set(candidates))

    # Dédupliquer par date : garder le fichier le plus volumineux (le plus complet)
    by_date: dict[str, Path] = {}
    for f in candidates:
        date = _date_from_filename(f.name)
        if not date and f.suffix.lower() == '.pdf':
            date = _peek_pdf_date(f)
        if date:
            if date not in by_date or f.stat().st_size > by_date[date].stat().st_size:
                by_date[date] = f

    stats = {
        'cms_traites': 0,
        'deliberations_inserees': 0,
        'event_entities_inserees': 0,
        'erreurs': [],
    }

    for date, filepath in sorted(by_date.items()):
        try:
            if verbose:
                print(f"  Parsing {date} — {filepath.name} ...")
            cm = parse_cm_file(filepath)
            cm['date'] = date  # forcer la date extraite du nom

            # CM principal
            cm_event_id = upsert_cm_to_db(conn, cm)

            # Présents → event_entities
            for name in cm['presents']:
                link_persons_to_event(conn, cm_event_id, [name], 'présent')
            for name in cm['absents']:
                link_persons_to_event(conn, cm_event_id, [name], 'absent')

            # Délibérations individuelles
            for delib in cm['deliberations']:
                # Filtrer les titres non-délibérations
                if delib['titre'] in ('QUESTIONS DIVERSES', 'INFORMATIONS', 'INFORMATION'):
                    # garder mais ne pas créer d'event individuel vide
                    if not delib['texte'].strip():
                        continue

                eid = upsert_deliberation(conn, date, cm['source_url'], delib)
                stats['deliberations_inserees'] += 1

                # Lier les personnes citées dans la délibération
                all_names = list(set(cm['presents'] + delib['personnes_citees']))
                link_persons_to_event(conn, eid, all_names, 'cité')
                stats['event_entities_inserees'] += 1

            stats['cms_traites'] += 1
            if verbose:
                print(f"    → {cm['nb_deliberations']} délibérations, {len(cm['presents'])} présents")

        except Exception as e:
            import traceback
            stats['erreurs'].append({'fichier': filepath.name, 'erreur': str(e)})
            if verbose:
                print(f"    ERREUR: {e}")
                traceback.print_exc()

    conn.commit()
    conn.close()
    return stats


if __name__ == '__main__':
    print("[cm_parser] Parsing des CMs...")
    stats = run_cm_parser(verbose=True)
    print(f"\n[cm_parser] Terminé :")
    print(f"  CMs traités       : {stats['cms_traites']}")
    print(f"  Délibérations     : {stats['deliberations_inserees']}")
    print(f"  Event_entities    : {stats['event_entities_inserees']}")
    if stats['erreurs']:
        print(f"  Erreurs ({len(stats['erreurs'])}) :")
        for e in stats['erreurs']:
            print(f"    {e['fichier']}: {e['erreur']}")
