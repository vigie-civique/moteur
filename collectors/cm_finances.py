"""
cm_finances.py — Extraction financière depuis le contenu des CR des assemblées.

Les CR contiennent des flux financiers réguliers non encore structurés (surtout
avant 2024). Ce collecteur les extrait du texte des événements délibérés et les
insère dans `financial_flows`, en RÉUTILISANT les entités existantes (résolveur
de noms — pas de doublon) plutôt qu'en les recréant.

Les DEUX assemblées sont lues, et chaque flux porte celle qui l'a voté. Le
collecteur ne lisait que la commune : sur Lasalle, 1 287 délibérations
communautaires étaient collectées, 211 mentionnaient une subvention, et pas une
n'a jamais été lue — l'argent que l'intercommunalité verse aux associations du
territoire n'existait nulle part dans la base.

Extraction automatique (haute confiance, motif régulier) :
  - subventions aux associations : « attribuer à X une subvention de N € »

Détection + rapport (pour curation manuelle, motifs moins réguliers ou enjeux
de nommage de particuliers) :
  - cessions de patrimoine, baux/loyers, aides façade

Idempotent : dédoublonne contre les flux déjà présents (type+année+montant+bénéficiaire).

Usage :
  python3 -m collectors.cm_finances --dry-run     # aperçu (résolution + doublons)
  python3 -m collectors.cm_finances               # insère les subventions résolues
  python3 -m collectors.cm_finances --report      # + rapport cessions/baux/aides
"""
from __future__ import annotations

import argparse
import re
import unicodedata

from .config import COMMUNE_URL, EPCI_URL
from .db import transaction, get_conn, upsert_entity, pivot_ids


# ── Quelle assemblée a voté ? ─────────────────────────────────────────────────
#
# Les quatre types d'actes délibérés. `approbations.py` lit déjà les quatre ;
# celui-ci n'en lisait que deux.
TYPES_DELIBERES = ("deliberation", "conseil_municipal",
                   "deliberation_cc", "conseil_communautaire")

_TYPES_CC = {"deliberation_cc", "conseil_communautaire"}

_EN_TYPES = ",".join("?" * len(TYPES_DELIBERES))


def _domaine(url: str | None) -> str:
    """Domaine nu d'une adresse ou d'un libellé de source, sans `www.`."""
    d = (url or "").strip().lower()
    d = d.split("://", 1)[-1].split("/", 1)[0].split("?", 1)[0]
    return d[4:] if d.startswith("www.") else d


def payeur(event_type: str | None, source: str | None) -> str:
    """Clé `pivot_ids` de l'assemblée qui a voté l'acte : `commune` ou `epci`.

    Le TYPE prime — une délibération du conseil communautaire est
    intercommunale même quand elle ne cite que des acteurs de la commune, c'est
    l'EPCI qui l'a votée. C'est la règle de `portee_evenement` au snapshot, et
    il ne doit pas y en avoir deux.

    Mais le type ne suffit pas, et c'est le piège de ce collecteur : sur
    l'instance de référence, 44 séances du conseil COMMUNAUTAIRE portent le
    type `conseil_municipal` — résidu du redécoupage qui enregistrait en portée
    commune les procès-verbaux de l'intercommunalité présents en cache
    (833 actes en double, corrigé le 07/09/2026). Les 44 conteneurs de séance
    ont survécu à la purge, chacun avec un jumeau `conseil_communautaire` sur la
    même URL. Les croire sur parole ferait payer par la commune des subventions
    votées par l'EPCI : deux assemblées sous un même compteur, et un lecteur qui
    en conclut une mairie plus dépensière qu'elle ne l'est.

    L'ÉDITEUR tranche donc quand le type dit « commune ». Il est lu dans la
    colonne `source` de la base — jamais recalculé depuis l'URL, un PV repêché
    sur web.archive.org restant publié par la collectivité qui l'avait mis en
    ligne.
    """
    if (event_type or "") in _TYPES_CC:
        return "epci"
    src = _domaine(source)
    if src and EPCI_URL and src == _domaine(EPCI_URL) and src != _domaine(COMMUNE_URL):
        return "epci"
    return "commune"


def _clean_benef(name: str) -> str:
    """Nettoie un nom de bénéficiaire extrait pour créer une entité lisible."""
    s = _deapos(name)
    s = re.sub(r"[«»\"']", "", s).strip()
    s = re.sub(r"^(l['’]?\s*association|association|amicale|club|l['’])\s+", "", s, flags=re.I).strip()
    s = re.sub(r"\s+", " ", s)
    return s[:80] or name

# ── Résolveur de noms → entité existante ───────────────────────────────────────

_STOP = {"de", "des", "du", "la", "le", "les", "l", "d", "et", "a", "au", "aux",
         "pour", "association", "asso"}

def _deapos(s: str) -> str:
    return s.replace("’", "'").replace("‘", "'").replace("`", "'")


# Alias pour les cas non résolus automatiquement (nom extrait → nom d'entité).
# Ce registre est de la SAISIE locale : il rapprochait « ape » de
# « ASSOCIATION DE PARENTS D'ELEVES DES ECOLES PUBLIQUES DE LASALLE ». Rejoué
# ailleurs, il ne rapproche rien — au mieux. Il se remplit donc dans
# config/seed_local.json, clé `alias_associations`, au fil des rapprochements
# constatés à l'atelier.
def _charger_alias() -> dict:
    import json as _json
    from pathlib import Path as _Path
    chemin = _Path(__file__).resolve().parent.parent / "config" / "seed_local.json"
    try:
        seed = _json.loads(chemin.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}
    return {k.lower(): v for k, v in (seed.get("alias_associations") or {}).items()}


ALIASES = _charger_alias()


# Les mots qui NOMMENT une forme de groupement plutôt que le groupement. Leur
# absence d'un côté ou de l'autre ne sépare pas deux associations : « Club
# Amitié Cévennes » et « ASSOCIATION AMITIE CEVENNES » sont la même.
_MOTS_STRUCTURE = {
    "club", "asso", "groupe", "amicale", "comite", "foyer", "union", "societe",
    "syndicat", "cercle", "federation", "collectif", "compagnie", "ligue",
    "atelier", "centre", "maison", "office", "oeuvre", "oeuvres", "section",
    "equipe", "troupe", "ensemble", "corporation", "confrerie", "fondation",
}


def _distance(a: str, b: str, maxi: int = 2) -> int:
    """Distance d'édition bornée — assez pour « lasailois » / « lasallois »."""
    if abs(len(a) - len(b)) > maxi:
        return maxi + 1
    prec = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cour = [i]
        for j, cb in enumerate(b, 1):
            cour.append(min(prec[j] + 1, cour[j - 1] + 1,
                            prec[j - 1] + (ca != cb)))
        if min(cour) > maxi:
            return maxi + 1
        prec = cour
    return prec[-1]


def _est_distinctif(mot: str, candidat: set[str]) -> bool:
    """Un mot absent du candidat suffit-il à dire que ce n'est pas la même entité ?

    Non s'il nomme une forme de groupement (« club », « groupe »), non s'il est
    trop court pour porter une identité (« mt », « vtt »), non s'il est
    l'orthographe abîmée d'un mot que le candidat porte — un procès-verbal
    océrisé écrit « Lasailois » pour « Lasallois ». Oui dans tous les autres
    cas : c'est « olympique », c'est « pétanque », et c'est ce mot-là qui dit
    que l'argent n'est pas allé à la même association.
    """
    if len(mot) <= 3 or mot in _MOTS_STRUCTURE:
        return False
    return not any(_distance(mot, autre) <= 2 for autre in candidat)


def _norm_tokens(s: str) -> set[str]:
    s = _deapos(s)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", " ", s).lower()
    return {t for t in s.split() if t and t not in _STOP and len(t) > 1}


class Resolver:
    def __init__(self, conn):
        self.ents = []
        for r in conn.execute(
            "SELECT id,name,type FROM entities WHERE type IN ('association','business','service','place')"
        ):
            self.ents.append((r["id"], r["name"], r["type"], _norm_tokens(r["name"])))
        self.name_of = {eid: name for eid, name, typ, _ in self.ents}
        self.type_of = {eid: typ for eid, name, typ, _ in self.ents}
        # Index par nom exact. Une association et son établissement SIRENE portent
        # souvent le même nom (« LA SOIERIE ») : sans arbitrage, c'est la dernière
        # ligne rendue par le SELECT qui gagnait — le business, la moitié du temps.
        self.by_name = {}
        for eid, name, typ, _ in self.ents:
            key = _deapos(name).strip().lower()
            prec = self.by_name.get(key)
            if prec is None or self._prefere(eid, prec):
                self.by_name[key] = eid

        # Entités déjà bénéficiaires de subventions → à privilégier (cohérence d'affichage
        # malgré les doublons d'entités préexistants).
        self.canon = []
        for r in conn.execute(
            "SELECT DISTINCT te.id, te.name FROM financial_flows ff JOIN entities te ON te.id=ff.to_id "
            "WHERE ff.type='subvention' AND te.id IS NOT NULL"
        ):
            self.canon.append((r["id"], r["name"], _norm_tokens(r["name"])))

    def _prefere(self, eid: int, contre: int) -> bool:
        """Une association l'emporte sur toute autre forme ; sinon la plus ancienne."""
        a, b = self.type_of.get(eid), self.type_of.get(contre)
        if (a == "association") != (b == "association"):
            return a == "association"
        return eid < contre

    def add(self, eid: int, name: str, typ: str = "association"):
        """Déclare une entité créée après le chargement du résolveur.

        Sans ça, un import qui crée une entité puis rencontre le même nom
        autrement orthographié plus loin dans sa propre boucle la recrée : c'est
        exactement ainsi que « La Boule lasalloise » (2025) et « La Boule
        Lasalloise » (2024) sont devenues deux associations.
        """
        toks = _norm_tokens(name)
        self.ents.append((eid, name, typ, toks))
        self.by_name[_deapos(name).strip().lower()] = eid
        self.name_of[eid] = name
        self.type_of[eid] = typ
        self.canon.append((eid, name, toks))

    def _best(self, et, pool):
        """Meilleure entité du pool pour ces tokens, ou None. Retourne (id, nom)."""
        best = None
        for eid, en, ntok in pool:
            inter = et & ntok
            if not inter:
                continue
            cover = len(inter) / len(et)
            score = cover + (0.5 if et <= ntok else 0)
            # Deux départages, tous deux constatés à l'exécution :
            #  - à nom égal, une association et son établissement SIRENE coexistent
            #    souvent (« LA SOIERIE » ×2). Une subvention communale va à
            #    l'association : la rattacher au business serait faux.
            #  - à tout égal, garder l'id le plus ancien — les doublons sont créés
            #    après la fiche d'origine, jamais avant.
            asso = 1 if self.type_of.get(eid) == "association" else 0
            # Le mot qui MANQUE décide. La couverture seule ne mesurait la
            # ressemblance que dans un sens, et le mot qui distingue deux noms
            # ne pesait rien : « OLYMPIQUE MONT AIGOUAL » couvrait 2 de ses 3
            # mots dans « OFFICE DE TOURISME MONT AIGOUAL CAUSSES CÉVENNES »,
            # le seuil de 0,6 était franchi, et 920 € d'une association
            # sportive étaient portés au compte de l'office de tourisme. Sur un
            # corpus communal les noms partagent peu de mots ; sur un corpus
            # intercommunal ils partagent tous le massif et la vallée, et le
            # défaut sort.
            distinctif = any(_est_distinctif(t, ntok) for t in et - ntok)
            cand = (score, cover, not distinctif, asso, -len(ntok), -eid, eid, en)
            if best is None or cand > best:
                best = cand
        # Mieux vaut CRÉER une association de plus que d'attribuer son argent à
        # une autre : un doublon se fusionne à l'atelier, une fausse
        # attribution se lit comme un fait sur le site.
        if not best or best[1] < 0.6 or not best[2]:
            return None
        return best[6], best[7]

    def resolve(self, name: str):
        akey = re.sub(r"\s+", " ", unicodedata.normalize("NFKD", _deapos(name))
                      .encode("ascii", "ignore").decode()).strip().lower()
        if akey in ALIASES:
            name = ALIASES[akey]
        key = _deapos(name).strip().lower()
        if key in self.by_name:
            eid = self.by_name[key]
            return eid, self.name_of.get(eid, name)
        et = _norm_tokens(name)
        if not et:
            return None, name
        # 1) privilégier une entité déjà subventionnée ; 2) sinon toute entité éligible.
        best = self._best(et, self.canon)
        if best is None:
            best = self._best(et, [(e[0], e[1], e[3]) for e in self.ents])
        if best:
            return best
        return None, name


# ── Motifs d'extraction ────────────────────────────────────────────────────────

SUBV_RE = re.compile(
    r"attribuer\s+(?:à|au|aux)\s+(?:l['’]|la\s+|le\s+)?(.{2,55}?)\s+"
    r"une\s+(?:subvention|avance[^.]{0,20}?subvention|aide)\s+"
    r"(?:exceptionnelle\s+)?(?:par anticipation\s+)?de\s+([\d\s  ]{2,12})\s*€",
    re.I,
)
CESSION_TITLE = re.compile(r"CESSION|VENTE.*(TERRAIN|PARCELLE|DOMAINE)|ALI[EÉ]NATION|D[EÉ]CLASSEMENT.*VENTE", re.I)
BAIL_RE = re.compile(r"loyer[^.]{0,40}?de\s+([\d\s  ]{2,10}(?:[,.]\d{2})?)\s*€[^.]{0,15}?(mois|an|annuel)", re.I)
AIDE_TITLE = re.compile(r"AIDE.*(FA[CÇ]ADE|R[EÉ]NOVATION)|RAVALEMENT", re.I)
AMOUNT_RE = re.compile(r"([\d][\d\s  ]{2,10}(?:[,.]\d{2})?)\s*€")


def _to_int(s: str) -> int:
    return int(re.sub(r"[^\d]", "", s) or 0)


def _to_float(s: str) -> float:
    s = re.sub(r"[^\d,.]", "", s).replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


# ── Extraction ─────────────────────────────────────────────────────────────────

def extract_subventions(conn):
    """Retourne [(year, beneficiary_raw, amount, event_id, payeur)].

    Dédoublonné par (année, assemblée, bénéficiaire) — et l'assemblée est dans
    la clé pour une raison : une association qui touche la même année 500 € de
    la commune et 500 € de l'intercommunalité reçoit DEUX subventions. Les
    réunir sous une seule clé en aurait effacé une, et effacé précisément celle
    qu'on vient chercher.
    """
    out, seen = [], set()
    for r in conn.execute(
        f"SELECT id,date,type,source,content FROM events WHERE type IN ({_EN_TYPES}) "
        "AND content IS NOT NULL", TYPES_DELIBERES
    ):
        year = int((r["date"] or "0")[:4]) or None
        if not year:
            continue
        qui = payeur(r["type"], r["source"])
        for m in SUBV_RE.finditer(r["content"]):
            benef = re.sub(r"\s+", " ", m.group(1)).strip(" ,.")
            amount = _to_int(m.group(2))
            if amount <= 0 or amount > 200000:
                continue
            key = (year, qui, benef.lower())
            if key in seen:
                continue
            seen.add(key)
            out.append((year, benef, amount, r["id"], qui))
    return out


# ── Second régime : le TABLEAU de subventions ────────────────────────────────
#
# `SUBV_RE` ci-dessus lit une PHRASE — « attribuer à X une subvention de N € ».
# C'est la forme communale. L'intercommunalité, elle, vote en une fois toutes
# ses subventions et les présente en TABLEAU, une association par ligne. Le
# régime de la phrase n'y trouve rien : à Lasalle, les 25 associations
# subventionnées par la CC en 2019 — dont la Filature du Mazel pour 25 500 € —
# ne sortaient d'aucun collecteur alors que le texte était en base depuis des
# mois.
#
# Le tableau se présente sous trois mises en page dans le même corpus :
#   NOM ................ 1 636 €                        (colonnes alignées)
#   NOM \n 217 000 €                                    (montant sur sa ligne)
#   NOM  245,40 €  24 pour et 1 abstention (…)          (issue du vote en queue)
# Elles se lisent d'un seul balayage, en gardant en attente le dernier nom vu.

_NUM = r"\d{1,3}(?:[\s  ]\d{3})+(?:[.,]\d{1,2})?|\d{2,7}(?:[.,]\d{1,2})?"

# Ce qui peut suivre le montant : l'issue du vote, et rien d'autre. Elle NOMME
# les élus qui se déportent — on la reconnaît pour la JETER, jamais pour la
# lire. Un tableau de subventions est aussi une liste de conflits d'intérêts
# déclarés, et ces noms-là ne sont pas des bénéficiaires.
_QUEUE = (r"A\s+l['’]unanim\w*|\d+\s*(?:pour|contre|voix|abstention)|"
          r"unanim\w*|abstention|ne\s+participe")

TAB_NOM_MONTANT  = re.compile(rf"^(?P<nom>\D.{{2,70}}?)\s+(?P<montant>{_NUM})\s*€\s*(?P<queue>.*)$")
TAB_MONTANT_SEUL = re.compile(rf"^(?P<montant>{_NUM})\s*€\s*(?P<queue>.*)$")
TAB_QUEUE_OK     = re.compile(rf"^\s*(?:{_QUEUE}).*$|^\s*$", re.I)
TAB_QUEUE_VOTE   = re.compile(rf"\s+(?:{_QUEUE}).*$", re.I)

# Le conseil ACCORDE. Une délibération qui SOLLICITE présente un plan de
# financement, dont les lignes nomment des FINANCEURS : les lire ici inverserait
# le sens de l'argent — « l'intercommunalité a versé 2 500 € à la Région
# Occitanie ». Ces actes-là relèvent d'`approbations`, qui les lit déjà.
TAB_OUVERTURE = re.compile(
    r"d[ée]cide[^.]{0,120}?d['’]accorder[^.]{0,120}?subvention"
    r"|attribu\w+[^.]{0,80}?subventions?[^.]{0,80}?(?:association|organisme)"
    r"|^[ \t]*SUBVENTIONS[ \t]*$"
    r"|^[ \t]*ASSOCIATIONS?[ \t]+(?:Montant|Subvention)", re.I | re.M)
TAB_DEMANDE = re.compile(r"demande\s+de\s+subvention|sollicit|plan\s+de\s+financement", re.I)

# En-têtes et totaux : ni bénéficiaires, ni bruit. Ils sont NEUTRES.
TAB_ENTETE = re.compile(r"^\s*(TOTAL|MONTANT|SUBVENTIONS?|ASSOCIATIONS?|ANNEE|VOTE)\b", re.I)
TAB_SECTION = re.compile(r"^\s*([IVXL]{1,5}\s*[.)]|\d{1,2}\s*[.)]\s+[A-ZÉÈ]|Vu\s|Consid[ée]rant\s)")
TAB_DETAIL = re.compile(r"^\s*[(\[]")          # « (fonctionnement 157 000 € + …) »
TAB_CIVILITE = re.compile(r"\b(M\.|Mme|Mrs|Mr|Monsieur|Madame)\b")
# Une phrase, pas une cellule de tableau.
TAB_PROSE = re.compile(r"\b(est|sont|sera|seront|a\s+[ée]t[ée]|d['’]un|à\s+hauteur|"
                       r"estim\w+|rembours\w+|qui|que|dont|propose)\b", re.I)
# La liste des élus déportés déborde sur sa propre ligne et se ferme sur la
# parenthèse ouverte plus haut.
TAB_RESTE_VOTE = re.compile(r"^[^(]*\)\s*$|^\s*\d+\s*(pour|contre|voix|abstention)", re.I)
# Un financeur n'est jamais bénéficiaire dans ce régime.
TAB_FINANCEUR = re.compile(r"\b(r[ée]gion|d[ée]partement|conseil\s+d[ée]partemental|[ée]tat|"
                           r"europe|FEDER|LEADER|autofinancement|AERMC|agence\s+de\s+l['’]eau|"
                           r"pr[ée]fecture|DETR|DSIL)\b", re.I)
TAB_EXERCICE = re.compile(r"(?:exercice|ann[ée]e)\s+(20\d{2})", re.I)

TAB_MAX_TROU = 3            # lignes illisibles tolérées avant de clore le tableau
TAB_PLAFOND = 1_000_000
TAB_MIN_LIGNES = 3          # en dessous, c'est une phrase — le régime de SUBV_RE


def _tab_montant(s: str) -> int:
    s = re.sub(r"[^\d,.]", "", s).replace(",", ".")
    try:
        return int(round(float(s)))
    except ValueError:
        return 0


# Un qualificatif entre parenthèses précise l'OBJET de la subvention, pas
# l'identité du bénéficiaire : « FILATURE DU MAZEL (Frais de structure) » et
# « AFR Lous Pitchouns Anhels (crèche Lanuéjols) » désignent l'association tout
# court. Le garder dans le nom en faisait une association distincte de
# celle qui reçoit l'autre ligne du même tableau. Le texte de l'acte, lui,
# reste attaché au flux : rien n'est perdu.
TAB_QUALIFICATIF = re.compile(r"\s*\([^)]*\)\s*$")


def _tab_nettoie(nom: str) -> str:
    nom = TAB_QUALIFICATIF.sub("", TAB_QUEUE_VOTE.sub("", nom))
    return re.sub(r"\s+", " ", nom.strip(" .:–-"))


def _tab_est_nom(ligne: str) -> bool:
    ligne = _tab_nettoie(ligne)
    if not (3 <= len(ligne) <= 70):
        return False
    if TAB_ENTETE.match(ligne) or TAB_DETAIL.match(ligne) or TAB_CIVILITE.search(ligne):
        return False
    if TAB_SECTION.match(ligne) or TAB_PROSE.search(ligne) or TAB_FINANCEUR.search(ligne):
        return False
    if TAB_RESTE_VOTE.match(ligne):
        return False
    return bool(re.search(r"[A-Za-zÀ-ÿ]{3}", ligne)) and not re.search(r"\d{4}", ligne)


def lire_tableau(texte: str) -> list[tuple[str, int]]:
    """[(nom, montant)] lus dans le tableau d'attribution, s'il y en a un."""
    ouverture = TAB_OUVERTURE.search(texte)
    if not ouverture:
        return []
    out, en_attente, trou = [], None, 0
    for brute in texte[ouverture.start():].splitlines()[1:]:
        L = brute.strip()
        if not L:
            continue
        if re.match(r"^\s*TOTAL\b", L, re.I) or TAB_SECTION.match(L):
            break                       # le tableau est clos
        if TAB_DETAIL.match(L):
            continue
        # Un en-tête ne nomme rien et n'écarte rien : le compter comme une ligne
        # illisible épuisait la tolérance avant la première association, et le
        # tableau se fermait sur son propre titre.
        if TAB_ENTETE.match(L):
            en_attente = None
            continue

        m = TAB_NOM_MONTANT.match(L)
        if m and TAB_QUEUE_OK.match(m.group("queue")) and _tab_est_nom(m.group("nom")):
            montant = _tab_montant(m.group("montant"))
            if 0 < montant <= TAB_PLAFOND:
                out.append((_tab_nettoie(m.group("nom")), montant))
                en_attente, trou = None, 0
                continue

        m = TAB_MONTANT_SEUL.match(L)
        if m and TAB_QUEUE_OK.match(m.group("queue")):
            montant = _tab_montant(m.group("montant"))
            if en_attente and 0 < montant <= TAB_PLAFOND:
                out.append((en_attente, montant))
                trou = 0
            en_attente = None
            continue

        # `_tab_est_nom` d'abord : une ligne porte parfois un nom ET l'issue du
        # vote (« LA FILATURE du MAZEL A l'unanimité »). Tester l'annotation en
        # premier jetait le nom, et avec lui le montant de la ligne suivante.
        if _tab_est_nom(L):
            en_attente, trou = _tab_nettoie(L), 0
        else:
            en_attente = None
            trou += 1
            if trou > TAB_MAX_TROU:
                break
    return out


def extract_subventions_tableau(conn):
    """Même forme que `extract_subventions` — [(year, benef, amount, eid, payeur)]."""
    out, seen = [], set()
    for r in conn.execute(
        f"SELECT id,date,type,title,source,content FROM events WHERE type IN ({_EN_TYPES}) "
        "AND content IS NOT NULL AND (content LIKE '%ubvention%' OR title LIKE '%ubvention%')",
        TYPES_DELIBERES
    ):
        if TAB_DEMANDE.search(r["title"] or ""):
            continue
        lignes = lire_tableau(r["content"])
        if len(lignes) < TAB_MIN_LIGNES:
            continue
        # L'exercice voté prime sur la date de séance : un tableau adopté en
        # décembre peut porter sur l'année suivante.
        exercice = TAB_EXERCICE.search(r["content"][:2000])
        year = int(exercice.group(1)) if exercice else (int((r["date"] or "0")[:4]) or None)
        if not year:
            continue
        qui = payeur(r["type"], r["source"])
        for nom, montant in lignes:
            key = (year, qui, nom.lower())
            if key in seen:
                continue
            seen.add(key)
            out.append((year, nom, montant, r["id"], qui))
    return out


def flow_exists(conn, ftype, year, amount, to_id, from_id=None) -> bool:
    """`from_id` fait partie de l'identité du flux : sans lui, la subvention de
    l'intercommunalité était prise pour un doublon de celle de la commune dès
    qu'elles portaient le même montant la même année — le cas le plus banal,
    deux collectivités votant volontiers 500 € au même comité des fêtes."""
    sql = "SELECT 1 FROM financial_flows WHERE type=? AND year=? AND amount=? AND to_id=?"
    args = [ftype, year, amount, to_id]
    if from_id is not None:
        sql += " AND from_id=?"
        args.append(from_id)
    return conn.execute(sql, args).fetchone() is not None


def run_subventions(commit: bool):
    conn = get_conn()
    res = Resolver(conn)
    pivots = pivot_ids(conn)
    # Deux régimes, dans cet ordre : la PHRASE d'abord, le TABLEAU ensuite. Un
    # même vote peut figurer sous les deux formes dans le même procès-verbal
    # (la phrase dans le corps, le tableau en annexe) ; la phrase nomme mieux le
    # bénéficiaire, elle garde donc la main sur la clé commune.
    phrases = extract_subventions(conn)
    vus = {(y, q, b.lower()) for y, b, a, e, q in phrases}
    tableaux = [t for t in extract_subventions_tableau(conn)
                if (t[0], t[4], t[1].lower()) not in vus]
    subs = phrases + tableaux
    print(f"[subventions] {len(subs)} extraites du contenu CR "
          f"({len(phrases)} en phrase, {len(tableaux)} en tableau)\n")
    to_insert, to_create, dupes = [], [], 0
    for year, benef, amount, eid, qui in subs:
        from_id = pivots[qui]
        to_id, matched = res.resolve(benef)
        if to_id is None:
            to_create.append((year, amount, benef, eid, qui))     # nouvelle asso à créer
            continue
        if flow_exists(conn, "subvention", year, amount, to_id, from_id):
            dupes += 1
            continue
        to_insert.append((year, amount, to_id, matched, benef, eid, qui))
    from collections import Counter
    allyears = [x[0] for x in to_insert] + [x[0] for x in to_create]
    print(f"  à insérer : {len(to_insert)}  |  déjà en base : {dupes}  |  entités à créer : {len(to_create)}")
    print("  nouveaux par année :", dict(sorted(Counter(allyears).items())))
    # Par assemblée, et jamais additionnées : ce sont deux budgets, deux
    # bulletins de vote. Un total unique dirait qu'elles se valent.
    par_assemblee = Counter([x[6] for x in to_insert] + [x[4] for x in to_create])
    print("  par assemblée :", {"commune": par_assemblee["commune"],
                                "intercommunalité": par_assemblee["epci"]})
    if to_create:
        print("  ⚠ bénéficiaires nouveaux (entité créée) :",
              sorted({f'{_clean_benef(b)} ({y})' for y, a, b, e, q in to_create}))
    print("  échantillon à insérer :")
    for year, amount, to_id, matched, benef, eid, qui in to_insert[:15]:
        marque = "CC" if qui == "epci" else "CM"
        print(f"    {year} {marque} {amount:>6} €  {benef[:24]:24} → #{to_id} {matched[:28]}")
    conn.close()

    if not commit:
        print("\n(dry-run — relancer sans --dry-run pour insérer)")
        return

    def _ins(w, year, amount, to_id, eid, from_id, qui):
        # Le libellé nomme l'assemblée : « CR CM » et « CR CC » se distinguent
        # dans la colonne `source`, que `etat_du_flux` lit pour dater un montant
        # (les deux matchent `^CR\b`, donc « voté » dans les deux cas), et qu'un
        # lecteur du tableau des flux lit pour savoir qui a payé.
        marque = "CC" if qui == "epci" else "CM"
        libelle = ("Subvention intercommunale" if qui == "epci"
                   else "Subvention communale")
        w.execute(
            "INSERT INTO financial_flows (type,year,amount,from_id,to_id,event_id,description,source,confidence) "
            "VALUES ('subvention',?,?,?,?,?,?,?, 'verified')",
            (year, amount, from_id, to_id, eid,
             f"{libelle} {year} (extraite du CR)", f"CR {marque} {year}"),
        )
        w.execute(
            "INSERT OR IGNORE INTO relations (from_id,to_id,relation_type,source,confidence,metadata) "
            "VALUES (?,?,'subventionné','cm_finances','verified',?)",
            (from_id, to_id, f'{{"year": {year}, "amount": {amount}}}'),
        )
        # Qui reçoit une subvention votée par une délibération est cité PAR
        # cette délibération : c'est vrai par construction, et c'est pourtant
        # ce lien qui manquait.
        #
        # « Cités dans un acte » ne montrait aucune association — pas une seule
        # sur 44 bénéficiaires — parce que le rôle `sujet` n'était posé que par
        # le BODACC, l'urbanisme, les commissions et les élections. Une
        # association subventionnée depuis dix ans n'apparaissait donc jamais
        # dans les actes qui la subventionnent, alors que l'argent, lui, était
        # en base et rattaché au bon acte.
        if eid:
            w.execute(
                "INSERT OR IGNORE INTO event_entities (event_id, entity_id, role) "
                "VALUES (?,?,'bénéficiaire')", (eid, to_id))

    ins = created = 0
    with transaction() as w:
        pivots = pivot_ids(w)
        for year, amount, to_id, matched, benef, eid, qui in to_insert:
            _ins(w, year, amount, to_id, eid, pivots[qui], qui); ins += 1
        for year, amount, benef, eid, qui in to_create:
            # Re-résoudre AVANT de créer : le résolveur a été chargé au début du
            # run et ignore tout ce que cette boucle vient d'écrire. Sans ce
            # rattrapage, « LA FILATURE DU MAZEL » (2018) et « LA FILATURE du
            # MAZEL » (2019) — deux lignes du même tableau à deux exercices —
            # deviennent deux associations, `upsert_entity` appariant sur le nom
            # EXACT. C'est ainsi que « La Boule lasalloise » et « La Boule
            # Lasalloise » sont nées ; `Resolver.add` existe précisément pour ça.
            nom = _clean_benef(benef)
            new_id, _ = res.resolve(nom)
            if new_id is None:
                new_id = upsert_entity(w, type="association", name=nom,
                                       confidence="verified")
                res.add(new_id, nom, "association")
                created += 1
            w.execute("INSERT OR IGNORE INTO associations (entity_id) VALUES (?)", (new_id,))
            if not flow_exists_conn(w, year, amount, new_id, pivots[qui]):
                _ins(w, year, amount, new_id, eid, pivots[qui], qui); ins += 1
    print(f"\n✓ {ins} subventions insérées ({created} nouvelles entités créées).")


# ── Baux et loyers communaux ──────────────────────────────────────────────────
#
# Les délibérations de tarifs présentent les loyers en tableau, une ligne par
# local, le montant en fin de ligne :
#
#     81 rue de la Place - Appart.                            486.75
#     Filature de Fer - Atelier Mme Nolwenn TESSIER               60.49
#     116 rue de la Gravière - Comité des Fêtes                46.57
#     Local Stade - Vélo Club                                  27.33
#
# L'occupant, quand il est nommé, suit le dernier tiret. Il est résolu contre
# les entités DÉJÀ en base — jamais créé : un nom tiré d'une ligne de tableau
# n'est pas une preuve d'existence.
#
# Ces flux entrent en `probable` : ils ne sont pas publiés, ils attendent
# l'atelier. Deux raisons — le découpage local/occupant est une lecture, et la
# PÉRIODICITÉ n'est pas toujours écrite. Le montant est enregistré TEL QU'IL
# EST LU, sans annualisation : multiplier par douze un chiffre dont on ignore
# s'il est mensuel, ce serait fabriquer une donnée.

TITRE_BAUX = re.compile(r"LOYERS?|BAIL|BAUX|TARIFS?\s+LOCATION|LOCATION\s+", re.I)

# Une ligne de tableau : un libellé, puis un montant en fin de ligne. Les
# montants s'écrivent « 486.75 » ou « 461,05 ».
# Les milliers sont tantôt séparés par une espace, tantôt collés : « 1 417,73 »
# et « 1417.73 » désignent le même loyer. N'accepter que la forme groupée
# écartait silencieusement les montants à quatre chiffres — c'est-à-dire les
# plus gros.
LIGNE_BAIL = re.compile(
    r"^(?P<local>.{6,90}?)\s+"
    r"(?P<montant>\d{1,3}(?:[\s ]\d{3})+|\d{1,7})[.,](?P<centimes>\d{2})\s*$")
# Le PV dit parfois sa périodicité — « PAR MOIS » sur sa propre ligne.
PERIODE_MOIS = re.compile(r"^\s*(PAR\s+MOIS|/\s*mois|mensuel)\s*$", re.I)
# Lignes qui ressemblent à un tableau sans en être : totaux, indices, dates.
BRUIT_BAIL = re.compile(r"^(total|indice|soit|montant|soit\s)", re.I)
# Mots qui désignent un LOCAL et non son occupant. Ils apparaissent après le
# même tiret que les noms d'occupants — « 81 rue de la Place - Appart. »,
# « Lotissement les Glycines - Villa N° » — et un tableau de loyers en est plein.
MOTS_DE_LOCAL = {
    "appart", "appartement", "atelier", "bureau", "cave", "chambre", "dependance",
    "dépendance", "etage", "étage", "garage", "grange", "hangar", "local", "locaux",
    "logement", "maison", "parking", "rez", "salle", "studio", "terrain",
    "terrasse", "terrasses", "villa", "villas", "gauche", "droite",
}


def extract_baux(conn) -> list[dict]:
    """Lignes de loyer lues dans les délibérations de tarifs.

    Chaque entrée : {annee, local, occupant, montant, mensuel, event_id}.
    `occupant` peut être vide : beaucoup de lignes ne désignent qu'un logement.
    """
    out, vus = [], set()
    for r in conn.execute(
        f"SELECT id, date, title, type, source, content FROM events "
        f"WHERE type IN ({_EN_TYPES}) AND content IS NOT NULL", TYPES_DELIBERES
    ):
        if not TITRE_BAUX.search(r["title"] or ""):
            continue
        annee = int((r["date"] or "0")[:4]) or None
        if not annee:
            continue
        mensuel = False
        for ligne in (r["content"] or "").splitlines():
            nu = ligne.strip()
            if PERIODE_MOIS.match(nu):
                mensuel = True
                continue
            m = LIGNE_BAIL.match(nu)
            if not m or BRUIT_BAIL.match(nu):
                continue
            local = " ".join(m.group("local").split()).strip(" -–")
            montant = _to_float(f"{m.group('montant')},{m.group('centimes')}")
            if montant <= 0 or montant > 100000:
                continue
            # L'occupant suit le dernier tiret, s'il y en a un — sauf quand ce
            # dernier segment désigne encore le LOCAL. « Lotissement les
            # Glycines - Villa N° » se résolvait sinon vers une entreprise
            # nommée « LAURENT VILLA », à qui la base aurait attribué un loyer
            # de 1 418 € : une erreur nominative, la seule espèce que ce
            # dispositif ne peut pas se permettre.
            occupant = ""
            morceaux = re.split(r"\s+[-–]\s+", local)
            if len(morceaux) > 1 and len(morceaux[-1]) >= 3:
                candidat = morceaux[-1].strip()
                premier = re.split(r"\W+", candidat.lower())[0]
                if premier not in MOTS_DE_LOCAL:
                    occupant = candidat
            qui = payeur(r["type"], r["source"])
            cle = (annee, qui, local.lower())
            if cle in vus:
                continue
            vus.add(cle)
            out.append({"annee": annee, "local": local, "occupant": occupant,
                        "montant": montant, "mensuel": mensuel,
                        "event_id": r["id"], "payeur": qui})
    return out


def run_baux(commit: bool) -> int:
    conn = get_conn()
    res = Resolver(conn)
    lignes = extract_baux(conn)
    print(f"\n[baux] {len(lignes)} ligne(s) de loyer extraites des CR")

    a_inserer, sans_occupant, non_resolus = [], 0, []
    for b in lignes:
        if not b["occupant"]:
            sans_occupant += 1
            continue
        to_id, matched = res.resolve(b["occupant"])
        if to_id is None:
            non_resolus.append(b)
            continue
        a_inserer.append({**b, "entity_id": to_id, "matched": matched})

    print(f"  occupant résolu : {len(a_inserer)}  |  local sans occupant nommé : "
          f"{sans_occupant}  |  occupant non résolu : {len(non_resolus)}")
    for b in a_inserer[:12]:
        unite = "€/mois" if b["mensuel"] else "€"
        print(f"    {b['annee']}  {b['montant']:>8.2f} {unite:6} "
              f"{b['local'][:44]:44} → {b['matched'][:28]}")

    if not commit:
        print("  (dry-run — rien écrit)")
        conn.close()
        return 0

    pivots = pivot_ids(conn)
    conn.close()
    inseres = 0
    with transaction() as w:
        for b in a_inserer:
            montant = int(round(b["montant"]))
            # Un loyer va de l'occupant vers le PROPRIÉTAIRE, qui est
            # l'assemblée dont le tableau de tarifs a été lu.
            bailleur = pivots[b["payeur"]]
            if w.execute(
                "SELECT 1 FROM financial_flows WHERE type='bail' AND year=? "
                "AND from_id=? AND to_id=? AND amount=?",
                (b["annee"], b["entity_id"], bailleur, montant)
            ).fetchone():
                continue
            periode = "par mois" if b["mensuel"] else "périodicité non précisée"
            marque = "CC" if b["payeur"] == "epci" else "CM"
            w.execute(
                "INSERT INTO financial_flows"
                " (type,year,amount,from_id,to_id,event_id,description,source,confidence)"
                " VALUES ('bail',?,?,?,?,?,?,?,'probable')",
                (b["annee"], montant, b["entity_id"], bailleur, b["event_id"],
                 f"{b['local']} — loyer {b['annee']} tel que lu ({periode})",
                 f"CR {marque} {b['annee']}"))
            inseres += 1
    print(f"  ✓ {inseres} bail/baux insérés en `probable` (non publiés)")
    return inseres


def flow_exists_conn(conn, year, amount, to_id, from_id=None) -> bool:
    return flow_exists(conn, "subvention", year, amount, to_id, from_id)


def report_others():
    """Détection (sans insertion) des cessions / baux / aides pour curation."""
    conn = get_conn()
    marque = lambda r: "CC" if payeur(r["type"], r["source"]) == "epci" else "CM"
    print("\n=== CESSIONS de patrimoine détectées dans les CR (à curer) ===")
    for r in conn.execute(
        f"SELECT id,date,title,type,source,content FROM events WHERE type IN ({_EN_TYPES}) "
        "AND content IS NOT NULL", TYPES_DELIBERES
    ):
        if not CESSION_TITLE.search(r["title"] or ""):
            continue
        amts = [a for a in (AMOUNT_RE.findall(r["content"] or "")) if _to_float(a) > 500]
        print(f"  {r['date']} {marque(r)} #{r['id']} {(r['title'] or '')[:50]}  montants≈ {amts[:4]}")
    print("\n=== BAUX / loyers détectés ===")
    for r in conn.execute(
        f"SELECT id,date,title,type,source,content FROM events WHERE type IN ({_EN_TYPES}) "
        "AND content IS NOT NULL AND content LIKE '%loyer%'", TYPES_DELIBERES
    ):
        for m in BAIL_RE.finditer(r["content"] or ""):
            print(f"  {r['date']} {marque(r)} #{r['id']} loyer {m.group(1)} €/{m.group(2)}  — {(r['title'] or '')[:40]}")
    print("\n=== AIDES façade détectées ===")
    for r in conn.execute(
        f"SELECT id,date,title,type,source FROM events WHERE type IN ({_EN_TYPES}) "
        "AND title IS NOT NULL", TYPES_DELIBERES
    ):
        if AIDE_TITLE.search(r["title"] or ""):
            print(f"  {r['date']} {marque(r)} #{r['id']} {r['title'][:58]}")
    conn.close()


def main():
    ap = argparse.ArgumentParser(description="Extraction financière depuis les CR du CM.")
    ap.add_argument("--dry-run", action="store_true", help="Aperçu sans insertion")
    ap.add_argument("--report", action="store_true", help="Rapport cessions/baux/aides (curation)")
    args = ap.parse_args()
    run_subventions(commit=not args.dry_run)
    if args.report:
        report_others()


if __name__ == "__main__":
    main()
