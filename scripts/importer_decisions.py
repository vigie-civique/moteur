#!/usr/bin/env python3
"""Applique à cette base les décisions d'arbitrage d'un autre atelier.

    python3 scripts/importer_decisions.py                    # simulation
    python3 scripts/importer_decisions.py --appliquer
    python3 scripts/importer_decisions.py --depuis /chemin --appliquer

CE QU'IL FAIT, ET CE QU'IL REFUSE DE FAIRE
Il rattache chaque décision par sa clé naturelle et l'applique. Trois cas
sortent du lot et sont TOUJOURS rapportés plutôt que tranchés en silence :

  non rattachées — la clé ne désigne rien ici. L'autre atelier a collecté
                   quelque chose que cette base n'a pas. Ce n'est pas une
                   erreur, c'est une information.
  désaccords     — les deux ateliers ont jugé le même objet différemment.
                   C'est un désaccord ÉDITORIAL, pas un conflit technique :
                   il doit remonter à un humain. Rien n'est écrasé sans --forcer.
  déjà à jour    — la décision est identique à celle d'ici.

Refuser de fusionner automatiquement deux jugements contraires est le point
important de ce script. Un dispositif qui distingue un fait d'une lecture ne
peut pas décider tout seul laquelle des deux lectures a raison.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collectors import saisies as _saisies  # noqa: E402
from collectors.config import COMMUNE_INSEE, COMMUNE_NAME  # noqa: E402
from collectors.db import get_conn  # noqa: E402
from scripts.decisions import resoudre  # noqa: E402


def _lire(chemin: Path) -> list[dict]:
    if not chemin.is_file():
        return []
    return [json.loads(l) for l in chemin.read_text(encoding="utf-8").splitlines() if l.strip()]


class Rapport:
    def __init__(self):
        self.applique = 0
        self.a_jour = 0
        self.non_rattachees: list[str] = []
        self.sans_objet: list[str] = []
        self.desaccords: list[str] = []

    def resume(self, forcer: bool) -> None:
        print(f"\n   {self.applique:>5}  appliquée(s)")
        print(f"   {self.a_jour:>5}  déjà à jour")
        if self.desaccords:
            titre = "écrasé(s) (--forcer)" if forcer else "DÉSACCORD — non appliqué(s)"
            print(f"   {len(self.desaccords):>5}  {titre}")
            for d in self.desaccords[:8]:
                print(f"          {d}")
            if len(self.desaccords) > 8:
                print(f"          … {len(self.desaccords) - 8} autres")
        # Deux situations très différentes, qu'il ne faut pas confondre :
        # l'objet n'existe pas ici, ou il existe mais il n'y a rien à arbitrer.
        # La première dit que les deux collectes divergent ; la seconde, que
        # cette base n'a pas encore produit la piste — un `run_all` la produira.
        if self.non_rattachees:
            print(f"   {len(self.non_rattachees):>5}  objet inconnu ici — les deux "
                  f"collectes divergent")
            for d in self.non_rattachees[:5]:
                print(f"          {d}")
            if len(self.non_rattachees) > 5:
                print(f"          … {len(self.non_rattachees) - 5} autres")
        if self.sans_objet:
            print(f"   {len(self.sans_objet):>5}  objet connu, mais aucune piste à "
                  f"arbitrer ici")
            for d in self.sans_objet[:5]:
                print(f"          {d}")
            if len(self.sans_objet) > 5:
                print(f"          … {len(self.sans_objet) - 5} autres")


def _appliquer(conn, sql, params, rap, appliquer):
    if appliquer:
        conn.execute(sql, params)
    rap.applique += 1


def importer(conn, src: Path, appliquer: bool, forcer: bool) -> Rapport:
    rap = Rapport()

    # ── Annotations ─────────────────────────────────────────────────────────
    for d in _lire(src / "annotations.jsonl"):
        oid = resoudre(conn, d["cle"])
        if oid is None:
            rap.non_rattachees.append(f"[{d['objet']}] {d.get('libelle', d['cle'])[:56]}")
            continue
        actuel = conn.execute(
            "SELECT review_status FROM annotations WHERE object_type=? AND object_id=?",
            (d["objet"], oid)).fetchone()
        if actuel and actuel[0] == d["statut"]:
            rap.a_jour += 1
            continue
        if actuel and actuel[0] not in ("pending", None) and not forcer:
            rap.desaccords.append(
                f"[{d['objet']}] {d.get('libelle', '')[:44]} — ici « {actuel[0]} », "
                f"reçu « {d['statut']} »")
            continue
        _appliquer(conn, """
            INSERT INTO annotations (object_type, object_id, review_status,
                                     confidence, note, reviewed_by, reviewed_at)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(object_type, object_id) DO UPDATE SET
              review_status=excluded.review_status, confidence=excluded.confidence,
              note=excluded.note, reviewed_by=excluded.reviewed_by,
              reviewed_at=excluded.reviewed_at, updated_at=datetime('now')
        """, (d["objet"], oid, d["statut"], d.get("confidence"), d.get("note"),
              d.get("par"), d.get("le")), rap, appliquer)

    # ── Statuts d'entités ───────────────────────────────────────────────────
    for d in _lire(src / "entites-statuts.jsonl"):
        eid = resoudre(conn, d["cle"])
        if eid is None:
            rap.non_rattachees.append(f"[entité] {d.get('libelle', d['cle'])[:56]}")
            continue
        actuel = conn.execute("SELECT validation_status FROM entities WHERE id=?",
                              (eid,)).fetchone()[0]
        if actuel == d["statut"]:
            rap.a_jour += 1
            continue
        if actuel not in ("unverified", None) and not forcer:
            rap.desaccords.append(f"[entité] {d.get('libelle','')[:44]} — ici "
                                  f"« {actuel} », reçu « {d['statut']} »")
            continue
        _appliquer(conn, "UPDATE entities SET validation_status=? WHERE id=?",
                   (d["statut"], eid), rap, appliquer)

    # ── Sites web ───────────────────────────────────────────────────────────
    for d in _lire(src / "sites.jsonl"):
        eid = resoudre(conn, d["cle"])
        if eid is None:
            rap.non_rattachees.append(f"[site] {d.get('libelle', d['cle'])[:56]}")
            continue
        actuel = conn.execute(
            "SELECT status FROM entity_websites WHERE entity_id=? AND url=?",
            (eid, d["url"])).fetchone()
        if actuel is None:
            # L'URL n'a pas été trouvée ici : la décision la fait exister, car
            # c'est justement le travail qu'on ne veut pas refaire.
            _appliquer(conn, """INSERT INTO entity_websites (entity_id, url, status, found_by)
                                VALUES (?,?,?,'import')""",
                       (eid, d["url"], d["statut"]), rap, appliquer)
            continue
        if actuel[0] == d["statut"]:
            rap.a_jour += 1
            continue
        if actuel[0] != "candidate" and not forcer:
            rap.desaccords.append(f"[site] {d['url'][:44]} — ici « {actuel[0]} », "
                                  f"reçu « {d['statut']} »")
            continue
        _appliquer(conn, "UPDATE entity_websites SET status=? WHERE entity_id=? AND url=?",
                   (d["statut"], eid, d["url"]), rap, appliquer)

    # ── Relations arbitrées ─────────────────────────────────────────────────
    for d in _lire(src / "relations-arbitrees.jsonl"):
        a, b = resoudre(conn, d["de"]), resoudre(conn, d["vers"])
        if a is None or b is None:
            rap.non_rattachees.append(
                f"[relation] {d.get('de_libelle','?')[:26]} → {d.get('vers_libelle','?')[:26]}")
            continue
        actuel = conn.execute(
            """SELECT review_status FROM relation_candidates
               WHERE from_id=? AND to_id=? AND relation_type=?""",
            (a, b, d["type"])).fetchone()
        if actuel is None:
            # Les deux entités existent, mais aucune piste ne les relie ici :
            # cette base n'a pas encore fait tourner le détecteur, ou il n'a rien
            # vu. La décision reste applicable plus tard, elle n'est pas perdue.
            rap.sans_objet.append(
                f"[relation] {d.get('de_libelle','?')[:24]} → "
                f"{d.get('vers_libelle','?')[:24]} ({d['type']})")
            continue
        if actuel[0] == d["statut"]:
            rap.a_jour += 1
            continue
        if actuel[0] != "pending" and not forcer:
            rap.desaccords.append(
                f"[relation] {d.get('de_libelle','')[:34]} — ici « {actuel[0]} », "
                f"reçu « {d['statut']} »")
            continue
        _appliquer(conn, """UPDATE relation_candidates
                            SET review_status=?, review_note=?, reviewed_at=?
                            WHERE from_id=? AND to_id=? AND relation_type=?""",
                   (d["statut"], d.get("note"), d.get("le"), a, b, d["type"]),
                   rap, appliquer)

    # ── Saisies manuelles ───────────────────────────────────────────────────
    # Les sections précédentes posent un jugement sur une ligne qui existe déjà
    # ici. Celle-ci apporte des lignes qui n'existent nulle part ailleurs : elle
    # n'écrit donc pas en base, elle complète `config/saisies.json`, et c'est le
    # collecteur `saisies` qui les insérera — le même chemin que pour une saisie
    # faite à la main sur cette machine.
    recues = _lire(src / "saisies.jsonl")
    if recues:
        fichier = _saisies.charger()
        connues = {s.get("id"): s for s in fichier.get("saisies", [])}
        for d in recues:
            d = dict(d)
            d.pop("cle", None)
            # Le chemin inverse de l'export : la clé naturelle redevient
            # l'identifiant LOCAL de cette base — ou la saisie est écartée.
            # Rattacher au hasard serait pire que ne rien importer.
            rattachement_perdu = False
            for champ, valeur in list((d.get("valeurs") or {}).items()):
                if isinstance(valeur, dict) and valeur.get("cle"):
                    eid = resoudre(conn, valeur["cle"])
                    if eid is None:
                        rattachement_perdu = True
                        break
                    d["valeurs"][champ] = {"id": eid}
            if rattachement_perdu:
                rap.non_rattachees.append(
                    f"[saisie {d.get('objet')}] tiers absent de cette base")
                continue

            ancienne = connues.get(d.get("id"))
            if ancienne is None:
                fichier.setdefault("saisies", []).append(d)
                rap.applique += 1
            elif ancienne == d:
                rap.a_jour += 1
            elif d.get("retire") and not ancienne.get("retire"):
                # Un retrait se propage toujours : ne pas publier est le côté
                # prudent de la décision.
                ancienne.update(d)
                rap.applique += 1
            elif not forcer:
                rap.desaccords.append(
                    f"[saisie {d.get('objet')}] déjà présente ici, contenu différent")
            else:
                ancienne.update(d)
                rap.applique += 1

        if appliquer:
            _saisies.enregistrer(fichier)
            _saisies.import_saisies()

    return rap


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--depuis", default="decisions", help="répertoire des décisions")
    ap.add_argument("--appliquer", action="store_true", help="écrit en base")
    ap.add_argument("--forcer", action="store_true",
                    help="écrase les décisions d'ici en cas de désaccord")
    args = ap.parse_args()

    src = Path(args.depuis)
    manifeste = src / "manifeste.json"
    if not manifeste.is_file():
        print(f"✖ {src}/manifeste.json introuvable.", file=sys.stderr)
        return 1
    m = json.loads(manifeste.read_text(encoding="utf-8"))

    if str(m.get("insee")) != str(COMMUNE_INSEE):
        print(f"✖ Ces décisions portent sur {m.get('commune')} ({m.get('insee')}), "
              f"cette base sur {COMMUNE_NAME} ({COMMUNE_INSEE}).\n"
              f"  Une décision ne se transpose pas d'une commune à l'autre.",
              file=sys.stderr)
        return 1

    print(f"Décisions de {m.get('commune')} exportées le {m.get('exporte_le','?')[:16]}")
    conn = get_conn()
    if args.appliquer:
        with conn:
            rap = importer(conn, src, True, args.forcer)
    else:
        rap = importer(conn, src, False, args.forcer)
    rap.resume(args.forcer)

    if not args.appliquer:
        print("\n   Simulation. Relancer avec --appliquer pour écrire.")
    elif rap.applique:
        print("\n   Régénérer le snapshot pour que le site en tienne compte.")
    if rap.desaccords and not args.forcer:
        print("\n   Les désaccords sont à trancher dans l'atelier, objet par objet.\n"
              "   `--forcer` fait gagner les décisions reçues sur les vôtres :\n"
              "   à n'utiliser que si vous savez pourquoi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
