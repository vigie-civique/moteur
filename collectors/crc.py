"""
crc.py — Rapports d'observations définitives des chambres régionales des comptes.

Un rapport de CRC est un audit officiel, contradictoire et public : sur une
commune ou son intercommunalité, c'est la pièce la plus lourde qu'un dossier
puisse contenir. Elle est publique depuis des années, et personne ne va la
chercher.

  - Rapports concernant LA commune          → events (type crc_rapport)
  - Rapports concernant SON intercommunalité → events (type crc_rapport_epci)

Usage :
  python3 -m collectors.crc
  python3 -m collectors.crc --stats

─────────────────────────────────────────────────────────────────────────────
CE QUE LA SOURCE EST, ET CE QU'ELLE N'EST PAS

Il n'y a PAS d'API, et pas de SIREN.

Les jeux de données de la Cour des comptes sur data.gouv.fr existent mais leur
dernière mise à jour date de 2017 : ils couvrent 2014-2015 et ne sont pas
utilisables. La source vivante est le site, dont la recherche est rendue côté
serveur — donc lisible — mais qui n'expose aucun identifiant de collectivité.

Le seul point d'accrochage est le TITRE : « Commune de X (Département) »,
« Communauté de communes du Y (Département) ». Le nom, et le département entre
parenthèses.

⚠️ ET LA RECHERCHE EST UN PLEIN-TEXTE FLOU, PAS UN FILTRE. Interrogée sur le
nom d'une petite commune, elle rend dix résultats dont aucun ne la concerne :
une intercommunalité d'un autre département, une commune au nom voisin, une
région, une société publique locale. Rapprocher sur la seule présence du mot attribuerait à une commune le
rapport d'une autre : dans un dispositif de transparence, c'est la faute qu'on
ne peut pas commettre.

D'où un rapprochement STRICT, en deux conditions qui doivent tenir ensemble :
le nom normalisé doit être exactement celui de la collectivité, et le
département doit correspondre. Un doute écarte le résultat — mieux vaut ne rien
publier qu'attribuer à tort.

⚠️ UNE COMMUNE DE MOINS DE 3 500 HABITANTS N'EST PRESQUE JAMAIS CONTRÔLÉE. Ne
rien trouver est le cas ORDINAIRE, pas un échec : le collecteur clôt en `empty`,
comme les autres, et c'est l'intercommunalité qui porte le plus souvent le
rapport.
"""
import argparse
import html as html_module
import json
import re
import time
import unicodedata
import urllib.parse

import ssl
import urllib.request

from .archive import HEADERS, archive_fetch
from .config import (COMMUNE_INSEE, COMMUNE_NAME, DEPARTEMENT,
                     DEPARTEMENT_NOM, EPCI_NOM, PREFECTURE_NOM, REQUEST_DELAY)
from .db import get_conn, log_run_end, log_run_start

RECHERCHE = "https://www.ccomptes.fr/fr/recherche"
BASE = "https://www.ccomptes.fr"
SOURCE = "ccomptes"

# Les formes sous lesquelles une intercommunalité se nomme. Le titre du site
# écrit « Communauté de communes du … » là où l'instance déclare « CC du … » :
# comparer les deux tels quels ne rapprocherait jamais rien.
FORMES_EPCI = (
    ("communaute de communes", "cc"),
    ("communaute d agglomeration", "ca"),
    ("communaute urbaine", "cu"),
    ("metropole", "metropole"),
)

# Mots de liaison, ignorés dans la comparaison : le site et l'instance ne les
# accordent pas de la même façon (« du Crestois et de Pays de Saillans » contre
# « du Crestois et du Pays de Saillans »).
LIAISONS = {"de", "du", "des", "d", "la", "le", "les", "l", "et", "en", "aux", "au"}


def departement_nom() -> str:
    """Le NOM du département, que le titre porte — pas son code.

    L'instance déclare `departement` en CODE (« 26 ») et le titre du site écrit
    le nom (« Drôme »). Trois lectures, dans cet ordre.

    1. `departement_nom`, DÉCLARÉ par l'instance. C'est la voie normale depuis
       que `init_instance.py` l'écrit — le remède que ce fichier nommait déjà
       sans que personne l'ait posé.
    2. À défaut, `prefecture_nom` relu par un humain : « Préfecture de la X »
       → « X ». Les trois instances communales sont dans ce cas ; la lecture
       reste, elles n'ont pas à être réamorcées.
    3. Sinon on REFUSE, en nommant le remède.

    ⚠️ C'est le point 1 qui manquait, et son absence ne se voyait pas ici mais
    à 700 km : `init_instance.py` écrit « Préfecture (30) » — la forme qu'aucun
    article ne rattrape. Tout dossier national amorcé automatiquement levait
    donc `SystemExit`, `run_all --step crc` sortait en 1, et le portail comptait
    `crc` en échec sur CHAQUE dossier livré. Trois d'affilée, et son veilleur a
    conclu — à juste titre — que la panne n'était pas chez la Cour des comptes.
    Le collecteur n'a jamais eu tort de refuser ; il refusait faute d'une donnée
    que rien ne lui donnait.

    Deviner un département reviendrait à relâcher la seule condition qui
    empêche d'attribuer un rapport à la mauvaise collectivité : on ne devine
    pas, on refuse.
    """
    if (DEPARTEMENT_NOM or "").strip():
        return DEPARTEMENT_NOM.strip()
    trouve = re.match(
        r"^Préfecture\s+(?:de\s+la\s+|du\s+|de\s+l['’]|des\s+|de\s+)(.+)$",
        (PREFECTURE_NOM or "").strip())
    if not trouve:
        raise SystemExit(
            f"Impossible de tirer le nom du département de « {PREFECTURE_NOM} ». "
            "Ajouter `departement_nom` à config/instance.json — sans lui, le "
            "rapprochement ne peut pas être sûr.")
    return trouve.group(1).strip()


def _plat(texte: str) -> str:
    """Minuscules, sans accents ni ponctuation : la forme qu'on compare."""
    sans = unicodedata.normalize("NFD", texte or "")
    sans = "".join(c for c in sans if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]+", " ", sans.lower()).strip()


def _mots_utiles(nom: str) -> list[str]:
    """Les mots qui portent le sens, liaisons et forme juridique ôtées."""
    plat = _plat(nom)
    for longue, courte in FORMES_EPCI:
        plat = plat.replace(longue, " ").replace(f" {courte} ", " ")
    if plat.startswith("cc ") or plat.startswith("ca "):
        plat = plat[3:]
    return [m for m in plat.split() if m and m not in LIAISONS]


def _fetch(terme: str) -> str:
    """La page de résultats — téléchargée, puis archivée comme toute réponse.

    `archive_fetch` ARCHIVE, il ne télécharge pas : c'est au collecteur de le
    faire, comme partout ailleurs dans le moteur. L'archivage n'est pas
    décoratif — il rend la collecte rejouable hors ligne, ce qui compte double
    pour une source qu'on aspire en HTML et qui peut changer de forme.
    """
    url = f"{RECHERCHE}?{urllib.parse.urlencode({'search': terme})}"
    requete = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(requete, timeout=30,
                                    context=ssl.create_default_context()) as reponse:
            brut = reponse.read()
            statut = reponse.status
    except Exception as erreur:
        print(f"  [crc][erreur] {url} → {erreur}")
        return ""
    archive_fetch(SOURCE, url, brut, content_type="text/html",
                  http_status=statut, title=f"Recherche ccomptes : {terme}")
    return brut.decode("utf-8", "replace")


def extraire(html: str) -> list[dict]:
    """Les publications d'une page de résultats, telles qu'elle les rend.

    Calée sur le balisage servi le 01/09/2026 — `<li class="search-result">`,
    titre en `<h2 class="title">`, résumé en `<p class="description">`, chambre
    en `<span class="title-hover">` et date en `<time datetime="…">`.

    ⚠️ La date se lit dans l'ATTRIBUT `datetime`, pas dans le texte « 01.10.2018 ».
    Le texte est écrit pour un lecteur français ; l'attribut est écrit pour une
    machine, et il est déjà au format ISO. Le premier se réordonne au premier
    changement de gabarit, le second est une promesse du format HTML.

    Une première version cherchait des conteneurs `card` ou `teaser` : elle
    n'extrayait qu'UNE publication sur dix, et l'unique retenue était la bonne
    par chance. C'est l'épreuve sur la page réelle qui l'a montré, pas la
    relecture.
    """
    trouvees, vues = [], set()
    for bloc in re.split(r'(?=<li class="search-result">)', html)[1:]:
        bloc = bloc[: bloc.find("</li>") if "</li>" in bloc else len(bloc)]
        lien = re.search(r'href="(/fr/publications/[^"?#]+)"', bloc)
        titre = re.search(r'<h2 class="title">\s*(.*?)\s*</h2>', bloc, re.S)
        if not lien or not titre or lien.group(1) in vues:
            continue
        vues.add(lien.group(1))
        date = re.search(r'<time[^>]*datetime="(\d{4}-\d{2}-\d{2})"', bloc)
        chambre = re.search(r'<span class="title-hover[^"]*"\s*>\s*(.*?)\s*</span>', bloc, re.S)
        resume = re.search(r'<p class="description">\s*(.*?)\s*</p>', bloc, re.S)
        documents = re.search(r'<p class="text">\s*(\d+)\s*Documents?\s*</p>', bloc)
        propre = lambda m: " ".join(html_module.unescape(re.sub(r"<[^>]+>", "", m.group(1))).split()) if m else None
        trouvees.append({
            "titre": propre(titre),
            "url": BASE + lien.group(1),
            "date": date.group(1) if date else None,
            "chambre": propre(chambre),
            "resume": propre(resume),
            "documents": int(documents.group(1)) if documents else None,
        })
    return trouvees


def correspond(titre: str, nom_attendu: str, departement: str, *, epci: bool) -> bool:
    """Le titre désigne-t-il BIEN cette collectivité-ci ?

    Deux conditions qui doivent tenir ENSEMBLE, et non l'une ou l'autre : le
    département écrit entre parenthèses, et le nom. Sans le département, trois
    communes homonymes se partagent le même rapport ; sans le nom, tout le
    département correspond.

    ⚠️ Le sens de l'inclusion n'est pas indifférent, et une première version
    l'avait à l'envers. Elle exigeait que TOUS les mots du nom déclaré soient
    dans le titre — et écartait le bon rapport, l'instance déclarant un nom d'usage
    plus long que celui que le site écrit. Un nom officiel et un nom d'usage ne
    se recouvrent pas mot pour mot.

    C'est donc l'inverse : les mots DU TITRE doivent tous se retrouver dans le
    nom déclaré. un titre qui porte un mot absent du nom déclaré ne passe
    pas — ce qui est précisément le
    faux positif qu'on veut refuser. Et il en faut au moins deux : un seul mot
    laisserait passer une intercommunalité voisine au nom plus court.
    """
    entre_parentheses = re.search(r"\(([^)]+)\)\s*$", titre.strip())
    if not entre_parentheses:
        return False
    if _plat(entre_parentheses.group(1)) != _plat(departement):
        return False

    mots_titre = _mots_utiles(titre[: entre_parentheses.start()])
    mots_attendus = _mots_utiles(nom_attendu)
    if not mots_titre or not mots_attendus:
        return False

    if epci:
        distinctifs = [m for m in mots_titre if m not in ("commune", "communes", "ville")]
        return len(distinctifs) >= 2 and all(m in mots_attendus for m in distinctifs)
    # Une commune se nomme exactement : « Commune de Saillans » porte
    # [commune, saillans], on retire le mot de forme et on exige l'égalité.
    return [m for m in mots_titre if m not in ("commune", "ville")] == mots_attendus


def _enregistrer(conn, publication: dict, type_event: str) -> bool:
    """Écrit le rapport, sauf s'il y est déjà. Rend True s'il est neuf."""
    deja = conn.execute("SELECT id FROM events WHERE source=? AND source_url=?",
                        (SOURCE, publication["url"])).fetchone()
    if deja:
        return False
    conn.execute(
        "INSERT INTO events (type, date, title, content, source, source_url, metadata)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (type_event, publication["date"], publication["titre"],
         publication["resume"], SOURCE, publication["url"],
         json.dumps({"chambre": publication["chambre"]}, ensure_ascii=False)))
    return True


def run_crc() -> dict:
    """Interroge la source pour la commune, puis pour son intercommunalité."""
    departement = departement_nom()
    cibles = [(COMMUNE_NAME, "crc_rapport", False)]
    if EPCI_NOM:
        cibles.append((EPCI_NOM, "crc_rapport_epci", True))

    releve = {"trouves": 0, "neufs": 0, "ecartes": 0, "ecartes_titres": []}
    with get_conn() as conn:
        run_id = log_run_start(conn, "crc", None)
        try:
            for terme, type_event, epci in cibles:
                page = _fetch(terme)
                for publication in extraire(page):
                    if correspond(publication["titre"], terme, departement, epci=epci):
                        releve["trouves"] += 1
                        if _enregistrer(conn, publication, type_event):
                            releve["neufs"] += 1
                    else:
                        releve["ecartes"] += 1
                        # ⚠️ Une omission doit SE VOIR. Le rapprochement est
                        # volontairement strict : il préfère ne rien publier
                        # qu'attribuer un rapport à la mauvaise collectivité.
                        # Cette prudence a un coût — une variante du titre, un
                        # sigle, un siège écrit à côté du nom, et un vrai
                        # rapport passe à la trappe. Constaté sur un titre qui
                        # ajoutait au nom le sigle de l'EPCI et le nom de la
                        # commune de son siège.
                        # Les écarter en silence rendrait ce défaut invisible ;
                        # les nommer laisse un humain les rattraper.
                        releve["ecartes_titres"].append(publication["titre"])
                time.sleep(REQUEST_DELAY)
        except Exception as erreur:
            log_run_end(conn, run_id, "error", None, None, error=str(erreur)[:300])
            raise
        # `empty` n'est pas un échec : sous 3 500 habitants, une commune n'est
        # presque jamais contrôlée, et c'est l'intercommunalité qui porte le
        # rapport quand il y en a un.
        # ⚠️ Ce qui est JOURNALISÉ comme apport, ce sont les rapports NEUFS,
        # pas les rapports retenus. La première version passait `trouves` et
        # un `items_before` de 0 : Saillans, qui porte deux rapports depuis
        # 2018, déclarait « +2 » à CHAQUE passage. Un tel journal ne peut plus
        # signaler qu'une source s'est figée — c'est exactement la panne que
        # `stale_source` cherche (cf. decp_augmente), rendue indétectable.
        log_run_end(conn, run_id, "ok" if releve["trouves"] else "empty",
                    releve["trouves"], releve["trouves"] - releve["neufs"])
    return releve


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--stats", action="store_true",
                        help="compte ce qui est déjà en base, sans rien collecter")
    arguments = parser.parse_args()

    if arguments.stats:
        with get_conn(read_only=True) as conn:
            for type_event in ("crc_rapport", "crc_rapport_epci"):
                combien = conn.execute("SELECT COUNT(*) FROM events WHERE type=?",
                                       (type_event,)).fetchone()[0]
                print(f"  {type_event:20} {combien}")
        return 0

    releve = run_crc()
    print(f"CRC — {COMMUNE_NAME} ({COMMUNE_INSEE}, dépt {DEPARTEMENT}) : "
          f"{releve['trouves']} rapport(s) retenu(s), {releve['neufs']} neuf(s), "
          f"{releve['ecartes']} résultat(s) écarté(s) comme hors sujet.")
    for titre in releve["ecartes_titres"]:
        print(f"    écarté : {titre}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
