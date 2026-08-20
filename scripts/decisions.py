"""Clés naturelles des objets arbitrés, partagées par l'export et l'import.

POURQUOI CE MODULE EXISTE
Deux ateliers qui collectent la même commune produisent deux bases dont les
identifiants n'ont rien à voir : `id` est un compteur local. Une décision
exportée sous « annotation sur l'objet 1430 » ne désigne rien ailleurs.

Chaque objet arbitré reçoit donc une clé calculée à partir de ce qui vient de
la SOURCE, jamais de la base : un SIREN, un numéro RNA, l'URL d'un acte. Deux
machines qui ont lu la même source obtiennent la même clé.

CE QUI N'EST PAS RÉSOLU, ET QUI NE PEUT PAS L'ÊTRE
Une personne physique n'a pas d'identifiant public. Un lieu non plus. Leur clé
retombe sur le nom normalisé et la commune : deux homonymes dans la même
commune sont indiscernables. C'est une limite assumée, pas un oubli — et
l'import signale ce qu'il n'a pas su rattacher plutôt que de deviner.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata


def _norme(texte: str | None) -> str:
    """Forme comparable : sans accents, sans casse, sans ponctuation."""
    t = unicodedata.normalize("NFD", texte or "")
    t = "".join(c for c in t if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def _empreinte(*morceaux: str | None) -> str:
    """Empreinte courte et stable d'une combinaison de champs."""
    brut = "|".join(_norme(m) for m in morceaux)
    return hashlib.sha1(brut.encode("utf-8")).hexdigest()[:16]


def cle_entite(conn, entity_id: int) -> tuple[str, str] | None:
    """(clé, libellé lisible) d'une entité, ou None si elle n'existe pas.

    L'ordre compte : un identifiant officiel prime toujours sur un nom. Un
    SIREN désigne la même entreprise partout ; « LA POSTE » non.
    """
    row = conn.execute(
        "SELECT type, name, commune FROM entities WHERE id=?", (entity_id,)
    ).fetchone()
    if not row:
        return None
    type_, nom, commune = row[0], row[1], row[2]

    siren = conn.execute(
        "SELECT siren FROM businesses WHERE entity_id=?", (entity_id,)
    ).fetchone() if type_ == "business" else None
    if siren and siren[0]:
        return f"siren:{siren[0]}", nom

    rna = conn.execute(
        "SELECT rna_id FROM associations WHERE entity_id=?", (entity_id,)
    ).fetchone() if type_ == "association" else None
    if rna and rna[0]:
        return f"rna:{rna[0]}", nom

    return f"nom:{type_}:{_empreinte(nom, commune)}", nom


def cle_evenement(conn, event_id: int) -> tuple[str, str] | None:
    """(clé, libellé lisible) d'un acte.

    `events` n'a aucune contrainte d'unicité : la clé est une empreinte du type,
    de la date, de la source et du titre. L'URL seule ne suffit pas — sur les
    communes qui publient un compte rendu par séance, vingt délibérations
    partagent la même adresse.
    """
    row = conn.execute(
        "SELECT type, date, source, source_url, title FROM events WHERE id=?", (event_id,)
    ).fetchone()
    if not row:
        return None
    type_, date, source, url, titre = row
    marche = conn.execute(
        "SELECT raw_id FROM marches_publics WHERE event_id=?", (event_id,)
    ).fetchone()
    if marche and marche[0]:
        # Le BOAMP et le DECP donnent un identifiant d'avis : il vaut mieux
        # qu'une empreinte, parce qu'il survit à une reformulation de l'objet.
        return f"marche:{marche[0]}", (titre or "")[:70]
    return (f"acte:{_empreinte(type_, date, source, url, titre)}",
            f"{date or '?'} — {(titre or '')[:60]}")


def cle_marche(conn, marche_id: int) -> tuple[str, str] | None:
    row = conn.execute(
        "SELECT raw_id, objet, source, date_notif FROM marches_publics WHERE id=?",
        (marche_id,)
    ).fetchone()
    if not row:
        return None
    raw_id, objet, source, date = row
    if raw_id:
        return f"marche:{raw_id}", (objet or "")[:70]
    return f"marche:{_empreinte(source, date, objet)}", (objet or "")[:70]


def cle_flux(conn, flow_id: int) -> tuple[str, str] | None:
    row = conn.execute(
        "SELECT type, year, amount, description, source FROM financial_flows WHERE id=?",
        (flow_id,)
    ).fetchone()
    if not row:
        return None
    type_, annee, montant, desc, source = row
    return (f"flux:{_empreinte(type_, str(annee), str(montant), desc, source)}",
            f"{annee or '?'} — {(desc or '')[:56]}")


# Un type d'objet arbitré → la fonction qui le désigne.
CLES = {
    "entity": cle_entite,
    "deliberation": cle_evenement,
    "event": cle_evenement,
    "marche": cle_marche,
    "flow": cle_flux,
}


def resoudre(conn, cle: str) -> int | None:
    """L'inverse : retrouve l'identifiant LOCAL d'un objet depuis sa clé.

    Renvoie None quand l'objet n'existe pas dans cette base — cas normal quand
    deux ateliers n'ont pas collecté exactement la même chose. L'appelant doit
    le signaler, pas le taire.
    """
    if cle.startswith("siren:"):
        r = conn.execute("SELECT entity_id FROM businesses WHERE siren=?",
                         (cle[6:],)).fetchone()
        return r[0] if r else None
    if cle.startswith("rna:"):
        r = conn.execute("SELECT entity_id FROM associations WHERE rna_id=?",
                         (cle[4:],)).fetchone()
        return r[0] if r else None
    if cle.startswith("marche:"):
        r = conn.execute("SELECT id FROM marches_publics WHERE raw_id=?",
                         (cle[7:],)).fetchone()
        return r[0] if r else None
    # Les clés par empreinte demandent un balayage : on les recalcule sur place.
    if cle.startswith("nom:"):
        _, type_, _ = cle.split(":", 2)
        for (eid,) in conn.execute("SELECT id FROM entities WHERE type=?", (type_,)):
            k = cle_entite(conn, eid)
            if k and k[0] == cle:
                return eid
        return None
    if cle.startswith("acte:"):
        for (eid,) in conn.execute("SELECT id FROM events"):
            k = cle_evenement(conn, eid)
            if k and k[0] == cle:
                return eid
        return None
    if cle.startswith("flux:"):
        for (fid,) in conn.execute("SELECT id FROM financial_flows"):
            k = cle_flux(conn, fid)
            if k and k[0] == cle:
                return fid
        return None
    return None
