"""
dirigeants_deports.py — Déduire les dirigeants d'associations des déports du conseil.

**Le problème résolu.** Le graphe public plafonne parce que l'argent de la commune
va aux associations (67 des 104 bénéficiaires) et que **le RNA ne publie pas leurs
dirigeants** — la liste déposée en préfecture n'est pas diffusée. Vérifié :
`recherche-entreprises` rend 0 dirigeant pour la nature juridique 9220, et le JO
des associations n'a aucun champ de ce type.

**Le signal exploité.** Quand le conseil vote une subvention, le compte rendu
note qui s'est retiré du vote — « Mme X ne participe pas au vote » sur la
délibération attribuant une subvention à l'association qu'elle préside. Un élu
ne se déporte que s'il a un intérêt dans la structure. Ce couple (élu, association) est donc une **hypothèse
forte**, déjà présente en base dans `metadata.conflit_interet`.

**Ce que le signal ne prouve pas.** Il établit un intérêt, pas un rôle précis :
président, trésorier, simple membre, ou lien familial. Les candidats sont donc
écrits en `relation_candidates` avec `confidence='probable'` et le rôle
`dirigeant` **à confirmer ou corriger par un valideur** — jamais insérés
directement dans `relations`, et donc exclus de la publication tant qu'ils ne
sont pas acceptés.

**Deux pièges de rapprochement, rencontrés en écrivant ce collecteur :**

1. Matcher un nom par **sous-chaîne** est faux : « ANNE » est contenu dans
   « MARIANNE », ce qui attribuait à *Anne SEO* les déports de *Marianne
   LICHTENBERG*. Le rapprochement se fait mot à mot.
2. Les mots du vallon ne discriminent rien : « LASALLOIS » apparaît dans quinze
   associations, si bien que la délibération « Subvention — Vélo Club Lasallois »
   se rapprochait du Judo-Club, du Tennis Club et du Club taurin. Ces mots sont
   écartés du calcul de similarité.

Usage :
  python3 -m collectors.dirigeants_deports --dry-run
  python3 -m collectors.dirigeants_deports
  python3 -m collectors.dirigeants_deports --seuil 0.4
  python3 -m collectors.dirigeants_deports --stats
"""
from __future__ import annotations

import argparse
import json
import unicodedata

from .config import COMMUNES, DEPARTEMENT
from .db import get_conn

# Mots trop répandus sur le territoire pour identifier une association. Sans
# cette liste, la similarité de noms est dominée par la géographie locale.
# Les noms des communes du registre y sont ajoutés automatiquement : ce sont
# eux qui saturent les intitulés, et les lister à la main revenait à figer le
# périmètre à celui d'une commune précise.
GENERIQUES = {
    "ASSOCIATION", "ASSOC", "COMITE", "CLUB", "LES", "LE", "LA", "DE", "DES",
    "DU", "ET", "AMIS", "SOU", "POUR", "AUX", "SUR", "EN", "AU",
    "LOCAL", "LOCALE", "UNION", "SPORTIVE",
    "SPORT", "SPORTS", "ANCIENS", "AVENIR", "ENSEMBLE",
    # Vocabulaire des titres de délibération : présent partout, donc sans
    # pouvoir discriminant. Le laisser passer écrasait la similarité —
    # « Subvention 2025 — L'Art Scène » tombait à 0,33 face à « L'ART SCENE »
    # alors que le seul mot utile, SCENE, correspondait exactement.
    "SUBVENTION", "SUBVENTIONS", "DEMANDE", "DEMANDES", "ANNUELLE",
    "EXCEPTIONNELLE", "VERSEMENT", "ATTRIBUTION", "CONVENTION",
}


def _utile(mot: str) -> bool:
    """Un mot discriminant : assez long, pas générique, et pas une année."""
    return len(mot) >= 4 and mot not in GENERIQUES and not mot.isdigit()

RELATION = "dirigeant"          # hypothèse à arbitrer par le valideur
SIGNAL = "deport_conseil"
SEUIL_DEFAUT = 0.34             # similarité de Jaccard minimale


def norm(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return " ".join(s.upper().replace("-", " ").replace("'", " ").split())


def mots_cles(nom: str | None) -> set[str]:
    """Mots discriminants d'un nom d'association ou d'un titre de délibération."""
    return {m for m in norm(nom).split() if _utile(m)}


def deports(conn) -> list[dict]:
    """Délibérations portant une mention de retrait du vote."""
    return [dict(r) for r in conn.execute("""
        SELECT id, date, title, source_url,
               json_extract(metadata,'$.conflit_interet') AS mention
        FROM events
        WHERE json_extract(metadata,'$.conflit_interet') IS NOT NULL
          AND json_extract(metadata,'$.conflit_interet') NOT IN ('false','0','')
        ORDER BY date
    """)]


def _personnes(conn) -> list[tuple[int, str, str]]:
    return [(r["id"], norm(r["name"]), r["name"]) for r in
            conn.execute("SELECT id, name FROM entities WHERE type='person'")]


def _associations(conn) -> list[tuple[int, str, set[str]]]:
    return [(r["id"], r["name"], mots_cles(r["name"])) for r in conn.execute(
        "SELECT e.id, e.name FROM entities e"
        " JOIN associations a ON a.entity_id = e.id")]


def _liens_existants(conn) -> set[tuple[int, int]]:
    """Couples déjà reliés, dans un sens ou l'autre — à ne pas re-proposer."""
    paires = {(r["from_id"], r["to_id"]) for r in conn.execute(
        "SELECT from_id, to_id FROM relations WHERE relation_type IN"
        " ('dirigeant','président','gérant','trésorier','secrétaire','membre')")}
    return paires | {(b, a) for a, b in paires}


def extraire(conn, seuil: float = SEUIL_DEFAUT) -> list[dict]:
    """Couples (élu, association) déduits des déports, avec leur score."""
    personnes = _personnes(conn)
    assos = _associations(conn)
    existants = _liens_existants(conn)

    candidats: dict[tuple[int, int], dict] = {}
    for d in deports(conn):
        titre = mots_cles(d["title"])
        if not titre:
            continue
        # Mots de la mention, comparés MOT À MOT (voir docstring, piège n°1).
        mots_mention = set(norm(d["mention"]).split())

        # Association la plus proche du titre de la délibération. On ne garde que
        # la meilleure : le titre ne concerne qu'une subvention à la fois.
        meilleure, score = None, 0.0
        for aid, anom, cles in assos:
            if not cles:
                continue
            s = len(cles & titre) / len(cles | titre)
            if s > score:
                meilleure, score = (aid, anom), s
        if meilleure is None or score < seuil:
            continue

        for pid, pnorm, pbrut in personnes:
            jetons = {t for t in pnorm.split() if len(t) >= 3}
            if not jetons or not jetons <= mots_mention:
                continue
            cle = (pid, meilleure[0])
            if cle in existants:
                continue
            precedent = candidats.get(cle)
            if precedent and precedent["score"] >= score:
                continue
            candidats[cle] = {
                "from_id": pid, "personne": pbrut,
                "to_id": meilleure[0], "association": meilleure[1],
                "score": score,
                "event_id": d["id"], "date": d["date"],
                "deliberation": d["title"], "mention": d["mention"],
                "source_url": d["source_url"],
            }
    return sorted(candidats.values(), key=lambda c: -c["score"])


def enregistrer(conn, candidats: list[dict]) -> int:
    """Écrit dans `relation_candidates` — file de revue, jamais dans `relations`."""
    n = 0
    for c in candidats:
        detail = (
            f"S'est retiré du vote « {c['deliberation']} » du {c['date']} "
            f"(mention : « {c['mention']} »). Un déport établit un intérêt dans la "
            f"structure, pas un rôle précis : confirmer président / trésorier / "
            f"membre, ou rejeter s'il s'agit d'un lien familial."
        )
        cur = conn.execute(
            "INSERT OR IGNORE INTO relation_candidates"
            " (from_id, to_id, relation_type, confidence, signal, signal_detail, score)"
            " VALUES (?,?,?,'probable',?,?,?)",
            (c["from_id"], c["to_id"], RELATION, SIGNAL, detail,
             int(round(c["score"] * 100))))
        n += cur.rowcount
    conn.commit()
    return n


def run(seuil: float = SEUIL_DEFAUT, dry_run: bool = False) -> dict:
    conn = get_conn()
    try:
        d = deports(conn)
        candidats = extraire(conn, seuil)
        print(f"[deports] {len(d)} délibérations avec mention de retrait du vote")
        print(f"[deports] {len(candidats)} couples (élu, association) proposés "
              f"(seuil {seuil})")
        for c in candidats:
            print(f"   {c['score']:.2f}  {c['personne'][:26]:<26} → "
                  f"{c['association'][:34]:<34} {c['date']}")
        if dry_run:
            print("\n=== DRY-RUN — rien écrit ===")
            return {"deports": len(d), "candidats": len(candidats), "ecrits": 0}
        n = enregistrer(conn, candidats)
        print(f"\n{n} candidats ajoutés à la file de revue "
              f"({len(candidats) - n} déjà présents)")
        print("À arbitrer dans /atelier/queue (ou GET /api/candidates"
              f"?signal={SIGNAL})")
        return {"deports": len(d), "candidats": len(candidats), "ecrits": n}
    finally:
        conn.close()


def stats():
    conn = get_conn()
    try:
        for r in conn.execute(
            "SELECT review_status, COUNT(*) n FROM relation_candidates"
            " WHERE signal=? GROUP BY 1", (SIGNAL,)
        ):
            print(f"  {r['review_status']:<10} {r['n']}")
        print("\n  en attente, par score décroissant :")
        for r in conn.execute("""
            SELECT rc.score, f.name AS personne, t.name AS association
            FROM relation_candidates rc
            JOIN entities f ON f.id = rc.from_id
            JOIN entities t ON t.id = rc.to_id
            WHERE rc.signal=? AND rc.review_status='pending'
            ORDER BY rc.score DESC LIMIT 30
        """, (SIGNAL,)):
            print(f"    {r['score']:>3}  {r['personne'][:26]:<26} → {r['association'][:34]}")
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seuil", type=float, default=SEUIL_DEFAUT,
                    help=f"similarité minimale de nom (défaut {SEUIL_DEFAUT})")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()
    if args.stats:
        stats()
        return
    run(seuil=args.seuil, dry_run=args.dry_run)


if __name__ == "__main__":
    main()


# Noms de communes du périmètre : trop fréquents dans les intitulés
# d'associations pour discriminer quoi que ce soit.
GENERIQUES |= {mot.upper()
               for c in COMMUNES.values()
               for mot in c["nom"].replace("-", " ").split()
               if len(mot) > 2}
