"""La vie démocratique : scrutins, intercommunalité, élus, transparence.

Des registres publics — résultats électoraux, répartition des sièges,
Répertoire National des Élus, déclarations HATVP, décisions de justice
administrative. Chaque étape lit ses tables et écrit son fichier.
"""
from __future__ import annotations

from collections import Counter

from scripts.snapshot.relations import relation_meta_publique
from scripts.snapshot.socle import (COMMUNES_EPCI, EPCI_NOM_C2, EPCI_SIREN_C2, INSEE_C1, jour_utc,
                                    rows, table_exists, write_json)


def etape_elections(conn, out) -> dict:
    # ── Lot 2 : élections, fiscalité, élus officiels, urbanisme ───────────
    # Publication arbitrée le 26/07/2026. Aucune de ces sources ne portait de
    # page publique alors qu'elles répondent à des questions de premier plan
    # (« combien ont voté ? », « de combien sont mes impôts ? »).
    elections = {}
    if table_exists(conn, "elections_resultats"):
        elections["resultats"] = rows(conn, """
            SELECT scrutin, tour, date_tour, insee, commune, inscrits, votants,
                   abstentions, exprimes, blancs, nuls,
                   ROUND(100.0*votants/NULLIF(inscrits,0), 2) AS participation_pct
            FROM elections_resultats ORDER BY scrutin, tour, commune
        """)
        elections["listes"] = rows(conn, """
            SELECT scrutin, tour, insee, rang, libelle, libelle_abrege, nuance,
                   tete_de_liste, voix, pct_exprimes, sieges_cm, sieges_cc
            FROM elections_listes ORDER BY scrutin, tour, insee, voix DESC
        """)
    write_json(out / "elections.json", elections)

    return {"elections": elections}


def etape_intercommunalite(conn, out, horloge) -> None:
    # ── L'intercommunalité (périmètre C2) ────────────────────────────────
    # Réponse publique à « qu'est-ce qui ne se décide plus à la mairie ? ».
    # Trois briques : ce que l'EPCI exerce à la place de la commune, qui
    # siège pour en décider, et où Lasalle se situe parmi ses pairs.
    # Les entités des 14 autres communes ne sont pas publiées en fiche
    # (cf. `publiable_dans_perimetre`) : elles n'existent ici qu'agrégées.
    competences = rows(conn, """
        SELECT code, libelle, categorie, obligatoire, interet_communautaire
        FROM epci_competences
        ORDER BY obligatoire DESC, categorie, libelle
    """) if table_exists(conn, "epci_competences") else []

    # Un même délégué porte plusieurs relations `élu_cc` — une par source
    # (banatic, rne, cc_cac_site, élections_2026). Deux filtres, et l'ordre
    # entre les deux compte :
    #
    # 1. `until` — les mandats de source BANATIC (état du 15/10/2025) et du
    #    site de la CC (mandat 2020-2026) sont clos au 15/03/2026 par
    #    une reprise ponctuelle des mandats. Sans ce filtre, la page
    #    annonçait Gilles BEAUMANOIR président et Irène CHAPUIS
    #    vice-présidente : trois des quatre premiers noms de la liste
    #    n'étaient plus délégués depuis les municipales de mars 2026.
    # 2. déduplication par personne, en préférant la source la plus récente
    #    (RNE, publication du 11/08/2026) — sinon `nb_relations` double.
    delegues_bruts = rows(conn, """
        SELECT e.id, e.name, e.commune, r.relation_type, r.source, r.metadata
        FROM relations r
        JOIN entities e ON e.id = r.from_id
        WHERE r.relation_type IN ('élu_cc','vice_président_cc','président_cc')
          AND r.confidence IN ('verified','confirmed')
          AND e.confidence IN ('verified','confirmed')
          AND (r.until IS NULL OR r.until > ?)
        ORDER BY CASE r.source WHEN 'rne' THEN 0
                               WHEN 'élections_2026' THEN 1 ELSE 2 END,
                 CASE r.relation_type
                   WHEN 'président_cc' THEN 0
                   WHEN 'vice_président_cc' THEN 1 ELSE 2 END
    """, (jour_utc(horloge),))
    # Commune d'élection du délégué, prise dans le fichier RNE des
    # conseillers MUNICIPAUX — pas dans le fichier EPCI, qui rattache 22 des
    # 27 délégués à Val-d'Aigoual, commune du siège de l'intercommunalité.
    # `entities.commune` ne suffit pas : elle est vide pour les 8 délégués
    # créés par le seul import EPCI (BALSAN, BOSIO, EL RHAZOUI, FOUGERAY,
    # LIRON, PIALOT, ROMAZZOTTI, SERRAL), qui apparaissaient donc sans
    # commune. Recoupé avec BANATIC, ce rattachement rend exactement la
    # répartition des sièges par commune.
    commune_election = {
        r["entity_id"]: r["commune"] for r in rows(conn, """
            SELECT entity_id, commune FROM elus_rne
            WHERE mandat = 'cm' AND entity_id IS NOT NULL AND commune IS NOT NULL
        """)
    } if table_exists(conn, "elus_rne") else {}

    # Un RENOUVELLEMENT invalide toute liste antérieure.
    #
    # Le filtre `until` ci-dessus ne suffit pas : aucune source ne clôt les
    # mandats qu'elle publie, et la clôture posée à la main le 15/03/2026
    # avait disparu à la recollecte suivante. BANATIC, lui, DATE son état
    # (`etat_au`, écrit par le collecteur) : il suffit de le comparer à la
    # dernière élection municipale connue de la base. Un état arrêté au
    # 15/10/2025 décrit la mandature d'avant mars 2026 — ses 28 délégués
    # s'ajoutaient aux 22 du RNE et la page en annonçait 45.
    #
    # Les sources non datées sont conservées : on n'écarte que ce qu'on sait
    # périmé, jamais ce qu'on ignore.
    dernier_scrutin = (conn.execute(
        "SELECT MAX(date) FROM events WHERE type = 'election'").fetchone() or [None])[0]

    par_personne: dict[int, dict] = {}
    perimes: list[str] = []
    for d in delegues_bruts:
        if d["id"] in par_personne:
            continue
        etat_au = relation_meta_publique(d.get("metadata")).get("etat_au")
        if dernier_scrutin and etat_au and etat_au < dernier_scrutin:
            perimes.append(f"{d['name']} ({d['source']}, état du {etat_au})")
            continue
        fonction = relation_meta_publique(d.get("metadata")).get("fonction_rne") \
            or {"président_cc": "Président",
                "vice_président_cc": "Vice-président"}.get(d["relation_type"],
                                                           "Délégué")
        commune = commune_election.get(d["id"]) or d["commune"]
        par_personne[d["id"]] = {
            "name": d["name"],
            "commune": commune,
            # Vrai quand la commune vient du RNE des conseillers municipaux,
            # qui donne la commune d'élection. Faux quand elle n'est que le
            # rattachement de l'entité, non recoupé : l'UI ne doit pas
            # l'afficher comme un fait établi.
            "commune_fiable": d["id"] in commune_election,
            "relation_type": d["relation_type"],
            "fonction": fonction,
            "source": d["source"],
        }
    ordre = {"président_cc": 0, "vice_président_cc": 1}
    delegues = sorted(par_personne.values(),
                      key=lambda d: (ordre.get(d["relation_type"], 2),
                                     d["commune"] or "", d["name"]))

    # Comparaison de Lasalle à ses pairs. Le nombre de sièges au conseil
    # communautaire face au poids démographique est l'information la plus
    # parlante : c'est le pouvoir de vote réel de chaque commune.
    #
    # Il est compté sur la SEULE source BANATIC, et sur les relations CLOSES
    # aussi bien qu'actives — d'où une requête distincte de celle des
    # délégués. La répartition des sièges est fixée par arrêté préfectoral :
    # elle survit au scrutin, seuls les NOMS changent. Le RNE, lui, est
    # inexploitable pour ce décompte : il range 22 délégués sur 27 sous
    # Val-d'Aigoual, commune du siège de l'EPCI, et laisserait 13 communes
    # membres à zéro siège. Cf. memory-bank/known-issues.md.
    sieges = Counter(
        r["commune"] for r in rows(conn, """
            SELECT DISTINCT e.id, e.commune
            FROM relations r
            JOIN entities e ON e.id = r.from_id
            WHERE r.relation_type IN ('élu_cc','vice_président_cc','président_cc')
              AND r.source = 'banatic'
              AND e.confidence IN ('verified','confirmed')
        """) if r["commune"])
    delegues_hors_banatic = 0
    membres = []
    for insee, meta in COMMUNES_EPCI.items():
        nom = meta["nom"]
        membres.append({
            "insee": insee,
            "nom": nom,
            "population": meta.get("population"),
            "sieges": sieges.get(nom, 0),
            "est_commune_du_site": insee == INSEE_C1,
        })
    membres.sort(key=lambda m: -(m["population"] or 0))

    syndicats = rows(conn, """
        SELECT t.name, t.id
        FROM relations r
        JOIN entities t ON t.id = r.to_id
        WHERE r.relation_type = 'adhère_à' AND r.source = 'banatic'
          AND t.confidence IN ('verified','confirmed')
        ORDER BY t.name
    """)

    write_json(out / "intercommunalite.json", {
        "nom": EPCI_NOM_C2,
        "siren": EPCI_SIREN_C2,
        "population": sum((m["population"] or 0) for m in membres),
        "competences": competences,
        "competences_obligatoires": sum(1 for c in competences if c["obligatoire"]),
        "delegues": delegues,
        "membres": membres,
        "syndicats": syndicats,
        # Honnêteté de la source, à afficher tel quel par l'UI : les noms et
        # la répartition des sièges ne viennent pas du même endroit.
        "sieges_source": "BANATIC (répartition arrêtée le 15/10/2025)",
        "delegues_source": "Répertoire National des Élus (publication du 11/08/2026)",
        # Ce qui a été écarté comme périmé, et pourquoi : un compteur qui
        # tombe de 45 à 22 doit pouvoir s'expliquer sans relire le code.
        "delegues_ecartes": len(perimes),
        "delegues_ecartes_motif": (
            f"listes antérieures au scrutin du {dernier_scrutin}" if perimes else ""),
        "delegues_a_confirmer": delegues_hors_banatic,
        "note_sources": (
            "Les délégués sont ceux du Répertoire National des Élus, "
            "postérieur aux élections municipales de mars 2026. La "
            "répartition des sièges par commune vient de BANATIC : elle est "
            "fixée par arrêté préfectoral et ne change pas avec le scrutin. "
            "La commune de chaque délégué est celle de son mandat municipal "
            "au RNE : le fichier RNE des conseillers communautaires, lui, "
            "rattache 22 des 27 délégués au siège de l'intercommunalité et "
            "non à leur commune d'élection."
        ),
    })


def etape_elus(conn, out, public_ids) -> dict:
    # Élus : source autoritaire DGCL. `birth_year` et la CSP restent privés
    # (`publication_rules.people.publish_birth_year = false`).
    #
    # Filtrage sur les 15 communes de l'EPCI. `elus_rne` en contient
    # davantage : la collecte du 26/07/2026 portait sur l'ancien périmètre —
    # les 7 communes du vallon de la Salindrenque — et le recadrage du
    # 11/08 a délibérément conservé ces lignes en base (elles servent à
    # détecter les mandats croisés, cf. activeContext). Publiées telles
    # quelles, elles faisaient apparaître 20 conseils municipaux dont ceux
    # de Colognac, Vabres, Thoiras-Corbès, Sainte-Croix-de-Caderle et
    # Saint-Bonnet-de-Salendrinque, qui relèvent d'autres EPCI. Le filtre va
    # ici, pas dans une purge : la donnée reste exploitable en interne.
    elus = rows(conn, f"""
        SELECT mandat, insee, commune, nom, prenom, fonction,
               date_debut_mandat, date_debut_fonction, epci_nom, entity_id
        FROM elus_rne
        WHERE insee IN ({",".join("?" * len(COMMUNES_EPCI))})
        ORDER BY commune, mandat, nom
    """, tuple(COMMUNES_EPCI)) if table_exists(conn, "elus_rne") else []

    # `fiche` : cet élu a-t-il une page `/entite/<id>` sur le site ?
    #
    # NON pour la plupart. `publiable_dans_perimetre()` n'accorde de fiche à
    # une personne C2 que si elle SIÈGE au conseil communautaire ; les
    # conseillers municipaux des autres communes membres n'en ont pas, et
    # c'est délibéré (leur fiche agrégerait mandats, sociétés et marchés
    # pour des élus sans pouvoir de décision sur la commune).
    #
    # L'export les portait quand même avec leur `entity_id`, et la page en
    # faisait un lien : 152 liens morts sur Lasalle, 176 sur Brassac, 191
    # sur Saillans — soit 78 à 90 % des élus affichés, en production, vers
    # un 404. Relevé par un audit externe le 21/08/2026.
    #
    # La composition d'un conseil municipal reste publiée : c'est une donnée
    # du Répertoire National des Élus, registre public rediffusable. C'est
    # la FICHE qui est refusée, pas le nom. Seul cet endroit connaît
    # `public_ids` — la page ne peut pas recalculer ce booléen, et ne doit
    # pas essayer.
    elus = [{**e, "fiche": e.get("entity_id") in public_ids} for e in elus]
    write_json(out / "elus_rne.json", {
        "elus": elus,
        "total": len(elus),
        "total_avec_fiche": sum(1 for e in elus if e["fiche"]),
        "note_fiche": (
            "`fiche: false` signale un élu publié sans page dédiée : sa "
            "commune relève de l'intercommunalité et il ne siège pas au "
            "conseil communautaire. Ne pas construire de lien "
            "/entite/<entity_id> pour ces lignes."
        ),
    })

    return {"elus": elus}


def etape_transparence(conn, out) -> None:
    # ── Transparence : qui doit déclarer, et où en est sa déclaration ────
    # ⚖️ Ce fichier NOMME des personnes. Elles y figurent au titre d'une
    # fonction publique et d'un registre que la loi ordonne de publier —
    # c'est le même registre qui les nomme, et le lien y renvoie. Le contenu
    # des déclarations n'est pas collecté, donc pas publié.
    # Une absence de ligne ne dit pas « personne n'a déclaré » : sous
    # 20 000 habitants, la loi n'exige rien. La page doit l'écrire.
    hatvp = rows(conn, """
        SELECT portee, prenom, nom, qualite, type_document, statut,
               date_depot, date_publication, url
          FROM hatvp_declarations ORDER BY portee, nom
    """) if table_exists(conn, "hatvp_declarations") else []
    # Les décisions de justice administrative citant la commune. Le TITRE,
    # la juridiction, la date, le numéro et le lien vers Légifrance — jamais
    # l'extrait conservé en base. Les textes de JADE sont pseudonymisés, mais
    # un extrait de quatre cents caractères reste du récit d'affaire : le
    # lien renvoie au texte intégral chez celui qui l'établit.
    justice = rows(conn, """
        SELECT portee, juridiction, date_dec, numero, titre, type_recours, url
          FROM justice_decisions ORDER BY date_dec DESC
    """) if table_exists(conn, "justice_decisions") else []
    write_json(out / "transparence.json", {
        "hatvp": hatvp,
        "justice": justice,
        "total": len(hatvp),
        "note": "Liste des responsables publics soumis à l'obligation de "
                "déclaration (HATVP). Sous 20 000 habitants, l'obligation ne "
                "s'applique généralement pas : une liste vide ne signale "
                "aucun manquement.",
    })
