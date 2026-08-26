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
import math
import re
import unicodedata
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


# ── Ne pas créer à côté de ce qui existe déjà ────────────────────────────────
#
# OpenStreetMap cartographie les écoles depuis longtemps : à Lasalle, « École
# maternelle » et « École élémentaire du Colombier » étaient en base bien avant
# ce collecteur, à 22 et 41 mètres de la position que donne l'Éducation
# nationale. Créer une troisième fiche « Ecole primaire — Lasalle » aurait
# fabriqué le doublon qu'on passe nos journées à défaire.
#
# Le rapprochement se fait sur DEUX signaux indépendants, jamais sur le nom
# seul : la position (deux sources qui pointent le même bâtiment) et la nature
# (une maternelle n'est pas une élémentaire, même à vingt mètres). Sans accord
# des deux, on crée — un doublon se répare, une fusion abusive écrase.
RAYON_M = 250

MOTS_ECOLE = ("ecole", "college", "lycee", "groupe scolaire", "maternelle")

# Ce que le libellé de nature de l'annuaire annonce, et le mot qu'on cherche
# dans le nom d'une fiche existante.
NIVEAUX = (
    ("MATERNELLE", ("maternelle",)),
    ("ELEMENTAIRE", ("elementaire", "primaire")),
    ("PRIMAIRE", ("primaire", "elementaire")),
    ("COLLEGE", ("college",)),
    ("LYCEE", ("lycee",)),
)


def _sans_accent(texte: str | None) -> str:
    t = unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def _distance_m(lat1, lng1, lat2, lng2) -> float | None:
    if None in (lat1, lng1, lat2, lng2):
        return None
    p = math.pi / 180
    a = (0.5 - math.cos((lat2 - lat1) * p) / 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lng2 - lng1) * p)) / 2)
    return 12742000 * math.asin(math.sqrt(max(0.0, a)))


def _niveaux_attendus(etab: dict) -> tuple[str, ...]:
    nature = (etab.get("libelle_nature") or "").upper()
    for cle, mots in NIVEAUX:
        if cle in nature:
            return mots
    return ()


def candidat_existant(conn, etab: dict, commune_nom: str) -> int | None:
    """Fiche scolaire déjà en base qui désigne le même établissement, ou None.

    Position ET nature doivent concorder. Une fiche déjà porteuse d'un UAI est
    écartée : elle appartient à un autre établissement de l'annuaire.
    """
    lat, lng = _coord(etab.get("latitude")), _coord(etab.get("longitude"))
    if lat is None or lng is None:
        return None
    attendus = _niveaux_attendus(etab)
    if not attendus:
        return None

    meilleur = None
    for r in conn.execute(
            "SELECT e.id, e.name, e.lat, e.lng FROM entities e"
            " LEFT JOIN etablissements_scolaires s ON s.entity_id = e.id"
            " WHERE e.type='service' AND e.commune=? AND s.entity_id IS NULL"
            "   AND e.lat IS NOT NULL AND e.lng IS NOT NULL", (commune_nom,)):
        nom = _sans_accent(r["name"])
        if not any(mot in nom for mot in MOTS_ECOLE):
            continue
        if not any(mot in nom for mot in attendus):
            continue
        d = _distance_m(lat, lng, r["lat"], r["lng"])
        if d is not None and d <= RAYON_M and (meilleur is None or d < meilleur[0]):
            meilleur = (d, r["id"], r["name"])
    if meilleur:
        print(f"    ↳ rapproché de « {meilleur[2]} » (#{meilleur[1]}, "
              f"{meilleur[0]:.0f} m) — pas de nouvelle fiche")
        return meilleur[1]
    return None


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
    # Rien sous cet UAI : peut-être une autre source a-t-elle déjà cartographié
    # l'établissement. On l'adopte plutôt que de créer une fiche de plus.
    adopte = None if connue else candidat_existant(conn, etab, commune_nom)

    nom = _nom_lisible(etab)
    adresse = ", ".join(filter(None, [
        (etab.get("adresse_1") or "").strip(),
        " ".join(filter(None, [(etab.get("code_postal") or "").strip(),
                               (etab.get("nom_commune") or "").strip()])),
    ]))

    if connue or adopte:
        eid, cree = (connue["entity_id"] if connue else adopte), False
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
