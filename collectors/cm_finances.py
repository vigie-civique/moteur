"""
cm_finances.py — Extraction financière depuis le contenu des CR du conseil municipal.

Les CR contiennent des flux financiers réguliers non encore structurés (surtout
avant 2024). Ce collecteur les extrait du texte des événements (deliberation /
conseil_municipal) et les insère dans `financial_flows`, en RÉUTILISANT les
entités existantes (résolveur de noms — pas de doublon) plutôt qu'en les recréant.

Extraction automatique (haute confiance, motif régulier) :
  - subventions aux associations : « attribuer à X une subvention de N € »

Détection + rapport (pour curation manuelle, motifs moins réguliers ou enjeux
de nommage de particuliers) :
  - cessions de patrimoine, baux/loyers, aides façade

Idempotent : dédoublonne contre les flux déjà présents (type+année+montant+bénéficiaire).

Usage :
  python3 -m collectors.cm_finances --dry-run     # aperçu (résolution + doublons)
  python3 -m collectors.cm_finances               # insère les subventions résolues
  python3 -m collectors.cm_finances --report      # + rapport cessions/baux/aides
"""
from __future__ import annotations

import argparse
import re
import unicodedata

from .db import transaction, get_conn, upsert_entity

COMMUNE_ID = 63


def _clean_benef(name: str) -> str:
    """Nettoie un nom de bénéficiaire extrait pour créer une entité lisible."""
    s = _deapos(name)
    s = re.sub(r"[«»\"']", "", s).strip()
    s = re.sub(r"^(l['’]?\s*association|association|amicale|club|l['’])\s+", "", s, flags=re.I).strip()
    s = re.sub(r"\s+", " ", s)
    return s[:80] or name

# ── Résolveur de noms → entité existante ───────────────────────────────────────

_STOP = {"de", "des", "du", "la", "le", "les", "l", "d", "et", "a", "au", "aux",
         "pour", "association", "asso"}

def _deapos(s: str) -> str:
    return s.replace("’", "'").replace("‘", "'").replace("`", "'")


# Alias pour les cas non résolus automatiquement (nom extrait → nom d'entité exact existant).
ALIASES = {
    "ape": "ASSOCIATION DE PARENTS D'ELEVES DES ECOLES PUBLIQUES DE LASALLE",
    "association des parents d'eleves": "ASSOCIATION DE PARENTS D'ELEVES DES ECOLES PUBLIQUES DE LASALLE",
    "art'scene": "L'ART SCENE",
    "art scene": "L'ART SCENE",
    "brico cafe": "LE BRICOCAFE LASALLOIS",
    "jardins d'emeraude": "LES JARDINS D'EMERAUDE JARDINS FAMILIAUX LASALLOIS",
    "les jardins d'emeraude": "LES JARDINS D'EMERAUDE JARDINS FAMILIAUX LASALLOIS",
    # L'apostrophe est un séparateur de tokens : « VIVALTO » donne {vivalto} et
    # « VIV'ALTO » donne {viv, alto}. Aucune intersection, donc aucun
    # rapprochement possible par similarité — seul un alias les réunit.
    "vivalto": "VIV'ALTO",
    # Le CR de 2025 écrit « Film », celui de 2024 « Filme » : un caractère
    # d'écart suffit à faire tomber la similarité sous le seuil (0,5 < 0,6).
    "la caravane film": "LA CARAVANE FILME",
}


def _norm_tokens(s: str) -> set[str]:
    s = _deapos(s)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", " ", s).lower()
    return {t for t in s.split() if t and t not in _STOP and len(t) > 1}


class Resolver:
    def __init__(self, conn):
        self.ents = []
        for r in conn.execute(
            "SELECT id,name,type FROM entities WHERE type IN ('association','business','service','place')"
        ):
            self.ents.append((r["id"], r["name"], r["type"], _norm_tokens(r["name"])))
        self.name_of = {eid: name for eid, name, typ, _ in self.ents}
        self.type_of = {eid: typ for eid, name, typ, _ in self.ents}
        # Index par nom exact. Une association et son établissement SIRENE portent
        # souvent le même nom (« LA SOIERIE ») : sans arbitrage, c'est la dernière
        # ligne rendue par le SELECT qui gagnait — le business, la moitié du temps.
        self.by_name = {}
        for eid, name, typ, _ in self.ents:
            key = _deapos(name).strip().lower()
            prec = self.by_name.get(key)
            if prec is None or self._prefere(eid, prec):
                self.by_name[key] = eid

        # Entités déjà bénéficiaires de subventions → à privilégier (cohérence d'affichage
        # malgré les doublons d'entités préexistants).
        self.canon = []
        for r in conn.execute(
            "SELECT DISTINCT te.id, te.name FROM financial_flows ff JOIN entities te ON te.id=ff.to_id "
            "WHERE ff.type='subvention' AND te.id IS NOT NULL"
        ):
            self.canon.append((r["id"], r["name"], _norm_tokens(r["name"])))

    def _prefere(self, eid: int, contre: int) -> bool:
        """Une association l'emporte sur toute autre forme ; sinon la plus ancienne."""
        a, b = self.type_of.get(eid), self.type_of.get(contre)
        if (a == "association") != (b == "association"):
            return a == "association"
        return eid < contre

    def add(self, eid: int, name: str, typ: str = "association"):
        """Déclare une entité créée après le chargement du résolveur.

        Sans ça, un import qui crée une entité puis rencontre le même nom
        autrement orthographié plus loin dans sa propre boucle la recrée : c'est
        exactement ainsi que « La Boule lasalloise » (2025) et « La Boule
        Lasalloise » (2024) sont devenues deux associations.
        """
        toks = _norm_tokens(name)
        self.ents.append((eid, name, typ, toks))
        self.by_name[_deapos(name).strip().lower()] = eid
        self.name_of[eid] = name
        self.type_of[eid] = typ
        self.canon.append((eid, name, toks))

    def _best(self, et, pool):
        """Meilleure entité du pool pour ces tokens, ou None. Retourne (id, nom)."""
        best = None
        for eid, en, ntok in pool:
            inter = et & ntok
            if not inter:
                continue
            cover = len(inter) / len(et)
            score = cover + (0.5 if et <= ntok else 0)
            # Deux départages, tous deux constatés à l'exécution :
            #  - à nom égal, une association et son établissement SIRENE coexistent
            #    souvent (« LA SOIERIE » ×2). Une subvention communale va à
            #    l'association : la rattacher au business serait faux.
            #  - à tout égal, garder l'id le plus ancien — les doublons sont créés
            #    après la fiche d'origine, jamais avant.
            asso = 1 if self.type_of.get(eid) == "association" else 0
            cand = (score, cover, asso, -len(ntok), -eid, eid, en)
            if best is None or cand > best:
                best = cand
        if not best or best[1] < 0.6:
            return None
        return best[5], best[6]

    def resolve(self, name: str):
        akey = re.sub(r"\s+", " ", unicodedata.normalize("NFKD", _deapos(name))
                      .encode("ascii", "ignore").decode()).strip().lower()
        if akey in ALIASES:
            name = ALIASES[akey]
        key = _deapos(name).strip().lower()
        if key in self.by_name:
            eid = self.by_name[key]
            return eid, self.name_of.get(eid, name)
        et = _norm_tokens(name)
        if not et:
            return None, name
        # 1) privilégier une entité déjà subventionnée ; 2) sinon toute entité éligible.
        best = self._best(et, self.canon)
        if best is None:
            best = self._best(et, [(e[0], e[1], e[3]) for e in self.ents])
        if best:
            return best
        return None, name


# ── Motifs d'extraction ────────────────────────────────────────────────────────

SUBV_RE = re.compile(
    r"attribuer\s+(?:à|au|aux)\s+(?:l['’]|la\s+|le\s+)?(.{2,55}?)\s+"
    r"une\s+(?:subvention|avance[^.]{0,20}?subvention|aide)\s+"
    r"(?:exceptionnelle\s+)?(?:par anticipation\s+)?de\s+([\d\s  ]{2,12})\s*€",
    re.I,
)
CESSION_TITLE = re.compile(r"CESSION|VENTE.*(TERRAIN|PARCELLE|DOMAINE)|ALI[EÉ]NATION|D[EÉ]CLASSEMENT.*VENTE", re.I)
BAIL_RE = re.compile(r"loyer[^.]{0,40}?de\s+([\d\s  ]{2,10}(?:[,.]\d{2})?)\s*€[^.]{0,15}?(mois|an|annuel)", re.I)
AIDE_TITLE = re.compile(r"AIDE.*(FA[CÇ]ADE|R[EÉ]NOVATION)|RAVALEMENT", re.I)
AMOUNT_RE = re.compile(r"([\d][\d\s  ]{2,10}(?:[,.]\d{2})?)\s*€")


def _to_int(s: str) -> int:
    return int(re.sub(r"[^\d]", "", s) or 0)


def _to_float(s: str) -> float:
    s = re.sub(r"[^\d,.]", "", s).replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


# ── Extraction ─────────────────────────────────────────────────────────────────

def extract_subventions(conn):
    """Retourne [(year, beneficiary_raw, amount, event_id)] dédoublonné par (year,benef)."""
    out, seen = [], set()
    for r in conn.execute(
        "SELECT id,date,content FROM events WHERE type IN ('deliberation','conseil_municipal') "
        "AND content IS NOT NULL"
    ):
        year = int((r["date"] or "0")[:4]) or None
        if not year:
            continue
        for m in SUBV_RE.finditer(r["content"]):
            benef = re.sub(r"\s+", " ", m.group(1)).strip(" ,.")
            amount = _to_int(m.group(2))
            if amount <= 0 or amount > 200000:
                continue
            key = (year, benef.lower())
            if key in seen:
                continue
            seen.add(key)
            out.append((year, benef, amount, r["id"]))
    return out


def flow_exists(conn, ftype, year, amount, to_id) -> bool:
    return conn.execute(
        "SELECT 1 FROM financial_flows WHERE type=? AND year=? AND amount=? AND to_id=?",
        (ftype, year, amount, to_id),
    ).fetchone() is not None


def run_subventions(commit: bool):
    conn = get_conn()
    res = Resolver(conn)
    subs = extract_subventions(conn)
    print(f"[subventions] {len(subs)} extraites du contenu CR\n")
    to_insert, to_create, dupes = [], [], 0
    for year, benef, amount, eid in subs:
        to_id, matched = res.resolve(benef)
        if to_id is None:
            to_create.append((year, amount, benef, eid))          # nouvelle asso à créer
            continue
        if flow_exists(conn, "subvention", year, amount, to_id):
            dupes += 1
            continue
        to_insert.append((year, amount, to_id, matched, benef, eid))
    from collections import Counter
    allyears = [x[0] for x in to_insert] + [x[0] for x in to_create]
    print(f"  à insérer : {len(to_insert)}  |  déjà en base : {dupes}  |  entités à créer : {len(to_create)}")
    print("  nouveaux par année :", dict(sorted(Counter(allyears).items())))
    if to_create:
        print("  ⚠ bénéficiaires nouveaux (entité créée) :",
              sorted({f'{_clean_benef(b)} ({y})' for y, a, b, e in to_create}))
    print("  échantillon à insérer :")
    for year, amount, to_id, matched, benef, eid in to_insert[:15]:
        print(f"    {year}  {amount:>6} €  {benef[:26]:26} → #{to_id} {matched[:30]}")
    conn.close()

    if not commit:
        print("\n(dry-run — relancer sans --dry-run pour insérer)")
        return

    def _ins(w, year, amount, to_id, eid):
        w.execute(
            "INSERT INTO financial_flows (type,year,amount,from_id,to_id,event_id,description,source,confidence) "
            "VALUES ('subvention',?,?,?,?,?,?,?, 'verified')",
            (year, amount, COMMUNE_ID, to_id, eid,
             f"Subvention communale {year} (extraite du CR)", f"CR CM {year}"),
        )
        w.execute(
            "INSERT OR IGNORE INTO relations (from_id,to_id,relation_type,source,confidence,metadata) "
            "VALUES (?,?,'subventionné','cm_finances','verified',?)",
            (COMMUNE_ID, to_id, f'{{"year": {year}, "amount": {amount}}}'),
        )

    ins = created = 0
    with transaction() as w:
        for year, amount, to_id, matched, benef, eid in to_insert:
            _ins(w, year, amount, to_id, eid); ins += 1
        for year, amount, benef, eid in to_create:
            new_id = upsert_entity(w, type="association", name=_clean_benef(benef), confidence="verified")
            w.execute("INSERT OR IGNORE INTO associations (entity_id) VALUES (?)", (new_id,))
            if not flow_exists_conn(w, year, amount, new_id):
                _ins(w, year, amount, new_id, eid); ins += 1
            created += 1
    print(f"\n✓ {ins} subventions insérées ({created} nouvelles entités créées).")


def flow_exists_conn(conn, year, amount, to_id) -> bool:
    return conn.execute(
        "SELECT 1 FROM financial_flows WHERE type='subvention' AND year=? AND amount=? AND to_id=?",
        (year, amount, to_id),
    ).fetchone() is not None


def report_others():
    """Détection (sans insertion) des cessions / baux / aides pour curation."""
    conn = get_conn()
    print("\n=== CESSIONS de patrimoine détectées dans les CR (à curer) ===")
    for r in conn.execute(
        "SELECT id,date,title,content FROM events WHERE type IN ('deliberation','conseil_municipal') "
        "AND content IS NOT NULL"
    ):
        if not CESSION_TITLE.search(r["title"] or ""):
            continue
        amts = [a for a in (AMOUNT_RE.findall(r["content"] or "")) if _to_float(a) > 500]
        print(f"  {r['date']} #{r['id']} {(r['title'] or '')[:52]}  montants≈ {amts[:4]}")
    print("\n=== BAUX / loyers détectés ===")
    for r in conn.execute(
        "SELECT id,date,title,content FROM events WHERE type IN ('deliberation','conseil_municipal') "
        "AND content IS NOT NULL AND content LIKE '%loyer%'"
    ):
        for m in BAIL_RE.finditer(r["content"] or ""):
            print(f"  {r['date']} #{r['id']} loyer {m.group(1)} €/{m.group(2)}  — {(r['title'] or '')[:40]}")
    print("\n=== AIDES façade détectées ===")
    for r in conn.execute(
        "SELECT id,date,title FROM events WHERE type IN ('deliberation','conseil_municipal') AND title IS NOT NULL"
    ):
        if AIDE_TITLE.search(r["title"] or ""):
            print(f"  {r['date']} #{r['id']} {r['title'][:60]}")
    conn.close()


def main():
    ap = argparse.ArgumentParser(description="Extraction financière depuis les CR du CM.")
    ap.add_argument("--dry-run", action="store_true", help="Aperçu sans insertion")
    ap.add_argument("--report", action="store_true", help="Rapport cessions/baux/aides (curation)")
    args = ap.parse_args()
    run_subventions(commit=not args.dry_run)
    if args.report:
        report_others()


if __name__ == "__main__":
    main()
