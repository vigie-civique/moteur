"""
dpe.py — État énergétique du parc de logements (ADEME), en agrégats seulement.

Les diagnostics de performance énergétique sont ouverts et géolocalisés À
L'ADRESSE. Agrégés à la commune, ils donnent la part de passoires thermiques :
un chiffre local, concret, relié aux aides que la commune relaie ou non.

🔴 CE COLLECTEUR NE TÉLÉCHARGE JAMAIS UNE LIGNE DE DPE.

Une ligne, c'est l'adresse d'un logement, sa surface, son mode de chauffage et
sa note énergétique — le dossier de quelqu'un. Rien n'oblige à la faire entrer
en base pour publier une part : l'API sait compter côté serveur (`values_agg`).
Le collecteur ne demande donc que des DÉNOMBREMENTS. Ce qu'il ne rapatrie pas
ne peut pas fuir, et `tests/test_dpe.py` refuse toute requête qui ramènerait des
lignes — la garde est structurelle, pas une intention.

─────────────────────────────────────────────────────────────────────────────
CE QU'ON NE COMPARE PAS

La réforme du 1er juillet 2021 a changé la méthode (5 usages, calcul 3CL-2021,
fin du calcul sur factures). Les jeux d'AVANT (`dpe-france`, 10,7 millions de
lignes) et d'APRÈS ne mesurent pas la même chose : mis bout à bout ils
donneraient une « évolution » qui ne serait que le changement de règle. Seuls
les jeux postérieurs à la réforme sont collectés, et le champ `jeu` dit lequel.

⚠️ ET UN DPE SUR TRENTE N'EST RATTACHÉ À AUCUNE COMMUNE. Mesuré le 02/09/2026 :
491 487 lignes du jeu des logements existants (3,2 %) n'ont pas de
`code_insee_ban` — l'adresse n'a pas été reconnue par la base adresse
nationale. Un filtre communal ne peut pas les voir. Le collecteur mesure donc,
par le CODE POSTAL, combien de diagnostics du secteur restent sans commune :
c'est ce chiffre qui dit si la part publiée porte sur tout le parc ou sur une
partie. Sur le code postal de la commune d'essai, il vaut zéro.

Source : `data.ademe.fr` (data-fair), sans clé.

Usage :
  python3 -m collectors.dpe
  python3 -m collectors.dpe --insee 30140
  python3 -m collectors.dpe --stats
"""
import argparse
import time
import urllib.parse

from .archive import fetch_json
from .config import COMMUNES, REQUEST_DELAY, communes_du_step
from .db import get_conn, transaction

SOURCE = "ademe-dpe"
API = "https://data.ademe.fr/data-fair/api/v1/datasets"

# Les jeux POSTÉRIEURS à la réforme de juillet 2021, et eux seuls.
JEUX = {
    "existant":  ("dpe03existant",  "Logements existants"),
    "neuf":      ("dpe02neuf",      "Logements neufs"),
    "tertiaire": ("dpe01tertiaire", "Bâtiments tertiaires"),
}

# Ce qu'on fait compter, et sous quel nom on le range. `type_batiment` n'existe
# pas dans le jeu tertiaire : une dimension absente rend une agrégation vide,
# qu'on distingue d'une absence de diagnostic (cf. plus bas).
DIMENSIONS = {
    "etiquette_dpe":                    "Étiquette énergie",
    "etiquette_ges":                    "Étiquette climat (GES)",
    "type_batiment":                    "Type de bâtiment",
    "periode_construction":             "Période de construction",
    "type_energie_principale_chauffage": "Énergie de chauffage",
}

# Les deux notes qui font une « passoire thermique » au sens de la loi Climat
# et résilience (art. L173-2 CCH) : F et G.
PASSOIRES = ("F", "G")


def _agreger(jeu: str, champ: str, filtre: str) -> list[tuple[str, int]]:
    """Dénombrement par modalité — le serveur compte, on ne rapatrie rien d'autre."""
    url = f"{API}/{jeu}/values_agg?" + urllib.parse.urlencode({
        "field": champ, "qs": filtre, "agg_size": 50, "size": 0})
    data = fetch_json(url, source=SOURCE, timeout=90)
    return [(str(a.get("value")), int(a.get("total") or 0))
            for a in data.get("aggs", []) if a.get("value") is not None]


def _compter(jeu: str, filtre: str) -> int:
    """Nombre de diagnostics, sans en ramener un seul (`size=0`)."""
    url = f"{API}/{jeu}/lines?" + urllib.parse.urlencode({"qs": filtre, "size": 0})
    return int(fetch_json(url, source=SOURCE, timeout=90).get("total") or 0)


def ensure_tables(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dpe_agregats (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            insee      TEXT NOT NULL,
            jeu        TEXT NOT NULL,   -- existant | neuf | tertiaire
            dimension  TEXT NOT NULL,
            modalite   TEXT NOT NULL,
            nombre     INTEGER,
            releve_le  TEXT DEFAULT (datetime('now')),
            UNIQUE(insee, jeu, dimension, modalite)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dpe_couverture (
            insee          TEXT NOT NULL,
            jeu            TEXT NOT NULL,
            diagnostics    INTEGER,   -- rattachés à la commune
            secteur_cp     INTEGER,   -- tout le code postal, communes voisines comprises
            sans_commune   INTEGER,   -- du code postal, sans code INSEE : invisibles
            code_postal    TEXT,
            releve_le      TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (insee, jeu)
        )
    """)
    conn.commit()


def import_commune(insee: str, commune_nom: str, code_postal: str | None) -> int:
    """Interroge d'abord, écrit ensuite.

    🔴 L'ordre n'est pas cosmétique : `fetch_json` archive chaque réponse dans la
    base, avec sa propre connexion. Tenir une transaction ouverte pendant les
    appels réseau lui laissait la base VERROUILLÉE — l'archivage était sauté, en
    disant seulement `[archive][skip] database is locked` au milieu du journal.
    Une source rejouable depuis `raw_documents` ne l'est que si l'archive a été
    écrite.
    """
    filtre = f'code_insee_ban:"{insee}"'
    releves, couvertures, resume = [], [], []
    for cle, (jeu, _libelle) in JEUX.items():
        total = _compter(jeu, filtre)
        # Le code postal sert de témoin : il englobe la commune et ses voisines,
        # et permet de voir les diagnostics que la BAN n'a rattachés à aucune
        # commune. Sans ce témoin, un parc mal géocodé donnerait une part
        # calculée sur un dénominateur amputé, sans que rien ne le dise.
        secteur = orphelins = None
        if code_postal:
            time.sleep(REQUEST_DELAY)
            secteur = _compter(jeu, f'code_postal_brut:"{code_postal}"')
            time.sleep(REQUEST_DELAY)
            orphelins = _compter(
                jeu, f'code_postal_brut:"{code_postal}" AND NOT _exists_:code_insee_ban')
        couvertures.append((insee, cle, total, secteur, orphelins, code_postal))
        if not total:
            continue
        for champ in DIMENSIONS:
            time.sleep(REQUEST_DELAY)
            try:
                paires = _agreger(jeu, champ, filtre)
            except Exception as e:                      # noqa: BLE001
                # Une dimension absente du jeu (`type_batiment` dans le
                # tertiaire) n'est pas une panne de collecte : on le dit et on
                # continue, plutôt que d'inscrire un vide qui se lirait comme
                # « aucun bâtiment ».
                print(f"    ↳ {jeu}/{champ} : {e}")
                continue
            for modalite, n in paires:
                releves.append((insee, cle, champ, modalite, n))
        resume.append(f"{cle} {total}")

    lignes_ecrites = 0
    with transaction() as conn:
        ensure_tables(conn)
        for c in couvertures:
            conn.execute(
                "INSERT INTO dpe_couverture"
                " (insee,jeu,diagnostics,secteur_cp,sans_commune,code_postal,releve_le)"
                " VALUES (?,?,?,?,?,?,datetime('now'))"
                " ON CONFLICT(insee,jeu) DO UPDATE SET diagnostics=excluded.diagnostics,"
                " secteur_cp=excluded.secteur_cp, sans_commune=excluded.sans_commune,"
                " code_postal=excluded.code_postal, releve_le=excluded.releve_le", c)
        for r in releves:
            conn.execute(
                "INSERT INTO dpe_agregats"
                " (insee,jeu,dimension,modalite,nombre,releve_le)"
                " VALUES (?,?,?,?,?,datetime('now'))"
                " ON CONFLICT(insee,jeu,dimension,modalite) DO UPDATE SET"
                " nombre=excluded.nombre, releve_le=excluded.releve_le", r)
            lignes_ecrites += 1

    part = part_passoires(insee, "existant")
    print(f"  [dpe] {commune_nom} — {', '.join(resume) or 'aucun diagnostic'}"
          + (f" ; passoires (F+G) {part:.1f} %" if part is not None else ""))
    return lignes_ecrites


def part_passoires(insee: str, jeu: str = "existant") -> float | None:
    """Part des étiquettes F et G, ou None si rien n'a été relevé."""
    conn = get_conn(read_only=True)
    try:
        lignes = conn.execute(
            "SELECT modalite, nombre FROM dpe_agregats"
            " WHERE insee=? AND jeu=? AND dimension='etiquette_dpe'",
            (insee, jeu)).fetchall()
    finally:
        conn.close()
    total = sum(r["nombre"] or 0 for r in lignes)
    if not total:
        return None
    return 100 * sum(r["nombre"] or 0 for r in lignes
                     if r["modalite"] in PASSOIRES) / total


def run(insee: str | None = None) -> int:
    cibles = [insee] if insee else communes_du_step("dpe")
    total = 0
    for i, code in enumerate(cibles):
        fiche = COMMUNES.get(code, {})
        nom = fiche.get("nom", code)
        try:
            total += import_commune(code, nom, fiche.get("cp"))
        except Exception as e:                          # noqa: BLE001
            print(f"  [dpe] {nom} — ÉCHEC : {e}")
        if i < len(cibles) - 1:
            time.sleep(REQUEST_DELAY)
    print(f"[dpe] {total} agrégat(s) sur {len(cibles)} commune(s)")
    return total


def stats():
    conn = get_conn()
    ensure_tables(conn)
    for r in conn.execute(
            "SELECT insee, jeu, diagnostics, secteur_cp, sans_commune, code_postal"
            " FROM dpe_couverture ORDER BY insee, jeu"):
        alerte = ""
        if r["sans_commune"]:
            alerte = (f"  ⚠️ {r['sans_commune']} diagnostic(s) du {r['code_postal']}"
                      " sans commune")
        print(f"  {r['insee']} {r['jeu']:<10} {r['diagnostics'] or 0:>6}"
              f" / {r['secteur_cp'] or 0:>6} sur le code postal{alerte}")
    for r in conn.execute(
            "SELECT insee, jeu, dimension, modalite, nombre FROM dpe_agregats"
            " WHERE dimension='etiquette_dpe' ORDER BY insee, jeu, modalite"):
        print(f"    {r['insee']} {r['jeu']:<10} {r['modalite']:<3} {r['nombre']:>5}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--insee", help="une seule commune")
    p.add_argument("--stats", action="store_true")
    a = p.parse_args()
    if a.stats:
        stats()
    else:
        run(a.insee)
