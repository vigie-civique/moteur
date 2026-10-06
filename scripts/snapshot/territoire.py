"""Le territoire : son environnement, son portrait, sa fiscalité.

Des données de service public et d'open data, sans personne derrière — eau
des rivières et du robinet, déchets, forêt et feux, risques, parc de
logements, INSEE, équipements, mobilité, cadastre, télécoms, accueil du jeune
enfant. Chaque étape lit ses tables et écrit son fichier.
"""
from __future__ import annotations

import re

from scripts.snapshot.socle import (DEPARTEMENT, EPCI_SIREN_C2, INSEE_C1, TELECOMS_RAYON_KM,
                                    row, rows, table_exists, write_json)


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


# ── Internet et téléphone (ARCEP, `collectors/telecoms.py`) ──────────────────
#
# Cinq relevés, cinq façons de se tromper en les affichant — chacune qualifiée
# ici, pour que la page n'ait rien à décider :
#   - le nombre de LOCAUX varie d'un trimestre à l'autre (le plan d'adressage
#     nettoie la base) : on publie la PART fibrée, jamais le seul compte ;
#   - l'éligibilité au cuivre tombe à zéro au 2ᵉ trimestre 2026 dans 25 805
#     communes à la fois : une rupture de méthode, pas une fermeture ;
#   - la qualité de la fibre n'existe que PAR RÉSEAU (tout un département hors
#     villes) : elle se dit comme telle, et ne se classe qu'à période et
#     périmètre égaux ;
#   - un site mobile est une ligne par opérateur : le site physique est
#     `id_site_partage` (sinon `num_site`) ;
#   - « 0 panne » ne vaut que sur des jours LUS : sans jour lu, rien n'est dit.

def _fin_de_periode(periode: str) -> tuple:
    """« 10/25 - 03/26 » → (26, 3) : une période se trie par sa fin."""
    m = re.search(r"(\d{2})/(\d{2})\s*$", periode or "")
    return (int(m.group(2)), int(m.group(1))) if m else (0, 0)


def _situer(conn, periode: str, perimetre: str, colonne: str, valeur) -> dict | None:
    """Rang (du meilleur au moins bon) et médiane parmi les réseaux de même
    période et même périmètre."""
    if valeur is None:
        return None
    autres = sorted(r[0] for r in conn.execute(
        f"SELECT {colonne} FROM telecoms_qualite_ftth WHERE periode=? AND perimetre=? "
        f"AND {colonne} IS NOT NULL", (periode, perimetre)))
    if not autres:
        return None
    n = len(autres)
    mediane = autres[n // 2] if n % 2 else (autres[n // 2 - 1] + autres[n // 2]) / 2
    return {"taux": valeur, "rang": sum(1 for x in autres if x < valeur) + 1,
            "sur": n, "mediane": round(mediane, 6)}


#: Les trimestres où l'ARCEP a changé de méthode pour le cuivre (le zéro y
#: apparaît dans des dizaines de milliers de communes, selon leur calendrier de
#: mise à jour). Un zéro apparu HORS de cette fenêtre n'est pas qualifié : la
#: page n'en dit rien plutôt que de l'expliquer à tort.
RUPTURE_CUIVRE = ("2026_T1", "2026_T2")


def _cuivre_a_zero(serie: list[dict]) -> dict | None:
    """Le trimestre où l'éligibilité au cuivre tombe à zéro, s'il est dans la
    fenêtre de rupture et le reste depuis."""
    for avant, apres in zip(serie, serie[1:]):
        if avant["cuivre"] and apres["cuivre"] == 0:
            if apres["trimestre"] in RUPTURE_CUIVRE and serie[-1]["cuivre"] == 0:
                return {"trimestre": apres["trimestre"], "date": apres["date"],
                        "avant": avant["cuivre"], "date_avant": avant["date"]}
    return None


def export_telecoms(conn, insee: str, departement: str, rayon_km: float) -> dict | None:
    if not table_exists(conn, "telecoms_fixe"):
        return None
    serie = rows(conn, """
        SELECT trimestre, date, locaux, elig_ftth AS fibre, elig_cu AS cuivre,
               mt_ftth, mt_4gf, mt_sat, mt_autre
          FROM telecoms_fixe WHERE insee=? ORDER BY trimestre
    """, (insee,))
    if not serie:
        return None
    for s in serie:
        s["part"] = round(100 * s["fibre"] / s["locaux"], 1) \
            if s["locaux"] and s["fibre"] is not None else None
    dernier = serie[-1]
    ouverture = next((s for s in serie if s["fibre"]), None)
    fixe = {
        "serie": [{k: s[k] for k in ("trimestre", "date", "locaux", "fibre", "part")}
                  for s in serie],
        "dernier": {**dernier, "sans_fibre": (dernier["locaux"] or 0) - (dernier["fibre"] or 0)},
        "ouverture": ouverture and {k: ouverture[k] for k in ("trimestre", "date", "fibre")},
        "cuivre_a_zero": _cuivre_a_zero(serie),
    }

    reseau = None
    if table_exists(conn, "telecoms_fixe_oi"):
        oi = row(conn, """
            SELECT f.trimestre, f.zone, f.oi, o.nom, f.locaux, f.ftth
              FROM telecoms_fixe_oi f LEFT JOIN telecoms_operateurs o ON o.code = f.oi
             WHERE f.insee=? ORDER BY f.trimestre DESC LIMIT 1
        """, (insee,))
        if oi:
            reseau = {**oi, "qualite": None}
            nom = oi.get("nom")
            if nom and table_exists(conn, "telecoms_qualite_ftth"):
                # L'ARCEP nomme le même opérateur « Wigard » ici, « Wigard
                # Fibre » là : la jointure se fait par préfixe.
                lignes = rows(conn, "SELECT * FROM telecoms_qualite_ftth WHERE oi LIKE ?",
                              (nom + "%",))
                periodes = sorted({r["periode"] for r in lignes}, key=_fin_de_periode)
                if periodes:
                    p = periodes[-1]
                    res = next((r for r in lignes if r["periode"] == p
                                and r["perimetre"] == "reseau"), None)
                    dep = next((r for r in lignes if r["periode"] == p
                                and r["perimetre"] == "departement"
                                and r["dep_code"] == departement), None)
                    reseau["qualite"] = {
                        "periode": p, "oi": (res or dep or {}).get("oi"),
                        "maison_mere": (res or dep or {}).get("maison_mere"),
                        "pannes": res and _situer(conn, p, "reseau", "taux_pannes",
                                                  res["taux_pannes"]),
                        "echecs_raccordement": res and _situer(
                            conn, p, "reseau", "taux_echecs_raccordement",
                            res["taux_echecs_raccordement"]),
                        # Publié au seul périmètre départemental par l'ARCEP.
                        "abonnes_avec_panne": dep and _situer(
                            conn, p, "departement", "taux_abonnes_avec_panne",
                            dep["taux_abonnes_avec_panne"]),
                    }

    mobile = None
    if table_exists(conn, "telecoms_sites_mobiles"):
        lignes = rows(conn, """
            SELECT *, COALESCE(id_site_partage, num_site) AS site FROM telecoms_sites_mobiles
             WHERE trimestre=(SELECT MAX(trimestre) FROM telecoms_sites_mobiles)
             ORDER BY distance_km, nom_op
        """)
        if lignes:
            sites: dict[str, dict] = {}
            for l in lignes:
                s = sites.setdefault(l["site"], {
                    "site": l["site"], "commune": l["nom_com"], "insee": l["insee_com"],
                    "distance_km": l["distance_km"], "zones_blanches": False,
                    "couverture_ciblee": False, "cinq_g": False, "operateurs": []})
                s["zones_blanches"] |= bool(l["site_zb"])
                s["couverture_ciblee"] |= bool(l["site_dcc"])
                s["cinq_g"] |= bool(l["site_5g"])
                s["operateurs"].append({"nom": l["nom_op"], **{
                    t: bool(l[f"site_{t}"]) for t in ("2g", "3g", "4g", "5g")}})
            tous = list(sites.values())
            cinq_g = [s for s in tous if s["cinq_g"]]
            mobile = {
                "trimestre": lignes[0]["trimestre"], "rayon_km": rayon_km,
                "sites": len(tous),
                "dans_la_commune": [s for s in tous if s["insee"] == insee],
                "plus_proche_5g": cinq_g[0] if cinq_g else None,
                "zones_blanches": sum(1 for s in tous if s["zones_blanches"]),
                "couverture_ciblee": sum(1 for s in tous if s["couverture_ciblee"]),
            }

    pannes = None
    if table_exists(conn, "telecoms_indispo_jours"):
        j = row(conn, "SELECT COUNT(*) AS jours, MIN(jour) AS du, MAX(jour) AS au "
                      "FROM telecoms_indispo_jours")
        if j and j["jours"]:
            pannes = {**j, "declarees": conn.execute(
                "SELECT COUNT(*) FROM telecoms_indisponibilites WHERE code_insee=? "
                "AND jour BETWEEN ? AND ?", (insee, j["du"], j["au"])).fetchone()[0]}

    return {"insee": insee, "fixe": fixe, "reseau": reseau, "mobile": mobile, "pannes": pannes}


def export_enfance(conn, insee: str, epci: str, departement: str) -> dict | None:
    """Les écoles de la commune, rentrée par rentrée, et l'accueil des moins de
    trois ans dans l'intercommunalité."""
    ecoles = []
    if table_exists(conn, "ecoles_effectifs") and table_exists(conn, "etablissements_scolaires"):
        for e in rows(conn, """
                -- Le nom de l'ANNUAIRE, pas celui de la fiche : la fiche a pu être
                -- adoptée d'une autre source (« École élémentaire »), alors que
                -- les effectifs sont ceux de l'école entière, maternelle comprise.
                SELECT s.uai, json_extract(s.raw_data, '$.nom_etablissement') AS nom,
                       s.nature, s.secteur, s.etat
                  FROM etablissements_scolaires s
                 WHERE json_extract(s.raw_data, '$.code_commune') = ?
                   AND s.uai IN (SELECT uai FROM ecoles_effectifs) ORDER BY s.uai""", (insee,)):
            ecoles.append({
                **e,
                "serie": rows(conn, "SELECT rentree, eleves, maternelle, classes"
                                    " FROM ecoles_effectifs WHERE uai=? ORDER BY rentree", (e["uai"],)),
                "ips": rows(conn, """
                    SELECT rentree, ips, ips_france_public AS france_public,
                           ips_departement_public AS departement_public
                      FROM ecoles_ips WHERE uai=? AND ips IS NOT NULL ORDER BY rentree""",
                            (e["uai"],)) if table_exists(conn, "ecoles_ips") else [],
            })
    accueil = None
    if epci and table_exists(conn, "accueil_petite_enfance"):
        serie = rows(conn, """
            SELECT annee, creche, assistantes, domicile, ecole, total, taux
              FROM accueil_petite_enfance WHERE portee='epci' AND code=? ORDER BY annee""", (epci,))
        if serie:
            # Les repères ne valent qu'à ANNÉE ÉGALE : la CAF publie le
            # département et la France sur moins d'années que l'intercommunalité.
            repere = lambda portee, code, annee: (row(conn, """
                SELECT taux FROM accueil_petite_enfance WHERE portee=? AND code=? AND annee=?""",
                                                      (portee, code, annee)) or {}).get("taux")
            for s in serie:
                s["departement"] = repere("departement", departement, s["annee"])
                s["france"] = repere("france", "", s["annee"])
            accueil = {"serie": serie, "dernier": serie[-1]}
    if not ecoles and not accueil:
        return None
    return {"insee": insee, "ecoles": ecoles, "accueil": accueil}


INSEE_PUBLIABLES = """
    SELECT insee, commune, dataset, indicateur, libelle, annee, valeur, dims
      FROM insee_indicateurs
     WHERE dataset <> 'DS_BPE'
     ORDER BY dataset, indicateur, annee
"""


def export_reperes_fiscaux(conn) -> list[dict]:
    """Où se place un taux parmi les communes qui lèvent la même taxe."""
    if not table_exists(conn, "fiscalite_reperes"):
        return []
    reperes = rows(conn, """
        SELECT insee, annee, indicateur, portee, code, taux, communes, mediane, au_moins_autant
          FROM fiscalite_reperes ORDER BY insee, indicateur, annee, portee DESC""")
    for r in reperes:
        r["part_au_moins_autant"] = (round(100 * r["au_moins_autant"] / r["communes"], 1)
                                     if r["communes"] and r["au_moins_autant"] is not None else None)
    return reperes


# ── Les installations classées : qui est nommé, qui est situé ────────────────
# Le registre des ICPE nomme l'exploitant et donne son adresse et ses
# coordonnées. Pour une société, c'est une installation industrielle ; pour un
# éleveur en nom propre — « DUPONT MARIE », « Mr MARTIN Paul » —, c'est le nom
# d'un particulier et, le plus souvent, son domicile. Relevé le 06/10/2026 sur
# deux instances en ligne : une douzaine de personnes publiées ainsi, avec leur
# point sur la carte.
#
# ⚖️ On ne nomme et ne situe que ce qui est ÉTABLI personne morale : une forme
# juridique écrite dans la raison sociale, ou un SIREN que la base connaît sous
# une autre forme que l'entreprise individuelle. Le reste — particulier, mais aussi
# société dont le nom ne dit pas la forme — garde sa commune, son régime et son
# état, sans nom, sans adresse, sans coordonnées ni numéro d'installation (qui
# rendrait le nom en une requête). On y perd le nom de quelques sociétés ; on ne
# devine pas qu'un « NOM Prénom » est une enseigne.
_FORME_MORALE = re.compile(
    r"\b(?:SARL|SAS|SASU|SA|EARL|GAEC|SCEA|SCA|SCI|SCP|EURL|SNC|SCOP|SICA|CUMA|GIE|GFA"
    r"|CC|SIVOM|SIVU|SICTOM|SMICTOM|SYNDICAT|COMMUNE|MAIRIE|COMMUNAUT[EÉ]"
    r"|COOP[EÉ]RATIVE|SOCI[EÉ]T[EÉ]|D[EÉ]PARTEMENT|R[EÉ]GION|ASSOCIATION)\b", re.I)
# Une entreprise individuelle est son exploitant, quelle que soit l'enseigne.
_EXPLOITANT_INDIVIDUEL = re.compile(r"\b(?:EIRL|EI|M\.|Mr|Mme|Monsieur|Madame)(?=\s|$)", re.I)


def exploitant_designe(raison_sociale: str | None, siret: str | None,
                       formes: dict[str, str]) -> bool:
    """L'exploitant d'une installation classée peut-il être nommé et situé ?

    `formes` : la catégorie juridique des SIREN que la base connaît. Elle
    tranche quand elle existe ; sinon c'est la raison sociale qui doit le dire.
    """
    nom = raison_sociale or ""
    forme = formes.get(str(siret)[:9]) if siret else None
    if forme:
        return forme != "1000"
    if _EXPLOITANT_INDIVIDUEL.search(nom):
        return False
    return bool(_FORME_MORALE.search(nom))


def export_icpe(conn) -> tuple[list[dict], int]:
    """Les installations classées, et le nombre d'exploitants non désignés."""
    if not table_exists(conn, "icpe_installations"):
        return [], 0
    formes = {r["siren"]: r["legal_form_code"] for r in rows(
        conn, "SELECT siren, legal_form_code FROM businesses "
              "WHERE siren IS NOT NULL AND legal_form_code IS NOT NULL")}
    sortie, masques = [], 0
    for i in rows(conn, """
        SELECT code_aiot, raison_sociale, commune, adresse, regime, seveso,
               etat_activite, lat, lng,
               CASE WHEN json_valid(raw_data) THEN json_extract(raw_data, '$.siret') END AS siret
        FROM icpe_installations ORDER BY commune, raison_sociale
    """):
        siret = i.pop("siret")
        if exploitant_designe(i["raison_sociale"], siret, formes):
            sortie.append(i)
            continue
        masques += 1
        sortie.append({"raison_sociale": None, "exploitant_masque": True,
                       "commune": i["commune"], "regime": i["regime"],
                       "seveso": i["seveso"], "etat_activite": i["etat_activite"]})
    return sortie, masques


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
    icpe, icpe_masques = export_icpe(conn)
    # Les arrêtés que le collecteur Géorisques a écrits, et eux seuls : la
    # requête lit la base, pas `events.json` — un acte du même type entré par une
    # autre porte n'a passé aucun filtre.
    catnat = rows(conn, """
        SELECT date, title, source_url FROM events
         WHERE type = 'arrete_catnat' AND source = 'georisques' ORDER BY date DESC
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
        "icpe_exploitants_masques": icpe_masques,
        "catnat": catnat,
        "eau_controle": export_eau_potable(conn, INSEE_C1),
        "dechets": export_dechets(conn, INSEE_C1),
        "incendie": export_incendie(conn, INSEE_C1),
    })


def etape_territoire(conn, out) -> None:
    # ── Portrait de territoire (INSEE) ────────────────────────────────────
    insee_data = rows(conn, INSEE_PUBLIABLES) \
        if table_exists(conn, "insee_indicateurs") else []

    # Équipements et services (BPE). `geo_type` distingue le communal de
    # l'intercommunal : l'INSEE ne publie l'ÉVOLUTION qu'à partir de l'EPCI,
    # et une page qui présenterait cette trajectoire comme communale
    # mentirait. Le champ voyage donc jusqu'au JSON.
    equipements = rows(conn, """
        SELECT geo_type, geo_code, geo_nom, annee, niveau, code, libelle, nombre
          FROM equipements ORDER BY geo_type, annee, niveau, code
    """) if table_exists(conn, "equipements") else []

    # Transport déclaré et dispositifs de l'État. Seuls les arrêts DANS la
    # commune sortent : ceux que la boîte englobante a ramassés chez le
    # voisin gonfleraient la desserte communale. Leur nombre est publié à
    # part, pour que l'écart reste lisible.
    mobilite_aom = rows(conn, """
        SELECT insee, nom, siren, forme, departement FROM mobilite_aom
    """) if table_exists(conn, "mobilite_aom") else []
    mobilite_arrets = rows(conn, """
        SELECT insee, reseau, arret, lat, lng FROM mobilite_arrets
         WHERE dans_commune = 1 ORDER BY reseau, arret
    """) if table_exists(conn, "mobilite_arrets") else []
    arrets_hors_commune = (conn.execute(
        "SELECT COUNT(*) FROM mobilite_arrets WHERE dans_commune = 0").fetchone()[0]
        if table_exists(conn, "mobilite_arrets") else 0)
    dispositifs = rows(conn, """
        SELECT insee, code, libelle, reference FROM dispositifs_etat
         ORDER BY insee, libelle
    """) if table_exists(conn, "dispositifs_etat") else []

    # Cadastre : le parcellaire ne se publie pas parcelle par parcelle (des
    # milliers de lignes qu'aucune page ne lit), mais son RÉSUMÉ situe le
    # territoire — combien de parcelles, quelle surface cadastrée.
    cadastre_resume = rows(conn, """
        SELECT insee, COUNT(*) AS parcelles, COUNT(DISTINCT section) AS sections,
               SUM(contenance) AS contenance_m2
          FROM cadastre_parcelles GROUP BY insee
    """) if table_exists(conn, "cadastre_parcelles") else []

    write_json(out / "territoire.json", {
        "insee": insee_data,
        "total": len(insee_data),
        "equipements": equipements,
        "mobilite_aom": mobilite_aom,
        "mobilite_arrets": mobilite_arrets,
        "mobilite_arrets_hors_commune": arrets_hors_commune,
        "dispositifs_etat": dispositifs,
        "cadastre": cadastre_resume,
        "telecoms": export_telecoms(conn, INSEE_C1, DEPARTEMENT, TELECOMS_RAYON_KM),
        "enfance": export_enfance(conn, INSEE_C1, EPCI_SIREN_C2, DEPARTEMENT),
    })


def etape_fiscalite(conn, out) -> dict:
    # `portee` distingue la part votée par la commune du total acquitté :
    # attribuer le taux global au conseil municipal serait faux.
    fiscalite = rows(conn, """
        SELECT insee, commune, annee, indicateur, libelle, portee, taux, epci
        FROM fiscalite_taux ORDER BY annee DESC, commune, indicateur
    """) if table_exists(conn, "fiscalite_taux") else []
    write_json(out / "fiscalite.json", {"taux": fiscalite, "total": len(fiscalite),
                                        "reperes": export_reperes_fiscaux(conn)})

    return {"fiscalite": fiscalite}
