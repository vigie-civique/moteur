"""
conseils.py — Séances et délibérations : conseil municipal et conseil communautaire.

Remplace la chaîne écrite pour les comptes rendus HTML d'une commune en
particulier. Le catalogue des procès-verbaux vient du connecteur déclaré par
l'instance ; leur lecture est faite ici, et l'analyse du texte dans
`pv_parsers`. Aucun des trois n'a besoin de savoir de quelle commune il s'agit.

Le format du document n'est pas non plus une affaire de commune : PDF, page
HTML, traitement de texte ou texte brut sont lus de la même façon — cf.
`texte_document.py` — et rendent le même texte à `pv_parsers`. Ce lecteur a
longtemps refusé tout ce qui n'était pas un PDF, et une séance entière
manquait quand la collectivité publiait son compte rendu en page web.

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
import shutil
import subprocess
from pathlib import Path

import pdfplumber

from .archive import archive_fetch
from .config import (COMMUNE_NAME, COMMUNE_SIREN, EPCI_NOM, EPCI_SIREN,
                     HEADERS, ROOT)
from .cm_parser import link_persons_to_event
from .connecteurs import charger
from .connecteurs.base import date_fr
from .db import transaction, upsert_entity
from .pv_parsers import (acte_unique, deliberations, presences,
                         reference_actes)
from .texte_document import format_de, texte_de

PDF_DIR = ROOT / "data" / "pv"

# En dessous : PDF scanné sans couche texte → relève de cm_ocr, pas d'ici.
MIN_TEXT_CHARS = 400

# Ce qui change entre les deux portées : le type d'événement, l'ordre d'écriture
# des noms dans le document, et l'intitulé de la séance. Rien d'autre.
PORTEES = {
    "commune": {
        "seance": "conseil_municipal",
        "delib": "deliberation",
        "titre": "Conseil municipal du {date}",
    },
    "epci": {
        "seance": "conseil_communautaire",
        "delib": "deliberation_cc",
        "titre": "Conseil communautaire du {date}",
    },
}

# Comment le document écrit les noms des présents. Trois conventions observées,
# et c'est une propriété du DOCUMENT, pas du moteur : elle se déclare dans
# config/instance.json, clé `format_pv`.
#   prenom_nom    « Delphine BARTHÈS »        (défaut)
#   nom_prenom    « BARTHÈS Delphine »
#   civilite_nom  « Mme BARTHÈS », sans prénom
ORDRE_NOMS_DEFAUT = {"commune": "prenom_nom", "epci": "nom_prenom"}


def _ordre_noms(portee: str) -> str:
    from .config import FORMAT_PV
    return (FORMAT_PV.get(portee) or {}).get("ordre_noms",
                                            ORDRE_NOMS_DEFAUT[portee])


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


MIME = {"pdf": "application/pdf", "html": "text/html",
        "office": "application/octet-stream", "texte": "text/plain"}


def _cible_cache(url: str) -> Path:
    nom = urllib.parse.unquote(Path(urllib.parse.urlparse(url).path).name)
    return PDF_DIR / (re.sub(r"[^A-Za-z0-9._-]", "_", nom) or "document")


def telecharger(url: str, source: str = "") -> tuple[bytes, str] | None:
    """Rend le contenu d'un document et son format, ou rien.

    Le format vient des OCTETS, pas de l'adresse : un fichier retiré est souvent
    servi sous son ancienne adresse en `.pdf` par une page d'erreur, qu'on
    enregistrerait sinon comme un procès-verbal vide.

    Ce lecteur a longtemps refusé tout ce qui n'était pas un PDF. Sur la
    première commune, le compte rendu de la séance budgétaire d'avril 2026 est
    une page HTML sans pièce jointe : elle était cataloguée, refusée ici, et la
    séance entière manquait — avec les huit budgets qu'elle votait.
    """
    try:
        req = urllib.request.Request(_url_http(url), headers=HEADERS)
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            ctype = r.headers.get("Content-Type", "")
    except Exception as e:
        print(f"  [pv][erreur] {url} → {e}")
        return None
    fmt = format_de(raw, ctype)
    if fmt == "inconnu":
        print(f"  [pv][skip] format illisible ({len(raw)} octets) : {url}")
        return None
    archive_fetch(source or "site", url, raw, MIME.get(fmt, "application/octet-stream"),
                  200, doc_type=fmt, title=_cible_cache(url).name)
    return raw, fmt


def texte_pdf(chemin: Path) -> str:
    try:
        with pdfplumber.open(str(chemin)) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception as e:
        print(f"  [pv][erreur] lecture {chemin.name} → {e}")
        return ""


def lire_document(doc, avec_ocr: bool = False) -> tuple[str, str, bool] | None:
    """(texte, format, océrisé) — ou rien si le document est hors d'atteinte.

    Les PDF gardent leur cache sur disque : ils sont lourds, immuables une fois
    déposés, et la reconnaissance optique a besoin d'un fichier. Les autres
    formats sont relus à chaque passage — une page web change, elle.
    """
    cache = _cible_cache(doc.url)
    if cache.exists() and cache.stat().st_size > 0:
        texte = texte_pdf(cache)
        if len(texte) < MIN_TEXT_CHARS and avec_ocr:
            texte = ocr(cache)
            return texte, "pdf", bool(texte)
        return texte, "pdf", False

    recu = telecharger(doc.url, doc.source)
    if recu is None:
        return None
    raw, fmt = recu
    if fmt != "pdf":
        return texte_de(raw, fmt), fmt, False

    PDF_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(raw)
    texte = texte_pdf(cache)
    if len(texte) < MIN_TEXT_CHARS and avec_ocr:
        texte = ocr(cache)
        return texte, "pdf", bool(texte)
    return texte, "pdf", False


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
    # Un portail d'actes dépose les délibérations une par une : quarante pièces
    # peuvent venir de la même séance, chacune avec sa propre adresse. L'identité
    # par l'URL en ferait quarante séances. Le repère est alors la DATE — celle
    # de l'acte, établie à la lecture, pas celle du dépôt.
    if getattr(doc, "acte", None):
        row = conn.execute(
            "SELECT id FROM events WHERE type=? AND date=?",
            (p["seance"], doc.date)).fetchone()
    else:
        row = conn.execute(
            "SELECT id FROM events WHERE type=? AND source_url=?",
            (p["seance"], doc.url)).fetchone()
    if row:
        conn.execute("UPDATE events SET date=?, metadata=? WHERE id=?",
                     (doc.date, json.dumps(meta, ensure_ascii=False), row["id"]))
        return row["id"]
    # La séance renvoie vers le portail qui la publie, jamais vers l'un de ses
    # actes : le premier arrivé n'a pas à représenter les trente-neuf autres.
    url_seance = (doc.acte or {}).get("portail") or doc.url if getattr(
        doc, "acte", None) else doc.url
    cur = conn.execute(
        "INSERT INTO events (type,date,title,source,source_url,metadata)"
        " VALUES (?,?,?,?,?,?)",
        (p["seance"], doc.date, p["titre"].format(date=doc.date), doc.source,
         url_seance, json.dumps(meta, ensure_ascii=False)))
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


def ocr(chemin: Path, langue: str = "fra") -> str:
    """Texte d'un PDF scanné, par reconnaissance optique.

    Le PDF reconnu est écrit à côté de l'original et conservé : l'OCR coûte
    plusieurs dizaines de secondes par document, et la relecture d'un corpus ne
    doit pas les repayer. L'original n'est jamais remplacé — c'est la pièce.

    Certaines communes scannent la totalité de leurs procès-verbaux : sur l'une
    des trois instances, 34 séances sur 48 sont des images. Sans cette étape,
    le dispositif y catalogue des documents qu'il ne sait pas lire.
    """
    cible = chemin.with_suffix(".ocr.pdf")
    if cible.exists() and cible.stat().st_size > 0:
        return texte_pdf(cible)
    if not shutil.which("ocrmypdf"):
        print("  [ocr] ocrmypdf introuvable — `brew install ocrmypdf`")
        return ""
    langues = subprocess.run(["tesseract", "--list-langs"],
                             capture_output=True, text=True).stdout
    if langue not in langues:
        print(f"  [ocr] langue tesseract « {langue} » absente")
        return ""
    print(f"  [ocr] {chemin.name} …", flush=True)
    try:
        subprocess.run(
            ["ocrmypdf", "-l", langue, "--force-ocr", "--output-type", "pdf",
             "--optimize", "0", "--jobs", "4", str(chemin), str(cible)],
            check=True, capture_output=True, timeout=900)
    except (subprocess.SubprocessError, OSError) as e:
        print(f"  [ocr][échec] {chemin.name} → {e}")
        return ""
    return texte_pdf(cible)


# « Séance du 25 juin 2026 », dans l'en-tête d'un acte. Repli de deuxième rang :
# la référence de contrôle de légalité vaut mieux, elle est mécanique.
_SEANCE_DU = re.compile(r"[Ss]éance\s+du\s+([^\n,;]{6,40})")


def date_de_seance(texte: str, doc, portee: str) -> tuple[str, str, dict]:
    """(date, provenance, contrôle) pour un acte publié seul.

    Trois provenances, par force de preuve décroissante :

    `reference_actes` — la référence @ctes apposée par la préfecture au moment
    du contrôle de légalité porte la date de l'acte. C'est un fait imprimé sur
    la pièce, et il porte aussi le SIREN de la collectivité : on en profite pour
    vérifier que l'acte émane bien de celle qu'on collecte.

    `entete` — « Séance du … » dans le corps du document. Fiable mais rédigée.

    `teletransmission` — la date que le portail affiche, en dernier recours. Ce
    n'est PAS la date de la séance : sur le portail relevé le 24/08/2026, six
    délibérations du 25 juin y figuraient au 30 juin et au 6 juillet. La
    provenance est écrite dans la métadonnée pour qu'un lecteur sache toujours
    ce qu'il regarde.
    """
    controle: dict = {}
    ref = reference_actes(texte)
    if ref:
        attendu = EPCI_SIREN if portee == "epci" else COMMUNE_SIREN
        if attendu and ref["siren"] != attendu:
            # Ne pas refuser la pièce : le portail d'un EPCI publie aussi les
            # actes de son CCAS ou d'un syndicat, qui ont leur propre SIREN.
            # Le signaler suffit, et laisse l'arbitrage à l'atelier.
            controle["siren_inattendu"] = ref["siren"]
            print(f"  [acte] {ref['numero']} — SIREN {ref['siren']} au lieu de "
                  f"{attendu} : émetteur à vérifier")
        controle["reference_actes"] = ref["reference"]
        return ref["date"], "reference_actes", controle

    m = _SEANCE_DU.search(texte or "")
    if m:
        date = date_fr(m.group(1))
        if date:
            return date, "entete", controle
    return doc.date, "teletransmission", controle


def traiter_acte(conn, doc, portee: str, verbose: bool = True,
                 avec_ocr: bool = False) -> dict:
    """Enregistre une pièce qui EST une délibération, sans rien découper.

    Un portail de publicité légale publie les actes un par un, avec leur numéro
    et leur objet. Tout ce que les analyseurs de procès-verbaux cherchent à
    deviner est ici déclaré par la collectivité — il n'y a donc pas de découpage
    à tenter, et en tenter un serait remplacer un fait par une inférence.

    La séance reste enregistrée : c'est le contenant qui rassemble les actes
    d'un même jour, et le seul endroit où lire les présents.
    """
    p = PORTEES[portee]
    lu = lire_document(doc, avec_ocr)
    if lu is None:
        return {"statut": "inaccessible", "delibs": 0}
    texte, format_, ocrise = lu

    if len(texte) < MIN_TEXT_CHARS:
        # Le portail donne l'objet et le numéro, mais pas le texte : enregistrer
        # une délibération vide la ferait passer pour lue. La lacune se signale.
        if verbose:
            print(f"  [acte] {doc.acte.get('numero') or doc.url} — "
                  f"pièce sans couche texte, non enregistrée")
        return {"statut": "sans_couche_texte" if format_ == "pdf"
                else "texte_trop_court", "delibs": 0}

    date, provenance, controle = date_de_seance(texte, doc, portee)
    doc.date = date

    pres = presences(texte, _ordre_noms(portee))
    seance_id = enregistrer_seance(
        conn, doc, portee,
        {"format": format_, "ocr": ocrise, "depuis_portail_actes": True, **pres})

    delib = acte_unique(doc.acte.get("objet") or doc.libelle, texte,
                        doc.acte.get("numero") or "")
    eid = enregistrer_deliberation(conn, doc, portee, delib)
    conn.execute(
        "UPDATE events SET metadata=json_patch(metadata, ?) WHERE id=?",
        (json.dumps({"type_acte": doc.acte.get("type") or "",
                     "date_source": provenance,
                     "date_teletransmission": doc.acte.get("date_teletransmission") or "",
                     **controle}, ensure_ascii=False), eid))

    # Le compte des actes d'une séance se LIT en base : la pièce en cours ne
    # sait pas combien de sœurs elle a, et un portail qui n'affiche que la
    # période d'affichage légal n'en connaît lui-même qu'une partie.
    nb = conn.execute("SELECT COUNT(*) FROM events WHERE type=? AND date=?",
                      (p["delib"], doc.date)).fetchone()[0]
    conn.execute(
        "UPDATE events SET metadata=json_patch(metadata, ?) WHERE id=?",
        (json.dumps({"nb_deliberations": nb}, ensure_ascii=False), seance_id))

    link_persons_to_event(conn, seance_id, pres["presents"], "présent")
    link_persons_to_event(conn, seance_id, pres["absents"], "absent")
    link_persons_to_event(conn, eid, pres["presents"], "présent")

    if verbose:
        print(f"  [acte] {doc.date} — {delib['numero_acte'] or 'sans numéro'} "
              f"({provenance}), {len(pres['presents'])} présents")
    return {"statut": "ok", "delibs": 1}


def traiter(conn, doc, portee: str, verbose: bool = True,
            avec_ocr: bool = False) -> dict:
    """Télécharge, lit et enregistre un procès-verbal, quel que soit son format."""
    if getattr(doc, "acte", None):
        return traiter_acte(conn, doc, portee, verbose, avec_ocr)
    p = PORTEES[portee]
    lu = lire_document(doc, avec_ocr)
    if lu is None:
        return {"statut": "inaccessible", "delibs": 0}
    texte, format_, ocrise = lu

    if len(texte) < MIN_TEXT_CHARS:
        # Sans reconnaissance optique, le signaler vaut mieux que produire une
        # séance vide qui passerait pour lue. Une page web trop courte, elle,
        # n'est pas un défaut de lecture : c'est un ordre du jour, ou une page
        # qui annonce la séance sans la rapporter.
        enregistrer_seance(conn, doc, portee, {"format": format_})
        return {"statut": "sans_couche_texte" if format_ == "pdf" else "texte_trop_court",
                "delibs": 0}

    # Seul un PDF a des pages, donc un en-tête de page. Cf. `_sans_entetes`.
    delibs = deliberations(texte, pagine=(format_ == "pdf"))
    pres = presences(texte, _ordre_noms(portee))
    seance_id = enregistrer_seance(
        conn, doc, portee,
        {"nb_deliberations": len(delibs), "ocr": ocrise, "format": format_, **pres})

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
              catalogue_seul: bool = False, avec_ocr: bool = False) -> None:
    instance = COMMUNE_NAME if portee == "commune" else (EPCI_NOM or "EPCI")
    print(f"\n[conseils] {instance} — catalogue des procès-verbaux")

    documents = charger(portee=portee).catalogue_pv(portee)
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
            r = traiter(conn, doc, portee, avec_ocr=avec_ocr)
            # `.get` et non `[]` : `traiter` rend aussi « texte_trop_court »,
            # absent du résumé — une page web courte faisait tomber la collecte
            # entière sur un KeyError, après des dizaines de documents lus.
            resume[r["statut"]] = resume.get(r["statut"], 0) + 1
            resume["delibs"] += r["delibs"]

    reste = resume["sans_couche_texte"]
    print(f"\n[conseils] {resume['ok']} documents lus, {resume['delibs']} "
          f"délibérations, {reste} sans couche texte"
          + ("" if avec_ocr else " (relancer avec --ocr)")
          + f", {resume['inaccessible']} inaccessibles")


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
    ap.add_argument("--ocr", action="store_true",
                    help="reconnaissance optique des PDF scannés (ocrmypdf)")
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
            print(traiter(conn, doc, args.portee, avec_ocr=args.ocr))
    else:
        depuis = args.depuis
        if depuis and len(depuis) == 4:
            depuis = f"{depuis}-01-01"
        collecter(args.portee, depuis, args.limit, args.commit, args.catalogue,
                  avec_ocr=args.ocr)
