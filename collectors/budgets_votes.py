#!/usr/bin/env python3
"""budgets_votes.py — le budget primitif VOTÉ, lu dans les procès-verbaux.

POURQUOI CE COLLECTEUR EXISTE
Les agrégats OFGL paraissent environ dix-huit mois après la clôture, le détail
DGFiP plus tard encore. L'exercice en cours et le précédent n'existent donc nulle
part ailleurs que dans la délibération qui les vote : sans ce collecteur, la page
du budget s'arrête à l'avant-dernière année et le lecteur ne voit pas le budget
sur lequel le conseil vient de se prononcer. Sur la première commune portée, ces
chiffres étaient tapés à la main dans un script jetable — dix-huit lignes que
toute recollecte effaçait.

CE QU'IL DISTINGUE, ET C'EST TOUT LE SUJET
Un procès-verbal de séance budgétaire aligne des tableaux de forme identique qui
ne disent pas la même chose : le budget voté, le compte administratif de
l'exercice écoulé, les restes à réaliser. Les confondre publierait du
prévisionnel comme du constaté — une erreur invisible, puisque chaque chiffre
est vrai.

Deux règles suffisent, et elles sont mécaniques :

  1. un tableau de budget voté porte une ligne de colonnes « Chap/art Intitulé …
     BP <année> ». Sans elle, ce n'en est pas un, et il est ignoré ;
  2. la colonne du budget voté est la DERNIÈRE : « Restes à réaliser | BP 2026 »,
     « CA 2025 | BP 2026 », ou « BP 2026 » seule. De chaque ligne on retient donc
     le dernier montant. Si une colonne est déclarée APRÈS elle, la règle ne tient
     plus : le tableau est laissé de côté et compté au rapport.

Le compte financier, lui, est laissé à l'OFGL, qui le publie bien mieux que nous
ne saurions le lire.

LE DÉCOUPAGE DES PV NE SE FAIT PAS TOUJOURS, ET CE MODULE N'EN DÉPEND PAS
Sur la première commune, la séance budgétaire de 2025 forme un seul « acte » de
30 000 caractères — intitulé, par accident du découpage, « Coût à la charge du
propriétaire de la parcelle AC 511 » — qui contient huit budgets : le principal
et sept annexes. Se fier au titre de l'acte y attribuerait au budget communal les
chiffres d'une régie. Ce sont donc les TABLEAUX qui sont repérés, pas les actes :
chacun porte son propre en-tête « <nom> section de fonctionnement … BP <année> »,
et c'est lui qui nomme le budget, la section et l'exercice.

CE QU'IL NE DEVINE PAS
  - un tableau sans en-tête de colonne « BP <année> » n'est pas un budget voté :
    il est ignoré, plutôt que daté au jugé ;
  - un en-tête dont le nom de budget ne se laisse pas lire est compté au rapport
    et jamais versé sous un périmètre supposé ;
  - les délibérations intercommunales sont écartées : le budget de l'EPCI n'est
    pas celui de la commune, et le verser dans la même table le ferait s'afficher
    comme tel.

Rien n'est écrit sans `--commit`, et une ligne corrigée dans l'atelier n'est
jamais réécrite.

    python3 -m collectors.budgets_votes            # simulation
    python3 -m collectors.budgets_votes --commit
"""
from __future__ import annotations

import argparse
import re
import unicodedata

from .db import get_conn, transaction

# ── Reconnaître un tableau de budget voté ────────────────────────────────────
# Les intitulés viennent de la nomenclature comptable nationale (M14, M57) :
# identiques dans toutes les communes de France, c'est ce qui rend ce collecteur
# générique. Ils sont écrits ici sans accent ni majuscule — le texte est normalisé
# avant toute recherche.

# « 2 270 783.59 », « 202 819.27 », « 1 035 000.00 ». Les PDF mêlent espace
# ordinaire, insécable et fine ; la virgule et le point servent tous deux de
# séparateur décimal. Les groupes de TROIS chiffres sont exigés : sans cela,
# « 177 717.01 175 149.78 » se lirait comme un seul nombre, et les deux colonnes
# d'un compte financier passeraient pour la colonne unique d'un budget voté.
MONTANT = r"-?\s?\d{1,3}(?:[   ]\d{3})*(?:[.,]\d{1,2})?"
_MONTANT_RX = re.compile(MONTANT)

# L'ANCRE : la ligne de colonnes d'un tableau budgétaire. « Chap/art Intitulé …
# BP <année> » se retrouve telle quelle dans un PDF de tableur comme dans une
# page HTML, et c'est le seul endroit du document qui affirme deux choses à la
# fois — ceci est un tableau, et il porte le budget primitif de cet exercice.
# Une phrase qui parle en passant d'un « virement à la section d'investissement »
# ne la produit jamais.
ENTETE = re.compile(
    r"chap(?:\s*[/.]\s*art)?\.?\s*[\s|]*intitul[ée]*\b(?P<colonnes>[\s\S]{0,60}?)"
    r"bp\s+(?P<annee>20\d\d)")

# Ce qui précède l'ancre nomme la section, et parfois le budget :
#     « principal section de fonctionnement m57 dépenses »   (PDF de tableur)
#     « dépenses d'investissement »                          (page HTML)
# Le nom, lui, n'est présent que dans la première forme — la seconde le laisse
# dans le récit de la séance, d'où il ne se déduit pas sans deviner.
SECTION_AVANT = re.compile(r"(?P<mot>fonctionnement|investissement)(?![a-z])")
NOM_AVANT = re.compile(
    r"(?P<nom>[a-z0-9.'  -]{0,40}?)\s*section\s+(?:de\s+)?"
    r"(?:fonctionnement|d'\s?investissement)")
# Fenêtre de lecture à rebours depuis l'ancre. Assez large pour couvrir un
# en-tête complet, assez étroite pour ne pas mordre sur le tableau précédent.
FENETRE_AVANT = 200

# Fenêtre plus courte pour la section : elle est dans l'en-tête, pas dans le
# récit. « … un virement à la section d'investissement de 50 500 € » se trouve à
# deux lignes de là, et donnerait la section d'à côté.
FENETRE_SECTION = 60

# Les colonnes qui peuvent suivre « BP <année> » dans un en-tête, et qui font
# renoncer au tableau : le compte administratif du même exercice, le réalisé,
# les restes à réaliser. Un tableau de compte financier en porte toujours au
# moins une — c'est ce qui le distingue d'un budget voté.
COLONNE_APRES_BP = re.compile(
    r"\bca\s*20\d\d\b|compte\s+administratif|realis|\brar\b|mandat")

# Les totaux nomment leur section : aucune ambiguïté à lever.
TOTAUX = (
    (r"total\s+des\s+recettes\s+fonct\w*\.?\s*(?:exercice)?", "Recettes de fonctionnement"),
    (r"total\s+des\s+depenses\s+fonct\w*\.?\s*(?:exercice)?", "Dépenses de fonctionnement"),
    (r"total\s+des\s+recettes\s+d[' ]?\s*invest\w*\.?\s*(?:exercice)?", "Recettes d'investissement"),
    (r"total\s+des\s+depenses\s+d[' ]?\s*invest\w*\.?\s*(?:exercice)?", "Dépenses d'investissement"),
)

# Deux chapitres seulement : les plus lourds, et les seuls dont l'intitulé est
# stable d'une commune à l'autre. Le reste du tableau se lit dans le PV, dont le
# lien accompagne chaque ligne versée.
CHAPITRES = (
    (r"\.?\s*012\s+charges\s+de\s+personnel[^\d]{0,40}", "Charges de personnel"),
    (r"\.?\s*011\s+charges\s+a\s+caractere\s+general[^\d]{0,40}", "Charges à caractère général"),
)

# Le solde ne nomme pas sa section : c'est le tableau qui la porte. Sans elle,
# deux tableaux de la même séance écriraient deux valeurs sous la même clé.
SOLDE = r"solde\s+d[' ]?\s*execution"
SOLDE_PAR_SECTION = {
    "fonctionnement": "Excédent net de fonctionnement",
    "investissement": "Solde d'exécution d'investissement",
}

# Un nom de budget se lit à rebours depuis « section », et s'arrête à ces mots :
# ils appartiennent à la phrase qui précède, pas au nom.
COUPURE = {"pv", "detail", "par", "chapitre", "chapitres", "ainsi", "etablit",
           "qui", "du", "de", "des", "la", "le", "les", "et", "en", "au", "aux",
           "budget", "budgets", "annexe", "annexes", "suit", "suivant", "vote",
           "votes", "adopte", "presente", "propose", "s'etablit"}
# « M57 », « M14 », « M4 » : une nomenclature, pas un budget annexe. Le tableau
# qu'elle coiffe est celui du budget principal.
NOMENCLATURE = re.compile(r"^m\s?\d{1,2}$")
PRINCIPAL = "principal"


def _norm(texte: str | None) -> str:
    """Minuscules sans accents, apostrophes uniformisées.

    Les procès-verbaux sont océrisés ou copiés d'un tableur : « DÉPENSES »,
    « Dépenses » et « DEPENSES » désignent la même ligne, et l'apostrophe
    typographique alterne avec la droite dans le même document.
    """
    if not texte:
        return ""
    t = unicodedata.normalize("NFD", texte)
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return t.replace("’", "'").replace("‘", "'").lower()


def _nombre(brut: str) -> float | None:
    net = re.sub(r"[\s   ]", "", brut).replace(",", ".")
    try:
        return float(net)
    except ValueError:
        return None


def _est_une_somme(brut: str, valeur: float) -> bool:
    """Un montant, ou le numéro de chapitre de la ligne suivante ?

    « .012 Charges de personnel 1 035 000.00 65 Autres charges… » : le 65 qui
    suit le montant n'est pas une seconde colonne, c'est le chapitre d'après. Le
    prendre pour une colonne ferait passer ce budget voté pour un compte
    financier, et la ligne disparaîtrait sans un mot.

    Ce qui les sépare : une somme de budget porte ses centimes, ou dépasse le
    millier. Les numéros de la nomenclature (011, 012, 021, 65, 66, 70, 73, 204)
    ne font ni l'un ni l'autre. Une colonne « réalisé » sous mille euros et sans
    décimales échapperait donc au contrôle — les états comptables les écrivent
    avec leurs centimes, ce cas ne s'est pas présenté.
    """
    return bool(re.search(r"[.,]\d{1,2}$", brut)) or abs(valeur) >= 1000


def montants_suivants(texte: str, depart: int, maximum: int = 3) -> list[float]:
    """Les sommes qui suivent IMMÉDIATEMENT une étiquette.

    « Immédiatement » veut dire : rien entre elles que des blancs. Les sauts de
    ligne en sont : une page HTML met chaque cellule sur sa ligne, un PDF de
    tableur les aligne sur une seule, et le tableau est le même. Ce qui arrête
    la lecture, c'est un MOT — l'étiquette de la ligne suivante.
    """
    valeurs: list[float] = []
    i = depart
    while len(valeurs) < maximum:
        while i < len(texte) and texte[i] in " \t\n\r|:":
            i += 1
        m = _MONTANT_RX.match(texte, i)
        if not m:
            break
        v = _nombre(m.group(0))
        if v is None or not _est_une_somme(m.group(0), v):
            break
        valeurs.append(v)
        i = m.end()
    return valeurs


def nom_de_budget(brut: str) -> str | None:
    """« principal », le nom d'un budget annexe, ou rien.

    Le nom précède « section » dans l'en-tête, mais la phrase d'avant aussi :
    « … le budget 2025 du parc locatif, qui s'établit ainsi : parc locatif
    section de fonctionnement … ». On remonte donc mot à mot depuis la fin, et on
    s'arrête au premier mot qui appartient visiblement à la phrase.

    Rien, c'est-à-dire : ce tableau ne dit pas de quel budget il parle. On ne
    suppose pas « principal » par défaut — ce serait attribuer au budget de la
    commune les chiffres d'une régie.
    """
    mots: list[str] = []
    for mot in reversed(re.findall(r"[a-z0-9'.-]+", brut)):
        mot = mot.strip(".'-:")
        if not mot or mot in COUPURE or re.fullmatch(r"[\d.'-]+", mot):
            break
        mots.append(mot)
        if len(mots) == 3:
            break
    if not mots:
        return None
    nom = " ".join(reversed(mots))
    if nom == PRINCIPAL or NOMENCLATURE.match(nom):
        return PRINCIPAL
    return nom


def _avant(texte: str, position: int, fenetre: int = FENETRE_AVANT) -> str:
    return texte[max(0, position - fenetre):position]


def colonne_apres_bp(suite: str) -> bool:
    """Une colonne est-elle déclarée APRÈS « BP <année> » ?

    Si oui, le budget voté n'est plus la dernière colonne du tableau, et plus
    rien ne dit lequel des montants d'une ligne est le sien.

    Ce sont les INTITULÉS de colonnes qui sont cherchés, et non la fin de la
    ligne d'en-tête : celle-ci ne se laisse pas borner. « BP 2025 CA 2025 Restes
    à réaliser » commence par une année, « BP 2026 11 0.023 Virement… » par un
    numéro de page suivi d'un chapitre. La liste est courte parce que ces
    intitulés viennent de la comptabilité publique, pas de la commune.
    """
    return bool(COLONNE_APRES_BP.search(suite))



def tableaux(titre: str, contenu: str) -> list[dict]:
    """Découpe un acte en tableaux de budget voté.

    Le titre est collé devant le texte : quand le découpage des procès-verbaux a
    réussi, la section est dans l'intitulé de l'acte (« M57 section de
    fonctionnement — dépenses ») et le corps commence par la ligne de colonnes.
    Quand il a échoué — une séance entière dans un seul acte — chaque tableau
    porte son en-tête dans le texte. Les deux cas se lisent de la même façon.
    """
    texte = _norm(titre) + " " + _norm(contenu)
    ancres = list(ENTETE.finditer(texte))
    lus: list[dict] = []
    for i, m in enumerate(ancres):
        fin = ancres[i + 1].start() if i + 1 < len(ancres) else len(texte)
        avant = _avant(texte, m.start())
        noms = NOM_AVANT.findall(avant)
        sections = SECTION_AVANT.findall(_avant(texte, m.start(), FENETRE_SECTION))
        scope = nom_de_budget(noms[-1]) if noms else None
        section = sections[-1] if sections else None
        # UN BUDGET, DEUX TABLEAUX. Le document nomme le premier — « chaufferie
        # bois section de fonctionnement / dépenses » — et coiffe le second d'un
        # simple « recettes ». Le tableau sans nom n'est pas d'un budget inconnu :
        # c'est la suite du précédent, et l'attribuer à autre chose serait faux.
        # L'héritage s'arrête au tableau suivant qui se nomme.
        if lus and lus[-1]["annee"] == int(m.group("annee")):
            scope = scope or lus[-1]["scope"]
            section = section or lus[-1]["section"]
        lus.append({
            "annee": int(m.group("annee")),
            "scope": scope,
            "section": section,
            "corps": texte[m.end():fin],
            "colonne_sure": not colonne_apres_bp(texte[m.end():m.end() + 45]),
        })
    return lus


def agregats_du_tableau(corps: str, section: str | None) -> list[dict]:
    """Les agrégats d'un tableau : pour chaque étiquette, la valeur de sa ligne.

    La valeur retenue est la DERNIÈRE de la ligne, parce que la colonne du
    budget voté est la dernière du tableau. Les colonnes qui la précèdent — les
    restes à réaliser, le compte administratif de l'exercice écoulé — sont ainsi
    lues et écartées d'un même mouvement, au lieu de faire renoncer au tableau
    entier comme le faisait la première version de ce module.
    """
    etiquettes = list(TOTAUX) + list(CHAPITRES)
    if section in SOLDE_PAR_SECTION:
        etiquettes.append((SOLDE, SOLDE_PAR_SECTION[section]))
    trouves: list[dict] = []
    for motif, nom in etiquettes:
        for m in re.finditer(motif, corps):
            valeurs = montants_suivants(corps, m.end())
            if not valeurs or not valeurs[-1]:
                continue
            trouves.append({"agregat": nom, "value": valeurs[-1]})
            break
    return trouves


def reperer(conn) -> tuple[list[dict], dict]:
    """Parcourt les délibérations de la commune et en tire les lignes de budget.

    L'ordre est chronologique CROISSANT, et il compte : une décision
    modificative revote une partie du budget primitif, et c'est le vote le plus
    récent qui doit rester en base. En ordre décroissant, l'écriture la plus
    ancienne serait la dernière à passer, donc la seule à subsister.
    """
    lignes: list[dict] = []
    ecartes = {"tableaux": 0, "budget_indetermine": 0, "colonne_incertaine": 0}
    actes = conn.execute(
        "SELECT id, date, title, content, source_url FROM events "
        " WHERE type = 'deliberation' AND content IS NOT NULL AND content <> ''"
        " ORDER BY date").fetchall()
    for acte in actes:
        for tableau in tableaux(acte["title"] or "", acte["content"]):
            ecartes["tableaux"] += 1
            if not tableau["colonne_sure"]:
                ecartes["colonne_incertaine"] += 1
                continue
            agregats = agregats_du_tableau(tableau["corps"], tableau["section"])
            if not agregats:
                continue
            if not tableau["scope"]:
                # Le tableau se lit, mais rien n'y dit de quel budget il est :
                # dans un compte rendu HTML, le nom reste dans le récit de la
                # séance. Compté ici, et laissé à la saisie de l'atelier.
                ecartes["budget_indetermine"] += 1
                continue
            for a in agregats:
                lignes.append({
                    "year": tableau["annee"],
                    "scope": tableau["scope"],
                    "agregat": a["agregat"],
                    "value": a["value"],
                    "source": f"PV du conseil du {acte['date']} (budget primitif voté)",
                    "source_event_id": acte["id"],
                    "source_url": acte["source_url"],
                })
    return lignes, ecartes


def run(commit: bool = False) -> dict:
    conn = get_conn()
    lignes, ecartes = reperer(conn)
    exercices = sorted({l["year"] for l in lignes})
    budgets = sorted({l["scope"] for l in lignes})
    print(f"[budgets_votes] {ecartes['tableaux']} tableau(x) repéré(s), "
          f"{ecartes['budget_indetermine']} sans budget identifiable, "
          f"{ecartes['colonne_incertaine']} à colonnes ambiguës → "
          f"{len(lignes)} ligne(s)")
    print(f"   exercices : {', '.join(str(a) for a in exercices) or '—'}")
    print(f"   budgets   : {', '.join(budgets) or '—'}")
    for l in lignes[:15]:
        montant = f"{l['value']:,.2f}".replace(",", " ")
        print(f"   {l['year']} {l['scope']:<16} {l['agregat']:<38} {montant:>16} €")
    if len(lignes) > 15:
        print(f"   … {len(lignes) - 15} autre(s)")
    if not commit:
        print("   simulation — rien n'a été écrit (--commit pour verser)")
        return {"reperes": len(lignes), "ecrits": 0}

    ecrits = 0
    with transaction() as w:
        for l in lignes:
            # Une ligne corrigée dans l'atelier porte la marque de l'atelier :
            # une relecture automatique n'a pas à défaire un arbitrage humain.
            cur = w.execute(
                "INSERT INTO budget_vote (year, scope, agregat, value, unit, approx,"
                " source, source_event_id, source_url)"
                " VALUES (?,?,?,?,'EUR',0,?,?,?)"
                " ON CONFLICT(year, scope, agregat) DO UPDATE SET"
                "   value = excluded.value,"
                "   source = excluded.source,"
                "   source_event_id = excluded.source_event_id,"
                "   source_url = excluded.source_url"
                " WHERE budget_vote.source IS NULL"
                "    OR budget_vote.source NOT LIKE 'atelier%'",
                (l["year"], l["scope"], l["agregat"], l["value"],
                 l["source"], l["source_event_id"], l["source_url"]))
            ecrits += cur.rowcount or 0
    print(f"   {ecrits} ligne(s) versée(s) dans budget_vote")
    return {"reperes": len(lignes), "ecrits": ecrits}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--commit", action="store_true",
                    help="écrit en base (sans lui, simulation)")
    args = ap.parse_args()
    run(commit=args.commit)


if __name__ == "__main__":
    main()
