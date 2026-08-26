"""
Collecteur RNA / Associations
Sources :
  1. API JO associations (Journal Officiel) — déclarations post-2009 (nationale)
  2. les pages d'annuaire du site officiel — responsables nommés

La source 2 passe par le connecteur de l'instance : la version d'origine
scrapait une page précise d'un site précis, avec un navigateur furtif pour
contourner l'anti-bot d'un thème Drupal. Les pages à lire se déclarent dans
`config/instance.json` (clé `pages.commune.annuaires`).

Ce que ces pages publient et que le RNA ne donne pas : le nom du responsable de
chaque association, avec ses coordonnées. C'est collecté tel quel — la règle de
l'atelier est de tout collecter et de filtrer à la publication, pas l'inverse —
et rangé dans `entity_notes`, jamais dans une fiche personne.
"""
import json
import re
import time
import urllib.parse
import urllib.request
import unicodedata
from .archive import fetch_json
from .config import (JO_ASSO_API, CODE_POSTAL, COMMUNE_NAME, COMMUNES,
                     COMMUNES_DELEGUEES, HEADERS, REQUEST_DELAY)


def _norm(s: str) -> str:
    """Normalise un nom de commune : sans accents, minuscules, séparateurs unifiés."""
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    for ch in "-'’":
        s = s.replace(ch, " ")
    return " ".join(s.lower().split())


# Index nom normalisé → nom officiel du registre (pour taguer/filtrer les assos)
_COMMUNE_LOOKUP = {_norm(c["nom"]): c["nom"] for c in COMMUNES.values()}
# Communes déléguées : le JO des associations continue d'écrire l'ancien nom
# des communes fusionnées, parfois des décennies après. La correspondance
# « ancien nom → commune actuelle » se lit dans `communes_deleguees` de
# config/instance.json, où chaque entrée porte le code INSEE de sa commune de
# rattachement. Elle a été écrite en dur pendant des mois : le moteur
# connaissait ainsi une fusion précise, et une seule.
for _delegee in COMMUNES_DELEGUEES.values():
    _parent = COMMUNES.get(_delegee.get("commune", ""), {}).get("nom")
    if _parent:
        _COMMUNE_LOOKUP[_norm(_delegee["nom"])] = _parent


def _match_commune(ville: str) -> str | None:
    """Nom officiel du registre si la commune est collectée, sinon None."""
    return _COMMUNE_LOOKUP.get(_norm(ville))
from .db import transaction, upsert_entity, upsert_relation
from .nom_normalise import nettoyer_libelle, normaliser


# ----------------------------------------------------------------
# Source 1 : API JO associations
# ----------------------------------------------------------------

def fetch_jo_page(offset: int = 0, limit: int = 100, cp: str = CODE_POSTAL) -> dict:
    params = urllib.parse.urlencode({
        "where": f'codepostal_actuel="{cp}"',
        "limit": limit,
        "offset": offset,
        "order_by": "dateparution DESC"
    })
    url = f"{JO_ASSO_API}?{params}"
    return fetch_json(url, source="rna-jo", timeout=15)


def fetch_all_jo(cp: str = CODE_POSTAL) -> list[dict]:
    results = []
    offset = 0
    limit  = 100
    total  = None

    while True:
        try:
            data = fetch_jo_page(offset, limit, cp)
        except Exception as e:
            print(f"  [rna] erreur offset {offset}: {e}")
            break

        items = data.get("results", [])
        results.extend(items)

        if total is None:
            total = data.get("total_count", 0)
            print(f"  [rna] {total} associations JO pour CP {cp}")

        if not items or len(results) >= total:
            break

        offset += limit
        time.sleep(REQUEST_DELAY)

    return results


# ----------------------------------------------------------------
# Source 2 : page « associations » du site communal
# ----------------------------------------------------------------

# « Club sportif \n NOM Prénom \n 119 avenue … »
# Le responsable est la ligne qui suit le nom, en « NOM Prénom ».
# Le prénom composé s'écrit « Jean-François » : le tiret n'est admis que suivi
# d'une majuscule, sinon la capture s'arrête sur « Jean- » et le responsable
# devient une association de plus.
_RESPONSABLE = re.compile(
    r"^([A-ZÀ-Ÿ][A-ZÀ-Ÿ'’\-]{2,}(?:\s+[A-ZÀ-Ÿ][A-ZÀ-Ÿ'’\-]{2,})*)\s+"
    r"([A-ZÀ-Ÿ][a-zà-ÿ'’]+(?:-[A-ZÀ-Ÿ][a-zà-ÿ'’]+)*)$")
_CONTACT = re.compile(r"(0\d[\s.]?(?:\d{2}[\s.]?){4}|[\w.+-]+@[\w-]+\.[\w.]+|https?://\S+)")


def fetch_structures_site() -> list[dict]:
    """Associations listées sur le site communal, avec leur responsable.

    Retourne [{name, responsable, contacts, url, source}]. Le découpage se fait
    sur les lignes : une association ouvre un bloc (ligne sans chiffre ni
    contact), le responsable suit, puis l'adresse et les contacts.
    """
    from .connecteurs import charger
    from .config import COMMUNE_URL
    import urllib.parse

    source = urllib.parse.urlparse(COMMUNE_URL).netloc.removeprefix("www.")
    structures = []
    for texte in charger().pages_annuaire("commune"):
        lignes = [l.strip() for l in texte.splitlines() if l.strip()]
        courante = None
        for ligne in lignes:
            if ligne.isupper() and "ANNUAIRE" in ligne:
                continue
            # Une phrase d'introduction n'est pas une association : elle est
            # longue et se termine par une ponctuation de phrase.
            if len(ligne) > 60 or ligne.endswith((":", ".")):
                continue
            m = _RESPONSABLE.match(ligne)
            if m and courante:
                courante["responsable"] = f"{m.group(2)} {m.group(1)}"
                continue
            contacts = _CONTACT.findall(ligne)
            if contacts and courante:
                courante["contacts"] += contacts
                continue
            # Une ligne d'adresse commence par un numéro, ou porte le code
            # postal de la commune.
            if re.match(r"^[\d]", ligne) or CODE_POSTAL in ligne:
                continue
            courante = {"name": ligne, "responsable": None, "contacts": [],
                        "url": COMMUNE_URL, "source": source}
            structures.append(courante)

    print(f"  [rna/site] {len(structures)} associations listées, "
          f"{sum(1 for s in structures if s['responsable'])} avec un responsable nommé")
    return structures


def _import_structures(conn, structures: list[dict]) -> int:
    """Rattache responsable et contacts à l'association, en note d'entité."""
    poses = 0
    for st in structures:
        if not st["responsable"] and not st["contacts"]:
            continue
        eid = upsert_entity(conn, type="association", name=nettoyer_libelle(st["name"]),
                            commune=COMMUNE_NAME, confidence="probable")
        note = json.dumps({"responsable": st["responsable"],
                           "contacts": st["contacts"],
                           "url": st["url"]}, ensure_ascii=False)
        # `entity_notes` n'a pas de contrainte d'unicité : sans ce contrôle,
        # chaque exécution ajoute une note identique de plus.
        if conn.execute(
            "SELECT 1 FROM entity_notes WHERE entity_id=? AND note=?",
            (eid, note)).fetchone():
            continue
        conn.execute(
            "INSERT INTO entity_notes (entity_id, note, source, confidence)"
            " VALUES (?,?,?,?)",
            (eid, note, st["source"], "probable"))
        poses += 1
    return poses


# ----------------------------------------------------------------
# Import en base
# ----------------------------------------------------------------

def import_rna(cp: str = CODE_POSTAL):
    print(f"[rna] Démarrage collecte JO associations (CP {cp})...")
    items = fetch_all_jo(cp)
    print(f"[rna] CP {cp} : {len(items)} associations récupérées, import en base...")

    inserted   = 0
    skipped    = 0
    hors_perimetre = 0

    with transaction() as conn:
        for item in items:
            # Filtre : ne garder que les communes collectées (registre COMMUNES).
            # Indispensable — un CP déborde toujours sur des communes voisines.
            if not _match_commune(item.get("commune_actuelle") or ""):
                hors_perimetre += 1
                continue
            try:
                _import_jo_record(conn, item)
                inserted += 1
            except Exception as e:
                skipped += 1
                print(f"  [rna] skip {item.get('numero_rna','?')}: {e}")
            if inserted % 50 == 0 and inserted > 0:
                conn.commit()

    print(f"[rna] CP {cp} OK — {inserted} associations du périmètre, "
          f"{hors_perimetre} hors périmètre ignorées, {skipped} erreurs")

    # Source 2 : uniquement sur le CP de la commune — la page ne liste que les
    # associations de Brassac, la relancer pour chaque CP du registre ferait
    # seize fois le même travail.
    if cp == CODE_POSTAL:
        structures = fetch_structures_site()
        with transaction() as conn:
            poses = _import_structures(conn, structures)
        print(f"[rna] {poses} associations enrichies depuis le site communal")


def titre_du_record(item: dict) -> str:
    """Le nom ACTUEL de l'association, tel que l'annonce le dit.

    `titre` est vide sur une annonce de Modification. Le repli tenait alors sur
    `titre_search` — qui est un champ d'INDEXATION, pas un nom : il empile
    l'ancien titre, le nouveau, puis leurs formes normalisées. « VIVALTO » en
    ressortait « VIVALTO. VIV'ALTO », un nom que personne ne porte, et qui ne
    pouvait plus rejoindre la fiche « VIVALTO » créée par l'annonce voisine.

    Sur une Modification, le nom actuel est `modification.nouveauTitre`. C'est
    la source qui le dit, à cet endroit précis : rien n'est deviné ici.
    """
    titre = item.get("titre")
    if not titre:
        titre = (_contenu(item).get("modification") or {}).get("nouveauTitre")
    if not titre:
        # Dernier recours seulement : mieux vaut un nom d'indexation qu'un
        # identifiant en guise de nom, mais l'un comme l'autre se voient.
        titre = item.get("titre_search") or item.get("numero_rna") or item.get("id", "")
    return nettoyer_libelle(titre)


def _contenu(item: dict) -> dict:
    """Le bloc `assoLoi1901` de l'annonce, ou vide s'il est illisible."""
    brut = item.get("contenu")
    if isinstance(brut, dict):
        return brut.get("assoLoi1901") or {}
    if isinstance(brut, str):
        try:
            return (json.loads(brut) or {}).get("assoLoi1901") or {}
        except (ValueError, AttributeError):
            return {}
    return {}


def _import_jo_record(conn, item: dict):
    # Schéma dataset jo_associations (Opendatasoft v2.1, refonte 2024)
    rna_id  = item.get("numero_rna") or item.get("id", "")
    # Le RNA publie ses titres tels que déposés : entre guillemets, avec un
    # point final, parfois deux fois de suite. `nettoyer_libelle` retire cette
    # ponctuation de saisie — et rien d'autre, la casse comprise.
    titre   = titre_du_record(item)
    objet   = item.get("objet", "")
    cp      = item.get("codepostal_actuel", "") or ""
    ville   = (item.get("commune_actuelle") or "").strip()
    addr    = (item.get("adresse_actuelle") or "").strip()

    # Type d'avis : Création / Modification / Dissolution
    typeavis = (item.get("typeavis") or "").lower()
    is_diss  = "dissol" in typeavis
    status   = "D" if is_diss else "A"

    # Coordonnées
    geo  = item.get("geo_point") or {}
    lat  = geo.get("lat")
    lng  = geo.get("lon")

    crea = item.get("datedeclaration") or item.get("dateparution", "")
    diss = item.get("datedeclaration") if is_diss else None

    commune = _match_commune(ville) or (ville or None)

    # L'adresse porte le nom de commune du RÉFÉRENTIEL quand il a été
    # reconnu, pas celui de la source : « 30570 Val d'aigoual » et
    # « Val-d'Aigoual » désignaient la même commune sur la même fiche, l'une
    # dans `address`, l'autre dans `commune`.
    addr_str = nettoyer_libelle(" ".join(filter(None, [addr, cp, commune or ville])))

    # L'IDENTIFIANT d'abord, le nom ensuite. Une association a plusieurs
    # annonces au Journal officiel — création, puis modifications — et elle n'y
    # porte pas toujours le même libellé. Chercher par le nom en faisait une
    # entité par graphie ; le `INSERT OR IGNORE` qui suivait échouait alors en
    # silence sur `rna_id UNIQUE`, laissant une entité sans fiche, sans
    # identifiant et sans objet — irrattachable autrement qu'à la main.
    connue = conn.execute(
        "SELECT entity_id FROM associations WHERE rna_id=?", (rna_id,)
    ).fetchone() if rna_id else None

    if connue:
        eid = connue["entity_id"]
        _completer_entite(conn, eid, lat, lng, addr_str, commune)
        # Un `nouveauTitre` est une déclaration de changement de nom : la source
        # dit que l'association s'appelle DÉSORMAIS ainsi. On la renomme — sauf
        # si ce nom est déjà pris par une autre fiche, auquel cas c'est une
        # fusion, et la fusion ne se décide pas au fil d'une collecte.
        nouveau = (_contenu(item).get("modification") or {}).get("nouveauTitre")
        if nouveau:
            _renommer_si_libre(conn, eid, nettoyer_libelle(nouveau))
    else:
        eid = upsert_entity(conn,
            type="association",
            name=titre,
            lat=float(lat) if lat else None,
            lng=float(lng) if lng else None,
            address=addr_str or None,
            confidence="verified",
            commune=commune
        )

    conn.execute(
        "INSERT OR IGNORE INTO associations"
        " (entity_id,rna_id,object,status,creation_date,dissolution_date,raw_data)"
        " VALUES (?,?,?,?,?,?,?)",
        (eid, rna_id, objet, status, crea[:10] if crea else None,
         diss[:10] if diss else None,
         json.dumps(item, ensure_ascii=False))
    )
    # Une annonce plus récente en dit plus : compléter ce qui était vide, sans
    # jamais écraser ce qu'une autre source a déjà renseigné.
    conn.execute(
        "UPDATE associations SET"
        "   object   = COALESCE(NULLIF(object,''), ?),"
        "   status   = COALESCE(NULLIF(status,''), ?),"
        "   raw_data = COALESCE(NULLIF(raw_data,''), ?)"
        " WHERE entity_id=?",
        (objet, status, json.dumps(item, ensure_ascii=False), eid))
    if is_diss and diss:
        conn.execute(
            "UPDATE associations SET status='D', dissolution_date=?"
            " WHERE entity_id=?", (diss[:10], eid))


def _completer_entite(conn, eid: int, lat, lng, addr_str, commune) -> None:
    """Remplit les cases vides d'une entité déjà connue. N'écrase rien."""
    champs = {"lat": float(lat) if lat else None,
              "lng": float(lng) if lng else None,
              "address": addr_str or None,
              "commune": commune}
    row = conn.execute(
        "SELECT lat,lng,address,commune FROM entities WHERE id=?", (eid,)).fetchone()
    if row is None:
        return
    maj = {k: v for k, v in champs.items() if v is not None and not row[k]}
    if maj:
        conn.execute(
            f"UPDATE entities SET {','.join(f'{k}=?' for k in maj)} WHERE id=?",
            (*maj.values(), eid))


def _renommer_si_libre(conn, eid: int, nom: str) -> bool:
    """Renomme l'association si le nom est libre. Rend False s'il est pris."""
    if not nom:
        return False
    actuel = conn.execute("SELECT name FROM entities WHERE id=?", (eid,)).fetchone()
    if actuel is None or actuel["name"] == nom:
        return False
    pris = conn.execute(
        "SELECT id FROM entities WHERE type='association' AND name=? AND id<>?",
        (nom, eid)).fetchone()
    if pris:
        return False
    conn.execute("UPDATE entities SET name=?, name_norm=? WHERE id=?",
                 (nom, normaliser(nom), eid))
    return True
