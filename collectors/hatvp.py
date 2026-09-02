"""
hatvp.py — Qui, ici, doit déclarer ses intérêts — et où en est sa déclaration.

La Haute Autorité pour la transparence de la vie publique publie la liste des
responsables publics soumis à l'obligation de déclaration, et l'état de chaque
dossier. Pour une commune, la question tient en une phrase : le maire est-il
soumis, le président de l'intercommunalité l'est-il, et leurs déclarations
sont-elles publiées ?

🔴 CE COLLECTEUR N'INGÈRE PAS LE CONTENU DES DÉCLARATIONS.

Le patrimoine et les intérêts déclarés sont publiés par la HATVP dans un fichier
à part (87 Mo). Ils ne sont pas collectés ici : ce qui intéresse un dispositif
communal, c'est l'EXISTENCE et l'ÉTAT de l'obligation — soumis ou non, déposé ou
non, publié ou non —, avec le lien vers la page officielle. Le détail se lit
chez celui qui l'établit, et c'est aussi ce qui garantit qu'on n'en publie pas
une copie périmée.

⚠️ NE RIEN TROUVER EST LE CAS ORDINAIRE. L'obligation vise les communes de plus
de 20 000 habitants, les EPCI au-delà du même seuil, et les élus titulaires
d'une délégation. Sous ces seuils, personne n'est soumis : un résultat vide ne
dit pas « aucun élu n'a déclaré », il dit « la loi n'exige rien à cette
échelle ». C'est une information, et elle se publie comme telle.

─────────────────────────────────────────────────────────────────────────────
LA SOURCE NE PORTE NI CODE INSEE NI SIREN

Le seul rattachement territorial est un texte libre : « Maire d'Alès »,
« Président de la communauté de communes du Crestois et du pays de Saillans ».
C'est le même problème que pour les rapports de chambre régionale des comptes,
et le même remède : deux conditions qui doivent tenir ENSEMBLE, jamais la
présence d'un mot.

  - le DÉPARTEMENT de la ligne doit être celui de la commune ;
  - le type de mandat doit être celui qu'on cherche (`commune` ou `epci`) ;
  - pour la commune : la qualité doit se TERMINER par son nom. « Lasalle » ne
    doit pas ramasser « Lasalle-sur-Cèze », et une simple recherche de mot ne
    les sépare pas ;
  - pour l'intercommunalité : la majorité des mots significatifs de son nom doit
    se retrouver, parce que la HATVP l'écrit rarement comme la préfecture
    (« CC du Crestois et de Pays de Saillans Cœur de Drôme » y devient
    « communauté de communes du Crestois et du pays de Saillans »).

Un doute écarte la ligne, et l'écart est compté : mieux vaut ne rien publier
qu'attribuer à quelqu'un une obligation qui ne le concerne pas.

Source : `hatvp.fr/livraison/opendata/liste.csv`, sans clé.

Usage :
  python3 -m collectors.hatvp
  python3 -m collectors.hatvp --stats
"""
import argparse
import csv
import io
import re
import unicodedata
import urllib.request

from .archive import HEADERS, archive_fetch
from .config import COMMUNE_INSEE, COMMUNE_NAME, DEPARTEMENT, EPCI_NOM
from .db import get_conn, transaction

SOURCE = "hatvp"
LISTE = "https://www.hatvp.fr/livraison/opendata/liste.csv"
BASE = "https://www.hatvp.fr"

# Mots qui ne distinguent pas une collectivité d'une autre : les garder ferait
# se ressembler toutes les communautés de communes du département.
VIDES = {"cc", "ca", "cu", "communaute", "communautes", "commune", "de", "des",
         "du", "la", "le", "les", "et", "d", "l", "en", "pays", "agglomeration",
         "metropole", "syndicat", "coeur", "grand", "grande", "val", "vallee"}

# Part des mots significatifs du nom d'un EPCI qu'il faut retrouver.
SEUIL_EPCI = 0.6

# La qualité d'un élu communal se TERMINE par le nom de sa commune : « Maire de
# Lasalle », « Adjointe au maire de Nantes ». Mesuré sur le fichier du
# 02/09/2026 : 1 521 lignes de mandat communal, et AUCUNE ne porte de complément
# après le nom (ni virgule, ni « chargé de »). Exiger que le nom cherché soit à
# la fin est donc à la fois strict et sans perte — c'est ce qui sépare
# « Lasalle » de « Lasalle-sur-Cèze », que ni une recherche de mot ni une liste
# de prolongements ne distinguent (« Saint-Just » suivi de « Malmont » passait).


def normaliser(texte: str | None) -> str:
    t = unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def jetons_significatifs(nom: str) -> set[str]:
    return {j for j in normaliser(nom).split() if j not in VIDES and len(j) > 2}


def cite_la_commune(qualite: str, commune: str) -> bool:
    """La qualité se termine-t-elle par le nom EXACT de la commune ?

    Terminer, et pas contenir : « Maire de Lasalle-sur-Cèze » contient
    « Lasalle », et l'attribuer à Lasalle serait donner à une commune l'élu
    d'une autre.
    """
    mots = normaliser(qualite).split()
    cherche = normaliser(commune).split()
    if not cherche or len(cherche) > len(mots):
        return False
    return mots[-len(cherche):] == cherche


def cite_l_epci(qualite: str, epci: str) -> bool:
    attendus = jetons_significatifs(epci)
    if len(attendus) < 2:
        return False          # un nom trop pauvre ne peut pas être rapproché
    presents = attendus & set(normaliser(qualite).split())
    return len(presents) >= 2 and len(presents) / len(attendus) >= SEUIL_EPCI


def telecharger() -> str:
    req = urllib.request.Request(LISTE, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=120) as r:
        brut = r.read()
        archive_fetch(SOURCE, LISTE, brut,
                      content_type=r.headers.get_content_type(), http_status=r.status)
    return brut.decode("utf-8-sig", errors="replace")


def selectionner(texte: str, departement: str, commune: str,
                 epci: str | None) -> tuple[list[dict], int]:
    """Les déclarants de CETTE commune et de SON intercommunalité.

    Rend aussi le nombre de lignes du même département écartées : c'est la
    mesure de ce que le rapprochement a refusé, et elle doit rester visible.
    """
    retenus, ecartes = [], 0
    for ligne in csv.DictReader(io.StringIO(texte), delimiter=";"):
        if (ligne.get("departement") or "").strip() != departement:
            continue
        mandat = (ligne.get("type_mandat") or "").strip()
        qualite = ligne.get("qualite") or ""
        portee = None
        if mandat == "commune" and cite_la_commune(qualite, commune):
            portee = "commune"
        elif mandat == "epci" and epci and cite_l_epci(qualite, epci):
            portee = "epci"
        if not portee:
            ecartes += 1
            continue
        chemin = (ligne.get("url_dossier") or "").strip()
        retenus.append({
            "portee": portee,
            "prenom": (ligne.get("prenom") or "").strip(),
            "nom": (ligne.get("nom") or "").strip(),
            "qualite": qualite.strip(),
            "type_document": (ligne.get("type_document") or "").strip(),
            "statut": (ligne.get("statut_publication") or "").strip(),
            "date_depot": (ligne.get("date_depot") or "").strip() or None,
            "date_publication": (ligne.get("date_publication") or "").strip() or None,
            "url": f"{BASE}{chemin}" if chemin.startswith("/") else chemin or None,
            "reference": (ligne.get("classement") or "").strip(),
        })
    return retenus, ecartes


def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS hatvp_declarations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            insee       TEXT NOT NULL,
            portee      TEXT NOT NULL,     -- commune | epci
            prenom      TEXT,
            nom         TEXT,
            qualite     TEXT,              -- le texte de la HATVP, tel quel
            type_document TEXT,            -- di (intérêts) | dsp (patrimoine) | dia
            statut      TEXT,              -- publiée | en cours | dispense…
            date_depot  TEXT,
            date_publication TEXT,
            url         TEXT,
            reference   TEXT,
            releve_le   TEXT DEFAULT (datetime('now')),
            UNIQUE(insee, reference, type_document)
        )
    """)
    conn.commit()


def run(insee: str | None = None) -> int:
    texte = telecharger()
    cible = insee or COMMUNE_INSEE
    retenus, ecartes = selectionner(texte, DEPARTEMENT, COMMUNE_NAME, EPCI_NOM)
    with transaction() as conn:
        ensure_table(conn)
        # Le registre est un ÉTAT : une déclaration retirée ou requalifiée ne
        # doit pas survivre en base sous son ancien statut.
        conn.execute("DELETE FROM hatvp_declarations WHERE insee=?", (cible,))
        for d in retenus:
            conn.execute(
                "INSERT OR IGNORE INTO hatvp_declarations"
                " (insee,portee,prenom,nom,qualite,type_document,statut,date_depot,"
                "  date_publication,url,reference)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (cible, d["portee"], d["prenom"], d["nom"], d["qualite"],
                 d["type_document"], d["statut"], d["date_depot"],
                 d["date_publication"], d["url"], d["reference"]))
    if retenus:
        for d in retenus:
            print(f"  [hatvp] {d['portee']:<8} {d['qualite'][:60]} — {d['statut']}")
    else:
        print(f"  [hatvp] {COMMUNE_NAME} — personne n'est soumis à l'obligation à "
              "cette échelle (aucune déclaration attendue)")
    print(f"[hatvp] {len(retenus)} déclaration(s) retenue(s), "
          f"{ecartes} ligne(s) du département écartée(s)")
    return len(retenus)


def stats():
    conn = get_conn()
    ensure_table(conn)
    lignes = conn.execute(
        "SELECT portee, prenom, nom, qualite, type_document, statut, url"
        " FROM hatvp_declarations ORDER BY portee, nom").fetchall()
    for r in lignes:
        print(f"  {r['portee']:<8} {r['prenom']} {r['nom']:<24} "
              f"{r['type_document']:<4} {r['statut'][:30]:<32} {r['qualite'][:50]}")
    print(f"  — {len(lignes)} déclaration(s)")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--insee", help="rattacher à une autre commune du périmètre")
    p.add_argument("--stats", action="store_true")
    a = p.parse_args()
    if a.stats:
        stats()
    else:
        run(a.insee)
