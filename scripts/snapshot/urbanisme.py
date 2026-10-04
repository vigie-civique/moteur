"""L'urbanisme : autorisations, document d'urbanisme, et les parcelles qui croisent DVF.

Les autorisations d'urbanisme sont un registre public, mais le demandeur
d'un permis est souvent un particulier : son adresse ne sort pas, et un
renvoi vers une fiche non publiée est retiré.
"""
from __future__ import annotations

from scripts.snapshot.socle import rows, table_exists, write_json


def etape_urbanisme(conn, out, public_ids) -> dict:
    urbanisme_rows = rows(conn, """
        SELECT num_dau, insee, commune, categorie, type_dau, type_label,
               date_depot, date_autorisation, date_achevement,
               demandeur_nom, demandeur_siren, demandeur_entity_id,
               adresse, lieu_dit, cadastre_ref, superficie_terrain,
               nb_logements, surface_hab_creee, surface_loc_creee, residence
        FROM urbanisme_autorisations ORDER BY date_depot DESC, commune
    """) if table_exists(conn, "urbanisme_autorisations") else []
    urbanisme_public = []
    adresses_retirees = 0
    renvois_retires = 0
    for u in urbanisme_rows:
        u = dict(u)
        # Prudence : sans personne morale nommée, le demandeur est un
        # particulier. On garde le lieu-dit et la parcelle (le croisement DVF
        # et la lecture territoriale sont préservés) mais pas la voie exacte.
        if not u.get("demandeur_nom"):
            if u.get("adresse"):
                adresses_retirees += 1
            u["adresse"] = None
        # Un identifiant d'entité PROMET une fiche. Le demandeur d'un permis
        # est très souvent hors périmètre publiable — 66 lignes sur Lasalle,
        # 199 sur Brassac, 168 sur Saillans pointaient vers une fiche
        # absente. Aucune page du site ne lit ce champ ; il ne sert donc
        # qu'au lecteur du JSON, à qui il ment. On le retire plutôt que de
        # le laisser désigner un 404.
        if u.get("demandeur_entity_id") and u["demandeur_entity_id"] not in public_ids:
            u["demandeur_entity_id"] = None
            renvois_retires += 1
        u["date_precision"] = "annee"   # cf. contrôle de divulgation SDES
        urbanisme_public.append(u)
    # Le document d'urbanisme au GPU, et ce qu'il fait du territoire. Les
    # parts ne sortent QUE si la couverture a été vérifiée — le collecteur
    # les laisse à NULL sinon, et le JSON transporte le contrôle avec elles.
    plu_documents = rows(conn, """
        SELECT insee, partition, titre, du_type, portee, date_appro,
               gpu_status, gpu_maj
          FROM urbanisme_documents WHERE couvre = 1 ORDER BY insee, date_appro
    """) if table_exists(conn, "urbanisme_documents") else []
    plu_zonage = rows(conn, """
        SELECT insee, typezone, famille, zones, aire_m2, part_pct, couverture
          FROM urbanisme_zonage ORDER BY insee, part_pct DESC
    """) if table_exists(conn, "urbanisme_zonage") else []
    plu_statut = rows(conn, """
        SELECT insee, nom, rnu, aire_km2, documents, releve_le
          FROM urbanisme_statut ORDER BY insee
    """) if table_exists(conn, "urbanisme_statut") else []

    write_json(out / "urbanisme.json", {
        "documents": plu_documents,
        "zonage": plu_zonage,
        "statut": plu_statut,
        "autorisations": urbanisme_public,
        "total": len(urbanisme_public),
        "note_dates": "Dates ramenées à l'année pour les petites communes "
                      "(contrôle de divulgation statistique du SDES).",
        "renvois_demandeur_retires": renvois_retires,
    })

    return {"urbanisme_public": urbanisme_public, "adresses_retirees": adresses_retirees}


def etape_croisement_foncier(conn, out) -> dict:
    # Parcelles portant à la fois une mutation DVF et une autorisation.
    croisement_foncier = rows(conn, """
        SELECT u.cadastre_ref, u.commune, u.num_dau, u.date_depot,
               u.demandeur_nom, u.nb_logements, COUNT(d.id) AS mutations,
               MIN(d.date) AS premiere_mutation, MAX(d.date) AS derniere_mutation
        FROM urbanisme_autorisations u
        JOIN dvf_transactions d ON d.cadastre_ref = u.cadastre_ref
        WHERE u.cadastre_ref IS NOT NULL
        GROUP BY u.id ORDER BY u.date_depot DESC
    """) if (table_exists(conn, "urbanisme_autorisations")
             and table_exists(conn, "dvf_transactions")) else []
    write_json(out / "croisement_foncier.json", {
        "parcelles": croisement_foncier, "total": len(croisement_foncier)})

    return {"croisement_foncier": croisement_foncier}
