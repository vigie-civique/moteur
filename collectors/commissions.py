"""
commissions.py — Composition des commissions communales, lue dans les PV.

Les commissions décident en amont du conseil : savoir qui siège où est une
information de gouvernance au même titre que les mandats. Elle est publique —
le conseil la vote et le procès-verbal la publie — mais elle n'existe dans
aucun registre national. Sur l'instance d'origine, les 65 services de ce type
avaient été transcrits à la main depuis un PV : exact, et non reproductible.

**Ce que ce collecteur produit, et ce qu'il ne produit pas.**

Il ne publie rien. Une commission mal peuplée est une information fausse sur
qui décide quoi, et le texte dont elle est tirée n'est pas fiable : les PV sont
des PDF dont l'extraction coupe les noms en deux (« René\\nFLOUTIER »,
« Jean-\\nJacques LAVERGNE ») et tronque les fins de liste. Le collecteur dépose
donc, pour arbitrage dans l'atelier :

  - la commission comme `service` en `probable` — le filtre de publication
    l'écarte tant que personne ne l'a promue ;
  - chaque siège dans `relation_candidates`, comme les dirigeants d'association.

Il ne CRÉE aucune personne. Un nom qui ne correspond à aucune personne déjà en
base est consigné dans `audits/commissions_non_resolues.json` : injecter des
patronymes tirés d'une expression régulière serait exactement ce que le reste
du dispositif refuse de faire.

Ces non-résolus ne sont pas du déchet, et le fichier le dit. Deux cas s'y
mêlent : un élu d'une mandature antérieure, que le RNE ne donne pas puisqu'il
ne porte que les mandats en cours ; et un membre NON ÉLU — les commissions
extramunicipales en comptent, et c'est justement ce qu'aucune autre source ne
publie. Le relever a de la valeur. L'inscrire d'office n'en aurait pas.

**Comment il lit.** Trois formes stables d'un PV à l'autre :

    Finances – Budgets                    ← le titre, seul sur sa ligne
    Responsable : Michèle FONTENAY          ← facultatif, parfois « Responsables »
    Membres : Brigitte MARTIN, Philippe BRISSAC, …

Le bloc s'arrête à la première prise de parole qui SUIT une composition — le
débat encadre la liste, il l'ouvre autant qu'il la referme. Les numéros de page
isolés sont ignorés.

Usage :
  python3 -m collectors.commissions --dry-run
  python3 -m collectors.commissions
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import unicodedata
from pathlib import Path

from .config import COMMUNE_NAME, DB_PATH, ROOT
from .db import get_conn, transaction

SIGNAL = "commission_pv"
AUDITS = ROOT / "audits"

# Délibérations qui portent une composition. Le titre suffit à les repérer :
# « COMMISSIONS COMMUNALES », « ACTUALISATION DES MEMBRES DES COMMISSIONS »,
# « MODIFICATION COMPOSITION COMMISSION "COMMUNICATION" ».
TITRE_DELIB = re.compile(
    r"COMMISSIONS?\s+(COMMUNALES?|EXTRA)|COMPOSITION.*COMMISSION|"
    r"MEMBRES?\s+DES\s+COMMISSIONS?", re.I)

RESPONSABLE = re.compile(r"^\s*Responsables?\s*:\s*(.+)$", re.I)
MEMBRES = re.compile(r"^\s*Membres?\s*:\s*(.+)$", re.I)
# Prise de parole : « M. VANTARD : », « Mme MARTIN : ». Fin du bloc.
PAROLE = re.compile(r"^\s*(M\.|Mme|MM\.|Mmes)\s+[A-ZÀ-Ÿ][^:]{0,40}:")
PAGE_SEULE = re.compile(r"^\s*\d{1,3}\s*$")
# Un titre de commission : du texte court, éventuellement suivi d'un deux-points
# (« Environnement : »), mais jamais une phrase. Une ligne qui se termine par un
# point est de la prose de séance — « … seront intégrés au sein des autres
# commissions. » avait été retenue comme titre.
TITRE_PLAUSIBLE = re.compile(r"^[^:]{4,90}:?$")
# Prose de séance : elle se termine par une ponctuation de phrase, commence par
# une puce, ou porte une frontière de phrase en son milieu (« commissions. Les
# membres… »). Ce dernier motif exige un espace après le point, pour ne pas
# rejeter un sigle — « C.C.A.S. » est un titre de commission parfaitement
# valable.
PROSE = re.compile(r"[.!?]\s*$|^\W|\.\s+[A-ZÀ-Ÿ]")

# Précisions entre parenthèses — « (volet agricole) », « (déléguée à l'école) ».
# Elles qualifient le siège, elles ne font pas partie du nom.
PARENTHESE = re.compile(r"\s*\(([^)]*)\)")


def _recoller(texte: str) -> str:
    """Répare les coupures de ligne du PDF à l'intérieur des noms.

    « René\\nFLOUTIER » et « Jean-\\nJacques LAVERGNE » sont un seul nom coupé par
    la mise en colonnes. Sans cette réparation, la moitié des membres se perd :
    le prénom reste sur une ligne, le patronyme sur la suivante.
    """
    texte = re.sub(r"-\s*\n\s*", "-", texte)          # « Jean-\nJacques »
    # Ligne se terminant par un prénom capitalisé et suivante commençant par un
    # patronyme en capitales : les deux appartiennent au même nom.
    return re.sub(r"([A-ZÀ-Ÿ][a-zà-ÿ]+)\s*\n\s*([A-ZÀ-Ÿ]{2,})", r"\1 \2", texte)


def _noms(fragment: str) -> list[tuple[str, str]]:
    """(nom, précision) depuis « A, B (volet X), C - D »."""
    fragment = fragment.replace("–", "-").replace("—", "-")
    out = []
    for brut in re.split(r"\s*[,;]\s*|\s+-\s+", fragment):
        precision = ""
        m = PARENTHESE.search(brut)
        if m:
            precision = m.group(1).strip()
            brut = PARENTHESE.sub("", brut)
        nom = " ".join(brut.split()).strip(" .-")
        # Un nom de membre porte au moins un patronyme en capitales.
        if nom and re.search(r"[A-ZÀ-Ÿ]{2,}", nom):
            out.append((nom, precision))
    return out


def extraire(texte: str) -> list[dict]:
    """Commissions trouvées dans le texte d'une délibération.

    Chaque entrée : {titre, responsables, membres} — les membres portent
    (nom, précision). Le responsable est aussi un membre, avec son rôle.
    """
    lignes = _recoller(texte).splitlines()
    commissions: list[dict] = []
    courante: dict | None = None
    titre_candidat = ""

    for ligne in lignes:
        nu = ligne.strip()
        if not nu or PAGE_SEULE.match(nu):
            continue
        if PAROLE.match(nu):
            # Le débat encadre la liste : il l'OUVRE (« M. X : Nous allons
            # désigner les membres… ») autant qu'il la referme. Casser à la
            # première prise de parole ne rendait donc rien du tout. On ne
            # s'arrête qu'une fois la première composition trouvée.
            if commissions:
                break
            titre_candidat = ""
            continue

        m = RESPONSABLE.match(nu)
        if m:
            if courante is None or courante["membres"] or courante["responsables"]:
                courante = {"titre": titre_candidat, "responsables": [],
                            "membres": []}
                commissions.append(courante)
            courante["responsables"] += [n for n, _ in _noms(m.group(1))]
            continue

        m = MEMBRES.match(nu)
        if m:
            if courante is None or courante["membres"]:
                courante = {"titre": titre_candidat, "responsables": [],
                            "membres": []}
                commissions.append(courante)
            courante["membres"] += _noms(m.group(1))
            continue

        # Ni responsable ni membres : suite d'une liste, ou nouveau titre.
        if courante is not None and courante["membres"] and not TITRE_PLAUSIBLE.match(nu):
            continue
        if courante is not None and courante["membres"] and _noms(nu) and nu[0].isupper() \
                and not re.search(r"[a-zà-ÿ]{6,}", nu):
            courante["membres"] += _noms(nu)         # la liste déborde d'une ligne
            continue
        if PROSE.search(nu) or not TITRE_PLAUSIBLE.match(nu):
            continue
        # Un titre peut déborder sur la ligne suivante : « Cadre de vie […]
        # travaux services » / « techniques ». La suite commence en minuscule,
        # ce qui la distingue d'un nouveau titre — mais une phrase de séance
        # aussi (« commissions. Les membres de cette commission seront… »).
        # Un débordement de titre est COURT et sans ponctuation de phrase.
        if titre_candidat and nu[:1].islower() and len(nu) <= 40 and "." not in nu:
            titre_candidat = f"{titre_candidat} {nu}".strip(" :–-")
        else:
            titre_candidat = nu.strip(" :–-")
        courante = None

    # Une commission sans aucun membre n'est pas une composition.
    return [c for c in commissions
            if c["titre"] and (c["membres"] or c["responsables"])]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^A-Za-z' -]", " ", s).upper().split())


def _index_personnes(conn) -> tuple[dict[str, int], dict[str, int]]:
    """Deux index de personnes DÉJÀ en base : par nom complet, puis par patronyme.

    Le patronyme seul suffit d'ordinaire — les PV désignent les élus par leur
    nom de famille. Mais la base contient aussi tous les dirigeants d'entreprise
    du territoire, et les homonymes y sont fréquents : « DELAUNAY » désigne deux
    personnes distinctes, et refuser de trancher faisait disparaître la
    commission entière faute d'un seul membre résolu. Le PV donnant presque
    toujours le prénom, on essaie d'abord le nom complet.

    Un patronyme ambigu est retiré du second index : on ne devine pas.
    """
    complet: dict[str, int] = {}
    patronyme: dict[str, int] = {}
    ambigus: set[str] = set()
    for eid, prenom, nom in conn.execute(
            "SELECT entity_id, firstname, lastname FROM persons "
            "WHERE lastname IS NOT NULL"):
        cle = _norm(nom)
        if not cle:
            continue
        if prenom:
            complet[f"{_norm(prenom)} {cle}"] = eid
        if cle in patronyme and patronyme[cle] != eid:
            ambigus.add(cle)
        patronyme[cle] = eid
    for cle in ambigus:
        patronyme.pop(cle, None)
    return complet, patronyme


def _resoudre(nom: str, complet: dict[str, int], patronyme: dict[str, int]) -> int | None:
    mots = [m for m in _norm(nom).split() if m not in ("M", "MME", "MM", "MMES")]
    if len(mots) >= 2:
        # « Aurélie DELAUNAY » : prénom + patronyme, quel que soit l'ordre des
        # mots intermédiaires (« Jean-Pierre MERCADIER », « Marie Anne DUPONT »).
        for i in range(len(mots) - 1):
            cle = f"{mots[i]} {mots[-1]}"
            if cle in complet:
                return complet[cle]
    for mot in reversed(mots):                       # à défaut, le patronyme seul
        if len(mot) >= 3 and mot in patronyme:
            return patronyme[mot]
    return None


def run(dry_run: bool = False) -> dict:
    conn = get_conn()
    delibs = [r for r in conn.execute(
        "SELECT id, date, title, content FROM events "
        "WHERE type IN ('deliberation','conseil_municipal') AND content IS NOT NULL "
        "ORDER BY date")
        if TITRE_DELIB.search(r["title"] or "")]
    print(f"[commissions] {len(delibs)} délibération(s) portant une composition")

    complet, patronyme = _index_personnes(conn)
    print(f"[commissions] {len(complet)} noms complets et "
          f"{len(patronyme)} patronymes non ambigus en base")

    trouvees, non_resolus = [], []
    for d in delibs:
        for c in extraire(d["content"]):
            sieges = []
            for nom, precision in c["membres"]:
                eid = _resoudre(nom, complet, patronyme)
                role = "responsable" if nom in c["responsables"] else "membre"
                if eid is None:
                    non_resolus.append({"nom": nom, "commission": c["titre"],
                                        "delib": d["date"], "event_id": d["id"]})
                    continue
                sieges.append({"entity_id": eid, "nom": nom, "role": role,
                               "precision": precision})
            for nom in c["responsables"]:
                if not any(s["nom"] == nom for s in sieges):
                    eid = _resoudre(nom, complet, patronyme)
                    if eid is None:
                        non_resolus.append({"nom": nom, "commission": c["titre"],
                                            "delib": d["date"], "event_id": d["id"]})
                    else:
                        sieges.append({"entity_id": eid, "nom": nom,
                                       "role": "responsable", "precision": ""})
            if sieges:
                trouvees.append({"titre": c["titre"], "date": d["date"],
                                 "event_id": d["id"], "sieges": sieges})

    print(f"[commissions] {len(trouvees)} commission(s), "
          f"{sum(len(c['sieges']) for c in trouvees)} siège(s) résolus, "
          f"{len(non_resolus)} nom(s) non résolus")
    for c in trouvees:
        noms = ", ".join(f"{s['nom']}{'*' if s['role'] == 'responsable' else ''}"
                         for s in c["sieges"])
        print(f"    {c['date']}  {c['titre'][:48]:48} {noms[:70]}")

    if dry_run:
        print("\n(dry-run — rien écrit)")
        conn.close()
        return {"commissions": len(trouvees), "sieges": 0}

    conn.close()
    ecrits = sieges_ecrits = 0
    with transaction() as w:
        for c in trouvees:
            nom_entite = f"Commission {c['titre']} — {COMMUNE_NAME}"
            row = w.execute("SELECT id FROM entities WHERE type='service' AND name=?",
                            (nom_entite,)).fetchone()
            if row:
                cid = row[0]
            else:
                # `probable` : ni le titre ni la composition ne sortent d'un
                # registre. Le filtre de publication les écarte jusqu'à ce que
                # l'atelier les promeuve.
                cid = w.execute(
                    "INSERT INTO entities (type, name, commune, confidence) "
                    "VALUES ('service', ?, ?, 'probable')",
                    (nom_entite, COMMUNE_NAME)).lastrowid
                ecrits += 1
            w.execute("INSERT OR IGNORE INTO event_entities (event_id, entity_id, role) "
                      "VALUES (?,?,'sujet')", (c["event_id"], cid))
            for s in c["sieges"]:
                detail = (f"Délibération du {c['date']} : « {c['titre']} », "
                          f"{s['role']}"
                          + (f" ({s['precision']})" if s["precision"] else ""))
                cur = w.execute(
                    "INSERT OR IGNORE INTO relation_candidates"
                    " (from_id, to_id, relation_type, confidence, signal,"
                    "  signal_detail, score) VALUES (?,?,?,'probable',?,?,?)",
                    (s["entity_id"], cid, "membre_commission", SIGNAL, detail,
                     90 if s["role"] == "responsable" else 80))
                sieges_ecrits += cur.rowcount

    # Regroupé par personne, avec ses commissions : la liste sert à quelqu'un
    # qui arbitre, et une même personne revient dans plusieurs délibérations.
    par_nom: dict[str, dict] = {}
    for n in non_resolus:
        e = par_nom.setdefault(n["nom"], {"nom": n["nom"], "occurrences": 0,
                                          "commissions": []})
        e["occurrences"] += 1
        entree = {"commission": n["commission"], "delib": n["delib"],
                  "event_id": n["event_id"]}
        if entree not in e["commissions"]:
            e["commissions"].append(entree)

    AUDITS.mkdir(parents=True, exist_ok=True)
    (AUDITS / "commissions_non_resolues.json").write_text(json.dumps({
        "note": "Noms lus dans une délibération de composition de commission, "
                "sans personne correspondante en base. Aucune entité n'est "
                "créée automatiquement : à arbitrer dans l'atelier.",
        "deux_cas_distincts": [
            "un élu d'une mandature antérieure, absent de la base parce que le "
            "RNE ne donne que les mandats en cours ;",
            "un membre NON ÉLU — les commissions extramunicipales en comptent, "
            "et c'est précisément ce qu'aucune autre source ne dit. Le relever "
            "a de la valeur ; l'inscrire d'office n'en aurait pas.",
        ],
        "total": len(non_resolus),
        "personnes": sorted(par_nom.values(),
                            key=lambda x: (-x["occurrences"], x["nom"])),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[commissions] {ecrits} commission(s) créée(s) en `probable`, "
          f"{sieges_ecrits} siège(s) en file d'arbitrage")
    print(f"[commissions] {len(non_resolus)} non résolus → "
          f"audits/commissions_non_resolues.json")
    return {"commissions": len(trouvees), "sieges": sieges_ecrits}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--dry-run", action="store_true")
    run(dry_run=ap.parse_args().dry_run)


if __name__ == "__main__":
    main()
