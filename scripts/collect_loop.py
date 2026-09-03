#!/usr/bin/env python3
"""
collect_loop.py — relance les sources PÉRIMÉES, et rien d'autre.

Le moteur savait déjà trois choses sur sa propre cadence, et il lui manquait la
quatrième :

  1. le RYTHME de chaque source — `STEP_META` (TTL, priorité, table témoin) ;
  2. le JOURNAL de ce qui a tourné — `collector_runs`, écrit par
     `run_all.run_step` ;
  3. le CONTRÔLE — `qa_loop` signale une source muette ;
  4. **l'ACTEUR** — personne ne relançait ce qui était périmé. C'est ce
     fichier. Il ne décide d'aucun rythme : il ne fait qu'exécuter celui que
     `STEP_META` déclare déjà.

Le vérificateur de cette boucle est donc la FRAÎCHEUR, pas le succès : un
collecteur qui rend zéro ligne n'est pas en échec (c'est le cas ordinaire d'une
petite commune), il est simplement à jour. Ce qui doit alerter, c'est le
silence — et il se lit dans `collector_runs`, pas dans les compteurs.

Usage :
    venv/bin/python3 scripts/collect_loop.py                 # scan seul (lecture)
    venv/bin/python3 scripts/collect_loop.py --run           # une passe
    venv/bin/python3 scripts/collect_loop.py --loop          # jusqu'à stable
    venv/bin/python3 scripts/collect_loop.py --only events --run
    venv/bin/python3 scripts/collect_loop.py --force --run   # ignore les TTL

Code de sortie : 0 si rien n'a échoué, 1 sinon — pour qu'un ordonnanceur le
sache sans lire la sortie.

⚠️ Deux gestes que cette boucle fait À VOTRE PLACE, et qu'il ne faut pas
retirer :

  - **les dérivés suivent leur source.** `cm_flux`, `commissions`,
    `approbations` et `budgets_votes` relisent le TEXTE des séances : les
    rejouer après `cm` n'est pas une précaution, c'est la correction du défaut
    du 14/08/2026 — `cm_flux` avait tourné sur 309 PV, `cm` en avait ajouté 636
    une demi-heure plus tard, et le site a publié 44 subventions au lieu de 123.
  - **`origine` et `perimetre` ferment toute passe** qui a collecté quelque
    chose. Un step lancé seul laisse ses entités NON CLASSÉES : le 03/09/2026,
    `--step osm` a créé 121 lieux avec `perimetre` NULL et le snapshot suivant a
    publié 130 objets de moins sans rien dire.
    Cf. [[feedback-step-isole-non-classe]].
"""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from collectors.config import DB_PATH, STEP_META          # noqa: E402
from collectors.db import get_conn                        # noqa: E402
from collectors.run_all import STEPS, run_step            # noqa: E402

# Ce que la boucle peut relancer : l'intersection du rythme déclaré et des steps
# qui existent. Une liste recopiée ici dériverait — c'est ce qui, en v1, ne
# suivait que 10 collecteurs sur 15, et rendait le silence des cinq autres
# indétectable.
SUIVIS = {nom: meta for nom, meta in STEP_META.items() if nom in STEPS}

# Les dérivés, par la source dont ils relisent le texte. Leur rythme propre
# reste dans `STEP_META` : ce tableau ne dit pas QUAND les jouer, il dit
# qu'après cette source-là ils sont périmés quoi qu'en dise leur date.
DERIVES: dict[str, tuple[str, ...]] = {
    "cm":         ("cm_flux", "commissions", "approbations", "budgets_votes"),
    "cm_archive": ("cm_flux", "commissions", "approbations", "budgets_votes"),
    "cc_epci":    ("cm_flux",),
    "ofgl":       ("subventions",),
    "budget":     ("subventions",),
}

# Les deux classements qui ferment une collecte. Ils ne vont chercher rien.
CLOTURE = ("origine", "perimetre")

TEMPS_MAX_DEFAUT = 900   # secondes, par collecteur


class TempsDepasse(Exception):
    """Levée dans le collecteur lui-même, donc journalisée par `run_step`."""


def _age_jours(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return (datetime.now() - datetime.fromisoformat(iso)).total_seconds() / 86400
    except ValueError:
        return None


def dernier_passage(conn, nom: str):
    """Dernier passage ABOUTI. Un `error` ou un `timeout` ne rajeunit rien.

    Sans cette clause, une source en panne paraîtrait fraîche pour la seule
    raison qu'on a essayé — et la boucle cesserait de la retenter le lendemain.
    """
    return conn.execute(
        "SELECT finished_at, status FROM collector_runs"
        " WHERE collector=? AND status IN ('ok','empty') AND finished_at IS NOT NULL"
        " ORDER BY finished_at DESC LIMIT 1", (nom,)).fetchone()


def perimes(conn, force: bool = False) -> list[str]:
    """Les steps à rejouer, du plus prioritaire au moins."""
    retard = []
    for nom in sorted(SUIVIS, key=lambda n: SUIVIS[n][1]):
        ttl = SUIVIS[nom][0]
        ligne = dernier_passage(conn, nom)
        age = _age_jours(ligne["finished_at"]) if ligne else None
        if force or age is None or age > ttl:
            retard.append(nom)
    return retard


def scan(conn, force: bool = False) -> list[str]:
    retard = set(perimes(conn, force))
    print(f"\n{'collecteur':14} {'dernier passage':18} {'âge':>7} {'TTL':>6}  état")
    print("─" * 62)
    for nom in sorted(SUIVIS, key=lambda n: SUIVIS[n][1]):
        ligne = dernier_passage(conn, nom)
        age = _age_jours(ligne["finished_at"]) if ligne else None
        quand = ligne["finished_at"][:16] if ligne else "jamais"
        print(f"{nom:14} {quand:18} {(f'{age:.1f}j' if age is not None else '—'):>7}"
              f" {SUIVIS[nom][0]:>5}j  {'PÉRIMÉ' if nom in retard else 'frais'}")
    print("─" * 62)
    ordre = [n for n in sorted(SUIVIS, key=lambda n: SUIVIS[n][1]) if n in retard]
    print(f"{len(ordre)} source(s) à rafraîchir : {', '.join(ordre) if ordre else '—'}")
    return ordre


def jouer(nom: str, temps_max: int) -> tuple[str, str | None]:
    """Joue un step sous garde de temps. `run_step` journalise, pas nous.

    L'alarme lève DANS le collecteur : l'exception remonte à `run_step`, qui la
    consigne en `error` avec son message. Une garde posée à l'extérieur aurait
    laissé la ligne de journal ouverte pour toujours — un run sans fin est
    indiscernable d'un run en cours.
    """
    def _alarme(signum, frame):
        raise TempsDepasse(f"dépassé {temps_max}s")

    precedent = signal.signal(signal.SIGALRM, _alarme)
    signal.alarm(temps_max)
    try:
        return run_step(nom)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, precedent)


def items(conn, nom: str) -> int | None:
    """Ce que le dernier run a ajouté, pour savoir si un dérivé doit suivre."""
    ligne = conn.execute(
        "SELECT items_added FROM collector_runs WHERE collector=?"
        " ORDER BY id DESC LIMIT 1", (nom,)).fetchone()
    return ligne["items_added"] if ligne else None


def sauvegarde() -> Path:
    """Copie de la base avant d'écrire. Même convention que `qa_loop`."""
    racine = Path(os.environ.get("VIGIE_BACKUPS") or Path.home() / "Claude" / ".backups")
    dest = racine / f"vigie-collecte-{datetime.now():%Y%m%d-%H%M%S}"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DB_PATH, dest / DB_PATH.name)
    return dest / DB_PATH.name


def main() -> int:
    ap = argparse.ArgumentParser(description="Relance les sources périmées")
    ap.add_argument("--run", action="store_true", help="une passe")
    ap.add_argument("--loop", action="store_true", help="scan → run → rescan jusqu'à stable")
    ap.add_argument("--only", help="ne traiter que ce step")
    ap.add_argument("--force", action="store_true", help="ignorer les TTL")
    ap.add_argument("--max-iter", type=int, default=3)
    ap.add_argument("--temps-max", type=int, default=TEMPS_MAX_DEFAUT,
                    help="garde de temps par collecteur, en secondes")
    args = ap.parse_args()

    if args.only and args.only not in SUIVIS:
        raise SystemExit(f"step inconnu ou sans rythme déclaré : {args.only}\n"
                         f"  connus : {', '.join(sorted(SUIVIS))}")

    conn = get_conn()
    agir = args.run or args.loop
    joues: list[str] = []
    echecs: dict[str, str] = {}
    try:
        if agir:
            print(f"Sauvegarde avant collecte : {sauvegarde()}")

        iteration = 0
        while True:
            iteration += 1
            retard = scan(conn, args.force)
            if args.only:
                retard = [args.only] if (args.only in retard or args.force) else []
            # Un échec ne se retente pas dans le même cycle : une API qui refuse
            # à 9 h refusera à 9 h 01, et insister ressemble à du martèlement.
            todo = [n for n in retard if n not in echecs]
            if not agir or not todo:
                break

            print(f"\n— Passe {iteration} : {len(todo)} step(s) —")
            for nom in todo:
                statut, err = jouer(nom, args.temps_max)
                joues.append(nom)
                if statut not in ("ok", "empty"):
                    echecs[nom] = err or "?"
                    continue
                # Le dérivé suit la source qui l'alimente, et seulement si elle
                # a ajouté quelque chose : rejouer une lecture de PV quand aucun
                # PV n'est arrivé ne coûte rien d'utile.
                if (items(conn, nom) or 0) > 0:
                    for derive in DERIVES.get(nom, ()):
                        if derive in STEPS and derive not in todo:
                            statut_d, err_d = jouer(derive, args.temps_max)
                            joues.append(derive)
                            if statut_d not in ("ok", "empty"):
                                echecs[derive] = err_d or "?"

            if not args.loop or iteration >= args.max_iter:
                break

        # Le classement ferme la passe, TOUJOURS — même si un collecteur a
        # échoué : ce qui a été écrit avant l'échec doit être classé, sinon il
        # reste invisible au snapshot.
        if joues:
            print(f"\n— Clôture : {', '.join(CLOTURE)} —")
            for nom in CLOTURE:
                statut, err = jouer(nom, args.temps_max)
                if statut not in ("ok", "empty"):
                    echecs[nom] = err or "?"

        print(f"\n{len(joues)} step(s) joué(s) : {', '.join(joues) if joues else '—'}")
        if echecs:
            print(f"{len(echecs)} en échec :")
            for nom, err in echecs.items():
                print(f"  ✗ {nom:14} {err}")
        return 1 if echecs else 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
