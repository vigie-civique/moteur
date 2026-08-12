"""
pop_culture.py — Patrimoine protégé (data.culture.gouv.fr) pour le périmètre.

  - Immeubles protégés MH (base Mérimée) → entités 'place' + note (historique,
    datation, protection, lien notice POP) + couche places (patrimoine)
  - Objets mobiliers classés (base Palissy) → notes (0 dans le périmètre à ce jour,
    collecté quand même : future-proof)

Le patrimoine non protégé (inventaire général, filatures, temples…) passe par
le canal documentaire scripts/ingest_docs.py. Réponses archivées (source
culture-mh) et rejouables via scripts/reparse.py.

Usage :
  python3 -m collectors.pop_culture
  python3 -m collectors.pop_culture --insee 30236
  python3 -m collectors.pop_culture --stats
"""
import argparse
import json
import time
import urllib.parse

from .archive import fetch_json
from .config import COMMUNES, COMMUNES_INSEE, REQUEST_DELAY
from .db import get_conn, upsert_entity

API = "https://data.culture.gouv.fr/api/explore/v2.1/catalog/datasets"
DS_MH  = "liste-des-immeubles-proteges-au-titre-des-monuments-historiques"
DS_OBJ = "liste-des-objets-mobiliers-propriete-publique-classes-au-titre-des-monuments"
POP_NOTICE = "https://www.pop.culture.gouv.fr/notice/merimee/{ref}"


def _fetch(dataset: str, field: str, insee: str) -> list[dict]:
    where = urllib.parse.quote(f'{field}="{insee}"')
    url = f"{API}/{dataset}/records?where={where}&limit=100"
    data = fetch_json(url, source="culture-mh", timeout=30)
    return data.get("results", [])


def _first(v):
    return v[0] if isinstance(v, list) and v else v


def import_mh(conn, insee: str, results: list[dict]) -> int:
    commune = COMMUNES.get(insee, {}).get("nom")
    n = 0
    for r in results:
        name = (_first(r.get("titre_editorial_de_la_notice"))
                or _first(r.get("denomination_de_l_edifice")))
        if not name:
            continue
        ref = _first(r.get("reference")) or ""
        coords = r.get("coordonnees_au_format_wgs84") or {}
        eid = upsert_entity(conn,
            type="place", name=str(name).strip(),
            lat=coords.get("lat"), lng=coords.get("lon"),
            address=_first(r.get("lieudit")),
            confidence="verified", commune=commune)
        conn.execute(
            "INSERT OR IGNORE INTO places (entity_id, osm_category, osm_value, tags)"
            " VALUES (?, 'patrimoine', 'monument_historique', ?)",
            (eid, json.dumps({"reference": ref,
                              "protection": _first(r.get("nature_de_la_protection"))},
                             ensure_ascii=False)))
        exists = conn.execute(
            "SELECT id FROM entity_notes WHERE entity_id=? AND note LIKE ?",
            (eid, f"%{ref}%")).fetchone() if ref else None
        if not exists:
            parts = [f"Monument historique — {_first(r.get('nature_de_la_protection')) or 'protection MH'}"]
            for label, key in (("Datation", "datation_de_l_edifice"),
                               ("Protection", "date_et_typologie_de_la_protection"),
                               ("Historique", "historique")):
                v = _first(r.get(key))
                if v:
                    parts.append(f"{label} : {str(v)[:600]}")
            if ref:
                parts.append(f"Notice POP : {POP_NOTICE.format(ref=ref)} ({ref})")
            conn.execute(
                "INSERT INTO entity_notes (entity_id, date, note, source, confidence)"
                " VALUES (?, date('now'), ?, 'pop-merimee', 'verified')",
                (eid, "\n".join(parts)))
        n += 1
    return n


def import_objets(conn, insee: str, results: list[dict]) -> int:
    commune = COMMUNES.get(insee, {}).get("nom")
    n = 0
    for r in results:
        name = _first(r.get("appellation_d_usage")) or _first(r.get("denomination"))
        edifice = _first(r.get("edifice_actuel"))
        if not name:
            continue
        host = str(edifice or name).strip()
        eid = upsert_entity(conn, type="place", name=host,
                            confidence="verified", commune=commune)
        conn.execute(
            "INSERT INTO entity_notes (entity_id, date, note, source, confidence)"
            " SELECT ?, date('now'), ?, 'pop-palissy', 'verified'"
            " WHERE NOT EXISTS (SELECT 1 FROM entity_notes WHERE entity_id=? AND note LIKE ?)",
            (eid, f"Objet mobilier classé MH : {name} — "
                  f"{_first(r.get('description')) or ''}"[:800],
             eid, f"%{name}%"))
        n += 1
    return n


IMPORTERS = {DS_MH: ("cog_insee_lors_de_la_protection", import_mh),
             DS_OBJ: ("cog_insee", import_objets)}


def run(insee_list: list[str] | None = None):
    conn = get_conn()
    total = 0
    for insee in (insee_list or COMMUNES_INSEE):
        commune = COMMUNES.get(insee, {}).get("nom", insee)
        for dataset, (field, importer) in IMPORTERS.items():
            try:
                results = _fetch(dataset, field, insee)
            except Exception as e:
                print(f"[patrimoine] {commune} {dataset[:30]}… : erreur — {e}")
                continue
            n = importer(conn, insee, results)
            conn.commit()
            if n:
                print(f"[patrimoine] {commune} : {n} ({dataset[:40]}…)")
            total += n
            time.sleep(REQUEST_DELAY)
    print(f"[patrimoine] OK — {total} éléments")
    conn.close()


def show_stats():
    conn = get_conn(read_only=True)
    for r in conn.execute("""
        SELECT e.commune, e.name, json_extract(p.tags,'$.protection')
        FROM places p JOIN entities e ON e.id = p.entity_id
        WHERE p.osm_category='patrimoine'"""):
        print(f"  {r[0] or '?':30} {r[1]:40} {r[2] or ''}")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Patrimoine MH — 15 communes de l'EPCI")
    ap.add_argument("--insee", help="Codes INSEE (virgule)")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()
    if args.stats:
        show_stats()
    else:
        run(insee_list=args.insee.split(",") if args.insee else None)
