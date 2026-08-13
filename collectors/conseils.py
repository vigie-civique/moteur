"""
conseils.py — Séances et délibérations : conseil municipal et conseil communautaire.

Remplace la chaîne écrite pour les comptes rendus HTML d'une commune en
particulier. Le catalogue des procès-verbaux vient du connecteur déclaré par
l'instance ; leur lecture est faite ici, et l'analyse du texte dans
`pv_parsers`. Aucun des trois n'a besoin de savoir de quelle commune il s'agit.

Ce qui est publié : le TITRE de chaque délibération, sa date, son vote et le
lien vers le procès-verbal. Le corps du texte est conservé mais reste matériau
d'atelier.

Ce qui n'est pas publié faute d'être connu : quand le document ne se laisse pas
découper — texte suivi dont les titres ne se distinguent que par la graisse — la
séance est enregistrée avec son texte intégral et `decoupage_delib: false`.
Fabriquer des délibérations en devinant produirait des actes qui n'existent pas.

Usage :
  python3 -m collectors.conseils --portee commune --catalogue
  python3 -m collectors.conseils --portee commune --depuis 2024 --commit
  python3 -m collectors.conseils --portee epci --commit
  python3 -m collectors.conseils --url <pdf> --date 2026-06-05 --commit
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

import pdfplumber

from .archive import archive_fetch
from .config import COMMUNE_NAME, EPCI_NOM, EPCI_SIREN, HEADERS, ROOT
from .cm_parser import link_persons_to_event
from .connecteurs import charger
from .db import transaction, upsert_entity
from .pv_parsers import deliberations, presences

PDF_DIR = ROOT / "data" / "pv"

# En dessous : PDF scanné sans couche texte → relève de cm_ocr, pas d'ici.
MIN_TEXT_CHARS = 400

# Ce qui change entre les deux portées : le type d'événement, l'ordre d'écriture
# des noms dans le document, et l'intitulé de la séance. Rien d'autre.
PORTEES = {
    "commune": {
        "seance": "conseil_municipal",
        "delib": "deliberation",
        "ordre_noms": "prenom_nom",
        "titre": "Conseil municipal du {date}",
    },
    "epci": {
        "seance": "conseil_communautaire",
        "delib": "deliberation_cc",
        "ordre_noms": "nom_prenom",
        "titre": "Conseil communautaire du {date}",
    },
}


# ── Récupération ─────────────────────────────────────────────────────────────

def _url_http(url: str) -> str:
    """Ré-encode le chemin d'une URL pour urllib.

    Les sites déposent des fichiers dont le nom porte des accents
    (`Séance-du-23-juillet-2018.pdf`). urllib transmet le chemin en ASCII et
    lève `'ascii' codec can't encode character` : vingt-et-un documents étaient
    comptés « inaccessibles » alors qu'ils étaient bien en ligne.
    """
    parts = urllib.parse.urlsplit(url)
    chemin = urllib.parse.quote(urllib.parse.unquote(parts.path), safe="/%")
    return urllib.parse.urlunsplit(parts._replace(path=chemin))


def telecharger(url: str, source: str = "") -> Path | None:
    """PDF en cache local. Retélécharge seulement s'il est absent."""
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    nom = urllib.parse.unquote(Path(urllib.parse.urlparse(url).path).name)
    cible = PDF_DIR / re.sub(r"[^A-Za-z0-9._-]", "_", nom)
    if cible.exists() and cible.stat().st_size > 0:
        return cible
    try:
        req = urllib.request.Request(_url_http(url), headers=HEADERS)
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
        if not raw.startswith(b"%PDF-"):
            print(f"  [pv][skip] pas un PDF : {url}")
            return None
        cible.write_bytes(raw)
        archive_fetch(source or "site", url, raw, "application/pdf", 200,
                      doc_type="pdf", title=nom)
        return cible
    except Exception as e:
        print(f"  [pv][erreur] {url} → {e}")
        return None


def texte_pdf(chemin: Path) -> str:
    try:
        with pdfplumber.open(str(chemin)) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception as e:
        print(f"  [pv][erreur] lecture {chemin.name} → {e}")
        return ""


# ── Écriture ─────────────────────────────────────────────────────────────────

def enregistrer_seance(conn, doc, portee: str, meta_sup: dict | None = None) -> int:
    """Événement ombrelle d'une séance. Idempotent sur l'URL du document.

    L'identité porte sur `source_url` et non sur la date : deux séances peuvent
    tomber le même jour, et le titre est reconstruit.
    """
    p = PORTEES[portee]
    meta = {"libelle_source": doc.libelle, **(meta_sup or {})}
    if portee == "epci" and EPCI_SIREN:
        meta["siren_epci"] = EPCI_SIREN
    row = conn.execute(
        "SELECT id FROM events WHERE type=? AND source_url=?",
        (p["seance"], doc.url)).fetchone()
    if row:
        conn.execute("UPDATE events SET date=?, metadata=? WHERE id=?",
                     (doc.date, json.dumps(meta, ensure_ascii=False), row["id"]))
        return row["id"]
    cur = conn.execute(
        "INSERT INTO events (type,date,title,source,source_url,metadata)"
        " VALUES (?,?,?,?,?,?)",
        (p["seance"], doc.date, p["titre"].format(date=doc.date), doc.source,
         doc.url, json.dumps(meta, ensure_ascii=False)))
    return cur.lastrowid


def enregistrer_deliberation(conn, doc, portee: str, delib: dict) -> int:
    """Une délibération = un événement.

    Identité : le numéro d'acte quand le document en porte un — il est unique et
    vient du document lui-même ; sinon le couple (date, numéro de séance) ;
    sinon (date, titre). Le titre seul ne peut pas servir de clé : « Questions
    diverses » revient à chaque séance.
    """
    p = PORTEES[portee]
    meta = {k: delib[k] for k in ("categorie", "tags", "vote", "montants",
                                  "numero_seance", "numero_acte", "regime")}
    if portee == "epci":
        meta["instance"] = EPCI_NOM

    if delib.get("numero_acte"):
        row = conn.execute(
            "SELECT id FROM events WHERE type=?"
            " AND json_extract(metadata,'$.numero_acte')=?",
            (p["delib"], delib["numero_acte"])).fetchone()
    elif delib.get("numero_seance"):
        row = conn.execute(
            "SELECT id FROM events WHERE type=? AND date=?"
            " AND json_extract(metadata,'$.numero_seance')=?",
            (p["delib"], doc.date, delib["numero_seance"])).fetchone()
    else:
        row = conn.execute(
            "SELECT id FROM events WHERE type=? AND date=? AND title=?",
            (p["delib"], doc.date, delib["titre"])).fetchone()

    if row:
        conn.execute(
            "UPDATE events SET date=?, title=?, content=?, metadata=?, source=?,"
            " source_url=? WHERE id=?",
            (doc.date, delib["titre"], delib["texte"],
             json.dumps(meta, ensure_ascii=False), doc.source, doc.url, row["id"]))
        return row["id"]
    cur = conn.execute(
        "INSERT INTO events (type,date,title,content,source,source_url,metadata)"
        " VALUES (?,?,?,?,?,?,?)",
        (p["delib"], doc.date, delib["titre"], delib["texte"], doc.source,
         doc.url, json.dumps(meta, ensure_ascii=False)))
    return cur.lastrowid


def traiter(conn, doc, portee: str, verbose: bool = True) -> dict:
    """Télécharge, lit et enregistre un procès-verbal."""
    p = PORTEES[portee]
    chemin = telecharger(doc.url, doc.source)
    if chemin is None:
        return {"statut": "inaccessible", "delibs": 0}

    texte = texte_pdf(chemin)
    if len(texte) < MIN_TEXT_CHARS:
        # Pas d'OCR ici : `cm_ocr --pdf-url … --date …` est fait pour ça, et le
        # signaler vaut mieux que produire une séance vide qui passe pour lue.
        enregistrer_seance(conn, doc, portee)
        return {"statut": "sans_couche_texte", "delibs": 0}

    delibs = deliberations(texte)
    pres = presences(texte, p["ordre_noms"])
    seance_id = enregistrer_seance(conn, doc, portee,
                                   {"nb_deliberations": len(delibs), **pres})

    if not delibs:
        conn.execute(
            "UPDATE events SET content=?, metadata=json_patch(metadata, ?)"
            " WHERE id=?",
            (texte, json.dumps({"decoupage_delib": False}, ensure_ascii=False),
             seance_id))

    link_persons_to_event(conn, seance_id, pres["presents"], "présent")
    link_persons_to_event(conn, seance_id, pres["absents"], "absent")
    for d in delibs:
        eid = enregistrer_deliberation(conn, doc, portee, d)
        link_persons_to_event(conn, eid, pres["presents"], "présent")

    if verbose:
        regime = delibs[0]["regime"] if delibs else "non découpé"
        print(f"  [pv] {doc.date} — {len(delibs)} délibérations ({regime}), "
              f"{len(pres['presents'])} présents, {len(pres['pouvoirs'])} pouvoirs")
    return {"statut": "ok", "delibs": len(delibs)}


# ── Point d'entrée ───────────────────────────────────────────────────────────

def collecter(portee: str = "commune", depuis: str | None = None,
              limit: int = 0, commit: bool = True,
              catalogue_seul: bool = False) -> None:
    instance = COMMUNE_NAME if portee == "commune" else (EPCI_NOM or "EPCI")
    print(f"\n[conseils] {instance} — catalogue des procès-verbaux")

    documents = charger().catalogue_pv(portee)
    print(f"  {len(documents)} procès-verbaux catalogués"
          + (f" ({documents[-1].date} → {documents[0].date})" if documents else ""))
    if depuis:
        documents = [d for d in documents if d.date >= depuis]
        print(f"  {len(documents)} depuis {depuis}")
    if limit:
        documents = documents[:limit]

    if not commit:
        for d in documents[:20]:
            print(f"    {d.date}  {d.url.split('/')[-1]}")
        print("  [dry-run] rien écrit")
        return

    if portee == "epci" and EPCI_NOM:
        with transaction() as conn:
            upsert_entity(conn, type="service", name=EPCI_NOM,
                          confidence="verified")

    resume = {"ok": 0, "sans_couche_texte": 0, "inaccessible": 0, "delibs": 0}
    # Une transaction PAR document, et non une seule pour tout le corpus : lire
    # deux cents PDF prend une vingtaine de minutes, pendant lesquelles une
    # transaction unique garde le verrou d'écriture et fait échouer tout autre
    # collecteur sur « database is locked » — huit étapes perdues d'un coup lors
    # du premier portage.
    for doc in documents:
        with transaction() as conn:
            if catalogue_seul:
                enregistrer_seance(conn, doc, portee)
                resume["ok"] += 1
                continue
            r = traiter(conn, doc, portee)
            resume[r["statut"]] += 1
            resume["delibs"] += r["delibs"]

    print(f"\n[conseils] {resume['ok']} séances lues, {resume['delibs']} "
          f"délibérations, {resume['sans_couche_texte']} sans couche texte "
          f"(→ cm_ocr), {resume['inaccessible']} inaccessibles")


def import_conseil_municipal() -> None:
    """Entrée appelée par run_all (step `cm`)."""
    collecter("commune")


def import_conseil_communautaire() -> None:
    """Entrée appelée par run_all (step `cc_epci`)."""
    collecter("epci")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Séances et délibérations")
    ap.add_argument("--portee", choices=["commune", "epci"], default="commune")
    ap.add_argument("--depuis", help="AAAA ou AAAA-MM-JJ")
    ap.add_argument("--limit", "-n", type=int, default=0)
    ap.add_argument("--catalogue", action="store_true",
                    help="enregistrer les séances sans lire les PDF")
    ap.add_argument("--commit", action="store_true", help="écrire en base")
    ap.add_argument("--url", help="traiter un seul document (URL du PDF)")
    ap.add_argument("--date", help="date du document passé par --url")
    args = ap.parse_args()

    if args.url:
        if not args.date:
            ap.error("--url exige --date")
        from .connecteurs.base import DocumentPublie
        doc = DocumentPublie(date=args.date, url=args.url, libelle=args.date,
                             source=urllib.parse.urlparse(args.url).netloc)
        if not args.commit:
            raise SystemExit("  [dry-run] rien écrit")
        with transaction() as conn:
            print(traiter(conn, doc, args.portee))
    else:
        depuis = args.depuis
        if depuis and len(depuis) == 4:
            depuis = f"{depuis}-01-01"
        collecter(args.portee, depuis, args.limit, args.commit, args.catalogue)
