#!/usr/bin/env python3
"""Retire les fiches que la source n'a jamais nommées, et nettoie les noms qu'elle a mal écrits.

    python3 scripts/nettoyer_entites.py              # simulation
    python3 scripts/nettoyer_entites.py --appliquer

Relevé le 22/08/2026 sur la page « Acteurs publics » de l'atelier de Lasalle :

* **dix lieux nommés « 2 » à « 10 » et « ? »**, tous `tourism=information`.
  OSM range là ses panneaux d'information et met le NUMÉRO du panneau dans
  `name`. Ils occupaient la totalité de l'onglet « Lieu », et sa tête de liste,
  les chiffres se triant avant les lettres ;
* **25 titres d'associations entre guillemets, 280 avec un point final**, tels
  que déposés au RNA — et une fiche dont le titre est deux fois le même titre
  avec deux orthographes ;
* des adresses où l'élision est décollée de son mot (« L' Estréchure »).

Les collecteurs refusent désormais de les créer (`osm.nom_utilisable`,
`nom_normalise.nettoyer_libelle`, appelés par `osm.py` et `rna.py`) ; ce script
traite ce qui est DÉJÀ en base. Il applique exactement les mêmes fonctions, pour
que la base et les collecteurs ne puissent pas diverger.

Il ne supprime que des fiches auxquelles rien n'est accroché : ce que le schéma
déclare supprimable avec l'entité (`ON DELETE CASCADE`) part avec elle, tout le
reste — un rattachement à une séance, une note d'atelier, un site web — fait
renoncer et sort dans la liste des cas à trancher à la main.

Il ne touche jamais à la CASSE d'un nom : cf. `nettoyer_libelle`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collectors.db import get_conn  # noqa: E402
from collectors.nom_normalise import nettoyer_libelle, normaliser, rectifier  # noqa: E402
from collectors.osm import nom_utilisable  # noqa: E402

# Types que le collecteur OSM crée : eux seuls peuvent hériter d'un nom qui
# n'est qu'un numéro de panneau. Une personne ou une entreprise sans lettre
# dans son nom relève d'un autre défaut, qu'on ne réparerait pas en la
# supprimant.
TYPES_OSM = ("place", "service")


def _tables_liees(conn) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """(accroches, cascades) — colonnes qui pointent vers `entities`.

    Lues dans le schéma, pas écrites ici : une table ajoutée demain compte
    d'elle-même, et une liste tenue à la main aurait pris du retard le jour où
    quelqu'un l'aurait oubliée.
    """
    accroches, cascades = [], []
    for (table,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        for fk in conn.execute(f'PRAGMA foreign_key_list("{table}")'):
            if fk["table"] != "entities":
                continue
            cible = cascades if (fk["on_delete"] or "").upper() == "CASCADE" else accroches
            cible.append((table, fk["from"]))
    return accroches, cascades


def _accroches(conn, eid: int, accroches: list[tuple[str, str]]) -> int:
    return sum(
        conn.execute(f'SELECT COUNT(*) FROM "{t}" WHERE "{c}"=?', (eid,)).fetchone()[0]
        for t, c in accroches
    )


def fiches_sans_nom(conn) -> tuple[list, list]:
    """(à retirer, retenues) — les retenues portent quelque chose."""
    accroches, _ = _tables_liees(conn)
    a_retirer, retenues = [], []
    for r in conn.execute(
            "SELECT id, type, name, commune FROM entities WHERE type IN (?,?)",
            TYPES_OSM):
        if nom_utilisable(r["name"]):
            continue
        n = _accroches(conn, r["id"], accroches)
        (retenues if n else a_retirer).append((r["id"], r["type"], r["name"],
                                               r["commune"], n))
    return a_retirer, retenues


def libelles_a_nettoyer(conn) -> tuple[list, list]:
    """(à réécrire, collisions) — une collision est un doublon révélé, pas une erreur.

    Deux fiches peuvent viser le MÊME nom propre sans qu'aucune ne le porte
    encore : « ""SAVEURS…"" » et « "SAVEURS…" » sont deux fiches, deux graphies
    d'un seul commerce, et se nettoient en un seul nom. Comparer chaque
    candidate à la base seule laissait passer les deux, et la seconde écriture
    heurtait `UNIQUE(type, name)` en pleine transaction — tout le lot annulé.
    Les cibles déjà réservées par ce lot comptent donc autant que les noms
    déjà en base.
    """
    a_ecrire, collisions = [], []
    pris = {(r["type"], r["name"]): r["id"]
            for r in conn.execute("SELECT id, type, name FROM entities")}
    reserves: dict[tuple[str, str], int] = {}
    for (type_, name), eid in pris.items():
        propre = nettoyer_libelle(name)
        if propre == name or not propre:
            continue
        cle = (type_, propre)
        autre = pris.get(cle) or reserves.get(cle)
        if autre is not None and autre != eid:
            collisions.append((eid, type_, name, propre, autre))
        else:
            reserves[cle] = eid
            a_ecrire.append((eid, type_, name, propre))
    return a_ecrire, collisions


def adresses_a_nettoyer(conn) -> list:
    lignes = []
    for r in conn.execute(
            "SELECT id, type, address FROM entities WHERE address IS NOT NULL AND address<>''"):
        propre = nettoyer_libelle(r["address"])
        if propre and propre != r["address"]:
            lignes.append((r["id"], r["type"], r["address"], propre))
    return lignes


# Types dont NOUS composons l'adresse à partir de morceaux (rna.py assemble
# « voie + code postal + commune »). Pour SIRENE, l'adresse arrive d'un bloc,
# tout en capitales et sans accents : y recoller « Causse-Bégon » au milieu de
# « LD CAMP FRECH 30750 CAUSSE-BEGON » remplacerait une incohérence par une
# autre. 3 269 fiches sont dans ce cas, et on n'y touche pas.
TYPES_ADRESSE_COMPOSEE = ("association",)


def communes_a_recaler(conn) -> list:
    """Adresses dont la fin désigne bien la commune, mais pas comme le référentiel.

    « 30570 Val d'aigoual » sur une fiche dont `commune` vaut « Val-d'Aigoual »,
    « 30750 Trêves » pour « Trèves » : la source écrit ce qu'elle veut, et les
    deux champs de la même fiche se contredisaient à l'écran.
    """
    lignes = []
    for r in conn.execute(
            "SELECT id, address, commune FROM entities"
            f" WHERE type IN ({','.join('?' * len(TYPES_ADRESSE_COMPOSEE))})"
            " AND address IS NOT NULL AND address<>'' AND commune IS NOT NULL",
            TYPES_ADRESSE_COMPOSEE):
        adr, commune = r["address"], r["commune"]
        if adr.endswith(commune) or not normaliser(adr).endswith(normaliser(commune)):
            continue
        # La plus courte fin d'adresse qui se normalise comme la commune : les
        # deux graphies n'ont pas la même longueur (« Val d'aigoual » /
        # « Val-d'Aigoual »), on ne peut pas couper sur le nombre de lettres.
        for k in range(1, len(adr) + 1):
            if normaliser(adr[-k:]) == normaliser(commune):
                lignes.append((r["id"], adr, adr[:-k] + commune))
                break
    return lignes


def rectifications_a_appliquer(conn) -> list:
    """Fiches en base que les rectifications déclarées de l'instance modifient.

    Les collecteurs les appliquent à l'écriture (`db.upsert_entity`) : ce
    passage-ci ne sert qu'à rattraper ce qui est entré avant la déclaration.
    """
    lignes = []
    for r in conn.execute("SELECT id, name, address FROM entities"):
        nom, adr = rectifier(r["name"]), rectifier(r["address"])
        if nom != r["name"] or adr != (r["address"]):
            lignes.append((r["id"], r["name"], nom, r["address"], adr))
    return lignes


def normes_a_recalculer(conn) -> list:
    """`name_norm` a changé de définition le 22/08/2026 (guillemets)."""
    return [(r["id"], normaliser(r["name"]))
            for r in conn.execute("SELECT id, name, name_norm FROM entities")
            if normaliser(r["name"]) != (r["name_norm"] or "")]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--appliquer", action="store_true", help="écrit en base")
    args = ap.parse_args()

    conn = get_conn()
    _, cascades = _tables_liees(conn)

    a_retirer, retenues = fiches_sans_nom(conn)
    a_ecrire, collisions = libelles_a_nettoyer(conn)
    adresses = adresses_a_nettoyer(conn)
    communes = communes_a_recaler(conn)
    rectifiees = rectifications_a_appliquer(conn)
    normes = normes_a_recalculer(conn)

    print(f"{len(a_retirer)} fiche(s) sans un seul caractère alphabétique dans le nom")
    for eid, type_, name, commune, _ in a_retirer[:12]:
        print(f"   #{eid:<6} [{type_:<7}] {name!r:<10} {commune or '?'}")
    if len(a_retirer) > 12:
        print(f"   … {len(a_retirer) - 12} autres")

    if retenues:
        print(f"\n{len(retenues)} fiche(s) sans nom mais PORTANT quelque chose "
              f"— conservées, à trancher dans l'atelier :")
        for eid, type_, name, commune, n in retenues[:6]:
            print(f"   #{eid:<6} [{type_:<7}] {name!r:<10} {n} rattachement(s)")

    print(f"\n{len(a_ecrire)} nom(s) à nettoyer")
    for eid, type_, name, propre in a_ecrire[:12]:
        print(f"   #{eid:<6} [{type_:<7}] {name[:46]!r}\n              → {propre[:46]!r}")
    if len(a_ecrire) > 12:
        print(f"   … {len(a_ecrire) - 12} autres")

    if collisions:
        print(f"\n{len(collisions)} nom(s) qui, nettoyés, en rejoignent un autre "
              f"— DOUBLONS à fusionner à la main, rien n'est écrit :")
        for eid, type_, name, propre, autre in collisions[:8]:
            print(f"   #{eid} {name[:40]!r} → {propre[:40]!r} déjà porté par #{autre}")

    print(f"\n{len(adresses)} adresse(s) à nettoyer")
    for eid, type_, addr, propre in adresses[:6]:
        print(f"   #{eid:<6} {addr[:52]!r}\n              → {propre[:52]!r}")
    if len(adresses) > 6:
        print(f"   … {len(adresses) - 6} autres")

    print(f"\n{len(communes)} adresse(s) où la commune n'est pas écrite comme le référentiel")
    for eid, adr, propre in communes[:6]:
        print(f"   #{eid:<6} {adr[:52]!r}\n              → {propre[:52]!r}")
    if len(communes) > 6:
        print(f"   … {len(communes) - 6} autres")

    print(f"\n{len(rectifiees)} fiche(s) touchée(s) par une rectification déclarée "
          f"de l'instance")
    for eid, nom, nom2, adr, adr2 in rectifiees[:6]:
        if nom != nom2:
            print(f"   #{eid:<6} nom     {nom[:44]!r} → {nom2[:44]!r}")
        if adr != adr2:
            print(f"   #{eid:<6} adresse {adr[:44]!r} → {adr2[:44]!r}")

    print(f"\n{len(normes)} forme(s) normalisée(s) à recalculer")

    if not args.appliquer:
        print("\nSimulation. Relancer avec --appliquer pour écrire.")
        return 0

    with conn:
        for eid, *_ in a_retirer:
            # Ce que le schéma déclare supprimable avec l'entité part d'abord :
            # `PRAGMA foreign_keys` n'est ON que sur les connexions en écriture,
            # et une cascade qui ne se déclenche pas laisse une ligne orpheline
            # qui pointe vers une entité disparue.
            for table, colonne in cascades:
                conn.execute(f'DELETE FROM "{table}" WHERE "{colonne}"=?', (eid,))
            conn.execute("DELETE FROM entities WHERE id=?", (eid,))
        for eid, _t, _name, propre in a_ecrire:
            conn.execute("UPDATE entities SET name=? WHERE id=?", (propre, eid))
        for eid, _t, _addr, propre in adresses:
            conn.execute("UPDATE entities SET address=? WHERE id=?", (propre, eid))
        for eid, _adr, propre in communes_a_recaler(conn):
            conn.execute("UPDATE entities SET address=? WHERE id=?", (propre, eid))
        for eid, _nom, nom, _adr, adr in rectifiees:
            conn.execute("UPDATE entities SET name=?, address=? WHERE id=?", (nom, adr, eid))
        # Après les réécritures : le nom vient de changer pour certaines fiches.
        for eid, norme in normes_a_recalculer(conn):
            conn.execute("UPDATE entities SET name_norm=? WHERE id=?", (norme, eid))

    print(f"\n✓ {len(a_retirer)} fiche(s) retirée(s), {len(a_ecrire)} nom(s), "
          f"{len(adresses)} adresse(s) nettoyée(s), {len(communes)} commune(s) recalée(s) "
          f"et {len(rectifiees)} rectification(s) appliquée(s).")
    print("  Régénérer le snapshot pour que le site publié en tienne compte.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
