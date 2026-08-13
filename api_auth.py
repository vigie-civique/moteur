"""
Atelier — Auth JWT (access 1h, refresh 7j) + bcrypt + lockout
Routes exportées : /api/auth/*
Deps exportées  : require_auth, require_role
"""
import hashlib
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import bcrypt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

try:
    from jose import JWTError, jwt
except ImportError:
    raise RuntimeError("python-jose manquant — pip install 'python-jose[cryptography]'")


def _hash_pw(password: str) -> str:
    pre = hashlib.sha256(password.encode()).hexdigest().encode()
    return bcrypt.hashpw(pre, bcrypt.gensalt()).decode()


def _verify_pw(password: str, hashed: str) -> bool:
    pre = hashlib.sha256(password.encode()).hexdigest().encode()
    return bcrypt.checkpw(pre, hashed.encode())

BASE_DIR         = Path(__file__).parent
from collectors.config import DB_PATH
_SECRET          = os.environ.get("JWT_SECRET", "")
_ALGO            = "HS256"
_ACCESS_MINUTES  = 60
_REFRESH_MINUTES = 60 * 24 * 7

router  = APIRouter(prefix="/api/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)


def _db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _get(conn, sql, params=()):
    r = conn.execute(sql, params).fetchone()
    return dict(r) if r else None


def _make_token(sub: str, kind: str, minutes: int) -> str:
    if not _SECRET:
        raise RuntimeError("JWT_SECRET absent — lance scripts/migrate_sprint1.py")
    exp = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    return jwt.encode({"sub": sub, "kind": kind, "exp": exp}, _SECRET, algorithm=_ALGO)


def _decode(token: str) -> dict:
    if not _SECRET:
        raise HTTPException(503, "JWT non configuré — JWT_SECRET manquant dans .env")
    try:
        return jwt.decode(token, _SECRET, algorithms=[_ALGO])
    except JWTError as exc:
        raise HTTPException(401, str(exc))


def _revoked(token: str, conn) -> bool:
    return conn.execute(
        "SELECT 1 FROM revoked_tokens WHERE jti=? AND expires_at > datetime('now')",
        (token,),
    ).fetchone() is not None


# ─── Dépendances FastAPI ────────────────────────────────────────────────────────

def require_auth(creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)):
    if not creds:
        raise HTTPException(401, "Token manquant")
    payload = _decode(creds.credentials)
    if payload.get("kind") != "access":
        raise HTTPException(401, "Token d'accès requis")
    conn = _db()
    try:
        if _revoked(creds.credentials, conn):
            raise HTTPException(401, "Token révoqué")
        user = _get(conn, "SELECT id, email, role FROM users WHERE email=?", (payload["sub"],))
        if not user:
            raise HTTPException(401, "Utilisateur introuvable")
        return user
    finally:
        conn.close()


def require_role(*roles):
    def _dep(user=Depends(require_auth)):
        if user["role"] not in roles:
            raise HTTPException(403, f"Rôle requis : {', '.join(roles)}")
        return user
    return _dep


# ─── Schemas ───────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


# ─── Routes ────────────────────────────────────────────────────────────────────

@router.post("/login")
def login(req: LoginRequest):
    conn = _db()
    try:
        user = _get(conn, "SELECT * FROM users WHERE email=?", (req.email.lower().strip(),))

        if user and user["locked_until"]:
            if user["locked_until"] > datetime.now(timezone.utc).isoformat():
                raise HTTPException(429, "Compte verrouillé 15 min (5 tentatives échouées)")

        if not user or not _verify_pw(req.password, user["password_hash"]):
            if user:
                attempts = (user["failed_attempts"] or 0) + 1
                lock = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat() \
                       if attempts >= 5 else None
                conn.execute(
                    "UPDATE users SET failed_attempts=?, locked_until=? WHERE id=?",
                    (attempts, lock, user["id"]),
                )
                conn.commit()
            raise HTTPException(401, "Email ou mot de passe incorrect")

        conn.execute(
            "UPDATE users SET failed_attempts=0, locked_until=NULL, last_login=datetime('now') WHERE id=?",
            (user["id"],),
        )
        conn.commit()

        return {
            "access_token":  _make_token(user["email"], "access",  _ACCESS_MINUTES),
            "refresh_token": _make_token(user["email"], "refresh", _REFRESH_MINUTES),
            "token_type":    "bearer",
            "user": {"id": user["id"], "email": user["email"], "role": user["role"]},
        }
    finally:
        conn.close()


@router.post("/refresh")
def refresh_token(req: RefreshRequest):
    payload = _decode(req.refresh_token)
    if payload.get("kind") != "refresh":
        raise HTTPException(401, "Token de rafraîchissement requis")
    conn = _db()
    try:
        if _revoked(req.refresh_token, conn):
            raise HTTPException(401, "Token révoqué")
        user = _get(conn, "SELECT id, email, role FROM users WHERE email=?", (payload["sub"],))
        if not user:
            raise HTTPException(401, "Utilisateur introuvable")
        return {
            "access_token": _make_token(user["email"], "access", _ACCESS_MINUTES),
            "token_type":   "bearer",
        }
    finally:
        conn.close()


@router.post("/logout")
def logout(creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)):
    if not creds:
        return {"ok": True}
    try:
        payload = _decode(creds.credentials)
        exp_iso = datetime.fromtimestamp(payload["exp"], tz=timezone.utc).isoformat()
        conn = _db()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO revoked_tokens(jti, expires_at) VALUES(?,?)",
                (creds.credentials, exp_iso),
            )
            conn.commit()
        finally:
            conn.close()
    except HTTPException:
        pass
    return {"ok": True}


@router.get("/me")
def me(user=Depends(require_auth)):
    return user
