"""
Vigie Civique — API de l'atelier (FastAPI)
Port 8765, proxié par Vite (:5173) en dev.
"""
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Charge .env si présent (dev local)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

from fastapi import Body, FastAPI, HTTPException, Path as FPath, Query, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ─── Config ────────────────────────────────────────────────────────────────────

BASE_DIR      = Path(__file__).parent
SYNTHESES_DIR = BASE_DIR / "dashboard" / "static" / "api" / "syntheses"

# L'atelier et la publication lisent la MÊME base, décrite par la même
# configuration : un atelier qui pointerait ailleurs travaillerait sur des
# données que le site ne publie pas, et l'écart ne se verrait jamais.
from collectors.config import (BBOX, COMMUNE_NAME, COMMUNE_INSEE, DB_PATH,
                               DEPARTEMENT, EPCI_NOM)

# Boîte englobante de la commune, telle que déclarée par l'instance.
COMMUNE_BBOX = {"lat_min": BBOX[0], "lng_min": BBOX[1],
                "lat_max": BBOX[2], "lng_max": BBOX[3]} if len(BBOX) == 4 else {
    "lat_min": -90.0, "lat_max": 90.0, "lng_min": -180.0, "lng_max": 180.0}

# RAG_ENABLED : True en local (Mac + Ollama), False sur l'atelier hébergé (VPS sans Ollama).
# Contrôle via env var RAG_ENABLED=0 pour désactiver sur le VPS.
# Les endpoints /api/rag/* retournent 503 si désactivé.
RAG_ENABLED = os.environ.get("RAG_ENABLED", "1").strip().lower() not in ("0", "false", "no")

app = FastAPI(title=f"Vigie Civique — atelier {COMMUNE_NAME}")

# ─── Verrou global API (audit Phase A — session 22) ──────────────────────────
# Toute requête /api/* exige un JWT access valide OU l'en-tête X-Admin-Key.
# Seul /api/auth/* est exempté (login/refresh/logout/me gèrent leur propre auth).
# Enregistré AVANT CORS pour que CORSMiddleware reste le plus externe (préflights
# OPTIONS + en-têtes CORS sur les réponses 401). Défense en profondeur : les
# require_auth / _check_admin des routes restent en place — NE PAS retirer.
import secrets as _secrets
from starlette.responses import JSONResponse as _JSONResponse

@app.middleware("http")
async def _api_auth_guard(request, call_next):
    path = request.url.path
    if (request.method == "OPTIONS"
            or not path.startswith("/api/")
            or path.startswith("/api/auth/")):
        return await call_next(request)

    # 1) Clé admin — fallback scripts CLI (sync_ia, generate_syntheses --push, deploy)
    admin_key = os.environ.get("ADMIN_KEY", "")
    provided  = request.headers.get("x-admin-key")
    if admin_key and provided and _secrets.compare_digest(provided, admin_key):
        return await call_next(request)

    # 2) JWT access valide (décodage + kind=access + non révoqué) — logique api_auth
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        try:
            from api_auth import _decode, _revoked, _db
            payload = _decode(token)
            if payload.get("kind") == "access":
                conn = _db()
                try:
                    if not _revoked(token, conn):
                        return await call_next(request)
                finally:
                    conn.close()
        except Exception:
            pass

    return _JSONResponse({"detail": "Authentification requise"}, status_code=401)

# CORS — restreint aux origines autorisées (env ALLOWED_ORIGINS ou localhost en dev)
_raw_origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:4173")
ALLOWED_ORIGINS = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)

# Rate limiting
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.requests import Request as StarletteRequest

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Auth JWT — atelier
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from api_auth import router as auth_router, require_auth, require_role
app.include_router(auth_router)

# Clé admin pour les endpoints d'écriture (env ADMIN_KEY — si absente, accès localhost uniquement)
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")

# ─── DB helpers ────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn

def get_db_rw():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")   # anti-SQLITE_BUSY multi-utilisateurs (WAL)
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

def rows(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]

def row(conn, sql, params=()):
    r = conn.execute(sql, params).fetchone()
    return dict(r) if r else None

def parse_json_field(value, default=None):
    if not value:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default

def fts_query(value: str) -> str:
    tokens = re.findall(r"[\wÀ-ÿ]{2,}", value or "", flags=re.UNICODE)
    if not tokens:
        return '""'
    return " AND ".join(f"{token}*" for token in tokens[:8])

# ─── /api/stats ────────────────────────────────────────────────────────────────

@app.get("/api/stats")
def stats():
    conn = get_db()
    try:
        s = row(conn, "SELECT * FROM v_stats") or {}
        s["entities"] = (s.get("persons", 0) + s.get("businesses", 0)
                         + s.get("associations", 0) + s.get("services", 0)
                         + s.get("places", 0))
        return s
    finally:
        conn.close()

# ─── /api/entities ─────────────────────────────────────────────────────────────

# Périmètre — cf. collectors/config.py et memory-bank/decisions.md.
# C1 = la commune, C2 = l'intercommunalité et ses communes membres,
# C3 = autorité supra-communale, lien = rattaché à un acteur suivi.
PERIMETRES = ("C1", "C2", "C3", "lien")


@app.get("/api/entities")
def entities(
    type: Optional[str] = None,
    confidence: Optional[str] = None,
    perimetre: Optional[str] = None,
    limit: int = Query(500, le=5000),
    offset: int = 0,
):
    # Filtre publication : whitelist stricte (Phase 3 — dépend du backfill Phase 2)
    filters = ["e.confidence IN ('verified','confirmed')"]
    params: list = []
    if type:
        filters.append("e.type = ?")
        params.append(type)
    if confidence and confidence in ("verified", "confirmed"):
        filters.append("e.confidence = ?")
        params.append(confidence)
    if perimetre:
        # Plusieurs valeurs acceptées : `?perimetre=C1,lien`. Sans filtre, la
        # réponse mêle la commune et les autres communes de l'EPCI — l'appelant
        # doit pouvoir demander explicitement ce qu'il affiche.
        demandes = [p.strip() for p in perimetre.split(",") if p.strip() in PERIMETRES]
        if not demandes:
            raise HTTPException(400, f"perimetre invalide — valeurs: {', '.join(PERIMETRES)}")
        filters.append(f"e.perimetre IN ({','.join('?' for _ in demandes)})")
        params += demandes
    where = "WHERE " + " AND ".join(filters)
    params += [limit, offset]

    conn = get_db()
    try:
        sql = f"""
            SELECT
                e.id, e.type, e.name, e.short_name,
                e.lat, e.lng, e.address, e.confidence, e.created_at,
                e.commune, e.perimetre,
                p.firstname, p.lastname, p.birth_year,
                b.siren, b.naf_code, b.naf_label, b.status AS biz_status,
                b.creation_date, b.legal_form,
                a.rna_id, a.object AS asso_object,
                a.creation_date AS asso_creation_date,
                pl.osm_category, pl.osm_value, pl.tags,
                s.category AS service_category
            FROM entities e
            LEFT JOIN persons      p  ON p.entity_id  = e.id
            LEFT JOIN businesses   b  ON b.entity_id  = e.id
            LEFT JOIN associations a  ON a.entity_id  = e.id
            LEFT JOIN places       pl ON pl.entity_id = e.id
            LEFT JOIN services     s  ON s.entity_id  = e.id
            {where}
            ORDER BY e.name
            LIMIT ? OFFSET ?
        """
        return rows(conn, sql, params)
    finally:
        conn.close()

# ─── /api/entities/{id} ────────────────────────────────────────────────────────

@app.get("/api/entities/{entity_id}")
def entity_detail(entity_id: int = FPath(..., ge=1)):
    conn = get_db()
    try:
        e = row(conn, """
            SELECT
                e.id, e.type, e.name, e.short_name,
                e.lat, e.lng, e.address, e.confidence, e.created_at,
                p.firstname, p.lastname, p.birth_year, p.gender,
                b.siren, b.siret_siege, b.naf_code, b.naf_label,
                b.legal_form, b.status AS biz_status, b.capital,
                b.employees_range, b.creation_date, b.closing_date,
                a.rna_id, a.waldec_id, a.object AS asso_object,
                a.status AS asso_status, a.creation_date AS asso_creation_date,
                pl.osm_id, pl.osm_category, pl.osm_value, pl.tags,
                s.category AS service_category, s.operator, s.opening_hours
            FROM entities e
            LEFT JOIN persons      p  ON p.entity_id  = e.id
            LEFT JOIN businesses   b  ON b.entity_id  = e.id
            LEFT JOIN associations a  ON a.entity_id  = e.id
            LEFT JOIN places       pl ON pl.entity_id = e.id
            LEFT JOIN services     s  ON s.entity_id  = e.id
            WHERE e.id = ?
        """, (entity_id,))
        if not e:
            raise HTTPException(404, "Entité introuvable")

        # Filtre publication : relations verified/confirmed uniquement (Phase 3 — whitelist)
        e["relations"] = rows(conn, """
            SELECT r.id, r.relation_type, r.since, r.until, r.source, r.confidence, r.metadata,
                   f.id AS from_id, f.name AS from_name, f.type AS from_type,
                   t.id AS to_id,   t.name AS to_name,   t.type AS to_type
            FROM relations r
            JOIN entities f ON f.id = r.from_id
            JOIN entities t ON t.id = r.to_id
            WHERE (r.from_id = ? OR r.to_id = ?)
              AND r.confidence IN ('verified','confirmed')
            ORDER BY r.relation_type
        """, (entity_id, entity_id))

        e["flows"] = rows(conn, """
            SELECT ff.id, ff.type, ff.year, ff.amount, ff.description, ff.source,
                   ef.id AS from_id, ef.name AS from_name,
                   et.id AS to_id,   et.name AS to_name
            FROM financial_flows ff
            LEFT JOIN entities ef ON ef.id = ff.from_id
            LEFT JOIN entities et ON et.id = ff.to_id
            WHERE ff.from_id = ? OR ff.to_id = ?
            ORDER BY ff.year DESC
        """, (entity_id, entity_id))

        e["events"] = rows(conn, """
            SELECT ev.id, ev.type, ev.date, ev.title, ev.source, ev.source_url,
                   ee.role
            FROM events ev
            JOIN event_entities ee ON ee.event_id = ev.id
            WHERE ee.entity_id = ?
            ORDER BY ev.date DESC
            LIMIT 50
        """, (entity_id,))

        return e
    finally:
        conn.close()

# ─── /api/search ───────────────────────────────────────────────────────────────

@app.get("/api/search")
def search(q: str = Query(..., min_length=1), limit: int = Query(20, le=100)):
    conn = get_db()
    try:
        return rows(conn, """
            SELECT e.id, e.type, e.name, e.short_name, e.address,
                   e.lat, e.lng, e.confidence
            FROM entities_fts
            JOIN entities e ON e.id = entities_fts.rowid
            WHERE entities_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (fts_query(q), limit))
    finally:
        conn.close()

# ─── /api/layers/{type} ────────────────────────────────────────────────────────

LAYER_TYPES = {"businesses", "associations", "persons", "services", "places", "dvf", "flows"}

@app.get("/api/layers/{layer_type}")
def layer(
    layer_type: str,
    status: Optional[str] = None,
    in_commune: bool = True,
):
    if layer_type not in LAYER_TYPES:
        raise HTTPException(400, f"Type inconnu. Valeurs: {', '.join(LAYER_TYPES)}")

    type_map = {
        "businesses": "business", "associations": "association",
        "persons": "person", "services": "service", "places": "place",
    }

    if layer_type == "dvf":
        conn = get_db()
        try:
            filters = []
            params: list = []
            if in_commune:
                filters.append("lat BETWEEN ? AND ? AND lng BETWEEN ? AND ?")
                params += [COMMUNE_BBOX["lat_min"], COMMUNE_BBOX["lat_max"],
                           COMMUNE_BBOX["lng_min"], COMMUNE_BBOX["lng_max"]]
            where = ("WHERE " + " AND ".join(filters)) if filters else ""
            return rows(conn, f"SELECT * FROM dvf_transactions {where} ORDER BY date DESC LIMIT 1000", params)
        finally:
            conn.close()

    if layer_type == "flows":
        conn = get_db()
        try:
            return rows(conn, "SELECT * FROM v_flows_summary LIMIT 500")
        finally:
            conn.close()

    entity_type = type_map[layer_type]
    # Filtre publication : whitelist stricte confidence (Phase 3)
    filters = ["e.type = ?", "e.confidence IN ('verified','confirmed')"]
    params: list = [entity_type]

    if in_commune:
        filters.append("e.lat BETWEEN ? AND ? AND e.lng BETWEEN ? AND ?")
        params += [COMMUNE_BBOX["lat_min"], COMMUNE_BBOX["lat_max"],
                   COMMUNE_BBOX["lng_min"], COMMUNE_BBOX["lng_max"]]

    if status and layer_type == "businesses":
        filters.append("b.status = ?")
        params.append(status)

    where = "WHERE " + " AND ".join(filters)

    conn = get_db()
    try:
        sql = f"""
            SELECT
                e.id, e.type, e.name, e.short_name,
                e.lat, e.lng, e.address, e.confidence,
                p.firstname, p.lastname,
                b.siren, b.naf_code, b.naf_label, b.status AS biz_status,
                b.creation_date,
                a.rna_id, a.object AS asso_object,
                a.creation_date AS asso_creation_date,
                pl.osm_category, pl.osm_value, pl.tags,
                s.category AS service_category
            FROM entities e
            LEFT JOIN persons      p  ON p.entity_id  = e.id
            LEFT JOIN businesses   b  ON b.entity_id  = e.id
            LEFT JOIN associations a  ON a.entity_id  = e.id
            LEFT JOIN places       pl ON pl.entity_id = e.id
            LEFT JOIN services     s  ON s.entity_id  = e.id
            {where}
            ORDER BY e.name
        """
        return rows(conn, sql, params)
    finally:
        conn.close()

# ─── /api/graph ────────────────────────────────────────────────────────────────

@app.get("/api/graph")
@limiter.limit("30/minute;200/hour")
def graph(
    request: StarletteRequest,
    entity_id: Optional[int] = None,
    depth: int = Query(2, ge=1, le=4),
    min_relations: int = Query(1, ge=1),
    limit: int = Query(180, ge=20, le=500),
):
    # En vue focalisée, cap pour éviter la saturation
    MAX_NEIGHBORS = 50   # voisins directs max au 1er niveau
    MAX_NODES     = 120  # total nœuds max dans le sous-graphe

    conn = get_db()
    try:
        if entity_id:
            # Sous-graphe centré sur une entité
            all_entity_ids = {entity_id}
            frontier = {entity_id}
            for step in range(depth):
                if not frontier:
                    break
                placeholders = ",".join("?" * len(frontier))
                neighbors = rows(conn, f"""
                    SELECT DISTINCT
                        CASE WHEN from_id IN ({placeholders}) THEN to_id ELSE from_id END AS nid
                    FROM relations
                    WHERE from_id IN ({placeholders}) OR to_id IN ({placeholders})
                """, list(frontier) * 3)
                new_ids = {r["nid"] for r in neighbors} - all_entity_ids

                # Au premier niveau, limiter aux MAX_NEIGHBORS les plus connectés
                if step == 0 and len(new_ids) > MAX_NEIGHBORS:
                    nid_list = list(new_ids)
                    ph2 = ",".join("?" * len(nid_list))
                    ranked = rows(conn, f"""
                        SELECT e.id, COUNT(*) AS deg
                        FROM entities e
                        JOIN relations r ON r.from_id = e.id OR r.to_id = e.id
                        WHERE e.id IN ({ph2})
                        GROUP BY e.id
                        ORDER BY deg DESC
                        LIMIT {MAX_NEIGHBORS}
                    """, nid_list)
                    new_ids = {r["id"] for r in ranked}

                # Cap total nœuds : garder les plus connectés si dépassement
                if len(all_entity_ids) + len(new_ids) > MAX_NODES:
                    remaining = MAX_NODES - len(all_entity_ids)
                    if remaining <= 0:
                        break
                    nid_list2 = list(new_ids)
                    ph3 = ",".join("?" * len(nid_list2))
                    ranked2 = rows(conn, f"""
                        SELECT e.id, COUNT(*) AS deg
                        FROM entities e
                        JOIN relations r ON r.from_id = e.id OR r.to_id = e.id
                        WHERE e.id IN ({ph3})
                        GROUP BY e.id
                        ORDER BY deg DESC
                        LIMIT {remaining}
                    """, nid_list2)
                    new_ids = {r["id"] for r in ranked2}

                frontier = new_ids
                all_entity_ids |= new_ids

            id_list = list(all_entity_ids)
            ph = ",".join("?" * len(id_list))
            # Filtre publication : nodes verified/confirmed uniquement (Phase 3)
            nodes = rows(conn, f"""
                SELECT e.id, e.type, e.name, e.short_name, e.lat, e.lng, e.confidence,
                       p.firstname, p.lastname,
                       b.siren, b.naf_code, b.naf_label, b.status AS biz_status,
                       a.rna_id
                FROM entities e
                LEFT JOIN persons p ON p.entity_id = e.id
                LEFT JOIN businesses b ON b.entity_id = e.id
                LEFT JOIN associations a ON a.entity_id = e.id
                WHERE e.id IN ({ph})
                  AND e.confidence IN ('verified','confirmed')
            """, id_list)
            # Links : whitelist stricte relations (Phase 3)
            links = rows(conn, f"""
                SELECT id, from_id, to_id, relation_type, confidence, source
                FROM relations
                WHERE from_id IN ({ph}) AND to_id IN ({ph})
                  AND confidence IN ('verified','confirmed')
            """, id_list + id_list)

        else:
            # Vue globale filtrée par min_relations — filtre publication Phase 3
            nodes = rows(conn, """
                SELECT e.id, e.type, e.name, e.short_name, e.lat, e.lng, e.confidence,
                       p.firstname, p.lastname,
                       b.siren, b.naf_code, b.naf_label, b.status AS biz_status,
                       a.rna_id,
                       COUNT(DISTINCT r.id) AS degree
                FROM entities e
                LEFT JOIN persons p ON p.entity_id = e.id
                LEFT JOIN businesses b ON b.entity_id = e.id
                LEFT JOIN associations a ON a.entity_id = e.id
                LEFT JOIN relations r ON (r.from_id = e.id OR r.to_id = e.id)
                    AND r.confidence IN ('verified','confirmed')
                WHERE e.confidence IN ('verified','confirmed')
                GROUP BY e.id
                HAVING degree >= ?
                ORDER BY degree DESC
                LIMIT ?
            """, (min_relations, limit))

            id_list = [n["id"] for n in nodes]
            if id_list:
                ph = ",".join("?" * len(id_list))
                links = rows(conn, f"""
                    SELECT id, from_id, to_id, relation_type, confidence, source
                    FROM relations
                    WHERE from_id IN ({ph}) AND to_id IN ({ph})
                      AND confidence IN ('verified','confirmed')
                """, id_list + id_list)
            else:
                links = []

        return {"nodes": nodes, "links": links}
    finally:
        conn.close()

# ─── /api/events ───────────────────────────────────────────────────────────────

@app.get("/api/events")
def events(
    type: Optional[str] = None,
    limit: int = Query(50, le=500),
):
    filters = []
    params: list = []
    if type:
        filters.append("e.type = ?")
        params.append(type)
    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    params.append(limit)

    conn = get_db()
    try:
        event_rows = rows(conn, f"""
            SELECT e.id, e.type, e.date, e.title,
                   substr(e.content, 1, 1200) AS content,
                   length(e.content) AS content_length,
                   e.source, e.source_url, e.metadata
            FROM events e
            {where}
            ORDER BY e.date DESC
            LIMIT ?
        """, params)
        for event in event_rows:
            event["metadata"] = parse_json_field(event.get("metadata"), {})
        return event_rows
    finally:
        conn.close()

@app.get("/api/events/search")
def event_search(
    q: str = Query(..., min_length=2),
    limit: int = Query(50, ge=1, le=200),
    civic: bool = False,
):
    filters = ["events_fts MATCH ?"]
    params: list = [fts_query(q)]
    if civic:
        civic_types = (
            "conseil_municipal",
            "deliberation",
            "délibérations_cc",
            "pv_cc",
            "marché_public",
            "election",
        )
        filters.append("e.type IN ({})".format(",".join("?" for _ in civic_types)))
        params.extend(civic_types)
    params.append(limit)

    conn = get_db()
    try:
        event_rows = rows(conn, f"""
            SELECT e.id, e.type, e.date, e.title,
                   substr(e.content, 1, 1200) AS content,
                   e.source, e.source_url, e.metadata,
                   snippet(events_fts, 1, '<mark>', '</mark>', '…', 16) AS snippet
            FROM events_fts
            JOIN events e ON e.id = events_fts.rowid
            WHERE {" AND ".join(filters)}
            ORDER BY rank
            LIMIT ?
        """, params)
        for event in event_rows:
            event["metadata"] = parse_json_field(event.get("metadata"), {})
        return event_rows
    finally:
        conn.close()

# ─── /api/dvf ──────────────────────────────────────────────────────────────────

@app.get("/api/dvf")
def dvf(
    year: Optional[int] = None,
    limit: int = Query(500, le=5000),
):
    filters = []
    params: list = []
    if year:
        filters.append("year = ?")
        params.append(year)
    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    params.append(limit)

    conn = get_db()
    try:
        return rows(conn, f"""
            SELECT * FROM dvf_transactions
            {where}
            ORDER BY date DESC
            LIMIT ?
        """, params)
    finally:
        conn.close()

# ─── /api/flows ────────────────────────────────────────────────────────────────

@app.get("/api/flows")
def flows(
    year: Optional[int] = None,
    type: Optional[str] = None,
):
    filters = []
    params: list = []
    if year:
        filters.append("ff.year = ?")
        params.append(year)
    if type:
        filters.append("ff.type = ?")
        params.append(type)
    where = ("WHERE " + " AND ".join(filters)) if filters else ""

    conn = get_db()
    try:
        return rows(conn, f"""
            SELECT ff.id, ff.type, ff.year, ff.amount, ff.description, ff.source,
                   ef.id AS from_id, ef.name AS from_name,
                   et.id AS to_id,   et.name AS to_name
            FROM financial_flows ff
            LEFT JOIN entities ef ON ef.id = ff.from_id
            LEFT JOIN entities et ON et.id = ff.to_id
            {where}
            ORDER BY ff.year DESC, ff.amount DESC
        """, params)
    finally:
        conn.close()

# ─── /api/marches ─────────────────────────────────────────────────────────────

@app.get("/api/marches")
def marches(
    acheteur: Optional[str] = None,
    titulaire: Optional[str] = None,
    year: Optional[int] = None,
    limit: int = 200,
):
    filters = []
    params: list = []
    if acheteur:
        filters.append("(mp.acheteur_siren=? OR mp.acheteur_nom LIKE ?)")
        params += [acheteur, f"%{acheteur}%"]
    if titulaire:
        filters.append("(mp.titulaire_siren=? OR mp.titulaire_nom LIKE ?)")
        params += [titulaire, f"%{titulaire}%"]
    if year:
        filters.append("substr(mp.date_notif,1,4)=?")
        params.append(str(year))
    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    params.append(limit)
    conn = get_db()
    try:
        return rows(conn, f"""
            SELECT mp.id, mp.acheteur_siren, mp.acheteur_nom,
                   mp.titulaire_siren, mp.titulaire_nom,
                   mp.objet, mp.nature, mp.procedure, mp.montant,
                   mp.cpv, mp.cpv_label, mp.date_notif, mp.date_pub,
                   mp.duree_mois, mp.lieu_exec, mp.source, mp.source_url,
                   mp.raw_id, mp.event_id,
                   ea.id AS acheteur_entity_id,
                   et.id AS titulaire_entity_id
            FROM marches_publics mp
            LEFT JOIN entities ea ON ea.id = mp.acheteur_id
            LEFT JOIN entities et ON et.id = mp.titulaire_id
            {where}
            ORDER BY mp.date_notif DESC
            LIMIT ?
        """, params)
    finally:
        conn.close()

# ─── /api/budget ───────────────────────────────────────────────────────────────

@app.get("/api/budget")
def budget(year: Optional[int] = None):
    conn = get_db()
    try:
        if year:
            return rows(conn, "SELECT * FROM budget_annuel WHERE year=? ORDER BY categorie, compte", (year,))
        return rows(conn, "SELECT * FROM budget_annuel ORDER BY year, categorie, compte")
    except Exception:
        return []
    finally:
        conn.close()

# ─── /api/ofgl ─────────────────────────────────────────────────────────────────

@app.get("/api/ofgl")
def ofgl(year: Optional[int] = None, agregat: Optional[str] = None):
    conn = get_db()
    try:
        filters, params = [], []
        if year:
            filters.append("year = ?"); params.append(year)
        if agregat:
            filters.append("agregat = ?"); params.append(agregat)
        where = ("WHERE " + " AND ".join(filters)) if filters else ""
        return rows(conn, f"SELECT * FROM ofgl_agregats {where} ORDER BY year, agregat", params)
    except Exception:
        return []
    finally:
        conn.close()

# ─── /api/syntheses ────────────────────────────────────────────────────────────

@app.get("/api/syntheses")
def syntheses_list():
    if not SYNTHESES_DIR.exists():
        return []
    result = []
    for f in SYNTHESES_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            result.append({
                "entity_id": data.get("_entity_id"),
                "entity_name": data.get("_entity_name"),
                "entity_type": data.get("_entity_type"),
                "generated": data.get("_generated"),
                "niveau_interet": data.get("niveau_interet"),
            })
        except Exception:
            pass
    return result

@app.get("/api/syntheses/{entity_id}")
def synthesis(entity_id: int = FPath(..., ge=1)):
    path = SYNTHESES_DIR / f"{entity_id}.json"
    if not path.exists():
        raise HTTPException(404, "Synthèse non disponible")
    return json.loads(path.read_text())

# ─── /api/synthesize (Claude API live) ─────────────────────────────────────────

class SynthesizeRequest(BaseModel):
    topic: str
    context: str = ""

SYSTEM_PROMPT = (
    "Tu es un assistant de veille citoyenne pour la commune de "
    f"{COMMUNE_NAME} ({COMMUNE_INSEE}, département {DEPARTEMENT}). "
    "Tu analyses des données OSINT locales (SIRENE, RNA, DVF, délibérations CM, subventions). "
    "Tu réponds en français, de manière factuelle, structurée et concise. "
    "Tu ne spécules pas au-delà des données fournies."
)

def _db_context_for_topic(topic: str, conn) -> str:
    """Charge des données réelles de la DB selon le topic demandé."""
    topic_l = topic.lower()
    parts = []

    if any(k in topic_l for k in ("flux", "subvention", "financ", "budget")):
        data = rows(conn, """
            SELECT ff.type, ff.year, ff.amount, ef.name AS from_name, et.name AS to_name, ff.description
            FROM financial_flows ff
            LEFT JOIN entities ef ON ef.id = ff.from_id
            LEFT JOIN entities et ON et.id = ff.to_id
            ORDER BY ff.year DESC, ff.amount DESC LIMIT 50
        """)
        if data:
            lines = [f"- {r['year']} | {r['type']} | {r['amount']} € | {r['to_name']} ({r['description'] or ''})" for r in data]
            parts.append("FLUX FINANCIERS (50 derniers) :\n" + "\n".join(lines))

    if any(k in topic_l for k in ("immobilier", "dvf", "terrain", "foncier")):
        data = rows(conn, """
            SELECT date, nature_mutation, nature_bien, price, surface_terrain, lieu_dit, cadastre_ref
            FROM dvf_transactions ORDER BY date DESC LIMIT 40
        """)
        if data:
            lines = [f"- {r['date']} | {r['nature_mutation']} | {r['nature_bien']} | {r['price']} € | {r['lieu_dit']} ({r['cadastre_ref']})" for r in data]
            parts.append("TRANSACTIONS DVF (40 dernières) :\n" + "\n".join(lines))

    if any(k in topic_l for k in ("associat", "tissu asso")):
        data = rows(conn, """
            SELECT e.name, a.object, a.creation_date, a.status
            FROM associations a JOIN entities e ON e.id = a.entity_id
            ORDER BY e.name LIMIT 80
        """)
        if data:
            lines = [f"- {r['name']} | {r['object'] or '?'} | créée {r['creation_date'] or '?'} | {r['status'] or '?'}" for r in data]
            parts.append("ASSOCIATIONS :\n" + "\n".join(lines))

    if any(k in topic_l for k in ("économi", "entreprise", "tissu éco")):
        data = rows(conn, """
            SELECT e.name, b.naf_label, b.creation_date, b.status, b.employees_range
            FROM businesses b JOIN entities e ON e.id = b.entity_id
            WHERE b.status = 'A' ORDER BY e.name LIMIT 80
        """)
        if data:
            lines = [f"- {r['name']} | {r['naf_label'] or '?'} | créée {r['creation_date'] or '?'} | {r['employees_range'] or '?'} sal." for r in data]
            parts.append("ENTREPRISES ACTIVES :\n" + "\n".join(lines))

    if any(k in topic_l for k in ("réseau", "influence", "person", "élu", "clé")):
        data = rows(conn, """
            SELECT e.name, p.firstname, p.lastname,
                   COUNT(DISTINCT r.id) AS nb_relations
            FROM persons p
            JOIN entities e ON e.id = p.entity_id
            LEFT JOIN relations r ON r.from_id = e.id OR r.to_id = e.id
            GROUP BY e.id ORDER BY nb_relations DESC LIMIT 40
        """)
        if data:
            lines = [f"- {r['firstname'] or ''} {r['lastname'] or r['name']} | {r['nb_relations']} relations" for r in data]
            parts.append("PERSONNES LES PLUS CONNECTÉES :\n" + "\n".join(lines))

    if any(k in topic_l for k in ("délibér", "cm ", "conseil municipal", "générale", "générale")):
        data = rows(conn, """
            SELECT date, title, source_url FROM events
            WHERE type = 'deliberation'
            ORDER BY date DESC LIMIT 30
        """)
        if data:
            lines = [f"- {r['date']} | {r['title']}" for r in data]
            parts.append("DÉLIBÉRATIONS CM (30 dernières) :\n" + "\n".join(lines))

    return "\n\n".join(parts)

def _build_user_msg(req: SynthesizeRequest, db_ctx: str = "") -> str:
    parts = []
    if db_ctx:
        parts.append(f"DONNÉES DE LA BASE :\n{db_ctx}")
    if req.context:
        parts.append(f"CONTEXTE UTILISATEUR :\n{req.context}")
    parts.append(f"DEMANDE : {req.topic}")
    return "\n\n".join(parts)

@app.post("/api/synthesize")
@limiter.limit("10/minute;50/hour")
def synthesize(request: StarletteRequest, req: SynthesizeRequest):
    """Groq primaire (llama-3.3-70b-versatile) → Anthropic fallback (cf. decisions.md)."""
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    groq_key      = os.environ.get("GROQ_API_KEY")

    if not anthropic_key and not groq_key:
        raise HTTPException(503, "Aucune clé IA configurée (ANTHROPIC_API_KEY ou GROQ_API_KEY)")

    conn = get_db()
    try:
        db_ctx = _db_context_for_topic(req.topic, conn)
    finally:
        conn.close()
    user_msg = _build_user_msg(req, db_ctx)

    # Groq primaire — free tier (14 400 req/j, économique)
    if groq_key:
        try:
            from groq import Groq
            client = Groq(api_key=groq_key)
            msg = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": user_msg},
                ],
            )
            return {"synthesis": msg.choices[0].message.content, "provider": "groq"}
        except Exception as e:
            if not anthropic_key:
                raise HTTPException(500, str(e))
            # Fallback Anthropic

    # Anthropic fallback — meilleure qualité, coût
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=anthropic_key)
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        return {"synthesis": msg.content[0].text, "provider": "claude"}
    except Exception as e:
        raise HTTPException(500, str(e))

# ─── /api/candidates ───────────────────────────────────────────────────────────

@app.get("/api/candidates")
def candidates(
    status: str = "pending",
    signal: Optional[str] = None,
):
    filters = ["rc.review_status = ?"]
    params: list = [status]
    if signal:
        filters.append("rc.signal = ?")
        params.append(signal)
    where = "WHERE " + " AND ".join(filters)

    conn = get_db()
    try:
        return rows(conn, f"""
            SELECT rc.id, rc.relation_type, rc.confidence, rc.signal,
                   rc.signal_detail, rc.score, rc.review_status, rc.created_at,
                   f.id AS from_id, f.name AS from_name, f.type AS from_type,
                   t.id AS to_id,   t.name AS to_name,   t.type AS to_type
            FROM relation_candidates rc
            JOIN entities f ON f.id = rc.from_id
            JOIN entities t ON t.id = rc.to_id
            {where}
            ORDER BY rc.score DESC
        """, params)
    finally:
        conn.close()

class ReviewRequest(BaseModel):
    action: str   # "accept" | "reject" | "ignore"
    note: str = ""

_opt_bearer = HTTPBearer(auto_error=False)

def optional_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(_opt_bearer)):
    """Utilisateur JWT si présent et valide, sinon None (pas d'erreur)."""
    if not creds:
        return None
    try:
        return require_auth(creds)
    except HTTPException:
        return None

def _check_admin(x_admin_key: Optional[str], user: Optional[dict] = None,
                 allow_validator: bool = False):
    """Autorise : JWT admin (rôle), JWT validateur si allow_validator,
    ou clé ADMIN_KEY (fallback scripts/CLI)."""
    if user:
        if user.get("role") == "admin":
            return
        if allow_validator and user.get("role") in ("validator", "contributor"):
            return
    if not ADMIN_KEY:
        raise HTTPException(403, "Endpoint d'écriture désactivé — configurer ADMIN_KEY en production")
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(403, "Réservé à l'admin (JWT rôle admin ou clé admin)")

def _read_json_file(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def _public_snapshot_status():
    from scripts.build_public_snapshot import DEFAULT_OUT, RULES_PATH

    stats_path = DEFAULT_OUT / "stats.json"
    report_path = DEFAULT_OUT / "review_report.json"
    rules = _read_json_file(RULES_PATH, {})
    stats = _read_json_file(stats_path)
    report = _read_json_file(report_path, {})
    return {
        "exists": stats is not None,
        "output_dir": str(DEFAULT_OUT),
        "rules_path": str(RULES_PATH),
        "project": rules.get("project", {}),
        "stats": stats,
        "exclusions": (stats or {}).get("exclusions", {}),
        "rules": report.get("rules", {}),
    }

def _sync_public_static(src, root) -> dict:
    """Copie les fichiers servables du snapshot (public-data/) vers
    public/static/data/ — l'app publique les sert tels quels.
    Élimine l'étape manuelle `cp public-data/* public/static/data/`."""
    import shutil

    dest = root / "public" / "static" / "data"
    (dest / "layers").mkdir(parents=True, exist_ok=True)
    (dest / "entite").mkdir(parents=True, exist_ok=True)
    copied = []
    for f in sorted(src.glob("*.json")):
        shutil.copy2(f, dest / f.name)
        copied.append(f.name)
    # Le README est le dictionnaire de données : il accompagne les JSON, il ne
    # reste pas dans le dépôt. Il était exclu de la synchro, si bien que
    # `public/static/data/README.md` datait du 26/07/2026 et annonçait des
    # chiffres faux à côté de fichiers à jour.
    readme = src / "README.md"
    if readme.exists():
        shutil.copy2(readme, dest / "README.md")
        copied.append("README.md")
    for f in sorted((src / "layers").glob("*.geojson")):
        shutil.copy2(f, dest / "layers" / f.name)
        copied.append(f"layers/{f.name}")

    # `entite/` était absent de la synchro : les fiches acteurs servies par le
    # site public dataient de la dernière copie manuelle, et une entité retirée
    # de la publication gardait sa page en ligne. Ce répertoire est donc mis en
    # MIROIR — copie + suppression de ce qui n'est plus publié.
    fiches = {f.name for f in (src / "entite").glob("*.json")}
    for f in sorted((src / "entite").glob("*.json")):
        shutil.copy2(f, dest / "entite" / f.name)
        copied.append(f"entite/{f.name}")
    retirees = []
    for f in sorted((dest / "entite").glob("*.json")):
        if f.name not in fiches:
            f.unlink()
            retirees.append(f.name)
    return {"dest": str(dest), "files": copied, "count": len(copied),
            "fiches_retirees": retirees}

@app.get("/api/admin/public-snapshot")
def public_snapshot_status(x_admin_key: Optional[str] = Header(default=None),
                           user=Depends(optional_user)):
    _check_admin(x_admin_key, user)
    return _public_snapshot_status()

@app.post("/api/admin/public-snapshot/generate")
def generate_public_snapshot(x_admin_key: Optional[str] = Header(default=None),
                             user=Depends(optional_user)):
    _check_admin(x_admin_key, user)
    from scripts.build_public_snapshot import DEFAULT_OUT, ROOT, build_snapshot

    stats = build_snapshot(DEFAULT_OUT)
    synced = _sync_public_static(DEFAULT_OUT, ROOT)   # snapshot → site public, 1 clic
    return {
        "ok": True,
        "output_dir": str(DEFAULT_OUT),
        "stats": stats,
        "exclusions": stats.get("exclusions", {}),
        "synced": synced,
    }

@app.post("/api/candidates/{candidate_id}/review")
def review_candidate(
    candidate_id: int = FPath(..., ge=1),
    req: ReviewRequest = ...,
    x_admin_key: Optional[str] = Header(default=None),
    user=Depends(optional_user),
):
    _check_admin(x_admin_key, user, allow_validator=True)
    if req.action not in ("accept", "reject", "ignore"):
        raise HTTPException(400, "action doit être: accept, reject ou ignore")

    status_map = {"accept": "accepted", "reject": "rejected", "ignore": "ignored"}
    new_status = status_map[req.action]

    conn = get_db_rw()
    try:
        candidate = row(conn, "SELECT * FROM relation_candidates WHERE id = ?", (candidate_id,))
        if not candidate:
            raise HTTPException(404, "Candidat introuvable")

        conn.execute("""
            UPDATE relation_candidates
            SET review_status = ?, reviewed_at = datetime('now'), review_note = ?
            WHERE id = ?
        """, (new_status, req.note, candidate_id))

        if req.action == "accept":
            conn.execute("""
                INSERT OR IGNORE INTO relations
                    (from_id, to_id, relation_type, confidence, source, metadata)
                VALUES (?, ?, ?, ?, 'candidate', ?)
            """, (
                candidate["from_id"],
                candidate["to_id"],
                candidate["relation_type"],
                candidate["confidence"],
                json.dumps({"signal": candidate["signal"], "signal_detail": candidate["signal_detail"]}),
            ))

        conn.commit()
        return {"ok": True, "status": new_status}
    finally:
        conn.close()

# ─── /api/atelier/stats ────────────────────────────────────────────────────────

@app.get("/api/atelier/stats")
def atelier_stats(user=Depends(require_auth)):
    conn = get_db()
    try:
        total = row(conn, "SELECT COUNT(*) AS n FROM entities")["n"]
        by_status = rows(conn, """
            SELECT validation_status, COUNT(*) AS n
            FROM entities
            GROUP BY validation_status
        """)
        result = {"total": total}
        for r in by_status:
            result[r["validation_status"] or "unverified"] = r["n"]
        # Le total seul ne dit plus rien depuis l'élargissement à l'EPCI :
        # l'atelier doit savoir combien de fiches relèvent de la commune.
        result["perimetre"] = {
            (r["perimetre"] or "non_classe"): r["n"]
            for r in rows(conn, "SELECT perimetre, COUNT(*) AS n FROM entities "
                                "GROUP BY perimetre")
        }
        return result
    finally:
        conn.close()

# ─── /api/atelier/workqueue ────────────────────────────────────────────────────

VALID_STATUSES = ("draft", "unverified", "reviewing", "verified", "published", "rejected")

@app.get("/api/atelier/workqueue")
def atelier_workqueue(
    status: str = Query("unverified"),
    type: Optional[str] = None,
    perimetre: Optional[str] = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    user=Depends(require_auth),
):
    if status not in VALID_STATUSES:
        raise HTTPException(400, f"status invalide — valeurs: {', '.join(VALID_STATUSES)}")

    filters = ["(e.validation_status = ? OR (e.validation_status IS NULL AND ? = 'unverified'))"]
    params: list = [status, status]
    if type:
        filters.append("e.type = ?")
        params.append(type)
    # Sans ce filtre, la file de travail noie les entités de la commune sous
    # les 6 500 de l'intercommunalité : on ne valide pas une fiche C2 avec le
    # même soin ni dans le même but qu'une fiche C1.
    if perimetre:
        demandes = [p.strip() for p in perimetre.split(",") if p.strip() in PERIMETRES]
        if not demandes:
            raise HTTPException(400, f"perimetre invalide — valeurs: {', '.join(PERIMETRES)}")
        filters.append(f"e.perimetre IN ({','.join('?' for _ in demandes)})")
        params += demandes
    where = "WHERE " + " AND ".join(filters)

    conn = get_db()
    try:
        total = row(conn, f"SELECT COUNT(*) AS n FROM entities e {where}", params)["n"]
        items = rows(conn, f"""
            SELECT
                e.id, e.type, e.name, e.short_name, e.address,
                e.confidence, e.validation_status, e.responsible, e.created_at,
                e.commune, e.perimetre,
                p.firstname, p.lastname,
                b.siren, b.naf_label, b.status AS biz_status,
                a.rna_id, a.object AS asso_object,
                (SELECT COUNT(*) FROM relations WHERE from_id=e.id OR to_id=e.id) AS rel_count,
                (SELECT COUNT(*) FROM audit_log WHERE entity_id=e.id) AS edit_count,
                (SELECT COUNT(*) FROM contacts WHERE entity_id=e.id) AS contacts_count,
                (SELECT value FROM contacts WHERE entity_id=e.id AND type='website' LIMIT 1) AS website
            FROM entities e
            LEFT JOIN persons      p ON p.entity_id  = e.id
            LEFT JOIN businesses   b ON b.entity_id  = e.id
            LEFT JOIN associations a ON a.entity_id  = e.id
            {where}
            ORDER BY e.type, e.name
            LIMIT ? OFFSET ?
        """, params + [limit, offset])
        return {"total": total, "items": items, "offset": offset, "limit": limit}
    finally:
        conn.close()

# ─── PATCH /api/atelier/entities/{id}/status ──────────────────────────────────

class ValidationStatusUpdate(BaseModel):
    validation_status: str
    note: str = ""

@app.patch("/api/atelier/entities/{entity_id}/status")
def atelier_update_status(
    entity_id: int = FPath(..., ge=1),
    req: ValidationStatusUpdate = ...,
    user=Depends(require_auth),
):
    if req.validation_status not in VALID_STATUSES:
        raise HTTPException(400, f"validation_status invalide — valeurs: {', '.join(VALID_STATUSES)}")

    conn = get_db_rw()
    try:
        entity = row(conn, "SELECT id, validation_status FROM entities WHERE id=?", (entity_id,))
        if not entity:
            raise HTTPException(404, "Entité introuvable")

        old_status = entity["validation_status"] or "unverified"
        conn.execute(
            "UPDATE entities SET validation_status=?, updated_at=datetime('now') WHERE id=?",
            (req.validation_status, entity_id),
        )
        conn.execute("""
            INSERT INTO audit_log(user_id, entity_id, table_name, action, field, old_value, new_value)
            VALUES(?,?,?,?,?,?,?)
        """, (user["id"], entity_id, "entities", "update", "validation_status",
              old_status, req.validation_status))
        conn.commit()
        return {"ok": True, "id": entity_id, "validation_status": req.validation_status}
    finally:
        conn.close()

# ─── Données importées (délibs / flux / marchés) — revue & annotation ─────────
# Les collecteurs sont INSERT-only ; l'annotation vit dans une table à part
# (annotations) pour ne jamais écraser les données sources. cf. CARTE_PRODUIT §4.

DONNEES_TYPES = ("deliberation", "flow", "marche")
ANNOTATION_STATUSES = ("pending", "validated", "rejected")

# ─── Corrections : rectifier sans écraser ────────────────────────────────────
# Rejeter une donnée fausse la fait disparaître ; le plus souvent ce qu'il faut
# c'est la rectifier — un statut de cession, un montant OCR aberrant, une date.
# La correction est stockée à part (annotations.corrections) et n'est appliquée
# qu'à la publication : la ligne du collecteur reste le reflet de la source.
#
# Liste blanche par type : on ne corrige QUE ce que la page publique affiche.
# Ouvrir tous les champs, ce serait rouvrir la porte à l'écrasement par l'API.
CHAMPS_CORRIGEABLES = {
    "deliberation": {"date": "date", "title": "texte", "source_url": "url",
                     "montant": "montant"},
    "flow": {"year": "annee", "amount": "montant", "description": "texte",
             "statut": "statut", "type_norm": "texte_court"},
    "marche": {"date_notif": "date", "montant": "montant", "objet": "texte",
               "titulaire_nom": "texte_court", "acheteur_nom": "texte_court"},
}
STATUTS_FLUX = ("demande", "engage", "realise")


def _valide_correction(object_type: str, champ: str, valeur):
    """Une correction mal typée en base est pire que la donnée fausse d'origine.

    Renvoie la valeur normalisée, ou lève une HTTPException. `None` est admis
    partout : il signifie « annuler cette correction ».
    """
    genre = CHAMPS_CORRIGEABLES.get(object_type, {}).get(champ)
    if genre is None:
        raise HTTPException(400, f"champ non corrigeable pour {object_type} : {champ}")
    if valeur is None or valeur == "":
        return None
    if genre == "date":
        s = str(valeur).strip()
        try:
            datetime.strptime(s, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, f"{champ} : date attendue au format AAAA-MM-JJ")
        return s
    if genre == "annee":
        try:
            n = int(valeur)
        except (TypeError, ValueError):
            raise HTTPException(400, f"{champ} : année attendue")
        if not 1900 <= n <= 2100:
            raise HTTPException(400, f"{champ} : année hors plage (1900-2100)")
        return n
    if genre == "montant":
        try:
            v = float(str(valeur).replace(",", ".").replace(" ", "").replace(" ", ""))
        except (TypeError, ValueError):
            raise HTTPException(400, f"{champ} : montant attendu")
        if v < 0:
            raise HTTPException(400, f"{champ} : montant négatif")
        return round(v, 2)
    if genre == "url":
        s = str(valeur).strip()
        if not s.startswith(("http://", "https://")):
            raise HTTPException(400, f"{champ} : URL http(s) attendue")
        return s[:1000]
    if genre == "statut":
        s = str(valeur).strip()
        if s not in STATUTS_FLUX:
            raise HTTPException(400, f"{champ} : valeurs admises — {', '.join(STATUTS_FLUX)}")
        return s
    if genre == "texte_court":
        return " ".join(str(valeur).split())[:255]
    return " ".join(str(valeur).split())[:4000]


def _donnees_query(object_type: str, limit: int):
    if object_type == "deliberation":
        return ("""
            SELECT e.id, e.type, e.date, e.title,
                   substr(e.content, 1, 400) AS excerpt,
                   e.source, e.source_url,
                   -- Montant tel que la page publique le calcule : le plus élevé
                   -- des montants cités. C'est celui qu'on corrige.
                   -- Les parsers successifs ont écrit `montant` ou `value` :
                   -- les deux clés sont acceptées, comme à la publication.
                   (SELECT MAX(CAST(COALESCE(json_extract(m.value, '$.montant'),
                                             json_extract(m.value, '$.value')) AS REAL))
                      FROM json_each(json_extract(e.metadata, '$.montants')) m
                     WHERE json_valid(e.metadata)) AS montant
            FROM events e
            WHERE e.type IN ('deliberation','conseil_municipal','délibérations_cc','pv_cc')
            ORDER BY e.date DESC
            LIMIT ?
        """, [limit])
    if object_type == "flow":
        return ("""
            SELECT ff.id, ff.type, ff.year, ff.amount, ff.description,
                   ff.source, ff.confidence,
                   ef.name AS from_name, et.name AS to_name
            FROM financial_flows ff
            LEFT JOIN entities ef ON ef.id = ff.from_id
            LEFT JOIN entities et ON et.id = ff.to_id
            ORDER BY ff.year DESC, ff.amount DESC
            LIMIT ?
        """, [limit])
    # marche
    return ("""
        SELECT mp.id, mp.acheteur_nom, mp.titulaire_nom, mp.objet,
               mp.montant, mp.procedure, mp.date_notif, mp.source, mp.source_url
        FROM marches_publics mp
        ORDER BY mp.date_notif DESC
        LIMIT ?
    """, [limit])


@app.get("/api/atelier/donnees")
def atelier_donnees(
    type: str = Query(..., description="deliberation | flow | marche"),
    status: Optional[str] = None,
    limit: int = Query(200, le=1000),
    user=Depends(require_auth),
):
    if type not in DONNEES_TYPES:
        raise HTTPException(400, f"type invalide — valeurs: {', '.join(DONNEES_TYPES)}")
    if status and status not in ANNOTATION_STATUSES:
        raise HTTPException(400, f"status invalide — valeurs: {', '.join(ANNOTATION_STATUSES)}")

    sql, params = _donnees_query(type, limit)
    conn = get_db()
    try:
        items = rows(conn, sql, params)
        ann = {
            a["object_id"]: a for a in rows(conn,
                "SELECT object_id, review_status, confidence, note, corrections, "
                "reviewed_by, reviewed_at FROM annotations WHERE object_type=?", (type,))
        }
        out = []
        for it in items:
            a = ann.get(it["id"])
            if a:
                a = dict(a)
                a["corrections"] = parse_json_field(a.get("corrections"), {}) or {}
            it["annotation"] = a or {"review_status": "pending", "confidence": None,
                                     "note": "", "corrections": {},
                                     "reviewed_by": None, "reviewed_at": None}
            if status and it["annotation"]["review_status"] != status:
                continue
            out.append(it)
        return out
    finally:
        conn.close()


@app.get("/api/atelier/champs-corrigeables")
def atelier_champs_corrigeables(user=Depends(require_auth)):
    """Contrat des corrections : l'atelier construit ses champs là-dessus.

    Le front ne devine pas ce qui est éditable — sinon il propose un champ que
    l'API refusera, ou il en oublie un qu'elle accepterait.
    """
    return {"champs": CHAMPS_CORRIGEABLES, "statuts_flux": list(STATUTS_FLUX)}


class AnnotationUpdate(BaseModel):
    review_status: Optional[str] = None
    confidence: Optional[str] = None
    note: Optional[str] = None
    # {champ: valeur} — valeur nulle ou vide = correction annulée.
    corrections: Optional[dict] = None


@app.patch("/api/atelier/annotations/{object_type}/{object_id}")
def atelier_annotate(
    object_type: str = FPath(...),
    object_id: int = FPath(..., ge=1),
    req: AnnotationUpdate = ...,
    user=Depends(require_auth),
):
    if object_type not in DONNEES_TYPES:
        raise HTTPException(400, f"object_type invalide — valeurs: {', '.join(DONNEES_TYPES)}")
    if req.review_status and req.review_status not in ANNOTATION_STATUSES:
        raise HTTPException(400, f"review_status invalide — valeurs: {', '.join(ANNOTATION_STATUSES)}")

    conn = get_db_rw()
    try:
        existing = row(conn,
            "SELECT review_status, confidence, note, corrections FROM annotations "
            "WHERE object_type=? AND object_id=?", (object_type, object_id))
        new_status = req.review_status or (existing["review_status"] if existing else "pending")

        # Sémantique PATCH : un champ ABSENT du corps n'est pas touché. Sans
        # ça, corriger un montant effaçait la note qui l'explique — et la note
        # est justement ce qui rend la correction défendable.
        fournis = req.model_fields_set if hasattr(req, "model_fields_set") else req.__fields_set__
        confidence = (req.confidence if "confidence" in fournis
                      else (existing["confidence"] if existing else None))
        note = (req.note if "note" in fournis
                else (existing["note"] if existing else None))

        # Les corrections sont FUSIONNÉES avec l'existant, pas remplacées : la
        # page d'atelier peut n'envoyer que le champ qu'elle vient d'éditer.
        # Une valeur vide retire la correction et rend la donnée d'origine.
        anciennes = parse_json_field(existing["corrections"], {}) if existing else {}
        corrections = dict(anciennes) if isinstance(anciennes, dict) else {}
        if req.corrections is not None:
            for champ, valeur in req.corrections.items():
                propre = _valide_correction(object_type, champ, valeur)
                if propre is None:
                    corrections.pop(champ, None)
                else:
                    corrections[champ] = propre

        conn.execute("""
            INSERT INTO annotations(object_type, object_id, review_status, confidence,
                                    note, corrections, reviewed_by, reviewed_at, updated_at)
            VALUES(?,?,?,?,?,?,?,datetime('now'),datetime('now'))
            ON CONFLICT(object_type, object_id) DO UPDATE SET
                review_status = excluded.review_status,
                confidence    = excluded.confidence,
                note          = excluded.note,
                corrections   = excluded.corrections,
                reviewed_by   = excluded.reviewed_by,
                reviewed_at   = datetime('now'),
                updated_at    = datetime('now')
        """, (object_type, object_id, new_status, confidence, note,
              json.dumps(corrections, ensure_ascii=False) if corrections else None,
              user["email"]))
        conn.execute("""
            INSERT INTO audit_log(user_id, entity_id, table_name, action, field, old_value, new_value)
            VALUES(?,?,?,?,?,?,?)
        """, (user["id"], None, "annotations", "annotate", f"{object_type}/{object_id}",
              json.dumps({"statut": existing["review_status"] if existing else None,
                          "corrections": anciennes}, ensure_ascii=False),
              json.dumps({"statut": new_status, "corrections": corrections},
                         ensure_ascii=False)))
        conn.commit()
        return {"ok": True, "object_type": object_type, "object_id": object_id,
                "review_status": new_status, "corrections": corrections}
    finally:
        conn.close()

# ─── GET /api/atelier/entities/{id} — détail complet pour l'éditeur ───────────

@app.get("/api/atelier/entities/{entity_id}")
def atelier_entity_detail(entity_id: int = FPath(..., ge=1), user=Depends(require_auth)):
    conn = get_db()
    try:
        e = row(conn, """
            SELECT e.id, e.type, e.name, e.short_name, e.address, e.commune,
                   e.perimetre,
                   e.lat, e.lng, e.confidence, e.validation_status, e.responsible,
                   e.created_at, e.updated_at,
                   p.firstname, p.lastname, p.birth_year, p.birth_month, p.gender,
                   b.siren, b.siret_siege, b.naf_code, b.naf_label,
                   b.legal_form_code, b.legal_form, b.status AS biz_status,
                   b.capital, b.employees_range, b.creation_date AS biz_creation,
                   b.closing_date,
                   a.rna_id, a.waldec_id, a.object AS asso_object,
                   a.status AS asso_status, a.creation_date AS asso_creation,
                   a.dissolution_date,
                   pl.osm_id, pl.osm_category, pl.osm_value, pl.tags AS osm_tags,
                   s.category AS svc_category, s.operator, s.opening_hours
            FROM entities e
            LEFT JOIN persons      p  ON p.entity_id  = e.id
            LEFT JOIN businesses   b  ON b.entity_id  = e.id
            LEFT JOIN associations a  ON a.entity_id  = e.id
            LEFT JOIN places       pl ON pl.entity_id = e.id
            LEFT JOIN services     s  ON s.entity_id  = e.id
            WHERE e.id = ?
        """, (entity_id,))
        if not e:
            raise HTTPException(404, "Entité introuvable")

        e["contacts"] = rows(conn,
            "SELECT id, type, value, label FROM contacts WHERE entity_id=? ORDER BY type, id",
            (entity_id,))

        e["relations"] = rows(conn, """
            SELECT r.id, r.relation_type, r.since, r.until, r.source, r.confidence,
                   f.id AS from_id, f.name AS from_name, f.type AS from_type,
                   t.id AS to_id,   t.name AS to_name,   t.type AS to_type
            FROM relations r
            JOIN entities f ON f.id = r.from_id
            JOIN entities t ON t.id = r.to_id
            WHERE r.from_id = ? OR r.to_id = ?
            ORDER BY r.relation_type, r.since DESC
        """, (entity_id, entity_id))

        e["audit"] = rows(conn, """
            SELECT al.at, al.action, al.field, al.old_value, al.new_value,
                   u.email AS user_email
            FROM audit_log al
            LEFT JOIN users u ON u.id = al.user_id
            WHERE al.entity_id = ?
            ORDER BY al.at DESC
            LIMIT 30
        """, (entity_id,))

        e["notes"] = rows(conn,
            "SELECT id, date, note, source, confidence FROM entity_notes"
            " WHERE entity_id=? ORDER BY date DESC, id DESC",
            (entity_id,))

        e["websites"] = rows(conn,
            "SELECT id, url, status, score, found_by, last_check, http_status, last_scraped"
            " FROM entity_websites WHERE entity_id=? ORDER BY status, score DESC",
            (entity_id,))

        return e
    finally:
        conn.close()

# ─── PUT /api/atelier/entities/{id} — mise à jour complète ────────────────────

class EntityUpdate(BaseModel):
    name:              Optional[str] = None
    short_name:        Optional[str] = None
    type:              Optional[str] = None
    address:           Optional[str] = None
    lat:               Optional[float] = None
    lng:               Optional[float] = None
    confidence:        Optional[str] = None
    validation_status: Optional[str] = None
    responsible:       Optional[str] = None
    # person
    firstname:   Optional[str] = None
    lastname:    Optional[str] = None
    birth_year:  Optional[int] = None
    birth_month: Optional[int] = None
    gender:      Optional[str] = None
    # business
    naf_code:       Optional[str] = None
    naf_label:      Optional[str] = None
    legal_form:     Optional[str] = None
    biz_status:     Optional[str] = None
    capital:        Optional[int] = None
    employees_range: Optional[str] = None
    biz_creation:   Optional[str] = None
    closing_date:   Optional[str] = None
    # association
    rna_id:          Optional[str] = None
    asso_object:     Optional[str] = None
    asso_status:     Optional[str] = None
    asso_creation:   Optional[str] = None
    dissolution_date: Optional[str] = None
    # place
    osm_category: Optional[str] = None
    osm_value:    Optional[str] = None
    # service
    svc_category:  Optional[str] = None
    operator:      Optional[str] = None
    opening_hours: Optional[str] = None


def _audit(conn, user_id: int, entity_id: int, field: str, old, new):
    if str(old or "") != str(new or ""):
        conn.execute("""
            INSERT INTO audit_log(user_id, entity_id, table_name, action, field, old_value, new_value)
            VALUES(?,?,'entities','update',?,?,?)
        """, (user_id, entity_id, field, str(old) if old is not None else None,
              str(new) if new is not None else None))


@app.put("/api/atelier/entities/{entity_id}")
def atelier_update_entity(
    entity_id: int = FPath(..., ge=1),
    req: EntityUpdate = ...,
    user=Depends(require_auth),
):
    conn = get_db_rw()
    try:
        current = row(conn, """
            SELECT e.*, p.firstname, p.lastname, p.birth_year, p.birth_month, p.gender,
                   b.naf_code, b.naf_label, b.legal_form, b.status AS biz_status,
                   b.capital, b.employees_range, b.creation_date AS biz_creation, b.closing_date,
                   a.rna_id, a.object AS asso_object, a.status AS asso_status,
                   a.creation_date AS asso_creation, a.dissolution_date,
                   pl.osm_category, pl.osm_value,
                   s.category AS svc_category, s.operator, s.opening_hours
            FROM entities e
            LEFT JOIN persons      p  ON p.entity_id  = e.id
            LEFT JOIN businesses   b  ON b.entity_id  = e.id
            LEFT JOIN associations a  ON a.entity_id  = e.id
            LEFT JOIN places       pl ON pl.entity_id = e.id
            LEFT JOIN services     s  ON s.entity_id  = e.id
            WHERE e.id = ?
        """, (entity_id,))
        if not current:
            raise HTTPException(404, "Entité introuvable")

        entity_type = current["type"]

        # — Champs entities —
        base_fields = ["name", "short_name", "type", "address", "lat", "lng",
                       "confidence", "validation_status", "responsible"]
        base_updates, base_params = [], []
        for f in base_fields:
            val = getattr(req, f)
            if val is not None:
                _audit(conn, user["id"], entity_id, f, current.get(f), val)
                base_updates.append(f"{f}=?")
                base_params.append(val)

        if base_updates:
            base_updates.append("updated_at=datetime('now')")
            conn.execute(
                f"UPDATE entities SET {', '.join(base_updates)} WHERE id=?",
                base_params + [entity_id]
            )

        # — Champs type-spécifiques —
        if entity_type == "person":
            pf = {k: getattr(req, k) for k in
                  ["firstname", "lastname", "birth_year", "birth_month", "gender"]
                  if getattr(req, k) is not None}
            if pf:
                for k, v in pf.items():
                    _audit(conn, user["id"], entity_id, k, current.get(k), v)
                sets = ", ".join(f"{k}=?" for k in pf)
                conn.execute(f"UPDATE persons SET {sets} WHERE entity_id=?",
                             list(pf.values()) + [entity_id])

        elif entity_type == "business":
            bf = {}
            for src, dst in [("naf_code","naf_code"), ("naf_label","naf_label"),
                              ("legal_form","legal_form"), ("biz_status","status"),
                              ("capital","capital"), ("employees_range","employees_range"),
                              ("biz_creation","creation_date"), ("closing_date","closing_date")]:
                val = getattr(req, src)
                if val is not None:
                    _audit(conn, user["id"], entity_id, src, current.get(src), val)
                    bf[dst] = val
            if bf:
                sets = ", ".join(f"{k}=?" for k in bf)
                conn.execute(f"UPDATE businesses SET {sets} WHERE entity_id=?",
                             list(bf.values()) + [entity_id])

        elif entity_type == "association":
            af = {}
            for src, dst in [("rna_id","rna_id"), ("asso_object","object"),
                              ("asso_status","status"), ("asso_creation","creation_date"),
                              ("dissolution_date","dissolution_date")]:
                val = getattr(req, src)
                if val is not None:
                    _audit(conn, user["id"], entity_id, src, current.get(src), val)
                    af[dst] = val
            if af:
                sets = ", ".join(f"{k}=?" for k in af)
                conn.execute(f"UPDATE associations SET {sets} WHERE entity_id=?",
                             list(af.values()) + [entity_id])

        elif entity_type == "place":
            plf = {}
            for f in ["osm_category", "osm_value"]:
                val = getattr(req, f)
                if val is not None:
                    _audit(conn, user["id"], entity_id, f, current.get(f), val)
                    plf[f] = val
            if plf:
                sets = ", ".join(f"{k}=?" for k in plf)
                conn.execute(f"UPDATE places SET {sets} WHERE entity_id=?",
                             list(plf.values()) + [entity_id])

        elif entity_type == "service":
            sf = {}
            for src, dst in [("svc_category","category"), ("operator","operator"),
                              ("opening_hours","opening_hours")]:
                val = getattr(req, src)
                if val is not None:
                    _audit(conn, user["id"], entity_id, src, current.get(src), val)
                    sf[dst] = val
            if sf:
                sets = ", ".join(f"{k}=?" for k in sf)
                conn.execute(f"UPDATE services SET {sets} WHERE entity_id=?",
                             list(sf.values()) + [entity_id])

        conn.commit()
        return {"ok": True, "id": entity_id}
    finally:
        conn.close()


# ─── PATCH /api/atelier/entities/{id} — verrou optimiste ──────────────────────
# Édition partielle d'une entité avec protection contre les conflits concurrents.
# Le client envoie updated_at (valeur lue à l'ouverture de la fiche).
# Si la valeur a changé entre-temps → 409 Conflict.

class EntityPatch(BaseModel):
    updated_at:        str             # verrou optimiste obligatoire
    # Champs éditables (même liste que EntityUpdate, sous-ensemble)
    name:              Optional[str] = None
    short_name:        Optional[str] = None
    address:           Optional[str] = None
    confidence:        Optional[str] = None
    validation_status: Optional[str] = None
    responsible:       Optional[str] = None
    # person
    firstname:   Optional[str] = None
    lastname:    Optional[str] = None
    birth_year:  Optional[int] = None
    birth_month: Optional[int] = None
    gender:      Optional[str] = None
    # business
    naf_code:        Optional[str] = None
    naf_label:       Optional[str] = None
    legal_form:      Optional[str] = None
    biz_status:      Optional[str] = None
    capital:         Optional[int] = None
    employees_range: Optional[str] = None
    biz_creation:    Optional[str] = None
    closing_date:    Optional[str] = None
    # association
    rna_id:           Optional[str] = None
    asso_object:      Optional[str] = None
    asso_status:      Optional[str] = None
    asso_creation:    Optional[str] = None
    dissolution_date: Optional[str] = None
    # place
    osm_category: Optional[str] = None
    osm_value:    Optional[str] = None
    # service
    svc_category:  Optional[str] = None
    operator:      Optional[str] = None
    opening_hours: Optional[str] = None


@app.patch("/api/atelier/entities/{entity_id}")
def atelier_patch_entity(
    entity_id: int = FPath(..., ge=1),
    req: EntityPatch = ...,
    user=Depends(require_auth),
):
    """
    Mise à jour partielle avec verrou optimiste.
    Rejette (409) si updated_at reçu ≠ valeur actuelle en DB (édition concurrente détectée).
    """
    conn = get_db_rw()
    try:
        current = row(conn, """
            SELECT e.*, p.firstname, p.lastname, p.birth_year, p.birth_month, p.gender,
                   b.naf_code, b.naf_label, b.legal_form, b.status AS biz_status,
                   b.capital, b.employees_range, b.creation_date AS biz_creation, b.closing_date,
                   a.rna_id, a.object AS asso_object, a.status AS asso_status,
                   a.creation_date AS asso_creation, a.dissolution_date,
                   pl.osm_category, pl.osm_value,
                   s.category AS svc_category, s.operator, s.opening_hours
            FROM entities e
            LEFT JOIN persons      p  ON p.entity_id  = e.id
            LEFT JOIN businesses   b  ON b.entity_id  = e.id
            LEFT JOIN associations a  ON a.entity_id  = e.id
            LEFT JOIN places       pl ON pl.entity_id = e.id
            LEFT JOIN services     s  ON s.entity_id  = e.id
            WHERE e.id = ?
        """, (entity_id,))
        if not current:
            raise HTTPException(404, "Entité introuvable")

        # ── Verrou optimiste ──────────────────────────────────────────────────
        db_updated_at = current.get("updated_at") or ""
        if req.updated_at != db_updated_at:
            raise HTTPException(
                409,
                f"Conflit : la fiche a été modifiée entre-temps (updated_at attendu={req.updated_at!r}, "
                f"actuel={db_updated_at!r}). Rechargez et réessayez.",
            )

        entity_type = current["type"]

        # ── Champs entities ───────────────────────────────────────────────────
        base_fields = ["name", "short_name", "address", "confidence",
                       "validation_status", "responsible"]
        base_updates, base_params = [], []
        for f in base_fields:
            val = getattr(req, f)
            if val is not None:
                _audit(conn, user["id"], entity_id, f, current.get(f), val)
                base_updates.append(f"{f}=?")
                base_params.append(val)

        if base_updates:
            base_updates.append("updated_at=datetime('now')")
            conn.execute(
                f"UPDATE entities SET {', '.join(base_updates)} WHERE id=?",
                base_params + [entity_id],
            )
        else:
            # Même sans champ de base modifié, mettre à jour updated_at si on touche une sous-table
            pass

        # ── Champs type-spécifiques ───────────────────────────────────────────
        if entity_type == "person":
            pf = {k: getattr(req, k) for k in
                  ["firstname", "lastname", "birth_year", "birth_month", "gender"]
                  if getattr(req, k) is not None}
            if pf:
                for k, v in pf.items():
                    _audit(conn, user["id"], entity_id, k, current.get(k), v)
                sets = ", ".join(f"{k}=?" for k in pf)
                conn.execute(f"UPDATE persons SET {sets} WHERE entity_id=?",
                             list(pf.values()) + [entity_id])
                if not base_updates:
                    conn.execute("UPDATE entities SET updated_at=datetime('now') WHERE id=?",
                                 (entity_id,))

        elif entity_type == "business":
            bf = {}
            for src, dst in [("naf_code","naf_code"), ("naf_label","naf_label"),
                              ("legal_form","legal_form"), ("biz_status","status"),
                              ("capital","capital"), ("employees_range","employees_range"),
                              ("biz_creation","creation_date"), ("closing_date","closing_date")]:
                val = getattr(req, src)
                if val is not None:
                    _audit(conn, user["id"], entity_id, src, current.get(src), val)
                    bf[dst] = val
            if bf:
                sets = ", ".join(f"{k}=?" for k in bf)
                conn.execute(f"UPDATE businesses SET {sets} WHERE entity_id=?",
                             list(bf.values()) + [entity_id])
                if not base_updates:
                    conn.execute("UPDATE entities SET updated_at=datetime('now') WHERE id=?",
                                 (entity_id,))

        elif entity_type == "association":
            af = {}
            for src, dst in [("rna_id","rna_id"), ("asso_object","object"),
                              ("asso_status","status"), ("asso_creation","creation_date"),
                              ("dissolution_date","dissolution_date")]:
                val = getattr(req, src)
                if val is not None:
                    _audit(conn, user["id"], entity_id, src, current.get(src), val)
                    af[dst] = val
            if af:
                sets = ", ".join(f"{k}=?" for k in af)
                conn.execute(f"UPDATE associations SET {sets} WHERE entity_id=?",
                             list(af.values()) + [entity_id])
                if not base_updates:
                    conn.execute("UPDATE entities SET updated_at=datetime('now') WHERE id=?",
                                 (entity_id,))

        elif entity_type == "place":
            plf = {}
            for f in ["osm_category", "osm_value"]:
                val = getattr(req, f)
                if val is not None:
                    _audit(conn, user["id"], entity_id, f, current.get(f), val)
                    plf[f] = val
            if plf:
                sets = ", ".join(f"{k}=?" for k in plf)
                conn.execute(f"UPDATE places SET {sets} WHERE entity_id=?",
                             list(plf.values()) + [entity_id])
                if not base_updates:
                    conn.execute("UPDATE entities SET updated_at=datetime('now') WHERE id=?",
                                 (entity_id,))

        elif entity_type == "service":
            sf = {}
            for src, dst in [("svc_category","category"), ("operator","operator"),
                              ("opening_hours","opening_hours")]:
                val = getattr(req, src)
                if val is not None:
                    _audit(conn, user["id"], entity_id, src, current.get(src), val)
                    sf[dst] = val
            if sf:
                sets = ", ".join(f"{k}=?" for k in sf)
                conn.execute(f"UPDATE services SET {sets} WHERE entity_id=?",
                             list(sf.values()) + [entity_id])
                if not base_updates:
                    conn.execute("UPDATE entities SET updated_at=datetime('now') WHERE id=?",
                                 (entity_id,))

        conn.commit()
        updated = row(conn, "SELECT updated_at FROM entities WHERE id=?", (entity_id,))
        return {"ok": True, "id": entity_id,
                "updated_at": updated["updated_at"] if updated else None}
    finally:
        conn.close()


# ─── Contacts ─────────────────────────────────────────────────────────────────

CONTACT_TYPES = {"website", "phone", "email", "other"}

class ContactCreate(BaseModel):
    type:  str
    value: str
    label: Optional[str] = None

@app.post("/api/atelier/entities/{entity_id}/contacts")
def add_contact(
    entity_id: int = FPath(..., ge=1),
    req: ContactCreate = ...,
    user=Depends(require_auth),
):
    if req.type not in CONTACT_TYPES:
        raise HTTPException(400, f"type invalide — valeurs: {', '.join(CONTACT_TYPES)}")
    conn = get_db_rw()
    try:
        if not row(conn, "SELECT 1 FROM entities WHERE id=?", (entity_id,)):
            raise HTTPException(404, "Entité introuvable")
        r = conn.execute(
            "INSERT INTO contacts(entity_id, type, value, label) VALUES(?,?,?,?)",
            (entity_id, req.type, req.value.strip(), req.label),
        )
        conn.commit()
        return {"ok": True, "id": r.lastrowid, "entity_id": entity_id,
                "type": req.type, "value": req.value.strip(), "label": req.label}
    finally:
        conn.close()

@app.delete("/api/atelier/contacts/{contact_id}")
def delete_contact(contact_id: int = FPath(..., ge=1), user=Depends(require_auth)):
    conn = get_db_rw()
    try:
        if not row(conn, "SELECT 1 FROM contacts WHERE id=?", (contact_id,)):
            raise HTTPException(404, "Contact introuvable")
        conn.execute("DELETE FROM contacts WHERE id=?", (contact_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()

# ─── Relations atelier ────────────────────────────────────────────────────────

RELATION_TYPES = [
    "dirigeant", "gérant", "associé", "président", "trésorier", "secrétaire", "membre",
    "élu_cm", "élu_cc", "candidat", "agent_communal", "membre_commission",
    "locataire_commune", "bailleur_commune", "subventionné", "prestataire",
    "famille_présumé", "époux_présumé", "enfant_présumé", "proche_présumé",
    "même_adresse", "même_lieu_dit",
]

class RelationCreate(BaseModel):
    direction:       str            # "from" = entity → cible, "to" = cible → entity
    other_entity_id: int
    relation_type:   str
    since:      Optional[str] = None
    until:      Optional[str] = None
    source:     str = "manual"
    confidence: str = "verified"

class RelationUpdate(BaseModel):
    relation_type: Optional[str] = None
    since:         Optional[str] = None
    until:         Optional[str] = None
    source:        Optional[str] = None
    confidence:    Optional[str] = None

def _relation_enriched(conn, rel_id: int):
    return row(conn, """
        SELECT r.id, r.relation_type, r.since, r.until, r.source, r.confidence,
               f.id AS from_id, f.name AS from_name, f.type AS from_type,
               t.id AS to_id,   t.name AS to_name,   t.type AS to_type
        FROM relations r
        JOIN entities f ON f.id = r.from_id
        JOIN entities t ON t.id = r.to_id
        WHERE r.id = ?
    """, (rel_id,))

@app.post("/api/atelier/entities/{entity_id}/relations")
def add_relation(
    entity_id: int = FPath(..., ge=1),
    req: RelationCreate = ...,
    user=Depends(require_auth),
):
    if req.relation_type not in RELATION_TYPES:
        raise HTTPException(400, "relation_type invalide")
    if req.confidence not in ("verified", "probable", "hypothesis"):
        raise HTTPException(400, "confidence invalide")
    if req.direction not in ("from", "to"):
        raise HTTPException(400, "direction doit être 'from' ou 'to'")

    from_id = entity_id          if req.direction == "from" else req.other_entity_id
    to_id   = req.other_entity_id if req.direction == "from" else entity_id

    conn = get_db_rw()
    try:
        if not row(conn, "SELECT 1 FROM entities WHERE id=?", (req.other_entity_id,)):
            raise HTTPException(404, "Entité cible introuvable")
        try:
            r = conn.execute("""
                INSERT INTO relations(from_id, to_id, relation_type, since, until, source, confidence)
                VALUES(?,?,?,?,?,?,?)
            """, (from_id, to_id, req.relation_type, req.since, req.until, req.source, req.confidence))
            rel_id = r.lastrowid
        except Exception:
            raise HTTPException(409, "Cette relation existe déjà (même type + source)")
        conn.execute("""
            INSERT INTO audit_log(user_id, entity_id, table_name, action, field, new_value)
            VALUES(?,?,'relations','create','relation_id',?)
        """, (user["id"], entity_id, str(rel_id)))
        conn.commit()
        return _relation_enriched(conn, rel_id)
    finally:
        conn.close()

@app.put("/api/atelier/relations/{rel_id}")
def update_relation(
    rel_id: int = FPath(..., ge=1),
    req: RelationUpdate = ...,
    user=Depends(require_auth),
):
    conn = get_db_rw()
    try:
        rel = row(conn, "SELECT * FROM relations WHERE id=?", (rel_id,))
        if not rel:
            raise HTTPException(404, "Relation introuvable")
        updates, params = [], []
        for field in ("relation_type", "since", "until", "source", "confidence"):
            val = getattr(req, field)
            if val is not None:
                old = rel.get(field)
                if str(old or "") != str(val):
                    conn.execute("""
                        INSERT INTO audit_log(user_id, entity_id, table_name, action, field, old_value, new_value)
                        VALUES(?,?,'relations','update',?,?,?)
                    """, (user["id"], rel["from_id"], field, str(old) if old else None, str(val)))
                updates.append(f"{field}=?")
                params.append(val)
        if updates:
            conn.execute(f"UPDATE relations SET {', '.join(updates)} WHERE id=?", params + [rel_id])
        conn.commit()
        return _relation_enriched(conn, rel_id)
    finally:
        conn.close()

@app.delete("/api/atelier/relations/{rel_id}")
def delete_relation(rel_id: int = FPath(..., ge=1), user=Depends(require_auth)):
    conn = get_db_rw()
    try:
        rel = row(conn, "SELECT * FROM relations WHERE id=?", (rel_id,))
        if not rel:
            raise HTTPException(404, "Relation introuvable")
        conn.execute("""
            INSERT INTO audit_log(user_id, entity_id, table_name, action, field, old_value)
            VALUES(?,?,'relations','delete','relation_id',?)
        """, (user["id"], rel["from_id"], str(rel_id)))
        conn.execute("DELETE FROM relations WHERE id=?", (rel_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# ─── /api/budget-annexe (public) ──────────────────────────────────────────────

@app.get("/api/budget-annexe")
def budget_annexe_list(entity_id: Optional[int] = None, year: Optional[int] = None):
    conn = get_db()
    try:
        filters, params = [], []
        if entity_id:
            filters.append("ba.entity_id = ?"); params.append(entity_id)
        if year:
            filters.append("ba.year = ?"); params.append(year)
        where = ("WHERE " + " AND ".join(filters)) if filters else ""
        return rows(conn, f"""
            SELECT ba.*, e.name AS entity_name, e.type AS entity_type
            FROM budget_annexe ba
            JOIN entities e ON e.id = ba.entity_id
            {where}
            ORDER BY ba.entity_id, ba.year DESC, ba.section, ba.sens, ba.id
        """, params)
    except Exception:
        return []
    finally:
        conn.close()


# ─── /api/atelier/budget-annexe (auth) ────────────────────────────────────────

class BudgetAnnexeCreate(BaseModel):
    entity_id:       int
    year:            int
    section:         str
    sens:            str
    compte:          Optional[str] = None
    libelle:         str
    montant:         float
    source:          str
    source_event_id: Optional[int] = None
    confidence:      str = "verified"

class BudgetAnnexeUpdate(BaseModel):
    section:    Optional[str]   = None
    sens:       Optional[str]   = None
    compte:     Optional[str]   = None
    libelle:    Optional[str]   = None
    montant:    Optional[float] = None
    source:     Optional[str]   = None
    confidence: Optional[str]   = None

@app.post("/api/atelier/budget-annexe")
def create_budget_annexe(req: BudgetAnnexeCreate, user=Depends(require_auth)):
    if req.section not in ("fonctionnement", "investissement", "dette"):
        raise HTTPException(400, "section invalide")
    if req.sens not in ("depense", "recette", "solde"):
        raise HTTPException(400, "sens invalide")
    conn = get_db_rw()
    try:
        if not row(conn, "SELECT 1 FROM entities WHERE id=?", (req.entity_id,)):
            raise HTTPException(404, "Entité introuvable")
        r = conn.execute(
            """INSERT INTO budget_annexe (entity_id, year, section, sens, compte, libelle, montant, source, source_event_id, confidence)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (req.entity_id, req.year, req.section, req.sens, req.compte,
             req.libelle, req.montant, req.source, req.source_event_id, req.confidence)
        )
        conn.commit()
        return row(conn, "SELECT * FROM budget_annexe WHERE id=?", (r.lastrowid,))
    finally:
        conn.close()

@app.put("/api/atelier/budget-annexe/{ba_id}")
def update_budget_annexe(ba_id: int = FPath(..., ge=1), req: BudgetAnnexeUpdate = ..., user=Depends(require_auth)):
    conn = get_db_rw()
    try:
        existing = row(conn, "SELECT * FROM budget_annexe WHERE id=?", (ba_id,))
        if not existing:
            raise HTTPException(404, "Ligne de budget introuvable")
        updates = {k: v for k, v in req.dict().items() if v is not None}
        if not updates:
            return existing
        set_clause = ", ".join(f"{k}=?" for k in updates)
        conn.execute(f"UPDATE budget_annexe SET {set_clause} WHERE id=?",
                     list(updates.values()) + [ba_id])
        conn.commit()
        return row(conn, "SELECT * FROM budget_annexe WHERE id=?", (ba_id,))
    finally:
        conn.close()

@app.delete("/api/atelier/budget-annexe/{ba_id}")
def delete_budget_annexe(ba_id: int = FPath(..., ge=1), user=Depends(require_auth)):
    conn = get_db_rw()
    try:
        if not row(conn, "SELECT 1 FROM budget_annexe WHERE id=?", (ba_id,)):
            raise HTTPException(404, "Ligne de budget introuvable")
        conn.execute("DELETE FROM budget_annexe WHERE id=?", (ba_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# ─── /api/atelier/entities/{id}/coords ────────────────────────────────────────

class CoordsUpdate(BaseModel):
    lat: float
    lng: float

@app.patch("/api/atelier/entities/{entity_id}/coords")
def update_coords(
    entity_id: int = FPath(..., ge=1),
    req: CoordsUpdate = ...,
    user=Depends(require_auth),
):
    from collectors.geocoder import wgs84_to_l93
    x_l93, y_l93 = wgs84_to_l93(req.lat, req.lng)
    conn = get_db_rw()
    try:
        if not row(conn, "SELECT 1 FROM entities WHERE id=?", (entity_id,)):
            raise HTTPException(404, "Entité introuvable")
        old = row(conn, "SELECT lat, lng FROM entities WHERE id=?", (entity_id,))
        conn.execute("""
            UPDATE entities
            SET lat=?, lng=?, x_l93=?, y_l93=?,
                geocode_source='manual', geocode_score=1.0,
                updated_at=datetime('now')
            WHERE id=?
        """, (req.lat, req.lng, x_l93, y_l93, entity_id))
        conn.execute("""
            INSERT INTO audit_log(user_id, entity_id, table_name, action, field, old_value, new_value)
            VALUES(?,?,'entities','update','coords',?,?)
        """, (user["id"], entity_id,
              f"{old['lat']},{old['lng']}" if old else None,
              f"{req.lat},{req.lng} (L93: {x_l93},{y_l93})"))
        conn.commit()
        return {"ok": True, "lat": req.lat, "lng": req.lng, "x_l93": x_l93, "y_l93": y_l93}
    finally:
        conn.close()


# ─── Notes ────────────────────────────────────────────────────────────────────

class NoteCreate(BaseModel):
    note:       str
    source:     str = "manual"
    confidence: str = "verified"
    date:       Optional[str] = None

class NoteUpdate(BaseModel):
    note:       Optional[str] = None
    source:     Optional[str] = None
    confidence: Optional[str] = None

@app.post("/api/atelier/entities/{entity_id}/notes")
def create_note(entity_id: int = FPath(..., ge=1), req: NoteCreate = ..., user=Depends(require_auth)):
    conn = get_db_rw()
    try:
        if not row(conn, "SELECT 1 FROM entities WHERE id=?", (entity_id,)):
            raise HTTPException(404, "Entité introuvable")
        date = req.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cur = conn.execute(
            "INSERT INTO entity_notes (entity_id, date, note, source, confidence)"
            " VALUES (?,?,?,?,?)",
            (entity_id, date, req.note.strip(), req.source, req.confidence)
        )
        conn.commit()
        return {"id": cur.lastrowid, "entity_id": entity_id, "date": date,
                "note": req.note.strip(), "source": req.source, "confidence": req.confidence}
    finally:
        conn.close()

@app.put("/api/atelier/notes/{note_id}")
def update_note(note_id: int = FPath(..., ge=1), req: NoteUpdate = ..., user=Depends(require_auth)):
    conn = get_db_rw()
    try:
        existing = row(conn, "SELECT * FROM entity_notes WHERE id=?", (note_id,))
        if not existing:
            raise HTTPException(404, "Note introuvable")
        updates, vals = [], []
        if req.note is not None:
            updates.append("note=?"); vals.append(req.note.strip())
        if req.source is not None:
            updates.append("source=?"); vals.append(req.source)
        if req.confidence is not None:
            updates.append("confidence=?"); vals.append(req.confidence)
        if updates:
            vals.append(note_id)
            conn.execute(f"UPDATE entity_notes SET {','.join(updates)} WHERE id=?", vals)
            conn.commit()
        return row(conn, "SELECT id, date, note, source, confidence FROM entity_notes WHERE id=?", (note_id,))
    finally:
        conn.close()

@app.delete("/api/atelier/notes/{note_id}", status_code=204)
def delete_note(note_id: int = FPath(..., ge=1), user=Depends(require_auth)):
    conn = get_db_rw()
    try:
        conn.execute("DELETE FROM entity_notes WHERE id=?", (note_id,))
        conn.commit()
    finally:
        conn.close()


# ─── Websites ─────────────────────────────────────────────────────────────────

class WebsiteAdd(BaseModel):
    url: str
    found_by: str = "manual"
    score: Optional[float] = 1.0

@app.post("/api/atelier/entities/{entity_id}/websites")
def add_website(entity_id: int = FPath(..., ge=1), req: WebsiteAdd = ..., user=Depends(require_auth)):
    conn = get_db_rw()
    try:
        if not row(conn, "SELECT 1 FROM entities WHERE id=?", (entity_id,)):
            raise HTTPException(404, "Entité introuvable")
        conn.execute(
            "INSERT OR IGNORE INTO entity_websites (entity_id, url, status, score, found_by)"
            " VALUES (?,?,'validated',?,?)",
            (entity_id, req.url.strip(), req.score, req.found_by)
        )
        conn.commit()
        return row(conn, "SELECT * FROM entity_websites WHERE entity_id=? AND url=?",
                   (entity_id, req.url.strip()))
    finally:
        conn.close()

@app.patch("/api/atelier/websites/{website_id}")
def patch_website(website_id: int = FPath(..., ge=1),
                  body: dict = Body(...), user=Depends(require_auth)):
    status = body.get("status")
    if status not in ("validated", "rejected", "candidate", "broken"):
        raise HTTPException(422, "status invalide")
    conn = get_db_rw()
    try:
        if not row(conn, "SELECT 1 FROM entity_websites WHERE id=?", (website_id,)):
            raise HTTPException(404)
        conn.execute("UPDATE entity_websites SET status=?, last_check=datetime('now') WHERE id=?",
                     (status, website_id))
        conn.commit()
        return row(conn, "SELECT * FROM entity_websites WHERE id=?", (website_id,))
    finally:
        conn.close()

@app.delete("/api/atelier/websites/{website_id}", status_code=204)
def delete_website(website_id: int = FPath(..., ge=1), user=Depends(require_auth)):
    conn = get_db_rw()
    try:
        conn.execute("DELETE FROM entity_websites WHERE id=?", (website_id,))
        conn.commit()
    finally:
        conn.close()


# ─── Queue websites ───────────────────────────────────────────────────────────

@app.get("/api/atelier/queue/websites")
def queue_websites(status: str = "candidate", limit: int = 100, user=Depends(require_auth)):
    conn = get_db()
    try:
        return rows(conn, """
            SELECT ew.id, ew.url, ew.status, ew.score, ew.found_by,
                   e.id AS entity_id, e.name AS entity_name, e.type AS entity_type
            FROM entity_websites ew
            JOIN entities e ON e.id = ew.entity_id
            WHERE ew.status = ?
            ORDER BY ew.score DESC, e.name
            LIMIT ?
        """, (status, limit))
    finally:
        conn.close()


# ─── Analyses / cross-references (Sprint F) ───────────────────────────────────

@app.get("/api/analyses/mandats-croises")
def analyse_mandats_croises(min_roles: int = 2, user=Depends(require_auth)):
    conn = get_db()
    try:
        return rows(conn,
            "SELECT * FROM v_mandats_croises WHERE nb_roles >= ? ORDER BY nb_roles DESC",
            (min_roles,))
    finally:
        conn.close()


@app.get("/api/analyses/conflits")
def analyse_conflits(
    chronologie: Optional[str] = None,  # contemporain|lien_sans_flux|dates_manquantes|tous
    user=Depends(require_auth)
):
    conn = get_db()
    try:
        if chronologie and chronologie != "tous":
            q = "SELECT * FROM v_conflits_potentiels WHERE chronologie=?"
            params = (chronologie,)
        else:
            q = "SELECT * FROM v_conflits_potentiels"
            params = ()
        return rows(conn, q, params)
    finally:
        conn.close()


@app.get("/api/analyses/subventions")
def analyse_subventions(entity_id: Optional[int] = None, user=Depends(require_auth)):
    conn = get_db()
    try:
        if entity_id:
            return rows(conn,
                "SELECT * FROM v_subventions_beneficiaires WHERE entity_id=?",
                (entity_id,))
        return rows(conn, "SELECT * FROM v_subventions_beneficiaires", ())
    finally:
        conn.close()


@app.get("/api/analyses/marches")
def analyse_marches(entity_id: Optional[int] = None, user=Depends(require_auth)):
    conn = get_db()
    try:
        if entity_id:
            return rows(conn,
                "SELECT * FROM v_marches_attributaires WHERE entity_id=?",
                (entity_id,))
        return rows(conn,
            "SELECT * FROM v_marches_attributaires WHERE titulaire_nom IS NOT NULL",
            ())
    finally:
        conn.close()


@app.get("/api/analyses/adresses-partagees")
def analyse_adresses(user=Depends(require_auth)):
    conn = get_db()
    try:
        return rows(conn, "SELECT * FROM v_adresses_partagees", ())
    finally:
        conn.close()


@app.get("/api/analyses/familles")
def analyse_familles(min_personnes: int = 2, user=Depends(require_auth)):
    conn = get_db()
    try:
        return rows(conn,
            "SELECT * FROM v_familles_potentielles WHERE nb_personnes >= ? ORDER BY nb_personnes DESC",
            (min_personnes,))
    finally:
        conn.close()


# ─── RAG — recherche sémantique (Sprint G) ────────────────────────────────────

import numpy as np
import requests as _requests

_OLLAMA_EMBED = "http://localhost:11434/api/embeddings"
_OLLAMA_CHAT  = "http://localhost:11434/api/chat"
_EMBED_MODEL  = "nomic-embed-text"
_CHAT_MODEL   = "gemma3:4b"


def _embed(text: str) -> np.ndarray:
    r = _requests.post(_OLLAMA_EMBED, json={"model": _EMBED_MODEL, "prompt": text}, timeout=30)
    r.raise_for_status()
    return np.array(r.json()["embedding"], dtype=np.float32)


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom > 1e-8 else 0.0


@app.get("/api/rag/search")
def rag_search(q: str, limit: int = 8, user=Depends(require_auth)):
    """Recherche sémantique dans l'index RAG (pas de génération). LOCAL UNIQUEMENT."""
    if not RAG_ENABLED:
        raise HTTPException(503, "RAG désactivé sur cet atelier (RAG_ENABLED=0). "
                                 "Interroger localement avec Ollama.")
    try:
        q_vec = _embed(q)
    except Exception as e:
        raise HTTPException(503, f"Ollama indisponible : {e}")

    conn = get_db()
    try:
        db_rows = conn.execute(
            "SELECT source_table, source_id, entity_id, chunk_text, vector FROM embeddings"
        ).fetchall()
    finally:
        conn.close()

    scored = []
    for source_table, source_id, entity_id, chunk_text, vec_bytes in db_rows:
        vec = np.frombuffer(vec_bytes, dtype=np.float32)
        sim = _cosine_sim(q_vec, vec)
        scored.append((sim, source_table, source_id, entity_id, chunk_text))

    scored.sort(key=lambda x: -x[0])
    return [
        {"score": round(s, 4), "source_table": st, "source_id": sid,
         "entity_id": eid, "chunk_text": text}
        for s, st, sid, eid, text in scored[:limit]
    ]


@app.post("/api/rag/ask")
def rag_ask(body: dict = Body(...), user=Depends(require_auth)):
    """Recherche + génération (Gemma 4 via Ollama). LOCAL UNIQUEMENT. body: {question, limit?}"""
    if not RAG_ENABLED:
        raise HTTPException(503, "RAG désactivé sur cet atelier (RAG_ENABLED=0). "
                                 "Interroger localement avec Ollama.")
    question = body.get("question", "").strip()
    limit     = int(body.get("limit", 6))
    if not question:
        raise HTTPException(400, "question vide")

    # Récupérer le contexte
    try:
        results = rag_search(q=question, limit=limit, user=user)
    except HTTPException:
        raise

    context = "\n\n".join(
        f"[{r['source_table']}#{r['source_id']}] {r['chunk_text']}"
        for r in results
    )

    prompt = (
        "Tu es un assistant d'investigation citoyenne sur la commune de "
        f"{COMMUNE_NAME} (département {DEPARTEMENT}, France). "
        "Réponds en français, de manière factuelle et concise, uniquement à partir des extraits fournis. "
        "Si l'information n'est pas dans les extraits, dis-le clairement.\n\n"
        f"### Extraits pertinents\n{context}\n\n"
        f"### Question\n{question}\n\n"
        "### Réponse"
    )

    try:
        r = _requests.post(
            _OLLAMA_CHAT,
            json={"model": _CHAT_MODEL, "messages": [{"role": "user", "content": prompt}], "stream": False},
            timeout=120,
        )
        r.raise_for_status()
        answer = r.json()["message"]["content"]
    except Exception as e:
        answer = None
        error  = str(e)
    else:
        error = None

    return {"question": question, "answer": answer, "error": error, "sources": results}


# ─── POST /api/atelier/queue/{id}/claim ────────────────────────────────────────
# Claim queue : lock mou sur un item de validation pour éviter le double-traitement.
# Expiration : 10 minutes. Utilise locked_by + locked_at sur relation_candidates ou entity_websites.

_CLAIM_EXPIRES_MIN = 10   # minutes avant qu'un claim expire


class ClaimRequest(BaseModel):
    table:     str     # "relation_candidates" | "entity_websites"
    locked_by: str     # email ou identifiant du valideur


CLAIMABLE_TABLES = {"relation_candidates", "entity_websites"}


@app.post("/api/atelier/queue/{item_id}/claim")
def queue_claim(
    item_id: int = FPath(..., ge=1),
    req: ClaimRequest = ...,
    user=Depends(require_auth),
):
    """
    Pose un lock mou sur un item de queue.
    - Si déjà locké par quelqu'un d'autre et non expiré → 409.
    - Sinon → pose locked_by + locked_at.
    Le claim expire après 10 minutes (côté serveur : on vérifie à la pose suivante).
    """
    if req.table not in CLAIMABLE_TABLES:
        raise HTTPException(400, f"table invalide — valeurs: {', '.join(CLAIMABLE_TABLES)}")

    conn = get_db_rw()
    try:
        existing = row(conn, f"SELECT * FROM {req.table} WHERE id=?", (item_id,))
        if not existing:
            raise HTTPException(404, "Item introuvable")

        current_lock  = existing.get("locked_by")
        current_lock_at = existing.get("locked_at")

        # Vérifier si le claim est encore valide
        if current_lock and current_lock_at:
            import datetime as _dt
            try:
                lock_time = _dt.datetime.fromisoformat(current_lock_at)
                age_min = (
                    _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
                    - lock_time.replace(tzinfo=None)
                ).total_seconds() / 60
                if age_min < _CLAIM_EXPIRES_MIN and current_lock != req.locked_by:
                    raise HTTPException(
                        409,
                        f"Item déjà locké par {current_lock!r} "
                        f"(depuis {age_min:.1f} min, expire dans {_CLAIM_EXPIRES_MIN - age_min:.1f} min)."
                    )
            except HTTPException:
                raise
            except Exception:
                pass  # Date invalide → on écrase le claim

        conn.execute(
            f"UPDATE {req.table} SET locked_by=?, locked_at=datetime('now') WHERE id=?",
            (req.locked_by, item_id),
        )
        conn.commit()
        return {
            "ok": True,
            "table": req.table,
            "item_id": item_id,
            "locked_by": req.locked_by,
            "expires_in_min": _CLAIM_EXPIRES_MIN,
        }
    finally:
        conn.close()


@app.delete("/api/atelier/queue/{item_id}/claim")
def queue_unclaim(
    item_id: int = FPath(..., ge=1),
    table: str = Query(...),
    user=Depends(require_auth),
):
    """Libère un claim sur un item de queue."""
    if table not in CLAIMABLE_TABLES:
        raise HTTPException(400, f"table invalide — valeurs: {', '.join(CLAIMABLE_TABLES)}")
    conn = get_db_rw()
    try:
        if not row(conn, f"SELECT 1 FROM {table} WHERE id=?", (item_id,)):
            raise HTTPException(404, "Item introuvable")
        conn.execute(
            f"UPDATE {table} SET locked_by=NULL, locked_at=NULL WHERE id=?",
            (item_id,),
        )
        conn.commit()
        return {"ok": True, "table": table, "item_id": item_id}
    finally:
        conn.close()


# ─── /api/atelier/geo-review — file de correction géo priorisée ──────────────

@app.get("/api/atelier/geo-review")
def geo_review(limit: int = Query(150, ge=1, le=500), user=Depends(require_auth)):
    """
    File de correction géolocalisation : entités PHYSIQUES, dans la commune,
    exposées (flux financiers, marchés, relations), triées « à corriger d'abord »
    puis par exposition. Objectif : atteindre le <5 m sur les entités qui comptent.
    Exclut personnes (coords masquées), institutions hors commune, commissions abstraites.
    """
    from collectors.config import CODE_POSTAL, COMMUNE_NAME
    conn = get_db()
    try:
        items = rows(conn, """
            SELECT e.id, e.type, e.name, e.address, e.lat, e.lng,
                   e.geocode_source, e.geocode_score,
                   ( (SELECT COUNT(*) FROM financial_flows f WHERE f.from_id=e.id OR f.to_id=e.id)*3
                   + (SELECT COUNT(*) FROM marches_publics m WHERE m.titulaire_id=e.id OR m.acheteur_id=e.id)*3
                   + MIN((SELECT COUNT(*) FROM relations r WHERE r.from_id=e.id OR r.to_id=e.id),12)
                   + CASE WHEN e.type='service' THEN 2 ELSE 0 END ) AS expo
            FROM entities e
            WHERE e.confidence IN ('verified','confirmed')
              AND e.type IN ('business','association','service','place')
              AND (e.commune = ?
                   OR UPPER(e.address) LIKE '%' || UPPER(?) || '%'
                   OR e.address LIKE '%' || ? || '%')
              AND e.name NOT LIKE 'Commission %'
              AND e.name NOT LIKE 'Conseil %'
            ORDER BY expo DESC
        """, (COMMUNE_NAME, COMMUNE_NAME, CODE_POSTAL))
        for r in items:
            if r["lat"] is None:
                r["geo_status"] = "missing"
            elif r["geocode_source"] == "manual":
                r["geo_status"] = "ok_manual"
            elif (r["geocode_score"] or 0) < 0.6 or r["geocode_source"] in ("osm", "ban", None):
                r["geo_status"] = "imprecise"
            else:
                r["geo_status"] = "ok"
        # à corriger (missing/imprecise) d'abord, par exposition décroissante
        to_fix = lambda r: 0 if r["geo_status"] in ("missing", "imprecise") else 1
        items.sort(key=lambda r: (to_fix(r), -r["expo"]))
        return items[:limit]
    finally:
        conn.close()


# ─── /api/atelier/ia — sync IA local → atelier hébergé ───────────────────────
# Le batch local (Mac) génère synthèses + embeddings, puis les pousse via ces endpoints.
# Le RAG live (/api/rag/*) reste local uniquement — ne pas exposer sur le VPS.

@app.get("/api/atelier/ia/pending")
def ia_pending(
    limit: int = Query(50, le=500),
    user=Depends(require_auth),
):
    """
    Retourne les entités sans synthèse IA (à traiter par le batch local).
    Consommé par generate_syntheses.py en mode remote.
    """
    conn = get_db()
    try:
        # Entités verified/confirmed sans synthèse déjà générée
        pending = rows(conn, """
            SELECT e.id, e.type, e.name, e.short_name, e.address,
                   e.confidence,
                   b.siren, b.naf_label, b.creation_date AS biz_creation,
                   a.rna_id, a.object AS asso_object,
                   p.firstname, p.lastname,
                   s.category AS service_category,
                   (SELECT COUNT(*) FROM relations r
                    WHERE r.from_id = e.id OR r.to_id = e.id) AS nb_relations,
                   (SELECT COUNT(*) FROM entity_notes n WHERE n.entity_id = e.id) AS nb_notes
            FROM entities e
            LEFT JOIN businesses   b ON b.entity_id = e.id
            LEFT JOIN associations a ON a.entity_id = e.id
            LEFT JOIN persons      p ON p.entity_id = e.id
            LEFT JOIN services     s ON s.entity_id = e.id
            WHERE e.confidence IN ('verified','confirmed')
            ORDER BY nb_relations DESC, nb_notes DESC
            LIMIT ?
        """, (limit,))

        # Filtrer ceux qui n'ont pas encore de synthèse sur disque
        existing_ids = set()
        for f in SYNTHESES_DIR.glob("*.json"):
            try:
                existing_ids.add(int(f.stem))
            except ValueError:
                pass

        result = [p for p in pending if p["id"] not in existing_ids]
        return {"pending": result, "total": len(result)}
    finally:
        conn.close()


class SynthesisItem(BaseModel):
    entity_id:   int
    entity_name: str
    entity_type: str
    content:     dict    # contenu JSON de la synthèse (clés libres + _entity_id, _generated)


@app.post("/api/atelier/ia/syntheses")
def push_syntheses(
    items: list[SynthesisItem],
    user=Depends(require_auth),
):
    """
    Push des synthèses générées en local vers l'atelier.
    Écritures petites, atomiques. Ne modifie pas la DB, écrit sur disque (SYNTHESES_DIR).
    """
    SYNTHESES_DIR.mkdir(parents=True, exist_ok=True)
    saved, skipped = 0, 0
    for item in items:
        if item.entity_id <= 0:
            skipped += 1
            continue
        content = dict(item.content)
        content["_entity_id"]   = item.entity_id
        content["_entity_name"] = item.entity_name
        content["_entity_type"] = item.entity_type
        if "_generated" not in content:
            content["_generated"] = datetime.now(timezone.utc).isoformat()
        path = SYNTHESES_DIR / f"{item.entity_id}.json"
        path.write_text(
            json.dumps(content, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        saved += 1
    return {"ok": True, "saved": saved, "skipped": skipped}


class EmbeddingItem(BaseModel):
    source_table: str
    source_id:    int
    entity_id:    Optional[int] = None
    chunk_text:   str
    vector:       list[float]   # vecteur float32 (768 dim nomic-embed-text)


@app.post("/api/atelier/ia/embeddings")
def push_embeddings(
    items: list[EmbeddingItem],
    user=Depends(require_auth),
):
    """
    Push des vecteurs RAG générés en local vers la DB atelier.
    Upsert par (source_table, source_id) — écritures courtes, hors heures de validation.
    """
    import struct
    conn = get_db_rw()
    saved, skipped = 0, 0
    try:
        for item in items:
            if not item.vector or not item.chunk_text:
                skipped += 1
                continue
            # Sérialiser le vecteur float32 en bytes (compatible numpy.frombuffer)
            vec_bytes = struct.pack(f"{len(item.vector)}f", *item.vector)
            conn.execute("""
                INSERT INTO embeddings (source_table, source_id, entity_id, chunk_text, vector)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source_table, source_id)
                DO UPDATE SET chunk_text=excluded.chunk_text,
                              vector=excluded.vector,
                              created_at=datetime('now')
            """, (item.source_table, item.source_id, item.entity_id,
                  item.chunk_text, vec_bytes))
            saved += 1
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "saved": saved, "skipped": skipped}

# ─── /api/ask — interrogation en langage naturel de la base PUBLIQUE ───────────
#
# Distinct de /api/synthesize, qui injecte un contexte choisi par mots-clés et ne
# sait donc rien répondre en dehors de ceux-ci. Ici, la question est traduite en
# SQL, la requête est validée puis exécutée, et la réponse cite la requête : elle
# est vérifiable. Voir scripts/ask.py pour les garde-fous.
#
# La base interrogée est `db/public.db`, dérivée du snapshot filtré : aucune
# donnée privée n'y figure. C'est une propriété du fichier, pas une promesse du
# code — même une requête malveillante ne peut atteindre que du déjà-publié.

class AskRequest(BaseModel):
    question: str
    rediger: bool = True


@app.post("/api/ask")
@limiter.limit("10/minute;100/hour")
def ask(request: StarletteRequest, req: AskRequest):
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(400, "question vide")
    if len(question) > 500:
        raise HTTPException(400, "question trop longue (500 caractères maximum)")

    sys.path.insert(0, str(BASE_DIR / "scripts"))
    try:
        import ask as ask_mod
    except Exception as e:
        raise HTTPException(503, f"module d'interrogation indisponible : {e}")

    if not ask_mod.PUBLIC_DB.exists():
        raise HTTPException(503, "base publique absente — lancer "
                                 "scripts/build_public_db.py")
    try:
        return ask_mod.demander(question, rediger_reponse=req.rediger)
    except ask_mod.RequeteRefusee as e:
        # 422 et non 500 : la question est recevable, c'est la traduction en SQL
        # qui n'a pas abouti. Le message est rendu tel quel pour que l'atelier
        # voie ce qui a été refusé.
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@app.get("/api/ask/schema")
def ask_schema():
    """Schéma public interrogeable — utile pour l'atelier et la page /ia."""
    sys.path.insert(0, str(BASE_DIR / "scripts"))
    import ask as ask_mod
    if not ask_mod.PUBLIC_DB.exists():
        raise HTTPException(503, "base publique absente")
    conn = ask_mod.connexion()
    try:
        return {"schema": ask_mod.schema_texte(conn),
                "tables": sorted(ask_mod.TABLES_AUTORISEES),
                "limite_lignes": ask_mod.LIMITE_LIGNES}
    finally:
        conn.close()
