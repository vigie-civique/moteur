"""
elections.py — Résultats électoraux par commune (Ministère de l'intérieur).

**Pourquoi.** La base savait *qui* avait été élu (relations `élu_cm`,
`candidat`) mais pas *avec combien de voix*, ni quelle participation : un seul
événement `election` y figurait. Or la légitimité d'un conseil se lit dans ces
chiffres — 81,3 % de participation et 55/45 entre deux listes ne racontent pas
la même chose qu'une élection à 40 % de votants.

**Format des fichiers.** CSV « large » : 18 colonnes de cadrage (inscrits,
votants, blancs, nuls…) puis un **bloc répété par liste** suffixé du rang
(« Voix 1 », « Sièges au CM 1 », « Voix 2 », …). Le nombre de blocs varie d'une
commune à l'autre, il faut donc les découvrir dynamiquement plutôt que de
figer des indices de colonnes.

Le code commune est donné sur 3 chiffres dans certains millésimes et sur 5 dans
d'autres : on reconstruit toujours `dep.zfill(2) + com.zfill(3)`.

**Périmètre livré : 2026 (tours 1 et 2).** Les fichiers 2020 existent aussi
(`elections-municipales-2020-resultats-1er-tour`) mais sont diffusés en `.txt`
avec un schéma différent, séparé entre communes de plus et de moins de
1 000 habitants — à traiter comme un second parseur, pas comme un paramètre.

Usage :
  python3 -m collectors.elections
  python3 -m collectors.elections --scrutin municipales-2026 --tour 1
  python3 -m collectors.elections --stats
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import urllib.request

from .archive import archive_fetch
from .config import COMMUNE_NAME, COMMUNES, COMMUNES_INSEE, HEADERS
from .db import get_conn

DATAGOUV_API = "https://www.data.gouv.fr/api/1/datasets"

# scrutin → tour → (slug data.gouv, préfixe du titre de ressource, date du tour)
SCRUTINS = {
    "municipales-2026": {
        1: ("elections-municipales-2026-resultats-du-premier-tour",
            "Municipales 2026 - Résultats - Communes", "2026-03-15"),
        2: ("elections-municipales-2026-resultats-du-second-tour",
            "Municipales 2026 - Résultats - Communes", "2026-03-22"),
    },
}

# Colonnes de cadrage : libellé du fichier → colonne en base.
CADRAGE = {
    "Inscrits": "inscrits", "Votants": "votants", "Abstentions": "abstentions",
    "Exprimés": "exprimes", "Blancs": "blancs", "Nuls": "nuls",
}


def ensure_tables(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS elections_resultats (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            scrutin     TEXT NOT NULL,
            tour        INTEGER NOT NULL,
            date_tour   TEXT,
            insee       TEXT NOT NULL,
            commune     TEXT,
            inscrits    INTEGER,
            votants     INTEGER,
            abstentions INTEGER,
            exprimes    INTEGER,
            blancs      INTEGER,
            nuls        INTEGER,
            event_id    INTEGER REFERENCES events(id) ON DELETE SET NULL,
            source      TEXT DEFAULT 'interieur',
            created_at  TEXT DEFAULT (datetime('now')),
            UNIQUE(scrutin, tour, insee)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS elections_listes (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            scrutin       TEXT NOT NULL,
            tour          INTEGER NOT NULL,
            insee         TEXT NOT NULL,
            rang          INTEGER NOT NULL,
            libelle       TEXT,
            libelle_abrege TEXT,
            nuance        TEXT,
            tete_de_liste TEXT,
            voix          INTEGER,
            pct_exprimes  REAL,
            sieges_cm     INTEGER,
            sieges_cc     INTEGER,
            created_at    TEXT DEFAULT (datetime('now')),
            UNIQUE(scrutin, tour, insee, rang)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_elec_insee"
                 " ON elections_resultats(insee, scrutin)")
    conn.commit()


def _int(v):
    if v is None:
        return None
    v = str(v).replace(" ", "").replace(" ", "").strip()
    return int(v) if v.isdigit() else None


def _pct(v):
    """« 55,09% » → 55.09."""
    if not v:
        return None
    v = str(v).replace("%", "").replace(",", ".").replace(" ", "").strip()
    try:
        return float(v)
    except ValueError:
        return None


def resolve_resource(slug: str, titre_prefixe: str) -> tuple[str, str | None]:
    req = urllib.request.Request(f"{DATAGOUV_API}/{slug}/", headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r:
        meta = json.load(r)
    for res in meta.get("resources", []):
        if (res.get("title") or "").startswith(titre_prefixe) and res.get("format") == "csv":
            return res["url"], res.get("last_modified")
    raise RuntimeError(
        f"ressource « {titre_prefixe}… » introuvable dans {slug} — titres : "
        f"{[r.get('title') for r in meta.get('resources', [])][:12]}")


def fetch_rows(slug: str, titre_prefixe: str,
               insee_list: list[str]) -> tuple[list[str], list[list[str]], str | None]:
    """(en-tête, lignes du périmètre, date de publication)."""
    url, last_modified = resolve_resource(slug, titre_prefixe)
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS),
                                timeout=240) as r:
        raw = r.read()
    # Ces fichiers sont en UTF-8 depuis 2026 ; les millésimes anciens sont en
    # cp1252. On tente dans cet ordre plutôt que de supposer.
    txt = None
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            txt = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if txt is None:
        raise RuntimeError("encodage du fichier de résultats non reconnu")

    reader = csv.reader(io.StringIO(txt), delimiter=";")
    header = next(reader)
    cible = set(insee_list)
    gardees = []
    for row in reader:
        if len(row) < 4:
            continue
        code = f"{row[0].strip().zfill(2)}{row[2].strip().zfill(3)}" \
            if len(row[2].strip()) <= 3 else row[2].strip()
        if code in cible:
            gardees.append(row)

    if gardees:
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(header)
        w.writerows(gardees)
        archive_fetch("interieur-elections", url, buf.getvalue().encode("utf-8"),
                      doc_type="csv", title=f"{titre_prefixe} — vallon",
                      metadata={"slug": slug, "last_modified": last_modified,
                                "lignes": len(gardees)})
    return header, gardees, last_modified


def _resume_listes(listes: list[dict]) -> str:
    """Résumé lisible d'un scrutin communal, pour le contenu de l'événement.

    Ce texte part dans `events_fts` : c'est lui qui rend un scrutin trouvable par
    le nom de la liste, et il alimente aussi l'index RAG.
    """
    parts = []
    for l in listes:
        nom = l["libelle"] or l["libelle_abrege"] or f"liste {l['rang']}"
        morceau = f"{nom} : {l['voix']} voix"
        if l["pct_exprimes"] is not None:
            morceau += f" ({l['pct_exprimes']} % des exprimés)"
        if l["sieges_cm"]:
            morceau += f", {l['sieges_cm']} sièges au conseil municipal"
        if l["sieges_cc"]:
            morceau += f" et {l['sieges_cc']} au conseil communautaire"
        parts.append(morceau)
    return " ; ".join(parts)


def _blocs_listes(header: list[str]) -> dict[int, dict[str, int]]:
    """Rang de liste → {champ: index de colonne}.

    Les blocs sont repérés par le suffixe numérique du libellé (« Voix 3 »),
    pas par une position : le nombre de listes varie d'une commune à l'autre et
    d'un fichier à l'autre.
    """
    champs = {
        "Libellé de liste": "libelle",
        "Libellé abrégé de liste": "libelle_abrege",
        "Nuance liste": "nuance",
        "Nuance": "nuance",
        "Nom candidat": "nom",
        "Prénom candidat": "prenom",
        "Voix": "voix",
        "% Voix/exprimés": "pct_exprimes",
        "Sièges au CM": "sieges_cm",
        "Sièges au CC": "sieges_cc",
    }
    blocs: dict[int, dict[str, int]] = {}
    for idx, col in enumerate(header):
        m = re.match(r"^(.*?)\s+(\d+)$", col.strip())
        if not m:
            continue
        base, rang = m.group(1), int(m.group(2))
        cle = champs.get(base)
        if cle:
            blocs.setdefault(rang, {})[cle] = idx
    return blocs


def import_rows(conn, scrutin: str, tour: int, date_tour: str,
                header: list[str], rows: list[list[str]]) -> dict:
    """Insert idempotent — résultats, listes, et un événement par commune."""
    idx_cadrage = {champ: header.index(lib)
                   for lib, champ in CADRAGE.items() if lib in header}
    blocs = _blocs_listes(header)
    res = {"communes": 0, "listes": 0, "events": 0}

    for row in rows:
        def cell(i):
            return row[i].strip() if i is not None and i < len(row) else None

        code = f"{row[0].strip().zfill(2)}{row[2].strip().zfill(3)}" \
            if len(row[2].strip()) <= 3 else row[2].strip()
        commune = COMMUNES.get(code, {}).get("nom") or row[3].strip()
        cadrage = {champ: _int(cell(i)) for champ, i in idx_cadrage.items()}

        # Listes réellement présentes pour cette commune : un bloc dont « Voix »
        # est vide correspond à un rang inexistant ici.
        listes = []
        for rang in sorted(blocs):
            b = blocs[rang]
            voix = _int(cell(b.get("voix")))
            if voix is None:
                continue
            tete = " ".join(x for x in (cell(b.get("prenom")), cell(b.get("nom"))) if x)
            listes.append({
                "rang": rang,
                "libelle": cell(b.get("libelle")),
                "libelle_abrege": cell(b.get("libelle_abrege")),
                "nuance": cell(b.get("nuance")),
                "tete_de_liste": tete or None,
                "voix": voix,
                "pct_exprimes": _pct(cell(b.get("pct_exprimes"))),
                "sieges_cm": _int(cell(b.get("sieges_cm"))),
                "sieges_cc": _int(cell(b.get("sieges_cc"))),
            })

        pct_part = (round(100 * cadrage["votants"] / cadrage["inscrits"], 2)
                    if cadrage.get("inscrits") and cadrage.get("votants") else None)
        titre = (f"Municipales {scrutin.split('-')[-1]} — {commune}, tour {tour}"
                 + (f" ({pct_part} % de participation)" if pct_part else ""))
        metadata = {"scrutin": scrutin, "tour": tour, "insee": code,
                    **cadrage, "participation_pct": pct_part,
                    "listes": listes}

        cur = conn.execute(
            "INSERT INTO events (type, date, title, content, source, source_url, metadata)"
            " SELECT 'election', ?, ?, ?, 'interieur', ?, ?"
            " WHERE NOT EXISTS (SELECT 1 FROM events WHERE type='election'"
            "   AND json_extract(metadata,'$.scrutin')=?"
            "   AND json_extract(metadata,'$.tour')=?"
            "   AND json_extract(metadata,'$.insee')=?)",
            (date_tour, titre, _resume_listes(listes),
             f"https://www.data.gouv.fr/fr/datasets/{SCRUTINS[scrutin][tour][0]}/",
             json.dumps(metadata, ensure_ascii=False), scrutin, tour, code))
        event_id = None
        if cur.rowcount:
            res["events"] += 1
        row_ev = conn.execute(
            "SELECT id FROM events WHERE type='election'"
            " AND json_extract(metadata,'$.scrutin')=?"
            " AND json_extract(metadata,'$.tour')=?"
            " AND json_extract(metadata,'$.insee')=?",
            (scrutin, tour, code)).fetchone()
        if row_ev:
            event_id = row_ev["id"]
            cible = conn.execute(
                "SELECT id FROM entities WHERE type='service' AND name=?",
                (f"Commune de {commune}",)).fetchone()
            if cible:
                conn.execute(
                    "INSERT OR IGNORE INTO event_entities (event_id, entity_id, role)"
                    " VALUES (?,?,'sujet')", (event_id, cible["id"]))

        conn.execute(
            "INSERT OR IGNORE INTO elections_resultats"
            " (scrutin, tour, date_tour, insee, commune, inscrits, votants,"
            "  abstentions, exprimes, blancs, nuls, event_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (scrutin, tour, date_tour, code, commune,
             cadrage.get("inscrits"), cadrage.get("votants"),
             cadrage.get("abstentions"), cadrage.get("exprimes"),
             cadrage.get("blancs"), cadrage.get("nuls"), event_id))
        res["communes"] += 1

        for l in listes:
            conn.execute(
                "INSERT OR IGNORE INTO elections_listes"
                " (scrutin, tour, insee, rang, libelle, libelle_abrege, nuance,"
                "  tete_de_liste, voix, pct_exprimes, sieges_cm, sieges_cc)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (scrutin, tour, code, l["rang"], l["libelle"], l["libelle_abrege"],
                 l["nuance"], l["tete_de_liste"], l["voix"], l["pct_exprimes"],
                 l["sieges_cm"], l["sieges_cc"]))
            res["listes"] += 1

    conn.commit()
    return res


def run(scrutin: str | None = None, tours: list[int] | None = None,
        insee_list: list[str] | None = None) -> dict:
    conn = get_conn()
    ensure_tables(conn)
    cibles = insee_list or COMMUNES_INSEE
    total = {}
    try:
        for nom_scrutin, tours_dispo in SCRUTINS.items():
            if scrutin and nom_scrutin != scrutin:
                continue
            for tour, (slug, prefixe, date_tour) in tours_dispo.items():
                if tours and tour not in tours:
                    continue
                try:
                    header, rows, _ = fetch_rows(slug, prefixe, cibles)
                except Exception as e:
                    print(f"  [elections] {nom_scrutin} tour {tour} : erreur — {e}")
                    continue
                if not rows:
                    # Normal quand tout le vallon est élu au premier tour.
                    print(f"  [elections] {nom_scrutin} tour {tour} : "
                          f"aucune commune du vallon concernée")
                    continue
                res = import_rows(conn, nom_scrutin, tour, date_tour, header, rows)
                total[f"{nom_scrutin}-t{tour}"] = res
                print(f"  [elections] {nom_scrutin} tour {tour} : "
                      f"{res['communes']} communes, {res['listes']} listes, "
                      f"{res['events']} nouveaux événements")
    finally:
        conn.close()
    return total


def stats():
    conn = get_conn()
    try:
        n = conn.execute("SELECT COUNT(*) FROM elections_resultats").fetchone()[0]
        print(f"elections_resultats : {n} communes×tours\n")
        for r in conn.execute("""
            SELECT scrutin, tour, commune, inscrits, votants,
                   ROUND(100.0*votants/inscrits, 1) part
            FROM elections_resultats ORDER BY scrutin, tour, part DESC
        """):
            print(f"  {r['scrutin']} t{r['tour']}  {(r['commune'] or '?'):<32}"
                  f"{r['inscrits'] or 0:>6} inscrits {r['votants'] or 0:>6} votants"
                  f"  {r['part'] or 0:>5} % participation")
        print()
        for r in conn.execute("""
            SELECT commune, l.libelle, l.voix, l.pct_exprimes, l.sieges_cm, l.sieges_cc
            FROM elections_listes l
            JOIN elections_resultats e
              ON e.insee=l.insee AND e.scrutin=l.scrutin AND e.tour=l.tour
            WHERE e.commune=? ORDER BY l.voix DESC
        """, (COMMUNE_NAME,)):
            print(f"  {COMMUNE_NAME} — {(r['libelle'] or '?')[:34]:<34} {r['voix']:>5} voix"
                  f"  {r['pct_exprimes'] or 0:>5} %  {r['sieges_cm'] or 0:>3} CM"
                  f"  {r['sieges_cc'] or 0:>2} CC")
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scrutin", choices=list(SCRUTINS))
    ap.add_argument("--tour", type=int, action="append")
    ap.add_argument("--insee", action="append")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()
    if args.stats:
        stats()
        return
    run(scrutin=args.scrutin, tours=args.tour, insee_list=args.insee)


if __name__ == "__main__":
    main()
