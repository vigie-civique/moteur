"""graphe.py — le graphe des liens du snapshot : qui cite quoi, dans les deux sens.

Le snapshot publiait des actes, des dossiers et des séances en clair comme trois
îles. Un dossier disait « (CM du 14/04/2021) » sans lien ; la page de l'acte ne
savait pas qu'un dossier s'appuyait sur elle ; une séance en clair citait ses
actes par leur numéro, en texte. Ce module tient le registre de ces renvois
pendant que le snapshot écrit les dossiers et les séances, puis publie :

  liens.json              vers le HAUT : clé d'acte → les dossiers (et leur
                          partie) et les séances en clair qui le citent ; plus
                          la table d'ALIAS `#a{id}` → clé, pour un cycle : les
                          liens posés avant le 03/10/2026 visaient l'id ;
  lacunes.json            vers l'ACTION : les questions ouvertes des dossiers
                          et leurs citations sans cible, sous un même format
                          (`collectors/lacunes.py`) ;
  personnes_morales.json  en LARGEUR : par acte, les personnes MORALES publiées
                          qu'il concerne, avec leur SIREN. Rien d'autre — ni
                          personne physique, ni appel à une autre vigie : le
                          branchement viendra avec `docs/federation.md`.

Aucune de ces trois tables ne publie ce qui ne l'est pas déjà : elles ne
portent que des clés d'actes publiés, des dossiers publiés, des entités
publiées. Un renvoi vers un dossier non retenu révélerait son existence.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from . import lacunes as _lacunes
from .citations import Index, ancre, relier


class Graphe:
    def __init__(self, index: Index | None = None, affiches: dict | None = None):
        #: Les actes et séances publiés, tels que le résolveur les connaît.
        self.index = index or Index([])
        #: id → ligne de `events.json` : ce que le site affiche d'un acte.
        self.affiches = affiches or {}
        self.retours: dict[str, list[dict]] = defaultdict(list)
        self.lacunes: list[dict] = []
        self.non_resolues: list[dict] = []

    # ── vers le haut ─────────────────────────────────────────────────────────
    def citer(self, cle: str, renvoi: dict) -> None:
        """Un renvoi vers l'acte `cle`. Deux citations du même acte dans la
        même partie du même dossier font UN retour : le lecteur de la page de
        l'acte veut savoir où aller, pas combien de fois."""
        if renvoi not in self.retours[cle]:
            self.retours[cle].append(renvoi)

    # ── un dossier ───────────────────────────────────────────────────────────
    def dossier(self, slug: str, titre: str, texte: str) -> dict:
        """Relie un dossier publié : son texte, ses citations pour le site, et
        ce qu'il apporte au graphe (retours, lacunes)."""
        relie = relier(texte, self.index)
        publiques, vues = [], set()
        for c in relie.resolues:
            a = c.resolution.cible
            self.citer(a.cle, {
                "type": "dossier", "slug": slug, "titre": titre,
                "section": c.section, "ancre": ancre(c.section) if c.section else None,
                "precis": c.resolution.statut == "precis"})
            if c.resolution.url not in vues:
                vues.add(c.resolution.url)
                publiques.append(c.public(self.affiches.get(a.id)))
        self.lacunes += _lacunes.questions(slug, texte)
        self.lacunes += _lacunes.citations(slug, relie.non_resolues)
        self.non_resolues += [{"dossier": slug, **c.releve()} for c in relie.non_resolues]
        return {"relie": relie, "citations": publiques}

    def titre_public(self, cle: str) -> str | None:
        a = self.index.par_cle.get(cle)
        return (self.affiches.get(a.id) or {}).get("title") if a else None

    # ── l'écriture ───────────────────────────────────────────────────────────
    def ecrire(self, out: Path, alias: dict[str, str],
               personnes_morales: dict[str, list[dict]]) -> dict:
        """Écrit les trois tables, et rend leurs comptes pour `stats.json`."""
        retours = {c: r for c, r in sorted(self.retours.items())}
        _ecrire(out / "liens.json", {
            "actes": retours, "total": len(retours),
            "alias": alias,
            "_alias": "Anciennes ancres #a{id} → clé datée de l'acte. Servies un "
                      "cycle de publication après le 03/10/2026, puis retirées.",
        })
        par_nature = defaultdict(int)
        for l in self.lacunes:
            par_nature[l["nature"]] += 1
        _ecrire(out / "lacunes.json", {"lacunes": self.lacunes, "total": len(self.lacunes),
                                       "par_nature": dict(par_nature)})
        _ecrire(out / "personnes_morales.json", {
            "actes": personnes_morales, "total": len(personnes_morales),
            "_note": "Personnes morales publiées que chaque acte concerne, par "
                     "SIREN. Aucune personne physique. Préparé pour la "
                     "fédération des vigies (docs/federation.md), non branché.",
        })
        return {"actes_cites": len(retours),
                "renvois": sum(len(r) for r in retours.values()),
                "alias": len(alias), "lacunes": dict(par_nature),
                "citations_non_resolues": len(self.non_resolues),
                "actes_avec_personne_morale": len(personnes_morales)}

    def ecrire_releve(self, dossier: Path) -> None:
        """Le relevé des citations non résolues — INTERNE (`audits/`), avec
        les candidats que l'atelier proposera."""
        _ecrire(dossier / "citations_non_resolues.json",
                {"citations": self.non_resolues, "total": len(self.non_resolues)})


def _ecrire(chemin: Path, donnees) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")


def personnes_morales_par_acte(conn, public_events: list[dict], public_links: list[dict],
                               public_entities: list[dict]) -> dict[str, list[dict]]:
    """Clé d'acte → les personnes MORALES publiées qu'il concerne, par SIREN.

    Le SIREN vit dans `businesses` et `associations` ; une entité sans SIREN
    n'y entre pas (rien à rapprocher d'une autre vigie). Une personne physique
    n'y entre JAMAIS, même publiée au titre de son mandat : la fédération
    rapproche des structures, pas des gens. Seules les clés stables comptent —
    une clé faible ou ambiguë ne se rapproche de rien ailleurs.
    """
    entites = {e["id"]: e for e in public_entities if e.get("type") != "person"}
    if not entites:
        return {}
    sirens: dict[int, str] = {}
    for table in ("businesses", "associations"):
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (table,)).fetchone():
            for eid, siren in conn.execute(
                    f"SELECT entity_id, siren FROM {table} WHERE siren IS NOT NULL AND siren <> ''"):
                if eid in entites:
                    sirens.setdefault(eid, siren)
    cles = {e["id"]: e["cle"] for e in public_events
            if e.get("cle") and e.get("ancre") == e.get("cle")}
    sortie: dict[str, list[dict]] = defaultdict(list)
    for l in public_links:
        cle, eid = cles.get(l["event_id"]), l["entity_id"]
        if cle and eid in sirens:
            ligne = {"siren": sirens[eid], "nom": entites[eid].get("name"), "entity_id": eid}
            if ligne not in sortie[cle]:
                sortie[cle].append(ligne)
    return dict(sorted(sortie.items()))
