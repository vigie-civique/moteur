#!/usr/bin/env python3
"""Exporte le travail d'arbitrage de l'atelier, pour le partager ou le sauver.

    python3 scripts/exporter_decisions.py                    # → decisions/
    python3 scripts/exporter_decisions.py --vers /chemin
    python3 scripts/exporter_decisions.py --sans-personnes

CE QUI SORT, ET POURQUOI SEULEMENT ÇA
La base est reconstructible : n'importe qui peut la refaire avec le code et un
code INSEE, puisque les collecteurs relisent des sources publiques. Ce qui ne se
régénère pas, c'est le jugement humain — les sièges tranchés, les sites validés,
les corrections, les notes. C'est petit, c'est précieux, et c'est ça qu'on
partage.

Les décisions sont désignées par des CLÉS NATURELLES (SIREN, RNA, identifiant
d'avis, empreinte de source), jamais par les `id` locaux, qui ne veulent rien
dire sur une autre machine. Cf. scripts/decisions.py.

⚠ CE FICHIER PEUT NOMMER DES PERSONNES PHYSIQUES.
L'atelier travaille sur la base non filtrée. Un dépôt qui reçoit cet export doit
être PRIVÉ, et ses membres doivent déjà avoir accès à la base. `--sans-personnes`
retire les décisions portant sur des personnes physiques — au prix de devoir les
reprendre à la main sur l'autre machine.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collectors import saisies as _saisies  # noqa: E402
from collectors.config import COMMUNE_INSEE, COMMUNE_NAME  # noqa: E402
from collectors.db import get_conn  # noqa: E402
from scripts.decisions import CLES, cle_entite  # noqa: E402


def _ecrire(chemin: Path, lignes: list[dict]) -> int:
    """Une décision par ligne, triées : un diff git doit se lire."""
    lignes = sorted(lignes, key=lambda d: (d.get("cle") or "", json.dumps(d, sort_keys=True)))
    chemin.write_text(
        "".join(json.dumps(l, ensure_ascii=False, sort_keys=True) + "\n" for l in lignes),
        encoding="utf-8")
    return len(lignes)


def exporter(conn, dest: Path, sans_personnes: bool) -> dict[str, int]:
    dest.mkdir(parents=True, exist_ok=True)
    orphelines = 0
    personnes_retirees = 0

    def est_personne(entity_id: int) -> bool:
        r = conn.execute("SELECT type FROM entities WHERE id=?", (entity_id,)).fetchone()
        return bool(r) and r[0] == "person"

    # ── 1. Annotations : le cœur de l'arbitrage (actes, marchés, flux) ───────
    annotations = []
    for a in conn.execute("""SELECT object_type, object_id, review_status, confidence,
                                    note, reviewed_by, reviewed_at
                             FROM annotations"""):
        type_, oid = a[0], a[1]
        fabrique = CLES.get(type_)
        if not fabrique:
            continue
        k = fabrique(conn, oid)
        if not k:
            orphelines += 1
            continue
        annotations.append({
            "objet": type_, "cle": k[0], "libelle": k[1],
            "statut": a[2], "confidence": a[3], "note": a[4],
            "par": a[5], "le": a[6],
        })

    # ── 2. Statuts d'entités : ce que la file de revue a tranché ─────────────
    statuts = []
    for eid, statut, nom in conn.execute(
            """SELECT id, validation_status, name FROM entities
               WHERE validation_status IS NOT NULL AND validation_status != 'unverified'"""):
        if sans_personnes and est_personne(eid):
            personnes_retirees += 1
            continue
        k = cle_entite(conn, eid)
        if not k:
            orphelines += 1
            continue
        statuts.append({"cle": k[0], "libelle": k[1], "statut": statut})

    # ── 3. Sites web validés : le maillon rare ──────────────────────────────
    # Rare parce qu'il n'existe dans aucun open data et qu'il coûte une
    # vérification humaine par entité. C'est la partie la plus chère à refaire.
    sites = []
    for eid, url, statut in conn.execute(
            """SELECT entity_id, url, status FROM entity_websites
               WHERE status != 'candidate'"""):
        if sans_personnes and est_personne(eid):
            personnes_retirees += 1
            continue
        k = cle_entite(conn, eid)
        if not k:
            orphelines += 1
            continue
        sites.append({"cle": k[0], "libelle": k[1], "url": url, "statut": statut})

    # ── 4. Relations arbitrées : accepté / rejeté / ignoré ───────────────────
    relations = []
    for from_id, to_id, rtype, statut, note, le in conn.execute(
            """SELECT from_id, to_id, relation_type, review_status, review_note, reviewed_at
               FROM relation_candidates WHERE review_status != 'pending'"""):
        if sans_personnes and (est_personne(from_id) or est_personne(to_id)):
            personnes_retirees += 1
            continue
        ka, kb = cle_entite(conn, from_id), cle_entite(conn, to_id)
        if not ka or not kb:
            orphelines += 1
            continue
        relations.append({"cle": f"{ka[0]}→{kb[0]}:{rtype}",
                          "de": ka[0], "vers": kb[0], "de_libelle": ka[1],
                          "vers_libelle": kb[1], "type": rtype,
                          "statut": statut, "note": note, "le": le})

    # ── 5. Saisies manuelles : ce qu'aucun collecteur ne peut refaire ────────
    # Les autres sections exportent des JUGEMENTS sur des lignes existantes.
    # Celle-ci exporte des lignes qui n'existent nulle part ailleurs : un budget
    # voté, une dotation notifiée, une subvention lue dans un compte rendu. Si
    # elle manquait, la reprise sur une autre machine perdrait la partie la plus
    # chère du travail — celle qui a demandé de lire les documents.
    #
    # LE POINT DÉLICAT est le même que partout ici : une saisie qui désigne son
    # bénéficiaire par `{"id": 4471}` ne veut rien dire ailleurs, où 4471 est une
    # autre entité. On remplace donc l'identifiant local par une clé naturelle,
    # et l'import fera le chemin inverse.
    saisies = []
    for s in _saisies.charger().get("saisies", []):
        ligne = json.loads(json.dumps(s, ensure_ascii=False))   # copie profonde
        retiree = bool(ligne.get("retire"))
        concerne_personne = False
        for champ, valeur in list((ligne.get("valeurs") or {}).items()):
            if isinstance(valeur, dict) and valeur.get("id"):
                k = cle_entite(conn, int(valeur["id"]))
                if not k:
                    orphelines += 1
                    continue
                if est_personne(int(valeur["id"])):
                    concerne_personne = True
                ligne["valeurs"][champ] = {"cle": k[0], "libelle": k[1]}
        if ligne.get("objet") == "entite" and \
                (ligne.get("valeurs") or {}).get("type") == "person":
            concerne_personne = True
        if sans_personnes and concerne_personne:
            personnes_retirees += 1
            continue
        # Le document local ne suit pas : c'est un fichier, parfois lourd, et
        # son identifiant est local lui aussi. L'empreinte, elle, voyage — elle
        # permet de reconnaître le document s'il est déjà présent en face.
        source = ligne.get("source") or {}
        source.pop("raw_document_id", None)
        ligne["source"] = source
        ligne["cle"] = f"saisie:{ligne.get('id')}"
        ligne["retire"] = retiree
        saisies.append(ligne)

    compte = {
        "annotations": _ecrire(dest / "annotations.jsonl", annotations),
        "entites-statuts": _ecrire(dest / "entites-statuts.jsonl", statuts),
        "sites": _ecrire(dest / "sites.jsonl", sites),
        "relations-arbitrees": _ecrire(dest / "relations-arbitrees.jsonl", relations),
        "saisies": _ecrire(dest / "saisies.jsonl", saisies),
    }

    (dest / "manifeste.json").write_text(json.dumps({
        "_doc": "Décisions d'arbitrage d'un atelier Vigie Civique. "
                "Désignées par clés naturelles, applicables sur toute base de la "
                "même commune. Peut nommer des personnes physiques : dépôt privé.",
        "commune": COMMUNE_NAME,
        "insee": COMMUNE_INSEE,
        "exporte_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sans_personnes": sans_personnes,
        "compte": compte,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    compte["_orphelines"] = orphelines
    compte["_personnes_retirees"] = personnes_retirees
    return compte


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vers", default="decisions", help="répertoire de sortie")
    ap.add_argument("--sans-personnes", action="store_true",
                    help="retire les décisions portant sur des personnes physiques")
    args = ap.parse_args()

    conn = get_conn()
    dest = Path(args.vers)
    compte = exporter(conn, dest, args.sans_personnes)

    print(f"Décisions de {COMMUNE_NAME} ({COMMUNE_INSEE}) → {dest}/")
    for nom in ("annotations", "entites-statuts", "sites", "relations-arbitrees"):
        print(f"   {compte[nom]:>5}  {nom}.jsonl")
    if compte["_personnes_retirees"]:
        print(f"\n   {compte['_personnes_retirees']} décision(s) sur des personnes "
              f"physiques retirée(s) (--sans-personnes)")
    if compte["_orphelines"]:
        print(f"\n   ⚠ {compte['_orphelines']} décision(s) portant sur un objet "
              f"absent de la base : non exportées.")
    total = sum(compte[n] for n in ("annotations", "entites-statuts", "sites",
                                    "relations-arbitrees"))
    if not total:
        print("\n   Rien à exporter : aucun arbitrage n'a encore été fait.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
