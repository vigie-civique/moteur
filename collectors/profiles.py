"""
Importeur profils markdown — élus, entourage.
Parse les fichiers /profils/*.md et /profils/entourage/*.md.
"""
import re
import json
from pathlib import Path
from .config import PROFILS_DIR
from .db import transaction, upsert_entity, upsert_relation

# Données structurées des élus (source : résultats électoraux + CRs)
# ─────────────────────────────────────────────────────────────────────────────
# Les données nominatives ne sont plus dans le code.
#
# Ce module portait en dur les 15 élus, les 17 candidats non élus et un
# « entourage » de 10 personnes avec leurs années de naissance, leurs liens
# familiaux et, pour l'un d'eux, une appréciation de proximité politique non
# vérifiée. Or le dictionnaire de données publié promet que ces trois
# catégories — liens de famille, domicile partagé, date de naissance — ne sont
# JAMAIS diffusées. Le filtre de publication les écartait bien du site, mais
# elles restaient dans le dépôt et dans son historique.
#
# Elles vivent désormais dans `config/profils_locaux.json`, non versionné.
# Bénéfice second : ce module ne connaît plus Lasalle, il lit une configuration.
# C'était la principale dette de réplication du projet.
# ─────────────────────────────────────────────────────────────────────────────

PROFILS_LOCAUX = Path(__file__).resolve().parent.parent / "config" / "profils_locaux.json"


def charger_profils() -> dict:
    """Profils nominatifs locaux, ou une structure vide s'il n'y en a pas.

    Un déploiement sur une autre commune démarre sans ce fichier : l'import
    doit alors ne rien faire plutôt que d'échouer, les élus étant de toute
    façon collectés par ailleurs (RNE, élections).
    """
    try:
        with open(PROFILS_LOCAUX, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[profiles] {PROFILS_LOCAUX.name} absent — import nominatif ignoré.")
        return {}
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{PROFILS_LOCAUX} illisible : {e}") from e


def import_profiles():
    print("[profiles] Import élus, candidats, entourage...")

    profils = charger_profils()
    if not profils:
        _parse_markdown_profiles()
        return

    commune = profils.get("commune")
    if not commune:
        raise RuntimeError("profils_locaux.json : clé « commune » manquante.")
    installation = profils.get("date_installation") or "1970-01-01"

    with transaction() as conn:
        commune_id = upsert_entity(conn, **commune, confidence="verified")
        conn.execute(
            "INSERT OR IGNORE INTO services (entity_id, category)"
            " VALUES (?, ?)", (commune_id, "admin")
        )

        for liste, contenu in (profils.get("listes") or {}).items():
            for e in contenu.get("elus") or []:
                pid = _import_person(conn, e)
                _link_mandat(conn, pid, commune_id, e, liste, installation)

            for c in contenu.get("non_elus") or []:
                pid = _import_person(conn, {**c, "cm": False, "cc": False,
                                            "confidence": "verified"})
                upsert_relation(conn, pid, commune_id, "candidat",
                                source="élections_2026", confidence="verified",
                                metadata=json.dumps({"liste": liste,
                                                     "rang": c["rank"]}))

        for p in profils.get("entourage") or []:
            pid = upsert_entity(conn,
                type="person",
                name=f"{p['firstname']} {p['lastname']}",
                confidence=p.get("confidence", "probable")
            )
            conn.execute(
                "INSERT OR IGNORE INTO persons"
                " (entity_id,firstname,lastname,birth_year)"
                " VALUES (?,?,?,?)",
                (pid, p["firstname"], p["lastname"], p.get("birth_year"))
            )

    # Parse aussi les fichiers markdown pour compléter
    _parse_markdown_profiles()

    print("[profiles] OK")


def _import_person(conn, e: dict) -> int:
    from .db import upsert_entity
    name = f"{e['firstname']} {e['lastname']}"
    pid = upsert_entity(conn,
        type="person",
        name=name,
        confidence=e.get("confidence", "verified")
    )
    conn.execute(
        "INSERT OR IGNORE INTO persons"
        " (entity_id,firstname,lastname)"
        " VALUES (?,?,?)",
        (pid, e["firstname"], e["lastname"])
    )
    return pid


def _link_mandat(conn, person_id, commune_id, e: dict, liste: str, since: str):
    meta = json.dumps({
        "liste": liste,
        "rang": e.get("rank"),
        "role": e.get("role")
    })
    if e.get("cm"):
        upsert_relation(conn, person_id, commune_id, "élu_cm",
                        source="élections_2026", since=since,
                        confidence="verified", metadata=meta)
    if e.get("cc"):
        upsert_relation(conn, person_id, commune_id, "élu_cc",
                        source="élections_2026", since=since,
                        confidence="verified", metadata=meta)


def _parse_markdown_profiles():
    """
    Extrait les SIRENs et liens depuis les fichiers markdown de profils.
    Complète les relations entreprises déjà importées de SIRENE.
    """
    siren_re  = re.compile(r"SIREN\s*[:\s]*(\d[\d\s]{7,10}\d)")
    charge_re = re.compile(
        r"\|\s*\*\*Fonction\*\*\s*\|\s*(.+?)\s*\|", re.IGNORECASE
    )

    for md_file in sorted(PROFILS_DIR.glob("**/*.md")):
        text = md_file.read_text(errors="ignore")
        # SIRENs mentionnés dans ce profil
        sirens = [s.replace(" ", "") for s in siren_re.findall(text)]
        if sirens:
            # Le profil correspond à une personne — on liera les SIRENs plus tard
            # (SIRENE importer aura déjà créé les entités entreprises)
            pass
