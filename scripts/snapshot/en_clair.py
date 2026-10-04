"""Ce qui cite : les conseils en clair, les dossiers, et le graphe des liens qu'ils tissent.

Feuilles « en clair » et dossiers thématiques sont des textes relus, pas des
faits collectés : ils ne sortent que retenus par l'atelier, et tels que
relus. En s'écrivant, ils citent des actes ; le graphe des liens
(`collectors/graphe.py`) relève ces citations contre les seuls actes PUBLIÉS
et écrit les tables qui permettent au site de remonter d'un acte à ce qui le
cite.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from collectors.graphe import Graphe, personnes_morales_par_acte
from scripts.snapshot.socle import ROOT, row, write_json


# ── Le conseil en clair : ce que l'atelier a RETENU, et rien d'autre ─────────
#
# Une feuille « en clair » est un texte rédigé sur une séance — souvent par un
# LLM sur le poste de l'opérateur —, pas un fait collecté. Elle suit donc la
# règle inverse des lignes importées (`collectors/verdict.py`,
# OBJETS_A_RETENIR) : publiée seulement si un validateur l'a retenue, ET si le
# vérificateur ne lui trouve aucune faute au moment de publier. Une source
# corrigée depuis la relecture peut rendre fausse une feuille retenue : elle
# sort alors du site jusqu'à nouvelle relecture, et le compte-rendu le dit.
# Depuis le 01/10/2026, elle sort aussi telle qu'elle a été RELUE : un relevé
# modifié après avoir été retenu ne porte plus l'empreinte retenue, et attend
# une nouvelle relecture (`verdict.publiable_tel_quel`).

def _liens_en_clair(releve: dict, graphe) -> dict:
    """n° d'acte d'une séance relevée → l'acte publié, par sa clé datée. Une
    séance en clair relève ses actes par leur NUMÉRO : c'est la clé
    (`c-2026-41`), pas l'identifiant en base, qui les relie. Un numéro dont
    l'acte n'est pas publié reste du texte."""
    from collectors.cle_acte import TYPE_ACTE, cle_acte
    prefixe = {"cm": "c", "cc": "cc"}.get(releve.get("code", ""))
    date = (releve.get("seance") or {}).get("date")
    if not prefixe or not date or graphe is None:
        return {}
    liens = {}
    for acte in releve.get("actes", []):
        c = cle_acte(TYPE_ACTE[prefixe], date, str(acte.get("n")))
        a = graphe.index.acte(c.valeur) if c else None
        if a:
            liens[acte["n"]] = a
    return liens


def export_en_clair(conn, out: Path, root: Path, graphe=None) -> dict:
    from collectors.en_clair.rendu import document, feuilles, page_erreurs
    from collectors.en_clair.seances import nom_de_fichier, releves, seance_id
    from collectors.en_clair.verifier import verifier
    from collectors.dossiers import a_la_colonne_empreinte
    from collectors.verdict import empreinte, publiable_si_retenu

    dossier = out / "conseils"
    dossier.mkdir(parents=True, exist_ok=True)
    for f in dossier.glob("*.html"):         # miroir : une feuille retirée sort
        f.unlink()
    index, ecartes = [], {"non_retenus": 0, "en_faute": [], "sans_seance": [],
                          "modifies": []}
    emp = "empreinte" if a_la_colonne_empreinte(conn) else "NULL AS empreinte"
    for chemin, r in releves(root):
        sid = seance_id(conn, r)
        if sid is None:
            ecartes["sans_seance"].append(chemin.parent.name)
            continue
        a = row(conn, f"SELECT review_status, reviewed_at, {emp} FROM annotations "
                      "WHERE object_type='en_clair' AND object_id=?", (sid,))
        if not a or not publiable_si_retenu(a["review_status"]):
            ecartes["non_retenus"] += 1
            continue
        if a["empreinte"] != empreinte(chemin.read_bytes()):
            # Retenu sur un autre texte (ou avant que l'empreinte existe, et
            # pas encore repris par scripts/reprendre_empreintes.py).
            ecartes["modifies"].append(chemin.parent.name)
            continue
        if verifier(chemin):
            ecartes["en_faute"].append(chemin.parent.name)
            continue
        # La mention publique ne porte pas l'adresse du relecteur : une date suffit
        # à dire que quelqu'un a regardé et l'assume.
        relu = f"relu à l'atelier le {(a['reviewed_at'] or '')[:10]}"
        nom = nom_de_fichier(r)
        s = r["seance"]
        actes_lies = _liens_en_clair(r, graphe)
        for acte in actes_lies.values():
            graphe.citer(acte.cle, {"type": "en_clair", "date": s["date"],
                                 "assemblee": s["assemblee_court"],
                                 "fichier": f"conseils/{nom}.html"})
        (dossier / f"{nom}.html").write_text(document(
            # Le nom de la rubrique, le même que l'en-tête et /conseils
            # (docs/refonte-du-contenu.md, décision 2).
            f"Les conseils en clair · {s['assemblee_court']} · {s['date']}",
            feuilles(r, relu=relu, liens={n: x.url for n, x in actes_lies.items()})
            + page_erreurs(r),
            retour=("/conseils", "Toutes les séances")), encoding="utf-8")
        ap = r["en_clair"]["apres"]
        index.append({
            "date": s["date"],
            "assemblee": s["assemblee_court"],
            "code": r.get("code"),
            "titre": ap.get("titre") if ap.get("statut") != "non_publie" else "Actes non publiés",
            "actes": len(r.get("actes", [])),
            "unanimite": sum(1 for x in r.get("actes", []) if (x.get("vote") or {}).get("unanimite")),
            "fichier": f"conseils/{nom}.html",
            "relu_le": (a["reviewed_at"] or "")[:10],
        })
    index.sort(key=lambda x: (x["date"], x["code"] or ""))
    write_json(out / "conseils.json", {"seances": index, "total": len(index)})
    return {"publiees": len(index), **ecartes}


# Les dossiers thématiques suivent la même règle depuis le 01/10/2026 : publiés
# RETENUS à l'atelier, et tels qu'ils ont été relus. Le site ne lit plus le
# répertoire `dossiers/` de l'instance : il lit `dossiers.json`, écrit ici, qui
# ne contient que ce qui sort. Un dossier écarté ou en cours de réécriture n'y
# figure pas — il n'a ni page ni URL.

#
# Depuis le 03/10/2026, chaque dossier publié passe par le résolveur de
# citations (`collectors/citations.py`) : son markdown sort RELIÉ — les « (CM du
# 14/04/2021) » deviennent des liens vers l'acte publié —, avec la liste de ses
# citations pour les infobulles, et, si un acte cité a changé depuis la
# relecture, l'état de péremption (`collectors/dossiers.py::peremption`). Le
# dossier reste publié dans ce cas : il a été relu, et le bandeau le dit.

def export_dossiers(conn, out: Path, root: Path, graphe=None) -> dict:
    from collectors.dossiers import entete, identifiant, peremption, publiables
    from collectors.graphe import Graphe
    graphe = graphe or Graphe()
    sortis, ecartes = publiables(conn, root)
    citations = Counter()
    perimes = []
    for d in sortis:
        meta, _ = entete(d["texte"])
        if meta.get("statut") == "a_developper":
            continue            # son corps ne sort pas : rien à relier
        r = graphe.dossier(d["slug"], meta.get("titre") or d["slug"], d["texte"])
        d["texte"] = r["relie"].texte
        if r["citations"]:
            d["citations"] = r["citations"]
        for c in r["relie"].citations:
            citations[c.resolution.statut] += 1
        p = peremption(conn, identifiant(conn, d["slug"]), d["empreinte"], graphe.index)
        if p and p["elements"]:
            for el in p["elements"]:
                if el["quoi"] == "modifie" and (t := graphe.titre_public(el["cle"])):
                    el["titre"] = t
            d["perime"] = p
            perimes.append(d["slug"])
    write_json(out / "dossiers.json", {"dossiers": sortis, "total": len(sortis)})
    return {"publies": len(sortis), **ecartes, "citations": dict(citations),
            "perimes": perimes}


def etape_graphe(conn, out, index_actes, affiches, public_events, public_links,
                 public_entities) -> dict:
    # Le graphe des liens se remplit pendant que séances et dossiers
    # s'écrivent : ce sont eux qui citent. Il ne connaît que les actes
    # PUBLIÉS (`index_actes`), jamais la base entière.
    graphe = Graphe(index_actes, affiches)
    stats_en_clair = export_en_clair(conn, out, ROOT, graphe)
    stats_dossiers = export_dossiers(conn, out, ROOT, graphe)
    stats_graphe = graphe.ecrire(
        out,
        alias={f"a{e['id']}": e["ancre"] for e in public_events
               if e.get("ancre") and e["ancre"] != f"a{e['id']}"},
        personnes_morales=personnes_morales_par_acte(
            conn, public_events, public_links, public_entities))
    return {"graphe": graphe, "stats_en_clair": stats_en_clair,
            "stats_dossiers": stats_dossiers, "stats_graphe": stats_graphe}
