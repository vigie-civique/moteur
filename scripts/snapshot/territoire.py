"""Le territoire : son environnement, son portrait, sa fiscalité.

Des données de service public et d'open data, sans personne derrière — eau
des rivières et du robinet, déchets, forêt et feux, risques, parc de
logements, INSEE, équipements, mobilité, cadastre, télécoms, accueil du jeune
enfant. Chaque étape lit ses tables et écrit son fichier.
"""
from __future__ import annotations

from scripts.snapshot.socle import INSEE_C1, row, rows, table_exists, write_json


# ── Ce que les dossiers thématiques ont fait collecter, sur les pages ────────
#
# Un dossier (`/dossiers`) est un texte relu ; ses chiffres, eux, viennent de
# collecteurs (`eau_potable`, `dechets`, `incendie`, `enfance`, les repères de
# `fiscalite`). Ils sortent ici en données, pour les pages qu'ils concernent.
# Chaque export qualifie ce qu'il rend, pour que la page n'ait rien à décider :
#   - une MAILLE qui n'est pas la commune (la collectivité qui collecte les
#     déchets, l'intercommunalité pour la CAF, l'école pour les élèves) est
#     nommée dans la donnée ;
#   - un ZÉRO ne sort que s'il a été mesuré : un réseau d'eau sans prélèvement
#     publié n'est pas un réseau conforme, « aucun feu » ne vaut que sur une
#     période lue ;
#   - une COMPARAISON ne se fait qu'à année égale.

def export_eau_potable(conn, insee: str) -> dict | None:
    """Le contrôle sanitaire de l'ARS, par réseau desservant la commune.

    Les réseaux sont ceux de la DERNIÈRE année de desserte publiée : la base
    porte aussi des réseaux voisins, arrivés par un prélèvement partagé."""
    if not table_exists(conn, "eau_potable_udi"):
        return None
    annee = conn.execute("SELECT MAX(annee) FROM eau_potable_udi WHERE code_commune=?",
                         (insee,)).fetchone()[0]
    if not annee:
        return None
    reseaux = []
    for u in rows(conn, """
            SELECT code_reseau, MAX(nom_reseau) AS nom,
                   group_concat(DISTINCT NULLIF(NULLIF(nom_quartier, ''), '-')) AS quartiers
              FROM eau_potable_udi WHERE code_commune=? AND annee=?
             GROUP BY code_reseau ORDER BY code_reseau""", (insee, annee)):
        depuis = ("FROM eau_potable_prelevement_reseaux r JOIN eau_potable_prelevements p"
                  " USING (code_prelevement) WHERE r.code_reseau=?")
        t = row(conn, f"""
            SELECT COUNT(*) AS prelevements, substr(MIN(p.date_prelevement), 1, 10) AS du,
                   substr(MAX(p.date_prelevement), 1, 10) AS au,
                   COALESCE(SUM(p.limites_bact = 'N'), 0) AS bacteriologie,
                   COALESCE(SUM(p.limites_pc = 'N'), 0) AS chimie,
                   COALESCE(SUM(p.references_bact = 'N' OR p.references_pc = 'N'), 0) AS hors_references
              {depuis}""", (u["code_reseau"],))
        qui = row(conn, f"""
            SELECT p.nom_moa AS maitre_ouvrage, p.nom_distributeur AS exploitant {depuis}
               AND p.nom_moa IS NOT NULL ORDER BY p.date_prelevement DESC LIMIT 1""",
                  (u["code_reseau"],)) or {}
        reseaux.append({
            "code": u["code_reseau"], "nom": u["nom"],
            "quartiers": sorted(q for q in (u["quartiers"] or "").split(",") if q),
            **qui, **t,
            "par_annee": rows(conn, f"""
                SELECT substr(p.date_prelevement, 1, 4) AS annee, COUNT(*) AS prelevements,
                       SUM(p.limites_bact = 'N') AS bacteriologie, SUM(p.limites_pc = 'N') AS chimie
                  {depuis} GROUP BY annee ORDER BY annee""", (u["code_reseau"],)),
            "hors_limites": rows(conn, f"""
                SELECT substr(p.date_prelevement, 1, 10) AS date,
                       p.limites_bact = 'N' AS bacteriologie, p.limites_pc = 'N' AS chimie
                  {depuis} AND (p.limites_bact = 'N' OR p.limites_pc = 'N')
                 ORDER BY p.date_prelevement DESC""", (u["code_reseau"],)),
        })
    return {"annee_desserte": annee, "reseaux": reseaux}


DECHETS_INDICATEURS = ("omr", "tri", "papier", "verre", "decheterie", "total")


def _quart(valeur, r: dict | None) -> int | None:
    """Dans quel quart des collectivités tombe la valeur (1 = le plus bas)."""
    if valeur is None or not r or None in (r["p25"], r["p50"], r["p75"]):
        return None
    return 1 + sum(valeur > r[k] for k in ("p25", "p50", "p75"))


def export_dechets(conn, insee: str) -> dict | None:
    """Les déchets ménagers, à la maille de la collectivité qui les collecte."""
    if not table_exists(conn, "dechets_desserte"):
        return None
    annee = conn.execute("SELECT MAX(annee) FROM dechets_desserte WHERE insee=?",
                         (insee,)).fetchone()[0]
    if not annee:
        return None
    acteurs = []
    for a in rows(conn, """
            SELECT code_acteur AS code, MAX(acteur) AS nom FROM dechets_desserte
             WHERE insee=? AND annee=? GROUP BY code_acteur ORDER BY code_acteur""",
                  (insee, annee)):
        # `papier` est arrivé après les autres : une base pas encore recollectée
        # n'a pas la colonne, et la page s'en passe.
        papier = "papier" if "papier" in {r[1] for r in conn.execute(
            "PRAGMA table_info(dechets_performance)")} else "NULL AS papier"
        serie = rows(conn, f"""
            SELECT annee, population, typologie, omr, tri, {papier}, verre, decheterie, total,
                   total_gravats FROM dechets_performance WHERE code_acteur=? ORDER BY annee""",
                     (a["code"],))
        # Un zéro n'est pas une collecte nulle : c'est un service que CETTE
        # collectivité n'exerce pas (un syndicat de traitement ne ramasse pas
        # les poubelles). Publié tel quel, il se lirait « 0 kg d'ordures par
        # habitant » — et les repères, eux, écartent déjà les zéros.
        for s in serie:
            for i in DECHETS_INDICATEURS:
                if s[i] == 0:
                    s[i] = None
        situer = None
        if serie:
            dernier = serie[-1]
            reperes = {(r["indicateur"], r["portee"]): r for r in rows(
                conn, "SELECT * FROM dechets_reperes WHERE annee=?", (dernier["annee"],))}
            situer = [{
                "indicateur": i, "valeur": dernier[i],
                "france": reperes.get((i, "france")),
                "departement": reperes.get((i, "departement")),
                "quart": _quart(dernier[i], reperes.get((i, "france"))),
            } for i in DECHETS_INDICATEURS if dernier[i] is not None]
            # Le total additionne ordures, collecte séparée et déchèterie. Si
            # la collectivité n'exerce pas l'un des trois, son total est
            # PARTIEL : le comparer à la médiane des totaux la placerait « dans
            # le quart le plus bas » pour une compétence qu'elle n'a pas.
            if any(dernier[i] is None for i in ("omr", "tri", "decheterie")):
                situer = [s for s in situer if s["indicateur"] != "total"]
        tonnes = lambda axe: rows(conn, """
            SELECT libelle, tonnes FROM dechets_tonnes
             WHERE code_acteur=? AND axe=? AND tonnes > 0
               AND annee=(SELECT MAX(annee) FROM dechets_tonnes WHERE code_acteur=? AND axe=?)
             ORDER BY tonnes DESC""", (a["code"], axe, a["code"], axe))
        annee_tonnes = lambda axe: conn.execute(
            "SELECT MAX(annee) FROM dechets_tonnes WHERE code_acteur=? AND axe=?",
            (a["code"], axe)).fetchone()[0]
        acteurs.append({
            **a,
            "services": [r["service"] for r in rows(conn, """
                SELECT service FROM dechets_desserte WHERE insee=? AND annee=? AND code_acteur=?
                 ORDER BY service""", (insee, annee, a["code"]))],
            "serie": serie, "situer": situer,
            "destinations": {"annee": annee_tonnes("destination"), "lignes": tonnes("destination")},
            "types": {"annee": annee_tonnes("dechet"), "lignes": tonnes("dechet")},
            "decheteries": rows(conn, """
                SELECT nom, insee, commune, lieu, ouverte_le, gestion FROM dechets_decheteries
                 WHERE code_acteur=? AND annee=(SELECT MAX(annee) FROM dechets_decheteries
                                                 WHERE code_acteur=?)
                 ORDER BY (insee = ?) DESC, commune""", (a["code"], a["code"], insee)),
        })
    return {"insee": insee, "annee_desserte": annee, "acteurs": acteurs}


def export_incendie(conn, insee: str) -> dict | None:
    """Forêt, feux et débroussaillement. Chaque partie ne sort que si son relevé
    a abouti (`incendie_suivi`) : une liste vide est alors un zéro mesuré."""
    if not table_exists(conn, "incendie_suivi"):
        return None
    suivi = {r["releve"]: r for r in rows(
        conn, "SELECT * FROM incendie_suivi WHERE insee=?", (insee,))}
    if not suivi:
        return None
    feux = None
    if "feux" in suivi:
        liste = rows(conn, "SELECT alerte, surface_ha, foret_ha, cause FROM feux"
                           " WHERE insee=? ORDER BY alerte", (insee,))
        feux = {"debut": suivi["feux"]["debut"], "fin": suivi["feux"]["fin"],
                "nombre": len(liste),
                "surface_ha": round(sum(f["surface_ha"] or 0 for f in liste), 4),
                "plus_grand": max(liste, key=lambda f: f["surface_ha"] or 0) if liste else None,
                "liste": liste}
    return {
        "insee": insee,
        "boisement": row(conn, "SELECT * FROM foret_boisement WHERE insee=?", (insee,))
        if "boisement" in suivi else None,
        "forets_publiques": rows(conn, "SELECT nom, nature FROM foret_publique WHERE insee=?"
                                       " ORDER BY nom", (insee,))
        if "forets_publiques" in suivi else None,
        "debroussaillement": row(conn, "SELECT * FROM debroussaillement WHERE insee=?", (insee,))
        if "debroussaillement" in suivi else None,
        "feux": feux,
    }


def etape_environnement(conn, out) -> None:
    # ── Environnement : qualité de l'eau, risques, installations classées ──
    # 27 652 analyses, 75 risques recensés et 3 ICPE dormaient en base sans
    # aucune page publique. Les analyses sont agrégées par station, paramètre
    # et année : publier 27 000 mesures brutes n'informerait personne.
    eau_stations = rows(conn, """
        SELECT code_station, libelle, code_commune, cours_eau, latitude, longitude
        FROM eau_stations ORDER BY libelle
    """) if table_exists(conn, "eau_stations") else []
    # Le suivi porte sur un millier de paramètres (micropolluants, pesticides…).
    # Publier les 10 756 séries n'aiderait personne : on détaille les
    # indicateurs qu'un lecteur non spécialiste peut interpréter, et on
    # résume le reste par un décompte des recherches et des détections.
    PARAM_CLES = [
        "Nitrates", "Nitrites", "Ammonium", "Phosphore total",
        "Oxygène dissous", "Température de l'Eau", "Conductivité à 25°C",
        "Matières en suspension", "Carbone Organique",
        "Demande Biochimique en oxygène en 5 jours (D.B.O.5)",
        "Escherichia coli (E. coli)", "Enterocoques",
        "Plomb", "Nickel", "Arsenic", "Cadmium", "Mercure", "Zinc", "Cuivre",
    ]
    ph = ",".join("?" for _ in PARAM_CLES)
    eau_series = rows(conn, f"""
        SELECT s.code_station, s.libelle AS station,
               a.libelle_parametre AS parametre, a.symbole_unite AS unite,
               substr(a.date_prelevement, 1, 4) AS annee,
               COUNT(*) AS n,
               ROUND(AVG(a.resultat), 3) AS moyenne,
               ROUND(MIN(a.resultat), 3) AS mini,
               ROUND(MAX(a.resultat), 3) AS maxi,
               MAX(a.date_prelevement) AS dernier_prelevement
          FROM eau_analyses a JOIN eau_stations s ON s.code_station = a.code_station
         WHERE a.resultat IS NOT NULL AND a.libelle_parametre IN ({ph})
         GROUP BY s.code_station, a.libelle_parametre, annee
         ORDER BY annee DESC, s.libelle, a.libelle_parametre
    """, PARAM_CLES) if table_exists(conn, "eau_analyses") else []
    eau_couverture = rows(conn, """
        SELECT substr(date_prelevement, 1, 4) AS annee,
               COUNT(*) AS analyses,
               COUNT(DISTINCT libelle_parametre) AS parametres_recherches,
               COUNT(DISTINCT CASE WHEN resultat > 0 THEN libelle_parametre END) AS parametres_detectes
          FROM eau_analyses
         GROUP BY annee ORDER BY annee DESC
    """) if table_exists(conn, "eau_analyses") else []
    eau_qualif = rows(conn, """
        SELECT substr(date_prelevement, 1, 4) AS annee,
               libelle_qualification AS qualification, COUNT(*) AS n
          FROM eau_analyses
         WHERE libelle_qualification IS NOT NULL AND libelle_qualification <> ''
         GROUP BY annee, qualification ORDER BY annee DESC
    """) if table_exists(conn, "eau_analyses") else []
    # ── L'eau du ROBINET, à ne pas confondre avec la précédente ───────────
    # Les analyses ci-dessus portent sur les COURS D'EAU. Ce que paie un
    # habitant et l'état du réseau qui l'alimente sont un autre sujet, une
    # autre source, et méritent de le dire — c'est le constat JOU-5 de la
    # contre-visite du 30/08. Tout sort publiable : un prix de l'eau et un
    # rendement de réseau sont des données de service public, sans la
    # moindre personne derrière.
    sispea_services = rows(conn, """
        SELECT code_service, competence, nom, libelle, type_collectivite,
               mode_gestion, siren, communes
          FROM sispea_services ORDER BY competence, code_service
    """) if table_exists(conn, "sispea_services") else []
    sispea_indicateurs = rows(conn, """
        SELECT code_service, annee, code, libelle, unite, valeur, origine
          FROM sispea_indicateurs ORDER BY code_service, annee, code
    """) if table_exists(conn, "sispea_indicateurs") else []

    # ── État énergétique du parc (DPE) ───────────────────────────────────
    # Des AGRÉGATS, jamais une ligne : le collecteur n'a rapatrié aucune
    # adresse de logement, et il n'y a donc rien d'autre à publier ici. La
    # couverture accompagne les parts — sans elle, une part calculée sur un
    # parc mal géocodé se lirait comme une part du parc entier.
    dpe_agregats = rows(conn, """
        SELECT insee, jeu, dimension, modalite, nombre FROM dpe_agregats
         ORDER BY insee, jeu, dimension, modalite
    """) if table_exists(conn, "dpe_agregats") else []
    dpe_couverture = rows(conn, """
        SELECT insee, jeu, diagnostics, secteur_cp, sans_commune, code_postal
          FROM dpe_couverture ORDER BY insee, jeu
    """) if table_exists(conn, "dpe_couverture") else []

    risques = rows(conn, """
        SELECT insee, commune, num_risque, libelle FROM risques_gaspar
        ORDER BY commune, libelle
    """) if table_exists(conn, "risques_gaspar") else []
    icpe = rows(conn, """
        SELECT code_aiot, raison_sociale, commune, adresse, regime, seveso,
               etat_activite, lat, lng
        FROM icpe_installations ORDER BY commune, raison_sociale
    """) if table_exists(conn, "icpe_installations") else []
    catnat = rows(conn, """
        SELECT date, title, source_url FROM events
         WHERE type = 'arrete_catnat' ORDER BY date DESC
    """)

    write_json(out / "environnement.json", {
        "eau_stations": eau_stations,
        "sispea_services": sispea_services,
        "sispea_indicateurs": sispea_indicateurs,
        "eau_series": eau_series,
        "eau_couverture": eau_couverture,
        "eau_qualification": eau_qualif,
        "dpe_agregats": dpe_agregats,
        "dpe_couverture": dpe_couverture,
        "risques": risques,
        "icpe": icpe,
        "catnat": catnat,
        "eau_controle": export_eau_potable(conn, INSEE_C1),
        "dechets": export_dechets(conn, INSEE_C1),
        "incendie": export_incendie(conn, INSEE_C1),
    })
