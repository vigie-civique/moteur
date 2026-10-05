#!/usr/bin/env python3
"""Recalcule la certitude d'attribution des marchés déjà collectés.

Le collecteur BOAMP concluait sur un mot commun : « terres » attrapait les
Terres australes, « cévennes » le GHT Cévennes Gard Camargue. Tout ce qui
matchait un jeton du nom de l'EPCI se retrouvait attribué à l'intercommunalité.
Corrigé à la collecte le 20/08/2026 — mais `INSERT OR IGNORE` ne revient pas sur
les lignes déjà en base, et elles prennent `verified` par défaut à l'ajout de la
colonne. Ce script les relit et tranche à nouveau, sur le nom complet.

Il ne supprime rien : un marché non attribuable passe en `probable`, donc hors
publication, et attend un arbitrage dans l'atelier.

    python3 scripts/requalifier_marches.py            # simulation
    python3 scripts/requalifier_marches.py --appliquer

Idempotent : le relancer ne change plus rien.

LE SIREN D'ABORD (05/10/2026). Jusqu'à cette date, `insert_marche` rattachait à
la fiche de l'intercommunalité tout marché dont le SIREN n'était pas celui de la
commune. Relevé sur deux instances : 27 marchés sur 58 d'un côté, 3 sur 45 de
l'autre, publiés comme ceux de la communauté de communes alors que leur SIREN
désignait une commune voisine, le Département ou un syndicat. La collecte ne le
fait plus (`marches_publics.acheteur_par_siren`), mais elle ne revient pas sur
les lignes en place. Ce script les reprend :

  - un marché rattaché à une fiche que son SIREN ne désigne pas en est DÉTACHÉ
    (il prend la fiche de son SIREN, s'il en a une), avec son flux financier ;
  - s'il porte en plus le NOM de la commune ou de l'intercommunalité, le nom et
    le SIREN se contredisent : il passe en `probable` et attend un arbitrage ;
  - sinon sa certitude ne change pas — son acheteur est établi, ce n'est
    simplement pas celui qu'on lui prêtait.

Le SIREN ne promeut jamais : sur certaines sources il a été posé par le
collecteur, pas lu. Et le nom ne tranche plus pour un marché dont le SIREN
désigne quelqu'un d'autre.

⚠ LIMITE, décisive sur les bases collectées avant le 20/08/2026.
`acheteur_nom` ne contenait pas le nom déclaré par la source : le collecteur y
écrivait le nom de l'entité qu'il avait cru reconnaître. La trace de ce qui
avait été lu était donc écrasée, et aucun réexamen n'est possible depuis la
base — toutes les lignes affirment le même acheteur, les justes comme les
fausses. Ce script le détecte et le dit. La seule sortie est alors de purger
les marchés de la source concernée et de relancer la collecte, qui les
reprendra avec l'attribution stricte et conservera l'énoncé de la source :

    python3 scripts/requalifier_marches.py --purger-source BOAMP --appliquer
    python3 -m collectors.run_all --step marches
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collectors.config import (COMMUNE_NAME, COMMUNE_SIREN, COMMUNES_ADRESSE,  # noqa: E402
                               EPCI_NOM, EPCI_SIREN)
from collectors.db import get_conn  # noqa: E402
from collectors.marches_publics import _norme_acheteur  # noqa: E402
from collectors.marches_publics import acheteur_par_siren  # noqa: E402
from collectors.marches_publics import attribution_acheteur  # noqa: E402
from collectors.marches_publics import siren_de  # noqa: E402

# Les autres noms du périmètre, pour qu'un nom tronqué par la source ne soit
# accepté que s'il ne convient qu'à une seule collectivité.
_HOMONYMES = tuple(c["nom"] for c in COMMUNES_ADRESSE.values())


def attribution(acheteur_nom: str) -> str:
    """'commune', 'epci', ou '' — la règle vit dans le collecteur, pas ici.

    Elle y était recopiée : une requalification pouvait donc trancher autrement
    que la collecte qui l'avait précédée, et le test de l'une ne disait rien de
    l'autre.
    """
    return attribution_acheteur(acheteur_nom, homonymes=_HOMONYMES)


def rattachements_a_reprendre(conn) -> list[dict]:
    """Les marchés rattachés à une fiche que leur SIREN ne désigne pas.

    Ne regarde que les SIREN qui ne sont NI celui de la commune NI celui de
    l'intercommunalité : pour ces deux-là, la fiche se retrouve par le nom de
    l'instance et la collecte n'a jamais eu tort. Ne lit que ; rend, pour
    chaque marché, la fiche voulue (None : aucune) et la certitude voulue.
    """
    notres = {siren_de(COMMUNE_SIREN), siren_de(EPCI_SIREN)} - {""}
    plan = []
    for m in conn.execute(
            "SELECT m.id, m.acheteur_id, m.acheteur_siren, m.acheteur_nom, m.confidence, "
            "       m.source, m.objet, m.event_id, e.name AS fiche "
            "FROM marches_publics m LEFT JOIN entities e ON e.id = m.acheteur_id "
            "WHERE m.acheteur_id IS NOT NULL").fetchall():
        siren = siren_de(m["acheteur_siren"])
        if not siren or siren in notres:
            continue
        voulue = acheteur_par_siren(conn, siren)
        contredit = bool(attribution(m["acheteur_nom"] or ""))
        certitude = "probable" if contredit else m["confidence"]
        if voulue == m["acheteur_id"] and certitude == m["confidence"]:
            continue
        plan.append({"id": m["id"], "siren": siren, "nom": m["acheteur_nom"] or "",
                     "fiche": m["fiche"] or "", "ancienne": m["acheteur_id"],
                     "voulue": voulue, "certitude": certitude, "contredit": contredit,
                     "source": m["source"], "objet": m["objet"] or "",
                     "event_id": m["event_id"]})
    return plan


def reprendre_rattachements(conn, plan: list[dict]) -> None:
    """Écrit le plan. La transaction est celle de l'appelant.

    Le flux financier et le lien « acheteur » de l'acte suivent le marché : les
    laisser sur l'ancienne fiche continuerait de lui prêter cet argent.
    """
    for r in plan:
        conn.execute("UPDATE marches_publics SET acheteur_id=?, confidence=? WHERE id=?",
                     (r["voulue"], r["certitude"], r["id"]))
        if r["event_id"] is None or r["voulue"] == r["ancienne"]:
            continue
        conn.execute("UPDATE financial_flows SET from_id=? "
                     "WHERE type='marché' AND event_id=? AND from_id=?",
                     (r["voulue"], r["event_id"], r["ancienne"]))
        conn.execute("DELETE FROM event_entities "
                     "WHERE event_id=? AND entity_id=? AND role='acheteur'",
                     (r["event_id"], r["ancienne"]))
        if r["voulue"] is not None:
            conn.execute("INSERT OR IGNORE INTO event_entities (event_id, entity_id, role) "
                         "VALUES (?, ?, 'acheteur')", (r["event_id"], r["voulue"]))


def purger(conn, source: str, appliquer: bool) -> int:
    """Supprime les marchés d'une source, avec leurs actes et flux.

    À n'utiliser que lorsque le nom d'acheteur de la source a été écrasé et
    qu'aucun réexamen n'est possible en base. La recollecte les reprendra.
    """
    n = conn.execute("SELECT COUNT(*) FROM marches_publics WHERE source=?",
                     (source,)).fetchone()[0]
    if not n:
        print(f"Aucun marché de source « {source} ».")
        return 0
    if not appliquer:
        print(f"{n} marché(s) de source « {source} » seraient supprimés, "
              f"avec leurs actes et flux financiers.\n"
              f"Relancer avec --appliquer, puis :\n"
              f"    python3 -m collectors.run_all --step marches")
        return 0
    with conn:
        events = [r[0] for r in conn.execute(
            "SELECT event_id FROM marches_publics WHERE source=? AND event_id IS NOT NULL",
            (source,))]
        conn.execute("DELETE FROM marches_publics WHERE source=?", (source,))
        for ev in events:
            conn.execute("DELETE FROM financial_flows WHERE event_id=?", (ev,))
            conn.execute("DELETE FROM event_entities WHERE event_id=?", (ev,))
            conn.execute("DELETE FROM events WHERE id=?", (ev,))
    print(f"✓ {n} marché(s) « {source} » supprimés, avec {len(events)} acte(s) et "
          f"leurs flux.\n  Relancer :  python3 -m collectors.run_all --step marches")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--appliquer", action="store_true",
                    help="écrit en base (sans l'option : simulation)")
    ap.add_argument("--purger-source", metavar="SOURCE",
                    help="supprime les marchés de cette source (ex. BOAMP), avec "
                         "leurs actes et flux, pour qu'une recollecte les reprenne")
    args = ap.parse_args()

    conn = get_conn()
    colonnes = {r[1] for r in conn.execute("PRAGMA table_info(marches_publics)")}
    if "confidence" not in colonnes:
        print("✖ colonne `confidence` absente — lancer d'abord "
              "`python3 -m collectors.run_all --step init`", file=sys.stderr)
        return 1

    if args.purger_source:
        return purger(conn, args.purger_source, args.appliquer)

    lignes = conn.execute(
        "SELECT id, acheteur_nom, confidence, source, objet FROM marches_publics"
    ).fetchall()

    # La colonne porte-t-elle encore l'énoncé de la source, ou le libellé
    # résolu ? Le signe : TOUS les acheteurs d'une source se réduisent aux deux
    # libellés que le collecteur savait produire. Une source qui rendrait
    # vraiment ses noms en aurait autant que d'acheteurs distincts.
    par_source: dict[str, set[str]] = {}
    effectif: dict[str, int] = {}
    for _, nom, _, source, _ in lignes:
        s = source or "?"
        par_source.setdefault(s, set()).add((nom or "").strip())
        effectif[s] = effectif.get(s, 0) + 1
    resolus = {_norme_acheteur(COMMUNE_NAME), _norme_acheteur(EPCI_NOM)}
    ecrasees = [s for s, noms in par_source.items()
                if effectif[s] > 5 and {_norme_acheteur(n) for n in noms} <= resolus]
    if ecrasees:
        print("⚠ Le nom d'acheteur déclaré par la source a été écrasé pour :")
        for s in ecrasees:
            noms = " / ".join(sorted(n[:34] for n in par_source[s]))
            print(f"    {s} — {effectif[s]} marché(s), sous {len(par_source[s])} "
                  f"libellé(s) seulement : {noms}")
        print("\n  Aucune requalification n'est possible depuis la base : toutes les\n"
              "  lignes affirment le même acheteur, les justes comme les fausses.\n"
              "  Purger et recollecter :\n"
              f"      python3 scripts/requalifier_marches.py --purger-source {ecrasees[0]} --appliquer\n"
              "      python3 -m collectors.run_all --step marches\n")

    # Le SIREN d'abord : un marché qu'il désigne comme celui d'un autre
    # acheteur n'est plus jugé sur son nom — celui-ci le ferait sortir de la
    # publication (« Ville de X » n'est pas la commune) ou, pire, l'y
    # ramènerait quand le nom de la source a été écrasé par celui de l'EPCI.
    plan = rattachements_a_reprendre(conn)
    par_le_siren = {r["id"] for r in plan}
    autres_acheteurs = {r[0] for r in conn.execute(
        "SELECT id, acheteur_siren FROM marches_publics")
        if siren_de(r[1]) and siren_de(r[1]) not in
        {siren_de(COMMUNE_SIREN), siren_de(EPCI_SIREN)}}

    a_degrader, a_promouvoir = [], []
    for mid, nom, actuelle, source, objet in lignes:
        if mid in par_le_siren or mid in autres_acheteurs:
            continue
        voulue = "verified" if attribution(nom or "") else "probable"
        if voulue == actuelle:
            continue
        (a_degrader if voulue == "probable" else a_promouvoir).append(
            (mid, nom or "", source, objet or ""))

    print(f"{len(lignes)} marché(s) en base")
    if plan:
        contredits = [r for r in plan if r["contredit"]]
        print(f"  → {len(plan)} rattaché(s) à une fiche que leur SIREN ne désigne pas, "
              f"dont {len(contredits)} dont le nom contredit le SIREN (→ « probable »)")
        groupes: dict[tuple, int] = {}
        for r in plan:
            cle = (r["siren"], r["nom"][:40], r["fiche"][:40],
                   "sans fiche" if r["voulue"] is None else f"fiche {r['voulue']}",
                   r["certitude"])
            groupes[cle] = groupes.get(cle, 0) + 1
        for (siren, nom, fiche, vers, certitude), n in sorted(groupes.items(),
                                                             key=lambda g: -g[1]):
            print(f"      {n:>3} × SIREN {siren} « {nom} » — détaché de « {fiche} », "
                  f"{vers}, {certitude}")
    print(f"  → {len(a_degrader)} à passer en « probable » (acheteur non établi)")
    print(f"  → {len(a_promouvoir)} à repasser en « verified »")

    if a_degrader:
        print("\nExemples de ce qui sortira de la publication :")
        for _, nom, source, objet in a_degrader[:6]:
            print(f"  [{source}] acheteur déclaré : {nom[:44]}")
            print(f"           {objet[:68]}")

    if not args.appliquer:
        print("\nSimulation. Relancer avec --appliquer pour écrire.")
        return 0

    with conn:
        reprendre_rattachements(conn, plan)
        for mid, *_ in a_degrader:
            conn.execute("UPDATE marches_publics SET confidence='probable' WHERE id=?", (mid,))
        for mid, *_ in a_promouvoir:
            conn.execute("UPDATE marches_publics SET confidence='verified' WHERE id=?", (mid,))
        # Le flux financier porte le même montant attribué au même acheteur :
        # le laisser publié pendant que le marché ne l'est plus prêterait de
        # l'argent à une collectivité sur la foi de rien.
        conn.execute("""
            UPDATE financial_flows SET confidence='probable'
             WHERE type='marché' AND event_id IN (
                   SELECT event_id FROM marches_publics WHERE confidence='probable')
        """)
    print(f"\n✓ {len(plan) + len(a_degrader) + len(a_promouvoir)} ligne(s) requalifiée(s). "
          "Régénérer le snapshot pour que le site en tienne compte.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
