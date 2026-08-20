"""Plans de financement votés — l'argent engagé qui n'est pas un marché.

« Le Conseil Municipal APPROUVE le projet dont le montant s'élève à
16 130,10 € HT soit 19 356,12 € TTC … et demande son inscription au programme. »

Aucune entreprise n'est retenue : la commune vote sa participation à une
opération portée par un syndicat. Ce n'est donc pas un marché attribué — le
publier comme tel fausserait le décompte des attributaires — mais c'est de
l'argent public engagé, et sans ce collecteur il n'apparaît nulle part.

La signature de ces délibérations est le DOUBLE MONTANT HT/TTC d'une opération
sans titulaire : un marché attribué annonce un prix, pas une estimation dans les
deux bases.

Rien d'automatique n'est publié tel quel : ces lignes naissent en `probable` et
attendent l'atelier. Une participation votée n'est pas une dépense constatée, et
la même opération revient souvent dans deux séances.

    python3 -m collectors.approbations            # simulation
    python3 -m collectors.approbations --commit
"""
from __future__ import annotations

import argparse
import re
import unicodedata

from .config import DB_PATH  # noqa: F401  (importé pour cohérence des chemins)
from .db import get_conn, transaction

# Les tournures qui votent une participation, relevées sur les procès-verbaux de
# plusieurs communes. Elles décrivent un ENGAGEMENT, pas une attribution.
APPROBATION = re.compile(
    r"approuve le projet|[ée]tat financier estimatif|"
    r"inscription au programme|avant[- ]projet ci[- ]joint|"
    r"ce projet s['’]\s*[ée]l[èe]ve|"
    r"plan de financement",
    re.I)

# « 16 130,10 € HT soit 19 356,12 € TTC » : les deux montants sont dans la phrase
# votée. Le point comme la virgule sont acceptés — les PV mélangent les deux.
MONTANT = re.compile(r"(\d[\d  ]{2,}(?:[.,]\d{1,2})?)\s*€?\s*(HT|TTC)", re.I)

# Un intitulé de séance ne dit rien de l'opération : on ne s'en sert pas comme
# objet, on garde alors la phrase votée.
TITRE_GENERIQUE = re.compile(
    r"^(PV du CM|CM du|Conseil municipal|Conseil communautaire|"
    r"D[ée]lib[ée]rations? du|Proc[èe]s[- ]verbal|Compte[- ]rendu|S[ée]ance)", re.I)

# Le maître d'ouvrage, quand il est nommé. Volontairement générique : un sigle
# de syndicat commence par S et fait trois à six capitales (SMEG, SIVOM, SIVU,
# SDEE, SMDE…), ou bien le mot est écrit en toutes lettres.
# La branche des SIGLES reste sensible à la casse : sans quoi « sont », « ses »
# ou « suite » deviennent des syndicats. Seul le mot « syndicat » est insensible,
# par un groupe local.
MAITRE_OUVRAGE = re.compile(
    r"\b(S[A-Z]{2,5})\b|\b((?i:syndicat)(?:\s+[\w'’-]+){1,4})", re.UNICODE)
# UN PATRONYME EN CAPITALES A LA MÊME FORME QU'UN SIGLE. « M. SERRE : Le SMEG
# propose… » livrait « SERRE » comme maître d'ouvrage — le nom d'un conseiller,
# dans un champ publié, alors que le vrai syndicat était dans la même phrase.
# Ce qui les distingue est le voisinage : un patronyme suit une civilité.
CIVILITE_AVANT = re.compile(r"(?:M\.|Mme|Mlle|Monsieur|Madame)\s*$")
# Une prise de parole n'est pas un intitulé de délibération.
PRISE_DE_PAROLE = re.compile(r"^(?:M\.|Mme|Mlle|Monsieur|Madame)\s+\S+\s*:", re.I)

# Un plan de financement porte sur une opération, pas sur un trombone : sous ce
# seuil, c'est une ligne de facture mal découpée.
MONTANT_MIN = 500.0
MONTANT_MAX = 20_000_000.0

# En deçà, un titre d'acte ne nomme pas une opération : « Coût des travaux »
# ne dit pas de quels travaux il s'agit.
OBJET_MIN = 25

# Deux séances peuvent voter la même opération. Même montant HT au centime près
# à moins de ~7 mois d'écart : c'est la même.
JOURS_DOUBLON = 200


def _nombre(brut: str) -> float | None:
    v = brut.replace(" ", "").replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        f = float(v)
    except ValueError:
        return None
    return f if MONTANT_MIN <= f <= MONTANT_MAX else None


def _slug(s: str, n: int = 45) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")[:n]


def _phrases(texte: str) -> list[str]:
    """Découpe grossière en phrases. Les PV ponctuent mal : on coupe aussi sur
    les retours à la ligne, sinon une « phrase » fait tout le paragraphe et
    ramasse les montants de l'opération suivante."""
    return [p.strip() for p in re.split(r"(?<=[.;])\s+|\n+", texte or "") if p.strip()]


# Ce qui peut suivre « syndicat » sans être un verbe : un qualificatif, une
# préposition, ou un nom propre. « Le syndicat mixte porte l'opération » doit
# rendre « syndicat mixte », pas « syndicat mixte porte ».
_QUALIFICATIFS = {"mixte", "intercommunal", "intercommunale", "departemental",
                  "departementale", "départemental", "départementale", "communal",
                  "communale"}
_PREPOSITIONS = {"de", "du", "des", "d'", "d’", "la", "le", "les", "l'", "l’"}


def _elaguer_syndicat(brut: str) -> str:
    """Coupe la capture au premier mot qui n'appartient pas au nom."""
    mots = brut.split()
    garde = [mots[0]]
    precedent_preposition = False
    for mot in mots[1:]:
        nu = mot.lower().rstrip(".,;:")
        # « d'électrification » est une préposition contractée collée à son nom :
        # un seul jeton, qui appartient bien au nom du syndicat.
        contractee = nu.startswith(("d'", "d’", "l'", "l’"))
        if (nu in _QUALIFICATIFS or nu in _PREPOSITIONS or contractee
                or mot[:1].isupper() or precedent_preposition):
            garde.append(mot)
            precedent_preposition = nu in _PREPOSITIONS or contractee
        else:
            break
    # Une préposition en fin de nom ne veut rien dire : « syndicat d' ».
    while garde and garde[-1].lower().rstrip(".,;:") in _PREPOSITIONS:
        garde.pop()
    return " ".join(garde)


def _maitre_ouvrage(texte: str) -> str | None:
    """Le premier sigle de syndicat qui ne soit pas un patronyme.

    On parcourt toutes les correspondances au lieu de prendre la première :
    « M. SERRE : Le SMEG propose… » rendait « SERRE » alors que le vrai maître
    d'ouvrage suivait dans la même phrase.
    """
    for m in MAITRE_OUVRAGE.finditer(texte or ""):
        if CIVILITE_AVANT.search(texte[:m.start()]):
            continue
        if m.group(1):
            return m.group(1).strip()
        if m.group(2):
            return _elaguer_syndicat(m.group(2).strip())
    return None


def _explicite(objet: str) -> tuple[bool, int]:
    """Un objet qui NOMME l'opération (« Poste Calviac », « Cap de Ville ») vaut
    mieux qu'un objet plus long mais générique (« travaux d'investissement »)."""
    nom_propre = bool(re.search(r"[«\"]|(?<=\s)[A-ZÉÈÀÎÔ][a-zéèêàîô]{2,}", objet or ""))
    return (nom_propre, len(objet or ""))


def reperer(conn) -> list[dict]:
    """Les plans de financement votés trouvés dans le texte des séances."""
    candidats: list[dict] = []
    for eid, date, titre, contenu, url in conn.execute(
            """SELECT id, date, title, content, source_url FROM events
               WHERE content IS NOT NULL AND content != ''
                 AND type IN ('deliberation','deliberation_cc',
                              'conseil_municipal','conseil_communautaire')"""):
        for phrase in _phrases(contenu):
            if not APPROBATION.search(phrase):
                continue
            montants: dict[str, float] = {}
            for brut, base in MONTANT.findall(phrase):
                v = _nombre(brut)
                if v is not None:
                    montants.setdefault(base.upper(), v)
            if not montants:
                continue
            # L'objet doit permettre de RECONNAÎTRE l'opération. Le titre de
            # l'acte suffit quand il la nomme (« EXTENSION DU RESEAU
            # D'ECLAIRAGE PUBLIC ») ; il ne suffit pas quand il est laconique
            # (« Coût des travaux ») ou générique. Dans ce cas on lui adjoint la
            # phrase votée plutôt que de laisser croire à un objet identifié :
            # ces lignes partent en arbitrage, et l'arbitre a besoin de voir sur
            # quoi il tranche.
            titre_utile = (titre or "").strip()
            if PRISE_DE_PAROLE.match(titre_utile):
                # « M. SERRE : Le SMEG… » est une prise de parole, pas un
                # intitulé — et elle nomme une personne. On ne la reprend pas.
                titre_utile = ""
            if titre_utile and (len(titre_utile) < OBJET_MIN
                                or TITRE_GENERIQUE.match(titre_utile)):
                objet = f"{titre_utile} — {phrase}"
            else:
                objet = titre_utile or phrase
            mo = _maitre_ouvrage(f"{phrase} {titre or ''}")
            candidats.append({
                "event_id": eid, "date": date, "objet": objet[:255],
                "montant_ht": montants.get("HT"), "montant_ttc": montants.get("TTC"),
                "maitre_ouvrage": mo, "citation": phrase[:500],
                "source": f"CR {date}" if date else "CR",
                "source_url": url,
            })
    return candidats


def dedoublonner(candidats: list[dict]) -> tuple[list[dict], list[dict]]:
    """Une même approbation figure dans le PV de séance ET dans la délibération
    dédiée, parfois trois fois. Le montant HT au centime près est la signature la
    plus sûre ; on garde la ligne dont l'objet nomme le mieux l'opération."""
    from datetime import datetime

    candidats = sorted(candidats, key=lambda c: _explicite(c["objet"]), reverse=True)
    retenus, ecartes = [], []
    for c in candidats:
        def _proche(g: dict) -> bool:
            if g["montant_ht"] is None or c["montant_ht"] is None:
                return False
            if g["montant_ht"] != c["montant_ht"]:
                return False
            if not (g["date"] and c["date"]):
                return True
            try:
                ecart = abs((datetime.fromisoformat(c["date"])
                             - datetime.fromisoformat(g["date"])).days)
            except ValueError:
                return True
            return ecart <= JOURS_DOUBLON
        (ecartes if any(_proche(g) for g in retenus) else retenus).append(c)
    retenus.sort(key=lambda c: c["date"] or "")
    return retenus, ecartes


def run(commit: bool = False) -> dict:
    conn = get_conn()
    retenus, ecartes = dedoublonner(reperer(conn))
    print(f"[approbations] {len(retenus) + len(ecartes)} repérée(s) → "
          f"{len(retenus)} retenue(s), {len(ecartes)} doublon(s) d'acte")
    for c in retenus[:10]:
        ht = f"{c['montant_ht']:,.2f} €".replace(",", " ") if c["montant_ht"] else "—"
        print(f"   [{c['date'] or '?'}] {ht:>16} HT  "
              f"{c['maitre_ouvrage'] or '—':<8} {c['objet'][:52]}")
    if not commit:
        print("   simulation — rien n'a été écrit (--commit pour verser)")
        return {"retenus": len(retenus), "ecrits": 0}

    ecrits = 0
    with transaction() as w:
        for c in retenus:
            raw_id = f"APPROB-{c['event_id']}-{_slug(c['objet'])}"
            if w.execute("SELECT 1 FROM approbations_projets WHERE raw_id=?",
                         (raw_id,)).fetchone():
                continue
            # `probable` : une participation votée n'est pas une dépense
            # constatée, et la lecture d'un PV n'est pas un registre. Le filtre
            # de publication l'écarte jusqu'à ce que l'atelier la promeuve.
            w.execute(
                "INSERT INTO approbations_projets (event_id, date, objet, montant_ht,"
                " montant_ttc, maitre_ouvrage, citation, source, source_url, raw_id,"
                " confidence) VALUES (?,?,?,?,?,?,?,?,?,?,'probable')",
                (c["event_id"], c["date"], c["objet"], c["montant_ht"], c["montant_ttc"],
                 c["maitre_ouvrage"], c["citation"], c["source"], c["source_url"], raw_id))
            ecrits += 1
    print(f"   {ecrits} approbation(s) versée(s) en « probable » — à arbitrer dans l'atelier")
    return {"retenus": len(retenus), "ecrits": ecrits}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--commit", action="store_true", help="écrit en base")
    run(commit=ap.parse_args().commit)


if __name__ == "__main__":
    main()
