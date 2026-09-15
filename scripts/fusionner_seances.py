#!/usr/bin/env python3
"""Fusionne les fiches de séance qu'un même conseil a produites en plusieurs.

    python3 scripts/fusionner_seances.py              # montre, n'écrit rien
    python3 scripts/fusionner_seances.py --appliquer  # fusionne

Pourquoi elles existent
-----------------------
`enregistrer_seance` identifiait une séance par l'URL du document qui la
rapporte. Or une séance en produit plusieurs — convocation, ordre du jour,
registre des délibérations, procès-verbal, annexes — et chacune faisait sa
fiche. Sur la base de Lasalle, le 15/09/2026 : 46 dates portaient deux à trois
fiches, 49 de trop sur 243, et pas une seule n'était une seconde séance tenue
le même jour. La page d'accueil affichait « Conseil municipal du 2026-06-30 »
deux fois de suite, le registre et le procès-verbal.

Le moteur ne les fabrique plus (identité sur date + assemblée). Cette reprise
range celles qui sont déjà en base : elle NE SUPPRIME AUCUNE PIÈCE — chaque
document survit dans `metadata.pieces` de la fiche conservée, et les liens
d'entités des fiches absorbées sont reportés avant leur retrait.

⚖️ La fiche conservée est la PLUS ANCIENNE (plus petit `id`) : c'est elle que
d'autres tables peuvent déjà citer. Son titre est réécrit en français au
passage — une date ISO est une clé, pas une phrase.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collectors import conseils  # noqa: E402
from collectors.db import get_conn, transaction  # noqa: E402

TYPES = tuple(p["seance"] for p in conseils.PORTEES.values())
TITRES = {p["seance"]: p["titre"] for p in conseils.PORTEES.values()}


def doublons(conn) -> list[dict]:
    """Les séances qu'une même date et une même assemblée partagent."""
    marques = ",".join("?" * len(TYPES))
    rows = conn.execute(
        f"SELECT type, date, GROUP_CONCAT(id) ids, COUNT(*) n FROM events"
        f" WHERE type IN ({marques}) AND date IS NOT NULL"
        f" GROUP BY type, date HAVING n > 1 ORDER BY date DESC", TYPES)
    groupes = []
    for r in rows:
        ids = sorted(int(i) for i in r["ids"].split(","))
        fiches = [dict(conn.execute(
            "SELECT id, source_url, metadata FROM events WHERE id=?",
            (i,)).fetchone()) for i in ids]
        groupes.append({"type": r["type"], "date": r["date"], "fiches": fiches})
    return groupes


def _fusion(fiches: list[dict]) -> tuple[dict, list]:
    """Les métadonnées des fiches absorbées, versées dans celle qu'on garde."""
    meta, pieces = {}, []
    for f in fiches:
        m = json.loads(f["metadata"] or "{}")
        for p in m.get("pieces") or []:
            pieces = conseils._avec_piece(pieces, p)
        libelle = m.get("libelle_source") or ""
        if not any(p.get("url") == f["source_url"] for p in pieces):
            pieces = conseils._avec_piece(pieces, {
                "nature": conseils.nature_de_piece(libelle),
                "libelle": libelle, "url": f["source_url"]})
        # Les clés des fiches suivantes complètent, elles n'écrasent pas : les
        # présents lus dans le procès-verbal doivent survivre au registre.
        meta = {**m, **{k: v for k, v in meta.items() if v not in (None, "", [])}}
    meta["pieces"] = pieces
    return meta, pieces


def fusionner(conn, groupe: dict, appliquer: bool) -> dict:
    fiches = groupe["fiches"]
    garde, absorbees = fiches[0], fiches[1:]
    meta, pieces = _fusion(fiches)
    depuis_portail = meta.get("depuis_portail_actes")
    url = (garde["source_url"] if depuis_portail
           else conseils._url_la_plus_probante(pieces, garde["source_url"]))
    titre = TITRES[groupe["type"]].format(
        date=conseils.date_en_francais(groupe["date"]))
    liens = 0
    if appliquer:
        for f in absorbees:
            liens += conn.execute(
                "INSERT OR IGNORE INTO event_entities (event_id, entity_id, role)"
                " SELECT ?, entity_id, role FROM event_entities WHERE event_id=?",
                (garde["id"], f["id"])).rowcount or 0
            conn.execute("DELETE FROM event_entities WHERE event_id=?", (f["id"],))
            conn.execute("DELETE FROM events WHERE id=?", (f["id"],))
        conn.execute(
            "UPDATE events SET title=?, source_url=?, metadata=? WHERE id=?",
            (titre, url, json.dumps(meta, ensure_ascii=False), garde["id"]))
    return {"garde": garde["id"], "retirees": [f["id"] for f in absorbees],
            "titre": titre, "pieces": pieces, "liens": liens}


def _jouer(conn, appliquer: bool) -> int:
    groupes = doublons(conn)
    if not groupes:
        print("Aucune séance en double.")
        return 0

    total = sum(len(g["fiches"]) - 1 for g in groupes)
    print(f"{len(groupes)} dates portent plusieurs fiches de séance, "
          f"{total} fiche(s) en trop.\n")
    for g in groupes:
        r = fusionner(conn, g, appliquer)
        print(f"  {g['date']}  {g['type']:22} garde {r['garde']}, "
              f"retire {r['retirees']}")
        print(f"      → {r['titre']}")
        for p in r["pieces"]:
            print(f"        · {p.get('nature','piece'):14} "
                  f"{(p.get('libelle') or '')[:46]}")
    print("\n" + ("Fusionné." if appliquer
                  else "Rien écrit — relancer avec --appliquer."))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--appliquer", action="store_true", help="écrit en base")
    args = ap.parse_args()

    # Sans `--appliquer`, la base est ouverte en LECTURE SEULE : une reprise
    # qui montre ce qu'elle ferait ne doit pas pouvoir l'écrire par accident.
    if args.appliquer:
        with transaction() as conn:
            return _jouer(conn, True)
    conn = get_conn(read_only=True)
    try:
        return _jouer(conn, False)
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
