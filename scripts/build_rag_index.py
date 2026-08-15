#!/usr/bin/env python3
"""
build_rag_index.py — Construit l'index de recherche par sens de l'atelier.

Un vecteur par note, acte, flux financier et entité, calculé par un modèle
d'embeddings local (Ollama). L'atelier s'en sert pour retrouver une notion
quand on n'en a pas le vocabulaire : « conflit d'intérêt » ramène les
récusations au conseil, où ce mot ne figure nulle part. Pour un mot qui
s'écrit tel quel, la recherche plein texte déjà en base (FTS5) est plus rapide
et plus prévisible — les deux ne se remplacent pas.

L'index porte sur la base de TRAVAIL, non filtrée : il ne sort pas de
l'atelier, et le site public n'en a aucune trace. Sa recherche à lui est en
texte clair, sur le snapshot déjà filtré.

Modèle et adresse se règlent par l'environnement, comme dans api.py :
OLLAMA_URL, OLLAMA_EMBED_MODEL.

Usage :
    python3 scripts/build_rag_index.py            # incrémental
    python3 scripts/build_rag_index.py --reset
    python3 scripts/build_rag_index.py --source events
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collectors.config import DB_PATH   # noqa: E402

OLLAMA_URL  = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
EMBED_URL   = f"{OLLAMA_URL}/api/embeddings"
EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")

def embed(text: str) -> np.ndarray:
    r = requests.post(EMBED_URL, json={"model": EMBED_MODEL, "prompt": text},
                      timeout=30)
    r.raise_for_status()
    return np.array(r.json()["embedding"], dtype=np.float32)


# ─── chunk builders ───────────────────────────────────────────────────────────

def chunks_entity_notes(conn):
    for row in conn.execute("""
        SELECT n.id, n.entity_id, e.name, n.note, n.source, n.confidence
        FROM entity_notes n
        JOIN entities e ON e.id = n.entity_id
        WHERE n.note IS NOT NULL AND LENGTH(n.note) > 10
    """):
        nid, eid, ename, content, source, conf = row
        text = f"Note ({conf}) sur {ename}: {content}"
        if source:
            text += f" [source: {source}]"
        yield "entity_notes", nid, eid, text


# Bruit connu, exclu de l'index : fragments de tableaux OCR mis en quarantaine
# (fragments de grilles tarifaires découpées par l'OCR d'un PV).
EVENT_TYPES_EXCLUS = ("fragment_ocr",)

# Longueur de contenu retenue par événement. nomic-embed-text accepte 8192
# tokens ; 2000 caractères couvrent une délibération entière dans la quasi-
# totalité des cas, sans diluer le vecteur.
EVENT_CONTENT_MAX = 2000


def chunks_events(conn):
    """Un embedding par événement, enrichi des acteurs liés.

    ⚠️ Cette fonction interrogeait `events.entity_id` et `events.description`
    — deux colonnes qui n'existent pas : le lien acteur↔acte passe par
    `event_entities` et le texte est dans `content`. La requête levait donc
    `OperationalError` à la première itération et faisait tomber tout le script.
    Résultat : 0 des 2 800 événements n'a jamais été indexé, alors que les
    délibérations et PV sont l'essentiel du texte substantiel de la base. Une
    question du type « qu'a voté le conseil sur la Cure ? » ne pouvait rien
    trouver. Ne pas réintroduire ces noms de colonnes.
    """
    placeholders = ",".join("?" for _ in EVENT_TYPES_EXCLUS)
    for row in conn.execute(f"""
        SELECT ev.id, ev.type, ev.date, ev.title, ev.content, ev.source,
               ev.metadata,
               (SELECT ee.entity_id FROM event_entities ee
                 WHERE ee.event_id = ev.id
                 ORDER BY (ee.role <> 'sujet'), ee.entity_id LIMIT 1) AS main_entity_id,
               (SELECT GROUP_CONCAT(e2.name, ', ') FROM event_entities ee2
                  JOIN entities e2 ON e2.id = ee2.entity_id
                 WHERE ee2.event_id = ev.id) AS acteurs
        FROM events ev
        WHERE ev.type NOT IN ({placeholders})
          AND (LENGTH(COALESCE(ev.title, '')) > 5
               OR LENGTH(COALESCE(ev.content, '')) > 40)
    """, EVENT_TYPES_EXCLUS):
        (ev_id, ev_type, date, title, content, source, metadata,
         main_entity_id, acteurs) = row

        parts = [f"{ev_type} {date or 'sans date'} : {title or '(sans titre)'}"]
        if acteurs:
            parts.append(f"Acteurs concernés : {acteurs}.")

        # Vote et montants sont dans metadata et portent l'essentiel du sens
        # d'une délibération — les sortir en clair les rend interrogeables.
        if metadata:
            try:
                meta = json.loads(metadata)
            except (json.JSONDecodeError, TypeError):
                meta = {}
            if meta.get("vote"):
                parts.append(f"Vote : {meta['vote']}.")
            montants = meta.get("montants")
            if montants:
                parts.append(f"Montants cités : {montants}.")
            if meta.get("categorie"):
                parts.append(f"Catégorie : {meta['categorie']}.")

        if content:
            parts.append(content[:EVENT_CONTENT_MAX])
        if source:
            parts.append(f"[source: {source}]")
        yield "events", ev_id, main_entity_id, " ".join(parts)


def chunks_financial_flows(conn):
    for row in conn.execute("""
        SELECT ff.id, ff.to_id, e_to.name, ff.from_id, e_from.name,
               ff.type, ff.amount, ff.year, ff.description
        FROM financial_flows ff
        LEFT JOIN entities e_to   ON e_to.id   = ff.to_id
        LEFT JOIN entities e_from ON e_from.id = ff.from_id
        WHERE ff.amount IS NOT NULL OR ff.description IS NOT NULL
    """):
        fid, to_id, to_name, from_id, from_name, ftype, amount, year, desc = row
        dest = to_name or "?"
        src  = from_name or "?"
        parts = [f"Flux {ftype} {year or ''}:"]
        parts.append(f"{src} → {dest}")
        if amount:
            parts.append(f"{amount:,.0f} €")
        if desc:
            parts.append(f"— {desc[:200]}")
        entity_id = to_id or from_id
        yield "financial_flows", fid, entity_id, " ".join(parts)


def chunks_entities(conn):
    for row in conn.execute("""
        SELECT e.id, e.name, e.type, e.address,
               b.siren
        FROM entities e
        LEFT JOIN businesses b ON b.entity_id = e.id
        WHERE e.name IS NOT NULL
    """):
        eid, name, etype, addr, siren = row
        parts = [f"Entité {etype}: {name}"]
        if siren:
            parts.append(f"SIREN {siren}")
        if addr:
            parts.append(f"Adresse: {addr}")
        yield "entities", eid, eid, " ".join(parts)


# Ce que l'index doit contenir : du TEXTE ÉCRIT — notes de l'atelier,
# délibérations, libellés de flux. Pas des fiches d'annuaire.
#
# `chunks_entities` produit « Entité association: NOM. Adresse: … » pour chaque
# acteur. Mesuré le 15/08/2026 sur une base de 18 176 chunks : ces 8 753 fiches
# représentaient 48 % de l'index et sortaient EN TÊTE de la question « conflit
# d'intérêt élu association subventionnée » — le mot « association » figure dans
# chacune d'elles. Les délibérations qui traitent réellement du sujet
# n'apparaissaient qu'une fois ces fiches écartées.
#
# Un nom d'acteur se cherche par son nom : c'est le métier du FTS5 déjà en base,
# qui le fait mieux et sans modèle. La recherche par sens sert à retrouver ce
# qu'on ne sait pas nommer.
#
# `--source entities` reste possible pour qui veut mesurer par lui-même.
ALL_BUILDERS = [
    chunks_entity_notes,
    chunks_events,
    chunks_financial_flows,
]

BUILDERS_OPTIONNELS = [chunks_entities]


# ─── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Vider et reconstruire l'index")
    parser.add_argument("--source", choices=["entity_notes","events","financial_flows","entities"],
                        help="Limiter à une source")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")

    if args.reset:
        if args.source:
            conn.execute("DELETE FROM embeddings WHERE source_table=?", (args.source,))
        else:
            conn.execute("DELETE FROM embeddings")
        conn.commit()
        print("Index réinitialisé.")

    total = inserted = skipped = 0

    builders = ([b for b in ALL_BUILDERS + BUILDERS_OPTIONNELS
                 if b.__name__ == f"chunks_{args.source}"]
                if args.source else list(ALL_BUILDERS))

    # Un builder qui casse ne doit pas emporter les autres : c'est ce qui a
    # masqué l'absence totale des events dans l'index (OperationalError sur une
    # colonne inexistante → le script mourait, les autres sources passaient
    # quand on les demandait une par une, et le trou restait invisible).
    echecs: list[str] = []

    for builder in builders:
        try:
            produced = list(builder(conn))
        except Exception as e:
            echecs.append(f"{builder.__name__}: {type(e).__name__}: {e}")
            print(f"  ✗ builder {builder.__name__} en échec — {e}", file=sys.stderr)
            continue

        for source_table, source_id, entity_id, chunk_text in produced:
            total += 1
            existing = conn.execute(
                "SELECT id FROM embeddings WHERE source_table=? AND source_id=?",
                (source_table, source_id)
            ).fetchone()
            if existing:
                skipped += 1
                continue

            try:
                vec = embed(chunk_text)
            except Exception as e:
                print(f"  ✗ {source_table}:{source_id} — {e}", file=sys.stderr)
                continue

            conn.execute(
                "INSERT OR IGNORE INTO embeddings (source_table, source_id, entity_id, chunk_text, vector, created_at) VALUES (?,?,?,?,?,?)",
                (source_table, source_id, entity_id, chunk_text, vec.tobytes(),
                 datetime.now(timezone.utc).isoformat())
            )
            conn.commit()
            inserted += 1
            if inserted % 10 == 0:
                print(f"  {inserted} / {total - skipped} embeddings…")

    count = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    par_source = conn.execute(
        "SELECT source_table, COUNT(*) n FROM embeddings GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()
    conn.close()
    print(f"\nTerminé — {inserted} ajoutés, {skipped} déjà indexés. Total en base : {count}")
    for src, n in par_source:
        print(f"  {src:16} {n:>5}")
    if echecs:
        print("\n⚠ builders en échec (index incomplet) :", file=sys.stderr)
        for e in echecs:
            print(f"  - {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
