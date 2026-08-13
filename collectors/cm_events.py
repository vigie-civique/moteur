"""
Importeur des SAISIES LOCALES — subventions votées, baux, transactions.

Ce module ne va rien chercher en ligne : il charge `config/seed_local.json`,
qui contient ce qu'un humain a relevé dans les documents. La lecture des procès-
verbaux du conseil municipal, elle, est automatique et vit dans `cm_brassac`.
"""
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from .config import COMMUNE_URL, HEADERS, REQUEST_DELAY
from .db import transaction, upsert_entity, upsert_relation
from .cm_finances import Resolver, _clean_benef

# Domaine du site officiel, tel qu'il apparaît dans events.source et dans
# l'allowlist de publication.
SOURCE_SITE = urllib.parse.urlparse(COMMUNE_URL).netloc.removeprefix("www.")

# CRs connus avec leur contenu notable (source : scraping précédent)
# ─────────────────────────────────────────────────────────────────────────────
# Les données locales ne sont plus dans le code.
#
# Ce module portait 294 lignes propres à Lasalle : catalogue des comptes rendus,
# subventions votées, baux communaux avec le nom des locataires, et une cession
# de terrain nommant l'acquéreur, le sens de son vote et une appréciation sur
# l'usage réel du bien. Rien de tout cela n'est du code : c'est de la saisie.
#
# Le tout vit désormais dans `config/seed_local.json`, non versionné. Une autre
# commune fournit le sien ; sans fichier, l'import est ignoré au lieu d'échouer.
# ─────────────────────────────────────────────────────────────────────────────

SEED_LOCAL = Path(__file__).resolve().parent.parent / "config" / "seed_local.json"


def charger_seed() -> dict:
    try:
        with open(SEED_LOCAL, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[cm] {SEED_LOCAL.name} absent — import local ignoré.")
        return {}
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{SEED_LOCAL} illisible : {e}") from e


def import_cm_events():
    print("[cm] Import délibérations, subventions, flux financiers...")

    seed = charger_seed()
    if not seed:
        return

    with transaction() as conn:
        commune_id = _get_or_create_commune(conn, seed.get("commune"))
        _import_cr_catalogue(conn, commune_id, seed)
        _import_subventions(conn, commune_id, seed)
        _import_baux(conn, commune_id, seed)
        _import_transactions(conn, commune_id, seed)

    print("[cm] OK")


def _get_or_create_commune(conn, commune: dict | None) -> int:
    if not commune:
        raise RuntimeError("seed_local.json : clé « commune » manquante.")
    return upsert_entity(conn, **commune, confidence="verified")


def _import_cr_catalogue(conn, commune_id: int, seed: dict):
    CR_CATALOGUE = seed.get("cr_catalogue") or []
    base = seed.get("base_url") or COMMUNE_URL
    # `events` n'a aucune contrainte UNIQUE : le OR IGNORE d'origine n'ignorait
    # rien et chaque exécution réinsérait les 26 comptes rendus. Le contrôle
    # d'existence doit donc être explicite. Il porte sur l'URL source, qui
    # identifie le compte rendu — le titre, lui, est reconstruit à partir de la
    # date et se retrouverait identique sur deux séances du même jour.
    for cr in CR_CATALOGUE:
        # L'URL du seed est prise telle quelle si elle est absolue. La version
        # d'origine préfixait systématiquement `{base}/CR/`, qui est le chemin
        # des comptes rendus de lasalle.fr : ici les PV sont des PDF déposés
        # dans /wp-content/uploads/, sans motif d'URL commun. Ce catalogue-là
        # n'a d'ailleurs plus à être saisi : `cm_brassac` le lit sur le site.
        url = cr["url"] if cr["url"].startswith("http") else f"{base}/{cr['url'].lstrip('/')}"
        if conn.execute(
            "SELECT 1 FROM events WHERE type='deliberation' AND source_url=?", (url,)
        ).fetchone():
            continue
        conn.execute(
            "INSERT INTO events"
            " (type,date,title,content,source,source_url)"
            " VALUES (?,?,?,?,?,?)",
            ("deliberation", cr["date"],
             f"CM du {cr['date']}", cr["note"],
             SOURCE_SITE, url)
        )

def _import_subventions(conn, commune_id: int, seed: dict):
    SUBVENTIONS = {int(k): v for k, v in (seed.get("subventions") or {}).items()}
    # Les noms de SUBVENTIONS sont recopiés des comptes rendus : « La Boule
    # lasalloise » là où le RNA dit « LA BOULE LASALLOISE ». upsert_entity
    # matche sur (type, name) EXACT — sans résolution préalable, chaque
    # orthographe crée une association de plus, y compris entre deux années de
    # cette même liste. Le résolveur par tokens normalisés de cm_finances est
    # la mécanique déjà en place pour ça : on la réutilise plutôt que d'en
    # écrire une seconde qui divergerait.
    resolver = Resolver(conn)
    inserted, resolus = 0, 0
    for year, subs in SUBVENTIONS.items():
        for asso_name, amount in subs:
            # Entité association bénéficiaire
            asso_id, nom_retenu = resolver.resolve(asso_name)
            if asso_id is None:
                asso_id = upsert_entity(conn,
                    type="association",
                    name=_clean_benef(asso_name),
                    confidence="verified"
                )
                # Rendre la nouvelle entité résolvable pour les années suivantes.
                resolver.add(asso_id, _clean_benef(asso_name), "association")
            else:
                resolus += 1
            conn.execute(
                "INSERT OR IGNORE INTO associations (entity_id) VALUES (?)",
                (asso_id,)
            )

            # Flux financier. Même piège que pour les events : `financial_flows`
            # n'a pas de contrainte UNIQUE, donc OR IGNORE n'ignore rien et
            # chaque exécution rejouait les 57 versements — les totaux publiés
            # doublaient d'autant.
            if not conn.execute(
                "SELECT 1 FROM financial_flows WHERE type='subvention'"
                " AND year=? AND to_id=? AND source=?",
                (year, asso_id, f"CM vote subventions {year}")
            ).fetchone():
                conn.execute(
                    "INSERT INTO financial_flows"
                    " (type,year,amount,from_id,to_id,description,source)"
                    " VALUES (?,?,?,?,?,?,?)",
                    ("subvention", year, amount,
                     commune_id, asso_id,
                     f"Subvention communale {year}",
                     f"CM vote subventions {year}")
                )

            # Relation commune→association
            upsert_relation(conn,
                from_id=commune_id, to_id=asso_id,
                rel_type="subventionné",
                source="cm",
                confidence="verified",
                metadata=json.dumps({"year": year, "amount": amount})
            )
            inserted += 1

    print(f"  [cm] {inserted} subventions importées "
          f"({resolus} rattachées à une entité existante)")

def _import_baux(conn, commune_id: int, seed: dict):
    BAUX = seed.get("baux") or []
    for b in BAUX:
        tenant_id = upsert_entity(conn,
            type="person" if b["tenant"][0].isupper() and " " in b["tenant"]
                          else "association",
            name=b["tenant"],
            confidence="verified"
        )
        # Même absence de contrainte UNIQUE que pour les subventions : sans ce
        # contrôle, chaque exécution ajoute un loyer de plus au même bail.
        if not conn.execute(
            "SELECT 1 FROM financial_flows WHERE type=? AND year=? AND from_id=?"
            " AND to_id=? AND source=?",
            (b["type"], b["year"], tenant_id, commune_id, b["source"])
        ).fetchone():
            conn.execute(
                "INSERT INTO financial_flows"
                " (type,year,amount,from_id,to_id,description,source)"
                " VALUES (?,?,?,?,?,?,?)",
                (b["type"], b["year"], b["amount"],
                 tenant_id, commune_id,
                 b["desc"], b["source"])
            )
        upsert_relation(conn,
            from_id=tenant_id, to_id=commune_id,
            rel_type="locataire_commune",
            source="cm",
            confidence="verified",
            metadata=json.dumps({"montant_annuel": b["amount"],
                                  "desc": b["desc"]})
        )
    print(f"  [cm] {len(BAUX)} baux importés")

def _import_transactions(conn, commune_id: int, seed: dict):
    """Transactions saisies à la main, avec la délibération qui les a votées.

    Le contrôle d'existence porte sur (date, référence cadastrale, prix) et non
    sur l'index UNIQUE de la table : celui-ci inclut `surface_bati`, NULL pour
    un terrain nu, et deux NULL ne sont jamais égaux pour SQLite — le OR IGNORE
    ne bloquait rien et la transaction était réinsérée à chaque exécution.
    """
    for t in seed.get("transactions_saisies") or []:
        if not conn.execute(
            "SELECT 1 FROM dvf_transactions WHERE date=? AND cadastre_ref=? AND price=?",
            (t["date"], t["cadastre_ref"], t["price"])
        ).fetchone():
            conn.execute(
                "INSERT INTO dvf_transactions"
                " (insee,date,cadastre_ref,section,numero,lieu_dit,"
                "  nature_mutation,nature_bien,surface_terrain,price,price_per_m2)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (t["insee"], t["date"], t["cadastre_ref"], t["section"], t["numero"],
                 t["lieu_dit"], t["nature_mutation"], t["nature_bien"],
                 t.get("surface_terrain"), t["price"], t.get("price_per_m2"))
            )

        d = t.get("deliberation")
        if not d:
            continue
        if conn.execute("SELECT 1 FROM events WHERE type='deliberation' AND title=?",
                        (d["title"],)).fetchone():
            continue
        conn.execute(
            "INSERT INTO events"
            " (type,date,title,content,source,source_url,metadata)"
            " VALUES (?,?,?,?,?,?,?)",
            ("deliberation", d["date"], d["title"], d.get("content"),
             d.get("source"), (seed.get("base_url") or COMMUNE_URL) + d.get("url_suffixe", ""),
             json.dumps(d.get("metadata") or {}))
        )
    print(f"  [cm] {len(seed.get('transactions_saisies') or [])} transaction(s) saisie(s)")
