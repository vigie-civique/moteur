"""
pv_parsers.py — Lire un procès-verbal de séance : présences et délibérations.

Ces analyseurs ne connaissent ni CMS ni commune : ils prennent du texte extrait
d'un PDF et rendent des structures. Ce qui varie d'une collectivité à l'autre,
c'est la MISE EN FORME du document, pas la nature de ce qu'on y cherche.

Trois régimes ont été rencontrés sur un même corpus de 217 procès-verbaux
couvrant vingt-deux ans, et un quatrième sur celui de l'intercommunalité :

    numerote   « 48/2026 : n° 4713 : Objet de la délibération »
               numéro dans la séance, puis numéro de l'acte transmis au
               contrôle de légalité. Découpage fiable.
    acte_final « Objet de la délibération (N° DE_2026_086) »
               l'identifiant clôt la ligne du titre. Découpage fiable.
    puces      compte rendu synthétique, un point par puce.
               Découpage acceptable.
    suivi      texte suivi dont les titres ne se distinguent que par la graisse,
               perdue à l'extraction. AUCUN découpage — et c'est le cas
               important : fabriquer des délibérations en devinant où elles
               commencent produirait des actes qui n'ont jamais existé. La
               séance est alors enregistrée avec son texte intégral et le fait
               que le découpage a échoué.

    capitales  titres en capitales, séparés du corps par un filet ou un saut.
               Découpage acceptable, mais silencieux sur ses limites : un
               intertitre en capitales devient une délibération de plus.

`deliberations()` essaie les quatre régimes dans l'ordre et rend une liste vide
plutôt qu'un découpage inventé. L'ordre compte : un identifiant d'acte est une
preuve, une mise en capitales n'est qu'un indice.
"""
from __future__ import annotations

import re

from .cm_parser import (categorize, extract_amounts, extract_vote,
                        split_into_deliberations)

# ── Régime « numéroté » : NN/AAAA [: n° NNNN] ────────────────────────────────
# Le séparateur entre les deux numéros a été « : », « – n° », « - n° » selon les
# années, et le numéro d'acte manque sur certains procès-verbaux.
ENTETE_NUMEROTE = re.compile(
    r"^[  ]*(\d{1,3})\s*/\s*(20\d{2})\s*(?:[:–—-]\s*)?(?:n[°ºo]\s*(\d{3,5}))?\s*:?\s*",
    re.M)
# Fin de titre : la formule de transmission, ou le premier visa.
FIN_TITRE = re.compile(r"(Acte rendu exécutoire|^\s*(?:Vu|Considérant|Monsieur|"
                       r"Madame|Le Conseil|Après)\b)", re.M)

# ── Régime « acte final » : … (N° DE_2026_086) ───────────────────────────────
ACTE_FINAL = re.compile(r"\(\s*N[°ºo]?\s*(?:DE\s*)?([A-Z]{2}_\d{4}_\d+)\s*\)")
LIGNE_CAPITALES = re.compile(r"^[^a-z]{8,}$")

# ── Régime « puces » ─────────────────────────────────────────────────────────
# `(cid:N)` est la façon dont pdfplumber rend une puce d'une police non standard.
PUCE = re.compile(r"^\s*(?:\(cid:\d+\)|[•▪–])\s*(.{6,150}?)\s*:\s", re.M)


def deliberations(texte: str) -> list[dict]:
    """Découpe un procès-verbal, ou rend [] si aucun régime ne s'applique."""
    for analyseur in (_numerote, _acte_final, _puces, _capitales):
        sorties = analyseur(texte)
        if sorties:
            return sorties
    return []


def _enrichir(d: dict) -> dict:
    d["categorie"], d["tags"] = categorize(d["titre"])
    d["vote"] = extract_vote(d["texte"])
    d["montants"] = extract_amounts(d["texte"])
    return d


def _numerote(texte: str) -> list[dict]:
    marques = list(ENTETE_NUMEROTE.finditer(texte))
    sorties = []
    for i, m in enumerate(marques):
        fin = marques[i + 1].start() if i + 1 < len(marques) else len(texte)
        corps = texte[m.end():fin].strip()
        if not corps:
            continue
        coupe = FIN_TITRE.search(corps)
        titre = re.sub(r"\s+", " ", corps[:coupe.start()] if coupe else corps[:300])
        titre = titre.strip(" :;.-")
        if len(titre) < 5:
            continue
        sorties.append(_enrichir({
            "regime": "numerote",
            "numero_seance": f"{m.group(1)}/{m.group(2)}",
            "numero_acte": m.group(3),
            "titre": titre[:255],
            "texte": corps,
        }))
    return sorties


def _acte_final(texte: str) -> list[dict]:
    """L'identifiant clôt la ligne du titre ; le titre peut déborder au-dessus.

    Deux mises en forme coexistent dans le même corpus : titres en capitales sur
    plusieurs lignes, et titres en casse normale sur une ligne. Ne remonter que
    sur les lignes capitales rendait « Délibération DE_2026_049 » pour tout le
    second format, soit la moitié du corpus sans titre.
    """
    marques = list(ACTE_FINAL.finditer(texte))
    if not marques:
        return []
    debut = 0
    ouverture = re.search(r"Délibérations du conseil\s*:", texte, re.I)
    if ouverture:
        debut = ouverture.end()

    sorties, precedent, curseur = [], None, debut
    for m in marques:
        lignes = texte[curseur:m.start()].splitlines()
        titre_lignes = [lignes.pop().strip()] if lignes else []
        for _ in range(3):
            if not lignes:
                break
            debute_mal = bool(re.match(r"[a-z0-9«»(,]", titre_lignes[0] or "x"))
            if LIGNE_CAPITALES.match(lignes[-1].strip()) or debute_mal:
                titre_lignes.insert(0, lignes.pop().strip())
            else:
                break
        if precedent is not None:
            precedent["texte"] = "\n".join(lignes).strip()
        titre = re.sub(r"\s+", " ", " ".join(titre_lignes)).strip(" :;.-")
        precedent = {"regime": "acte_final", "numero_seance": None,
                     "numero_acte": m.group(1),
                     "titre": (titre or f"Délibération {m.group(1)}")[:255],
                     "texte": ""}
        sorties.append(precedent)
        curseur = m.end()
    if precedent is not None:
        precedent["texte"] = texte[curseur:].strip()
    return [_enrichir(d) for d in sorties]


def _puces(texte: str) -> list[dict]:
    marques = list(PUCE.finditer(texte))
    sorties = []
    for i, m in enumerate(marques):
        fin = marques[i + 1].start() if i + 1 < len(marques) else len(texte)
        sorties.append(_enrichir({
            "regime": "puces", "numero_seance": None, "numero_acte": None,
            "titre": re.sub(r"\s+", " ", m.group(1)).strip(" :;.-")[:255],
            "texte": texte[m.end():fin].strip(),
        }))
    return sorties


def _sans_entetes(texte: str) -> str:
    """Retire les lignes répétées d'un PDF : en-tête et pied de page.

    Un procès-verbal de vingt-quatre pages répète son en-tête vingt-quatre
    fois. Le découpeur par capitales en fait autant de titres, et la séance
    ressort avec deux fois plus de délibérations qu'elle n'en a pris.
    """
    from collections import Counter
    lignes = texte.splitlines()
    compte = Counter(l.strip() for l in lignes if l.strip())
    repetees = {l for l, n in compte.items() if n >= 4 and len(l) < 60}
    return "\n".join(l for l in lignes if l.strip() not in repetees)


def _apres_entete(texte: str) -> str:
    """Le corps commence après le bloc de présences, jamais avant.

    Sans cette borne, la liste des présents — en capitales, elle aussi — ouvre
    une première « délibération » intitulée du nom des conseillers.
    """
    for motif in (r"[Ss]ecrétaire de séance", r"^_{5,}$", r"ORDRE DU JOUR"):
        m = re.search(motif, texte, re.M)
        if m:
            return texte[m.end():]
    return texte


def _capitales(texte: str) -> list[dict]:
    """Dernier recours : les titres sont en capitales, le corps ne l'est pas.

    S'appuie sur le découpeur historique du dispositif, éprouvé sur les procès-
    verbaux de l'instance de référence — le seul des quatre régimes qui ne
    dispose d'aucun identifiant d'acte pour se vérifier. On l'essaie en dernier
    pour cette raison.
    """
    propre = _apres_entete(_sans_entetes(texte))
    blocs = split_into_deliberations([l for l in propre.splitlines() if l.strip()])
    sorties = []
    for bloc in blocs:
        titre = re.sub(r"\s+", " ", bloc["titre"]).strip(" :;.-")
        if len(titre) < 6 or len(re.findall(r"\b(?:M\.|Mme|Mlle)\s", titre)) >= 2:
            continue
        sorties.append(_enrichir({
            "regime": "capitales", "numero_seance": None, "numero_acte": None,
            "titre": titre[:255], "texte": "\n".join(bloc["paragraphes"]),
        }))
    return sorties


# ── Présences ────────────────────────────────────────────────────────────────
#
# Deux conventions d'écriture, qui exigent deux lectures :
#   « Présents : Mesdames Prénom NOM, Prénom NOM et Messieurs Prénom NOM »
#   « Présents : NOM COMPOSÉ Prénom, NOM Prénom, … »
# La seconde met le patronyme d'abord et peut lui donner deux mots.

CIVILITES = ("Mesdames", "Messieurs", "Madame", "Monsieur", "Mmes", "Mme",
             "MM.", "M.", "Melle", "Mesdemoiselles")

# Le prénom composé n'admet le trait d'union QUE devant une nouvelle majuscule :
# avec le tiret dans la classe de caractères, « Jean-Claude » s'arrête sur
# « Jean- », le moteur d'expressions régulières n'ayant aucune raison de revenir
# en arrière quand la capture réussit déjà. Ce piège s'est présenté trois fois.
PRENOM_NOM = re.compile(
    r"([A-ZÀÂÇÉÈÊËÎÏÔÙÛÜ][a-zà-ÿ'’]+(?:[- ][A-ZÀÂÇÉÈÊËÎÏÔÙÛÜ][a-zà-ÿ'’]+)*)"
    r"\s+([A-ZÀÂÇÉÈÊËÎÏÔÙÛÜ][A-ZÀÂÇÉÈÊËÎÏÔÙÛÜ'’\-]{2,})")
NOM_PRENOM = re.compile(
    r"\b([A-ZÀ-Ÿ][A-ZÀ-Ÿ'’\-]{1,}(?:\s+[A-ZÀ-Ÿ][A-ZÀ-Ÿ'’\-]{1,})*)\s+"
    r"([A-ZÀ-Ÿ][a-zà-ÿ'’]+(?:[- ][A-ZÀ-Ÿ][a-zà-ÿ'’]+)*)")
# « PRÉSENTS : M. NOM, Mme NOM, … » — la civilité tient lieu de prénom, qui
# n'est pas donné. Le rapprochement avec la table des personnes se fera sur le
# seul patronyme, ce qui est moins sûr : deux homonymes ne se distinguent plus.
CIVILITE_NOM = re.compile(
    r"\b(?:M\.|Mme|Mlle|MM\.|Mmes)\s+((?:de\s+|d')?[A-ZÀ-Ÿ][A-ZÀ-Ÿ'’\-]{2,}"
    r"(?:\s+[A-ZÀ-Ÿ][A-ZÀ-Ÿ'’\-]{2,})?)")
NOM_INVERSE_CIVILITE = re.compile(
    r"(?:Monsieur|Madame)\s+([A-ZÀÂÇÉÈÊËÎÏÔÙÛÜ][A-ZÀÂÇÉÈÊËÎÏÔÙÛÜ'’\-]{2,})"
    r"\s+([A-ZÀÂÇÉÈÊËÎÏÔÙÛÜ][a-zà-ÿ]+)")

# « a donné procuration à », « ayant donné procuration à », et — vu en 2019 —
# « ayant donné procuration » sans préposition. Le « à » est donc optionnel.
# Quatre formulations rencontrées : « a donné procuration à », « ayant donné
# procuration à », « ayant donné procuration » sans préposition, et « donne
# pouvoir pour voter en son nom à ».
PROCURATION = re.compile(
    r"(?:Monsieur|Madame|M\.|Mme)?\s*([A-ZÀ-Ÿa-zà-ÿ'’\- ]{4,40}?)\s+"
    r"(?:(?:a|ayant)\s+donné\s+procuration|donne\s+pouvoir(?:\s+pour\s+voter"
    r"\s+en\s+son\s+nom)?)\s+(?:à\s+)?(?:Monsieur|Madame|M\.|Mme)?\s*"
    r"([A-ZÀ-Ÿa-zà-ÿ'’\- ]{4,40})", re.I)
REPRESENTATION = re.compile(
    r"([A-ZÀ-Ÿ][A-ZÀ-Ÿ'’\- ]+ [A-ZÀ-Ÿ][a-zà-ÿ\-]+)\s+représenté?e?\s+par\s+"
    r"([A-ZÀ-Ÿ][A-ZÀ-Ÿ'’\- ]+ [A-ZÀ-Ÿ][a-zà-ÿ\-]+)", re.I)

BLOC_PRESENTS = re.compile(
    r"Présents?\s*:(.*?)(?:Représentés?\s*:|Absente?s?\s*:|Secrétaire"
    r"|Date de la publi|Ordre du jour|Délibérations)", re.S | re.I)
BLOC_REPRESENTES = re.compile(
    r"Représentés?\s*:(.*?)(?:Absents?|Délibérations|Secrétaire|$)", re.S | re.I)
BLOC_ABSENTS = re.compile(
    r"Absente?s?(?:\s+et\s+excusés?)?\s*:(.*?)(?:Secrétaire|Date de la publi"
    r"|Ordre du jour|Délibérations|$)", re.S | re.I)
PRESIDENCE = re.compile(
    r"sous la [Pp]résidence de\s+(?:Monsieur|Madame|M\.|Mme)?\s*"
    r"([A-ZÀ-Ÿa-zà-ÿ'’\- ]{4,45}?)\s*(?:,|\.|\bMaire\b)")


def _sans_civilite(nom: str) -> str:
    n = re.sub(r"\s+", " ", (nom or "").strip())
    for c in CIVILITES:
        if n.startswith(c + " "):
            n = n[len(c) + 1:]
            break
    return n.strip(" ,;.")


def _borner(bloc: str) -> str:
    """Coupe un bloc d'en-tête là où commence le corps du document.

    « Absents et excusés : X, Y » est parfois suivi directement du titre de la
    première délibération. Sans borne, la liste des absents avalait ce titre et
    le bloc de signature d'en face — d'où des « absents » nommés « Mme AUTORISE ».
    """
    bloc = bloc.split("Délibérations")[0]
    m = ACTE_FINAL.search(bloc)
    if m:
        bloc = bloc[:bloc.rfind("\n", 0, m.start()) + 1 or m.start()]
    return bloc.strip()


def noms(bloc: str, ordre: str = "prenom_nom") -> list[str]:
    """Noms d'un bloc de présence, rendus « Prénom NOM ».

    Le rapprochement avec la table des personnes se fait sur le patronyme en
    capitales : deux conventions d'écriture dans la même base finissent toujours
    par produire deux personnes là où il n'y en a qu'une.
    """
    if not bloc:
        return []
    # Le PDF coupe les noms en fin de ligne, y compris au milieu d'un prénom
    # composé : recoller avant de découper, sans quoi le conseiller entre en
    # base sous le prénom « Jean- ».
    bloc = bloc.replace("-\n", "-").replace("\n", " ")

    trouves = []
    if ordre == "civilite_nom":
        trouves += [n.strip() for n in CIVILITE_NOM.findall(bloc)]
    elif ordre == "prenom_nom":
        trouves += [f"{p} {n}" for n, p in NOM_INVERSE_CIVILITE.findall(bloc)]
        bloc = NOM_INVERSE_CIVILITE.sub(" ", bloc)
        for c in CIVILITES:
            bloc = bloc.replace(c + " ", " ")
        trouves += [f"{p} {n}" for p, n in PRENOM_NOM.findall(bloc)]
    else:
        for segment in bloc.split(","):
            m = NOM_PRENOM.search(segment.strip())
            if m:
                trouves.append(f"{m.group(2)} {m.group(1)}")

    vus, sortie = set(), []
    for n in trouves:
        if n.upper() not in vus:
            vus.add(n.upper())
            sortie.append(n)
    return sortie


def presences(texte: str, ordre: str = "prenom_nom") -> dict:
    """Présents, absents, procurations, depuis l'en-tête du procès-verbal.

    L'en-tête tient dans les premiers milliers de caractères, et les blocs sont
    bornés : sur un document de 35 000 caractères, un « Absents : » ouvert
    jusqu'au prochain mot-clé ramassait les signatures de fin de document.
    """
    tete = texte[:3000]
    res = {"presents": [], "absents": [], "pouvoirs": []}

    m = BLOC_PRESENTS.search(tete)
    if m:
        # Les procurations se glissent DANS le bloc des présents autant que dans
        # celui des absents. Les y laisser rendait présent celui qui avait donné
        # pouvoir, c'est-à-dire l'inverse.
        res["presents"] = noms(_borner(PROCURATION.sub(" ", m.group(1)[:900])), ordre)

    # Le maire ou le président ne figure pas dans la liste : seulement dans la
    # formule d'ouverture. L'omettre revenait à publier un conseil sans sa
    # présidence.
    m = PRESIDENCE.search(tete)
    if m:
        president = _sans_civilite(m.group(1))
        if president and president.upper() not in {n.upper() for n in res["presents"]}:
            res["presents"].insert(0, president)

    for donneur, receveur in PROCURATION.findall(tete):
        res["pouvoirs"].append({"de": _sans_civilite(donneur),
                                "à": _sans_civilite(receveur)})
    m = BLOC_REPRESENTES.search(tete)
    if m:
        for absent, mandataire in REPRESENTATION.findall(_borner(m.group(1)[:600])):
            res["pouvoirs"].append({"de": _retourner(absent, ordre),
                                    "à": _retourner(mandataire, ordre)})

    m = BLOC_ABSENTS.search(tete)
    if m:
        bloc = PROCURATION.sub(" ", _borner(m.group(1)[:600]))
        res["absents"] = noms(bloc, ordre)
    return res


def _retourner(nom: str, ordre: str) -> str:
    if ordre == "prenom_nom":
        return _sans_civilite(nom)
    m = NOM_PRENOM.search((nom or "").strip())
    return f"{m.group(2)} {m.group(1)}" if m else (nom or "").strip()
