"""
url_finder.py — Recherche automatique des sites web des entités locales

Source : DuckDuckGo HTML → candidates insérés dans entity_websites (status='candidate')
Validation : atelier /atelier/queue/websites ou --interactive

Usage :
  python3 -m collectors.url_finder --batch --limit 50   # auto, top résultat DDG
  python3 -m collectors.url_finder --interactive         # validation manuelle
  python3 -m collectors.url_finder --query "Champ Contrechamp"  # recherche libre
  python3 -m collectors.url_finder --stats               # état de la table
"""

import argparse
import re
import time
import urllib.parse
import sqlite3

from ddgs import DDGS

from .config import CODE_POSTAL, COMMUNE_NAME, DB_PATH, DEPARTEMENT

DELAY = 1.0  # secondes entre requêtes (ddgs gère son propre rate limiting)

EXCLUDE_DOMAINS = {
    "facebook.com", "twitter.com", "instagram.com", "linkedin.com",
    "youtube.com", "tiktok.com", "wikipedia.org", "wikidata.org",
    "societe.com", "verif.com", "infogreffe.fr", "pappers.fr",
    "data.gouv.fr", "journal-officiel.gouv.fr", "sirene.fr",
    "pagesjaunes.fr", "annuaire.caf.fr", "kompass.com",
    "manageo.fr", "societe.ninja", "bfmtv.com", "lemonde.fr",
    "ouest-france.fr", "midilibre.fr", "legifrance.gouv.fr",
    "maps.google", "google.com", "bing.com", "yahoo.com",
    "tripadvisor.fr", "leparisien.fr", "mappy.com", "annuaire-mairie.fr",
    "net1901.org", "annuairefrancais.fr", "kbis.pro",
}


# ── Recherche via ddgs ────────────────────────────────────────────────────────

def search_ddg(query: str, max_results: int = 5) -> list[dict]:
    try:
        with DDGS() as ddg:
            raw = list(ddg.text(query, max_results=max_results * 2, region="fr-fr"))
    except Exception as e:
        print(f"  [erreur DDG] {e}")
        return []

    results = []
    for r in raw:
        url    = r.get("href", "")
        domain = urllib.parse.urlparse(url).netloc.lower().replace("www.", "")
        if any(excl in domain for excl in EXCLUDE_DOMAINS):
            continue
        results.append({"url": url, "title": r.get("title", ""), "snippet": r.get("body", "")})
        if len(results) >= max_results:
            break
    return results


def build_query(entity: dict) -> str:
    name = entity["name"]
    etype = entity.get("type", "")
    clean = re.sub(r"\s*\(.*?\)\s*$", "", name).strip()
    if etype == "association":
        return f'"{clean}" {COMMUNE_NAME} {DEPARTEMENT} site officiel'
    elif etype == "business":
        # Une entreprise se cherche sur son territoire, pas sur sa commune :
        # beaucoup ont une adresse dans un hameau ou la commune voisine.
        return f'"{clean}" {DEPARTEMENT} {COMMUNE_NAME}'
    else:
        return f'"{clean}" {COMMUNE_NAME} {CODE_POSTAL}'


def score_result(entity_name: str, result: dict) -> float:
    """Score 0-1 : pertinence du résultat DDG pour cette entité."""
    name_lower = entity_name.lower()
    words = [w for w in re.split(r'\W+', name_lower) if len(w) > 3]
    domain = urllib.parse.urlparse(result["url"]).netloc.lower().replace("www.", "")
    title  = (result.get("title") or "").lower()

    score = 0.3  # base
    if any(w in domain for w in words):
        score += 0.4
    if any(w in title for w in words):
        score += 0.2
    if COMMUNE_NAME.lower() in domain or COMMUNE_NAME.lower() in title:
        score += 0.1
    return min(score, 1.0)


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_entities_without_url(conn, entity_type: str | None = None, limit: int = 0) -> list[dict]:
    """Entités sans aucune URL candidate ou validée."""
    q = """
        SELECT e.id, e.type, e.name
        FROM entities e
        WHERE e.type IN ('association','business','place','service')
          AND NOT EXISTS (
              SELECT 1 FROM entity_websites ew
              WHERE ew.entity_id = e.id
                AND ew.status IN ('candidate','validated')
          )
    """
    params: list = []
    if entity_type:
        q += " AND e.type = ?"
        params.append(entity_type)
    q += " ORDER BY e.type, e.name"
    if limit:
        q += f" LIMIT {limit}"
    return [dict(r) for r in conn.execute(q, params).fetchall()]


def insert_candidate(conn, entity_id: int, url: str, score: float,
                     found_by: str = "url_finder") -> bool:
    try:
        conn.execute(
            "INSERT OR IGNORE INTO entity_websites (entity_id, url, status, score, found_by)"
            " VALUES (?, ?, 'candidate', ?, ?)",
            (entity_id, url, round(score, 2), found_by)
        )
        return conn.execute("SELECT changes()").fetchone()[0] == 1
    except Exception as e:
        print(f"  [db erreur] {e}")
        return False


def set_status(conn, entity_id: int, url: str, status: str) -> None:
    conn.execute(
        "UPDATE entity_websites SET status=? WHERE entity_id=? AND url=?",
        (status, entity_id, url)
    )


# ── Modes ─────────────────────────────────────────────────────────────────────

def batch_mode(limit: int = 0, entity_type: str | None = None, dry_run: bool = False) -> None:
    conn = get_conn()
    missing = get_entities_without_url(conn, entity_type=entity_type, limit=limit)
    print(f"\n[batch] {len(missing)} entités sans URL\n")

    found = 0
    for i, entity in enumerate(missing):
        query = build_query(entity)
        print(f"[{i+1}/{len(missing)}] [{entity['type']}] {entity['name']}")
        results = search_ddg(query)
        time.sleep(DELAY)

        if not results:
            print("  → aucun résultat")
            continue

        best = results[0]
        sc   = score_result(entity["name"], best)
        print(f"  → {best['url']}  (score={sc:.2f})")

        if not dry_run:
            insert_candidate(conn, entity["id"], best["url"], sc)
            conn.commit()
        found += 1

    conn.close()
    prefix = "[DRY] " if dry_run else ""
    print(f"\n{prefix}✅ {found}/{len(missing)} URLs candidates trouvées")


def interactive_mode(limit: int = 0, entity_type: str | None = None) -> None:
    conn = get_conn()
    missing = get_entities_without_url(conn, entity_type=entity_type, limit=limit)
    print(f"\n{len(missing)} entités à traiter")
    print("Commandes : [1-5] choisir | [u] saisir URL | [s] ignorer | [q] quitter\n")

    for i, entity in enumerate(missing):
        print(f"{'─'*60}")
        print(f"[{i+1}/{len(missing)}] {entity['type'].upper()} — {entity['name']}")
        query = build_query(entity)
        print(f"  Recherche : {query}")
        results = search_ddg(query)
        time.sleep(DELAY)

        if not results:
            print("  Aucun résultat.")
            choice = input("  [u] saisir URL | [s] ignorer : ").strip().lower()
        else:
            for j, r in enumerate(results, 1):
                sc = score_result(entity["name"], r)
                print(f"  [{j}] {r['url']}  (score={sc:.2f})")
                if r.get("title"):
                    print(f"      {r['title'][:70]}")
            choice = input(f"\n  Choix [1-{len(results)}] / [u]rl / [s]auter / [q]uitter : ").strip().lower()

        if choice == "q":
            break
        elif choice in ("s", ""):
            continue
        elif choice == "u":
            url = input("  URL : ").strip()
            if url:
                insert_candidate(conn, entity["id"], url, score=1.0, found_by="manual")
                set_status(conn, entity["id"], url, "validated")
                conn.commit()
                print(f"  ✓ Validé : {url}")
        elif choice.isdigit() and 1 <= int(choice) <= len(results):
            r   = results[int(choice) - 1]
            sc  = score_result(entity["name"], r)
            insert_candidate(conn, entity["id"], r["url"], sc)
            conn.commit()
            print(f"  ✓ Candidate : {r['url']}")
        print()

    conn.close()


def single_query(query: str) -> None:
    print(f"\nRecherche : {query}\n")
    results = search_ddg(query, max_results=8)
    if not results:
        print("Aucun résultat.")
        return
    for i, r in enumerate(results, 1):
        print(f"[{i}] {r['url']}")
        if r.get("title"):
            print(f"    {r['title']}")
        if r.get("snippet"):
            print(f"    {r['snippet'][:100]}")
        print()


def show_stats() -> None:
    conn = get_conn()
    rows = conn.execute(
        "SELECT status, COUNT(*) n FROM entity_websites GROUP BY status ORDER BY status"
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM entity_websites").fetchone()[0]
    entities_total = conn.execute("SELECT COUNT(*) FROM entities WHERE type IN ('association','business','place','service')").fetchone()[0]
    print(f"\nentity_websites — {total} entrées ({entities_total} entités cibles)")
    for r in rows:
        print(f"  {r['status']:12s} : {r['n']}")
    print(f"  {'sans URL':12s} : {entities_total - total}")
    conn.close()


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="url_finder — recherche sites web des entités locales")
    parser.add_argument("--batch",       action="store_true", help="Mode automatique (top résultat DDG)")
    parser.add_argument("--interactive", action="store_true", help="Mode validation manuelle")
    parser.add_argument("--dry-run",     action="store_true", help="Affiche sans insérer en DB")
    parser.add_argument("--limit",  "-n", type=int, default=0)
    parser.add_argument("--type",   "-t", default=None, choices=["association","business","place","service"])
    parser.add_argument("--query",  "-q", default=None, help="Recherche libre")
    parser.add_argument("--stats",       action="store_true", help="Affiche état de la table")
    args = parser.parse_args()

    if args.stats:
        show_stats()
    elif args.query:
        single_query(args.query)
    elif args.batch:
        batch_mode(limit=args.limit, entity_type=args.type, dry_run=args.dry_run)
    else:
        interactive_mode(limit=args.limit, entity_type=args.type)
