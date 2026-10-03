"""citations.py — de quoi une phrase est faite : le résolveur des citations d'actes.

Un dossier thématique (`<instance>/dossiers/<slug>.md`) cite des actes comme on
les cite en français, sans lien : « (CM du 14/04/2021) », « délibération CC du
02/04/2025 », une ligne de frise `| 17/02/2016 | Motion … | CM |`. Relevé sur
les dossiers de l'instance d'origine le 03/10/2026 : presque aucun lien
markdown. Le lecteur voyait une date, et devait retrouver seul l'acte parmi
deux mille.

Ce module relie la phrase à l'acte, AU BUILD du snapshot — jamais dans le
navigateur : le site est statique, et un résolveur côté lecteur publierait
l'index entier des actes pour chaque page de dossier.

⚖️ La règle qui gouverne tout : **l'extraction n'est pas la publication.** Le
résolveur ne reçoit que des actes PUBLIÉS (ceux du snapshot, ou à l'atelier
ceux que les règles de publication laisseraient sortir). Il ne fait jamais un
lien vers ce qui n'est pas publié : une citation qui ne mène qu'à un acte
retenu hors du site n'est pas résolue, et elle entre au relevé des citations
non résolues comme les autres.

Trois issues, et seulement trois :

  précis      une seule correspondance → lien vers l'acte ;
  imprécis    la séance est trouvée mais elle a pris plusieurs actes, et rien
              dans la phrase ne dit lequel → lien vers la séance, signalé ;
  non résolu  aucune correspondance publiée → pas de lien, une entrée au
              relevé (c'est une QUESTION : cf. `collectors/lacunes.py`).

La syntaxe explicite, pour lever une ambiguïté (documentée dans
`docs/dossiers-thematiques.md`) :

    [le vote du budget](acte:c-2021-41)        un acte, par sa clé datée
    [la séance de mars](seance:c-2021-03-04)   une séance
    [le registre](piece:c-2021-41)             la pièce source de l'acte

Le préfixe (`acte:`…) n'est pas une adresse : `markdownSur` le neutralise en
`#` s'il arrive jusqu'au site. Il n'y arrive pas — le résolveur le remplace
par l'URL de l'acte, ou retire le lien et garde le texte.

Les résolveurs forment une petite table (`RESOLVEURS`) : acte, séance, pièce.
Un « fait en base » (un indicateur, un compte) s'y ajoutera par une entrée de
plus, sans toucher au relevé des citations.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field

from .cle_acte import (ASSEMBLEE, PREFIXE_PAR_TYPE, TYPE_ACTE, TYPES_ACTES,
                       TYPES_SEANCES, cle_acte, cle_de_ligne, cle_seance)

# ─── Lire une date, un montant, un texte ─────────────────────────────────────

MOIS = {"janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
        "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11,
        "decembre": 12}
_MOIS_RE = "janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[ûu]t|septembre|octobre|novembre|d[ée]cembre"
_DATE = (r"(?:(?P<j>\d{1,2})(?:er)?[/.](?P<m>\d{1,2})[/.](?P<a>\d{4})"
         rf"|(?P<j2>\d{{1,2}})(?:er)?\s+(?P<mois>{_MOIS_RE})\s+(?P<a2>\d{{4}}))")

#: « (CM du 14/04/2021) », « délibération CC du 02/04/2025 », « conseil
#: municipal du 4 mars 2026 », « délibération n°41 du 14/04/2021 ». Les deux
#: membres facultatifs ne le sont pas ensemble : « du 14/04/2021 » seul n'est
#: pas une citation d'acte (vérifié dans `_naturelles`).
NATURELLE = re.compile(
    r"(?<![\w])(?:(?P<delib>d[ée]lib[ée]rations?)\s+)?"
    r"(?:(?P<ass>CM|CC|conseil\s+municipal|conseil\s+communautaire)\s+)?"
    r"(?:(?:n°|n\.|no)\s*(?P<num>\d[\w/.-]*?)\s+)?"
    rf"du\s+{_DATE}", re.I)

#: « délibération n°41/2021 », « délibération CC n° 2025-12 » : un numéro qui
#: porte son année, sans date de séance.
NUMEROTEE = re.compile(
    r"(?<![\w])(?:d[ée]lib[ée]ration|CM|CC)\s+(?:(?P<ass>CM|CC)\s+)?(?:n°|n\.|no)\s*"
    r"(?:(?P<num1>\d+[a-z]*)\s*/\s*(?P<a1>(?:19|20)\d{2})|(?P<a2>(?:19|20)\d{2})\s*-\s*(?P<num2>\d+[a-z]*))"
    r"(?![\w/-])", re.I)

#: `[texte](acte:c-2021-41)` — la syntaxe explicite.
EXPLICITE = re.compile(r"\[(?P<texte>[^\]\n]+)\]\((?P<type>acte|seance|piece):(?P<cle>[a-z0-9-]+)\)")

#: Un lien markdown déjà écrit : on ne relie pas ce qui l'est déjà.
LIEN = re.compile(r"!?\[[^\]\n]*\]\([^)\n]*\)|`[^`\n]*`")

_CELLULE_DATE = re.compile(rf"^\s*{_DATE}\s*$", re.I)
_CELLULE_ASSEMBLEE = re.compile(r"^\s*(CM|CC)\s*$")
_MONTANT = re.compile(r"(\d{1,3}(?:[   .]\d{3})+|\d+)(?:,(\d+))?\s*(?:€|euros?\b)")
_GUILLEMETS = re.compile(r"«\s*([^»]{6,}?)\s*»|“([^”]{6,}?)”")


def _ascii(t: str) -> str:
    return unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()


def compact(t: str) -> str:
    """Un texte réduit à ses lettres et chiffres : « 80 % » et « 80% », une
    coupure de ligne d'OCR ou une apostrophe courbe ne doivent pas faire
    rater une citation exacte."""
    return re.sub(r"[^a-z0-9]", "", _ascii(t))


def _iso(m: re.Match) -> str | None:
    try:
        if m.group("a"):
            j, mo, a = int(m.group("j")), int(m.group("m")), int(m.group("a"))
        else:
            j, mo, a = int(m.group("j2")), MOIS[_ascii(m.group("mois"))], int(m.group("a2"))
    except (KeyError, TypeError, ValueError):
        return None
    if not (1 <= j <= 31 and 1 <= mo <= 12):
        return None
    return f"{a:04d}-{mo:02d}-{j:02d}"


def montants_cites(texte: str) -> set[float]:
    sortie = set()
    for m in _MONTANT.finditer(texte or ""):
        entier = re.sub(r"[^\d]", "", m.group(1))
        try:
            sortie.add(float(f"{entier}.{m.group(2) or 0}"))
        except ValueError:
            continue
    return sortie


def _prefixe(assemblee: str | None) -> str | None:
    a = _ascii(assemblee or "")
    if not a:
        return None
    return "cc" if a == "cc" or "communautaire" in a else "c"


# ─── L'ancre d'une partie de dossier ─────────────────────────────────────────

def ancre(titre: str) -> str:
    """La même ancre que le site (`public/src/lib/dossiers.server.js::ancre`),
    pour qu'un retour « cité dans le dossier eau (§ Le prix) » ouvre la bonne
    partie. Le markdown en ligne est retiré comme le site retire le HTML."""
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", titre or "")
    t = re.sub(r"[*_`]", "", t)
    # NFD puis retrait des diacritiques SEULS, comme `normalize('NFD')` du
    # site : une apostrophe courbe y devient un tiret, pas un vide.
    t = "".join(c for c in unicodedata.normalize("NFD", t.lower()) if not unicodedata.combining(c))
    a = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return a or "partie"


# ─── Les actes publiés : l'index ─────────────────────────────────────────────

def _empreinte(octets: bytes) -> str:
    return hashlib.sha256(octets).hexdigest()[:16]


def _valeur(m):
    v = m.get("montant", m.get("value")) if isinstance(m, dict) else m
    return float(v) if isinstance(v, (int, float)) else None


def vue(ligne: dict) -> dict:
    """Ce qui est AFFICHÉ d'un acte et qui, s'il change, rend une relecture
    caduque : titre, date, numéro, vote, montants, texte, et les corrections de
    l'atelier. Lu dans la ligne brute de la base — la même à l'atelier, au
    moment du verdict, et au snapshot, au moment de comparer : deux lectures
    différentes du même acte feraient croire à un changement qui n'a pas eu lieu.
    """
    meta = ligne.get("metadata") or {}
    montants = sorted({v for v in (_valeur(m) for m in (meta.get("montants") or []))
                       if v is not None})
    return {
        "titre": (ligne.get("title") or "").strip(),
        "date": ligne.get("date"),
        "numero": meta.get("numero_acte"),
        "vote": meta.get("vote") if isinstance(meta.get("vote"), dict) else None,
        "montants": montants,
        "texte": _empreinte((ligne.get("content") or "").encode()) if ligne.get("content") else None,
        "corrections": ligne.get("corrections") or None,
    }


def empreinte_vue(v: dict) -> str:
    return _empreinte(json.dumps(v, sort_keys=True, ensure_ascii=False).encode())


#: Ce qu'on écrit d'un champ qui a changé, dans le bandeau et dans l'atelier.
CHAMPS = {"titre": "le titre", "date": "la date", "numero": "le numéro",
          "vote": "le vote", "montants": "les montants", "texte": "le texte",
          "corrections": "une correction de l'atelier"}


@dataclass
class Acte:
    """Un acte ou une séance PUBLIÉ, tel que le résolveur le connaît."""
    id: int
    type: str
    cle: str
    faible: bool
    prefixe: str
    date: str
    titre: str
    numero: str | None = None
    texte: str = ""
    montants: set = field(default_factory=set)
    source_url: str | None = None
    empreinte: str = ""
    vue: dict = field(default_factory=dict)

    @property
    def seance(self) -> bool:
        return self.type in TYPES_SEANCES

    @property
    def annee(self) -> str:
        return (self.date or "")[:4] or "sans-date"

    @property
    def ancre(self) -> str:
        """L'ancre sur la page de l'année. Une clé faible n'est jamais une
        ancre : elle changerait à la première relecture du titre."""
        return f"a{self.id}" if self.faible else self.cle

    @property
    def url(self) -> str:
        return f"/deliberations/{self.annee}#{self.ancre}"

    @property
    def assemblee(self) -> str:
        return ASSEMBLEE.get(self.prefixe, "")


def ligne_de_base(r) -> dict:
    """Une ligne `events` (sqlite3.Row ou dict) en dict, métadonnées lues."""
    d = dict(r)
    try:
        d["metadata"] = json.loads(d.get("metadata") or "{}") if isinstance(
            d.get("metadata"), (str, bytes, type(None))) else d["metadata"]
    except json.JSONDecodeError:
        d["metadata"] = {}
    if isinstance(d.get("corrections"), str):
        try:
            d["corrections"] = json.loads(d["corrections"]) or None
        except json.JSONDecodeError:
            d["corrections"] = None
    return d


def acte_de_ligne(ligne: dict) -> Acte | None:
    cle = cle_de_ligne(ligne["type"], ligne.get("date"), ligne.get("metadata"),
                       ligne.get("title"))
    if cle is None:
        return None
    meta = ligne.get("metadata") or {}
    v = vue(ligne)
    return Acte(
        id=ligne["id"], type=ligne["type"], cle=cle.valeur, faible=cle.faible,
        prefixe=PREFIXE_PAR_TYPE[ligne["type"]], date=ligne["date"][:10],
        titre=(ligne.get("title") or "").strip(), numero=meta.get("numero_acte"),
        texte=compact(ligne.get("content") or ""),
        montants=set(v["montants"]), source_url=ligne.get("source_url"),
        empreinte=empreinte_vue(v), vue=v)


class Index:
    """Les actes et séances publiés, par clé et par séance."""

    def __init__(self, actes: list[Acte]):
        self.par_cle: dict[str, Acte] = {}
        self.collisions: set[str] = set()
        self.par_seance: dict[tuple[str, str], list[Acte]] = {}
        for a in actes:
            if a.cle in self.par_cle:
                # Deux lignes publiées sous la même clé : aucune ne peut être LA
                # cible d'un lien. Elles restent atteignables par la séance.
                self.collisions.add(a.cle)
            self.par_cle[a.cle] = a
            if not a.seance:
                self.par_seance.setdefault((a.prefixe, a.date), []).append(a)
        for c in self.collisions:
            del self.par_cle[c]

    def __len__(self) -> int:
        return len(self.par_cle)

    def acte(self, cle: str) -> Acte | None:
        a = self.par_cle.get(cle)
        return a if a and not a.seance else None

    def seance(self, prefixe: str, date: str) -> Acte | None:
        s = self.par_cle.get(f"{prefixe}-{date}")
        return s if s and s.seance else None

    def actes_du(self, prefixe: str, date: str) -> list[Acte]:
        return list(self.par_seance.get((prefixe, date), []))


TYPES_INDEXES = TYPES_ACTES + TYPES_SEANCES


def lignes_en_base(conn) -> list[dict]:
    """Les actes et séances de la base, corrections de l'atelier comprises."""
    colonnes = {r[1] for r in conn.execute("PRAGMA table_info(annotations)")}
    corr = ("(SELECT a.corrections FROM annotations a WHERE a.object_type='deliberation' "
            "AND a.object_id=e.id)" if "corrections" in colonnes else "NULL")
    marques = ",".join("?" for _ in TYPES_INDEXES)
    curseur = conn.execute(
        f"SELECT e.id, e.type, e.date, e.title, e.content, e.source, e.source_url, "
        f"e.metadata, {corr} AS corrections FROM events e WHERE e.type IN ({marques})",
        TYPES_INDEXES)
    noms = [d[0] for d in curseur.description]
    return [ligne_de_base(dict(zip(noms, r))) for r in curseur.fetchall()]


def index_de(lignes: list[dict], publies=None) -> Index:
    """L'index des lignes PUBLIÉES. `publies` : l'ensemble des identifiants qui
    sortent (au snapshot, ceux de `events.json`), ou un prédicat sur la ligne
    (à l'atelier, `publiable_selon_regles`). Rien n'entre sans y passer."""
    garde = publies if callable(publies) else (lambda l: l["id"] in publies)
    return Index([a for l in lignes if garde(l) and (a := acte_de_ligne(l))])


def publiable_selon_regles(regles: dict, ecartes: set[int]):
    """Le prédicat de publication d'un acte, tel que le snapshot l'applique
    (`build_public_snapshot.py`, boucle des événements) : source admise, type
    non exclu, pas écarté à l'atelier. Sert à l'ATELIER, qui n'a pas de
    snapshot sous la main au moment où un validateur retient un dossier."""
    ev = (regles or {}).get("events", {})
    sources = set(ev.get("public_sources", []))
    exclus = set(ev.get("exclude_types", []))
    return lambda l: (l.get("source") in sources and l["type"] not in exclus
                      and l["id"] not in ecartes)


def ecartes_en_base(conn) -> set[int]:
    from .verdict import ecarte
    return {oid for oid, st in conn.execute(
        "SELECT object_id, review_status FROM annotations WHERE object_type='deliberation'")
        if ecarte(st)}


def index_selon_regles(conn, regles: dict) -> Index:
    return index_de(lignes_en_base(conn), publiable_selon_regles(regles, ecartes_en_base(conn)))


# ─── Les résolveurs ──────────────────────────────────────────────────────────

@dataclass
class Resolution:
    statut: str                 # precis | imprecis | non_resolu
    type: str                   # acte | seance | piece
    cible: Acte | None = None
    url: str | None = None
    raison: str = ""
    candidats: list = field(default_factory=list)   # clés, pour l'atelier


def _resoudre_acte(cle: str, index: Index, **_) -> Resolution:
    a = index.acte(cle)
    if a:
        return Resolution("precis", "acte", a, a.url,
                          "clé faible : ce lien peut changer au prochain rejeu" if a.faible else "")
    s = index.par_cle.get(cle)
    if s and s.seance:      # une clé de séance écrite avec `acte:`
        return _resoudre_seance(cle, index)
    if cle in index.collisions:
        return Resolution("non_resolu", "acte", raison="deux actes publiés portent cette clé")
    return Resolution("non_resolu", "acte", raison="aucun acte publié sous cette clé")


def _resoudre_seance(cle: str, index: Index, **_) -> Resolution:
    s = index.par_cle.get(cle)
    if s and s.seance:
        return Resolution("precis", "seance", s, s.url)
    return Resolution("non_resolu", "seance", raison="aucune séance publiée sous cette clé")


def _resoudre_piece(cle: str, index: Index, **_) -> Resolution:
    a = index.par_cle.get(cle)
    if a and a.source_url and re.match(r"^https?://", a.source_url):
        return Resolution("precis", "piece", a, a.source_url)
    if a:
        return Resolution("non_resolu", "piece", raison="la pièce source de cet acte n'est pas publiée")
    return Resolution("non_resolu", "piece", raison="aucun acte publié sous cette clé")


#: La table des types de cible. Ajouter « fait en base » (indicateur, compte)
#: = une entrée ici, et la syntaxe `[texte](fait:…)` dans `EXPLICITE`.
RESOLVEURS = {"acte": _resoudre_acte, "seance": _resoudre_seance, "piece": _resoudre_piece}


def _departager(candidats: list[Acte], contexte: str, objet: str = "") -> tuple[list[Acte], str]:
    """Ce que la phrase dit d'autre que la date : une citation entre
    guillemets retrouvée dans le texte d'un seul acte, un montant voté par un
    seul, ou (dans une frise) l'objet de la ligne proche d'un seul titre."""
    for m in _GUILLEMETS.finditer(contexte):
        cite = compact(m.group(1) or m.group(2))
        if len(cite) >= 10:
            ok = [a for a in candidats if cite in a.texte or cite in compact(a.titre)]
            if len(ok) == 1:
                return ok, "citation retrouvée dans le texte de l'acte"
    sommes = montants_cites(contexte)
    if sommes:
        ok = [a for a in candidats if a.montants & sommes]
        if len(ok) == 1:
            return ok, "montant retrouvé dans l'acte"
    mots = {w for w in re.findall(r"[a-z]{4,}", _ascii(objet))}
    if len(mots) >= 2:
        scores = sorted(((len(mots & set(re.findall(r"[a-z]{4,}", _ascii(a.titre)))) / len(mots), a)
                         for a in candidats), key=lambda x: -x[0])
        if scores and scores[0][0] >= 0.5 and (len(scores) == 1 or scores[1][0] < scores[0][0]):
            return [scores[0][1]], "objet de la frise proche du titre de l'acte"
    return candidats, ""


def resoudre_naturelle(prefixe: str | None, date: str | None, numero: str | None,
                       annee: str | None, index: Index, contexte: str = "",
                       objet: str = "") -> Resolution:
    """Une citation en français : une assemblée (ou aucune), une date ou une
    année, peut-être un numéro."""
    prefixes = [prefixe] if prefixe else ["c", "cc"]
    if numero:
        trouves = []
        for p in prefixes:
            c = cle_acte(TYPE_ACTE[p], date or f"{annee}-01-01", numero)
            if c and (a := index.acte(c.valeur)):
                trouves.append(a)
        if len(trouves) == 1:
            return Resolution("precis", "acte", trouves[0], trouves[0].url)
    if not date:
        return Resolution("non_resolu", "acte", raison="aucun acte publié ne porte ce numéro cette année-là")

    actes = [a for p in prefixes for a in index.actes_du(p, date)]
    seances = [s for p in prefixes if (s := index.seance(p, date))]
    if len(actes) == 1:
        return Resolution("precis", "acte", actes[0], actes[0].url)
    if len(actes) > 1:
        retenus, pourquoi = _departager(actes, contexte, objet)
        if len(retenus) == 1:
            return Resolution("precis", "acte", retenus[0], retenus[0].url, pourquoi)
        if len(seances) == 1:
            return Resolution("imprecis", "seance", seances[0], seances[0].url,
                              f"la séance a pris {len(actes)} actes publiés, la phrase ne dit pas lequel",
                              candidats=[a.cle for a in actes])
        return Resolution("non_resolu", "acte",
                          raison=f"{len(actes)} actes publiés ce jour-là et aucune séance publiée pour les rassembler",
                          candidats=[a.cle for a in actes])
    if len(seances) == 1:
        return Resolution("imprecis", "seance", seances[0], seances[0].url,
                          "séance publiée, mais aucun de ses actes ne l'est")
    if len(seances) > 1:
        return Resolution("non_resolu", "seance",
                          raison="un conseil municipal ET un conseil communautaire ce jour-là : préciser CM ou CC")
    return Resolution("non_resolu", "acte", raison="aucun acte ni aucune séance publiés à cette date")


# ─── Relier un texte ─────────────────────────────────────────────────────────

@dataclass
class Citation:
    texte: str
    forme: str                  # explicite | naturelle | frise
    ligne: int
    section: str | None
    resolution: Resolution
    #: Pour une ligne de frise : ce que la ligne dit de l'acte (sa colonne
    #: « Acte »). C'est ce qui permet de poser la question sans relire le dossier.
    objet: str = ""

    def public(self, affiche: dict | None = None) -> dict:
        """Ce que le site reçoit d'une citation résolue (rien des autres).

        `affiche` : la ligne de l'acte telle que `events.json` la publie. Le
        titre, le vote et la pièce viennent de LÀ, jamais de la base : un titre
        y est masqué (domicile, naissance), et l'infobulle d'un dossier ne doit
        pas en dire plus que la page de l'acte."""
        r = self.resolution
        a = r.cible
        affiche = affiche or {}
        d = {"url": r.url, "statut": r.statut, "type": r.type, "cle": a.cle,
             "assemblee": a.assemblee, "date": a.date,
             "titre": affiche.get("title") or a.titre}
        if a.numero and not a.seance:
            d["numero"] = a.numero
        if affiche.get("vote"):
            d["vote"] = affiche["vote"]
        source = affiche.get("pdf_url") or affiche.get("source_url")
        if source:
            d["source_url"] = source
        if a.faible:
            d["cle_faible"] = True
        if r.raison:
            d["raison"] = r.raison
        return d

    def releve(self) -> dict:
        r = self.resolution
        return {"texte": self.texte, "forme": self.forme, "ligne": self.ligne,
                "objet": self.objet or None,
                "section": self.section, "ancre": ancre(self.section) if self.section else None,
                "statut": r.statut, "type": r.type, "raison": r.raison,
                "cle": r.cible.cle if r.cible else None, "candidats": r.candidats}


@dataclass
class Relie:
    texte: str
    citations: list[Citation]

    @property
    def resolues(self) -> list[Citation]:
        return [c for c in self.citations if c.resolution.statut != "non_resolu"]

    @property
    def non_resolues(self) -> list[Citation]:
        return [c for c in self.citations if c.resolution.statut == "non_resolu"]


def _titre_lien(c: Citation) -> str:
    """L'infobulle sans JavaScript : ce que l'on ouvre."""
    r = c.resolution
    a = r.cible
    if r.type == "piece":
        quoi = "Pièce source"
    elif a.seance:
        quoi = f"Séance — {a.assemblee} du {a.date[8:10]}/{a.date[5:7]}/{a.date[:4]}"
    else:
        num = f" n°{a.numero}" if a.numero else ""
        quoi = f"Délibération{num} — {a.assemblee} du {a.date[8:10]}/{a.date[5:7]}/{a.date[:4]} — {a.titre}"
    if r.statut == "imprecis":
        quoi += " (renvoi imprécis : " + r.raison + ")"
    # Ni guillemet droit ni barre oblique inverse : le titre est posé entre
    # guillemets dans le markdown, et rien d'autre que du texte ne doit en sortir.
    quoi = re.sub(r"\s+", " ", quoi.replace('"', "”").replace("\\", " "))
    return quoi[:240]


def _lien(c: Citation) -> str:
    return f'[{c.texte}]({c.resolution.url} "{_titre_lien(c)}")'


def _naturelles(ligne: str, interdits: list[tuple[int, int]], index: Index,
                no: int, section: str | None) -> list[tuple[int, int, Citation]]:
    trouvees = []

    def libre(d, f):
        return not any(d < b and a < f for a, b in interdits)

    for m in NATURELLE.finditer(ligne):
        if not (m.group("delib") or m.group("ass")) or not libre(m.start(), m.end()):
            continue
        iso = _iso(m)
        if not iso:
            continue
        debut_ctx = max([b for a, b in interdits if b <= m.start()] + [0])
        r = resoudre_naturelle(_prefixe(m.group("ass")), iso, m.group("num"), iso[:4],
                               index, contexte=ligne[debut_ctx:m.start()] + ligne[m.end():])
        trouvees.append((m.start(), m.end(), Citation(m.group(0), "naturelle", no, section, r)))
        interdits = interdits + [(m.start(), m.end())]
    for m in NUMEROTEE.finditer(ligne):
        if not libre(m.start(), m.end()):
            continue
        num, annee = (m.group("num1"), m.group("a1")) if m.group("num1") else (m.group("num2"), m.group("a2"))
        premier = m.group(0).split()[0].upper()
        prefixe = _prefixe(m.group("ass") or (premier if premier in ("CM", "CC") else None))
        r = resoudre_naturelle(prefixe, None, num, annee, index)
        trouvees.append((m.start(), m.end(), Citation(m.group(0), "naturelle", no, section, r)))
    return trouvees


def _frise(ligne: str, index: Index, no: int, section: str | None):
    """Une ligne de tableau : une cellule date, une cellule CM ou CC. On relie
    la date — c'est elle que le lecteur cherche dans la frise."""
    if not ligne.lstrip().startswith("|") or re.match(r"^\s*\|[\s:|-]+\|?\s*$", ligne):
        return []
    cellules = ligne.split("|")
    dates = [(i, m) for i, c in enumerate(cellules) if (m := _CELLULE_DATE.match(c))]
    assemblees = [_CELLULE_ASSEMBLEE.match(c).group(1) for c in cellules if _CELLULE_ASSEMBLEE.match(c)]
    if len(dates) != 1 or len(assemblees) != 1:
        return []
    i, m = dates[0]
    iso = _iso(m)
    if not iso:
        return []
    objet = " ".join(c for j, c in enumerate(cellules) if j != i and not _CELLULE_ASSEMBLEE.match(c))
    r = resoudre_naturelle(_prefixe(assemblees[0]), iso, None, iso[:4], index,
                           contexte=objet, objet=objet)
    debut = sum(len(c) + 1 for c in cellules[:i])
    texte = cellules[i].strip()
    debut += cellules[i].index(texte)
    objet = re.sub(r"\s+", " ", objet).strip()
    return [(debut, debut + len(texte), Citation(texte, "frise", no, section, r, objet))]


_ENTETE = re.compile(r"^---\n[\s\S]*?\n---\n?")


def relier(texte: str, index: Index) -> Relie:
    """Le markdown d'un dossier, ses citations reliées, et le relevé de toutes.

    Une citation résolue devient un lien `[texte](/deliberations/2021#c-2021-41
    "infobulle")` ; une citation explicite non résolue perd son lien et garde
    son texte ; une citation naturelle non résolue reste telle quelle. Les
    titres (`#`), les blocs de code et les liens déjà écrits ne sont pas lus :
    relier un titre changerait l'ancre de sa partie.
    """
    m = _ENTETE.match(texte)
    tete, corps = (texte[:m.end()], texte[m.end():]) if m else ("", texte)
    lignes = corps.split("\n")
    decalage = tete.count("\n")
    citations: list[Citation] = []
    section, dans_code = None, False
    sortie = []
    for no, ligne in enumerate(lignes, start=decalage + 1):
        if ligne.lstrip().startswith("```"):
            dans_code = not dans_code
            sortie.append(ligne)
            continue
        if dans_code:
            sortie.append(ligne)
            continue
        if h := re.match(r"^##\s+(.+?)\s*#*\s*$", ligne):
            section = h.group(1)
        if ligne.lstrip().startswith("#"):
            sortie.append(ligne)
            continue
        morceaux = []   # (début, fin, remplacement)
        for e in EXPLICITE.finditer(ligne):
            r = RESOLVEURS[e.group("type")](e.group("cle"), index)
            c = Citation(e.group("texte"), "explicite", no, section, r)
            citations.append(c)
            morceaux.append((e.start(), e.end(),
                             _lien(c) if r.statut != "non_resolu" else e.group("texte")))
        interdits = [(a, b) for a, b, _ in morceaux] + [(x.start(), x.end()) for x in LIEN.finditer(ligne)]
        trouvees = _frise(ligne, index, no, section) or _naturelles(ligne, interdits, index, no, section)
        for d, f, c in trouvees:
            citations.append(c)
            if c.resolution.statut != "non_resolu":
                morceaux.append((d, f, _lien(c)))
        for d, f, rempl in sorted(morceaux, key=lambda x: -x[0]):
            ligne = ligne[:d] + rempl + ligne[f:]
        sortie.append(ligne)
    citations.sort(key=lambda c: c.ligne)
    return Relie(tete + "\n".join(sortie), citations)
