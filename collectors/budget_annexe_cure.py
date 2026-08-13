"""
budget_annexe_cure.py — Collecteur ciblé : un budget annexe communal
===================================================================
Reconstitue le coût d'investissement d'un budget annexe depuis l'open-data
DGFiP (balances comptables des communes), section investissement, 2019-2023.
Le budget suivi se déclare dans config/seed_local.json — sur l'instance de
référence c'était « CENTRE CULTUREL LASALLE » (réhabilitation de La Cure).

Source  : https://data.economie.gouv.fr  (datasets "balances-comptables-des-communes-en-AAAA")
Budget  : SIREN de la commune + lbudg déclaré (cbudg=3, nomenclature M4)
Cible   : comptes d'investissement
          - 20/21/23  immobilisations (travaux)        → section invest, sens "depense"
          - 13x       subventions d'équipement reçues  → section invest, sens "recette"
          - 16x       emprunts                          → section invest, sens "recette"
Stockage: table budget_annexe (entity_id de l'entité déclarée, source="DGFiP-balances").
          Idempotent : purge puis réinsère uniquement les lignes de cette source.

Usage :
  venv/bin/python -m collectors.budget_annexe_cure            # collecte + stocke
  venv/bin/python -m collectors.budget_annexe_cure --dry-run  # affiche sans stocker
  venv/bin/python -m collectors.budget_annexe_cure --summary  # synthèse coût réhab
"""
import argparse
import json
import urllib.parse
import urllib.request

from .db import get_conn

from .config import COMMUNE_SIREN as SIREN, HEADERS
# Le budget annexe suivi et l'entité à laquelle il se rapporte sont propres à
# une commune : ils se déclarent dans config/seed_local.json
# (`"budget_annexe": {"libelle": "…", "entite": "…"}`). Sans déclaration, le
# collecteur ne fait rien — il interrogeait sinon la DGFiP pour un budget
# « CENTRE CULTUREL LASALLE » qui n'existe pas ici, et rattachait le résultat
# à l'entité n° 3561, quelle qu'elle soit dans cette base.
def _declaration() -> dict:
    import json as _json
    from pathlib import Path as _Path
    chemin = _Path(__file__).resolve().parent.parent / "config" / "seed_local.json"
    try:
        return (_json.loads(chemin.read_text(encoding="utf-8")).get("budget_annexe")
                or {})
    except (FileNotFoundError, ValueError):
        return {}


LBUDG = _declaration().get("libelle", "")
SOURCE = "DGFiP-balances"
API_BASE = "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets"
YEARS = range(2019, 2024)

# Comptes d'investissement → (sens, libellé lisible)
COMPTES = {
    "1311": ("recette", "Subvention d'équipement — État"),
    "1312": ("recette", "Subvention d'équipement — Région"),
    "1313": ("recette", "Subvention d'équipement — Département"),
    "1314": ("recette", "Subvention d'équipement — Communes"),
    "1315": ("recette", "Subvention d'équipement — Groupements (EPCI)"),
    "1316": ("recette", "Subvention d'équipement — Autres EPL"),
    "1317": ("recette", "Subvention d'équipement — Fonds de concours / autres groupements"),
    "1318": ("recette", "Subvention d'équipement — Autres"),
    "1641": ("recette", "Emprunt en euros"),
    "2031": ("depense", "Frais d'études"),
    "2128": ("depense", "Aménagements de terrains"),
    "2135": ("depense", "Installations générales, agencements"),
    "2153": ("depense", "Travaux / installations à caractère spécifique (réhabilitation)"),
    "2183": ("depense", "Matériel de bureau et informatique"),
    "2184": ("depense", "Mobilier"),
    "2188": ("depense", "Autres immobilisations corporelles"),
    "2313": ("depense", "Immobilisations en cours — constructions"),
}
PREFIXES = ("13", "16", "20", "21", "23")


def fetch_year(year: int) -> list[dict]:
    dataset = f"balances-comptables-des-communes-en-{year}"
    out, offset = [], 0
    while True:
        params = urllib.parse.urlencode({
            "where": f'siren="{SIREN}" AND lbudg="{LBUDG}"',
            "limit": 100, "offset": offset,
        })
        url = f"{API_BASE}/{dataset}/records?{params}"
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
        except Exception as e:
            print(f"  [erreur] {year} offset={offset} : {e}")
            break
        recs = data.get("results", [])
        out += recs
        if len(recs) < 100:
            break
        offset += 100
    return out


def extract_invest(records: list[dict]) -> list[dict]:
    """Garde les comptes d'investissement, retourne le flux net de l'année."""
    lignes = []
    for r in records:
        compte = str(r.get("compte", ""))
        if not compte.startswith(PREFIXES):
            continue
        sens, libelle = COMPTES.get(compte, (None, None))
        if sens is None:
            # compte d'invest non répertorié → on déduit le sens par préfixe
            sens = "recette" if compte.startswith(("13", "16")) else "depense"
            libelle = f"Compte {compte}"
        deb = float(r.get("obnetdeb") or 0)
        cre = float(r.get("obnetcre") or 0)
        montant = deb if sens == "depense" else cre
        if montant == 0:
            continue
        lignes.append({
            "compte": compte, "sens": sens, "libelle": libelle, "montant": round(montant, 2),
        })
    return lignes


def collect(dry_run: bool = False) -> dict:
    decl = _declaration()
    if not decl.get("libelle") or not decl.get("entite"):
        print("[budget_annexe] aucun budget annexe déclaré dans seed_local.json "
              "(clés « libelle » et « entite ») — rien à collecter.")
        return {"_inserted": 0}

    conn = get_conn()
    from .db import upsert_entity
    CURE_ENTITY_ID = upsert_entity(conn, type="service", name=decl["entite"],
                                   confidence="verified")
    report = {}
    try:
        if not dry_run:
            conn.execute(
                "DELETE FROM budget_annexe WHERE entity_id=? AND source=?",
                (CURE_ENTITY_ID, SOURCE),
            )
        total_inserted = 0
        for year in YEARS:
            recs = fetch_year(year)
            lignes = extract_invest(recs)
            report[year] = lignes
            for lg in lignes:
                print(f"  {year} {lg['sens']:7} c.{lg['compte']:5} {lg['montant']:>11.0f} €  {lg['libelle']}")
                if not dry_run:
                    conn.execute(
                        """INSERT INTO budget_annexe
                           (entity_id, year, section, sens, compte, libelle, montant, source, confidence)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (CURE_ENTITY_ID, year, "investissement", lg["sens"],
                         lg["compte"], lg["libelle"], lg["montant"], SOURCE, "verified"),
                    )
                    total_inserted += 1
        if not dry_run:
            conn.commit()
        report["_inserted"] = total_inserted
        return report
    finally:
        conn.close()


def summary(report: dict) -> None:
    depenses = recettes = 0.0
    par_compte = {}
    for year, lignes in report.items():
        if not isinstance(lignes, list):
            continue
        for lg in lignes:
            if lg["sens"] == "depense":
                depenses += lg["montant"]
            else:
                recettes += lg["montant"]
            par_compte.setdefault(lg["compte"], 0.0)
            par_compte[lg["compte"]] += lg["montant"]
    print("\n=== SYNTHÈSE — coût de réhabilitation La Cure (2019-2023) ===")
    print(f"  Total dépenses d'investissement (travaux+équipement) : {depenses:>12.0f} €")
    print(f"  Total recettes d'investissement (subv.+emprunt)      : {recettes:>12.0f} €")
    print("  Détail travaux (compte 2153) cumulé = coût des travaux de réhabilitation.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Collecteur budget annexe La Cure (réhabilitation)")
    ap.add_argument("--dry-run", action="store_true", help="Affiche sans stocker")
    ap.add_argument("--summary", action="store_true", help="Affiche la synthèse coût réhab")
    args = ap.parse_args()

    print(f"[budget_annexe_cure] budget « {LBUDG} » — DGFiP balances {YEARS.start}-{YEARS.stop-1}")
    rep = collect(dry_run=args.dry_run)
    if not args.dry_run:
        print(f"\n✓ {rep['_inserted']} lignes d'investissement stockées (source={SOURCE}).")
    if args.summary or args.dry_run:
        summary(rep)
