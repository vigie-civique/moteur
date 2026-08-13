"""
Création d'un utilisateur atelier
Usage: python scripts/create_user.py add --email vous@exemple.fr --role admin
"""
import argparse
import getpass
import hashlib
import sqlite3
from pathlib import Path

import bcrypt


def hash_password(password: str) -> str:
    pre = hashlib.sha256(password.encode()).hexdigest().encode()
    return bcrypt.hashpw(pre, bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    pre = hashlib.sha256(password.encode()).hexdigest().encode()
    return bcrypt.checkpw(pre, hashed.encode())

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collectors.config import DB_PATH


def create_user(email: str, role: str, password: str) -> None:
    hashed = hash_password(password)
    conn = sqlite3.connect(str(DB_PATH))
    try:
        existing = conn.execute(
            "SELECT id, role FROM users WHERE email=?", (email.lower(),)
        ).fetchone()
        if existing:
            print(f"Utilisateur {email} existe déjà (id={existing[0]}, rôle={existing[1]})")
            return
        conn.execute(
            "INSERT INTO users(email, password_hash, role) VALUES(?,?,?)",
            (email.lower().strip(), hashed, role),
        )
        conn.commit()
        print(f"✓ Utilisateur créé : {email} ({role})")
    except Exception as e:
        print(f"ERREUR: {e}")
    finally:
        conn.close()


def list_users() -> None:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        rows = conn.execute(
            "SELECT id, email, role, last_login, created_at FROM users ORDER BY id"
        ).fetchall()
        if not rows:
            print("Aucun utilisateur.")
            return
        for r in rows:
            print(f"  [{r[0]}] {r[1]} ({r[2]}) — dernier login: {r[3] or 'jamais'}")
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gérer les utilisateurs atelier")
    sub = parser.add_subparsers(dest="cmd")

    add_p = sub.add_parser("add", help="Créer un utilisateur")
    add_p.add_argument("--email", required=True)
    add_p.add_argument("--role", choices=["admin", "validator", "contributor"], default="admin")

    sub.add_parser("list", help="Lister les utilisateurs")

    args = parser.parse_args()

    if args.cmd == "list" or args.cmd is None:
        list_users()
    elif args.cmd == "add":
        password = getpass.getpass("Mot de passe (12 car. min) : ")
        confirm  = getpass.getpass("Confirmer : ")
        if password != confirm:
            print("Les mots de passe ne correspondent pas")
            exit(1)
        if len(password) < 12:
            print("Mot de passe trop court (12 caractères minimum)")
            exit(1)
        create_user(args.email, args.role, password)
