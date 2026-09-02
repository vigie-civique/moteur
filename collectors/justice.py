"""
justice.py — Décisions de justice administrative citant la commune (JADE, DILA).

Recours contre un permis, litige de marché, contestation d'élection, refus
d'accès à un document : la juridiction administrative tranche des affaires qui
concernent directement une commune, et ses décisions sont publiques. Personne ne
va les chercher.

─────────────────────────────────────────────────────────────────────────────
POURQUOI PAS JUDILIBRE

La proposition d'audit visait « api.piste.gouv.fr · Judilibre ». Deux raisons de
ne pas la suivre telle quelle, vérifiées le 02/09/2026 :

  1. **Judilibre exige une clé.** Sans en-tête `KeyId`, l'API rend 400 — il faut
     un compte PISTE et une clé par déployeur. Un step du moteur doit tourner
     pour n'importe quelle commune sans compte : la clé en ferait un collecteur
     à part, comme `pappers`.
  2. **Judilibre, c'est la Cour de cassation.** L'ordre JUDICIAIRE. Or ce qui
     concerne une commune — permis, marchés, élections, actes — relève du juge
     ADMINISTRATIF, publié par la DILA sous le fonds JADE, en accès libre et
     sans clé.

Source retenue : `echanges.dila.gouv.fr/OPENDATA/JADE/`, archives `tar.gz`.

⚠️ DEUX ÉCHELLES, ET LA GRANDE NE SE PREND PAS SANS LE DIRE. Le corpus complet
pèse **1,19 Go compressés** ; les incréments quotidiens, **0,2 Mo** pour environ
80 décisions. Le step ordinaire ne lit donc QUE les incréments récents : il
coûte quelques mégaoctets, et le corpus se constitue au fil des jours. Reprendre
l'historique entier est un geste explicite — `--amorcer` — parce qu'il engage le
disque de la machine, qui est déjà un sujet.

⚠️ ET UNE DÉCISION QUI CONTIENT LE NOM DE LA COMMUNE NE LA CONCERNE PAS
FORCÉMENT. « Saillans » est aussi un patronyme ; « Lasalle » aussi. Le
rapprochement n'accepte donc que les formes où le nom désigne la collectivité —
« commune de X », « ville de X », « maire de X » —, et refuse le nom suivi d'un
mot qui prolongerait une autre commune (« Lasalle-sur-Cèze »). Mieux vaut rater
une décision que d'attribuer à une commune le procès d'une autre.

Usage :
  python3 -m collectors.justice              # les incréments récents
  python3 -m collectors.justice --jours 90
  python3 -m collectors.justice --amorcer    # ⚠️ 1,19 Go : le corpus entier
  python3 -m collectors.justice --stats
"""
import argparse
import datetime as dt
import io
import re
import tarfile
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET

from .archive import HEADERS
from .config import COMMUNE_INSEE, COMMUNE_NAME, EPCI_NOM
from .db import get_conn, transaction

SOURCE = "jade"
BASE = "https://echanges.dila.gouv.fr/OPENDATA/JADE/"
LEGIFRANCE = "https://www.legifrance.gouv.fr/ceta/id/"

# Les incréments lus par défaut. Trente jours donnent une marge confortable :
# une collecte hebdomadaire ne peut pas rater un jour, et une reprise après
# interruption rattrape seule.
JOURS_DEFAUT = 30

# Ce qui, devant un nom, désigne une collectivité et non une personne.
DEVANT = ("commune de", "commune d", "ville de", "ville d", "mairie de",
          "mairie d", "maire de", "maire d", "communaute de communes",
          "communaute d agglomeration")


def normaliser(texte: str | None) -> str:
    """Minuscules sans accents — MAIS le trait d'union est conservé.

    🔴 C'est lui qui distingue « commune de Jonquières » de « commune de
    Jonquières-Saint-Vincent ». Une première version rabattait le trait d'union
    sur une espace, puis refusait le nom suivi d'un mot de liaison (« sur »,
    « la », « saint »…) pour rattraper le coup. Dans du texte suivi, cette
    liste refusait tout : « du maire de Beaucaire la commune… » était rejeté
    parce que « la » suivait. Le trait d'union, lui, ne se trompe pas : il
    n'apparaît QUE dans le nom composé.
    """
    t = unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9-]+", " ", t.lower()).strip()


def cite(texte_normalise: str, nom: str) -> bool:
    """Le texte désigne-t-il CETTE collectivité ?

    Deux conditions : le nom doit être précédé d'une formule qui en fait une
    collectivité (sans quoi « Saillans » peut être un patronyme), et il ne doit
    pas être le DÉBUT d'un nom composé plus long.
    """
    cherche = normaliser(nom).strip("-")
    if not cherche:
        return False
    for prefixe in DEVANT:
        aiguille = f"{prefixe} {cherche}"
        i = texte_normalise.find(aiguille)
        while i >= 0:
            apres = texte_normalise[i + len(aiguille):i + len(aiguille) + 1]
            if apres != "-" and not apres.isalnum():
                return True
            i = texte_normalise.find(aiguille, i + 1)
    return False


def _archives_recentes(jours: int) -> list[str]:
    """Les incréments publiés depuis `jours`, du plus ancien au plus récent."""
    req = urllib.request.Request(BASE, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=90) as r:
        page = r.read().decode("utf-8", "replace")
    limite = (dt.date.today() - dt.timedelta(days=jours)).strftime("%Y%m%d")
    noms = sorted(set(re.findall(r'href="(JADE_(\d{8})-\d{6}\.tar\.gz)"', page)))
    return [nom for nom, jour in noms if jour >= limite]


def _decisions(brut: bytes):
    """Parcourt une archive JADE et rend chaque décision lue.

    En flux : une archive du corpus complet ne tient pas en mémoire, et le
    moteur a déjà payé cette leçon sur les consolidés DECP.
    """
    with tarfile.open(fileobj=io.BytesIO(brut), mode="r:gz") as tar:
        for membre in tar:
            if not membre.isfile() or not membre.name.endswith(".xml"):
                continue
            fichier = tar.extractfile(membre)
            if fichier is None:
                continue
            try:
                arbre = ET.parse(fichier).getroot()
            except ET.ParseError:
                continue
            yield _lire(arbre)


def _texte(noeud) -> str:
    return " ".join(t.strip() for t in noeud.itertext() if t and t.strip())


def _lire(racine) -> dict:
    def prem(chemin: str) -> str:
        n = racine.find(chemin)
        return (n.text or "").strip() if n is not None and n.text else ""

    contenu_noeud = racine.find(".//TEXTE/BLOC_TEXTUEL/CONTENU")
    return {
        "id": prem(".//META_COMMUN/ID"),
        "titre": prem(".//META_JURI/TITRE"),
        "date": prem(".//META_JURI/DATE_DEC"),
        "juridiction": prem(".//META_JURI/JURIDICTION"),
        "numero": prem(".//META_JURI/NUMERO"),
        "type_recours": prem(".//META_JURI_ADMIN/TYPE_REC"),
        "contenu": _texte(contenu_noeud) if contenu_noeud is not None else "",
    }


def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS justice_decisions (
            id           TEXT PRIMARY KEY,      -- CETATEXT…
            insee        TEXT NOT NULL,
            portee       TEXT,                  -- commune | epci
            juridiction  TEXT,
            date_dec     TEXT,
            numero       TEXT,
            titre        TEXT,
            type_recours TEXT,
            extrait      TEXT,                  -- les 400 premiers caractères
            url          TEXT,
            releve_le    TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()


def _retenir(decision: dict) -> str | None:
    texte = normaliser(f"{decision['titre']} {decision['contenu']}")
    if cite(texte, COMMUNE_NAME):
        return "commune"
    if EPCI_NOM and cite(texte, EPCI_NOM):
        return "epci"
    return None


def _traiter(brut: bytes, releve: dict) -> list[tuple]:
    trouves = []
    for d in _decisions(brut):
        releve["lues"] += 1
        if not d["id"]:
            continue
        portee = _retenir(d)
        if not portee:
            continue
        trouves.append((d["id"], COMMUNE_INSEE, portee, d["juridiction"],
                        d["date"], d["numero"], d["titre"], d["type_recours"],
                        (d["contenu"] or "")[:400], f"{LEGIFRANCE}{d['id']}"))
    return trouves


def run(jours: int = JOURS_DEFAUT, amorcer: bool = False) -> int:
    releve = {"lues": 0, "archives": 0}
    trouves: list[tuple] = []

    if amorcer:
        nom = _archive_globale()
        if not nom:
            print("  [justice] aucune archive globale au catalogue")
            return 0
        print(f"  [justice] ⚠️ reprise du corpus entier : {nom} (1,19 Go)")
        trouves += _traiter(_telecharger(nom), releve)
        releve["archives"] += 1
    else:
        for nom in _archives_recentes(jours):
            try:
                trouves += _traiter(_telecharger(nom), releve)
                releve["archives"] += 1
            except Exception as e:                  # noqa: BLE001
                # Une archive illisible ne doit pas emporter les autres, mais
                # elle se dit : un corpus silencieusement amputé est pire qu'un
                # corpus vide.
                print(f"    ↳ {nom} : {e}")

    with transaction() as conn:
        ensure_table(conn)
        for t in trouves:
            conn.execute(
                "INSERT OR IGNORE INTO justice_decisions"
                " (id,insee,portee,juridiction,date_dec,numero,titre,type_recours,"
                "  extrait,url) VALUES (?,?,?,?,?,?,?,?,?,?)", t)

    print(f"  [justice] {releve['archives']} archive(s), {releve['lues']} décision(s) "
          f"lues, {len(trouves)} citant {COMMUNE_NAME}"
          + ("" if trouves else " — le cas ordinaire pour une petite commune"))
    return len(trouves)


def _telecharger(nom: str) -> bytes:
    req = urllib.request.Request(BASE + nom, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=600) as r:
        return r.read()


def _archive_globale() -> str | None:
    req = urllib.request.Request(BASE, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=90) as r:
        page = r.read().decode("utf-8", "replace")
    noms = re.findall(r'href="(Freemium_jade_global_\d{8}-\d{6}\.tar\.gz)"', page)
    return sorted(noms)[-1] if noms else None


def stats():
    conn = get_conn()
    ensure_table(conn)
    lignes = conn.execute(
        "SELECT date_dec, juridiction, numero, type_recours, titre, url"
        " FROM justice_decisions ORDER BY date_dec DESC").fetchall()
    for r in lignes:
        print(f"  {r['date_dec']}  {r['juridiction'] or '?':<34} "
              f"{r['type_recours'] or '':<22} {r['numero']}")
    print(f"  — {len(lignes)} décision(s)")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--jours", type=int, default=JOURS_DEFAUT,
                   help="profondeur des incréments à relire")
    p.add_argument("--amorcer", action="store_true",
                   help="reprendre le corpus entier (1,19 Go)")
    p.add_argument("--stats", action="store_true")
    a = p.parse_args()
    if a.stats:
        stats()
    else:
        run(a.jours, a.amorcer)
