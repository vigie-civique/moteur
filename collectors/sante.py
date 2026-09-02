"""
sante.py — Établissements sanitaires et médico-sociaux (FINESS).

Pharmacie, cabinet de radiologie, EHPAD, laboratoire, centre de santé, service
d'aide à domicile : ce que la commune compte en matière de soin, et qui le
porte. Un acte du conseil qui parle de l'EHPAD ne peut être rattaché à rien tant
que l'EHPAD n'existe comme fiche nulle part — c'est le même manque que celui des
écoles, réglé par `education.py`, et le même remède.

Le numéro FINESS joue ici le rôle de l'UAI : identifiant national, stable, il
sert de clé de déduplication. Jamais le nom — « PHARMACIE DU CENTRE » est le
libellé de plusieurs centaines d'officines.

─────────────────────────────────────────────────────────────────────────────
CE QUE FINESS EST, ET CE QU'IL N'EST PAS

FINESS recense des ÉTABLISSEMENTS, pas des professionnels. Le médecin qui
consulte dans son cabinet n'y est pas ; la pharmacie, le laboratoire et l'EHPAD
y sont. Le décompte des professionnels installés, lui, vient de la base
permanente des équipements — `collectors/equipements.py`, domaine D. Les deux se
complètent et ne se remplacent pas : dire « le désert médical se démontre » avec
FINESS seul reviendrait à ne compter que les murs.

⚠️ LES COORDONNÉES SONT EN LAMBERT 93, PAS EN DEGRÉS. Le fichier livre deux
sortes de lignes : `structureet` (l'établissement) puis `geolocalisation` (ses
coordonnées PROJETÉES, dans le système du territoire — Lambert 93 en métropole,
UTM outre-mer). Les prendre pour des degrés poserait les fiches au large du
golfe de Guinée. La conversion existe déjà dans `geocoder.l93_to_wgs84` ; hors
métropole, le système n'est pas Lambert 93 et la fiche est écrite SANS position
plutôt qu'avec une fausse.

Le code INSEE ne figure pas tel quel : FINESS écrit le département et le code
commune sur trois chiffres, séparément. C'est leur concaténation qui donne le
code INSEE, y compris en Corse (`2A` + `004`).

Source : `data.gouv.fr`, extraction FINESS du ministère chargé de la santé.
Fichier national de 48 Mo, déposé au magasin partagé : une seule copie sert
toutes les instances de la machine.

Usage :
  python3 -m collectors.sante
  python3 -m collectors.sante --insee 30140
  python3 -m collectors.sante --stats
"""
import argparse
import csv
import json
import math
import re
import unicodedata
import urllib.request

from .archive import HEADERS, archive_fetch, fetch_json
from .config import COMMUNES, NATIONAL_STORE, communes_du_step
from .db import get_conn, transaction, upsert_entity
from .geocoder import l93_to_wgs84
from .national_store import copier_atomiquement, est_frais

SOURCE = "finess"
DATASET = "finess-extraction-du-fichier-des-etablissements"
CACHE = NATIONAL_STORE / "finess"
FICHIER = CACHE / "finess-etablissements.csv"

# Le ministère dépose une extraction par mois environ.
CACHE_JOURS = 30

# Colonnes du type `structureet`, dans l'ordre du fichier. Nommées ici parce que
# le fichier n'a PAS d'en-tête : un index nu dans le code serait illisible et
# indéfendable au premier changement de format.
STRUCTURE = {
    "finess": 1, "finess_ej": 2, "raison_sociale": 3, "raison_sociale_longue": 4,
    "num_voie": 7, "type_voie": 8, "voie": 9, "compl_voie": 10, "lieu_dit": 11,
    "commune": 12, "departement": 13, "acheminement": 15, "telephone": 16,
    "categorie": 18, "categorie_libelle": 19,
    "agregat": 20, "agregat_libelle": 21,
    "siret": 22, "ape": 23, "sph": 26, "sph_libelle": 27,
    "date_ouverture": 28, "date_autorisation": 29, "date_maj": 30,
}
GEO = {"finess": 1, "x": 2, "y": 3, "systeme": 4}

# Seul le Lambert 93 est converti — cf. l'avertissement du préambule.
LAMBERT93 = "EPSG:2154"

RAYON_M = 250
MOTS_SANTE = ("pharmacie", "medecin", "sante", "hopital", "clinique", "ehpad",
              "maison de retraite", "laboratoire", "cabinet", "infirmier",
              "dentaire", "kine", "creche", "foyer")


def _telecharger() -> None:
    """Dépose l'extraction nationale dans le magasin partagé, si besoin.

    L'URL porte la date de dépôt : elle est LUE dans la fiche du jeu, jamais
    écrite ici. En flux, jamais en mémoire — 48 Mo chargés d'un bloc sur un
    petit serveur, c'est autant de pris sur une génération qui tourne à côté.
    """
    if est_frais(FICHIER, CACHE_JOURS):
        return
    fiche = fetch_json(f"https://www.data.gouv.fr/api/1/datasets/{DATASET}/",
                       source=SOURCE, timeout=60)
    url = None
    for res in fiche.get("resources", []):
        if (res.get("format") or "").lower() == "csv" and "olocalis" in (res.get("title") or ""):
            url = res.get("url")
            break
    if not url:
        raise RuntimeError("FINESS : pas d'extraction géolocalisée au catalogue")
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=600) as r:
        copier_atomiquement(FICHIER, r)
        archive_fetch(SOURCE, url, b"", content_type="text/csv", http_status=r.status)
    print(f"  [sante] extraction nationale déposée : {FICHIER.name}")


def _insee(ligne: list[str]) -> str:
    """Département + code commune sur 3 chiffres → code INSEE."""
    dep = (ligne[STRUCTURE["departement"]] or "").strip()
    com = (ligne[STRUCTURE["commune"]] or "").strip()
    return f"{dep}{com.zfill(3)}" if dep and com else ""


def lire(chemin, codes: set[str]) -> tuple[dict, dict]:
    """(établissements, positions) pour les communes demandées.

    Deux passes dans le même parcours : les `structureet` retenus d'abord, les
    `geolocalisation` ensuite — le fichier place toutes les secondes après
    toutes les premières.
    """
    etablissements: dict[str, dict] = {}
    positions: dict[str, tuple] = {}
    with open(chemin, encoding="utf-8", newline="") as f:
        for ligne in csv.reader(f, delimiter=";"):
            if not ligne:
                continue
            if ligne[0] == "structureet" and len(ligne) > 30:
                if _insee(ligne) in codes:
                    fiche = {cle: (ligne[i] or "").strip()
                             for cle, i in STRUCTURE.items() if i < len(ligne)}
                    fiche["insee"] = _insee(ligne)
                    etablissements[fiche["finess"]] = fiche
            elif ligne[0] == "geolocalisation" and len(ligne) > 4:
                num = (ligne[GEO["finess"]] or "").strip()
                if num in etablissements:
                    positions[num] = (ligne[GEO["x"]], ligne[GEO["y"]],
                                      ligne[GEO["systeme"]])
    return etablissements, positions


def coordonnees(x: str, y: str, systeme: str) -> tuple[float | None, float | None]:
    """(lat, lng) en degrés, ou (None, None) hors Lambert 93."""
    if LAMBERT93 not in (systeme or ""):
        return None, None
    try:
        return l93_to_wgs84(float(x), float(y))
    except (TypeError, ValueError):
        return None, None


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


def _adresse(fiche: dict) -> str:
    voie = " ".join(x for x in (fiche.get("num_voie"), fiche.get("type_voie"),
                                fiche.get("voie")) if x)
    return ", ".join(x for x in (voie, fiche.get("lieu_dit"),
                                 fiche.get("acheminement")) if x)


def candidat_existant(conn, fiche: dict, lat, lng, commune_nom: str) -> int | None:
    """Fiche de santé déjà en base qui désigne le même lieu, ou None.

    Même règle que pour les écoles : position ET vocabulaire doivent concorder.
    OpenStreetMap cartographie les pharmacies depuis longtemps — créer une
    seconde fiche à quarante mètres de la première fabriquerait le doublon qu'on
    passe des journées à défaire. Une fiche portant déjà un numéro FINESS est
    écartée : elle appartient à un autre établissement.
    """
    if lat is None or lng is None:
        return None
    meilleur = None
    for r in conn.execute(
            "SELECT e.id, e.name, e.lat, e.lng FROM entities e"
            " LEFT JOIN etablissements_sante s ON s.entity_id = e.id"
            " WHERE e.type='service' AND e.commune=? AND s.entity_id IS NULL"
            "   AND e.lat IS NOT NULL AND e.lng IS NOT NULL", (commune_nom,)):
        nom = _sans_accent(r["name"])
        if not any(mot in nom for mot in MOTS_SANTE):
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS etablissements_sante (
            entity_id   INTEGER PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
            finess      TEXT UNIQUE,
            finess_ej   TEXT,      -- l'entité juridique qui le porte
            categorie   TEXT,
            categorie_libelle TEXT,
            agregat     TEXT,      -- regroupement (« Commerce de biens à usage médicaux »)
            siret       TEXT,
            ape         TEXT,
            sph_libelle TEXT,      -- statut : public, privé, privé non lucratif
            telephone   TEXT,
            date_ouverture TEXT,
            date_maj    TEXT,
            raw_data    TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sante_finess"
                 " ON etablissements_sante(finess)")
    conn.commit()


def _importer(conn, fiche: dict, lat, lng, commune_nom: str) -> bool:
    num = fiche.get("finess")
    connue = conn.execute(
        "SELECT entity_id FROM etablissements_sante WHERE finess=?", (num,)
    ).fetchone() if num else None
    adopte = None if connue else candidat_existant(conn, fiche, lat, lng, commune_nom)

    nom = (fiche.get("raison_sociale_longue") or fiche.get("raison_sociale")
           or f"Établissement de santé {num}")
    adresse = _adresse(fiche)

    if connue or adopte:
        eid, cree = (connue["entity_id"] if connue else adopte), False
        # Ne jamais renommer sur une recollecte : l'atelier a pu corriger le
        # libellé, et le registre national ne le saura pas.
        for champ, valeur in (("address", adresse or None), ("lat", lat), ("lng", lng)):
            conn.execute(
                f"UPDATE entities SET {champ}=? WHERE id=? AND ({champ} IS NULL)",
                (valeur, eid))
    else:
        eid = upsert_entity(conn, type="service", name=nom,
                            short_name=num or None, lat=lat, lng=lng,
                            address=adresse or None, confidence="verified",
                            commune=commune_nom)
        cree = True

    conn.execute("INSERT OR IGNORE INTO services (entity_id, category, operator)"
                 " VALUES (?,?,?)", (eid, "sante", fiche.get("sph_libelle")))
    conn.execute(
        "INSERT OR IGNORE INTO etablissements_sante"
        " (entity_id,finess,finess_ej,categorie,categorie_libelle,agregat,siret,"
        "  ape,sph_libelle,telephone,date_ouverture,date_maj,raw_data)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (eid, num or None, fiche.get("finess_ej"), fiche.get("categorie"),
         fiche.get("categorie_libelle"), fiche.get("agregat_libelle"),
         fiche.get("siret"), fiche.get("ape"), fiche.get("sph_libelle"),
         fiche.get("telephone"), fiche.get("date_ouverture"),
         fiche.get("date_maj"), json.dumps(fiche, ensure_ascii=False)))
    # La mise à jour du registre est le seul champ qu'une recollecte rafraîchit.
    conn.execute("UPDATE etablissements_sante SET date_maj=? WHERE entity_id=?",
                 (fiche.get("date_maj"), eid))
    return cree


def run(insee: str | None = None) -> int:
    _telecharger()
    codes = {insee} if insee else set(communes_du_step("sante"))
    etablissements, positions = lire(FICHIER, codes)
    if not etablissements:
        print(f"  [sante] aucun établissement FINESS sur {len(codes)} commune(s)")
        return 0
    crees = sans_position = 0
    with transaction() as conn:
        ensure_table(conn)
        for num, fiche in sorted(etablissements.items()):
            x, y, systeme = positions.get(num, (None, None, None))
            lat, lng = coordonnees(x, y, systeme) if x else (None, None)
            sans_position += int(lat is None)
            nom_commune = COMMUNES.get(fiche["insee"], {}).get("nom", fiche["insee"])
            crees += _importer(conn, fiche, lat, lng, nom_commune)
    print(f"  [sante] {len(etablissements)} établissement(s), {crees} créé(s)"
          + (f", {sans_position} sans position" if sans_position else ""))
    return len(etablissements)


def stats():
    conn = get_conn()
    ensure_table(conn)
    lignes = conn.execute("""
        SELECT e.commune, s.categorie_libelle, COUNT(*) n
          FROM etablissements_sante s JOIN entities e ON e.id = s.entity_id
         GROUP BY 1, 2 ORDER BY 1, 3 DESC
    """).fetchall()
    for r in lignes:
        print(f"  {r['commune'] or '?':<26} {r['categorie_libelle'] or '?':<46} {r['n']}")
    print(f"  — {sum(r['n'] for r in lignes)} établissement(s)")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--insee", help="une seule commune")
    p.add_argument("--stats", action="store_true")
    a = p.parse_args()
    if a.stats:
        stats()
    else:
        run(a.insee)
