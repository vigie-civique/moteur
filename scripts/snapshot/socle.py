"""Le socle du snapshot : ce dont toutes les étapes ont besoin, et rien d'autre.

Le périmètre de l'instance et ses règles de publication, l'horloge de la
construction, la lecture de la base (en lecture seule) et l'écriture d'un
fichier JSON. Une étape qui en a besoin l'importe d'ici ; elle n'a pas à
passer par `build_public_snapshot.py`, qui n'est plus que la façade des
appelants (`api.py`, `scripts/publication.py`, les essais) et le point
d'entrée en ligne de commande.

Le module ne lit rien de la base et n'écrit rien à son import — sauf les
règles de publication, lues une fois comme elles l'ont toujours été.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Le périmètre est décrit une seule fois, dans la config des collecteurs : le
# snapshot ne redéclare ni la liste des communes ni le SIREN de l'EPCI.
from collectors.config import (  # noqa: F401 — réexportés aux étapes
    COMMUNE_INSEE as INSEE_C1,
    COMMUNE_URL as URL_COMMUNE,
    EPCI_URL as URL_EPCI,
    EPCI_COMMUNES as COMMUNES_EPCI,
    EPCI_NOM as EPCI_NOM_C2,
    EPCI_SIREN as EPCI_SIREN_C2,
    DEPARTEMENT,
    TELECOMS_RAYON_KM,
)
from collectors.config import DB_PATH   # nommée dans la config
# `VIGIE_RULES` désigne d'autres règles de publication — les tests s'en servent
# pour tourner sur l'exemple versionné, un dépôt fraîchement cloné n'ayant pas
# encore de règles à lui. Le chemin est lu dans la config, comme l'atelier le lit.
from collectors.config import RULES_PATH


def load_rules(path: Path = RULES_PATH) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    required = ["confidence", "locations", "people", "relations", "events", "urls", "outputs"]
    missing = [key for key in required if key not in data]
    if missing:
        raise ValueError(f"publication_rules.json incomplet: {', '.join(missing)}")
    return data


RULES = load_rules()
DEFAULT_OUT = ROOT / RULES["outputs"]["public_snapshot_dir"]


# ── L'horloge d'une construction ─────────────────────────────────────────────
#
# Le snapshot lisait l'heure à trois endroits — `stats.json`, l'export Popolo,
# et `date('now')` dans la requête des délégués — si bien que deux fichiers
# d'une même construction ne portaient pas la même heure, et qu'aucune
# construction ne pouvait être rejouée : comparer la sortie de deux versions du
# code revenait à comparer deux instants.
#
# Elle se lit désormais UNE fois, au début de `build_snapshot`, et se donne :
# `--horloge` ou `VIGIE_HORLOGE`, au format ISO (`2026-10-04T09:45:04`). Sans
# l'un ni l'autre, c'est l'heure qu'il est, comme avant.
VARIABLE_HORLOGE = "VIGIE_HORLOGE"


def lire_horloge(valeur: str | None = None) -> datetime:
    """L'heure de la construction : donnée, ou lue — une seule fois.

    Rend une heure LOCALE sans fuseau, la forme que `generated_at` a toujours
    eue. Une valeur donnée avec son fuseau est ramenée à l'heure locale.
    """
    brut = valeur or os.environ.get(VARIABLE_HORLOGE)
    if not brut:
        return datetime.now()
    try:
        horloge = datetime.fromisoformat(brut)
    except ValueError:
        raise ValueError(
            f"{VARIABLE_HORLOGE} illisible : {brut!r} — attendu une date ISO, "
            "par exemple 2026-10-04T09:45:04") from None
    if horloge.tzinfo is not None:
        horloge = horloge.astimezone().replace(tzinfo=None)
    return horloge


def jour_utc(horloge: datetime) -> str:
    """Le jour que SQLite appelle `date('now')` à cette heure-là : il compte en
    temps universel, pas en heure locale. Entre minuit et deux heures du matin,
    les deux ne sont pas le même jour — et c'est le jour UTC que la requête des
    délégués a toujours comparé à la fin d'un mandat."""
    return horloge.astimezone(timezone.utc).date().isoformat()


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def rows(conn: sqlite3.Connection, sql: str, params=()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def row(conn: sqlite3.Connection, sql: str, params=()) -> dict | None:
    r = conn.execute(sql, params).fetchone()
    return dict(r) if r else None


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def relation_exists(conn: sqlite3.Connection, name: str) -> bool:
    """Table OU vue. `table_exists` filtre sur `type='table'` et renvoie donc
    False pour une vue — ce qui faisait silencieusement retourner un export
    vide pour `v_conflits_potentiels`."""
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?",
        (name,)
    ).fetchone() is not None


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_json_compact(path: Path, data) -> None:
    """Sans indentation ni espaces — pour ce que le navigateur télécharge.

    Les fichiers relus par un humain (stats, review) restent indentés ; l'index
    de recherche et les 2 800 fiches, non : l'indentation y pèse ~40 % du poids
    transféré pour zéro lisibilité utile.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8")


def safe_url(url: str | None) -> str | None:
    """Garde-fou : aucun chemin local ne doit sortir dans le snapshot public.

    Un `file:///Users/...` est à la fois un lien mort pour le lecteur et une
    fuite de l'arborescence personnelle. Une reprise ponctuelle a fait la
    correction en base ; ici on refuse simplement de publier le reliquat.
    """
    if not url:
        return None
    value = url.strip()
    if value.lower().startswith(("file:", "/users/", "c:\\")):
        return None
    return value
