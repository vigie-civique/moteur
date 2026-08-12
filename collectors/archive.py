"""
archive.py — Conservation brute de toute source récupérée.

Toute page/PDF/JSON scrapé peut être archivé tel quel sur disque
(data/raw/<source>/) et tracé dans la table raw_documents. Dédup par sha256 :
une source inchangée n'est pas redupliquée (last_seen mis à jour). Permet de
re-parser hors-ligne même si la source disparaît (lasalle.fr ne garde que le
dernier CR, les PDF préfecture tournent, etc.).

Usage programmatique (depuis un collecteur) :
    from .archive import archive_url, archive_bytes
    archive_url(conn, "https://www.lasalle.fr/...", source="lasalle.fr")
    archive_bytes(conn, raw_pdf, source="prefecture-gard", url=None,
                  doc_type="pdf", title="CM 28.05.26 - DELIBERATIONS.pdf")
"""
import hashlib
import json
import mimetypes
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from .config import HEADERS, ROOT

RAW_DIR = ROOT / "data" / "raw"

_EXT = {"html": "html", "pdf": "pdf", "json": "json", "csv": "csv", "txt": "txt",
        "xlsx": "xlsx"}

# UA navigateur pour les sources anti-bot (emploi-collectivites = 403 sinon)
_BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36")


def _ssl_ctx():
    """Contexte SSL : vérifié via certifi si dispo, sinon tolérant (archivage de pages publiques)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl._create_unverified_context()


def _guess_doc_type(url: str | None, content_type: str | None, raw: bytes) -> str:
    if raw[:5] == b"%PDF-":
        return "pdf"
    ct = (content_type or "").lower()
    if "pdf" in ct:
        return "pdf"
    if "json" in ct:
        return "json"
    if "html" in ct:
        return "html"
    if "csv" in ct:
        return "csv"
    if url:
        ext = Path(urlparse(url).path).suffix.lower().lstrip(".")
        if ext in _EXT:
            return ext
    # défaut : html pour les pages web, txt sinon
    return "html" if raw[:15].lstrip().lower().startswith(b"<") else "txt"


def archive_bytes(conn, raw: bytes, *, source: str, url: str | None = None,
                  doc_type: str | None = None, http_status: int | None = None,
                  title: str | None = None, metadata: dict | None = None) -> dict:
    """
    Conserve un contenu brut. Idempotent par sha256.
    Retourne {id, sha256, local_path, deduped: bool}.
    """
    sha = hashlib.sha256(raw).hexdigest()
    row = conn.execute(
        "SELECT id, local_path FROM raw_documents WHERE sha256=?", (sha,)
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE raw_documents SET last_seen=datetime('now') WHERE sha256=?", (sha,)
        )
        rid = row[0] if not isinstance(row, dict) else row["id"]
        lp = row[1] if not isinstance(row, dict) else row["local_path"]
        return {"id": rid, "sha256": sha, "local_path": lp, "deduped": True}

    dt = doc_type or _guess_doc_type(url, None, raw)
    ext = _EXT.get(dt, "bin")
    dest_dir = RAW_DIR / source
    dest_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{sha[:16]}.{ext}"
    dest = dest_dir / fname
    dest.write_bytes(raw)
    local_path = str(dest.relative_to(ROOT))

    cur = conn.execute(
        "INSERT INTO raw_documents"
        " (source,url,doc_type,sha256,byte_size,local_path,http_status,title,metadata)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (source, url, dt, sha, len(raw), local_path, http_status, title,
         json.dumps(metadata, ensure_ascii=False) if metadata else None),
    )
    return {"id": cur.lastrowid, "sha256": sha, "local_path": local_path, "deduped": False}


def archive_fetch(source: str, url: str | None, raw: bytes,
                  content_type: str | None = None,
                  http_status: int | None = None,
                  doc_type: str | None = None,
                  title: str | None = None,
                  metadata: dict | None = None) -> None:
    """
    Archivage « fire-and-forget » depuis un collecteur, sans connexion partagée.
    Ouvre sa propre connexion courte (les fetch ont lieu hors transaction d'écriture
    des collecteurs → pas de contention WAL) et ne lève jamais d'exception : un échec
    d'archivage ne doit jamais interrompre une collecte.
    """
    if not raw:
        return
    try:
        from .db import get_conn
        conn = get_conn()
        try:
            dt = doc_type or _guess_doc_type(url, content_type, raw)
            archive_bytes(conn, raw, source=source, url=url, doc_type=dt,
                          http_status=http_status, title=title, metadata=metadata)
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"  [archive][skip] {url} → {e}")


def fetch_json(url: str, *, source: str, headers: dict | None = None,
               timeout: int = 30, archive_url: str | None = None):
    """
    GET une URL d'API, archive la réponse brute (dédup sha256), retourne le JSON.
    Les erreurs HTTP/réseau remontent à l'appelant (retry/fallback inchangés).
    archive_url : URL enregistrée en base à la place de l'URL réelle (ex. token masqué).
    """
    req = urllib.request.Request(url, headers=headers or HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        ct = r.headers.get_content_type()
        status = r.status
    archive_fetch(source, archive_url or url, raw, content_type=ct, http_status=status)
    return json.loads(raw)


def archive_url(conn, url: str, *, source: str, title: str | None = None,
                timeout: int = 20, metadata: dict | None = None) -> dict | None:
    """Télécharge une URL et l'archive. Retourne le dict archive_bytes ou None si échec."""
    req = urllib.request.Request(url, headers={**HEADERS, "User-Agent": _BROWSER_UA})
    raw = ct = status = None
    for ctx in (_ssl_ctx(), ssl._create_unverified_context()):  # retry SSL non-vérifié si chaîne incomplète
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                raw = r.read()
                ct = r.headers.get_content_type()
                status = r.status
            break
        except urllib.error.URLError as e:
            if isinstance(getattr(e, "reason", None), ssl.SSLError):
                continue  # tenter sans vérification
            print(f"  [archive][erreur] {url} → {e}")
            return None
        except (TimeoutError, Exception) as e:
            print(f"  [archive][erreur] {url} → {e}")
            return None
    if raw is None:
        return None
    dt = _guess_doc_type(url, ct, raw)
    res = archive_bytes(conn, raw, source=source, url=url, doc_type=dt,
                        http_status=status, title=title, metadata=metadata)
    flag = "déjà archivé" if res["deduped"] else f"NOUVEAU → {res['local_path']}"
    print(f"  [archive] {url} ({len(raw)} o, {dt}) — {flag}")
    return res
