"""
dirigeants_web.py — Extraire les dirigeants d'associations depuis leurs sites.

**Pourquoi cette voie.** Les dirigeants d'associations ne sont pas en open data
(vérifié : `recherche-entreprises` rend 0 dirigeant pour la nature juridique 9220,
le JO des associations n'a pas le champ, la déclaration en préfecture n'est pas
diffusée). En revanche **181 des 520 associations ont une URL en base**, et une
page « contact » ou « le bureau » nomme presque toujours le président.

Ce que les associations publient elles-mêmes sur leur propre site est
légitimement exploitable ; les résultats restent néanmoins côté atelier
(`relation_candidates`, `probable`) et ne sont donc pas publiés avant arbitrage.

**Deux sorties, parce que deux cas distincts :**
  - la personne existe déjà en base → candidat de relation, file de revue ;
  - elle n'existe pas → consignée dans `audits/dirigeants_web_a_creer.json`.
    On ne crée **pas** l'entité automatiquement : ce serait injecter dans la base
    des noms extraits d'un site par une regex, sans vérification.

L'extraction est d'abord **par motifs** (« Président : X », « présidée par X »),
ce qui est déterministe et vérifiable. `--gemma` ajoute une passe Gemma 4 locale
sur les pages où les motifs ne donnent rien : les sites d'associations présentent
souvent leur bureau dans un tableau ou une image légendée que la regex rate.

Usage :
  python3 -m collectors.dirigeants_web --dry-run
  python3 -m collectors.dirigeants_web --limit 20
  python3 -m collectors.dirigeants_web --gemma
  python3 -m collectors.dirigeants_web --entity-id 473
  python3 -m collectors.dirigeants_web --stats
"""
from __future__ import annotations

import argparse
import json
import re
import time
import unicodedata
from pathlib import Path

from .config import COMMUNE_NAME, DEPARTEMENT, REQUEST_DELAY, ROOT
from .db import get_conn
from .web_scraper import PageInfoParser, fetch, find_relevant_subpages

AUDITS = ROOT / "audits"
SIGNAL = "site_web_asso"
RELATION_DEFAUT = "dirigeant"

# Rôles reconnus → type de relation.
#
# L'ordre compte : « vice-président » doit précéder « président », sinon il est
# capté par lui. Et les variantes **accentuées ET féminines** doivent toutes être
# listées : la regex est bâtie sur ces chaînes littérales, si bien qu'oublier
# « présidente » ou « trésorière » fait rater silencieusement la moitié des
# bureaux d'association (constaté au test : « Mme Prénom NOM (présidente) »
# et « Trésorière : Marie Martin » n'étaient pas détectés).
ROLES = [
    ("vice-présidente", "membre_bureau"),
    ("vice-président", "membre_bureau"),
    ("vice-presidente", "membre_bureau"),
    ("vice-president", "membre_bureau"),
    ("co-présidente", "président"),
    ("co-président", "président"),
    ("présidente", "président"),
    ("président", "président"),
    ("presidente", "président"),
    ("president", "président"),
    # Formes participiales : « association présidée par X ».
    ("présidée par", "président"),
    ("présidé par", "président"),
    ("dirigée par", "dirigeant"),
    ("dirigé par", "dirigeant"),
    ("trésorière", "trésorier"),
    ("trésorier", "trésorier"),
    ("tresoriere", "trésorier"),
    ("tresorier", "trésorier"),
    ("secrétaire générale", "secrétaire"),
    ("secrétaire général", "secrétaire"),
    ("secrétaire", "secrétaire"),
    ("secretaire", "secrétaire"),
    ("directrice", "dirigeant"),
    ("directeur", "dirigeant"),
    ("gérante", "gérant"),
    ("gérant", "gérant"),
    ("responsable", "responsable"),
    ("fondatrice", "dirigeant"),
    ("fondateur", "dirigeant"),
]

# Un nom propre français : deux à cinq mots capitalisés ou en capitales, avec
# particules en minuscules (« Pierre de Cazenove », « Paul Le Goff »).
# `\b` après chaque particule est indispensable : sans lui, l'alternative « de »
# mordait sur « depuis » et le nom capturé devenait « Pierre de Cazenove de ».
#
# ⚠️ Le groupe est encadré de `(?-i: … )` pour **annuler `re.IGNORECASE`** sur
# cette portion. Les motifs sont insensibles à la casse pour capter « Président »
# comme « président », mais ce flag rendait `[A-ZÀ-Ý]` équivalent à n'importe
# quelle lettre : « depuis » passait alors pour un mot de nom propre et
# « présidée par Pierre de Cazenove depuis 2020 » rendait « Pierre de Cazenove
# depuis ». La casse est précisément ce qui distingue un patronyme d'un mot
# ordinaire : elle doit rester significative ici.
_PART = r"(?:de|du|des|le|la|von|van)\b"
_NOM = (r"(?-i:(?:[A-ZÀ-Ý][\w'’\-]+|%s\s)"
        r"(?:\s+(?:[A-ZÀ-Ý][\w'’\-]+|%s))*)" % (_PART, _PART))

# « Président : Jean Dupont », « Secrétaire Paul Le Goff »
#
# Le séparateur autorise **le deux-points ou l'espace, jamais la virgule ni le
# tiret** : ceux-là séparent deux entrées d'une liste de bureau. Avec
# `[\s:,–—-]*`, la chaîne « Jean-Luc MARTIN, président — Anne SEO, trésorière »
# rapprochait « président » de « Anne SEO », lui attribuant le rôle du voisin.
_APRES = re.compile(
    r"\b(?P<role>%s)\b(?:\s*:\s*|\s+)"
    r"(?:M\.|Mme|Mlle|Monsieur|Madame)?\s*"
    r"(?P<nom>%s)" % ("|".join(re.escape(r) for r, _ in ROLES), _NOM),
    re.IGNORECASE)

# « Jean Dupont, président », « Marie Martin (présidente) »
_AVANT = re.compile(
    r"(?P<nom>%s)\s*[,(–—-]\s*(?:le\s+|la\s+)?(?P<role>%s)\b" % (
        _NOM, "|".join(re.escape(r) for r, _ in ROLES)),
    re.IGNORECASE)

# Mots qui ne sont jamais un nom de personne mais suivent souvent un rôle.
# Les particules (« de », « le », « du ») n'y figurent PAS : « Paul Le Goff » et
# « Pierre de Cazenove » sont des noms parfaitement valides, et les exclure
# faisait rater tous les patronymes à particule.
_FAUX_NOMS = {
    "ASSOCIATION", "CLUB", "COMITE", "BUREAU", "CONSEIL", "ADMINISTRATION",
    "MEMBRES", "MEMBRE", "CONTACT", "CONTACTS", "MAIRIE", "COMMUNE", "SEANCE",
    "REUNION", "ORDRE", "JOUR", "STATUTS", "ELU", "ELUE", "SORTANT", "SORTANTE",
    "ADJOINT", "MAIRE", "TRESORERIE", "SECRETARIAT", "EQUIPE", "ACCUEIL",
    "HORAIRES", "ADHESION", "COTISATION", "NOUS", "VOUS", "NOTRE", "SITE",
}

# Particules de patronyme : légitimes dans un nom, mais elles ne comptent pas
# comme un « vrai » mot pour juger de la plausibilité.
_PARTICULES = {"DE", "DU", "DES", "LE", "LA", "VON", "VAN", "D", "L"}

# Civilités à retirer du nom capturé : « Mme Prénom NOM » → « Prénom NOM ».
_CIVILITES = re.compile(r"^(?:M\.|MM\.|Mme|Mmes|Mlle|Monsieur|Madame|"
                        r"Mademoiselle)\s+", re.IGNORECASE)

# Mots grammaticaux capitalisés en début de phrase, qui se collent au nom quand
# le motif « nom, rôle » démarre sur un début de phrase : sur un site réel,
# « Pour contacter Xavier Perret (président) » donnait « Pour Xavier Perret ».
_AMORCES = re.compile(
    r"^(?:Pour|Avec|Dans|Depuis|Notre|Nos|Votre|Vos|Cette|Ce|Les|Le|La|Un|Une|"
    r"Contacter|Contact|Voir|Lire|Suivez|Merci|Bonjour|Ici|Tous|Toute)\s+",
    re.IGNORECASE)

# Sous-pages où le bureau est décrit. Plus ciblé que la liste générique de
# `web_scraper`, qui cherche aussi l'agenda et les actualités.
_PAGES_BUREAU = ["bureau", "membres", "équipe", "equipe", "conseil", "contact",
                 "qui-sommes", "qui sommes", "présentation", "presentation",
                 "à propos", "a-propos", "about", "association", "statuts"]


def norm(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return " ".join(s.upper().replace("-", " ").replace("'", " ").split())


def role_relation(role: str) -> str:
    r = norm(role)
    for motif, relation in ROLES:
        if norm(motif) == r:
            return relation
    return RELATION_DEFAUT


def nettoyer_nom(nom: str) -> str:
    """Retire civilité et amorces de phrase, normalise les espaces."""
    n = (nom or "").strip()
    n = _CIVILITES.sub("", n)
    # Répété : « Pour Contacter Xavier Perret » porte deux amorces.
    for _ in range(3):
        nouveau = _AMORCES.sub("", n)
        if nouveau == n:
            break
        n = nouveau
    return " ".join(n.split())


def nom_plausible(nom: str) -> bool:
    """Écarte les faux positifs les plus fréquents de l'extraction par motifs."""
    mots = norm(nom).split()
    if not 2 <= len(mots) <= 5:
        return False            # « Président : Contact », ou une phrase entière
    if any(m in _FAUX_NOMS for m in mots):
        return False
    if any(any(c.isdigit() for c in m) for m in mots):
        return False
    # Au moins deux mots « pleins » : « Le Goff » seul ne suffit pas, mais
    # « Paul Le Goff » et « Pierre de Cazenove » passent.
    pleins = [m for m in mots if m not in _PARTICULES]
    return len(pleins) >= 2 and all(len(m) >= 2 for m in pleins)


def extraire_roles(texte: str) -> list[dict]:
    """(role, nom) trouvés dans un texte, dédupliqués.

    `_APRES` (« Trésorière : Marie Martin ») est appliqué d'abord et ses zones
    sont **réservées**. Sans cela, `_AVANT` relit la même phrase à l'envers : dans
    « Trésorière : Marie Martin, Secrétaire Paul Le Goff », il rapproche « Marie
    Martin » du mot « Secrétaire » qui suit et lui attribue le mauvais rôle. Les
    bureaux d'association étant presque toujours écrits en liste, l'erreur serait
    systématique.
    """
    texte = texte or ""
    trouves: dict[tuple[str, str], dict] = {}
    zones: list[tuple[int, int]] = []

    def ajouter(m, role: str):
        nom = nettoyer_nom(m.group("nom"))
        if not nom_plausible(nom):
            return False
        cle = (norm(nom), role_relation(role))
        trouves.setdefault(cle, {
            "nom": nom, "role_brut": role.lower(),
            "relation": role_relation(role),
            "extrait": " ".join(texte[max(0, m.start() - 60):m.end() + 40].split()),
        })
        return True

    for m in _APRES.finditer(texte):
        if ajouter(m, m.group("role")):
            zones.append((m.start(), m.end()))

    for m in _AVANT.finditer(texte):
        deb, fin = m.span("nom")
        if any(deb < z_fin and fin > z_deb for z_deb, z_fin in zones):
            continue                    # nom déjà attribué par `_APRES`
        ajouter(m, m.group("role"))

    return list(trouves.values())


def gemma_bureau(nom_asso: str, texte: str) -> list[dict]:
    """Passe Gemma 4 locale : le bureau est souvent dans un tableau ou une image.

    On demande du JSON strict et on ignore tout ce qui n'est pas exploitable :
    une sortie approximative ne doit pas polluer la file de revue.
    """
    import subprocess
    if not texte or len(texte) < 120:
        return []
    prompt = (
        f"Voici le texte du site de l'association « {nom_asso} » "
        f"({COMMUNE_NAME}, département {DEPARTEMENT}).\n\n"
        f"{texte[:3000]}\n\n"
        "Liste UNIQUEMENT les personnes présentées comme dirigeantes de cette "
        "association (président, vice-président, trésorier, secrétaire, directeur). "
        "Réponds en JSON strict, sans texte autour : "
        '[{"nom": "Prénom Nom", "role": "président"}]. '
        "Si aucune n'est nommée, réponds []."
    )
    try:
        r = subprocess.run(["ollama", "run", "gemma4:26b", prompt],
                           capture_output=True, text=True, timeout=180)
        sortie = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", r.stdout)
        if "...done thinking." in sortie:
            sortie = sortie.split("...done thinking.")[-1]
        bloc = re.search(r"\[.*\]", sortie, re.S)
        if not bloc:
            return []
        data = json.loads(bloc.group(0))
    except Exception as e:
        print(f"    [gemma] {e}")
        return []

    res = []
    for x in data if isinstance(data, list) else []:
        nom = str((x or {}).get("nom") or "").strip()
        role = str((x or {}).get("role") or "").strip()
        if nom and nom_plausible(nom):
            res.append({"nom": nom, "role_brut": role or "dirigeant",
                        "relation": role_relation(role), "extrait": "(Gemma)"})
    return res


# Domaines qui ne sont jamais le site propre d'une association. Sans ce filtre,
# le collecteur scrapait la fiche que la MAIRIE consacre à l'association
# (`lasalle.fr/node/591`), un article de presse, un annuaire — et pour l'USEP de
# Lasalle carrément `trouville.fr`, commune de Normandie (URL manifestement
# fausse, cf. BUG-3 « URLs assignées à de mauvaises entités »).
# Les réseaux sociaux nomment souvent le bureau mais sont derrière un mur
# d'authentification : inutile de les fetcher.
# Les sites officiels de l'instance en font partie : une page de mairie qui
# parle d'une association n'est pas le site de cette association.
def _domaines_officiels() -> set[str]:
    import urllib.parse
    from .config import COMMUNE_URL, EPCI_URL
    return {urllib.parse.urlparse(u).netloc.removeprefix("www.")
            for u in (COMMUNE_URL, EPCI_URL) if u}


DOMAINES_EXCLUS = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "tiktok.com", "helloasso.com",
    # Annuaires et agrégateurs : ils citent l'association sans être son site.
    "monbeauvillage.fr",
    "infonet.fr", "assoce.fr", "annuaire-mairie.fr", "acte-deces.fr",
    "entreprises.lefigaro.fr", "societe.com", "pappers.fr", "pagesjaunes.fr",
    "resultats-municipales-2026.fr", "journal-officiel.gouv.fr",
    "data.gouv.fr", "net1901.org", "repertoiredesassociations.fr",
} | _domaines_officiels()


def _domaine(url: str) -> str:
    from urllib.parse import urlparse
    d = urlparse(url if url.startswith("http") else "https://" + url).netloc.lower()
    return d.removeprefix("www.")


def url_exploitable(url: str) -> bool:
    """Une URL susceptible d'être le site propre de l'association."""
    if not url or not url.startswith(("http://", "https://")):
        return False
    d = _domaine(url)
    return not any(d == x or d.endswith("." + x) for x in DOMAINES_EXCLUS)


def associations_avec_url(conn, entity_id: int | None = None,
                          limit: int | None = None,
                          tous_statuts: bool = False) -> list[dict]:
    """Associations ayant une URL exploitable, les subventionnées d'abord.

    L'ordre n'est pas cosmétique : ce sont les bénéficiaires d'argent public qui
    débloquent le graphe public.

    ⚠️ **Le rendement de ce collecteur est plafonné par la file de validation des
    URLs**, pas par l'extraction : `entity_websites` compte 1 777 URLs
    `candidate` pour seulement **27 `validated`**, et le palmarès des domaines est
    Facebook, Instagram, LinkedIn et des annuaires. Passer la queue
    `/atelier/queue/websites` est le préalable — sinon on scrape des pages qui ne
    parlent pas de l'association.
    """
    statuts = ("validated", "candidate") if tous_statuts else ("validated",)
    sql = f"""
        SELECT e.id, e.name, w.url, w.status,
               COALESCE((SELECT SUM(f.amount) FROM financial_flows f
                          WHERE f.to_id = e.id
                            AND COALESCE(f.perimetre,'detail')='detail'), 0) AS recu
        FROM entities e
        JOIN associations a ON a.entity_id = e.id
        JOIN entity_websites w ON w.entity_id = e.id
        WHERE w.status IN ({",".join("?" for _ in statuts)})
    """
    params: list = list(statuts)
    if entity_id:
        sql += " AND e.id = ?"
        params.append(entity_id)
    # `validated` d'abord, puis les plus subventionnées.
    sql += " ORDER BY (w.status='validated') DESC, recu DESC, e.name"
    lignes, vus = [], set()
    for r in conn.execute(sql, params):
        if r["id"] in vus or not url_exploitable(r["url"]):
            continue
        vus.add(r["id"])
        lignes.append(dict(r))
        if limit and len(lignes) >= int(limit):
            break
    return lignes


def index_personnes(conn) -> dict[str, int]:
    idx: dict[str, int] = {}
    for r in conn.execute("SELECT id, name FROM entities WHERE type='person'"):
        idx.setdefault(norm(r["name"]), r["id"])
    return idx


def _liens_existants(conn) -> set[tuple[int, int]]:
    paires = {(r["from_id"], r["to_id"]) for r in conn.execute(
        "SELECT from_id, to_id FROM relations WHERE relation_type IN"
        " ('dirigeant','président','gérant','trésorier','secrétaire','membre',"
        " 'membre_bureau','responsable')")}
    return paires | {(b, a) for a, b in paires}


def texte_du_site(url: str, max_pages: int = 4) -> str:
    """Texte de la page d'accueil et des sous-pages décrivant le bureau."""
    html = fetch(url)
    if not html:
        return ""
    parseur = PageInfoParser()
    parseur.feed(html)
    morceaux = [parseur.full_text]

    # `find_relevant_subpages` de web_scraper cible aussi agenda et actualités ;
    # on filtre sur les pages susceptibles de décrire le bureau.
    for lien in find_relevant_subpages(html, url, max_pages=8):
        if not any(k in lien.lower() for k in _PAGES_BUREAU):
            continue
        time.sleep(REQUEST_DELAY)
        sous = fetch(lien)
        if not sous:
            continue
        p = PageInfoParser()
        p.feed(sous)
        morceaux.append(p.full_text)
        if len(morceaux) > max_pages:
            break
    return "\n".join(m for m in morceaux if m)


def run(entity_id: int | None = None, limit: int | None = None,
        use_gemma: bool = False, dry_run: bool = False) -> dict:
    conn = get_conn()
    AUDITS.mkdir(exist_ok=True)
    try:
        cibles = associations_avec_url(conn, entity_id, limit)
        personnes = index_personnes(conn)
        existants = _liens_existants(conn)
        print(f"[dirigeants_web] {len(cibles)} associations avec URL "
              f"(subventionnées d'abord){' — Gemma actif' if use_gemma else ''}")

        candidats, a_creer, sans_rien = [], [], 0
        for a in cibles:
            texte = texte_du_site(a["url"])
            if not texte:
                sans_rien += 1
                continue
            trouves = extraire_roles(texte)
            if not trouves and use_gemma:
                trouves = gemma_bureau(a["name"], texte)
            if not trouves:
                sans_rien += 1
                print(f"  · {a['name'][:38]:<38} aucun dirigeant repéré")
                continue

            for t in trouves:
                pid = personnes.get(norm(t["nom"]))
                ligne = {**t, "association": a["name"], "entity_id": a["id"],
                         "url": a["url"], "recu": a["recu"]}
                if pid and (pid, a["id"]) not in existants:
                    candidats.append({**ligne, "from_id": pid})
                elif pid:
                    pass                     # lien déjà connu, rien à proposer
                else:
                    a_creer.append(ligne)
            print(f"  ✓ {a['name'][:38]:<38} "
                  f"{len(trouves)} rôle(s) : "
                  + ", ".join(f"{t['nom']} ({t['relation']})" for t in trouves[:3]))
            time.sleep(REQUEST_DELAY)

        print(f"\n  candidats de relation (personne connue) : {len(candidats)}")
        print(f"  personnes à créer (nom inconnu en base)  : {len(a_creer)}")
        print(f"  sites sans dirigeant repéré              : {sans_rien}")

        if dry_run:
            for c in candidats[:15]:
                print(f"     {c['nom'][:24]:<24} —{c['relation']}→ {c['association'][:30]}")
            print("\n=== DRY-RUN — rien écrit ===")
            return {"candidats": len(candidats), "a_creer": len(a_creer), "ecrits": 0}

        n = 0
        for c in candidats:
            detail = (f"Site de l'association ({c['url']}) : « {c['role_brut']} ». "
                      f"Extrait : {c['extrait'][:180]}")
            cur = conn.execute(
                "INSERT OR IGNORE INTO relation_candidates"
                " (from_id, to_id, relation_type, confidence, signal, signal_detail, score)"
                " VALUES (?,?,?,'probable',?,?,?)",
                (c["from_id"], c["entity_id"], c["relation"], SIGNAL, detail,
                 90 if c["extrait"] != "(Gemma)" else 70))
            n += cur.rowcount
        conn.commit()

        (AUDITS / "dirigeants_web_a_creer.json").write_text(json.dumps({
            "note": "Dirigeants nommés sur le site de l'association mais absents "
                    "de la base. L'entité personne n'est PAS créée "
                    "automatiquement : vérifier puis saisir à l'atelier.",
            "personnes": sorted(a_creer, key=lambda x: -(x["recu"] or 0)),
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"\n{n} candidats ajoutés à la file de revue "
              f"({len(candidats) - n} déjà présents)")
        print(f"à créer à la main : audits/dirigeants_web_a_creer.json")
        return {"candidats": len(candidats), "a_creer": len(a_creer), "ecrits": n}
    finally:
        conn.close()


def stats():
    conn = get_conn()
    try:
        for r in conn.execute(
            "SELECT review_status, COUNT(*) n FROM relation_candidates"
            " WHERE signal=? GROUP BY 1", (SIGNAL,)):
            print(f"  {r['review_status']:<10} {r['n']}")
        for r in conn.execute("""
            SELECT rc.score, rc.relation_type, f.name AS personne, t.name AS asso
            FROM relation_candidates rc
            JOIN entities f ON f.id = rc.from_id
            JOIN entities t ON t.id = rc.to_id
            WHERE rc.signal=? AND rc.review_status='pending'
            ORDER BY rc.score DESC LIMIT 30""", (SIGNAL,)):
            print(f"    {r['score']:>3}  {r['personne'][:24]:<24} "
                  f"—{r['relation_type']}→ {r['asso'][:30]}")
        p = AUDITS / "dirigeants_web_a_creer.json"
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            print(f"\n  {len(d.get('personnes', []))} personnes à créer "
                  f"(audits/dirigeants_web_a_creer.json)")
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--entity-id", type=int, help="une seule association")
    ap.add_argument("--limit", type=int, help="limiter le nombre de sites")
    ap.add_argument("--gemma", action="store_true",
                    help="passe Gemma 4 locale quand les motifs ne donnent rien")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()
    if args.stats:
        stats()
        return
    run(entity_id=args.entity_id, limit=args.limit,
        use_gemma=args.gemma, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
