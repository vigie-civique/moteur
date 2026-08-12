"""
banatic.py — L'intercommunalité comme institution (périmètre C2).

Source : https://www.banatic.interieur.gouv.fr/intercommunalite/<SIREN>
La page est une application Next.js : toutes les données utiles sont dans le
blob JSON `__NEXT_DATA__`, structuré et stable. On ne parse donc pas du HTML.

Ce que le collecteur ramène, et pourquoi
----------------------------------------
1. **Compétences** — la liste officielle de ce que l'EPCI exerce À LA PLACE de
   la commune. C'est la définition même du périmètre C2 : sans elle, on ne sait
   pas quelles décisions ont quitté le conseil municipal. 26 compétences pour la
   CC CAC, dont eau, assainissement et déchets.
2. **Délégués** — l'assemblée qui vote le budget intercommunal, avec la commune
   représentée. Source FAISANT FOI, contrairement au RNE : relevé le 11/08/2026,
   le fichier RNE `elus-conseillers-communautaires-epci.csv` attribuait 22 des
   27 délégués à Val-d'Aigoual, alors que BANATIC en donne 7 pour cette commune
   et répartit correctement les 28 sièges sur les 15 communes. Ne pas
   reconstruire l'assemblée depuis le RNE.
3. **Adhésions** — les syndicats mixtes auxquels l'EPCI adhère (SIAEP de
   Lasalle, SYMTOMA, EPTB Gardons…). Deuxième étage de délégation : une
   compétence transférée par la commune à l'EPCI peut être re-transférée à un
   syndicat. Ces structures sont classées C2 par la relation `adhère_à`.
4. **Arrêtés préfectoraux** — création, recomposition du conseil, modifications
   de compétences. Les actes qui font foi, avec leur PDF.

Usage :
    python3 -m collectors.banatic              # collecte complète
    python3 -m collectors.banatic --dry-run    # affiche sans écrire
    python3 -m collectors.banatic --siren 200034601
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request

from .archive import archive_fetch
from .config import EPCI_NOM, EPCI_SIREN, HEADERS
from .db import transaction, upsert_entity, upsert_person, upsert_relation

BASE_URL = "https://www.banatic.interieur.gouv.fr/intercommunalite/{siren}"
DOC_URL = "https://www.banatic.interieur.gouv.fr/consultation/api/document/{id}/{titre}"

# `fonction` BANATIC → type de relation vers l'EPCI.
FONCTIONS = {
    "Président": "président_cc",
    "Vice-président": "vice_président_cc",
    "Autre délégué": "élu_cc",
}


def fetch(siren: str) -> dict:
    """Récupère le blob __NEXT_DATA__ de la fiche BANATIC."""
    url = BASE_URL.format(siren=siren)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=45) as r:
        raw = r.read()
        status = r.status
    archive_fetch("banatic", url, raw, doc_type="html", http_status=status,
                  title=f"BANATIC — {EPCI_NOM} ({siren})")
    html = raw.decode("utf-8", errors="replace")
    m = re.search(r'__NEXT_DATA__[^>]*>(\{.*?\})</script>', html, re.S)
    if not m:
        raise RuntimeError(
            "blob __NEXT_DATA__ introuvable — la fiche BANATIC a changé de forme")
    return json.loads(m.group(1))["props"]["pageProps"]["intercommunaliteJson"]


def _epci_entity(conn, siren: str) -> int:
    """Entité `service` de l'EPCI, créée si absente."""
    row = conn.execute(
        """SELECT e.id FROM entities e
           LEFT JOIN entity_notes n ON n.entity_id = e.id
           WHERE e.type='service' AND (n.note LIKE ? OR e.name LIKE ?)
           LIMIT 1""",
        (f"%{siren}%", f"%{EPCI_NOM.split(' ', 1)[-1]}%")).fetchone()
    if row:
        return row["id"]
    return upsert_entity(conn, type="service", name=EPCI_NOM,
                         confidence="verified")


def import_competences(conn, epci_id: int, data: dict, dry_run: bool) -> int:
    n = 0
    for c in data.get("competencesGroupement", []):
        cat = (c.get("categorieCompetence") or {}).get("libelle")
        n += 1
        if dry_run:
            continue
        conn.execute(
            """INSERT INTO epci_competences
               (epci_siren, code, libelle, categorie, obligatoire,
                interet_communautaire, source)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(epci_siren, code) DO UPDATE SET
                 libelle=excluded.libelle, categorie=excluded.categorie,
                 obligatoire=excluded.obligatoire,
                 interet_communautaire=excluded.interet_communautaire,
                 collected_at=datetime('now')""",
            (EPCI_SIREN, c.get("code"), c.get("libelle"), cat,
             1 if c.get("isObligatoire") else 0,
             1 if c.get("isInteretCommunautaire") else 0,
             "BANATIC"))
    return n


def import_delegues(conn, epci_id: int, data: dict, dry_run: bool) -> dict:
    res = {"delegues": 0, "personnes_creees": 0, "relations": 0,
           "communes_corrigees": []}
    for d in data.get("delegues", []):
        prenom = (d.get("prenom") or "").strip()
        nom = (d.get("nom") or "").strip()
        if not nom:
            continue
        membre = (d.get("membreRepresente") or {}).get("membre") or {}
        commune = membre.get("libelle")
        rel = FONCTIONS.get(d.get("fonction"), "élu_cc")
        res["delegues"] += 1
        if dry_run:
            continue

        nom_complet = f"{prenom} {nom}".strip()
        avant = conn.execute(
            "SELECT id, commune FROM entities WHERE type='person' AND name=?",
            (nom_complet,)).fetchone()
        # La commune DOIT être passée à la création : `entities.commune` a pour
        # défaut 'Lasalle' dans le schéma, et upsert_entity n'écrase jamais un
        # tag déjà posé. Créer d'abord puis corriger donnait 25 délégués sur 28
        # marqués « Lasalle » — dont le président, qui est de Val-d'Aigoual.
        pid = upsert_entity(conn, type="person", name=nom_complet,
                            commune=commune, confidence="verified")
        conn.execute(
            "INSERT OR IGNORE INTO persons (entity_id, firstname, lastname)"
            " VALUES (?,?,?)", (pid, prenom, nom))
        if avant is None:
            res["personnes_creees"] += 1
        elif commune and avant["commune"] != commune:
            # BANATIC fait foi sur le rattachement d'un délégué : il siège AU
            # TITRE de cette commune. On corrige, en le disant.
            conn.execute("UPDATE entities SET commune=?, updated_at=datetime('now')"
                         " WHERE id=?", (commune, pid))
            res["communes_corrigees"].append(
                f"{nom_complet} : {avant['commune']} → {commune}")
        upsert_relation(conn, pid, epci_id, rel, source="banatic",
                        confidence="verified",
                        metadata=json.dumps(
                            {"fonction": d.get("fonction"),
                             "commune_representee": commune},
                            ensure_ascii=False))
        res["relations"] += 1
    return res


def import_adhesions(conn, epci_id: int, data: dict, dry_run: bool) -> int:
    n = 0
    for s in data.get("groupementsAdherentsSyndicatMixte", []):
        libelle = (s.get("libelle") or "").strip()
        if not libelle:
            continue
        n += 1
        if dry_run:
            continue
        sid = upsert_entity(conn, type="service", name=libelle,
                            confidence="verified")
        conn.execute(
            "INSERT OR IGNORE INTO services (entity_id, category, operator)"
            " VALUES (?,?,?)", (sid, "intercommunal", s.get("codeNatureJuridique")))
        conn.execute(
            "INSERT OR IGNORE INTO entity_notes (entity_id, note, source, confidence)"
            " VALUES (?,?,?,?)",
            (sid, f"SIREN: {s.get('siren')} | Nature: {s.get('codeNatureJuridique')} "
                  f"| Population: {s.get('populationTotale')}",
             "BANATIC", "verified"))
        upsert_relation(conn, epci_id, sid, "adhère_à", source="banatic",
                        confidence="verified")
    return n


def import_arretes(conn, data: dict, dry_run: bool) -> int:
    n = 0
    for e in data.get("evenements", []):
        if not e.get("isAffichable", True):
            continue
        doc = e.get("document") or {}
        titre = doc.get("titre") or e.get("description") or "Arrêté préfectoral"
        url = (DOC_URL.format(id=doc["id"], titre=urllib.parse.quote(titre))
               if doc.get("id") else None)
        n += 1
        if dry_run:
            continue
        conn.execute(
            """INSERT OR IGNORE INTO events
               (type, date, title, content, source, source_url, metadata)
               VALUES (?,?,?,?,?,?,?)""",
            ("arrete_prefectoral_epci",
             (e.get("dateEffet") or e.get("dateCreation") or "")[:10],
             f"{EPCI_NOM} — {e.get('description') or titre}",
             titre, "banatic", url,
             json.dumps({"siren": EPCI_SIREN,
                         "creation_groupement": e.get("isCreationGroupement")},
                        ensure_ascii=False)))
    return n


def run(siren: str = EPCI_SIREN, dry_run: bool = False) -> None:
    print(f"[banatic] {EPCI_NOM} (SIREN {siren})")
    data = fetch(siren)

    with transaction() as conn:
        epci_id = _epci_entity(conn, siren)
        n_comp = import_competences(conn, epci_id, data, dry_run)
        deleg = import_delegues(conn, epci_id, data, dry_run)
        n_adh = import_adhesions(conn, epci_id, data, dry_run)
        n_arr = import_arretes(conn, data, dry_run)

    obligatoires = sum(1 for c in data.get("competencesGroupement", [])
                       if c.get("isObligatoire"))
    print(f"  compétences   : {n_comp} ({obligatoires} obligatoires, "
          f"{n_comp - obligatoires} facultatives)")
    print(f"  délégués      : {deleg['delegues']} "
          f"({deleg['personnes_creees']} personnes créées, "
          f"{deleg['relations']} relations)")
    for correction in deleg["communes_corrigees"]:
        print(f"    ↳ rattachement corrigé — {correction}")
    print(f"  adhésions     : {n_adh} syndicats mixtes")
    print(f"  arrêtés       : {n_arr}")
    if dry_run:
        print("  [dry-run] rien n'a été écrit")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="BANATIC — compétences et délégués de l'EPCI")
    ap.add_argument("--siren", default=EPCI_SIREN)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    run(args.siren, args.dry_run)
