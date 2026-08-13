"""
events_scraper.py — Vie locale : actualités et agenda des sites officiels.

Le connecteur déclaré par l'instance rend des articles typés ; ce module les
enregistre. Il ne sait pas lire un site, et c'est voulu : la particularité vit
dans `collectors/connecteurs/`, pas ici.

Ce qu'il faut assumer plutôt que masquer : **un système de publication date la
PUBLICATION, pas l'événement**. Le connecteur cherche une date dans le titre
puis dans le corps de l'article ; faute de quoi il retient la date de
publication et le dit (`date_source`). La page publique doit pouvoir
distinguer les deux — un agenda qui affiche une date de publication comme une
date d'événement ment sur son contenu.

Usage :
  python3 -m collectors.events_scraper --dry-run
  python3 -m collectors.events_scraper --depuis 2026-01-01
  python3 -m collectors.events_scraper --source commune
"""
from __future__ import annotations

import argparse
import json

from .config import COMMUNE_NAME
from .connecteurs import charger
from .db import transaction

# Un titre n'est pas un événement du seul fait d'être publié : une rubrique
# « animations » contient aussi des changements d'horaire et des appels à
# bénévoles. On ne filtre pas là-dessus (trop fragile), mais ces mots qualifient
# l'article en métadonnée, pour l'atelier.
MOTS_EVENEMENT = (
    "fête", "festival", "concert", "spectacle", "exposition", "randonnée",
    "repas", "soirée", "bal", "tournoi", "vide-grenier", "brocante", "forum",
    "marché", "loto", "théâtre", "cinéma", "conférence", "atelier", "stage",
    "assemblée générale", "rencontre", "animation", "journée", "portes ouvertes",
)


def enregistrer(conn, art) -> int | None:
    """Un article = un événement local. Identité : le lien canonique.

    Le titre ne peut pas servir de clé (« Marché de producteurs » revient tous
    les ans), la date non plus (plusieurs articles le même jour). Le permalien,
    lui, est unique et stable — et c'est aussi ce qu'on republie.
    """
    metadata = json.dumps({
        "date_source": art.date_source,
        "date_publication": art.date_publication,
        "rubriques": art.rubriques,
        "mots_evenement": [m for m in MOTS_EVENEMENT
                           if m in f"{art.titre} {art.contenu[:400]}".lower()],
        "identifiant": art.identifiant,
        "content_preview": art.contenu[:500],
    }, ensure_ascii=False)

    row = conn.execute(
        "SELECT id FROM events WHERE type='local_event' AND source_url=?",
        (art.url,)).fetchone()
    if row:
        conn.execute("UPDATE events SET date=?, title=?, metadata=? WHERE id=?",
                     (art.date, art.titre, metadata, row["id"]))
        return None
    cur = conn.execute(
        "INSERT INTO events (type,date,title,source,source_url,metadata)"
        " VALUES ('local_event',?,?,?,?,?)",
        (art.date, art.titre, art.source, art.url, metadata))
    return cur.lastrowid


def main(dry_run: bool = False, depuis: str | None = None,
         source: str = "all", limit: int = 0) -> None:
    print(f"\n[events_scraper] {COMMUNE_NAME} — source={source} "
          f"depuis={depuis or 'origine'}")

    connecteur = charger()
    portees = ["commune", "epci"] if source == "all" else [source]
    articles = []
    for portee in portees:
        lot = list(connecteur.articles(portee, depuis))
        print(f"  [{portee}] {len(lot)} articles de vie locale")
        articles += lot
    if limit:
        articles = articles[:limit]

    if dry_run:
        date_texte = sum(1 for a in articles if a.date_source == "texte")
        print(f"\n  [dry-run] {len(articles)} articles — {date_texte} avec une "
              f"date trouvée dans le texte, {len(articles) - date_texte} datés "
              "de leur publication")
        for a in articles[:15]:
            marque = "≈" if a.date_source == "publication" else " "
            print(f"    {marque}{a.date}  {a.source:14} {a.titre[:58]}")
        return

    inseres = 0
    with transaction() as conn:
        for a in articles:
            if enregistrer(conn, a):
                inseres += 1
    print(f"\n[events_scraper] {inseres} nouveaux / {len(articles)} articles traités")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Vie locale — commune et intercommunalité")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--depuis", help="date ISO minimale de publication")
    ap.add_argument("--limit", "-n", type=int, default=0)
    ap.add_argument("--source", "-s", default="all", choices=["all", "commune", "epci"])
    args = ap.parse_args()
    main(dry_run=args.dry_run, depuis=args.depuis, source=args.source, limit=args.limit)
