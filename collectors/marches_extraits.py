#!/usr/bin/env python3
"""marches_extraits.py — faire entrer les marchés lus dans les procès-verbaux.

POURQUOI
Les marchés d'une petite commune passent sous les seuils de publicité : ni le
BOAMP ni les données essentielles (DECP) n'en gardent trace, et ils ne se lisent
que dans les procès-verbaux du conseil. Relevé à Lasalle le 04/10/2026 : le
site servait 58 marchés, TOUS de l'intercommunalité, aucun de la commune ;
un outil d'extraction hors dépôt (modèle local, garde par citation) en avait
pourtant lu 180 dans les PV de 2016 à 2026 — 77 pour la commune. Ils dormaient
dans un rapport JSON, faute de chemin pour les faire entrer : depuis que
l'atelier tourne sur un serveur, déposer un fichier dans la base à la main
n'est plus un geste possible.

LE CHEMIN, ET CE QU'IL NE FAIT JAMAIS
    rapport JSON ──déposer()──▶ une PROPOSITION par ligne (en attente)
                                 │ un validateur relit, acte et citation
                                 │ sous les yeux : accepte, corrige, écarte
                                 ▼
                 accepter() ──▶ une saisie `marche` (config/saisies.json)
                                 ──import_saisies()──▶ marches_publics

Extraction n'est pas publication : rien de ce qu'un rapport apporte n'atteint
`marches_publics` avant qu'un compte VALIDATEUR l'ait accepté. Une ligne
acceptée passe par l'écrivain des saisies — pas de second chemin d'écriture, et
le fichier de saisies la rejoue après un `init_instance`, comme tout travail
humain (cf. `collectors/saisies.py`).

Une ligne n'est même pas PROPOSÉE si sa citation ne se retrouve pas,
littéralement, dans le texte de l'acte qu'elle désigne : c'est la preuve qu'on
mettra sous les yeux du validateur, et une preuve introuvable n'en est pas une.

Rejouer le même rapport ne crée aucun doublon : chaque ligne porte une
empreinte (`cle_de`), unique parmi les propositions, quel que soit leur sort.

Le format accepté est décrit dans `docs/format-marches-extraits.md`.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from . import propositions as _propositions
from .citations import compact, montants_cites
from .extraction import CITATION_MIN, _aplatir, citation_presente
from .cle_acte import PREFIXE_PAR_TYPE, TYPES_ACTES, TYPES_SEANCES
from .chemins import sous
from .config import COMMUNE_NAME, COMMUNE_SIREN, COMMUNES_ADRESSE, EPCI_SIREN
from .marches_publics import attribution_acheteur, siren_de

#: L'identifiant du format, que le rapport déclare. Un autre format est refusé
#: entier : mieux vaut un dépôt refusé qu'une colonne lue à contresens.
FORMAT = "vigie-marches-extraits/1"

NATURE = "marche"

#: Où un rapport déposé est archivé, sous son empreinte — par l'atelier comme
#: par la ligne de commande : une ligne proposée dit de quel rapport elle vient,
#: et ce rapport doit exister quel que soit le chemin par lequel il est entré.
RAPPORTS = Path(__file__).resolve().parent.parent / "data" / "extraits" / "marches"

#: Les champs d'une ligne : (obligatoire, genre, ce qu'il dit). Le genre est
#: celui que `_valeur` sait lire. Une clé absente d'ici est ignorée, et le
#: bilan la nomme : l'outil peut porter ses propres colonnes de travail.
CHAMPS = {
    "event_id":       (True,  "entier", "L'acte d'où la ligne est lue (events.id de CETTE base)"),
    "date":           (True,  "date",   "Date de l'acte, AAAA-MM-JJ — vérifiée contre la base"),
    "objet":          (True,  "texte",  "Objet du marché, tel que l'acte le décrit"),
    "citation":       (True,  "texte",  "Passage LITTÉRAL de l'acte qui atteste la ligne"),
    "acheteur_nom":   (True,  "texte",  "L'acheteur, tel que l'acte le nomme"),
    "acheteur_siren": (False, "siren",  "SIREN (ou SIRET) de l'acheteur, s'il est établi"),
    "titulaire":      (False, "texte",  "L'attributaire retenu"),
    "montant":        (False, "montant", "Montant en euros, tel que l'acte le donne"),
    "devise_base":    (False, "choix:HT,TTC", "Le montant est-il hors taxes ou TTC ?"),
    "procedure":      (False, "texte",  "Procédure (adaptée, appel d'offres…)"),
    "nature":         (False, "texte",  "Travaux, fournitures, services…"),
    "type_acte":      (False, "texte",  "Le genre d'acte, tel que l'outil l'a lu"),
    "titre_acte":     (False, "texte",  "Le titre de l'acte, pour le relecteur"),
    "source_url":     (False, "texte",  "L'adresse de la pièce, pour le relecteur"),
    "deja_importe":   (False, "booleen", "Vrai si l'outil sait la ligne déjà en base"),
}

#: Ce qu'un validateur peut corriger en acceptant. Ni l'acte ni la citation :
#: ce sont les preuves, et les corriger reviendrait à accepter autre chose que
#: ce qui a été relu.
CORRIGEABLES = ("objet", "acheteur_nom", "acheteur_siren", "titulaire", "montant",
                "devise_base", "procedure", "nature")

#: La portée d'une ligne, au sens des pages publiques : celle de son ACHETEUR.
#: Un marché de l'intercommunalité n'est pas un marché de la commune, même lu
#: dans le procès-verbal municipal qui en rend compte.
PORTEES = ("commune", "intercommunalite", "autre", "non_etabli")


class LigneRefusee(ValueError):
    """La ligne ne peut pas être proposée ; le message dit pourquoi."""


class RapportRefuse(ValueError):
    """Le rapport entier est illisible ou d'un autre format."""


# ─── Lire une valeur ─────────────────────────────────────────────────────────

def _valeur(champ: str, genre: str, v):
    """Normalise une valeur, ou lève `LigneRefusee`. None : absente."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if genre == "entier":
        if isinstance(v, bool) or not str(v).strip().isdigit():
            raise LigneRefusee(f"{champ} : entier attendu, reçu {v!r}")
        return int(v)
    if genre == "date":
        s = str(v).strip()[:10]
        try:
            datetime.strptime(s, "%Y-%m-%d")
        except ValueError:
            raise LigneRefusee(f"{champ} : date AAAA-MM-JJ attendue, reçu {v!r}")
        return s
    if genre == "montant":
        if isinstance(v, bool):
            raise LigneRefusee(f"{champ} : montant attendu, reçu {v!r}")
        try:
            n = float(str(v).replace(" ", "").replace("\xa0", "").replace(" ", "")
                      .replace(",", "."))
        except ValueError:
            raise LigneRefusee(f"{champ} : montant attendu, reçu {v!r}")
        # `float("nan")` et `float("inf")` se lisent sans erreur : une charge qui
        # porterait un NaN ne se sérialise plus, et la file entière tomberait.
        if not math.isfinite(n):
            raise LigneRefusee(f"{champ} : montant attendu, reçu {v!r}")
        if n < 0:
            raise LigneRefusee(f"{champ} : montant négatif")
        return round(n, 2)
    if genre == "siren":
        s = siren_de(v)
        if not s:
            raise LigneRefusee(f"{champ} : SIREN (9 chiffres) ou SIRET (14) attendu, reçu {v!r}")
        return s
    if genre == "booleen":
        if isinstance(v, bool):
            return v
        raise LigneRefusee(f"{champ} : vrai ou faux attendu, reçu {v!r}")
    if genre.startswith("choix:"):
        s = str(v).strip().upper()
        admis = genre.split(":", 1)[1].split(",")
        if s not in admis:
            raise LigneRefusee(f"{champ} : valeurs admises — {', '.join(admis)}")
        return s
    return " ".join(str(v).split())[:2000]


def lire_ligne(brute) -> tuple[dict, list[str]]:
    """Les champs reconnus d'une ligne, normalisés ; et les clés ignorées."""
    if not isinstance(brute, dict):
        raise LigneRefusee("une ligne doit être un objet JSON")
    propre: dict = {}
    for champ, (obligatoire, genre, _) in CHAMPS.items():
        v = _valeur(champ, genre, brute.get(champ))
        if v is None:
            if obligatoire:
                raise LigneRefusee(f"{champ} : champ obligatoire")
            continue
        propre[champ] = v
    return propre, sorted(set(brute) - set(CHAMPS))


def lignes_du_rapport(rapport) -> list:
    """Les lignes d'un rapport : `{"format": …, "lignes": [...]}`.

    Une liste nue est acceptée aussi — c'est la forme du rapport existant, « une
    ligne par marché » — mais un objet qui déclare un AUTRE format est refusé.
    """
    if isinstance(rapport, list):
        return rapport
    if not isinstance(rapport, dict):
        raise RapportRefuse("le rapport doit être un objet JSON ou une liste de lignes")
    fmt = rapport.get("format")
    if fmt is not None and fmt != FORMAT:
        raise RapportRefuse(f"format « {fmt} » inconnu — attendu « {FORMAT} »")
    lignes = rapport.get("lignes")
    if not isinstance(lignes, list):
        raise RapportRefuse("le rapport n'a pas de liste « lignes »")
    return lignes


# ─── Ce qui fait d'une ligne une proposition ─────────────────────────────────

def cle_de(ligne: dict, acte_cle: str | None = None) -> str:
    """L'empreinte d'une ligne : l'acte, l'objet, le titulaire et le montant.

    Lus sous leur forme compacte : une espace insécable ou une majuscule de plus
    dans un second passage de l'outil ne fait pas un second marché. Un montant
    ou un titulaire DIFFÉRENT, si : c'est une autre lecture, à relire.

    L'acte entre par sa clé datée (`events.cle_acte`) quand il en a une, par son
    identifiant sinon. `events.id` est renouvelé par `redecouper_pv` et les
    purges : une clé qui en dépendait faisait reproposer, après un redécoupage,
    ce qu'un validateur avait déjà écarté (relecture du 05/10/2026).
    """
    montant = ligne.get("montant")
    parts = (f"cle:{acte_cle}" if acte_cle else str(ligne["event_id"]), compact(ligne["objet"]),
             compact(ligne.get("titulaire") or ""),
             "" if montant is None else f"{float(montant):.2f}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:24]


def portee_de(acheteur_siren: str | None, acheteur_nom: str) -> str:
    """La portée d'une ligne, par le SIREN d'abord, par le nom à défaut.

    Le nom ne suffit pas toujours : `attribution_acheteur` refuse de conclure
    sur un nom tronqué que plusieurs collectivités pourraient porter, et la
    ligne est alors `non_etabli` — c'est au validateur de le dire.
    """
    s = siren_de(acheteur_siren)
    if s:
        if COMMUNE_SIREN and s == siren_de(COMMUNE_SIREN):
            return "commune"
        if EPCI_SIREN and s == siren_de(EPCI_SIREN):
            return "intercommunalite"
        return "autre"
    homonymes = tuple(c["nom"] for c in COMMUNES_ADRESSE.values()
                      if c.get("nom") != COMMUNE_NAME)
    return {"commune": "commune", "epci": "intercommunalite"}.get(
        attribution_acheteur(acheteur_nom or "", homonymes=homonymes), "non_etabli")


def acte_de_proposition(conn, proposition: dict) -> dict | None:
    """L'acte d'où la ligne a été lue, sur la base TELLE QU'ELLE EST.

    Par l'identifiant noté au dépôt, s'il désigne encore le même acte (même clé
    datée, quand la ligne en porte une) ; sinon par la clé datée seule, si un
    acte et un seul la porte. Sans cela, une ligne en attente ne pouvait plus
    qu'être écartée après un redécoupage des procès-verbaux.
    """
    cle = (proposition.get("charge") or {}).get("acte_cle")
    acte = _acte(conn, proposition["object_id"])
    if acte and (not cle or acte.get("cle_acte") in (cle, None)):
        return acte
    if cle:
        trouves = conn.execute("SELECT id FROM events WHERE cle_acte=? LIMIT 2",
                               (cle,)).fetchall()
        if len(trouves) == 1:
            return _acte(conn, trouves[0][0])
    return None


def _acte(conn, event_id: int):
    r = conn.execute(
        "SELECT id, type, date, title, content, source_url, raw_document_id, cle_acte "
        "FROM events WHERE id=?", (event_id,)).fetchone()
    if not r:
        return None
    return dict(zip(("id", "type", "date", "title", "content", "source_url",
                     "raw_document_id", "cle_acte"), r))


def retrouver_citation(conn, acte: dict, citation: str) -> str | None:
    """Où la citation se lit LITTÉRALEMENT : 'acte', 'seance', ou None.

    Le texte de l'acte d'abord. À défaut, celui des actes de la même pièce
    (même document archivé, ou même adresse, même date) : un procès-verbal est
    souvent découpé en délibérations, et l'outil a pu lire le passage dans la
    pièce entière. Jamais au-delà — une citation trouvée dans une autre séance
    n'atteste pas cet acte.
    """
    # Le contrôle est celui de l'extraction de l'atelier (`citation_presente`),
    # pas une copie : une ligne que l'atelier juge attestée doit l'être ici.
    if citation_presente(citation, acte.get("content") or ""):
        return "acte"
    if any(citation_presente(citation, t) for t in _voisins(conn, acte)):
        return "seance"
    return None


def _voisins(conn, acte: dict) -> list[str]:
    if acte.get("raw_document_id"):
        rows = conn.execute("SELECT content FROM events WHERE raw_document_id=? AND id<>?",
                            (acte["raw_document_id"], acte["id"])).fetchall()
    elif acte.get("source_url"):
        rows = conn.execute("SELECT content FROM events WHERE source_url=? AND date=? AND id<>?",
                            (acte["source_url"], acte["date"], acte["id"])).fetchall()
    else:
        rows = []
    return [r[0] or "" for r in rows]


def _plat_indexe(texte: str) -> tuple[str, list[int]]:
    """La forme de `extraction._aplatir`, avec pour chaque caractère sa position
    dans le texte d'origine : c'est ce qui permet de surligner le passage que
    `citation_presente` a reconnu, ponctuation et accents compris."""
    chars: list[str] = []
    index: list[int] = []
    blanc = True
    for i, c in enumerate(texte or ""):
        for x in unicodedata.normalize("NFD", c.lower()):
            if unicodedata.category(x) == "Mn":
                continue
            if "a" <= x <= "z" or "0" <= x <= "9":
                chars.append(x)
                index.append(i)
                blanc = False
            elif not blanc:
                chars.append(" ")
                index.append(i)
                blanc = True
    return "".join(chars), index


def extrait(texte: str, citation: str, marge: int = 500) -> dict | None:
    """Le passage cité dans `texte`, avec `marge` caractères de part et d'autre.

    Repéré comme `citation_presente` le repère, et non par une égalité stricte :
    le surlignage échouait sur une virgule ou une apostrophe là où le contrôle
    avait réussi. Découpé ici, et non dans le navigateur : la file renvoyait le
    texte entier de chaque acte, environ 2 Mo pour le rapport de Lasalle.
    """
    plat, index = _plat_indexe(texte)
    cherche = _aplatir(citation)
    pos = plat.find(cherche) if cherche else -1
    if pos < 0:
        return None
    debut, fin = index[pos], index[pos + len(cherche) - 1] + 1
    return {"avant": ("…" if debut > marge else "") + texte[max(0, debut - marge):debut],
            "cite": texte[debut:fin],
            "apres": texte[fin:fin + marge] + ("…" if fin + marge < len(texte) else "")}


def extrait_de(conn, acte: dict, citation: str) -> dict | None:
    """Le passage dans l'acte, ou dans l'acte de la même pièce qui le porte."""
    # 1 500 caractères de part et d'autre : avec 500, le relecteur n'avait pas
    # toujours l'en-tête de la délibération ni son dispositif (07/10/2026).
    for texte in [acte.get("content") or ""] + _voisins(conn, acte):
        e = extrait(texte, citation, marge=1500)
        if e:
            return e
    return None


def doublons(conn, charge: dict, limite: int = 3) -> list[dict]:
    """Les marchés DÉJÀ en base du même acheteur et du même montant (à l'euro).

    L'outil calcule `deja_importe` par acte, pas par marché : sur le rapport de
    Lasalle, les 180 lignes le portaient à faux, et une maîtrise d'œuvre à
    30 000 € recoupait une saisie déjà publiée. Ce n'est pas un refus — deux
    marchés peuvent avoir le même montant — mais le validateur doit le voir.
    L'acheteur se compare par SIREN : c'est la seule clé qui ne dépende pas de
    la graphie.
    """
    siren, montant = siren_de(charge.get("acheteur_siren")), charge.get("montant")
    if not siren or montant is None:
        return []
    rows = conn.execute(
        "SELECT id, source, objet, date_notif, montant, confidence FROM marches_publics "
        "WHERE acheteur_siren=? AND ABS(COALESCE(montant, -1e18) - ?) < 1 "
        "ORDER BY date_notif DESC LIMIT ?", (siren, montant, limite)).fetchall()
    return [dict(zip(("id", "source", "objet", "date_notif", "montant", "confidence"), r))
            for r in rows]


def examiner(conn, ligne: dict) -> dict:
    """La charge d'une proposition, ou `LigneRefusee` avec la raison.

    Ce qui est vérifié ici l'est contre la BASE, pas contre le rapport : l'acte
    existe, il est un acte d'assemblée, sa date est celle que la ligne déclare
    (un rapport produit sur une autre base aurait d'autres identifiants, et
    tomberait sur des actes sans rapport), et la citation s'y lit.
    """
    if len(_aplatir(ligne["citation"])) < CITATION_MIN:
        raise LigneRefusee(f"citation trop courte pour attester quoi que ce soit "
                           f"(moins de {CITATION_MIN} caractères)")
    acte = _acte(conn, ligne["event_id"])
    if acte is None:
        raise LigneRefusee(f"acte {ligne['event_id']} absent de cette base")
    if acte["type"] not in TYPES_ACTES + TYPES_SEANCES:
        raise LigneRefusee(f"l'événement {ligne['event_id']} n'est pas un acte "
                           f"d'assemblée ({acte['type']})")
    if (acte["date"] or "")[:10] != ligne["date"]:
        raise LigneRefusee(f"l'acte {ligne['event_id']} est daté du {acte['date']}, "
                           f"la ligne du {ligne['date']} : le rapport vient-il d'une "
                           f"autre base ?")
    ou = retrouver_citation(conn, acte, ligne["citation"])
    if ou is None:
        raise LigneRefusee("citation introuvable dans le texte de l'acte")

    portee = portee_de(ligne.get("acheteur_siren"), ligne["acheteur_nom"])
    assemblee = "intercommunalite" if PREFIXE_PAR_TYPE.get(acte["type"]) == "cc" else "commune"
    charge = {c: ligne[c] for c in CHAMPS if c in ligne and c not in ("event_id", "deja_importe")}
    charge.update({
        "portee": portee,
        "trouvee_dans": ou,
        # La clé datée de l'acte, pour le retrouver après un redécoupage.
        **({"acte_cle": acte["cle_acte"]} if acte.get("cle_acte") else {}),
        # Deux signaux pour le relecteur, jamais des refus : un montant peut se
        # lire ailleurs dans l'acte, et un procès-verbal municipal peut rendre
        # compte d'un marché communautaire. Mais il doit le voir.
        "montant_dans_citation": (ligne.get("montant") is None or any(
            abs(m - ligne["montant"]) < 0.01 for m in montants_cites(ligne["citation"]))),
        "assemblee_de_l_acte": assemblee,
    })
    return charge


# ─── Déposer ─────────────────────────────────────────────────────────────────

def deposer(conn, rapport, auteur: dict, empreinte_rapport: str = "") -> dict:
    """Une proposition par ligne nouvelle et attestée. N'écrit rien d'autre.

    `auteur` est le compte qui dépose (`id`, `email`) ; il porte les
    propositions. Le bilan dit, ligne par ligne, ce qui n'a pas été proposé et
    pourquoi : un rapport dont 30 lignes disparaissent sans un mot ferait
    croire que l'outil n'en a lu que 150.

    La transaction est celle de l'appelant, qui valide : un rapport à moitié
    déposé laisserait croire à un dépouillement complet.
    """
    _propositions.assurer_schema(conn)
    lignes = lignes_du_rapport(rapport)
    bilan = {"lignes": len(lignes), "proposees": 0, "deja_proposees": 0,
             "deja_importees": 0, "refusees": [], "cles_ignorees": [],
             "par_portee": {}}
    ignorees: set[str] = set()
    for i, brute in enumerate(lignes, start=1):
        try:
            ligne, inconnues = lire_ligne(brute)
            ignorees.update(inconnues)
            if ligne.get("deja_importe"):
                # L'outil sait la ligne déjà en base (BOAMP, DECP) : la proposer
                # ferait publier deux fois le même marché sous deux sources.
                bilan["deja_importees"] += 1
                continue
            charge = examiner(conn, ligne)
        except LigneRefusee as e:
            bilan["refusees"].append({"ligne": i, "motif": str(e)})
            continue
        cle = cle_de(ligne, charge.get("acte_cle"))
        if conn.execute("SELECT 1 FROM propositions WHERE nature=? AND cle=?",
                        (NATURE, cle)).fetchone():
            bilan["deja_proposees"] += 1
            continue
        if empreinte_rapport:
            charge["rapport"] = empreinte_rapport
        _propositions.proposer(conn, NATURE, "deliberation", ligne["event_id"], None,
                               charge, {}, auteur, cle=cle)
        bilan["proposees"] += 1
        bilan["par_portee"][charge["portee"]] = bilan["par_portee"].get(charge["portee"], 0) + 1
    bilan["cles_ignorees"] = sorted(ignorees)
    return bilan


def empreinte(octets: bytes) -> str:
    return hashlib.sha256(octets).hexdigest()


def archiver(octets: bytes, dossier: Path | None = None) -> Path:
    """Garde le rapport tel qu'il a été reçu, sous son empreinte. Le nom n'est
    jamais une valeur reçue, et passe quand même par le garde des chemins."""
    chemin = sous(dossier or RAPPORTS, f"{empreinte(octets)[:16]}.json")
    chemin.parent.mkdir(parents=True, exist_ok=True)
    if not chemin.exists():
        chemin.write_bytes(octets)
    return chemin


def journaliser(conn, auteur: dict, empreinte_rapport: str, bilan: dict) -> None:
    """Le dépôt au journal de l'atelier, quel que soit le chemin d'entrée : la
    ligne de commande ne l'écrivait pas, et un dépôt fait sur le serveur
    n'aurait laissé aucune trace de qui l'avait fait."""
    conn.execute(
        "INSERT INTO audit_log(user_id, entity_id, table_name, action, field, new_value) "
        "VALUES(?,?,?,?,?,?)",
        (auteur["id"], None, "propositions", "deposer_marches_extraits",
         f"rapport/{empreinte_rapport}", json.dumps(
             {k: v for k, v in bilan.items() if k != "refusees"}, ensure_ascii=False)))


# ─── Accepter ────────────────────────────────────────────────────────────────

def corriger(charge: dict, corrections: dict) -> dict:
    """La charge, corrigée par le validateur. Refuse ce qui n'est pas corrigeable."""
    interdits = set(corrections or {}) - set(CORRIGEABLES)
    if interdits:
        raise LigneRefusee(f"non corrigeable : {', '.join(sorted(interdits))} — "
                           f"l'acte et la citation sont la preuve relue")
    sortie = dict(charge)
    for champ, v in (corrections or {}).items():
        obligatoire, genre, _ = CHAMPS[champ]
        propre = _valeur(champ, genre, v)
        if propre is None:
            if obligatoire:
                raise LigneRefusee(f"{champ} : ne peut pas être vidé")
            sortie.pop(champ, None)
        else:
            sortie[champ] = propre
    if "acheteur_nom" in (corrections or {}) or "acheteur_siren" in (corrections or {}):
        sortie["portee"] = portee_de(sortie.get("acheteur_siren"), sortie["acheteur_nom"])
    return sortie


def saisie_de(conn, proposition: dict, corrections: dict, validateur: dict) -> dict:
    """La saisie `marche` qu'écrit une proposition acceptée.

    Son identifiant dérive de la clé de la ligne : deux validateurs qui
    acceptent la même proposition au même instant n'écrivent qu'une saisie.
    La source porte l'acte ET sa pièce archivée, avec l'empreinte de celle-ci —
    sur une autre machine, c'est elle et la clé datée de l'acte qui les
    retrouvent, pas des identifiants de ligne.
    """
    charge = corriger(proposition["charge"], corrections)
    acte = acte_de_proposition(conn, proposition) or {}
    doc = None
    if acte.get("raw_document_id"):
        doc = conn.execute("SELECT id, sha256, url FROM raw_documents WHERE id=?",
                           (acte["raw_document_id"],)).fetchone()
    source = {
        "citation": charge["citation"],
        "event_id": acte.get("id", proposition["object_id"]),
        "acte_cle": acte.get("cle_acte"),
        "acte_date": (acte.get("date") or "")[:10] or None,
        "url": (doc[2] if doc else None) or acte.get("source_url") or charge.get("source_url"),
    }
    if doc:
        source.update(raw_document_id=doc[0], sha256=doc[1])
    valeurs = {
        "objet": charge["objet"],
        "acheteur_nom": charge["acheteur_nom"],
        "titulaire_nom": charge.get("titulaire"),
        "montant": charge.get("montant"),
        # La date que l'acte donne est celle de la DÉCISION d'attribuer ; la
        # notification la suit de quelques jours ou semaines. C'est la seule
        # que le procès-verbal connaît, et c'est elle qui range le marché dans
        # son année — dit au validateur, et dans la note de format.
        "date_notif": charge["date"],
        "procedure": charge.get("procedure"),
        "acheteur_siren": charge.get("acheteur_siren"),
        "nature": charge.get("nature"),
        "montant_base": charge.get("devise_base"),
    }
    return {
        "id": f"pv-{proposition['cle']}",
        "objet": "marche",
        "valeurs": {k: v for k, v in valeurs.items() if v is not None},
        "source": {k: v for k, v in source.items() if v is not None},
        "confidence": "confirmed",
        "saisi_par": validateur["email"],
        "saisi_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "proposition": proposition["id"],
        # Ce que le validateur a changé à la ligne lue : la relecture d'une
        # extraction se vérifie, celle d'une saisie aussi.
        **({"corrige": sorted(corrections)} if corrections else {}),
    }


def releve(conn) -> dict | None:
    """Ce que le snapshot dit des lignes extraites : des NOMBRES, jamais les
    lignes (décision 6 du 04/10/2026, docs/refonte-du-contenu.md).

    None : la base n'a pas la table — rien n'a jamais été déposé, et le site ne
    peut pas distinguer « pas dépouillé » de « pas su ». Le dire est le travail
    de la page.
    """
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                        "AND name='propositions'").fetchone():
        return None
    compte = {"deposees": 0, "en_attente": {p: 0 for p in PORTEES},
              "retenues": 0, "ecartees": 0, "dernier_depot": None}
    for etat, charge, le in conn.execute(
            "SELECT etat, charge, propose_le FROM propositions WHERE nature=?", (NATURE,)):
        compte["deposees"] += 1
        if le and (compte["dernier_depot"] is None or le > compte["dernier_depot"]):
            compte["dernier_depot"] = le
        if etat == "en_attente":
            try:
                portee = json.loads(charge or "{}").get("portee")
            except json.JSONDecodeError:
                portee = None
            portee = portee if portee in PORTEES else "non_etabli"
            compte["en_attente"][portee] += 1
        elif etat == "acceptee":
            compte["retenues"] += 1
        elif etat == "refusee":
            compte["ecartees"] += 1
    compte["en_attente"]["total"] = sum(compte["en_attente"][p] for p in PORTEES)
    compte["dernier_depot"] = (compte["dernier_depot"] or "")[:10] or None
    return compte
