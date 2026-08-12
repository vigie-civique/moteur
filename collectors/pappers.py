#!/usr/bin/env python3
"""
Collecteur Pappers API — enrichit les données entreprises depuis l'API officielle.

Ce que ça apporte :
  - Dates de création réelles (BODACC, pas SIRENE/1900)
  - Liste des établissements : détecte les adresses Lasalle non connues
  - Dirigeants historiques : détecte ceux absents de la DB
  - Contact : téléphone et site web si disponibles dans l'API
  - Publications BODACC : événements (création, cession, fermeture)

Inscription API gratuite : https://www.pappers.fr/api
  → 200 appels/jour en free tier

Usage :
    export PAPPERS_API_TOKEN=votre_token
    python3 collectors/pappers.py                    # top 200 par priorité
    python3 collectors/pappers.py --limit 50         # 50 premiers
    python3 collectors/pappers.py --siren 881350995  # une seule entreprise
    python3 collectors/pappers.py --all              # toutes les actives (plusieurs jours)
    python3 collectors/pappers.py --dry-run          # sans écrire en DB
"""
import os
import sys
import json
import time
import sqlite3
import argparse
import urllib.request
import urllib.parse
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from collectors.archive import archive_fetch

DB_PATH = Path(__file__).parent.parent / "db" / "lasalle.db"
API_BASE = "https://api.pappers.fr/v2"
DELAY = 0.5            # secondes entre requêtes (conservateur)
CODE_POSTAL = "30460"  # Lasalle


# ── Helpers ────────────────────────────────────────────────────────

def get_token() -> str:
    token = os.environ.get("PAPPERS_API_TOKEN", "")
    if not token:
        print("ERREUR : variable PAPPERS_API_TOKEN non définie.")
        print("  Inscription gratuite : https://www.pappers.fr/api")
        sys.exit(1)
    return token


def api_get(path: str, params: dict) -> dict | None:
    # Convertir les booléens en minuscules pour l'API
    clean = {k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()}
    url = f"{API_BASE}{path}?" + urllib.parse.urlencode(clean)
    # URL archivée/affichée sans le token
    safe_url = f"{API_BASE}{path}?" + urllib.parse.urlencode(
        {k: v for k, v in clean.items() if k != "api_token"})
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "LasalleOSINT/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
        archive_fetch("pappers", safe_url, raw,
                      content_type="application/json", http_status=200)
        return json.loads(raw)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        print(f"  HTTP {e.code} — {safe_url[:120]}")
        return None
    except Exception as e:
        print(f"  Erreur réseau : {e}")
        return None


def is_spurious_date(d: str | None) -> bool:
    if not d:
        return True
    if d.startswith("1900"):
        return True
    if d.endswith("-12-25") or d.endswith("-01-01"):
        return True  # placeholders SIRENE courants
    return False


def is_lasalle_address(addr: str | None) -> bool:
    if not addr:
        return False
    return CODE_POSTAL in addr or "LASALLE" in addr.upper()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ── Traitement d'une entreprise ────────────────────────────────────

def process_one(conn, entity_id: int, siren: str, token: str, dry_run: bool) -> dict:
    """
    Appelle l'API Pappers pour un SIREN et enrichit la DB.
    Retourne un dict de résumé.
    """
    result = {"siren": siren, "updated": [], "notes": [], "error": None}

    data = api_get("/entreprise", {
        "siren": siren,
        "api_token": token,
        "entreprise_cessee": False,
    })

    if data is None:
        result["error"] = "non trouvé"
        return result

    return apply_enrichment(conn, entity_id, data, dry_run, result)


def apply_enrichment(conn, entity_id: int, data: dict, dry_run: bool = False,
                     result: dict | None = None) -> dict:
    """
    Enrichit la DB depuis une réponse Pappers /entreprise (déjà fetchée ou
    rejouée depuis raw_documents via scripts/reparse.py).
    """
    if result is None:
        result = {"siren": data.get("siren"), "updated": [], "notes": [], "error": None}

    today = date.today().isoformat()

    # ── 1. Date de création ──────────────────────────────────────
    pappers_date = data.get("date_creation")  # format YYYY-MM-DD
    current = conn.execute(
        "SELECT creation_date FROM businesses WHERE entity_id=?", (entity_id,)
    ).fetchone()
    current_date = current["creation_date"] if current else None

    if pappers_date and is_spurious_date(current_date):
        if not dry_run:
            conn.execute(
                "UPDATE businesses SET creation_date=? WHERE entity_id=?",
                (pappers_date, entity_id)
            )
        result["updated"].append(f"date_création : {current_date} → {pappers_date}")

    # ── 2. Contact (téléphone, site web) ────────────────────────
    phone   = data.get("telephone")
    website = data.get("site_internet")
    if phone or website:
        # Stocker dans places.tags si l'entité a une fiche OSM, sinon entity_notes
        place = conn.execute(
            "SELECT entity_id, tags FROM places WHERE entity_id=?", (entity_id,)
        ).fetchone()
        if place:
            tags = json.loads(place["tags"] or "{}")
            changed = False
            if phone and not tags.get("phone"):
                tags["phone"] = phone; changed = True
            if website and not tags.get("website"):
                tags["website"] = website; changed = True
            if changed and not dry_run:
                conn.execute(
                    "UPDATE places SET tags=? WHERE entity_id=?",
                    (json.dumps(tags, ensure_ascii=False), entity_id)
                )
            if changed:
                result["updated"].append(f"contact OSM : tél={phone} site={website}")
        else:
            # Stocker en note si pas de fiche OSM
            contact_parts = []
            if phone:   contact_parts.append(f"tél: {phone}")
            if website: contact_parts.append(f"site: {website}")
            if contact_parts and not dry_run:
                _add_note(conn, entity_id, today,
                          "Contact Pappers : " + " | ".join(contact_parts),
                          "Pappers API", "verified")
            if contact_parts:
                result["notes"].append("contact: " + " | ".join(contact_parts))

    # ── 3. Établissements ────────────────────────────────────────
    etablissements = data.get("etablissements", [])
    for etab in etablissements:
        adresse = etab.get("adresse", "")
        nom_com = etab.get("nom_commercial", "")
        siret   = etab.get("siret", "")
        etat    = etab.get("etat_administratif", "")
        if is_lasalle_address(adresse) and etat == "A":
            # Établissement actif à Lasalle → noter si pas déjà dans l'adresse principale
            current_addr = conn.execute(
                "SELECT address FROM entities WHERE id=?", (entity_id,)
            ).fetchone()
            note = f"Établissement Lasalle actif — SIRET {siret}"
            if nom_com:
                note += f" | Nom commercial : {nom_com}"
            note += f" | Adresse : {adresse}"
            # Vérifier qu'on n'a pas déjà cette note
            exists = conn.execute("""
                SELECT id FROM entity_notes
                WHERE entity_id=? AND source='Pappers API' AND note LIKE ?
            """, (entity_id, f"%{siret}%")).fetchone()
            if not exists:
                if not dry_run:
                    _add_note(conn, entity_id, today, note, "Pappers API", "verified")
                result["notes"].append(note[:80])

    # ── 4. Dirigeants ────────────────────────────────────────────
    representants = data.get("representants", [])
    for rep in representants:
        nom   = rep.get("nom", "")
        prenom = rep.get("prenom", "")
        qualite = rep.get("qualite", "")
        if not nom:
            continue
        full_name = f"{prenom} {nom}".strip()
        # Chercher si cette personne est en DB
        existing = conn.execute("""
            SELECT e.id FROM entities e
            JOIN persons p ON p.entity_id = e.id
            WHERE p.lastname = ? AND e.type = 'person'
        """, (nom.upper(),)).fetchone()
        if not existing:
            note = f"Dirigeant Pappers non en DB : {full_name} ({qualite})"
            exists = conn.execute("""
                SELECT id FROM entity_notes WHERE entity_id=? AND note LIKE ?
            """, (entity_id, f"%{full_name}%")).fetchone()
            if not exists:
                if not dry_run:
                    _add_note(conn, entity_id, today, note, "Pappers API", "probable")
                result["notes"].append(f"dirigeant absent: {full_name}")

    # ── 5. Sauvegarder raw + timestamp ──────────────────────────
    if not dry_run:
        conn.execute("""
            UPDATE businesses
            SET pappers_fetched_at=?, pappers_raw=?
            WHERE entity_id=?
        """, (today, json.dumps(data, ensure_ascii=False), entity_id))

    return result


def _add_note(conn, entity_id, date_str, note, source, confidence):
    conn.execute("""
        INSERT INTO entity_notes (entity_id, date, note, source, confidence)
        VALUES (?, ?, ?, ?, ?)
    """, (entity_id, date_str, note, source, confidence))


# ── Sélection des entités cibles ───────────────────────────────────

def get_targets(conn, siren_filter=None, limit=200, all_mode=False, local_only=False) -> list[dict]:
    if siren_filter:
        rows = conn.execute("""
            SELECT b.entity_id, e.name, b.siren, b.creation_date, b.pappers_fetched_at
            FROM businesses b JOIN entities e ON e.id=b.entity_id
            WHERE b.siren=?
        """, (siren_filter,)).fetchall()
        return [dict(r) for r in rows]

    # Priorité : actives + nombre de relations + events, non encore fetchées en priorité
    order = "b.pappers_fetched_at IS NULL DESC, (rel_count + ev_count * 2) DESC"
    lim = f"LIMIT {limit}"
    having = "" if all_mode else "HAVING (rel_count + ev_count > 0 OR b.creation_date LIKE '1900%' OR b.creation_date IS NULL)"
    local_filter = "AND (e.address LIKE '%30460%' OR e.address LIKE '%LASALLE%' OR e.address LIKE '%Lasalle%')" if local_only else ""

    rows = conn.execute(f"""
        SELECT b.entity_id, e.name, b.siren, b.creation_date, b.pappers_fetched_at,
               COUNT(DISTINCT r.id) as rel_count,
               COUNT(DISTINCT ee.event_id) as ev_count
        FROM businesses b
        JOIN entities e ON e.id=b.entity_id
        LEFT JOIN relations r ON r.from_id=b.entity_id OR r.to_id=b.entity_id
        LEFT JOIN event_entities ee ON ee.entity_id=b.entity_id
        WHERE b.siren IS NOT NULL AND b.status = 'A'
        {local_filter}
        GROUP BY b.entity_id
        {having}
        ORDER BY {order}
        {lim}
    """).fetchall()
    return [dict(r) for r in rows]


# ── Main ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Collecteur Pappers API")
    parser.add_argument("--limit",   type=int, default=200, help="Nb max d'entreprises (défaut 200)")
    parser.add_argument("--siren",   type=str, help="Traiter un seul SIREN")
    parser.add_argument("--all",     action="store_true", help="Toutes les entreprises actives")
    parser.add_argument("--refetch", action="store_true", help="Re-fetcher même celles déjà traitées")
    parser.add_argument("--dry-run", action="store_true", help="Sans écrire en DB")
    parser.add_argument("--local", action="store_true", help="Uniquement entités avec adresse Lasalle/30460")
    args = parser.parse_args()

    token = get_token()
    conn = get_db()

    targets = get_targets(conn, siren_filter=args.siren, limit=args.limit, all_mode=args.all, local_only=args.local)

    if not args.refetch:
        targets = [t for t in targets if not t.get("pappers_fetched_at")]

    print(f"{len(targets)} entreprises à traiter")
    if args.dry_run:
        print("[dry-run] aucune écriture DB")
    print()

    ok = errors = 0
    for i, t in enumerate(targets, 1):
        name_short = t["name"][:45]
        print(f"[{i}/{len(targets)}] {name_short:<45} SIREN {t['siren']}", end=" … ", flush=True)

        result = process_one(conn, t["entity_id"], t["siren"], token, args.dry_run)

        if result["error"]:
            print(f"SKIP ({result['error']})")
            errors += 1
        else:
            parts = []
            if result["updated"]: parts.append(f"MàJ: {', '.join(result['updated'])}")
            if result["notes"]:   parts.append(f"notes: {len(result['notes'])}")
            print("OK" + (f" — {' | '.join(parts)}" if parts else ""))
            ok += 1

        if not args.dry_run:
            conn.commit()

        time.sleep(DELAY)

    print(f"\nTerminé : {ok} OK, {errors} erreurs")
    conn.close()


if __name__ == "__main__":
    main()
