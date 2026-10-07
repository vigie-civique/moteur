#!/usr/bin/env python3
"""Amorce une base minimale pour l'intégration continue.

Cinq entités, un acte, deux élus et une autorisation d'urbanisme, choisis pour
que la chaîne complète ait quelque chose à filtrer : une entreprise de la
commune qui doit sortir, une entreprise d'une commune membre qui ne doit pas,
une personne sans rôle civique qui ne doit pas non plus, et — depuis le
21/08/2026 — deux élus dont un seul a droit à une fiche, plus un permis dont le
demandeur n'en a pas. Le snapshot construit dessus vaut assertion de bout en bout — si le
filtre se relâche, le compte publié change et le contrôle d'étanchéité le voit.

Une base vide ne suffisait pas : SvelteKit refuse de terminer un build où une
route dynamique déclarée prérendable ne produit aucune page. C'est un contrôle
utile en production, on ne le désactive pas pour arranger la CI.

    VIGIE_DB=db/ci.db python3 tests/amorcer_base_ci.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("VIGIE_INSTANCE", str(Path(__file__).parent / "instance_test.json"))
sys.path.insert(0, str(ROOT))

from collectors.config import DB_PATH                     # noqa: E402
from collectors.rne import ensure_table as rne_ensure_table          # noqa: E402
from collectors.urbanisme_sitadel import ensure_table as sitadel_ensure_table  # noqa: E402


def main() -> int:
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))

    def entite(type_, nom, commune, perimetre, confidence="verified"):
        return conn.execute(
            "INSERT INTO entities (type, name, commune, perimetre, confidence) "
            "VALUES (?,?,?,?,?)", (type_, nom, commune, perimetre, confidence)
        ).lastrowid

    publiable = entite("business", "Boulangerie d'épreuve", "Testonville", "C1")
    voisin = entite("business", "Commerce de Voisinbourg", "Voisinbourg", "C2")
    entite("person", "Une habitante", "Testonville", "C1")

    # Un élu de la commune (fiche) et un conseiller d'une commune membre (pas de
    # fiche : `publiable_dans_perimetre` ne l'accorde à une personne C2 que si
    # elle siège au conseil communautaire). Sans ces deux lignes, la CI ne
    # traversait JAMAIS l'export des élus — `elus_rne` n'est pas dans
    # `db/schema.sql`, elle est créée par son collecteur, donc `table_exists()`
    # rendait faux et le bloc entier était sauté. C'est ce trou qui a laissé
    # passer 152 à 191 liens morts par instance jusqu'au 21/08/2026.
    mairie = entite("service", "Mairie d'épreuve", "Testonville", "C1")
    elu_publiable = entite("person", "Élue de Testonville", "Testonville", "C1")
    elu_sans_fiche = entite("person", "Conseiller de Voisinbourg", "Voisinbourg", "C2")
    # Le mandat rend l'élue publiable : une personne ne sort qu'au titre d'un
    # rôle civique (`people.publish_only_with_relation_types`). Sans lui, les
    # DEUX élus seraient sans fiche et la CI ne verrait jamais le cas passant —
    # un correctif qui mettrait `fiche: false` partout passerait le contrôle.
    conn.execute(
        "INSERT INTO relations (from_id, to_id, relation_type, confidence) "
        "VALUES (?,?,'maire','verified')", (elu_publiable, mairie))
    rne_ensure_table(conn)
    for mandat, insee, commune, nom, prenom, eid in (
            ("cm", "99001", "Testonville", "ÉPREUVE", "Élue", elu_publiable),
            ("cm", "99002", "Voisinbourg", "VOISIN", "Conseiller", elu_sans_fiche)):
        conn.execute(
            "INSERT INTO elus_rne (mandat, insee, commune, nom, prenom, "
            "date_debut_mandat, entity_id) VALUES (?,?,?,?,?,'2026-03-22',?)",
            (mandat, insee, commune, nom, prenom, eid))

    # Une autorisation dont le demandeur n'a pas de fiche : le builder doit
    # retirer le renvoi plutôt que de le laisser désigner un 404.
    sitadel_ensure_table(conn)
    conn.execute(
        "INSERT INTO urbanisme_autorisations (num_dau, insee, commune, categorie,"
        " type_dau, type_label, date_depot, demandeur_nom, demandeur_entity_id)"
        " VALUES ('99001260001','99001','Testonville','logements','PC',"
        "'Permis de construire','2026-01-01','Commerce de Voisinbourg',?)",
        (voisin,))

    # La source doit figurer dans l'allowlist des règles d'EXEMPLE, qui ne
    # connaît que les sources nationales : les sources locales (« CM »,
    # « CR CM ») se déclarent instance par instance. Un acte publié avec la
    # source « CM » serait donc écarté ici, et la CI construirait un site sans
    # aucun acte — or c'est justement ce parcours qu'elle doit vérifier.
    conn.execute(
        "INSERT INTO events (type, date, title, content, source) "
        "VALUES ('election','2026-01-15','Scrutin d''épreuve',"
        "'Résultats publiés par le ministère.','interieur')")
    conn.execute(
        "INSERT INTO event_entities (event_id, entity_id, role) VALUES (?,?,'sujet')",
        (conn.execute("SELECT MAX(id) FROM events").fetchone()[0], publiable))
    conn.commit()

    n_actes = amorcer_deliberations(conn, publiable)
    n_extraits = amorcer_marches_extraits(conn)
    regles = ecrire_regles_ci()
    n_dossiers = amorcer_dossiers(conn, regles) if os.environ.get("VIGIE_CI_DOSSIERS") else 0
    n_seances = amorcer_conseils(conn) if os.environ.get("VIGIE_CI_DOSSIERS") else 0

    total = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    conn.close()
    print(f"[ci] {DB_PATH} amorcée — {total} entités, dont 1 seule publiable ; "
          f"{n_actes} actes d'assemblée ; {n_dossiers} dossiers retenus ; "
          f"{n_seances} séance relue ; {n_extraits} marché lu en attente ; "
          f"règles : {regles}")
    return 0


# ─── Les actes d'assemblée ───────────────────────────────────────────────────
# Ajoutés le 03/10/2026. Jusque-là la base de la CI n'avait AUCUNE délibération
# avec texte : une régression des extraits (`extrait/<id>.json`, le texte déplié
# sous chaque acte) est passée verte, faute d'un seul acte à extraire. Ils sont
# aussi ce qu'il faut au graphe des liens : deux années qui réemploient le même
# numéro (la clé doit les distinguer), les deux assemblées, une séance qui a pris
# plusieurs actes (une citation par date y est imprécise), un acte sans numéro
# (clé faible, jamais une ancre).
#
# La source est le domaine de l'instance, comme `scripts/init_instance.py` le
# déclare publiable : c'est ainsi qu'une vraie instance publie ses actes.

SOURCE_COMMUNE = "exemple.invalid"
SOURCE_EPCI = "epci.exemple.invalid"

ACTES = (
    # type, date, numéro d'acte, titre, texte, montants, vote
    ("deliberation", "2021-04-14", "41", "Protection des captages : périmètres et servitudes",
     "Le conseil municipal, après en avoir délibéré, décide la protection à 80 % de la "
     "ressource en eau du captage du bourg et approuve les périmètres proposés.",
     [], {"pour": 13, "contre": 0, "abstention": 2, "unanimite": False}),
    ("deliberation", "2021-04-14", "42", "Budget primitif 2021 du service de l'eau",
     "Le conseil municipal adopte le budget primitif 2021 de la régie de l'eau, équilibré "
     "en section d'exploitation à 61 500 €.",
     [{"montant": 61500.0, "context": "équilibré à 61 500 €"}], {"unanimite": True}),
    # Le MÊME numéro, l'année suivante : une clé sans année les confondrait.
    ("deliberation", "2022-05-11", "41", "Tarifs de l'eau : abonnement et part variable",
     "Le conseil municipal fixe l'abonnement annuel à 45 € et la part variable à "
     "1,20 € le mètre cube à compter du 1er juillet 2022.",
     [{"montant": 45.0, "context": "abonnement annuel à 45 €"}], {"unanimite": True}),
    # Sans numéro d'acte ni de séance : la clé repose sur le titre, elle est faible.
    ("deliberation", "2023-03-06", None, "Compte administratif 2022 de la régie de l'eau",
     "Le conseil municipal approuve le compte administratif 2022 : 27 980 € de dépenses "
     "d'exploitation.",
     [{"montant": 27980.0, "context": "27 980 € de dépenses"}], {"unanimite": True}),
    ("deliberation_cc", "2025-04-02", "12", "Redevance pour pollution domestique",
     "Le conseil communautaire approuve le reversement de 2 064 € de redevance à "
     "l'Agence de l'eau au titre de l'exercice 2024.",
     [{"montant": 2064.0, "context": "reversement de 2 064 €"}], {"unanimite": True}),
    ("deliberation_cc", "2024-06-20", "12", "Adhésion au service commun d'instruction",
     "Le conseil communautaire approuve l'adhésion au service commun d'instruction des "
     "autorisations d'urbanisme.", [], {"pour": 30, "contre": 1, "abstention": 0}),
    # En dernier, pour ne décaler l'identifiant d'aucun acte de la référence.
    # Un marché attribué en conseil, sous le seuil de publicité : il ne se lit
    # que là. Sa ligne extraite attend une relecture (`amorcer_marches_extraits`).
    ("deliberation", "2023-09-18", "57", "Toiture de l'école : attribution du marché",
     "Le conseil municipal attribue le marché de réfection de la toiture de l'école à "
     "l'entreprise Couvreurs d'épreuve pour un montant de 18 450 € HT, au terme d'une "
     "procédure adaptée.",
     [{"montant": 18450.0, "context": "18 450 € HT"}], {"unanimite": True}),
)

SEANCES = (("conseil_municipal", "2021-04-14", "Conseil municipal du 14 avril 2021"),
           ("conseil_communautaire", "2025-04-02", "Conseil communautaire du 2 avril 2025"))


def amorcer_deliberations(conn, entite_concernee: int) -> int:
    import json
    from collectors.cle_acte import cle_de_ligne
    for type_, date, titre in SEANCES:
        source = SOURCE_EPCI if type_ == "conseil_communautaire" else SOURCE_COMMUNE
        cle = cle_de_ligne(type_, date, {}, titre)
        conn.execute(
            "INSERT INTO events (type, date, title, source, source_url, metadata, cle_acte) "
            "VALUES (?,?,?,?,?,?,?)",
            (type_, date, titre, source, f"https://{source}/pv/{date}.pdf",
             json.dumps({"pieces": [{"nature": "proces_verbal", "libelle": f"PV du {date}",
                                     "url": f"https://{source}/pv/{date}.pdf"}]}),
             cle.valeur))
    for type_, date, numero, titre, texte, montants, vote in ACTES:
        source = SOURCE_EPCI if type_ == "deliberation_cc" else SOURCE_COMMUNE
        meta = {"numero_acte": numero, "numero_seance": None, "montants": montants,
                "vote": vote, "categorie": "eau", "regime": "actes_teletransmis"}
        cle = cle_de_ligne(type_, date, meta, titre)
        eid = conn.execute(
            "INSERT INTO events (type, date, title, content, source, source_url, metadata, "
            "cle_acte) VALUES (?,?,?,?,?,?,?,?)",
            (type_, date, titre, texte, source,
             f"https://{source}/actes/{date}-{numero or 'sn'}.pdf",
             json.dumps(meta, ensure_ascii=False), cle.valeur)).lastrowid
        if type_ == "deliberation_cc" and numero == "12" and date.startswith("2025"):
            # Une personne MORALE que l'acte concerne : l'index par SIREN
            # (`personnes_morales.json`) doit avoir une ligne à publier.
            conn.execute("INSERT INTO event_entities (event_id, entity_id, role) "
                         "VALUES (?,?,'beneficiaire')", (eid, entite_concernee))
    conn.execute("INSERT OR IGNORE INTO businesses (entity_id, siren) VALUES (?, '999000001')",
                 (entite_concernee,))
    conn.commit()
    return len(ACTES)


# ─── Un marché lu dans un procès-verbal, en attente de relecture ─────────────
# Ajouté le 04/10/2026 avec `collectors/marches_extraits.py`. La base de la CI
# n'a AUCUN marché publié : /marches y affiche son zéro, et ce zéro doit dire
# qu'une attribution lue attend sa relecture — sans la publier. Déposée par le
# vrai chemin, pour que le contrôle porte sur lui et non sur une copie.

def amorcer_marches_extraits(conn) -> int:
    from collectors import marches_extraits
    from collectors.config import COMMUNE_NAME, COMMUNE_SIREN
    eid = conn.execute("SELECT id FROM events WHERE type='deliberation' "
                       "AND date='2023-09-18'").fetchone()[0]
    uid = conn.execute("INSERT INTO users (email, password_hash, role) "
                       "VALUES ('ci@exemple.invalid', '-', 'validator')").lastrowid
    bilan = marches_extraits.deposer(conn, {"format": marches_extraits.FORMAT, "lignes": [{
        "event_id": eid, "date": "2023-09-18",
        "objet": "Réfection de la toiture de l'école",
        "citation": "attribue le marché de réfection de la toiture de l'école à "
                    "l'entreprise Couvreurs d'épreuve pour un montant de 18 450 € HT",
        "acheteur_nom": f"Commune de {COMMUNE_NAME}", "acheteur_siren": COMMUNE_SIREN,
        "titulaire": "Couvreurs d'épreuve", "montant": 18450, "devise_base": "HT",
        "procedure": "adaptée", "nature": "travaux"}]},
        {"id": uid, "email": "ci@exemple.invalid"})
    # Une date fixe : `couverture.json` publie celle du dernier dépôt, et le
    # snapshot de référence doit être le même quel que soit le jour.
    conn.execute("UPDATE propositions SET propose_le='2026-10-04 09:00:00'")
    conn.commit()
    assert bilan["proposees"] == 1, bilan
    return bilan["proposees"]


def ecrire_regles_ci() -> Path:
    """Les règles d'exemple, plus les deux domaines de l'instance factice —
    exactement ce que `scripts/init_instance.py` ajoute pour une vraie
    instance. Sans eux, aucun acte d'assemblée ne sortirait, et la CI
    construirait un site sans délibérations : le parcours qu'elle doit voir."""
    import json
    from collectors.config import CODE_POSTAL, COMMUNE_INSEE, COMMUNE_NAME
    regles = json.loads((ROOT / "config" / "publication_rules.exemple.json").read_text())
    # La commune aussi, comme `init_instance.py` : sans elle le contrôleur ne
    # peut pas juger la part de la commune dans ce qui sort, et il refuse.
    regles["project"] = {
        "public_name": f"Vigie Civique {COMMUNE_NAME}",
        "private_name": f"Atelier Vigie Civique {COMMUNE_NAME}",
        "commune": COMMUNE_NAME,
        "insee": COMMUNE_INSEE,
        "postal_code": CODE_POSTAL,
    }
    sources = set(regles.setdefault("events", {}).get("public_sources", []))
    regles["events"]["public_sources"] = sorted(sources | {SOURCE_COMMUNE, SOURCE_EPCI})
    chemin = Path(DB_PATH).with_suffix(".regles.json")
    chemin.write_text(json.dumps(regles, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return chemin


# ─── Les dossiers ────────────────────────────────────────────────────────────
# Un dossier inventé (tests/fixtures/dossiers/), sans personne physique, qui
# cite les actes ci-dessus comme les vrais dossiers les citent. Il est RETENU,
# son sceau est posé comme l'atelier le pose, puis un acte cité est « relu à
# l'OCR » : le build doit publier le dossier AVEC son bandeau de péremption.
#
# Seulement sous `VIGIE_CI_DOSSIERS=1`, que pose le job `site` : la copie va
# dans `dossiers/` à la racine du dépôt, qui est celui d'une instance quand on
# travaille sur une instance. Ni un poste de développement ni la suite pytest
# (qui rejoue ce script) n'ont à y trouver un dossier d'épreuve.

def amorcer_dossiers(conn, regles_chemin: Path) -> int:
    import json
    import shutil
    from collectors import dossiers as D
    from collectors.citations import index_selon_regles, relier
    regles = json.loads(Path(regles_chemin).read_text())
    D.assurer_schema(conn)
    n = 0
    for source in sorted((ROOT / "tests" / "fixtures" / "dossiers").glob("*.md")):
        cible = D.chemin(ROOT, source.stem)
        cible.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, cible)
        did = D.identifiant(conn, source.stem, creer=True)
        emp = D.empreinte_de(cible)
        conn.execute(
            "INSERT INTO annotations(object_type, object_id, review_status, reviewed_by, "
            "reviewed_at, empreinte) VALUES('dossier', ?, 'retenu', 'ci', "
            "'2026-10-01 10:00:00', ?)", (did, emp))
        D.sceller(conn, did, emp, relier(cible.read_text(encoding="utf-8"),
                                         index_selon_regles(conn, regles)),
                  "2026-10-01 10:00:00")
        n += 1
    # La relecture OCR d'un titre, après le verdict : le bandeau doit le dire.
    conn.execute("UPDATE events SET title = 'Budget primitif 2021 du service de l''eau (relu)' "
                 "WHERE type='deliberation' AND date='2021-04-14' "
                 "AND json_extract(metadata, '$.numero_acte') = '42'")
    conn.commit()
    return n


# ─── Les conseils en clair ───────────────────────────────────────────────────
# Ajouté le 04/10/2026 (lot 0 de docs/refonte-du-contenu.md). La base de la CI
# n'avait AUCUNE séance relue : `conseils.json` sortait vide, aucune feuille
# n'était écrite, et tout ce que la refonte construit sur les séances — la page
# de séance, ses deux nombres, les retours depuis les actes — n'aurait été
# éprouvé nulle part. Une séance municipale inventée (tests/fixtures/conseils/),
# qui relève les deux actes du 14/04/2021 ci-dessus, RETENUE comme l'atelier
# la retient : le verdict signe l'empreinte du relevé lu.
#
# Même condition que les dossiers, et pour la même raison : la copie va dans
# `data/conseils/`, le répertoire d'une instance.

def amorcer_conseils(conn) -> int:
    import shutil
    from collectors.dossiers import assurer_schema
    from collectors.en_clair.seances import dossier, releves, seance_id
    from collectors.verdict import empreinte
    assurer_schema(conn)        # la colonne `empreinte` des verdicts
    cible = dossier(ROOT)
    shutil.copytree(ROOT / "tests" / "fixtures" / "conseils", cible, dirs_exist_ok=True)
    n = 0
    for chemin, releve in releves(ROOT):
        sid = seance_id(conn, releve)
        if sid is None:
            continue
        conn.execute(
            "INSERT INTO annotations(object_type, object_id, review_status, reviewed_by, "
            "reviewed_at, empreinte) VALUES('en_clair', ?, 'retenu', 'ci', "
            "'2026-10-01 10:00:00', ?)", (sid, empreinte(chemin.read_bytes())))
        n += 1
    conn.commit()
    return n


if __name__ == "__main__":
    sys.exit(main())
