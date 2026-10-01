"""Les dossiers thématiques : lire, identifier, écrire — et décider s'ils sortent.

Un dossier est un markdown de l'INSTANCE (`<instance>/dossiers/<slug>.md`),
hors du dépôt du moteur parce qu'il nomme des personnes. Jusqu'au 01/10/2026,
une ligne `statut: publie` dans son en-tête suffisait à le mettre en ligne : le
seul texte du site écrit par un humain était aussi le seul à ne passer par
aucune relecture. Il suit désormais la règle des feuilles « en clair »
(`collectors/verdict.py`, OBJETS_A_RETENIR) : il sort RETENU à l'atelier, et
seulement tel qu'il a été relu (empreinte).

Ce que l'en-tête garde :
  titre, chapeau, maj      la présentation ;
  statut: a_developper     le dossier annonce son sujet et rien d'autre — son
                           corps ne sort pas, même retenu.
`brouillon` et `publie` ne décident plus rien : c'est le verdict qui publie.

Écrire passe par `ecrire()` : la version remplacée est gardée dans
`dossiers/.versions/<slug>/` (le répertoire est hors git, sans quoi rien ne
garderait l'historique), et l'écriture est refusée si le fichier a changé
depuis que l'éditeur l'a ouvert — deux personnes, ou une personne et un script,
ne s'écrasent pas en silence.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from .verdict import empreinte

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")
STATUTS = ("brouillon", "a_developper", "publie")


class Conflit(Exception):
    """Le fichier a changé depuis qu'il a été ouvert."""


def repertoire(racine: Path) -> Path:
    return Path(racine) / "dossiers"


def chemin(racine: Path, slug: str) -> Path:
    """Le fichier d'un dossier. Le slug est validé ici : c'est un nom de fichier
    qui vient d'une URL, il ne doit jamais sortir du répertoire."""
    if not SLUG.match(slug or ""):
        raise ValueError(f"Identifiant de dossier invalide : « {slug} » "
                         "(minuscules, chiffres et tirets).")
    return repertoire(racine) / f"{slug}.md"


def lister(racine: Path) -> list[tuple[str, Path]]:
    d = repertoire(racine)
    if not d.is_dir():
        return []
    return sorted((p.stem, p) for p in d.glob("*.md") if SLUG.match(p.stem))


def entete(texte: str) -> tuple[dict, str]:
    """L'en-tête `--- clé: valeur ---` et le corps — même lecture que le site
    (`public/src/lib/dossiers.server.js::entete`)."""
    m = re.match(r"^---\n([\s\S]*?)\n---\n?", texte)
    if not m:
        return {}, texte
    meta = {}
    for ligne in m.group(1).split("\n"):
        k = re.match(r"^([a-z_]+)\s*:\s*(.*?)\s*(#.*)?$", ligne)
        if k:
            meta[k.group(1)] = re.sub(r"^[\"']|[\"']$", "", k.group(2))
    return meta, texte[m.end():]


def empreinte_de(p: Path) -> str | None:
    return empreinte(p.read_bytes()) if p.exists() else None


# ─── L'identité en base ──────────────────────────────────────────────────────

def assurer_schema(conn) -> None:
    """La table `dossiers` et la colonne `annotations.empreinte`, sur une base
    antérieure au 01/10/2026. L'API ne passe pas par `init_db()` : sans ce
    rattrapage, le premier verdict sur un dossier échouerait."""
    conn.execute("""CREATE TABLE IF NOT EXISTS dossiers (
        id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT NOT NULL UNIQUE,
        cree_le TEXT DEFAULT (datetime('now')))""")
    colonnes = {r[1] for r in conn.execute("PRAGMA table_info(annotations)")}
    if colonnes and "empreinte" not in colonnes:
        conn.execute("ALTER TABLE annotations ADD COLUMN empreinte TEXT")


def identifiant(conn, slug: str, creer: bool = False) -> int | None:
    r = conn.execute("SELECT id FROM dossiers WHERE slug=?", (slug,)).fetchone()
    if r:
        return r[0]
    if not creer:
        return None
    return conn.execute("INSERT INTO dossiers(slug) VALUES(?)", (slug,)).lastrowid


def slug_de(conn, dossier_id: int) -> str | None:
    r = conn.execute("SELECT slug FROM dossiers WHERE id=?", (dossier_id,)).fetchone()
    return r[0] if r else None


def a_la_colonne_empreinte(conn) -> bool:
    return "empreinte" in {r[1] for r in conn.execute("PRAGMA table_info(annotations)")}


def verdict(conn, dossier_id: int | None) -> dict | None:
    """La décision posée sur un dossier, empreinte comprise (None si aucune)."""
    if dossier_id is None:
        return None
    emp = "empreinte" if a_la_colonne_empreinte(conn) else "NULL AS empreinte"
    r = conn.execute(f"SELECT review_status, note, reviewed_by, reviewed_at, {emp} "
                     "FROM annotations WHERE object_type='dossier' AND object_id=?",
                     (dossier_id,)).fetchone()
    if not r:
        return None
    return dict(zip(("review_status", "note", "reviewed_by", "reviewed_at", "empreinte"), r))


# ─── Écrire ──────────────────────────────────────────────────────────────────

def ecrire(racine: Path, slug: str, texte: str, empreinte_lue: str | None) -> str:
    """Écrit le dossier et rend sa nouvelle empreinte.

    `empreinte_lue` : celle du fichier quand l'éditeur l'a ouvert ; None pour
    CRÉER un dossier, ce qui échoue s'il existe déjà. Une empreinte qui ne
    correspond plus → `Conflit`, rien n'est écrit.
    """
    p = chemin(racine, slug)
    actuelle = empreinte_de(p)
    if actuelle != empreinte_lue:
        raise Conflit("Ce dossier a été modifié depuis que vous l'avez ouvert."
                      if actuelle else "Ce dossier n'existe plus.")
    texte = texte.replace("\r\n", "\n")
    if not texte.endswith("\n"):
        texte += "\n"
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        if p.read_text(encoding="utf-8") == texte:
            return actuelle
        versions = p.parent / ".versions" / slug
        versions.mkdir(parents=True, exist_ok=True)
        horo = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        (versions / f"{horo}-{actuelle}.md").write_bytes(p.read_bytes())
    tmp = p.with_suffix(".md.tmp")
    tmp.write_text(texte, encoding="utf-8")
    tmp.replace(p)
    return empreinte_de(p)


def modele(titre: str) -> str:
    """Le squelette d'un dossier neuf, sur le gabarit « grand écart »."""
    jour = datetime.now().strftime("%Y-%m-%d")
    return (f"---\ntitre: {titre}\nchapeau: \nmaj: {jour}\n---\n\n"
            "## L'essentiel\n\n\n\n## Ce qu'on ne sait pas\n\n\n\n"
            "## Les mots du dossier\n\n")


# ─── Publier ─────────────────────────────────────────────────────────────────

def publiables(conn, racine: Path) -> tuple[list[dict], dict]:
    """Les dossiers qui sortent, et le compte de ceux qui ne sortent pas.

    Retenu ET inchangé depuis la relecture : la règle de toutes les pages
    rédigées (`verdict.publiable_tel_quel`). Rien n'est créé en base ici : un
    dossier sans identifiant n'a jamais été retenu.
    """
    from .verdict import RETENU, modifie_depuis_relecture, publiable_tel_quel, verdict_de
    sortis, ecartes = [], {"non_retenus": [], "modifies": []}
    for slug, p in lister(racine):
        v = verdict(conn, identifiant(conn, slug))
        actuelle = empreinte_de(p)
        statut = v["review_status"] if v else None
        if not publiable_tel_quel(statut, v and v["empreinte"], actuelle):
            if modifie_depuis_relecture(statut, v and v["empreinte"], actuelle):
                ecartes["modifies"].append(slug)
            else:
                ecartes["non_retenus"].append(slug)
            continue
        assert verdict_de(statut) == RETENU
        sortis.append({"slug": slug, "texte": p.read_text(encoding="utf-8"),
                       "empreinte": actuelle, "relu_le": (v["reviewed_at"] or "")[:10]})
    return sortis, ecartes
