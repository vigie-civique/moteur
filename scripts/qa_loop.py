#!/usr/bin/env python3
"""
qa_loop.py — Loop QA / Vérification de la base Commune Lasalle.

Le « vérificateur » de la boucle : une suite de checks d'anomalies. La loop
scanne → corrige les anomalies SÛRES (intégrité : orphelins) → laisse les
DOUTEUSES en rapport (fusion/retypage = jugement humain via /atelier) →
re-scanne jusqu'à 0 anomalie auto-corrigeable.

Usage :
    venv/bin/python3 scripts/qa_loop.py            # scan (lecture seule)
    venv/bin/python3 scripts/qa_loop.py --fix      # + applique les autofixes sûrs
    venv/bin/python3 scripts/qa_loop.py --loop     # scan→fix→rescan jusqu'à stable

Principe : ne JAMAIS auto-fusionner ni auto-retyper (corromprait les données).
Seuls les orphelins d'intégrité référentielle sont auto-supprimés.
"""
import argparse
import json
import shutil
import sqlite3
import sys
import unicodedata
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from collectors.config import STEP_META            # noqa: E402  (fraîcheur des sources)

from collectors.config import DB_PATH   # nommée dans la config
REPORT_PATH = ROOT / "audits" / "qa_report.json"
ELECTION_2026 = "2026-03-15"          # début de la mandature actuelle
MANDATE_TYPES = ("élu_cm", "élu_cc", "adjoint", "maire", "délégué_cm", "délégué_cc")

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def conn():
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = OFF")   # on gère l'intégrité nous-mêmes
    return c


def norm(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return " ".join(s.upper().split())


def finding(check, severity, detail, ref=None, autofix=None):
    """severity ∈ blocking|warning|info ; autofix = SQL sûr ou None."""
    return {"check": check, "severity": severity, "detail": detail,
            "ref": ref, "autofix": autofix}


# ─────────────────────────────────────────────────────────────────────────────
# Checks — chacun retourne une liste de findings
# ─────────────────────────────────────────────────────────────────────────────

def check_orphan_relations(c):
    rows = c.execute("""
        SELECT r.id, r.from_id, r.to_id, r.relation_type FROM relations r
        WHERE NOT EXISTS(SELECT 1 FROM entities e WHERE e.id=r.from_id)
           OR NOT EXISTS(SELECT 1 FROM entities e WHERE e.id=r.to_id)
    """).fetchall()
    return [finding("orphan_relation", "blocking",
                    f"relation {r['id']} ({r['relation_type']}) {r['from_id']}→{r['to_id']} pointe sur une entité absente",
                    ref={"table": "relations", "id": r["id"]},
                    autofix=("DELETE FROM relations WHERE id=?", (r["id"],)))
            for r in rows]


def check_self_loop_relations(c):
    """Relation d'une entité vers elle-même (from_id=to_id) — toujours une erreur
    d'import (ex: dirigeant SIRENE personne→personne au lieu de personne→entreprise).
    La métadonnée ne porte aucune cible exploitable → suppression sûre.
    (La ré-association dirigeant→entreprise est un enrichissement séparé, pas du QA.)"""
    rows = c.execute("""
        SELECT r.id, r.relation_type, e.name FROM relations r
        JOIN entities e ON e.id = r.from_id
        WHERE r.from_id = r.to_id
    """).fetchall()
    return [finding("self_loop_relation", "blocking",
                    f"relation {r['id']} ({r['relation_type']}) de « {r['name']} » vers elle-même",
                    ref={"table": "relations", "id": r["id"]},
                    autofix=("DELETE FROM relations WHERE id=?", (r["id"],)))
            for r in rows]


def check_orphan_embeddings(c):
    rows = c.execute("""
        SELECT id, entity_id FROM embeddings
        WHERE entity_id IS NOT NULL
          AND NOT EXISTS(SELECT 1 FROM entities e WHERE e.id=embeddings.entity_id)
    """).fetchall()
    return [finding("orphan_embedding", "blocking",
                    f"embedding {r['id']} référence l'entité absente {r['entity_id']}",
                    ref={"table": "embeddings", "id": r["id"]},
                    autofix=("DELETE FROM embeddings WHERE id=?", (r["id"],)))
            for r in rows]


def check_orphan_notes(c):
    rows = c.execute("""
        SELECT id, entity_id FROM entity_notes
        WHERE NOT EXISTS(SELECT 1 FROM entities e WHERE e.id=entity_notes.entity_id)
    """).fetchall()
    return [finding("orphan_note", "blocking",
                    f"note {r['id']} référence l'entité absente {r['entity_id']}",
                    ref={"table": "entity_notes", "id": r["id"]},
                    autofix=("DELETE FROM entity_notes WHERE id=?", (r["id"],)))
            for r in rows]


def check_duplicate_official_ids(c):
    out = []
    for col, table, label in (("rna_id", "associations", "RNA"), ("siren", "businesses", "SIREN")):
        rows = c.execute(f"""
            SELECT {col} AS k, GROUP_CONCAT(entity_id) AS ids, COUNT(*) c
            FROM {table} WHERE {col} IS NOT NULL AND {col}!='' GROUP BY {col} HAVING c>1
        """).fetchall()
        for r in rows:
            out.append(finding("duplicate_official_id", "blocking",
                               f"{label} {r['k']} partagé par {r['c']} entités (ids {r['ids']}) — fusion à trancher",
                               ref={"table": table, "ids": r["ids"]}))
    return out


def check_duplicate_names(c):
    """Doublons probables : même nom normalisé, type identique, ids distincts."""
    rows = c.execute("SELECT id, type, name FROM entities WHERE name IS NOT NULL").fetchall()
    groups = {}
    for r in rows:
        groups.setdefault((r["type"], norm(r["name"])), []).append(r["id"])
    out = []
    for (typ, n), ids in groups.items():
        if len(ids) > 1 and n:
            out.append(finding("duplicate_name", "warning",
                               f"{len(ids)} entités '{typ}' de même nom normalisé « {n} » (ids {ids}) — doublon probable",
                               ref={"entity_ids": ids}))
    return out


def check_unclosed_old_mandates(c):
    """Mandat commencé avant la mandature actuelle, jamais clôturé (until NULL)."""
    q = f"""
        SELECT r.id, r.relation_type, r.since, f.name
        FROM relations r JOIN entities f ON f.id=r.from_id
        WHERE r.relation_type IN ({','.join('?' for _ in MANDATE_TYPES)})
          AND r.until IS NULL AND r.since IS NOT NULL AND r.since < ?
    """
    rows = c.execute(q, (*MANDATE_TYPES, ELECTION_2026)).fetchall()
    return [finding("unclosed_old_mandate", "warning",
                    f"mandat {r['id']} {r['relation_type']} de {r['name']} (depuis {r['since']}) sans date de fin — clore ?",
                    ref={"table": "relations", "id": r["id"]})
            for r in rows]


def check_orphan_event_entities(c):
    """Liens événement↔acteur pointant dans le vide. 378 rattachements morts
    traînaient en base le 25/07/2026 — autant de croisements perdus pour la
    fiche entité et pour le graphe."""
    rows = c.execute("""
        SELECT ee.rowid AS rid, ee.event_id, ee.entity_id FROM event_entities ee
         WHERE ee.entity_id NOT IN (SELECT id FROM entities)
            OR ee.event_id  NOT IN (SELECT id FROM events)
    """).fetchall()
    return [finding("orphan_event_entity", "warning",
                    f"lien event {r['event_id']} ↔ entité {r['entity_id']} pointe dans le vide",
                    ref={"table": "event_entities", "id": r["rid"]},
                    autofix=("DELETE FROM event_entities WHERE rowid=?", (r["rid"],)))
            for r in rows]


# Toutes les tables qui référencent `entities`, et ce qu'on fait de leurs
# orphelins. La liste précédente n'en couvrait que 8 sur 21 : les 139 violations
# de clé étrangère découvertes le 12/08/2026 (129 relation_candidates + 1
# financial_flow) étaient invisibles pour le QA. Elles viennent des suppressions
# faites `PRAGMA foreign_keys = OFF` — la purge hors périmètre, les fusions de
# doublons — où le CASCADE déclaré au schéma ne s'applique pas.
#
# `supprimable` : la ligne n'a aucun sens sans son entité (sous-tables 1:1,
# tables de liaison) → autofix. Les autres sont des JOURNAUX ou du travail
# humain : `audit_log`, `scrape_runs`, `atelier_comments`, `contacts`,
# `elus_rne` gardent la trace d'un fait daté, et l'effacer parce que l'entité a
# disparu détruirait de l'historique. Signalés, jamais supprimés.
TABLES_LIEES = [
    # (table, colonnes, supprimable)
    ("persons",                 ["entity_id"],                 True),
    ("businesses",              ["entity_id"],                 True),
    ("associations",            ["entity_id"],                 True),
    ("places",                  ["entity_id"],                 True),
    ("services",                ["entity_id"],                 True),
    ("entity_websites",         ["entity_id"],                 True),
    ("entity_enrichment",       ["entity_id"],                 True),
    ("entity_notes",            ["entity_id"],                 True),
    ("event_entities",          ["entity_id"],                 True),
    ("relation_candidates",     ["from_id", "to_id"],          True),
    ("budget_indicators",       ["entity_id"],                 True),
    ("budget_annexe",           ["entity_id"],                 True),
    # Données de fond : un flux ou un marché orphelin est une PERTE, pas du
    # bruit — il peut porter un montant public. À trancher à la main.
    ("financial_flows",         ["from_id", "to_id"],          False),
    ("marches_publics",         ["titulaire_id", "acheteur_id"], False),
    ("urbanisme_autorisations", ["demandeur_entity_id"],       False),
    # Journaux et travail humain.
    ("audit_log",               ["entity_id"],                 False),
    ("scrape_runs",             ["entity_id"],                 False),
    ("atelier_comments",        ["entity_id"],                 False),
    ("contacts",                ["entity_id"],                 False),
    ("elus_rne",                ["entity_id"],                 False),
]


def check_orphan_subtables(c):
    """Lignes référençant une entité disparue, sur les 21 tables concernées."""
    out = []
    for table, colonnes, supprimable in TABLES_LIEES:
        for col in colonnes:
            rows = c.execute(
                f"SELECT rowid AS rid, {col} AS ref FROM {table} "
                f"WHERE {col} IS NOT NULL "
                f"AND {col} NOT IN (SELECT id FROM entities)").fetchall()
            out += [finding(
                "orphan_subtable", "warning",
                f"{table}.{col}: entité {r['ref']} inexistante"
                + ("" if supprimable else " — à trancher à la main, la ligne "
                                          "porte une donnée de fond"),
                ref={"table": table, "id": r["rid"]},
                autofix=((f"DELETE FROM {table} WHERE rowid=?", (r["rid"],))
                         if supprimable else None))
                for r in rows]
    return out


def check_stale_body_membership(c):
    """Membre d'un corps intermédiaire (commission, CCAS…) encore actif alors que
    son mandat électif est clos. Piège vu le 25/07/2026 : la page les-elus de
    lasalle.fr n'avait pas été mise à jour après le scrutin, le collecteur a
    estampillé les commissions 2020-2026 avec since=2026-03-15, et 12 anciens
    élus (dont l'ancien maire) sont restés « actifs » dans le graphe public."""
    rows = c.execute(f"""
        SELECT r.id, r.relation_type, r.since, f.name AS who, t.name AS body
        FROM relations r
        JOIN entities f ON f.id = r.from_id
        JOIN entities t ON t.id = r.to_id
        WHERE r.relation_type IN ('membre_commission','adjoint','délégué_cm','responsable')
          AND (r.until IS NULL OR r.until > date('now'))
          AND NOT EXISTS (
                SELECT 1 FROM relations m
                 WHERE m.from_id = r.from_id
                   AND m.relation_type IN ({','.join('?' for _ in MANDATE_TYPES)})
                   AND (m.until IS NULL OR m.until > date('now')))
          AND EXISTS (
                SELECT 1 FROM relations m
                 WHERE m.from_id = r.from_id
                   AND m.relation_type IN ({','.join('?' for _ in MANDATE_TYPES)})
                   AND m.until IS NOT NULL AND m.until <= date('now'))
    """, (*MANDATE_TYPES, *MANDATE_TYPES)).fetchall()
    return [finding("stale_body_membership", "error",
                    f"{r['who']} siège encore à « {r['body']} » ({r['relation_type']}) "
                    f"alors que son mandat est clos — clore la relation {r['id']}",
                    ref={"table": "relations", "id": r["id"]})
            for r in rows]


def check_geocodable_in_commune(c):
    """Structures in-commune publiables, physiques, sans coords → à placer via /atelier/geo
    (cas par cas, jugement humain). Exclut : hors-commune, commissions/conseils abstraits.
    Les domiciles de personnes ne sont PAS forcés sur la carte (règle 3 sécurité) — ils
    restent ici en file de revue, c'est le valideur qui tranche au placement."""
    from collectors.config import CODE_POSTAL, COMMUNE_NAME
    rows = c.execute("""
        SELECT id, type, name FROM entities e
        WHERE confidence IN ('verified','confirmed')
          AND type IN ('business','association','service','place')
          AND (lat IS NULL OR lng IS NULL)
          AND (commune = ?
               OR UPPER(address) LIKE '%' || UPPER(?) || '%'
               OR address LIKE '%' || ? || '%')
          AND name NOT LIKE 'Commission %'
          AND name NOT LIKE 'Conseil %'
    """, (COMMUNE_NAME, COMMUNE_NAME, CODE_POSTAL)).fetchall()
    return [finding("geocodable_in_commune", "info",
                    f"structure {r['id']} ({r['type']}) « {r['name']} » sans géoloc — à placer via /atelier/geo",
                    ref={"table": "entities", "id": r["id"]})
            for r in rows]


def check_silent_source(c):
    """Collecteur qui n'a plus livré depuis trop longtemps, ou qui tourne à vide.

    Deux pannes distinctes, aucune des deux visible sans ce check :

    1. SILENCE — plus aucun run réussi depuis > 1,5 × TTL. Cas de figure : le
       collecteur n'est plus planifié, ou l'API ne répond plus.
       `api-dvf.cerema.fr` ne résout plus (DNS mort) et personne ne l'a vu.

    2. À VIDE — la source répond, les runs passent, mais n'apportent plus rien
       depuis plusieurs passages. C'est exactement ce qui est arrivé à DECP :
       `decp_augmente` n'était plus alimenté depuis le 05/03/2026 alors que
       l'API répondait normalement — 577 jours de données foncières figées sans
       le moindre signal. Un jeu qui répond n'est pas un jeu à jour.

    Le seuil est 1,5 × TTL : le TTL déclenche la relance de la collecte, pas
    l'alerte. On n'alerte que si la relance elle-même n'a rien produit.
    """
    findings = []
    for name, (ttl, _prio, _table, _where) in STEP_META.items():
        last = c.execute(
            "SELECT finished_at, status, items_added FROM collector_runs"
            " WHERE collector=? AND status IN ('ok','empty')"
            " ORDER BY finished_at DESC LIMIT 1", (name,)
        ).fetchone()

        if last is None or not last["finished_at"]:
            # Le filtre status IN ('ok','empty') ne voit ici que l'ABSENCE de
            # succès — un collecteur qui échoue à CHAQUE run (error/timeout)
            # tombe dans la même branche qu'un collecteur jamais lancé, alors
            # que ce sont deux pannes très différentes à traiter. Cas réel
            # trouvé le 10/08/2026 : rne échouait en DNS (URLError) à chaque
            # passage depuis le 27/07 — 10+ échecs consécutifs journalisés,
            # rapportés ici comme un simple "jamais journalisé" jusqu'à ce
            # qu'on aille lire collector_runs à la main.
            recent_errors = c.execute(
                "SELECT COUNT(*), MAX(started_at), error FROM collector_runs"
                " WHERE collector=? AND status IN ('error','timeout')"
                " ORDER BY started_at DESC LIMIT 1", (name,)
            ).fetchone()
            n_err = c.execute(
                "SELECT COUNT(*) FROM collector_runs"
                " WHERE collector=? AND status IN ('error','timeout')", (name,)
            ).fetchone()[0]
            if n_err:
                findings.append(finding(
                    "silent_source", "error",
                    f"collecteur « {name} » : {n_err} run(s) en échec, aucun succès "
                    f"journalisé — dernier échec {recent_errors[1]} ({recent_errors[2]})",
                    ref={"collector": name, "n_errors": n_err}))
            else:
                findings.append(finding(
                    "silent_source", "warning",
                    f"collecteur « {name} » n'a aucun run journalisé — "
                    f"fraîcheur non vérifiable (lancer python3 -m collectors.run_all pour la produire)",
                    ref={"collector": name}))
            continue

        age = c.execute("SELECT julianday('now') - julianday(?)",
                        (last["finished_at"],)).fetchone()[0]
        if age is not None and age > ttl * 1.5:
            sev = "error" if age > ttl * 3 else "warning"
            findings.append(finding(
                "silent_source", sev,
                f"collecteur « {name} » muet depuis {age:.0f} j (TTL {ttl} j) — "
                f"source morte ou plus planifiée",
                ref={"collector": name, "age_days": round(age, 1), "ttl": ttl}))
            continue

        # Runs consécutifs sans apport : la source répond mais ne livre plus.
        recents = c.execute(
            "SELECT items_added FROM collector_runs"
            " WHERE collector=? AND status IN ('ok','empty')"
            " ORDER BY finished_at DESC LIMIT 3", (name,)
        ).fetchall()
        if len(recents) == 3 and all((r["items_added"] or 0) == 0 for r in recents):
            # ⚠️ « Sans apport » ne veut dire « figé » que si la source a DÉJÀ
            # livré ici. Sur `crc`, ne rien trouver est le résultat JUSTE et
            # durable : une commune de moins de 3 500 habitants n'est presque
            # jamais contrôlée, et son intercommunalité pas davantage. Le
            # contrôle criait donc à chaque passage sur une réponse correcte —
            # Lasalle et Brassac, en septembre 2026. Un avertissement qui ne
            # peut pas s'éteindre apprend à ne plus lire les avertissements.
            a_deja_livre = c.execute(
                "SELECT 1 FROM collector_runs"
                " WHERE collector=? AND items_added > 0 LIMIT 1", (name,)
            ).fetchone()
            if a_deja_livre:
                findings.append(finding(
                    "stale_source", "warning",
                    f"collecteur « {name} » : 3 runs consécutifs sans aucun apport "
                    f"alors qu'il a déjà livré — vérifier que le jeu source est "
                    f"encore alimenté (cf. decp_augmente figé alors que l'API répondait)",
                    ref={"collector": name}))
            else:
                findings.append(finding(
                    "stale_source", "info",
                    f"collecteur « {name} » : aucun apport dans tout l'historique "
                    f"journalisé — normal quand la collectivité n'est pas concernée "
                    f"(crc sur une commune jamais contrôlée), à vérifier sinon",
                    ref={"collector": name}))
    return findings


def check_confidence_values(c):
    allowed = ("verified", "confirmed", "probable", "hypothesis")
    rows = c.execute(f"""
        SELECT id, name, confidence FROM entities
        WHERE confidence IS NULL OR confidence NOT IN ({','.join('?' for _ in allowed)})
    """, allowed).fetchall()
    return [finding("bad_confidence", "warning",
                    f"entité {r['id']} « {r['name']} » a une confidence invalide : {r['confidence']!r}",
                    ref={"table": "entities", "id": r["id"]})
            for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Réplicabilité — le moteur ne doit rien savoir de Lasalle
# ─────────────────────────────────────────────────────────────────────────────
# Le projet a vocation à être rejoué sur une autre commune : toute règle codée
# en dur sur Lasalle est une dette (cf. CLAUDE.md). C'est aussi la leçon
# structurante du Council Data Project, qui sépare strictement le MOTEUR
# (pipelines, schéma, frontend, versionnés une fois) de l'INSTANCE (la config
# d'une collectivité) — sans quoi aucune instance ne peut être mise à jour.
#
# Ici la config d'instance vit dans `collectors/config.py`. Ce check garde la
# frontière : il signale toute occurrence littérale du nom de la commune dans
# le code moteur. Il ne bloque rien — certaines occurrences sont légitimes
# (scripts d'import ponctuels déjà exécutés) — mais une dette non comptée
# grossit sans bruit.
# Une troisième implémentation de ce contrôle vivait ici, avec sa propre liste
# de fichiers « moteur » — dont trois n'existaient plus, sautés en silence — et
# ne cherchait que le nom de la commune COURANTE, donc rien du tout sur une
# instance portée. Le contrôle est désormais unique : `verifier_generique.py`,
# qui sert aussi d'admission au kit. Trois définitions du mot « moteur »
# finissent par diverger ; celle-ci avait déjà divergé.


def check_hardcoded_commune(_c):
    """Particularités locales trouvées dans le code moteur, par fichier.

    Inventaire de dette, pas alarme : `info`, jamais bloquant. Le contrôle
    bloquant est `scripts/verifier_generique.py`, appelé avant de fabriquer un
    kit.
    """
    import importlib.util
    from collections import Counter

    chemin = ROOT / "scripts" / "verifier_generique.py"
    spec = importlib.util.spec_from_file_location("verifier_generique", chemin)
    vg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vg)

    communes = vg.communes_locales()
    constats = [c for f in vg._fichiers(vg.MOTEUR) for c in vg.analyser(f, communes)]
    constats += [c for f in vg._fichiers_texte() for c in vg.analyser_texte(f, communes)]

    par_fichier: dict[str, list] = {}
    for c in constats:
        par_fichier.setdefault(c["fichier"], []).append(c)

    findings = []
    for fichier, liste in sorted(par_fichier.items()):
        motifs = ", ".join(f"{m}×{n}" for m, n in
                           Counter(c["motif"] for c in liste).most_common())
        lignes = sorted({c["ligne"] for c in liste})
        findings.append(finding(
            "hardcoded_commune", "info",
            f"{fichier} — {len(liste)} constat(s) ({motifs}), "
            f"lignes {', '.join(map(str, lignes[:8]))}"
            f"{'…' if len(lignes) > 8 else ''} : à lire depuis la configuration",
            ref={"file": fichier, "lines": lignes}))
    return findings


def check_commune_sans_preuve(c):
    """Entités taguées de la commune C1 sans aucune preuve d'ancrage.

    Séquelle du `DEFAULT 'Lasalle'` retiré du schéma le 12/08/2026
    par une migration ponctuelle : les entités créées AVANT cette
    date portent peut-être un tag que personne n'a jamais posé sciemment.

    Le tri ne s'automatise pas. Sur les 971 entités taguées sans adresse ni
    coordonnées, **807 ont bien une preuve** — le défaut avait vu juste par
    accident. Les autres demandent un coup d'œil : une SCI sans adresse peut
    être parfaitement lasalloise. On les remonte donc en revue, jamais en
    autofix, conformément à la règle du projet.

    Preuve d'ancrage retenue, du plus fort au plus faible :
      - adresse mentionnant la commune ou son code postal ;
      - mandat municipal au RNE sur l'INSEE de la commune ;
      - coordonnées dans la bbox de publication ;
      - une relation vers une entité qui a l'une des trois.
    """
    import json

    from collectors.config import CODE_POSTAL, COMMUNE_INSEE, COMMUNE_NAME
    bbox = json.loads(
        (ROOT / "config" / "publication_rules.json").read_text(encoding="utf-8")
    )["locations"]["bbox"]

    c.executescript(f"""
        DROP TABLE IF EXISTS temp.ancre;
        CREATE TEMP TABLE ancre AS
        SELECT DISTINCT id FROM entities
         WHERE UPPER(address) LIKE '%' || UPPER('{COMMUNE_NAME}') || '%'
            OR address LIKE '%{CODE_POSTAL}%'
        UNION SELECT entity_id FROM elus_rne
         WHERE insee = '{COMMUNE_INSEE}' AND entity_id IS NOT NULL
        UNION SELECT id FROM entities
         WHERE lat BETWEEN {bbox['lat_min']} AND {bbox['lat_max']}
           AND lng BETWEEN {bbox['lng_min']} AND {bbox['lng_max']};
    """)
    rows = c.execute("""
        SELECT e.id, e.type, e.name, e.perimetre FROM entities e
        WHERE e.commune = ? AND e.address IS NULL AND e.lat IS NULL
          AND e.id NOT IN (SELECT id FROM ancre)
          AND NOT EXISTS (
              SELECT 1 FROM relations r
               WHERE (r.from_id = e.id AND r.to_id   IN (SELECT id FROM ancre))
                  OR (r.to_id   = e.id AND r.from_id IN (SELECT id FROM ancre)))
        ORDER BY e.type, e.name
    """, (COMMUNE_NAME,)).fetchall()
    return [finding("commune_sans_preuve", "info",
                    f"{r['type']} {r['id']} « {r['name']} » tagué {COMMUNE_NAME} "
                    f"({r['perimetre']}) sans preuve d'ancrage — à trancher via /atelier",
                    ref={"table": "entities", "id": r["id"]})
            for r in rows]


CHECKS = [
    check_hardcoded_commune,
    check_commune_sans_preuve,
    check_orphan_relations,
    check_self_loop_relations,
    check_orphan_embeddings,
    check_orphan_notes,
    check_orphan_event_entities,
    check_orphan_subtables,
    check_duplicate_official_ids,
    check_duplicate_names,
    check_unclosed_old_mandates,
    check_stale_body_membership,
    check_geocodable_in_commune,
    check_confidence_values,
    check_silent_source,
]

# ─────────────────────────────────────────────────────────────────────────────
# Loop
# ─────────────────────────────────────────────────────────────────────────────

def scan(c):
    findings = []
    for check in CHECKS:
        findings.extend(check(c))
    return findings


def summarize(findings):
    by_sev, by_check = {}, {}
    for f in findings:
        by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1
        by_check[f["check"]] = by_check.get(f["check"], 0) + 1
    return by_sev, by_check


def apply_autofixes(c, findings):
    n = 0
    for f in findings:
        if f["autofix"]:
            sql, params = f["autofix"]
            c.execute(sql, params)
            n += 1
    c.commit()
    return n


def backup_db():
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = Path.home() / "Claude" / ".backups" / f"commune-qa-{ts}"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DB_PATH, dest / DB_PATH.name)
    return dest / DB_PATH.name


def write_report(findings):
    by_sev, by_check = summarize(findings)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps({
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total": len(findings),
        "by_severity": by_sev,
        "by_check": by_check,
        "findings": findings,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def print_summary(findings, iteration=None):
    by_sev, by_check = summarize(findings)
    head = f"\n— Scan QA{f' (itération {iteration})' if iteration else ''} —"
    print(head)
    if not findings:
        print("  ✓ aucune anomalie."); return
    order = {"blocking": 0, "warning": 1, "info": 2}
    for sev in sorted(by_sev, key=lambda s: order.get(s, 9)):
        print(f"  {sev:9} : {by_sev[sev]}")
    print("  par check :")
    for ck, n in sorted(by_check.items(), key=lambda kv: -kv[1]):
        autofix = any(f["autofix"] for f in findings if f["check"] == ck)
        print(f"    {ck:26} {n:>4}{'  (autofix)' if autofix else ''}")


def main():
    ap = argparse.ArgumentParser(description="Loop QA / vérification Commune")
    ap.add_argument("--fix", action="store_true", help="applique les autofixes sûrs (orphelins)")
    ap.add_argument("--loop", action="store_true", help="scan→fix→rescan jusqu'à stable")
    ap.add_argument("--max-iter", type=int, default=5)
    args = ap.parse_args()

    if not DB_PATH.exists():
        raise SystemExit(f"DB introuvable : {DB_PATH}")

    do_fix = args.fix or args.loop
    c = conn()
    try:
        if do_fix:
            print(f"Backup avant fix : {backup_db()}")

        iteration = 0
        while True:
            iteration += 1
            findings = scan(c)
            print_summary(findings, iteration if args.loop else None)

            autofixable = [f for f in findings if f["autofix"]]
            if do_fix and autofixable:
                n = apply_autofixes(c, findings)
                print(f"  → {n} autofixes appliqués.")

            # condition de sortie
            if not args.loop:
                break
            if not autofixable:
                print("  ✓ plus d'anomalie auto-corrigeable — loop stable.")
                break
            if iteration >= args.max_iter:
                print(f"  ⚠ max-iter ({args.max_iter}) atteint."); break

        findings = scan(c)        # état final
        write_report(findings)
        by_sev, _ = summarize(findings)
        print(f"\nRapport : {REPORT_PATH}")
        blocking = by_sev.get("blocking", 0)
        print(f"Anomalies bloquantes restantes : {blocking}"
              + ("" if blocking == 0 else "  → fusion/retypage à traiter via /atelier"))
        raise SystemExit(1 if blocking else 0)
    finally:
        c.close()


if __name__ == "__main__":
    main()
