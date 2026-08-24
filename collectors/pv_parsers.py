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

    liste      un ordre du jour NUMÉROTÉ : « 1. », « 01. », « III. », « XVI. »,
               le corps de chaque délibération en dessous. Découpage fiable —
               c'est la suite qui l'autorise, et elle s'arrête d'elle-même.
    capitales  titres en capitales, séparés du corps par un filet ou un saut.
               Découpage acceptable, mais silencieux sur ses limites : un
               intertitre en capitales devient une délibération de plus.

`deliberations()` essaie les cinq régimes dans l'ordre et rend une liste vide
plutôt qu'un découpage inventé. L'ordre compte : un identifiant d'acte est une
preuve, une mise en capitales n'est qu'un indice.

Le régime `liste` a tenu jusqu'au 21/08/2026 son autorisation d'un EN-TÊTE —
« Délibérations : » — et non de sa numérotation. La mesure sur 389 procès-verbaux
de trois communes a montré que les 21 documents qu'il découpait l'étaient TOUS à
tort, pour 4 337 des 5 529 actes du corpus de Lasalle. Le détail est sous
`_liste`. C'est la leçon du module, vérifiée une fois de plus : ce qui autorise
un découpage est une preuve interne au document, jamais une formule d'annonce.
"""
from __future__ import annotations

import re
import unicodedata

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


# Un chiffre qui compte dans un tableau : montant ou pourcentage. Les deux
# notations décimales cohabitent dans un même procès-verbal — « 8 800,00 € » et
# « 52 655.52 € » — et n'en reconnaître qu'une laissait passer la moitié des
# lignes de tableau : « DETR 52 655.52 € 27.62 % » était publiée comme un acte.
_MONTANT_TITRE = re.compile(
    r"\d{1,3}(?:[  ]\d{3})*[.,]\d{1,2}\s*[€%]|\d[\d  ]*\s*[€%]")
# Un mot porteur de sens : au moins quatre lettres, pas de chiffre dedans.
_MOT_PORTEUR = re.compile(r"\b[^\W\d_]{4,}\b", re.UNICODE)
# Un nombre À DÉCIMALES. Une ligne de tableau en aligne plusieurs — « LANUEJOLS
# ETAGE N° 9 39,60 318.37 190 € » en porte deux, avec assez de mots pour passer
# la règle précédente. Compter TOUS les nombres refusait de vraies délibérations :
# « N°4280 : Vente parcelles cadastrées section A n°836 et n°838 » en aligne trois,
# et « Vu la loi n° 2005-102 du 11 février 2005 » aussi. Un numéro d'acte, une
# parcelle, une année sont des entiers ; une colonne de tableau porte des centimes.
# Les décimales se lisent AU BORD du nombre : sans les deux gardes, « la loi
# n° 82.213 » et « 01.01.2016 au 31.12.2016 » passaient pour des montants, et
# deux vraies délibérations de Brassac disparaissaient.
_DECIMAL = re.compile(r"(?<![\d.,])\d{1,3}(?:[  ]\d{3})*[.,]\d{1,2}(?![\d.,])")
# Le vocabulaire des en-têtes de colonnes. Un titre dont TOUS les mots porteurs
# viennent d'ici nomme une colonne, jamais l'objet d'une délibération : le
# conseil ne délibère pas sur « DEPENSES D'INVESTISSEMENT ». Les termes qui
# servent aussi de vrais intitulés — budget, compte, exercice, section — n'y
# figurent pas : « BUDGET PRIMITIF 2026 » est une délibération.
_MOTS_DE_COLONNE = {
    "DEPENSES", "DÉPENSES", "DEPENSE", "DÉPENSE", "RECETTES", "RECETTE",
    "CHARGES", "PRODUITS", "MONTANT", "MONTANTS", "TOTAL", "TOTAUX", "CHAP",
    "LIBELLE", "LIBELLÉ", "INTITULE", "INTITULÉ", "FONCTIONNEMENT",
    "INVESTISSEMENT", "REALISE", "RÉALISÉ", "PREVU", "PRÉVU", "SOLDE",
    "CREDIT", "CREDITS", "CRÉDIT", "CRÉDITS",
}
# L'appel nominal d'un vote : « M. BENEFICE : Oui ». Chaque conseiller devenait
# une délibération, avec le reste de la séance pour contenu.
_APPEL_NOMINAL = re.compile(
    r"^(?:MM?|Mme|Mmes|Mlle)\.?\s+[A-ZÀ-Ÿ][\wÀ-ÿ'’\-]*"
    r"(?:\s+[A-ZÀ-Ÿ][\wÀ-ÿ'’\-]*)?\s*:\s*"
    r"(?:oui|non|abstention|pour|contre|ne\s+prend\s+pas\s+part)\b", re.I)


def _titre_plausible(titre: str) -> bool:
    """Un titre de délibération qui porte un montant doit aussi porter des mots.

    Les procès-verbaux contiennent des TABLEAUX de plan de financement, et tous
    les régimes de découpage finissent par couper dedans : chaque ligne du
    tableau devient un « acte ». Le 20/08/2026, la base de Lasalle en comptait
    275, tous publiés, dont un en première page du site :

        « 2 506,51 € TTC (TVA: 20%) »      « CD30 8 800,00 € »
        « FEDER 2021-2027 156 812,54 € 13,0% »

    Aucun n'avait de flux financier extrait : l'information chiffrée était
    perdue ET affichée comme une décision du conseil.

    La règle d'origine ne mordait QUE sur les titres portant un montant à la
    française, et deux mots d'au moins quatre lettres suffisaient à distinguer
    « CHAMP CONTRE CHAMP 3 000,00 € » d'une ligne de tableau. La mesure du
    21/08/2026 sur 389 procès-verbaux de trois communes a montré trois fuites,
    et chacune ajoute ici une ligne :

        « DETR 52 655.52 € 27.62 % »     le point décimal n'était pas reconnu
        « LANUEJOLS ETAGE N° 9 39,60 318.37 190 € »   deux mots, quatre nombres
        « M. BENEFICE : Oui »            l'appel nominal d'un vote
        « DEPENSES D'INVESTISSEMENT »    un en-tête de colonne, 34 774 caractères

    Un intitulé sans chiffre reste intact, si court soit-il — « PLU », « TARIFS »,
    « INCIVILITES » sont de vrais objets de délibération. Les plans de
    financement eux-mêmes relèvent d'un extracteur dédié, pas du découpage.
    """
    titre = titre or ""
    if _APPEL_NOMINAL.match(titre):
        return False
    mots = _MOT_PORTEUR.findall(titre)
    if mots and all(m.upper() in _MOTS_DE_COLONNE for m in mots):
        return False
    if len(_DECIMAL.findall(titre)) >= 2:
        return False
    if not _MONTANT_TITRE.search(titre):
        return True
    return len(mots) >= 2


# Référence du contrôle de légalité, apposée sur tout acte télétransmis par
# @ctes : département, SIREN de la collectivité, DATE DE L'ACTE, numéro, nature.
#     026-200040509-20260625-DE2026116bis-BF
# C'est la seule date de séance qu'un acte porte de façon mécanique, et elle est
# la bonne : sur le portail relevé le 24/08/2026, six délibérations de la séance
# du 25 juin étaient déposées sous « date d'acte » 30/06 et 06/07 — leur date de
# TÉLÉTRANSMISSION. Le SIREN, lui, permet de vérifier que la pièce émane bien de
# la collectivité attendue, et non d'une homonyme.
_REFERENCE_ACTES = re.compile(
    r"\b(\d{3}[A-Z]?)-(\d{9})-(\d{4})(\d{2})(\d{2})-([A-Za-z0-9_./]{1,30})-([A-Z]{2})\b")


def reference_actes(texte: str) -> dict | None:
    """La référence @ctes portée par un acte télétransmis, ou None.

    Rend `{reference, departement, siren, date, numero, nature}`. La date est
    celle de l'acte, donc de la séance qui l'a pris.
    """
    m = _REFERENCE_ACTES.search(texte or "")
    if not m:
        return None
    dep, siren, annee, mois, jour, numero, nature = m.groups()
    return {
        "reference": m.group(0),
        "departement": dep,
        "siren": siren,
        "date": f"{annee}-{mois}-{jour}",
        "numero": numero,
        "nature": nature,
    }


def deliberations(texte: str, pagine: bool = True) -> list[dict]:
    """Découpe un procès-verbal, ou rend [] si aucun régime ne s'applique.

    `pagine` dit si le document a des pages — un PDF en a, une page web n'en a
    pas. Deux régimes s'en servent pour ne pas confondre l'en-tête d'une page
    avec la ligne de colonnes d'un tableau ; cf. `_sans_entetes`.
    """
    for analyseur in (_numerote, _acte_final, _puces, _liste, _capitales):
        sorties = analyseur(texte, pagine)
        if sorties:
            # Filtré ICI et non dans chaque régime : la règle vaut pour tous, et
            # les faux actes venaient aussi bien des PV de la commune que de ceux
            # de l'intercommunalité.
            return _recoller(sorties)
    return []


def acte_unique(titre: str, texte: str, numero_acte: str = "",
                numero_seance: str | None = None) -> dict:
    """Une délibération publiée SEULE, rendue dans la forme des analyseurs.

    Un portail de publicité légale ne dépose pas des séances mais des actes, un
    par fichier, avec leur numéro et leur objet déclarés par la collectivité.
    Il n'y a alors rien à découper, et surtout rien à deviner : le régime
    s'appelle `acte_seul` pour que la base dise d'où vient le découpage — ici,
    d'aucun. L'enrichissement (catégorie, vote, montants) reste le même que
    pour un acte tiré d'un procès-verbal : c'est le même texte de délibération.
    """
    return _enrichir({
        "regime": "acte_seul",
        "numero_seance": numero_seance,
        "numero_acte": numero_acte or "",
        "titre": (re.sub(r"\s+", " ", titre or "").strip(" :;.-") or
                  f"Délibération {numero_acte}".strip())[:255],
        "texte": texte or "",
    })


def _recoller(sorties: list[dict]) -> list[dict]:
    """Écarte les faux titres et REND LEUR TEXTE à l'acte qu'ils coupaient.

    Un titre invraisemblable ne signale pas seulement un acte de trop : il
    signale que le découpage s'est trompé d'endroit, et que les deux blocs n'en
    font qu'un. Les jeter avec leur contenu perdait la matière — le compte rendu
    du 27/04/2026 de Lasalle ouvre un bloc sur la cellule « DEPENSES
    D'INVESTISSEMENT » et lui donne 34 748 caractères, soit les tableaux des huit
    budgets votés ce soir-là. Refuser le titre sans recoller le texte revenait à
    supprimer les huit budgets au lieu de les rattacher à « BUDGET PRINCIPAL ».
    """
    gardees: list[dict] = []
    for d in sorties:
        if _titre_plausible(d.get("titre", "")):
            gardees.append(d)
            continue
        if not gardees:
            continue
        recolle = "\n".join(x for x in (d.get("titre"), d.get("texte")) if x)
        gardees[-1]["texte"] = f"{gardees[-1]['texte']}\n{recolle}".strip()
        _enrichir(gardees[-1])
    return gardees


def _enrichir(d: dict) -> dict:
    d["categorie"], d["tags"] = categorize(d["titre"])
    d["vote"] = extract_vote(d["texte"])
    d["montants"] = extract_amounts(d["texte"])
    return d


def _numerote(texte: str, pagine: bool = True) -> list[dict]:
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


def _acte_final(texte: str, pagine: bool = True) -> list[dict]:
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


def _puces(texte: str, pagine: bool = True) -> list[dict]:
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


def _sans_entetes(texte: str, pagine: bool = True) -> str:
    """Retire les lignes répétées d'un document PAGINÉ : en-tête et pied de page.

    Un procès-verbal de vingt-quatre pages répète son en-tête vingt-quatre
    fois. Le découpeur par capitales en fait autant de titres, et la séance
    ressort avec deux fois plus de délibérations qu'elle n'en a pris.

    Une page web n'a pas de pages, donc pas d'en-tête de page — mais elle a des
    TABLEAUX, dont la ligne de colonnes se répète à chaque tableau. Le compte
    rendu du 27/04/2026 de Lasalle vote huit budgets : « Chap / Art », « Intitulé »
    et « BP 2026 » y reviennent vingt fois chacun, et étaient retirés comme un
    en-tête de page. L'acte perdait sa ligne de colonnes, `budgets_votes` n'y
    trouvait plus une seule ancre, et les huit budgets — dont la Cantine à
    162 724,13 € — n'étaient nulle part. Appliquer à une page web le remède d'un
    PDF, c'est soigner un mal qu'elle n'a pas.
    """
    if not pagine:
        return texte
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


# ── Régime « liste » : une suite d'ordinaux ──────────────────────────────────
#
# Ce régime a longtemps tenu son autorisation d'un EN-TÊTE : « Délibérations : »
# ouvrait la liste, la levée de séance ou la signature la fermait, et chaque
# ligne de l'intervalle devenait un acte. Sa propre note disait : « Découpage
# fiable tant que l'en-tête est là — c'est lui qui l'autorise, pas la mise en
# page. » La mesure du 21/08/2026 sur 389 procès-verbaux de trois communes a
# démenti la prémisse : les 21 documents découpés par ce régime l'étaient TOUS
# à tort, et ils fournissaient 4 337 des 5 529 actes du corpus de Lasalle.
#
# Deux raisons, toutes deux fatales. « Délibération : » AU SINGULIER introduit
# le texte d'UNE délibération à l'intérieur d'un procès-verbal suivi — quatorze
# des seize documents de Lasalle. Et la formule de clôture ne venait jamais :
# les intercommunalités écrivent « La séance se termine à 12h50 ». Les 57 521
# caractères qui restaient après l'en-tête du 02/10/2019 sont donc devenus 497
# « délibérations » d'une ligne : « Vu la saisine du CT », « Risque de
# contentieux », « Thomas Vidal ».
#
# Ce qui prouve une liste, ce n'est pas son en-tête, c'est sa NUMÉROTATION.
# Une suite d'ordinaux qui progresse d'un en un — « 1. », « 01. », « III. »,
# « XVI. » — ne se rencontre pas par hasard, et elle s'arrête d'elle-même :
# aucune formule de clôture n'est nécessaire. Une ligne numérotée isolée ne
# prouve rien ; trois qui se suivent, si. Le régime rejoint ainsi `numerote` et
# `acte_final` : il découpe sur une preuve, non sur un indice.

# Les deux alphabets. Le point ou la parenthèse ferme l'ordinal ; ce qui suit ne
# doit pas être un chiffre, sinon « L. 2224-13 du code général » et « IV. 2024 »
# passeraient pour des titres. « L » est exclu des romains pour la même raison :
# c'est le préfixe des articles du code général des collectivités.
ORDINAL_ARABE = re.compile(r"^(\d{1,2})\s*[.)]\s*(?=[^\W\d_])(\S.*)$")
ORDINAL_ROMAIN = re.compile(r"^([IVX]{1,7})\s*[.)]\s+(?=[^\W\d_])(\S.*)$")
_CHIFFRES_ROMAINS = {"I": 1, "V": 5, "X": 10}
# Trois ordinaux qui se suivent : en deçà, c'est une coïncidence.
MIN_SUITE = 3

FERMETURE_LISTE = re.compile(
    r"(La séance est levée|La séance se termine|Fait et délibéré|Le Maire,|"
    r"La Présidente,|Le Président,)", re.I)
# Le vote clôt la ligne : « … approuvé à l'unanimité », « … à la majorité ».
VOTE_EN_FIN = re.compile(
    r"[,\s]+((?:approuv|adopt|rejet|refus|valid)[eé]{1,2}s?\s+)?"
    r"[àa]\s+(?:l['’]unanimité|la majorité)[^.]*$", re.I)


def _valeur_romaine(chiffres: str) -> int:
    total = 0
    for i, c in enumerate(chiffres):
        v = _CHIFFRES_ROMAINS[c]
        suivant = _CHIFFRES_ROMAINS.get(chiffres[i + 1:i + 2] or "", 0)
        total += -v if suivant > v else v
    return total


def _plus_longue_suite(marques: list[tuple]) -> list[tuple]:
    """La plus longue série d'ordinaux qui progressent d'un en un.

    À longueur égale on garde la DERNIÈRE : l'ordre du jour énumère les mêmes
    intitulés en tête du document, mais c'est la seconde énumération qui porte
    le texte des délibérations. Découper sur l'ordre du jour rendrait des actes
    correctement titrés et vides.
    """
    meilleure: list[tuple] = []
    courante: list[tuple] = []
    for marque in marques:
        if courante and marque[1] == courante[-1][1] + 1:
            courante.append(marque)
            continue
        if len(courante) >= len(meilleure):
            meilleure = courante
        courante = [marque]
    return courante if len(courante) >= len(meilleure) else meilleure


# Une personne, et rien d'autre : « Jean-Claude GUIRAUD », « BOUSQUET Christiane ».
# Les conseils d'installation numérotent leurs conseillers, et le tableau du
# conseil est une suite d'ordinaux irréprochable — mais c'est un trombinoscope,
# pas un ordre du jour. Sur Brassac, une séance rendait ainsi dix-sept « actes »
# nommés d'après les élus présents.
_ITEM_PERSONNE = re.compile(
    r"^(?:[A-ZÀ-Ÿ][a-zà-ÿ'’\-]+(?:[- ][A-ZÀ-Ÿ][a-zà-ÿ'’\-]+)*\s+[A-ZÀ-Ÿ][A-ZÀ-Ÿ'’\-]{2,}"
    r"|[A-ZÀ-Ÿ][A-ZÀ-Ÿ'’\-]{2,}\s+[A-ZÀ-Ÿ][a-zà-ÿ'’\-]+)"
    r"(?:\s+\d[\d/.,\s€%]*)?$")
# Au-delà, deux ordinaux consécutifs ne se touchent plus : du texte les sépare.
_ECART_SERRE = 2
# Un ordre du jour se lit en tête de document. Une énumération serrée qui arrive
# ensuite est interne à une délibération — « 1. Lui donne acte de la présentation
# du compte administratif, 2. Constate les identités de valeurs… » — et la
# prendre pour un ordre du jour émiette une délibération en cinq.
_TETE_DU_DOCUMENT = 0.25


def _est_un_ordre_du_jour(suite: list[tuple], total_lignes: int) -> bool:
    """La suite énumère-t-elle des délibérations, ou autre chose ?"""
    intitules = [t for _, _, t in suite]
    if sum(1 for t in intitules if _ITEM_PERSONNE.match(t.strip())) * 2 >= len(suite):
        return False
    ecarts = [b[0] - a[0] for a, b in zip(suite, suite[1:])]
    serree = bool(ecarts) and sorted(ecarts)[len(ecarts) // 2] <= _ECART_SERRE
    return not serree or suite[0][0] <= total_lignes * _TETE_DU_DOCUMENT


def _liste(texte: str, pagine: bool = True) -> list[dict]:
    """Une suite numérotée de délibérations, le corps de chacune en dessous."""
    lignes = [l.strip() for l
              in _apres_entete(_sans_entetes(texte, pagine)).splitlines() if l.strip()]
    suites = []
    for motif, valeur in ((ORDINAL_ARABE, int), (ORDINAL_ROMAIN, _valeur_romaine)):
        marques = []
        for i, ligne in enumerate(lignes):
            m = motif.match(ligne)
            if m:
                marques.append((i, valeur(m.group(1)), m.group(2)))
        suites.append(_plus_longue_suite(marques))
    suite = max(suites, key=len)
    if len(suite) < MIN_SUITE or not _est_un_ordre_du_jour(suite, len(lignes)):
        return []

    sorties = []
    for rang, (i, _, intitule) in enumerate(suite):
        fin = suite[rang + 1][0] if rang + 1 < len(suite) else len(lignes)
        corps = "\n".join(lignes[i + 1:fin])
        cloture = FERMETURE_LISTE.search(corps)
        if cloture and rang + 1 == len(suite):
            corps = corps[:cloture.start()].strip()
        titre = VOTE_EN_FIN.sub("", re.sub(r"\s+", " ", intitule)).strip(" ,;:.-–—")
        if len(titre) < 8:
            continue
        sorties.append(_enrichir({
            "regime": "liste", "numero_seance": None, "numero_acte": None,
            "titre": titre[:255], "texte": corps or intitule,
        }))
    return sorties


def _capitales(texte: str, pagine: bool = True) -> list[dict]:
    """Dernier recours : les titres sont en capitales, le corps ne l'est pas.

    S'appuie sur le découpeur historique du dispositif, éprouvé sur les procès-
    verbaux de l'instance de référence — le seul des quatre régimes qui ne
    dispose d'aucun identifiant d'acte pour se vérifier. On l'essaie en dernier
    pour cette raison.
    """
    propre = _apres_entete(_sans_entetes(texte, pagine))
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
    r"(?:Monsieur|Madame|M\.|Mme)?\s*([A-ZÀ-Ÿa-zà-ÿ'’\- ]{4,40}?)\s*\(?\s*"
    r"(?:(?:a|ayant)\s+donné\s+procuration|donne\s+pouvoir(?:\s+pour\s+voter"
    r"\s+en\s+son\s+nom)?)\s+(?:à\s+)?(?:Monsieur|Madame|M\.|Mme)?\s*"
    r"([A-ZÀ-Ÿa-zà-ÿ'’\- ]{4,40})", re.I)
REPRESENTATION = re.compile(
    r"([A-ZÀ-Ÿ][A-ZÀ-Ÿ'’\- ]+ [A-ZÀ-Ÿ][a-zà-ÿ\-]+)\s+représenté?e?\s+par\s+"
    r"([A-ZÀ-Ÿ][A-ZÀ-Ÿ'’\- ]+ [A-ZÀ-Ÿ][a-zà-ÿ\-]+)", re.I)

BLOC_PRESENTS = re.compile(
    r"Présents?\s*:(.*?)(?:Représentés?\s*:|Absente?s?\s*:|Pouvoirs?\s|Secrétaire"
    r"|Date de la publi|Ordre du jour|Délibérations)", re.S | re.I)
# Même bloc, mais mis en TABLEAU : la légende occupe une cellule, la liste la
# suivante, et il n'y a donc pas de deux-points. C'est la forme des actes du
# conseil communautaire relevés le 24/08/2026 — « Présents ARMAGNAT Anne ; … » —
# où le motif ci-dessus ne trouvait que le président, tiré de la formule
# d'ouverture : un conseil de trente-deux présents publié avec un seul.
# Sans `re.I`, à dessein : la négation exige que le mot suivant ne soit pas en
# minuscules, ce qui écarte « les conseillers présents ont approuvé ».
BLOC_PRESENTS_TABLEAU = re.compile(
    r"(?:^|\n)[ \t]*Présents?[ \t]+(?![a-zà-ÿ])(.*?)"
    r"(?:Représentés?|Absente?s?|Pouvoirs?\s|Secrétaire|Date de la publi"
    r"|Ordre du jour|Délibérations)", re.S)
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


def _cle_nom(nom: str) -> str:
    """Clé de comparaison d'un nom : capitales, sans accents.

    Le président figure deux fois dans un procès-verbal — « Éric ESCANDE » dans
    la formule d'ouverture, « ESCANDE Eric » dans la liste — et les deux
    graphies ne diffèrent que par un accent. Comparées telles quelles, elles
    faisaient deux présents pour une personne.
    """
    decompose = unicodedata.normalize("NFD", (nom or "").upper())
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn")


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
        # La virgule n'est pas le seul séparateur : les actes du conseil
        # communautaire relevés le 24/08/2026 alignent « ARMAGNAT Anne ;
        # BEAUFORT Jean ; … », et un bloc entier ne rendait qu'un seul nom.
        # Le deux-points y figure aussi, par coquille de saisie
        # (« L'ORPHELIN Samuel : MARCHÉ Damien ») : le traiter en séparateur
        # rend les deux conseillers au lieu du premier.
        # « … ; TRICOTELLE Flore et VERNIER Hugues. » — le dernier de la liste
        # est amené par « et », et se perdait dans le segment du précédent.
        for segment in re.split(r"[;,:]|\bet\b", bloc):
            m = NOM_PRENOM.search(segment.strip())
            if m:
                trouves.append(f"{m.group(2)} {m.group(1)}")

    vus, sortie = set(), []
    for n in trouves:
        if _cle_nom(n) not in vus:
            vus.add(_cle_nom(n))
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

    m = BLOC_PRESENTS.search(tete) or BLOC_PRESENTS_TABLEAU.search(tete)
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
        if president and _cle_nom(president) not in {_cle_nom(n)
                                                     for n in res["presents"]}:
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
