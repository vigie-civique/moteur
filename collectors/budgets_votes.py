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
Un procès-verbal de séance budgétaire contient deux tableaux de forme identique,
souvent à quelques pages d'écart :

    BUDGET PRIMITIF (prévisionnel)     UNE colonne de montants, sous un en-tête
                                       « Chap/art Intitulé BP <année> ».
    COMPTE FINANCIER (réalisé)         DEUX colonnes — prévu, puis réalisé.

Les confondre publierait du prévisionnel comme du constaté, ou l'inverse : une
erreur invisible, puisque les deux tableaux sont vrais. La règle appliquée ici
est mécanique — un total suivi d'un SEUL montant est un budget voté, un total
suivi de deux est un compte financier, et le second est ignoré. L'OFGL publie le
réalisé bien mieux que nous ne saurions le lire.

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

# L'en-tête d'un tableau, en une seule expression : le nom du budget, sa section,
# puis la ligne de colonnes. Les trois doivent se suivre — c'est ce qui distingue
# un en-tête d'une phrase qui parle en passant d'un « virement à la section
# d'investissement ». Entre les deux peuvent s'intercaler la nomenclature (M57)
# et le sens (dépenses / recettes), qui n'apprennent rien de plus.
TABLE = re.compile(
    r"(?P<nom>[a-z0-9.'  -]{0,40}?)\s*"
    r"section\s+(?:de\s+)?(?P<section>fonctionnement|d'\s?investissement)\s*"
    r"(?:[-–:]\s*)?(?:m\s?\d{1,2}\s*)?(?:d[ée]penses|recettes)?\s*(?:[-–:]\s*)?"
    r"chap(?:/art)?\.?\s+intitul[ée]*\s*(?:rar\s*-?\s*pm\s+)?bp\s+(?P<annee>20\d\d)")

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

    « Immédiatement » veut dire : rien entre elles que des espaces. C'est ce qui
    sépare un budget voté d'un compte financier — une colonne contre deux — et
    c'est donc le seul endroit du module où la tolérance serait une erreur.
    """
    valeurs: list[float] = []
    i = depart
    while len(valeurs) < maximum:
        while i < len(texte) and texte[i] in " \t:":
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


def tableaux(titre: str, contenu: str) -> list[dict]:
    """Découpe un acte en tableaux de budget voté.

    Le titre est collé devant le texte : quand le découpage des PV a réussi, la
    section est dans l'intitulé de l'acte (« M57 section de fonctionnement —
    dépenses ») et le corps commence directement par la ligne de colonnes.
    Quand il a échoué, chaque tableau porte son en-tête complet dans le texte.
    Les deux cas se lisent alors de la même façon.
    """
    texte = _norm(titre) + " " + _norm(contenu)
    entetes = list(TABLE.finditer(texte))
    lus: list[dict] = []
    for i, m in enumerate(entetes):
        fin = entetes[i + 1].start() if i + 1 < len(entetes) else len(texte)
        section = "investissement" if m.group("section").startswith("d") else "fonctionnement"
        lus.append({
            "annee": int(m.group("annee")),
            "scope": nom_de_budget(m.group("nom")),
            "section": section,
            "corps": texte[m.end():fin],
        })
    return lus


def agregats_du_tableau(corps: str, section: str) -> list[dict]:
    etiquettes = list(TOTAUX) + list(CHAPITRES)
    if section in SOLDE_PAR_SECTION:
        etiquettes.append((SOLDE, SOLDE_PAR_SECTION[section]))
    trouves: list[dict] = []
    for motif, nom in etiquettes:
        for m in re.finditer(motif, corps):
            valeurs = montants_suivants(corps, m.end())
            # UNE valeur : budget voté. DEUX : prévu puis réalisé, donc un
            # compte financier — ignoré, l'OFGL le publie mieux que nous.
            if len(valeurs) != 1 or not valeurs[0]:
                continue
            trouves.append({"agregat": nom, "value": valeurs[0]})
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
    ecartes = {"budget_indetermine": 0, "tableaux_lus": 0}
    actes = conn.execute(
        "SELECT id, date, title, content, source_url FROM events "
        " WHERE type = 'deliberation' AND content IS NOT NULL AND content <> ''"
        " ORDER BY date").fetchall()
    for acte in actes:
        for tableau in tableaux(acte["title"] or "", acte["content"]):
            agregats = agregats_du_tableau(tableau["corps"], tableau["section"])
            if not agregats:
                continue
            ecartes["tableaux_lus"] += 1
            if not tableau["scope"]:
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
    print(f"[budgets_votes] {ecartes['tableaux_lus']} tableau(x) de budget voté lu(s), "
          f"{ecartes['budget_indetermine']} sans budget identifiable → "
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
