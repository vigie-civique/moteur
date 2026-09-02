"""
sispea.py — Le prix de l'eau du robinet, et l'état du réseau qui l'apporte.

Prix TTC du mètre cube, rendement du réseau, taux de renouvellement des
canalisations, conformité sanitaire : les chiffres qu'un habitant cherche quand
il pense « eau », et que personne ne va lire dans un rapport annexé au compte
administratif.

Deux sources pour une seule donnée — l'observatoire national SISPEA :

  - **Hub'Eau** rattache la commune à ses services et donne leurs indicateurs
    jusqu'à l'exercice 2019. C'est la seule source qui sache DE QUEL service une
    commune dépend.
  - **Les extractions de l'OFB** donnent les exercices 2015 à 2024, France
    entière, mais en archives 7z de classeurs Excel : elles ne portent aucune
    liste de communes — elles les COMPTENT (« 6 ») sans les nommer.

Ensemble : une série de 2008 à 2024, service par service. C'est ce que le site
d'une commune peut montrer et qu'aucun aperçu national ne montrera — non pas un
prix, mais son évolution sur quinze ans.

Usage :
  python3 -m collectors.sispea
  python3 -m collectors.sispea --stats
  python3 -m collectors.sispea --sans-millesimes   # Hub'Eau seul, sans l'OFB

─────────────────────────────────────────────────────────────────────────────
CE QUI REND LA JOINTURE POSSIBLE

`Id SISPEA de l'entité de gestion`, dans les fichiers de l'OFB, EST le
`code_service` de Hub'Eau. Vérifié sur plusieurs services, dont un syndicat
intercommunal et deux régies communales. Sans cette égalité, les extractions
nationales seraient inexploitables commune par commune.

⚠️ CINQ PIÈGES, tous rencontrés en lisant ces fichiers, aucun visible à la
relecture du code :

1. `/indicateurs` DE HUB'EAU N'A PAS DE PARAMÈTRE `code_commune` et l'accepte
   quand même : il rend la France entière — 68 064 lignes — en commençant par un
   autre département. On passe par `/services` et `/communes`, qui filtrent.

2. `/communes` REND CHAQUE LIGNE EN DOUBLE, une fois nommée, une fois anonyme.

3. LES EN-TÊTES DES CLASSEURS CHANGENT DE CONVENTION À CHAQUE GÉNÉRATION :
   « Id SISPEA du service » (2015-2019), `id_sispea_serv` (2020-2023),
   « Id SISPEA de l'entité de gestion » (2024) — et l'un des fichiers écrit
   `N_iNSEE_si_commune`, avec une capitale au milieu d'un mot. D'où une
   comparaison sur forme normalisée, des alias déclarés, et un ARRÊT NET quand
   une colonne manque : un index à demi rempli, écrit en silence, serait pire.

4. L'EXTENSION MENT — une archive livre un `.xls` qui est un `.xlsx`. Et
   reconnaître les octets ne suffit pas : `openpyxl` refuse d'après l'EXTENSION
   sans regarder le contenu, d'où le passage par un flux.

5. ZÉRO N'EST PAS UN PRIX. Des services déclarent 0 €/m³ : une case laissée
   vide, pas une eau gratuite. Le zéro reste légitime partout ailleurs — un
   service peut n'avoir renouvelé aucune canalisation dans l'année.

🔴 ET LES CLASSEURS PORTENT UNE COLONNE DE COURRIELS, une adresse par service et
souvent nominative. Les colonnes lues sont une LISTE BLANCHE, jamais un retrait
de ce qui gêne : une colonne ajoutée par le producteur n'entre pas dans la base
sans qu'on l'ait écrite ici.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import time
import unicodedata
import urllib.parse
import urllib.request

from .archive import fetch_json
from .config import (COMMUNE_INSEE, HEADERS, NATIONAL_STORE, REQUEST_DELAY,
                     communes_du_step)
from .db import get_conn, log_run_end, log_run_start
from .national_store import ecrire_atomiquement, est_frais

SOURCE = "sispea"
HUBEAU = "https://hubeau.eaufrance.fr/api/v0/indicateurs_services"
CATALOGUE = "https://data.ofb.fr/catalogue/srv/api/records/{record}/attachments"
CACHE = NATIONAL_STORE / "sispea"

# Les exercices que l'OFB publie. Les récents apportent la fraîcheur — Hub'Eau
# s'arrête à 2019 — et les anciens la couverture : un service qui a cessé de
# déclarer en 2017 n'est dans aucun fichier récent.
MILLESIMES = tuple(range(2015, 2025))

# Un millésime ne change plus une fois publié ; seul le dernier peut être
# complété en cours d'année.
MILLESIME_CACHE_JOURS = 180

COMPETENCES = {
    "AEP": {
        "record": "7d6a3010-cf19-42c3-8a38-9823074185ce",
        "marque": "_AEP",
        # Hub'Eau expose le rattachement de l'eau potable sur `/services`, qui
        # porte aussi l'identité du service. L'assainissement n'y est PAS :
        # contrôlé, un département entier rend zéro service. Il se lit sur
        # `/communes`, qui ne donne que des identifiants.
        "route": "services",
        "libelle": "eau potable",
    },
    "AC": {
        "record": "5feec4e9-03a6-409a-a522-d51346d5f4c9",
        "marque": "_AC",
        "route": "communes",
        "libelle": "assainissement collectif",
    },
}

# LISTE BLANCHE des colonnes des classeurs. Chaque entrée : le nom retenu, puis
# les formes normalisées sous lesquelles les générations d'export l'écrivent.
COLONNES = {
    "service": ("id_sispea_de_l_entite_de_gestion", "id_sispea_serv", "id_sispea_du_service"),
    "collectivite": ("nom_collectivite", "nom_coll"),
    "type": ("type_collectivite", "type_coll"),
    "gestion": ("mode_de_gestion", "mode_gestion"),
}

# Les indicateurs retenus, et ce qu'ils disent. Les mêmes des deux sources : une
# série qui changerait de contenu selon l'année d'où elle vient ne serait pas
# une série. Codes de l'arrêté du 2 mai 2007.
INDICATEURS = {
    "AEP": {
        "D102.0": ("Prix TTC du m³ pour 120 m³", "€/m³"),
        "P104.3": ("Rendement du réseau de distribution", "%"),
        "P107.2": ("Taux moyen de renouvellement des réseaux", "%"),
        "P101.1": ("Taux de conformité microbiologique", "%"),
        "P102.1": ("Taux de conformité physico-chimique", "%"),
        "D101.0": ("Habitants desservis", "hab."),
    },
    "AC": {
        "D204.0": ("Prix TTC du m³ pour 120 m³", "€/m³"),
        "P201.1": ("Taux de desserte par les réseaux de collecte", "%"),
        "P205.3": ("Conformité de la performance des ouvrages d'épuration", "%"),
    },
}

# Le prix est le seul indicateur dont zéro n'est pas une valeur.
INDICATEURS_SANS_ZERO = {"D102.0", "D204.0"}


def ensure_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sispea_services (
            code_service    TEXT PRIMARY KEY,
            competence      TEXT NOT NULL,          -- AEP | AC
            nom             TEXT,                   -- la collectivité (extractions OFB)
            libelle         TEXT,                   -- le service (Hub'Eau) : « eau potable »
            type_collectivite TEXT,
            mode_gestion    TEXT,                   -- Régie | Délégation
            siren           TEXT,
            communes        TEXT,                   -- codes INSEE desservis, séparés par des virgules
            created_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS sispea_indicateurs (
            code_service    TEXT NOT NULL REFERENCES sispea_services(code_service),
            annee           INTEGER NOT NULL,
            code            TEXT NOT NULL,
            libelle         TEXT,
            unite           TEXT,
            valeur          REAL,
            origine         TEXT,                   -- hubeau | ofb
            PRIMARY KEY (code_service, annee, code)
        );
        CREATE INDEX IF NOT EXISTS idx_sispea_indicateurs_annee
            ON sispea_indicateurs(annee, code);
    """)
    conn.commit()


def plat(nom: object) -> str:
    """La forme sur laquelle on compare deux en-têtes : sans casse ni accents."""
    sans = unicodedata.normalize("NFD", str(nom if nom is not None else ""))
    sans = "".join(c for c in sans if unicodedata.category(c) != "Mn")
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", sans.lower())).strip("_")


def nombre(valeur: object) -> float | None:
    """Un nombre, quelle que soit la façon dont le millésime l'a écrit.

    Le vide s'écrit « . » dans ces classeurs, les nombres sont tantôt des
    nombres et tantôt des chaînes, et la virgule décimale apparaît selon le
    poste qui a produit l'export.
    """
    if valeur is None or isinstance(valeur, bool):
        return None
    if isinstance(valeur, (int, float)):
        return float(valeur)
    texte = str(valeur).strip().replace(",", ".")
    if texte in ("", ".", "-", "nan", "None"):
        return None
    try:
        return float(texte)
    except ValueError:
        return None


def _texte(valeur: object) -> str | None:
    if valeur is None:
        return None
    net = " ".join(str(valeur).split())
    return net if net and net != "." else None


# ── Hub'Eau : QUI dessert la commune, et ce qu'il déclarait jusqu'en 2019 ─────

def services_hubeau(insee: str, competence: str) -> list[dict]:
    """Les lignes que Hub'Eau rend pour cette commune, une par service et année."""
    reglage = COMPETENCES[competence]
    parametres = urllib.parse.urlencode(
        {"code_commune": insee, "type_service": competence, "size": 500})
    url = f"{HUBEAU}/{reglage['route']}?{parametres}"
    try:
        return fetch_json(url, source=SOURCE, timeout=60).get("data", [])
    except Exception as erreur:  # noqa: BLE001 — une compétence absente n'arrête pas l'autre
        print(f"  [sispea][{competence}] {insee} → {erreur}")
        return []


def _identite(ligne: dict, competence: str) -> tuple[str, dict] | None:
    """Le service que décrit cette ligne, sous la forme qu'on enregistre.

    ⚠️ `/services` nomme UN service (`code_service`), `/communes` en liste
    plusieurs par ligne (`codes_service`). Ne lire qu'une des deux formes
    réunirait sous une clé vide des services réellement distincts.
    """
    identifiants = ligne.get("codes_service") or [ligne.get("code_service")]
    identifiants = [str(i) for i in identifiants if i not in (None, "")]
    if len(identifiants) != 1:
        # Une ligne de `/communes` peut couvrir plusieurs services : ses
        # indicateurs sont alors ceux de leur agrégat, et on ne saurait pas à
        # qui les attribuer. On garde l'identité, pas les valeurs.
        return None
    # ⚠️ `nom` et `libelle` ne disent pas la même chose, et les ranger dans la
    # même colonne faisait afficher « LASALLE » pour un service et « eau
    # potable » pour l'autre, selon la source arrivée en dernier. Hub'Eau nomme
    # le SERVICE, l'OFB nomme la COLLECTIVITÉ : deux colonnes, chacune remplie
    # par la source qui la connaît.
    return identifiants[0], {
        "libelle": _texte(ligne.get("nom_service")) or _texte((ligne.get("noms_service") or [None])[0]),
        "type_collectivite": _texte(ligne.get("type_collectivite")),
        "mode_gestion": _texte(ligne.get("mode_gestion")),
        "siren": _texte(ligne.get("numero_siren")),
        "communes": ",".join(str(c) for c in (ligne.get("codes_commune") or []) if c),
    }


# ── OFB : les exercices que Hub'Eau ne publie pas ────────────────────────────

def _archives(competence: str) -> dict[int, str]:
    """Les URL des archives, relevées dans le catalogue plutôt que devinées.

    Les noms changent d'une année à l'autre — `…_2022_AEP_260124_Rapport_SISPEA.7z`
    puis `…_2024_AEP.7z`. Les composer à la main aurait fait échouer la collecte
    au prochain changement de convention, et ce producteur en change souvent.

    ⚠️ Le catalogue écrit `filename`, pas `fileName` : la mauvaise graphie ne
    lève rien, elle rend une liste VIDE. D'où le refus explicite plus bas.
    """
    reglage = COMPETENCES[competence]
    url = CATALOGUE.format(record=reglage["record"])
    requete = urllib.request.Request(url, headers={**HEADERS, "accept": "application/json"})
    with urllib.request.urlopen(requete, timeout=60) as reponse:
        pieces = json.load(reponse)
    pieces = pieces if isinstance(pieces, list) else pieces.get("items", [])
    trouvees: dict[int, str] = {}
    for piece in pieces:
        nom = str(piece.get("filename") or "")
        if not nom.endswith(".7z") or reglage["marque"] not in nom:
            continue
        for annee in MILLESIMES:
            if f"_{annee}_" in nom or nom.endswith(f"_{annee}{reglage['marque']}.7z"):
                trouvees[annee] = piece["url"]
    if not trouvees:
        raise RuntimeError(
            f"aucune archive {reglage['marque']} dans le catalogue de l'OFB ({url}) — "
            "le catalogue a changé de forme ; une collecte muette serait pire")
    return trouvees


def _format_reel(chemin) -> str:
    """Le format d'après SES OCTETS, jamais d'après son nom."""
    tete = chemin.open("rb").read(4)
    if tete[:2] == b"PK":
        return "xlsx"
    if tete == b"\xd0\xcf\x11\xe0":
        return "xls"
    raise RuntimeError(f"{chemin.name} : ni xlsx ni xls (octets de tête {tete!r})")


def _lignes_du_classeur(chemin):
    """Les lignes du classeur, en-têtes normalisés, quel que soit son format."""
    if _format_reel(chemin) == "xlsx":
        import openpyxl
        # 🔴 On passe un FLUX : `openpyxl` refuse d'après l'EXTENSION — « does
        # not support the old .xls file format » — sans regarder le contenu.
        with chemin.open("rb") as flux:
            cahier = openpyxl.load_workbook(flux, read_only=True, data_only=True)
            feuille = cahier.worksheets[0]
            iterateur = feuille.iter_rows(values_only=True)
            entetes = [plat(x) for x in next(iterateur)]
            for ligne in iterateur:
                yield entetes, ligne
            cahier.close()
        return
    try:
        import xlrd
    except ModuleNotFoundError as absent:
        raise RuntimeError(
            "xlrd manque, et l'un des millésimes est un classeur d'ancienne "
            "génération : pip install xlrd") from absent
    cahier = xlrd.open_workbook(str(chemin))
    feuille = cahier.sheet_by_index(max(0, cahier.nsheets - 1))
    entetes = [plat(feuille.cell_value(0, j)) for j in range(feuille.ncols)]
    for i in range(1, feuille.nrows):
        yield entetes, [feuille.cell_value(i, j) for j in range(feuille.ncols)]


def _indice(entetes: list[str], noms: tuple[str, ...], quoi: str, nom_fichier: str) -> int:
    for nom in noms:
        if nom in entetes:
            return entetes.index(nom)
    raise RuntimeError(
        f"{nom_fichier} : colonne « {quoi} » introuvable sous {noms}. "
        f"En-têtes lus : {entetes[:24]}. Le producteur a changé de convention : "
        "ajouter l'alias dans COLONNES ou INDICATEURS.")


def _extraire_archive(archive):
    """Le classeur contenu dans l'archive 7z, extrait à côté d'elle."""
    dossier = archive.with_suffix("")
    deja = [c for c in dossier.iterdir() if c.suffix.lower() in (".xls", ".xlsx")] \
        if dossier.is_dir() else []
    if deja:
        return deja[0]
    if shutil.which("bsdtar") is None:
        raise RuntimeError(
            "bsdtar est introuvable et les extractions de l'OFB sont des archives 7z "
            "(macOS le fournit ; Debian : apt install libarchive-tools)")
    dossier.mkdir(parents=True, exist_ok=True)
    subprocess.run(["bsdtar", "-xf", str(archive), "-C", str(dossier)], check=True)
    classeurs = [c for c in dossier.iterdir() if c.suffix.lower() in (".xls", ".xlsx")]
    if not classeurs:
        raise RuntimeError(f"{archive.name} ne contient aucun classeur")
    return classeurs[0]


def millesime(competence: str, annee: int, url: str) -> dict[str, dict]:
    """Un exercice entier, réduit aux colonnes retenues, et gardé au magasin.

    Le fichier réduit pèse un mégaoctet là où le classeur en pèse quatorze, et
    il est PARTAGÉ : la deuxième instance qui collecte ne relit rien.
    """
    reduit = CACHE / "millesimes" / f"{competence}-{annee}.json"
    if est_frais(reduit, MILLESIME_CACHE_JOURS):
        return json.loads(reduit.read_bytes())

    archive = CACHE / "archives" / urllib.parse.urlparse(url).path.rsplit("/", 1)[-1]
    if not est_frais(archive, None):
        requete = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(requete, timeout=300) as reponse:
            ecrire_atomiquement(archive, reponse.read())
        if not archive.is_file():
            # Magasin en lecture seule : on ne peut pas garder l'archive, donc
            # pas non plus l'exploiter. Ce n'est pas une erreur de collecte.
            print(f"  [sispea] magasin non écrivable — millésime {annee} ignoré")
            return {}

    classeur = _extraire_archive(archive)
    services: dict[str, dict] = {}
    colonnes: dict[str, int] = {}
    entetes_vus: list[str] = []
    for entetes, ligne in _lignes_du_classeur(classeur):
        if entetes is not entetes_vus:
            entetes_vus = entetes
            colonnes = {c: _indice(entetes, formes, c, classeur.name)
                        for c, formes in COLONNES.items()
                        if c != "gestion" or competence == "AEP"}
            colonnes |= {code: _indice(entetes, (plat(code),), code, classeur.name)
                         for code in INDICATEURS[competence]}
        identifiant = nombre(ligne[colonnes["service"]])
        if identifiant is None:
            continue
        fiche = {
            "nom": _texte(ligne[colonnes["collectivite"]]),
            "type_collectivite": _texte(ligne[colonnes["type"]]),
            "mode_gestion": _texte(ligne[colonnes["gestion"]]) if competence == "AEP" else None,
            "indicateurs": {},
        }
        for code in INDICATEURS[competence]:
            valeur = nombre(ligne[colonnes[code]])
            if valeur is None or (valeur == 0 and code in INDICATEURS_SANS_ZERO):
                continue
            fiche["indicateurs"][code] = valeur
        services[str(int(identifiant))] = fiche

    if ecrire_atomiquement(
            reduit, json.dumps(services, ensure_ascii=False, separators=(",", ":")).encode()):
        # Le classeur de quatorze mégaoctets ne sert plus : le fichier réduit en
        # pèse un et dit la même chose. L'archive, elle, reste — c'est la pièce
        # d'origine, et la reconstruire depuis elle doit rester possible.
        shutil.rmtree(classeur.parent, ignore_errors=True)
    return services


# ── Écriture ─────────────────────────────────────────────────────────────────

def _mieux_ecrit(neuf: str | None, ancien: str | None) -> str | None:
    """Entre deux graphies d'une même valeur, celle qui porte ses accents.

    🔴 Hub'Eau écrit « Régie » et « Délégation », les extractions de l'OFB
    écrivent « Regie » et « Delegation ». La source qui passe en dernier
    l'emportant, la base se remplissait de mots français sans leurs accents —
    et deux services d'une même commune s'affichaient sous deux graphies du
    même mot.

    La règle ne réécrit rien qu'on n'ait pas vu écrit : à forme normalisée
    identique on garde la mieux accentuée, sinon la plus récente l'emporte,
    parce qu'une valeur qui CHANGE est une information.
    """
    if not neuf:
        return ancien
    if not ancien or plat(neuf) != plat(ancien):
        return neuf
    accentuation = lambda mot: sum(1 for c in mot if ord(c) > 127)  # noqa: E731
    return neuf if accentuation(neuf) >= accentuation(ancien) else ancien


def _ecrire_service(conn, code: str, competence: str, identite: dict) -> None:
    """Enregistre le service, en complétant ce qui manque sans écraser ce qui est.

    Les deux sources ne portent pas les mêmes champs : Hub'Eau donne le SIREN et
    la liste des communes desservies, l'OFB donne un nom de collectivité souvent
    plus complet. Un `INSERT OR REPLACE` ferait perdre à chaque passage ce que
    l'autre source avait apporté.
    """
    ancien = conn.execute(
        "SELECT nom, libelle, type_collectivite, mode_gestion, siren, communes"
        " FROM sispea_services WHERE code_service=?", (code,)).fetchone()
    champs = ("nom", "libelle", "type_collectivite", "mode_gestion", "siren", "communes")
    valeurs = {c: _mieux_ecrit(identite.get(c), ancien[c] if ancien else None) for c in champs}
    if ancien:
        conn.execute(
            "UPDATE sispea_services SET nom=?, libelle=?, type_collectivite=?,"
            " mode_gestion=?, siren=?, communes=? WHERE code_service=?",
            (*[valeurs[c] for c in champs], code))
    else:
        conn.execute(
            "INSERT INTO sispea_services (code_service, competence, nom, libelle,"
            " type_collectivite, mode_gestion, siren, communes) VALUES (?,?,?,?,?,?,?,?)",
            (code, competence, *[valeurs[c] for c in champs]))


def _ecrire_indicateur(conn, code_service: str, annee: int, competence: str,
                       code: str, valeur: float, origine: str) -> bool:
    """Écrit une mesure, sauf si elle y est déjà. Rend True si elle est neuve.

    ⚠️ Les deux sources se recouvrent sur 2015-2019. La clé primaire fait le
    tri, et l'OFB passe APRÈS : à valeur discordante, c'est le fichier publié
    par le producteur qui fait foi sur l'API qui le republie.
    """
    libelle, unite = INDICATEURS[competence][code]
    if origine == "hubeau":
        curseur = conn.execute(
            "INSERT OR IGNORE INTO sispea_indicateurs"
            " (code_service, annee, code, libelle, unite, valeur, origine)"
            " VALUES (?,?,?,?,?,?,?)",
            (code_service, annee, code, libelle, unite, valeur, origine))
    else:
        curseur = conn.execute(
            "INSERT INTO sispea_indicateurs"
            " (code_service, annee, code, libelle, unite, valeur, origine)"
            " VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(code_service, annee, code) DO UPDATE SET"
            " valeur=excluded.valeur, origine=excluded.origine",
            (code_service, annee, code, libelle, unite, valeur, origine))
    return curseur.rowcount > 0


def _moisson_hubeau() -> list[tuple[str, dict]]:
    """Tout ce que Hub'Eau rend pour le périmètre, AVANT d'ouvrir la base.

    🔴 `archive_fetch` ouvre la base pour son propre compte. Appelé depuis une
    collecte qui la tient déjà ouverte, il rend « database is locked » et SAUTE
    l'archivage — il le dit, la collecte n'échoue pas, et la réponse brute n'est
    simplement jamais gardée. Constaté à la première exécution réelle, sur la
    réponse d'assainissement. Or l'archivage n'est pas décoratif : c'est lui qui
    rend une collecte rejouable hors ligne.

    Le réseau se fait donc en premier, base fermée ; l'écriture ensuite.
    """
    moisson: list[tuple[str, dict]] = []
    for insee in communes_du_step("sispea"):
        for competence in COMPETENCES:
            for ligne in services_hubeau(insee, competence):
                moisson.append((competence, ligne))
            time.sleep(REQUEST_DELAY)
    return moisson


def completer_par_millesimes(conn, connus: dict[str, str], releve: dict) -> str | None:
    """Ajoute les exercices que Hub'Eau ne publie pas, et NE FAIT PAS ÉCHOUER.

    Ces extractions sont un COMPLÉMENT : elles demandent un téléchargement
    national, `bsdtar` pour ouvrir une archive 7z, et `xlrd` pour l'un des
    millésimes. Rien de tout cela n'est acquis sur la machine qui collecte, et
    leur absence ne doit pas emporter la série que Hub'Eau vient de rendre.

    ⚠️ Une dégradation qui ne se dit pas est un défaut, pas une souplesse : la
    cause est imprimée, et rendue à l'appelant pour qu'il l'annonce.
    """
    try:
        for competence in COMPETENCES:
            interessants = {c for c, comp in connus.items() if comp == competence}
            if not interessants:
                continue
            for annee, url in sorted(_archives(competence).items()):
                exercice = millesime(competence, annee, url)
                if not exercice:
                    continue
                releve["millesimes"] += 1
                for code in interessants & set(exercice):
                    fiche = exercice[code]
                    _ecrire_service(conn, code, competence, fiche)
                    for indicateur, valeur in fiche["indicateurs"].items():
                        if _ecrire_indicateur(conn, code, annee, competence,
                                              indicateur, valeur, "ofb"):
                            releve["mesures"] += 1
                            releve["annees"].add(annee)
    except Exception as erreur:  # noqa: BLE001 — le complément échoue, la série reste
        motif = f"{type(erreur).__name__}: {erreur}"
        print(f"  [sispea] exercices récents indisponibles — {motif}")
        print("           la série s'arrête à ce que Hub'Eau publie (2019)")
        releve["millesimes_erreur"] = motif[:300]
        return motif
    return None


def run_sispea(avec_millesimes: bool = True) -> dict:
    releve = {"services": 0, "mesures": 0, "millesimes": 0, "annees": set()}
    moisson = _moisson_hubeau()
    with get_conn() as conn:
        ensure_tables(conn)
        run_id = log_run_start(conn, "sispea", None)
        try:
            connus: dict[str, str] = {}
            for competence, ligne in moisson:
                trouve = _identite(ligne, competence)
                if not trouve:
                    continue
                code, identite = trouve
                if code not in connus:
                    connus[code] = competence
                    releve["services"] += 1
                _ecrire_service(conn, code, competence, identite)
                annee = int(ligne.get("annee") or 0)
                if not annee:
                    continue
                for indicateur, valeur in (ligne.get("indicateurs") or {}).items():
                    if indicateur not in INDICATEURS[competence]:
                        continue
                    propre = nombre(valeur)
                    if propre is None or (propre == 0 and indicateur in INDICATEURS_SANS_ZERO):
                        continue
                    if _ecrire_indicateur(conn, code, annee, competence,
                                          indicateur, propre, "hubeau"):
                        releve["mesures"] += 1
                        releve["annees"].add(annee)

            if avec_millesimes and connus:
                completer_par_millesimes(conn, connus, releve)
            conn.commit()
        except Exception as erreur:
            log_run_end(conn, run_id, "error", None, None, error=str(erreur)[:300])
            raise
        # `empty` n'est pas un échec : une commune peut n'avoir aucun service
        # déclaré à l'observatoire, qui est alimenté par les services eux-mêmes.
        log_run_end(conn, run_id, "ok" if releve["services"] else "empty",
                    releve["services"], releve["mesures"])
    return releve


def main() -> int:
    parseur = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parseur.add_argument("--stats", action="store_true",
                         help="compte ce qui est en base, sans rien collecter")
    parseur.add_argument("--sans-millesimes", action="store_true",
                         help="Hub'Eau seul : pas de téléchargement national")
    arguments = parseur.parse_args()

    if arguments.stats:
        with get_conn(read_only=True) as conn:
            for ligne in conn.execute(
                    "SELECT s.competence, s.code_service, s.nom, s.mode_gestion,"
                    " MIN(i.annee), MAX(i.annee), COUNT(*)"
                    " FROM sispea_services s LEFT JOIN sispea_indicateurs i"
                    " ON i.code_service = s.code_service"
                    " GROUP BY s.code_service ORDER BY s.competence, s.code_service"):
                comp, code, nom, gestion, debut, fin, combien = ligne
                print(f"  {comp:4} {code:>8} {str(nom)[:34]:36} {str(gestion or ''):11}"
                      f" {debut}-{fin}  {combien} mesures")
        return 0

    releve = run_sispea(avec_millesimes=not arguments.sans_millesimes)
    annees = sorted(releve["annees"])
    print(f"SISPEA — {COMMUNE_INSEE} : {releve['services']} service(s), "
          f"{releve['mesures']} mesure(s) neuve(s), {releve['millesimes']} millésime(s) lu(s)"
          + (f", exercices {annees[0]}-{annees[-1]}" if annees else ""))
    if releve.get("millesimes_erreur"):
        print(f"  ⚠ exercices récents non collectés : {releve['millesimes_erreur']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
