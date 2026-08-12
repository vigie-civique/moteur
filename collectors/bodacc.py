"""
bodacc.py — Collecteur BODACC pour les 15 communes de la CC CAC

Source : API open data BODACC (bodacc-datadila.opendatasoft.com)
Pas de clé API requise, 100 req/10s.

Périmètre : les 2 codes postaux du vallon (30460 + 30140). Le CP 30140 couvre
aussi Anduze et d'autres communes hors périmètre → filtrage par NOM de commune
(registre COMMUNES) en plus du CP. cf. audit Phase A (session 22).

Usage :
  python3 -m collectors.bodacc             # import complet (CP 30460 par défaut)
  python3 -m collectors.bodacc --since 2020-01-01
  python3 -m collectors.bodacc --dry-run
  python3 -m collectors.bodacc --stats
"""

import argparse
import json
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime

from .archive import fetch_json
from .config import ROOT, COMMUNES, COMMUNES_CP
from .db import get_conn

API_BASE = "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/annonces-commerciales/records"
CP = "30460"
PAGE_SIZE = 100


def _norm(s: str) -> str:
    """Normalise un nom de commune : sans accents, minuscules, séparateurs unifiés."""
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    for ch in "-'’":
        s = s.replace(ch, " ")
    return " ".join(s.lower().split())


# Index nom normalisé → nom officiel du registre (pour filtrer les annonces)
_COMMUNE_LOOKUP = {_norm(c["nom"]): c["nom"] for c in COMMUNES.values()}
# Alias commune nouvelle Thoiras-Corbès (BODACC peut encore utiliser les anciens noms)
for _alias in ("Thoiras", "Corbès"):
    _COMMUNE_LOOKUP[_norm(_alias)] = "Thoiras-Corbès"


def _match_commune(ville: str) -> str | None:
    """Nom officiel du registre si la commune est collectée, sinon None."""
    return _COMMUNE_LOOKUP.get(_norm(ville))

# Mapping famille → type event
FAMILLE_TYPE = {
    "vente":        "bodacc_vente",
    "creation":     "bodacc_creation",
    "radiation":    "bodacc_radiation",
    "modification": "bodacc_modification",
    "depot":        "bodacc_depot",
    "collective":   "bodacc_collective",
    "immatriculation": "bodacc_creation",
    "avis":         "bodacc_divers",
}


def fetch_page(offset: int, since: str | None = None, cp: str = CP) -> dict:
    filters = [f'cp="{cp}"']
    if since:
        filters.append(f'dateparution>="{since}"')
    where = " AND ".join(filters)
    params = urllib.parse.urlencode({
        "where": where,
        "limit": PAGE_SIZE,
        "offset": offset,
        "order_by": "dateparution ASC",
    })
    url = f"{API_BASE}?{params}"
    return fetch_json(url, source="bodacc", timeout=30,
                      headers={"User-Agent": "LasalleOSINT/1.0"})


def parse_siren(registre) -> str | None:
    """Extrait le SIREN (9 chiffres) depuis le champ registre."""
    if not registre:
        return None
    candidates = registre if isinstance(registre, list) else [registre]
    for c in candidates:
        digits = str(c).replace(" ", "").replace(".", "")
        if len(digits) == 9 and digits.isdigit():
            return digits
        if len(digits) >= 9:
            clean = "".join(ch for ch in digits if ch.isdigit())[:9]
            if len(clean) == 9:
                return clean
    return None


def parse_persons(listepersonnes_raw) -> list[dict]:
    """Parse le champ JSON listepersonnes pour extraire noms/SIREN."""
    if not listepersonnes_raw:
        return []
    try:
        data = json.loads(listepersonnes_raw) if isinstance(listepersonnes_raw, str) else listepersonnes_raw
    except (json.JSONDecodeError, TypeError):
        return []

    persons = []
    raw_list = data.get("personne") or data.get("listepersonnes", {}).get("personne")
    if raw_list is None:
        return []
    if isinstance(raw_list, dict):
        raw_list = [raw_list]
    for p in raw_list:
        nom = p.get("denomination") or f"{p.get('nom', '')} {p.get('prenom', '')}".strip()
        siren = None
        immat = p.get("numeroImmatriculation") or p.get("inscriptionRM") or {}
        if isinstance(immat, dict):
            raw = immat.get("numeroIdentification") or immat.get("numeroIdentificationRM", "")
            siren = parse_siren([raw]) if raw else None
        persons.append({"nom": nom, "siren": siren, "type_personne": p.get("typePersonne", "")})
    return persons


def build_title(rec: dict) -> str:
    famille = rec.get("familleavis_lib", "Annonce")
    commercant = rec.get("commercant", "")
    ville = rec.get("ville", "")
    date = rec.get("dateparution", "")[:10]
    return f"BODACC {famille} — {commercant} — {ville} ({date})"


def build_content(rec: dict) -> str:
    parts = []
    for field in ("jugement", "acte", "modificationsgenerales", "radiationaurcs", "depot", "divers"):
        raw = rec.get(field)
        if not raw:
            continue
        try:
            obj = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(obj, dict):
                parts.append(f"{field}: " + " | ".join(f"{k}={v}" for k, v in obj.items() if v))
            else:
                parts.append(f"{field}: {obj}")
        except Exception:
            parts.append(f"{field}: {raw}")

    # Vendeur/acheteur pour ventes
    for field in ("listeprecedentexploitant", "listeprecedentproprietaire"):
        raw = rec.get(field)
        if raw:
            try:
                obj = json.loads(raw) if isinstance(raw, str) else raw
                parts.append(f"{field}: {json.dumps(obj, ensure_ascii=False)}")
            except Exception:
                pass
    return "\n".join(parts)


def find_entity_id(conn, siren: str | None, name: str | None) -> int | None:
    """Cherche une entité en DB par SIREN d'abord, puis par nom."""
    if siren:
        row = conn.execute(
            "SELECT entity_id FROM businesses WHERE siren=?", (siren,)
        ).fetchone()
        if row:
            return row[0]
    if name:
        row = conn.execute(
            "SELECT id FROM entities WHERE name=? OR short_name=?",
            (name.upper(), name.upper())
        ).fetchone()
        if row:
            return row[0]
    return None


def already_imported(conn, bodacc_id: str) -> bool:
    row = conn.execute(
        "SELECT id FROM events WHERE source='bodacc' AND source_url LIKE ?",
        (f"%{bodacc_id}%",)
    ).fetchone()
    return row is not None


def import_record(conn, rec: dict, dry_run: bool = False) -> bool:
    """Importe une annonce BODACC. Retourne True si insérée."""
    bodacc_id = rec.get("id", "")
    if already_imported(conn, bodacc_id):
        return False

    famille = (rec.get("familleavis") or "").lower()
    event_type = FAMILLE_TYPE.get(famille, "bodacc_divers")
    date = rec.get("dateparution", "")[:10]
    title = build_title(rec)
    content = build_content(rec)
    source_url = rec.get("url_complete", "")
    siren = parse_siren(rec.get("registre"))
    commercant = rec.get("commercant", "")

    metadata = {
        "bodacc_id": bodacc_id,
        "familleavis": rec.get("familleavis_lib"),
        "typeavis": rec.get("typeavis_lib"),
        "tribunal": rec.get("tribunal"),
        "siren": siren,
        "commercant": commercant,
        "ville": rec.get("ville"),
        "cp": rec.get("cp"),
    }

    if dry_run:
        print(f"  [dry-run] {date} | {event_type} | {commercant} | SIREN={siren}")
        return True

    try:
        cur = conn.execute(
            "INSERT INTO events (type, date, title, content, source, source_url, metadata)"
            " VALUES (?, ?, ?, ?, 'bodacc', ?, ?)",
            (event_type, date, title, content, source_url, json.dumps(metadata, ensure_ascii=False))
        )
        event_id = cur.lastrowid

        # Lier à l'entité si trouvée
        entity_id = find_entity_id(conn, siren, commercant)
        if entity_id:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO event_entities (event_id, entity_id, role)"
                    " VALUES (?, ?, 'sujet')",
                    (event_id, entity_id)
                )
            except Exception:
                pass

        # Pour les ventes : tenter de lier vendeur et acheteur
        persons = parse_persons(rec.get("listepersonnes"))
        for p in persons:
            pid = find_entity_id(conn, p.get("siren"), p.get("nom"))
            if pid and pid != entity_id:
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO event_entities (event_id, entity_id, role)"
                        " VALUES (?, ?, 'mentionné')",
                        (event_id, pid)
                    )
                except Exception:
                    pass

        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return True


def run(since: str | None = None, dry_run: bool = False, stats_only: bool = False,
        cp: str = CP):
    conn = get_conn()

    if stats_only:
        count = conn.execute("SELECT COUNT(*) FROM events WHERE source='bodacc'").fetchone()[0]
        by_type = conn.execute(
            "SELECT type, COUNT(*) FROM events WHERE source='bodacc' GROUP BY type ORDER BY COUNT(*) DESC"
        ).fetchall()
        print(f"Événements BODACC en DB : {count}")
        for t, n in by_type:
            print(f"  {t} : {n}")
        return

    print(f"Collecte BODACC CP {cp}" + (f" depuis {since}" if since else " (complet)"))

    offset = 0
    total_fetched = 0
    total_inserted = 0
    hors_perimetre = 0

    while True:
        try:
            page = fetch_page(offset, since, cp)
        except Exception as e:
            # NE PAS avaler : un `break` silencieux ici rend une panne réseau
            # indiscernable d'un "rien de nouveau" — c'est exactement ce qui a
            # laissé 17 annonces BODACC non lues pendant 3 semaines (constaté
            # le 10/08/2026, cron 7h en échec DNS répété). L'appelant
            # (collect_loop.run_one) journalise l'exception en status='error',
            # au lieu du 'empty' qui masquait la panne jusqu'ici.
            print(f"  [erreur] offset={offset} : {e}")
            raise

        records = page.get("results", [])
        total_count = page.get("total_count", 0)

        if not records:
            break

        for rec in records:
            total_fetched += 1
            # Filtre par nom de commune : le CP 30140 couvre aussi Anduze & co.
            if not _match_commune(rec.get("ville") or ""):
                hors_perimetre += 1
                continue
            inserted = import_record(conn, rec, dry_run=dry_run)
            if inserted:
                total_inserted += 1
                commercant = rec.get("commercant", "")
                date = rec.get("dateparution", "")[:10]
                famille = rec.get("familleavis_lib", "")
                ville = rec.get("ville", "")
                print(f"  ✓ {date} | {famille:25s} | {commercant} — {ville}")

        offset += len(records)
        print(f"  [{offset}/{total_count}]")

        if offset >= total_count:
            break

        time.sleep(0.3)

    print(f"\nBODACC CP {cp} : {total_fetched} annonces lues, "
          f"{hors_perimetre} hors périmètre ignorées, {total_inserted} insérées.")
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collecteur BODACC — Lasalle CP 30460")
    parser.add_argument("--since", default=None, help="Date minimale YYYY-MM-DD (défaut: tout)")
    parser.add_argument("--dry-run", action="store_true", help="Affiche sans insérer")
    parser.add_argument("--stats", action="store_true", help="Affiche stats DB et quitte")
    args = parser.parse_args()
    run(since=args.since, dry_run=args.dry_run, stats_only=args.stats)
