"""
Atelier — Auth JWT (access 1h, refresh 7j) + bcrypt + lockout
Routes exportées : /api/auth/*, /api/admin/comptes/*
Deps exportées  : require_auth, require_role, require_au_moins, au_moins, exiger,
                  utilisateur_du_jeton

On n'entre dans l'atelier que sur invitation (arbitré par Julien le 17/09/2026) :
le premier compte admin est créé à l'installation (installateur ou
`scripts/create_user.py`) ; ensuite, un admin invite une adresse en choisissant
son rôle, et seul le porteur du lien d'invitation crée le compte.
"""
import hashlib
import os
import secrets
import sqlite3
import sys
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

# Sans secret, l'API démarrait sans rien dire et n'échouait qu'à la PREMIÈRE
# tentative de connexion, par une trace dans le terminal du serveur — pendant que
# le navigateur affichait une erreur générique. Le lien entre les deux n'était
# pas déductible, et un `.env` recopié depuis l'exemple (donc au secret vide)
# ramène exactement cette situation.
#
# Un service qui ne peut rien faire d'utile doit refuser de démarrer, à voix
# haute, au moment où on le lance. C'est le seul instant où l'exploitant regarde.
if not _SECRET:
    print(
        "\n  ✖ JWT_SECRET absent : l'atelier ne peut authentifier personne.\n"
        "\n    cp deploy/env.exemple .env && chmod 600 .env\n"
        "    puis renseigner JWT_SECRET (openssl rand -hex 32)\n"
        "\n    Attention : recopier l'exemple par-dessus un .env existant\n"
        "    REMET le secret à vide.\n",
        file=sys.stderr,
    )
    raise SystemExit(1)
_ACCESS_MINUTES  = 60
_REFRESH_MINUTES = 60 * 24 * 7

router  = APIRouter(prefix="/api/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)


#: Bases dont les tables de comptes ont déjà été mises à niveau.
_COMPTES_PRETS: set[str] = set()

#: Rattrapé ici ET déclaré dans `db/schema.sql` : l'API ne passe pas par
#: `init_db()`, et une base d'avant le 17/09/2026 n'a ni l'une ni l'autre.
_INVITATIONS_SQL = """
CREATE TABLE IF NOT EXISTS invitations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    email        TEXT NOT NULL,
    role         TEXT NOT NULL CHECK(role IN ('admin','validator','contributor')),
    nature       TEXT NOT NULL DEFAULT 'compte' CHECK(nature IN ('compte','mot_de_passe')),
    jeton_sha256 TEXT NOT NULL UNIQUE,
    invite_par   INTEGER REFERENCES users(id),
    cree_le      TEXT DEFAULT (datetime('now')),
    expire_le    TEXT NOT NULL,
    utilisee_le  TEXT,
    annulee_le   TEXT
)"""


def _db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    cle = str(DB_PATH)
    if cle not in _COMPTES_PRETS:
        colonnes = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
        if colonnes:
            # `desactive_le` : un compte ne se supprime pas — `audit_log` le
            # référence, et effacer l'auteur effacerait la trace.
            # `sessions_version` : un mot de passe changé met fin aux sessions
            # ouvertes avant, au lieu de les laisser courir sept jours.
            for colonne, definition in (("desactive_le", "TEXT"),
                                        ("sessions_version", "INTEGER DEFAULT 0")):
                if colonne not in colonnes:
                    conn.execute(f"ALTER TABLE users ADD COLUMN {colonne} {definition}")
            conn.execute(_INVITATIONS_SQL)
            conn.commit()
            _COMPTES_PRETS.add(cle)
    return conn


def _get(conn, sql, params=()):
    r = conn.execute(sql, params).fetchone()
    return dict(r) if r else None


def _make_token(sub: str, kind: str, minutes: int, version: int = 0) -> str:
    if not _SECRET:
        raise RuntimeError("JWT_SECRET absent : le renseigner dans .env "
                           "(cp deploy/env.exemple .env, puis openssl rand -hex 32)")
    maintenant = datetime.now(timezone.utc)
    exp = maintenant + timedelta(minutes=minutes)
    # `sv` : la génération de sessions du compte. Un changement de mot de passe
    # l'incrémente, et tout jeton d'une génération antérieure est refusé. Une
    # date (`iat`, à la seconde) laissait passer les jetons de la même seconde.
    return jwt.encode({"sub": sub, "kind": kind, "exp": exp, "iat": int(maintenant.timestamp()),
                       "sv": version}, _SECRET, algorithm=_ALGO)


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


# ─── Rôles ─────────────────────────────────────────────────────────────────────
# EMBOÎTÉS — arbitré par Julien le 17/09/2026. Le contributeur propose sans
# trancher ; le validateur fait tout ce que fait le contributeur, tranche, et
# voit les analyses ; l'admin fait tout ce que fait le validateur, gère les
# comptes et publie. Jusque-là `contributor` et `validator` avaient exactement
# les mêmes droits : un contributeur rendait une fiche publiable.

ROLES = ("contributor", "validator", "admin")
RANG = {r: i for i, r in enumerate(ROLES)}
LIBELLE_ROLE = {"contributor": "contributeur", "validator": "validateur",
                "admin": "administrateur"}


def au_moins(user: Optional[dict], role: str) -> bool:
    return bool(user) and RANG.get(user.get("role"), -1) >= RANG[role]


def exiger(user: Optional[dict], role: str, geste: str) -> None:
    """403 lisible si `user` n'a pas au moins `role` pour `geste`."""
    if not au_moins(user, role):
        actuel = LIBELLE_ROLE.get((user or {}).get("role"), "non identifié")
        raise HTTPException(403, {
            "message": f"{geste} : réservé au rôle {LIBELLE_ROLE[role]}"
                       f"{'' if role == 'admin' else ' et au-dessus'} "
                       f"— vous êtes {actuel}.",
            "role_requis": role})


# ─── Dépendances FastAPI ────────────────────────────────────────────────────────

def utilisateur_du_jeton(jeton: str, kind: str = "access") -> dict:
    """Le compte d'un jeton valide, ou 401. Seul endroit où une session est
    jugée : le verrou global de `api.py`, `require_auth` et `/refresh` l'appellent
    tous — trois copies de ce contrôle auraient divergé au premier ajout."""
    payload = _decode(jeton)
    if payload.get("kind") != kind:
        raise HTTPException(401, "Token d'accès requis" if kind == "access"
                            else "Token de rafraîchissement requis")
    conn = _db()
    try:
        if _revoked(jeton, conn):
            raise HTTPException(401, "Token révoqué")
        user = _get(conn, "SELECT id, email, role, desactive_le, sessions_version "
                          "FROM users WHERE email=?", (payload.get("sub"),))
    finally:
        conn.close()
    if not user:
        raise HTTPException(401, "Utilisateur introuvable")
    if user.pop("desactive_le"):
        raise HTTPException(401, "Compte désactivé")
    if payload.get("sv", 0) != (user.pop("sessions_version") or 0):
        raise HTTPException(401, "Session close : le mot de passe a changé depuis")
    return user


def require_auth(creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)):
    if not creds:
        raise HTTPException(401, "Token manquant")
    return utilisateur_du_jeton(creds.credentials, "access")


def require_role(*roles):
    def _dep(user=Depends(require_auth)):
        if user["role"] not in roles:
            raise HTTPException(403, f"Rôle requis : {', '.join(roles)}")
        return user
    return _dep


def require_au_moins(role: str, geste: str = "Cette action"):
    def _dep(user=Depends(require_auth)):
        exiger(user, role, geste)
        return user
    return _dep


# ─── Schemas ───────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None


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

        if user.get("desactive_le"):
            raise HTTPException(403, "Compte désactivé — voir un administrateur de l'atelier.")

        conn.execute(
            "UPDATE users SET failed_attempts=0, locked_until=NULL, last_login=datetime('now') WHERE id=?",
            (user["id"],),
        )
        conn.commit()

        return {
            **_sessions(conn, user["id"]),
            "user": {"id": user["id"], "email": user["email"], "role": user["role"]},
        }
    finally:
        conn.close()


@router.post("/refresh")
def refresh_token(req: RefreshRequest):
    payload = _decode(req.refresh_token)
    user = utilisateur_du_jeton(req.refresh_token, "refresh")
    return {
        "access_token": _make_token(user["email"], "access", _ACCESS_MINUTES,
                                    payload.get("sv", 0)),
        "token_type":   "bearer",
    }


@router.post("/logout")
def logout(req: Optional[LogoutRequest] = None,
           creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)):
    """Révoque le jeton d'accès ET, s'il est fourni, celui de rafraîchissement.

    Seul le jeton d'accès (une heure) était révoqué. Celui de rafraîchissement
    (sept jours, gardé dans le navigateur) en refabriquait un neuf : après
    « Déconnexion », la session survivait une semaine — constaté le 17/09/2026.
    """
    jetons = [creds.credentials] if creds else []
    if req and req.refresh_token:
        jetons.append(req.refresh_token)
    conn = _db()
    try:
        for jeton in jetons:
            try:
                payload = _decode(jeton)
            except HTTPException:
                continue                     # déjà expiré ou illisible : rien à révoquer
            exp_iso = datetime.fromtimestamp(payload["exp"], tz=timezone.utc).isoformat()
            conn.execute(
                "INSERT OR IGNORE INTO revoked_tokens(jti, expires_at) VALUES(?,?)",
                (jeton, exp_iso),
            )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@router.get("/me")
def me(user=Depends(require_auth)):
    return user


# ─── Son propre mot de passe ────────────────────────────────────────────────────

MOT_DE_PASSE_MIN = 12
INVITATION_JOURS = 7


def _sessions(conn, user_id: int) -> dict:
    """Jetons neufs, de la génération de sessions COURANTE du compte."""
    u = _get(conn, "SELECT email, COALESCE(sessions_version, 0) AS v FROM users WHERE id=?",
             (user_id,))
    return {
        "access_token":  _make_token(u["email"], "access",  _ACCESS_MINUTES, u["v"]),
        "refresh_token": _make_token(u["email"], "refresh", _REFRESH_MINUTES, u["v"]),
        "token_type":    "bearer",
    }


def _verifier_mot_de_passe(motdepasse: str) -> None:
    if len(motdepasse) < MOT_DE_PASSE_MIN:
        raise HTTPException(400, f"Le mot de passe doit faire au moins "
                                 f"{MOT_DE_PASSE_MIN} caractères.")


def _journal_compte(conn, auteur_id: Optional[int], action: str, cible: str,
                    avant: Optional[str] = None, apres: Optional[str] = None) -> None:
    conn.execute(
        "INSERT INTO audit_log(user_id, entity_id, table_name, action, field, "
        "old_value, new_value) VALUES(?,?,?,?,?,?,?)",
        (auteur_id, None, "users", action, cible, avant, apres))


def _clore_sessions(conn, user_id: int) -> None:
    """Toute session ouverte jusqu'ici est refusée (cf. `sv` dans le jeton)."""
    conn.execute("UPDATE users SET sessions_version = COALESCE(sessions_version, 0) + 1 "
                 "WHERE id=?", (user_id,))


class ChangementMotDePasse(BaseModel):
    actuel: str
    nouveau: str


@router.post("/mot-de-passe")
def changer_mot_de_passe(req: ChangementMotDePasse, user=Depends(require_auth)):
    """Seule la ligne de commande changeait un mot de passe — donc personne, sauf
    celui qui tient la machine. Les autres sessions du compte sont closes ; celle
    qui change le mot de passe reçoit des jetons neufs."""
    _verifier_mot_de_passe(req.nouveau)
    conn = _db()
    try:
        ligne = _get(conn, "SELECT password_hash FROM users WHERE id=?", (user["id"],))
        if not ligne or not _verify_pw(req.actuel, ligne["password_hash"]):
            raise HTTPException(403, "Le mot de passe actuel est incorrect.")
        conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                     (_hash_pw(req.nouveau), user["id"]))
        _clore_sessions(conn, user["id"])
        _journal_compte(conn, user["id"], "mot_de_passe", user["email"])
        conn.commit()
        return {"ok": True, **_sessions(conn, user["id"])}
    finally:
        conn.close()


@router.get("/etat")
def etat_des_comptes():
    """L'atelier a-t-il déjà un compte ? La page de connexion le dit : sans
    compte, personne ne peut en inviter, et le premier se crée à l'installation."""
    conn = _db()
    try:
        return {"comptes": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0}
    finally:
        conn.close()


# ─── Invitations ─────────────────────────────────────────────────────────────────
# Le lien porte un jeton de 32 octets tiré au sort ; la base n'en garde que
# l'empreinte. Usage unique, sept jours. Il circule dans le FRAGMENT de l'adresse
# (`#…`), que le navigateur n'envoie jamais au serveur : il ne finit ni dans un
# journal d'accès, ni dans un en-tête Referer. L'interface le poste ensuite.

def _empreinte(jeton: str) -> str:
    return hashlib.sha256(jeton.encode()).hexdigest()


def _etat_invitation(inv: dict) -> str:
    if inv["utilisee_le"]:
        return "utilisee"
    if inv["annulee_le"]:
        return "annulee"
    if inv["expire_le"] <= datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"):
        return "expiree"
    return "en_attente"


def _creer_invitation(conn, email: str, role: str, nature: str, par: dict) -> tuple[dict, str]:
    """Annule les invitations encore ouvertes pour cette adresse et cette nature :
    un seul lien valide à la fois."""
    conn.execute("UPDATE invitations SET annulee_le=datetime('now') WHERE email=? "
                 "AND nature=? AND utilisee_le IS NULL AND annulee_le IS NULL",
                 (email, nature))
    jeton = secrets.token_urlsafe(32)
    cur = conn.execute(
        "INSERT INTO invitations(email, role, nature, jeton_sha256, invite_par, expire_le) "
        f"VALUES(?,?,?,?,?, datetime('now', '+{INVITATION_JOURS} days'))",
        (email, role, nature, _empreinte(jeton), par["id"]))
    _journal_compte(conn, par["id"], "invitation" if nature == "compte" else "lien_mot_de_passe",
                    email, None, role)
    return _invitation(conn, cur.lastrowid), jeton


def _invitation(conn, inv_id: int) -> dict:
    inv = _get(conn, """
        SELECT i.id, i.email, i.role, i.nature, i.cree_le, i.expire_le, i.utilisee_le,
               i.annulee_le, u.email AS invite_par
        FROM invitations i LEFT JOIN users u ON u.id = i.invite_par WHERE i.id=?""", (inv_id,))
    inv["etat"] = _etat_invitation(inv)
    return inv


def _invitation_du_jeton(conn, jeton: str) -> dict:
    inv = _get(conn, "SELECT id FROM invitations WHERE jeton_sha256=?", (_empreinte(jeton or ""),))
    if not inv:
        raise HTTPException(404, "Ce lien d'invitation n'est pas reconnu. "
                                 "Demandez-en un nouveau à un administrateur.")
    inv = _invitation(conn, inv["id"])
    messages = {
        "utilisee": "Ce lien a déjà servi : il n'est valable qu'une fois. Connectez-vous, "
                    "ou demandez un nouveau lien à un administrateur.",
        "annulee": "Ce lien a été annulé ou remplacé par un plus récent.",
        "expiree": f"Ce lien a expiré (valable {INVITATION_JOURS} jours). "
                   "Demandez-en un nouveau à un administrateur.",
    }
    if inv["etat"] in messages:
        raise HTTPException(410, messages[inv["etat"]])
    return inv


class JetonInvitation(BaseModel):
    jeton: str


class AcceptationInvitation(BaseModel):
    jeton: str
    motdepasse: str


@router.post("/invitation/lire")
def lire_invitation(req: JetonInvitation):
    conn = _db()
    try:
        inv = _invitation_du_jeton(conn, req.jeton)
    finally:
        conn.close()
    return {k: inv[k] for k in ("email", "role", "nature", "expire_le", "invite_par")} | {
        "role_libelle": LIBELLE_ROLE[inv["role"]]}


@router.post("/invitation/accepter")
def accepter_invitation(req: AcceptationInvitation):
    """Crée le compte invité (ou pose le nouveau mot de passe), et ouvre la session."""
    _verifier_mot_de_passe(req.motdepasse)
    conn = _db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        inv = _invitation_du_jeton(conn, req.jeton)
        if inv["nature"] == "compte":
            if _get(conn, "SELECT 1 FROM users WHERE email=?", (inv["email"],)):
                raise HTTPException(409, "Un compte existe déjà pour cette adresse : "
                                         "connectez-vous.")
            cur = conn.execute("INSERT INTO users(email, password_hash, role) VALUES(?,?,?)",
                               (inv["email"], _hash_pw(req.motdepasse), inv["role"]))
            user = {"id": cur.lastrowid, "email": inv["email"], "role": inv["role"]}
            _journal_compte(conn, user["id"], "inscription", user["email"], None, user["role"])
        else:
            user = _get(conn, "SELECT id, email, role, desactive_le FROM users WHERE email=?",
                        (inv["email"],))
            if not user or user.pop("desactive_le"):
                raise HTTPException(410, "Ce compte n'existe plus ou a été désactivé.")
            conn.execute("UPDATE users SET password_hash=?, failed_attempts=0, "
                         "locked_until=NULL WHERE id=?", (_hash_pw(req.motdepasse), user["id"]))
            _clore_sessions(conn, user["id"])
            _journal_compte(conn, user["id"], "mot_de_passe", user["email"])
        conn.execute("UPDATE invitations SET utilisee_le=datetime('now') WHERE id=?", (inv["id"],))
        conn.execute("UPDATE users SET last_login=datetime('now') WHERE id=?", (user["id"],))
        conn.commit()
        return {**_sessions(conn, user["id"]), "user": user}
    finally:
        conn.close()


# ─── Comptes (admin) ────────────────────────────────────────────────────────────
# Inviter, changer de rôle, désactiver, envoyer un lien de mot de passe. Un compte
# ne se supprime pas : il se désactive, et ce qu'il a fait reste attribué.

comptes = APIRouter(prefix="/api/admin/comptes", tags=["comptes"])
_ADMIN = "Gérer les comptes"


class InvitationDemandee(BaseModel):
    email: str
    role: str = "contributor"


class CompteModifie(BaseModel):
    role: Optional[str] = None
    actif: Optional[bool] = None


def _admins_actifs(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM users WHERE role='admin' "
                        "AND desactive_le IS NULL").fetchone()[0]


def _adresse(email: str) -> str:
    email = (email or "").strip().lower()
    local, _, domaine = email.partition("@")
    if not local or "." not in domaine or " " in email or len(email) > 254:
        raise HTTPException(400, "Adresse électronique invalide.")
    return email


@comptes.get("")
def lister_comptes(user=Depends(require_au_moins("admin", _ADMIN))):
    conn = _db()
    try:
        comptes_ = [dict(r) for r in conn.execute(
            "SELECT id, email, role, last_login, created_at, desactive_le, locked_until "
            "FROM users ORDER BY desactive_le IS NOT NULL, email")]
        invitations = [_invitation(conn, r[0]) for r in conn.execute(
            "SELECT id FROM invitations ORDER BY id DESC LIMIT 200")]
    finally:
        conn.close()
    return {"comptes": comptes_, "invitations": invitations,
            "roles": [{"cle": r, "libelle": LIBELLE_ROLE[r]} for r in ROLES],
            "invitation_jours": INVITATION_JOURS,
            # Adresse à mettre dans les liens. Vide : l'interface prend celle par
            # laquelle l'admin consulte l'atelier.
            "adresse_atelier": os.environ.get("ATELIER_URL", "").rstrip("/")}


@comptes.post("/invitations", status_code=201)
def inviter(req: InvitationDemandee, user=Depends(require_au_moins("admin", _ADMIN))):
    """Le jeton n'est rendu QU'ICI, une fois : la base n'en garde que l'empreinte."""
    email = _adresse(req.email)
    if req.role not in ROLES:
        raise HTTPException(400, f"Rôle inconnu — valeurs : {', '.join(ROLES)}")
    conn = _db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        existant = _get(conn, "SELECT id, desactive_le FROM users WHERE email=?", (email,))
        if existant:
            raise HTTPException(409, "Cette adresse a déjà un compte"
                                + (" (désactivé : le réactiver plutôt que l'inviter)."
                                   if existant["desactive_le"] else "."))
        inv, jeton = _creer_invitation(conn, email, req.role, "compte", user)
        conn.commit()
    finally:
        conn.close()
    return {"invitation": inv, "jeton": jeton}


@comptes.post("/invitations/{inv_id}/renouveler", status_code=201)
def renouveler_invitation(inv_id: int, user=Depends(require_au_moins("admin", _ADMIN))):
    conn = _db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        ancienne = _get(conn, "SELECT email, role, nature FROM invitations WHERE id=?", (inv_id,))
        if not ancienne:
            raise HTTPException(404, "Invitation introuvable.")
        if ancienne["nature"] == "compte" and _get(conn, "SELECT 1 FROM users WHERE email=?",
                                                   (ancienne["email"],)):
            raise HTTPException(409, "Cette adresse a déjà créé son compte.")
        inv, jeton = _creer_invitation(conn, ancienne["email"], ancienne["role"],
                                       ancienne["nature"], user)
        conn.commit()
    finally:
        conn.close()
    return {"invitation": inv, "jeton": jeton}


@comptes.delete("/invitations/{inv_id}")
def annuler_invitation(inv_id: int, user=Depends(require_au_moins("admin", _ADMIN))):
    conn = _db()
    try:
        inv = _get(conn, "SELECT email FROM invitations WHERE id=? AND utilisee_le IS NULL "
                         "AND annulee_le IS NULL", (inv_id,))
        if not inv:
            raise HTTPException(404, "Aucune invitation ouverte à ce numéro.")
        conn.execute("UPDATE invitations SET annulee_le=datetime('now') WHERE id=?", (inv_id,))
        _journal_compte(conn, user["id"], "invitation_annulee", inv["email"])
        conn.commit()
        return _invitation(conn, inv_id)
    finally:
        conn.close()


@comptes.patch("/{compte_id}")
def modifier_compte(compte_id: int, req: CompteModifie,
                    user=Depends(require_au_moins("admin", _ADMIN))):
    conn = _db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cible = _get(conn, "SELECT * FROM users WHERE id=?", (compte_id,))
        if not cible:
            raise HTTPException(404, "Compte introuvable.")
        if req.role is not None and req.role not in ROLES:
            raise HTTPException(400, f"Rôle inconnu — valeurs : {', '.join(ROLES)}")
        perd_admin = (cible["role"] == "admin" and cible["desactive_le"] is None
                      and ((req.role is not None and req.role != "admin")
                           or req.actif is False))
        if perd_admin and _admins_actifs(conn) <= 1:
            raise HTTPException(409, "C'est le dernier administrateur actif : "
                                     "l'atelier n'aurait plus personne pour gérer les comptes.")
        if req.actif is False and compte_id == user["id"]:
            raise HTTPException(409, "On ne désactive pas son propre compte : "
                                     "demander à un autre administrateur.")
        if req.role is not None and req.role != cible["role"]:
            conn.execute("UPDATE users SET role=? WHERE id=?", (req.role, compte_id))
            _journal_compte(conn, user["id"], "role", cible["email"], cible["role"], req.role)
        if req.actif is False and cible["desactive_le"] is None:
            conn.execute("UPDATE users SET desactive_le=datetime('now') WHERE id=?", (compte_id,))
            _journal_compte(conn, user["id"], "desactivation", cible["email"])
        elif req.actif is True and cible["desactive_le"] is not None:
            conn.execute("UPDATE users SET desactive_le=NULL WHERE id=?", (compte_id,))
            _journal_compte(conn, user["id"], "reactivation", cible["email"])
        if perd_admin:
            # Les liens envoyés par un admin qui ne l'est plus ne valent plus rien.
            conn.execute("UPDATE invitations SET annulee_le=datetime('now') WHERE invite_par=? "
                         "AND utilisee_le IS NULL AND annulee_le IS NULL", (compte_id,))
        conn.commit()
        return _get(conn, "SELECT id, email, role, last_login, created_at, desactive_le, "
                          "locked_until FROM users WHERE id=?", (compte_id,))
    finally:
        conn.close()


@comptes.post("/{compte_id}/lien-mot-de-passe", status_code=201)
def lien_mot_de_passe(compte_id: int, user=Depends(require_au_moins("admin", _ADMIN))):
    """Mot de passe oublié : un lien à usage unique, comme une invitation.
    L'admin ne voit ni ne choisit jamais le mot de passe de quelqu'un d'autre."""
    conn = _db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cible = _get(conn, "SELECT email, role, desactive_le FROM users WHERE id=?", (compte_id,))
        if not cible:
            raise HTTPException(404, "Compte introuvable.")
        if cible["desactive_le"]:
            raise HTTPException(409, "Compte désactivé : le réactiver d'abord.")
        inv, jeton = _creer_invitation(conn, cible["email"], cible["role"], "mot_de_passe", user)
        conn.commit()
    finally:
        conn.close()
    return {"invitation": inv, "jeton": jeton}
