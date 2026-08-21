#!/usr/bin/env python3
"""
banc_essai_ia.py — quel modèle local sait lire un procès-verbal ?

Compare plusieurs modèles sur de VRAIS comptes rendus de l'instance, avec
exactement le prompt de l'atelier (importé de `collectors/extraction.py`, jamais
recopié). Rien n'est écrit en base : le banc lit, mesure, et affiche.

CE QU'IL MESURE, ET POURQUOI

  propositions          combien de lignes le modèle propose. Beaucoup n'est pas
                        bon signe en soi — un modèle bavard invente.
  citations vérifiées   la part des propositions dont la phrase citée figure
                        VRAIMENT dans le texte. C'est la mesure qui compte :
                        elle ne demande aucune confiance envers le modèle, et
                        elle attrape l'invention sans relecture humaine.
  réponses illisibles   tranches où le modèle n'a pas rendu de JSON exploitable.
  durée                 sur une machine de collecte, un modèle qui met dix
                        minutes par PV ne sera pas utilisé.

Le taux de citations vérifiées est un plancher, pas une note : une citation
retrouvée prouve que la phrase existe, pas que la ligne l'interprète bien. Le
banc dit quel modèle ne ment pas ; il ne dit pas lequel comprend.

Usage :
  venv/bin/python scripts/banc_essai_ia.py
  venv/bin/python scripts/banc_essai_ia.py --modeles qwen2.5:14b,gemma4:26b --actes 3
  venv/bin/python scripts/banc_essai_ia.py --objet budget_vote --json rapport.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

from collectors import extraction  # noqa: E402
from collectors.db import get_conn  # noqa: E402

# `127.0.0.1` et non `localhost` : sur ce Mac, `localhost` résout en IPv6 alors
# qu'Ollama n'écoute qu'en IPv4 — une demi-journée perdue le 20/08/2026 sur un
# « connection refused » qui ne concernait pas le service qu'on croyait.
OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")

MODELES_PAR_DEFAUT = ["qwen2.5:14b", "gemma4:26b"]


def appel_pour(modele: str):
    """Fabrique la fonction d'appel attendue par `extraction.extraire`.

    Format « chat completions », celui que parlent aussi bien Ollama que les
    passerelles distantes : le banc mesure donc le modèle, pas un dialecte.
    """
    def appel(message, system="", max_tokens=2048, json_strict=False):
        charge = {
            "model": modele,
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": message}],
        }
        if json_strict:
            charge["response_format"] = {"type": "json_object"}
            charge["temperature"] = 0
        r = requests.post(f"{OLLAMA}/v1/chat/completions", json=charge, timeout=900)
        r.raise_for_status()
        # Le même lecteur que l'atelier : un modèle à raisonnement rend un
        # contenu vide avec un HTTP 200 quand son budget de tokens est épuisé,
        # et le banc doit dire ça plutôt que « 0 proposition ».
        return extraction.contenu_openai(r.json())
    return appel


def actes_dessai(conn, combien: int) -> list[dict]:
    """Les procès-verbaux les plus consistants de la base.

    Choisis par longueur de texte, et non au hasard : un compte rendu de trois
    lignes ne départage aucun modèle. Ce sont de vrais documents de l'instance,
    avec leurs césures de PDF et leurs en-têtes répétés — les extraire
    proprement est précisément ce qu'on veut éprouver.
    """
    return [dict(r) for r in conn.execute("""
        SELECT id, date, title, content, LENGTH(content) AS taille
        FROM events
        WHERE type IN ('deliberation','conseil_municipal','délibérations_cc','pv_cc')
          AND content IS NOT NULL AND LENGTH(content) > 4000
        ORDER BY LENGTH(content) DESC
        LIMIT ?""", (combien,))]


def modeles_disponibles() -> set[str]:
    try:
        r = requests.get(f"{OLLAMA}/api/tags", timeout=5)
        r.raise_for_status()
        return {m["name"] for m in r.json().get("models", [])}
    except Exception:
        return set()


def essayer(modele: str, actes: list[dict], objet: str) -> dict:
    resultats, propositions_vues = [], []
    debut_total = time.time()
    for acte in actes:
        debut = time.time()
        try:
            r = extraction.extraire(acte["content"], objet, appel_pour(modele))
        except Exception as e:
            print(f"    ✗ {acte['date']} — {type(e).__name__}: {e}")
            resultats.append({"acte": acte["id"], "erreur": str(e)})
            continue
        duree = time.time() - debut
        n = len(r["propositions"])
        part = f"{r['citations_verifiees']}/{n}" if n else "—"
        print(f"    {acte['date']}  {r['tranches']} tranche(s)  "
              f"{n:3} propositions  citations {part:>7}  {duree:6.1f}s"
              + (f"  ⚠ {r['reponses_illisibles']} sans réponse exploitable"
                 if r["reponses_illisibles"] else ""))
        # Le motif, pas seulement le compte : « 5 réponses illisibles » n'a
        # rien appris pendant deux essais, « le modèle n'est pas arrivé à la
        # réponse » se corrige en une variable d'environnement.
        for motif in r.get("motifs_echec", []):
            print(f"        ↳ {motif}")
        resultats.append({"acte": acte["id"], "date": acte["date"],
                          "duree": round(duree, 1), **{k: v for k, v in r.items()
                                                       if k != "propositions"}})
        propositions_vues.extend(r["propositions"])

    n = len(propositions_vues)
    verifiees = sum(1 for p in propositions_vues if p.get("citation_verifiee"))
    return {
        "modele": modele,
        "duree_totale": round(time.time() - debut_total, 1),
        "propositions": n,
        "citations_verifiees": verifiees,
        "taux": round(100 * verifiees / n) if n else 0,
        "illisibles": sum(r.get("reponses_illisibles", 0) for r in resultats),
        "detail": resultats,
        "echantillon": propositions_vues[:5],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Compare des modèles locaux sur de vrais PV")
    ap.add_argument("--modeles", default=",".join(MODELES_PAR_DEFAUT),
                    help="liste séparée par des virgules")
    ap.add_argument("--objet", default="flux", choices=list(extraction.GABARITS))
    ap.add_argument("--actes", type=int, default=2)
    ap.add_argument("--json", help="écrire le rapport complet dans ce fichier")
    args = ap.parse_args()

    dispo = modeles_disponibles()
    if not dispo:
        print(f"Aucun modèle joignable sur {OLLAMA} — Ollama tourne-t-il ?")
        sys.exit(1)

    demandes = [m.strip() for m in args.modeles.split(",") if m.strip()]
    absents = [m for m in demandes if m not in dispo]
    if absents:
        print(f"Absents d'Ollama, ignorés : {', '.join(absents)}")
        print(f"Disponibles : {', '.join(sorted(dispo))}")
    demandes = [m for m in demandes if m in dispo]
    if not demandes:
        sys.exit(1)

    conn = get_conn(read_only=True)
    actes = actes_dessai(conn, args.actes)
    conn.close()
    if not actes:
        print("Aucun procès-verbal assez consistant dans cette base.")
        sys.exit(1)

    print(f"\nBanc d'essai — objet « {args.objet} », {len(actes)} acte(s), "
          f"{sum(a['taille'] for a in actes) // 1000} k caractères")
    for a in actes:
        print(f"  · {a['date']}  {a['taille']:6} car.  {(a['title'] or '')[:60]}")

    rapports = []
    for modele in demandes:
        print(f"\n  {modele}")
        rapports.append(essayer(modele, actes, args.objet))

    print("\n" + "─" * 72)
    print(f"{'modèle':24} {'propositions':>12} {'citations OK':>13} {'durée':>8}")
    for r in rapports:
        # Guillemets non imbriqués : la CI joue aussi sur Python 3.11, où une
        # f-string ne peut pas contenir le même guillemet qu'elle.
        citations = "{} ({} %)".format(r["citations_verifiees"], r["taux"])
        print(f"{r['modele']:24} {r['propositions']:>12} {citations:>13} "
              f"{r['duree_totale']:>7.0f}s")
    print("─" * 72)
    print("Le taux de citations vérifiées est un PLANCHER : il prouve que la "
          "phrase existe,\nnon que la ligne l'interprète correctement. "
          "Relire l'échantillon avant de trancher.")

    for r in rapports:
        if r["echantillon"]:
            print(f"\n  Échantillon — {r['modele']}")
            for p in r["echantillon"]:
                marque = "✓" if p.get("citation_verifiee") else "✗ CITATION INTROUVABLE"
                extrait = {k: v for k, v in p.items()
                           if k not in ("citation", "citation_verifiee")}
                print(f"    {marque} {json.dumps(extrait, ensure_ascii=False)[:140]}")
                print(f"      « {(p.get('citation') or '')[:120]} »")

    if args.json:
        Path(args.json).write_text(
            json.dumps({"objet": args.objet,
                        "actes": [{k: v for k, v in a.items() if k != "content"}
                                  for a in actes],
                        "rapports": rapports}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(f"\nRapport complet → {args.json}")


if __name__ == "__main__":
    main()
