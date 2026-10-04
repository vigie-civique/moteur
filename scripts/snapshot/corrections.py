"""Les corrections : ce que l'atelier a rectifié, et le journal des corrections du site.

`corrections.json` publie les rectifications portées par la revue (actes,
flux, marchés) et celles du journal tenu à la main
(`config/journal_corrections.json`, ou `VIGIE_JOURNAL_CORRECTIONS`) :
une correction se voit, elle ne se fait pas en silence.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from scripts.snapshot.socle import ROOT, write_json


JOURNAL_PATH = Path(os.environ.get("VIGIE_JOURNAL_CORRECTIONS")
                    or ROOT / "config" / "journal_corrections.json")
_DATE_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def lire_journal_corrections(path: Path = JOURNAL_PATH) -> list[dict]:
    """Les erreurs DU SITE, reconnues et corrigées — écrites par l'instance.

    Une donnée rectifiée à la main se relève toute seule (`corrige`). Un
    calcul faux, un doublon qui comptait deux fois, un chiffre mal nommé ne
    laissent aucune trace dans les données : ils n'existent que si quelqu'un
    les écrit. Le fichier est facultatif ; une entrée incomplète est écartée,
    jamais complétée — un journal ne s'invente pas.
    """
    if not path.exists():
        return []
    try:
        brut = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  ⚠ {path.name} illisible ({exc}) : journal des corrections vide")
        return []
    entrees = []
    for e in brut if isinstance(brut, list) else []:
        if not isinstance(e, dict):
            continue
        date, constat, correction = (str(e.get(k) or "").strip()
                                     for k in ("date", "constat", "correction"))
        page = str(e.get("page") or "").strip()
        if not (_DATE_ISO.match(date) and constat and correction):
            continue
        entrees.append({
            "date": date,
            # Un chemin du site, jamais une URL : le journal ne renvoie pas ailleurs.
            "page": page if re.fullmatch(r"/[\w\-/]*", page) else None,
            "constat": constat, "correction": correction,
            "signale_par": str(e.get("signale_par") or "").strip() or None,
        })
    return sorted(entrees, key=lambda e: e["date"], reverse=True)


def export_corrections(public_events: list[dict], public_flows: list[dict],
                       marches: list[dict], journal: list[dict]) -> dict:
    """Le journal des corrections : ce que le site a reconnu faux, et réparé.

    « Rectifié » était promis sur /methode, avec « 0 » en face et aucun endroit
    où lire ce qui avait été corrigé (audit du 24/09/2026). Un zéro se publie
    aussi : c'est un fait, pas une absence de page.
    """
    donnees = []
    for e in public_events:
        if e.get("corrige"):
            donnees.append({"nature": "acte", "id": e["id"], "type": e.get("type"),
                            "date": e.get("date"), "ancre": e.get("ancre"),
                            "libelle": e.get("title"), "champs": e["corrige"],
                            "motif": e.get("note_revue")})
    for f in public_flows:
        if f.get("corrige"):
            donnees.append({"nature": "flux", "id": f.get("id"),
                            "date": f"{f['year']}" if f.get("year") else None,
                            "libelle": f.get("description") or f.get("to_name"),
                            "champs": f["corrige"], "motif": f.get("note_revue")})
    for m in marches:
        if m.get("corrige"):
            donnees.append({"nature": "marche", "id": m.get("id"),
                            "date": m.get("date_notif"), "libelle": m.get("objet"),
                            "champs": m["corrige"], "motif": m.get("note_revue")})
    donnees.sort(key=lambda d: d.get("date") or "", reverse=True)
    return {"site": journal, "donnees": donnees}


def etape_corrections(out, public_events, public_flows, marches_data) -> dict:
    corrections = export_corrections(public_events, public_flows, marches_data,
                                     lire_journal_corrections())
    write_json(out / "corrections.json", corrections)

    return {"corrections": corrections}
