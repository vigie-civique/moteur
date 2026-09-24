#!/usr/bin/env python3
"""
detect_links.py — Détection de liens potentiels entre entités.

Produit des candidats dans relation_candidates pour validation manuelle.
Ne touche pas à la table relations — tout passe par le panneau de review.

Signaux détectés (par score décroissant) :
  88 entity_duplicate     — même nom normalisé, types différents (ex: doublon Commune)
  82 same_full_name       — élu/candidat retrouvé dans SIRENE (nom exact)
  80 subsidy_entity_match — entité fantôme subvention ↔ vraie entité RNA
  78 maiden_name          — nom de jeune fille (parenthèses SIRENE) → famille
  20-42 same_surname      — patronyme rare partagé (≤ 5 personnes dans la DB)
  42 toponym              — lieu dans le nom d'une entité

Usage:
    python collectors/detect_links.py [--dry-run] [--reset] [--tous-signaux]
    --dry-run       : affiche le compte sans écrire en base
    --reset         : supprime d'abord tous les candidats pending
    --tous-signaux  : ajoute les deux signaux familiaux, éteints par défaut

⚠️ **Ce module n'a jamais tourné** avant le 23/09/2026 : il n'était ni un step
de `run_all.py`, ni appelé par un script. Joué à blanc ce jour-là sur copie des
trois instances, il produisait **59 799 candidats**, dont **52 637 `maiden_name`
(88 %)** — des liens de FAMILLE présumés entre personnes physiques nommées,
déduits des parenthèses SIRENE. Les 87 sièges de commission qui attendaient
vraiment à Lasalle y auraient disparu.

D'où `SIGNAUX_PAR_DEFAUT`, arbitré par Julien le 23/09 : le step quotidien ne
pose que ce qu'un humain peut trancher — un doublon, un élu retrouvé dirigeant,
un toponyme. Les deux signaux familiaux restent écrits, et éteints : ils
inféreraient des liens de parenté sur des particuliers, à 54 000 exemplaires,
pour une file que personne ne descendra jamais. `--tous-signaux` les rallume
pour une enquête menée à la main, en connaissance de cause.
"""
import sqlite3
import unicodedata
import re
import json
import sys
from pathlib import Path

from .config import DB_PATH   # la base est nommée dans la config, pas ici
from .db import log_run_end, log_run_start

# Seuil max de personnes partageant un patronyme pour suggérer un lien familial.
# Au-delà, le patronyme est considéré comme trop courant sur le territoire.
MAX_SURNAME_FREQ = 5

#: Au-delà de ce nombre de noms de structures qui le portent, un mot ne
#: distingue plus personne (cf. `detect_subsidy_phantoms`).
MAX_FREQ_MOT_DISTINCTIF = 5

#: Ce que la passe quotidienne pose : des candidats qu'on peut trancher sur
#: pièce. Mesuré le 23/09/2026 — 16/42/33 doublons, 3/1/2 élus-dirigeants,
#: 97/156/100 toponymes sur Lasalle, Saillans et Brassac.
SIGNAUX_PAR_DEFAUT = ("entity_duplicate", "same_full_name", "toponym",
                      "subsidy_entity_match")

#: Les deux qui infèrent une parenté. Hors passe automatique — cf. l'en-tête.
SIGNAUX_FAMILLE = ("maiden_name", "same_surname")

TOUS_SIGNAUX = SIGNAUX_PAR_DEFAUT + SIGNAUX_FAMILLE


# ── Normalisation ──────────────────────────────────────────────────────────────

def normalize(s: str) -> str:
    """Minuscules, sans accents, sans ponctuation, espaces réduits."""
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    return " ".join(s.split())


def parse_married_name(full_name: str):
    """
    Extrait le nom de naissance (entre parenthèses) d'un nom SIRENE.
    "Prénom NOM (NOM DE NAISSANCE)" → ("Prénom NOM", "NOM DE NAISSANCE")
    Retourne (None, None) si pas de parenthèses.
    """
    m = re.search(r"\(([^)]+)\)\s*$", full_name.strip())
    if m:
        birth = m.group(1).strip()
        married = full_name[: m.start()].strip()
        return married, birth
    return None, None


def extract_surnames(name: str) -> list[str]:
    """
    Extrait les tokens entièrement en majuscules d'un nom (probables patronymes).
    Ignore les mots entre parenthèses et les tokens ≤ 2 caractères.
    """
    clean = re.sub(r"\([^)]*\)", "", name).strip()
    return [t for t in clean.split() if t.isupper() and len(t) > 2]


# ── Insertion candidat ─────────────────────────────────────────────────────────

def insert_candidate(cur, from_id, to_id, rel_type, confidence, signal, detail, score) -> int:
    if from_id == to_id:
        return 0
    try:
        cur.execute(
            """INSERT OR IGNORE INTO relation_candidates
               (from_id, to_id, relation_type, confidence, signal, signal_detail, score)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (from_id, to_id, rel_type, confidence, signal, detail, score),
        )
        return cur.rowcount
    except Exception as e:
        print(f"  [!] insert error: {e}")
        return 0


# ── Détections ────────────────────────────────────────────────────────────────

def detect_entity_duplicates(cur, entities) -> int:
    """
    Signal entity_duplicate : même nom normalisé, entités différentes.
    Cible typique : 'Commune de Lasalle' (service) vs 'COMMUNE DE LASALLE' (business).
    """
    norm_map: dict[str, list[dict]] = {}
    for e in entities:
        key = normalize(e["name"])
        norm_map.setdefault(key, []).append(e)

    count = 0
    for group in norm_map.values():
        if len(group) < 2:
            continue
        for i, a in enumerate(group):
            for b in group[i + 1 :]:
                # Ignorer si déjà reliés dans relations
                already = cur.execute(
                    "SELECT 1 FROM relations WHERE (from_id=? AND to_id=?) OR (from_id=? AND to_id=?)",
                    (a["id"], b["id"], b["id"], a["id"]),
                ).fetchone()
                if already:
                    continue
                detail = f'"{a["name"]}" ({a["type"]}) ≈ "{b["name"]}" ({b["type"]})'
                count += insert_candidate(
                    cur, a["id"], b["id"], "doublon_probable", "probable",
                    "entity_duplicate", detail, 88
                )
    return count


def detect_maiden_names(cur, persons) -> int:
    """
    Signal maiden_name : personne avec nom marital (parenthèses SIRENE).
    "NOM (NOM DE NAISSANCE)" → liens vers tous les porteurs du nom de naissance.
    Score élevé : le signal est très fiable (source officielle SIRENE).
    """
    count = 0
    for p in persons:
        _, birth = parse_married_name(p["name"])
        if not birth:
            continue
        birth_norm = normalize(birth)

        for other in persons:
            if other["id"] == p["id"]:
                continue
            other_norm = normalize(other["name"])
            # Correspondance directe (le nom de naissance apparaît dans l'autre nom)
            if birth_norm in other_norm:
                detail = f'{p["name"]} → famille {birth} via {other["name"]}'
                count += insert_candidate(
                    cur, p["id"], other["id"], "famille_présumé", "probable",
                    "maiden_name", detail, 78
                )
            else:
                # L'autre a aussi ce nom entre parenthèses (même famille naissance)
                _, other_birth = parse_married_name(other["name"])
                if other_birth and normalize(other_birth) == birth_norm:
                    detail = f'Même famille de naissance {birth} : {p["name"]} / {other["name"]}'
                    count += insert_candidate(
                        cur, p["id"], other["id"], "famille_présumé", "probable",
                        "maiden_name", detail, 72
                    )
    return count


def detect_elu_sirene_match(cur) -> int:
    """
    Signal same_full_name : élu ou candidat retrouvé comme dirigeant dans SIRENE.
    Correspondance par nom normalisé (inclusion tolérée pour les prénoms composés).
    """
    elu_ids = {
        r[0] for r in cur.execute(
            "SELECT DISTINCT from_id FROM relations "
            "WHERE relation_type IN ('élu_cm','élu_cc','candidat')"
        ).fetchall()
    }
    sirene_ids = {
        r[0] for r in cur.execute(
            "SELECT DISTINCT from_id FROM relations WHERE source='sirene' "
            "AND relation_type IN ('dirigeant','gérant','président','associé','trésorier','secrétaire')"
        ).fetchall()
    }
    if not elu_ids or not sirene_ids:
        return 0

    def load(ids):
        ph = ",".join("?" * len(ids))
        return {
            e["id"]: e for e in cur.execute(
                f"SELECT id, name FROM entities WHERE id IN ({ph})", list(ids)
            ).fetchall()
        }

    elus = load(elu_ids)
    sirene = load(sirene_ids)

    count = 0
    for eid, ent in elus.items():
        en = normalize(ent["name"])
        for sid, sent in sirene.items():
            sn = normalize(sent["name"])
            if en == sn:
                score = 82
            elif en in sn or sn in en:
                score = 62
            else:
                continue
            detail = f'Élu "{ent["name"]}" ↔ SIRENE "{sent["name"]}"'
            count += insert_candidate(
                cur, eid, sid, "même_personne_probable", "probable",
                "same_full_name", detail, score
            )
    return count


def detect_rare_surnames(cur, persons) -> int:
    """
    Signal same_surname : patronyme rare (≤ MAX_SURNAME_FREQ) partagé entre personnes.
    Score faible — hypothèse à confirmer, non applicable aux patronymes courants
    (les trois ou quatre plus répandus de la commune).
    """
    surname_map: dict[str, dict] = {}
    for p in persons:
        for surname in extract_surnames(p["name"]):
            sn = normalize(surname)
            surname_map.setdefault(sn, {"surname": surname, "ids": []})
            if p["id"] not in surname_map[sn]["ids"]:
                surname_map[sn]["ids"].append(p["id"])

    count = 0
    for sn, data in surname_map.items():
        ids = data["ids"]
        freq = len(ids)
        if freq < 2 or freq > MAX_SURNAME_FREQ:
            # Trop rare (1) ou trop courant (>5) : on ignore
            continue
        # Score décroissant avec la fréquence : 2→42, 3→34, 4→26, 5→20
        score = max(20, 50 - freq * 8)
        for i, aid in enumerate(ids):
            for bid in ids[i + 1 :]:
                detail = (
                    f'Patronyme "{data["surname"]}" partagé '
                    f"({freq} personnes dans la DB) — à vérifier"
                )
                count += insert_candidate(
                    cur, aid, bid, "famille_présumé", "hypothesis",
                    "same_surname", detail, score
                )
    return count


def detect_toponyms(cur, entities) -> int:
    """
    Signal toponym : un nom de lieu (place) apparaît dans le nom d'une autre entité.
    Ex : "Château de X" (place) ↔ "SCI DU X" (business).
    """
    places = [e for e in entities if e["type"] == "place" and len(e["name"]) >= 4]
    count = 0
    for place in places:
        pn = normalize(place["name"])
        if len(pn) < 4:
            continue
        for e in entities:
            if e["id"] == place["id"] or e["type"] == "place":
                continue
            if pn in normalize(e["name"]):
                already = cur.execute(
                    "SELECT 1 FROM relations WHERE (from_id=? AND to_id=?) OR (from_id=? AND to_id=?)",
                    (e["id"], place["id"], place["id"], e["id"]),
                ).fetchone()
                if already:
                    continue
                detail = f'"{e["name"]}" contient le toponyme "{place["name"]}"'
                count += insert_candidate(
                    cur, e["id"], place["id"], "même_lieu_dit", "hypothesis",
                    "toponym", detail, 42
                )
    return count


def detect_subsidy_phantoms(cur) -> int:
    """
    Signal subsidy_entity_match : un bénéficiaire de subvention nommé dans un
    acte, mais qu'aucun registre n'atteste — ni SIREN, ni RNA — rapproché d'une
    vraie association ou d'un service déjà en base.

    ⚖️ Générique depuis le 23/09/2026. Le fantôme se reconnaissait à une PLAGE
    D'IDENTIFIANTS écrite en dur (`range(107, 122)`), relevée un jour sur la
    base de Lasalle. Sur une autre commune ces quinze identifiants désignent
    quinze entités quelconques, et le signal aurait rapproché n'importe quoi ;
    sur Lasalle même, les identifiants avaient bougé et il rendait 0. Le fantôme
    est une PROPRIÉTÉ — touché de l'argent public sans exister dans un registre
    — pas un numéro de ligne. Mesuré : 59 à Lasalle, 8 à Saillans, 3 à Brassac.
    """
    phantoms = cur.execute("""
        SELECT DISTINCT e.id, e.name FROM entities e
        JOIN financial_flows f ON f.to_id = e.id
        WHERE f.type LIKE 'subvention%'
          AND NOT EXISTS (SELECT 1 FROM businesses b
                           WHERE b.entity_id = e.id AND b.siren IS NOT NULL)
          AND NOT EXISTS (SELECT 1 FROM associations a
                           WHERE a.entity_id = e.id AND a.rna_id IS NOT NULL)
    """).fetchall()
    ph_ids = [p["id"] for p in phantoms] or [-1]
    real = cur.execute(
        "SELECT id, name FROM entities WHERE type IN ('association','service') "
        f"AND id NOT IN ({','.join('?'*len(ph_ids))})", ph_ids
    ).fetchall()

    # Un mot que portent beaucoup de noms ne désigne personne. Jusqu'au
    # 24/09/2026 le filtre était la LONGUEUR (> 3 lettres) : « Lasalle 2 GYM »
    # se réduisait à « lasalle », et ressortait à 100 % contre les soixante
    # structures dont le nom contient la commune — le bon candidat, LASALLE 2
    # GYMS, rejeté dans le même lot que le bruit. La fréquence est générique :
    # elle écarte la commune, le canton, « association », sans liste à tenir.
    frequence: dict[str, int] = {}
    for r in real:
        for w in set(normalize(r["name"]).split()):
            frequence[w] = frequence.get(w, 0) + 1

    def distinctifs(nom: str) -> list[str]:
        return [w for w in normalize(nom).split()
                if len(w) > 2 and frequence.get(w, 0) <= MAX_FREQ_MOT_DISTINCTIF]

    count = 0
    for ph in phantoms:
        ph_words = distinctifs(ph["name"])
        if not ph_words:
            continue
        for r in real:
            rn = normalize(r["name"])
            ratio = sum(1 for w in ph_words if w in rn) / len(ph_words)
            if ratio < 0.7:
                continue
            score = int(70 + ratio * 20)
            detail = (
                f'Subvention "{ph["name"]}" (id {ph["id"]}) → '
                f'RNA "{r["name"]}" ({int(ratio*100)}% de correspondance)'
            )
            count += insert_candidate(
                cur, ph["id"], r["id"], "doublon_probable", "probable",
                "subsidy_entity_match", detail, score
            )
    return count


# ── Main ──────────────────────────────────────────────────────────────────────

def run(dry_run=False, reset=False, signaux=SIGNAUX_PAR_DEFAUT):
    """Pose des candidats pour les `signaux` demandés. Rien d'autre n'est joué.

    Un signal absent de `signaux` n'est pas seulement tu : son détecteur ne
    tourne pas. Les deux signaux familiaux parcourent des dizaines de milliers
    de couples de personnes — les exécuter pour jeter le résultat coûterait la
    minute qu'on a cherché à ne pas payer.
    """
    inconnus = set(signaux) - set(TOUS_SIGNAUX)
    if inconnus:
        raise ValueError(f"signal inconnu : {', '.join(sorted(inconnus))} — "
                         f"valeurs : {', '.join(TOUS_SIGNAUX)}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()

    # Journaliser la passe, comme tout collecteur : c'est ce qui permet à la
    # file « Liens présumés » de dire POURQUOI elle est vide. Sans cette ligne,
    # un zéro y voudrait dire « jamais mesuré ici » alors qu'on vient de
    # chercher — cf. `collectors/files.py`. Pas en `--dry-run` : une mesure à
    # blanc n'est pas une passe, et la dater ferait croire à un relevé.
    avant = cur.execute("SELECT COUNT(*) FROM relation_candidates").fetchone()[0]
    run_id = None if dry_run else log_run_start(conn, "liens", avant)

    if reset:
        cur.execute("DELETE FROM relation_candidates WHERE review_status='pending'")
        print("[reset] Candidats pending supprimés.")

    # Chargement global (évite de multiples requêtes répétées)
    all_entities = [dict(r) for r in cur.execute("SELECT id, type, name FROM entities").fetchall()]
    persons = [e for e in all_entities if e["type"] == "person"]

    # Chaque détecteur est paresseux : `lambda`, pas un appel. Sans quoi les
    # six tourneraient pour qu'on en garde trois.
    DETECTEURS = {
        "entity_duplicate":     ("Doublons d'entités",
                                 lambda: detect_entity_duplicates(cur, all_entities)),
        "same_full_name":       ("Élus/candidats ↔ dirigeants SIRENE",
                                 lambda: detect_elu_sirene_match(cur)),
        "subsidy_entity_match": ("Bénéficiaires sans registre ↔ entités connues",
                                 lambda: detect_subsidy_phantoms(cur)),
        "toponym":              ("Toponymies (lieu dans nom d'entité)",
                                 lambda: detect_toponyms(cur, all_entities)),
        "maiden_name":          ("Noms de jeune fille (parenthèses SIRENE)",
                                 lambda: detect_maiden_names(cur, persons)),
        "same_surname":         ("Patronymes rares partagés",
                                 lambda: detect_rare_surnames(cur, persons)),
    }

    results = {}
    for rang, signal in enumerate(TOUS_SIGNAUX, 1):
        if signal not in signaux:
            continue
        titre, detecteur = DETECTEURS[signal]
        print(f"[{rang}] {titre}…")
        results[signal] = detecteur()
        print(f"    → {results[signal]}")

    eteints = [s for s in TOUS_SIGNAUX if s not in signaux]
    if eteints:
        # Un signal éteint doit se VOIR : sinon un zéro dans la file ressemble
        # à « rien à trouver » alors qu'il veut dire « on n'a pas cherché ».
        print(f"    (éteints, non joués : {', '.join(eteints)})")

    total = sum(results.values())
    tag = "[DRY-RUN] " if dry_run else ""
    print(f"\n{tag}Total : {total} nouveaux candidats")
    for sig, n in results.items():
        if n:
            print(f"  {sig:<25} {n}")

    if not dry_run:
        conn.commit()
        apres = cur.execute("SELECT COUNT(*) FROM relation_candidates").fetchone()[0]
        log_run_end(conn, run_id, "ok", apres, avant)
        print("Candidats enregistrés dans relation_candidates.")
    else:
        conn.rollback()
    conn.close()
    return results


if __name__ == "__main__":
    run(
        dry_run="--dry-run" in sys.argv,
        reset="--reset" in sys.argv,
        signaux=TOUS_SIGNAUX if "--tous-signaux" in sys.argv else SIGNAUX_PAR_DEFAUT,
    )
