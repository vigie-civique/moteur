"""education.py — Écoles, collèges et lycées (annuaire de l'Éducation nationale).

Les établissements scolaires manquaient au répertoire. Ce n'est pas un oubli
sans conséquence : à Lasalle, le complexe scolaire du Colombier fait l'objet
d'une délibération d'attribution de maîtrise d'œuvre en février 2025, et
l'équipement concerné n'existait comme entité nulle part. Un acte qui porte sur
un bâtiment public ne peut être rattaché à rien tant que le bâtiment n'est pas
recensé — et une école est, avec la mairie, le premier équipement public d'une
commune rurale.

Source : `fr-en-annuaire-education` sur data.education.gouv.fr (Opendatasoft
v2.1, sans clé). Elle porte l'UAI — l'identifiant national d'un établissement,
stable et opposable, le pendant du SIREN pour l'école. C'est lui qui sert de
clé de déduplication, jamais le nom : « Ecole primaire » est le libellé de des
milliers d'établissements, et deux communes voisines en portent le même.

Entités créées en `service`, catégorie `education`. Elles sont PUBLIQUES par
nature — un établissement scolaire n'a pas de vie privée — mais on ne collecte
ni effectifs nominatifs ni personnel : l'annuaire n'en publie pas, et la fiche
s'en tient à ce qu'il donne.

Usage :
  python3 -m collectors.education
  python3 -m collectors.education --insee 30140
  python3 -m collectors.education --stats
"""
import argparse
import json
import urllib.parse

from .archive import fetch_json
from .config import COMMUNES, COMMUNES_INSEE, REQUEST_DELAY
from .db import get_conn, transaction, upsert_entity

API = ("https://data.education.gouv.fr/api/explore/v2.1/"
       "catalog/datasets/fr-en-annuaire-education/records")

# Un établissement FERMÉ reste dans l'annuaire, avec `etat = FERME`. On le
# collecte : une école fermée en 2019 apparaît dans les délibérations qui l'ont
# fermée, et sa fiche est ce qui rend ces actes lisibles. C'est la publication
# qui décidera de son sort, pas la collecte — cf. `actif` dans le snapshot.
ETAT_OUVERT = "OUVERT"


def fetch_commune(insee: str) -> list[dict]:
    """Établissements d'une commune. La source pagine à 100."""
    resultats: list[dict] = []
    offset = 0
    while True:
        params = urllib.parse.urlencode({
            "where": f'code_commune="{insee}"',
            "limit": 100,
            "offset": offset,
        })
        data = fetch_json(f"{API}?{params}", source="education", timeout=20)
        lot = data.get("results") or []
        resultats.extend(lot)
        offset += len(lot)
        if len(lot) < 100 or offset >= (data.get("total_count") or 0):
            break
    return resultats


def _coord(valeur):
    try:
        return float(valeur) if valeur not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _nom_lisible(etab: dict) -> str:
    """Un nom qui désigne l'établissement, pas sa catégorie.

    L'annuaire nomme « Ecole primaire » la plupart des écoles publiques : tel
    quel, le répertoire d'une intercommunalité de quinze communes contiendrait
    quinze « Ecole primaire » indiscernables, et l'index unique (type, name)
    n'en garderait qu'une. La commune est donc accolée quand le nom ne la porte
    pas déjà — c'est ainsi qu'on la nomme sur place.
    """
    nom = (etab.get("nom_etablissement") or "").strip()
    commune = (etab.get("nom_commune") or "").strip()
    if not nom:
        return f"Établissement scolaire — {commune}".strip(" —")
    if commune and commune.lower() not in nom.lower():
        return f"{nom} — {commune}"
    return nom


def ensure_table(conn):
    """La fiche d'extension. `services` ne porte pas l'UAI ni les effectifs."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS etablissements_scolaires (
            entity_id    INTEGER PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
            uai          TEXT UNIQUE,
            nature       TEXT,   -- libellé : école élémentaire, collège…
            secteur      TEXT,   -- Public | Privé
            etat         TEXT,   -- OUVERT | FERME
            ouverture    TEXT,
            fermeture    TEXT,
            eleves       INTEGER,
            telephone    TEXT,
            courriel     TEXT,
            site         TEXT,
            raw_data     TEXT,
            created_at   TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_etab_uai"
                 " ON etablissements_scolaires(uai)")
    conn.commit()


def _importer(conn, etab: dict, commune_nom: str) -> tuple[int, bool]:
    """(entity_id, créé). Déduplique par UAI, jamais par nom."""
    uai = (etab.get("identifiant_de_l_etablissement") or "").strip()
    connue = conn.execute(
        "SELECT entity_id FROM etablissements_scolaires WHERE uai=?", (uai,)
    ).fetchone() if uai else None

    nom = _nom_lisible(etab)
    adresse = ", ".join(filter(None, [
        (etab.get("adresse_1") or "").strip(),
        " ".join(filter(None, [(etab.get("code_postal") or "").strip(),
                               (etab.get("nom_commune") or "").strip()])),
    ]))

    if connue:
        eid, cree = connue["entity_id"], False
        # Ne jamais renommer sur une recollecte : l'atelier a pu corriger le
        # libellé, et l'annuaire ne le saura pas.
        for champ, valeur in (("address", adresse or None),
                              ("lat", _coord(etab.get("latitude"))),
                              ("lng", _coord(etab.get("longitude")))):
            conn.execute(
                f"UPDATE entities SET {champ}=? WHERE id=? AND ({champ} IS NULL)",
                (valeur, eid))
    else:
        eid = upsert_entity(
            conn,
            type="service",
            name=nom,
            short_name=uai or None,
            lat=_coord(etab.get("latitude")),
            lng=_coord(etab.get("longitude")),
            address=adresse or None,
            confidence="verified",
            commune=commune_nom,
        )
        cree = True

    conn.execute(
        "INSERT OR IGNORE INTO services (entity_id, category, operator)"
        " VALUES (?,?,?)",
        (eid, "education", etab.get("ministere_tutelle")))
    conn.execute(
        "INSERT OR IGNORE INTO etablissements_scolaires"
        " (entity_id,uai,nature,secteur,etat,ouverture,fermeture,eleves,"
        "  telephone,courriel,site,raw_data)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (eid, uai or None, etab.get("libelle_nature"),
         etab.get("statut_public_prive"), etab.get("etat"),
         etab.get("date_ouverture"), etab.get("date_fermeture"),
         etab.get("nombre_d_eleves"), etab.get("telephone"),
         etab.get("mail"), etab.get("web"),
         json.dumps(etab, ensure_ascii=False)))
    # L'état et les effectifs CHANGENT d'une rentrée à l'autre : ce sont les
    # deux seuls champs qu'une recollecte doit rafraîchir.
    conn.execute(
        "UPDATE etablissements_scolaires SET etat=?, eleves=?, fermeture=?"
        " WHERE entity_id=?",
        (etab.get("etat"), etab.get("nombre_d_eleves"),
         etab.get("date_fermeture"), eid))
    return eid, cree


def import_commune(insee: str, commune_nom: str) -> int:
    etablissements = fetch_commune(insee)
    if not etablissements:
        print(f"  [education] {commune_nom} — aucun établissement recensé")
        return 0
    crees = 0
    with transaction() as conn:
        ensure_table(conn)
        for etab in etablissements:
            _, cree = _importer(conn, etab, commune_nom)
            crees += cree
    ouverts = sum(1 for e in etablissements if e.get("etat") == ETAT_OUVERT)
    print(f"  [education] {commune_nom} — {len(etablissements)} établissement(s), "
          f"{ouverts} ouvert(s), {crees} créé(s)")
    return len(etablissements)


def run(insee: str | None = None) -> int:
    import time
    cibles = [insee] if insee else COMMUNES_INSEE
    total = 0
    for i, code in enumerate(cibles):
        nom = COMMUNES.get(code, {}).get("nom", code)
        try:
            total += import_commune(code, nom)
        except Exception as e:                      # noqa: BLE001
            # Une commune qui échoue n'emporte pas les quatorze autres, mais
            # elle se dit : un total silencieusement amputé est pire qu'un zéro.
            print(f"  [education] {nom} — ÉCHEC : {e}")
        if i < len(cibles) - 1:
            time.sleep(REQUEST_DELAY)
    print(f"[education] {total} établissements scolaires sur "
          f"{len(cibles)} commune(s)")
    return total


def stats():
    conn = get_conn()
    ensure_table(conn)
    lignes = conn.execute("""
        SELECT e.commune, s.etat, s.nature, COUNT(*) n
        FROM etablissements_scolaires s JOIN entities e ON e.id = s.entity_id
        GROUP BY 1, 2, 3 ORDER BY 1, 3
    """).fetchall()
    for r in lignes:
        print(f"  {r['commune'] or '?':<28} {r['etat'] or '?':<8} "
              f"{r['nature'] or '?':<34} {r['n']}")
    print(f"  — {sum(r['n'] for r in lignes)} établissements")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--insee", help="une seule commune")
    p.add_argument("--stats", action="store_true")
    a = p.parse_args()
    if a.stats:
        stats()
    else:
        run(a.insee)
