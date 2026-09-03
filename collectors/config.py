"""Configuration du moteur — chargeur, pas registre.

Ce fichier ne contient AUCUNE donnée de commune. Il lit `config/instance.json`,
écrit une fois pour toutes par `scripts/init_instance.py`, et expose les noms
que les collecteurs importent depuis toujours. Les quarante modules du moteur
n'ont donc rien à savoir de l'endroit d'où vient le périmètre.

Pourquoi ce détour plutôt qu'un fichier de constantes à éditer : sur la
première commune portée, les données locales s'étaient répandues bien au-delà
de ce fichier — identifiants de lignes de la base d'origine dans quatre
collecteurs, nom de la base dans dix fichiers, et jusqu'au statut urbanistique
d'une commune écrit en dur dans le code d'un collecteur. Tant que le particulier
a le droit d'être « quelque part dans le code », il finit partout. Ici il n'a
qu'un seul endroit possible, et `scripts/verifier_generique.py` échoue s'il en
sort. Voir `docs/portage-brassac.md`.

Amorcer une instance :
    python3 scripts/init_instance.py 81037      # code INSEE de la commune
"""
from __future__ import annotations

import json
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

# `VIGIE_INSTANCE` désigne un autre fichier de périmètre. Utilisé par les tests,
# qui doivent tourner sur une instance factice sans qu'un dépôt fraîchement
# cloné ait à en configurer une vraie — et utilisable pour vérifier un périmètre
# avant de l'installer. En dehors de ces deux cas, il n'y a qu'une instance par
# copie du moteur, et c'est voulu.
INSTANCE = pathlib.Path(
    os.environ.get("VIGIE_INSTANCE") or ROOT / "config" / "instance.json")

if not INSTANCE.exists():
    raise SystemExit(
        f"Aucune instance configurée : {INSTANCE} est absent.\n"
        "Amorcer avec :  python3 scripts/init_instance.py <code INSEE>\n"
        "Exemple      :  python3 scripts/init_instance.py 81037"
    )

_I = json.loads(INSTANCE.read_text(encoding="utf-8"))


def _exiger(cle: str):
    if cle not in _I:
        raise SystemExit(f"config/instance.json : clé « {cle} » manquante. "
                         "Relancer scripts/init_instance.py.")
    return _I[cle]


# ─────────────────────────────────────────────────────────────────────────────
# PÉRIMÈTRE
#
# Le périmètre suit la CHAÎNE DE DÉCISION, pas le bassin de vie. On entre dans
# une donnée par l'autorité qui l'a produite ou par le lien à un acteur suivi,
# jamais par la proximité géographique.
#
#   C1  la commune de collecte              → profondeur maximale
#   C2  l'intercommunalité : l'institution ET ses autres communes membres, au
#       même niveau de collecte, plus les syndicats auxquels la commune adhère
#   C3  contexte descendant (département, région, État) → filtré par mention
# ─────────────────────────────────────────────────────────────────────────────

# ── C1 — la commune ──────────────────────────────────────────────────────────
COMMUNE_INSEE = _exiger("commune_insee")
COMMUNE_NAME  = _exiger("commune_nom")
CODE_POSTAL   = _exiger("code_postal")
DEPARTEMENT   = _exiger("departement")
COMMUNE_SIREN = _I.get("commune_siren", "")
COMMUNE_SIRET = _I.get("commune_siret", "")

# ── Registre de COLLECTE — les communes de l'EPCI ────────────────────────────
# Piloter le périmètre de collecte se fait ici et nulle part ailleurs : rna,
# bodacc, marches_publics, rne, fiscalite, elections, georisques, insee_social,
# urbanisme_sitadel et dgf_notifications filtrent tous sur ce registre.
#
# COMMUNES ≠ C1. C1, c'est COMMUNE_INSEE seul. Les autres sont C2 : elles sont
# collectées au même niveau parce qu'elles délèguent leurs compétences à la même
# intercommunalité et siègent au même conseil communautaire. La distinction
# C1/C2 se lit dans `entities.perimetre`, pas ici.
COMMUNES = _exiger("communes")
COMMUNES_INSEE = list(COMMUNES)

# ATTENTION : un code postal ne délimite pas une commune ; il déborde toujours
# sur des communes voisines, parfois sur toute une aire urbaine. Les collecteurs
# qui interrogent par code postal (RNA/JO, BODACC) sur-collectent donc
# mécaniquement, puis rejettent sur le nom de commune via COMMUNES. Ne pas
# supprimer ce filtre aval en croyant que le code postal suffit.
COMMUNES_CP = sorted({c["cp"] for c in COMMUNES.values()})

# Communes déléguées — une fusion de communes n'est pas répercutée dans toutes
# les sources ADRESSÉES : SIRENE et DVF continuent d'indexer sous l'ancien code,
# BODACC sous l'ancien nom. Les clés sont des CODES INSEE envoyés tels quels aux
# API : ne rien y mettre qui n'en soit pas un.
#
# Ce registre était vide sur la commune d'origine, donc le code qui l'exploite
# n'avait jamais tourné. Une branche jamais empruntée est une branche fausse
# jusqu'à preuve du contraire — cf. docs/portage-brassac.md.
COMMUNES_DELEGUEES: dict[str, dict] = _I.get("communes_deleguees", {})
COMMUNES_ADRESSE = {**COMMUNES, **COMMUNES_DELEGUEES}
COMMUNES_INSEE_ADRESSE = list(COMMUNES_ADRESSE)

# ── PROFONDEUR DE COLLECTE ───────────────────────────────────────────────────
# Le registre ci-dessus dit QUI est dans le périmètre. Il ne disait pas à quelle
# PROFONDEUR chacun est collecté, et cette confusion coûtait cher : aspirer les
# commerces, les associations, les mutations immobilières et les points
# d'intérêt des quinze communes de l'intercommunalité produisait un annuaire où
# la commune de collecte était minoritaire chez elle. Un site communal parle de
# sa commune.
#
# Deux profondeurs, et deux seulement :
#
#   'fond'         collecte complète. Par défaut la commune de collecte, seule.
#   'institution'  contexte institutionnel — ce que la commune délègue, partage
#                  ou subit : élus, compétences, budgets, fiscalité, risques,
#                  indicateurs. Porte sur TOUT le périmètre, C1 compris.
#
# Ce partage est une règle du moteur, pas un particulier de commune : une
# instance l'hérite sans rien déclarer. `collecte.fond` dans `instance.json` ne
# sert qu'à la SURCHARGER — plusieurs communes suivies en propre (un média qui
# couvre une vallée), ou une commune qui veut réellement l'EPCI en profondeur.
#
# `fond` est une LISTE même quand elle n'a qu'un élément. Le reste du moteur ne
# sait pas encore suivre plusieurs communes (COMMUNE_INSEE, le connecteur du
# site de mairie et l'EPCI sont au singulier) ; le périmètre de collecte, lui,
# est déjà prêt à les recevoir.
_COLLECTE = _I.get("collecte", {})
COMMUNES_FOND_INSEE = list(_COLLECTE.get("fond") or [COMMUNE_INSEE])

_hors_registre = [c for c in COMMUNES_FOND_INSEE if c not in COMMUNES]
if _hors_registre:
    raise SystemExit(
        "config/instance.json : collecte.fond cite des communes absentes du "
        f"registre `communes` : {', '.join(_hors_registre)}.\n"
        "Une commune collectée en profondeur doit d'abord appartenir au "
        "périmètre, sans quoi les collecteurs l'interrogent et le classement "
        "écarte ensuite tout ce qu'ils en ont rapporté.")

COMMUNES_FOND = {c: COMMUNES[c] for c in COMMUNES_FOND_INSEE}
# Les communes déléguées suivent leur commune de rattachement : une fusion ne
# change pas la profondeur à laquelle on suit un territoire, seulement le code
# sous lequel les répertoires continuent de l'indexer.
COMMUNES_FOND_ADRESSE = {
    **COMMUNES_FOND,
    **{code: d for code, d in COMMUNES_DELEGUEES.items()
       if d.get("commune") in COMMUNES_FOND},
}
COMMUNES_FOND_INSEE_ADRESSE = list(COMMUNES_FOND_ADRESSE)

# Profondeur de chaque step qui boucle sur des communes. Piloter le périmètre de
# collecte se fait ici et nulle part ailleurs : un collecteur ne CHOISIT pas sa
# profondeur, il nomme son step et reçoit la liste qui lui revient. Écrite dans
# les collecteurs, elle se serait dispersée sur quinze fichiers et aurait cessé
# d'être réglable — c'est très exactement ce qui était arrivé au périmètre.
PROFONDEURS = ("fond", "institution")
PROFONDEUR_STEP = {
    # ── fond : ce qui fait le tissu d'une commune ────────────────────────────
    "sirene":      "fond",          # entreprises et établissements
    "rna":         "fond",          # associations (RNA / Journal officiel)
    "bodacc":      "fond",          # annonces légales des entreprises
    "dvf":         "fond",          # mutations immobilières
    "osm":         "fond",          # points d'intérêt
    "patrimoine":  "fond",          # monuments historiques
    "education":   "fond",          # écoles, collèges, lycées
    "eau":         "fond",          # stations et analyses des cours d'eau
    "sispea":      "fond",          # prix et performance de l'eau potable
    "plu":         "fond",          # document d'urbanisme déposé au GPU
    "equipements": "fond",          # commerces, santé, écoles (BPE)
    "dpe":         "fond",          # état énergétique du parc de logements
    "mobilite":    "fond",          # AOM, arrêts déclarés, dispositifs de l'État
    "sante":       "fond",          # établissements sanitaires et médico-sociaux
    "cadastre":    "fond",          # parcellaire — une commune, un fichier
    # ── institution : ce qui se décide à plusieurs ───────────────────────────
    # `rne` reste sur tout le périmètre parce que les délégués communautaires
    # sont élus dans les communes membres : les en retirer, c'est perdre la
    # moitié du conseil communautaire.
    "rne":         "institution",
    "elections":   "institution",
    "fiscalite":   "institution",
    "insee":       "institution",
    "georisques":  "institution",
    "sitadel":     "institution",
    "subventions": "institution",
}

for _step, _prof in _COLLECTE.get("profondeur_steps", {}).items():
    if _step not in PROFONDEUR_STEP:
        raise SystemExit(
            f"config/instance.json : collecte.profondeur_steps cite « {_step} », "
            "qui n'est pas un step à profondeur. Steps réglables : "
            + ", ".join(sorted(PROFONDEUR_STEP)))
    if _prof not in PROFONDEURS:
        raise SystemExit(
            f"config/instance.json : profondeur « {_prof} » inconnue pour "
            f"« {_step} ». Valeurs possibles : {', '.join(PROFONDEURS)}")
    PROFONDEUR_STEP[_step] = _prof


def registre_du_step(step: str, adresse: bool = False) -> dict:
    """Les communes que ce step doit interroger, par code INSEE.

    `adresse=True` ajoute les communes déléguées : les sources ADRESSÉES
    (SIRENE, DVF, Sitadel) indexent encore sous l'ancien code des communes
    qu'une fusion a absorbées, et les oublier fait disparaître des
    établissements et des mutations d'un territoire.
    """
    if step not in PROFONDEUR_STEP:
        raise SystemExit(
            f"collectors/config.py : le step « {step} » n'a pas de profondeur "
            "déclarée. Un step qui boucle sur des communes doit dire "
            "lesquelles — ajouter une entrée à PROFONDEUR_STEP.")
    if PROFONDEUR_STEP[step] == "fond":
        return COMMUNES_FOND_ADRESSE if adresse else COMMUNES_FOND
    return COMMUNES_ADRESSE if adresse else COMMUNES


def communes_du_step(step: str, adresse: bool = False) -> list[str]:
    """Codes INSEE à interroger pour ce step."""
    return list(registre_du_step(step, adresse))


def cp_du_step(step: str) -> list[str]:
    """Codes postaux à interroger pour ce step.

    Rappel du registre ci-dessus : un code postal ne délimite pas une commune.
    Les collecteurs qui l'emploient (RNA, BODACC) sur-remontent puis rejettent
    sur le nom — et ce filtre aval doit lui aussi être borné à la profondeur du
    step, sans quoi la réduction est annulée par la commune voisine qui partage
    le code postal.
    """
    return sorted({c["cp"] for c in registre_du_step(step, adresse=True).values()
                   if c.get("cp")})


# ── Bruit propre à la mise en page des PV de cette mairie ─────────────────────
# En-têtes de colonnes, intitulés d'équipements, patronymes d'agents qui
# reviennent à chaque page : `cm_parser` les écarte du découpage en
# délibérations. Ils ne relèvent pas du français mais d'un gabarit de document,
# et parfois ils NOMMENT des personnes — ils ne peuvent donc pas vivre dans le
# moteur, qui est publié. Liste vide par défaut : sans elle, le découpage est
# seulement un peu plus bruyant.
BRUIT_PV: list[str] = _I.get("bruit_pv", [])

# Rectifications déclarées : ce que la source ÉCRIT → ce qu'il faut LIRE.
# Chaque entrée est une décision humaine, datée et motivée, pas une règle. Une
# faute de frappe d'un registre national ne se corrige ni à la main dans la
# base (elle revient à la collecte suivante) ni par une règle générale (« uu »
# n'est pas une faute dans tous les mots) : elle se déclare ici, une fois, et
# vaut pour toutes les collectes à venir.
# Une `lecture` ne doit jamais contenir sa `source`, sans quoi la rectification
# se rejouerait sur elle-même.
RECTIFICATIONS: list[dict] = _I.get("rectifications", [])

# ── C2 — l'intercommunalité ──────────────────────────────────────────────────
# Suivie comme INSTITUTION : conseil communautaire et délégués, compétences
# transférées, budget principal et annexes, marchés, délibérations.
EPCI_SIREN = _I.get("epci_siren", "")
EPCI_NOM   = _I.get("epci_nom", "")
EPCI_COMMUNES = {code: {"nom": c["nom"], "population": c.get("population")}
                 for code, c in COMMUNES.items()}
EPCI_COMMUNES_INSEE = list(EPCI_COMMUNES)
EPCI_COMMUNES_NOMS  = {c["nom"] for c in EPCI_COMMUNES.values()}

# Structures intercommunales exerçant une compétence de la commune (syndicats
# d'eau, d'assainissement, de déchets, syndicats mixtes). Elles relèvent de C2
# au même titre que l'EPCI : elles décident à la place de la commune. Détectées
# par la relation d'adhésion et non par une liste en dur — condition pour que le
# classement ne se périme pas au premier syndicat créé.
RELATIONS_ADHESION = ("adhère_à", "membre_de")

# ── Classement des entités (colonne entities.perimetre) ──────────────────────
# 'C1'   commune de collecte
# 'C2'   commune membre de l'EPCI, l'EPCI lui-même, ou une structure à laquelle
#        la commune adhère (RELATIONS_ADHESION)
# 'C3'   autorité supra-communale : préfecture, département, région, agences
#        d'État. Produit des actes qui s'appliquent à C1/C2, n'est pas collectée
#        pour elle-même.
# 'lien' hors périmètre géographique MAIS rattachée à un acteur C1/C2 par une
#        relation, un marché ou un flux financier : matériau du graphe
#        d'influence et de la commande publique.
# 'hors' ni l'un ni l'autre → purgeable.
PERIMETRES = ("C1", "C2", "C3", "lien", "hors")

# ── Sites officiels ──────────────────────────────────────────────────────────
# La partie irréductible du portage : il n'existe pas de format commun aux sites
# de mairie. Le connecteur qui sait les lire est nommé dans l'instance ; le
# moteur, lui, ne connaît que l'interface (cf. collectors/connecteurs/).
COMMUNE_URL = _I.get("commune_url", "")
EPCI_URL    = _I.get("epci_url", "")
CONNECTEUR  = _I.get("connecteur", "wordpress_rest")
# Rien n'oblige une commune et son intercommunalité à publier sur le même
# outil : la première peut tenir un WordPress quand la seconde dépose ses actes
# sur un portail de publicité légale. Sans cette clé, le connecteur de la
# commune est employé pour les deux — c'était le cas jusqu'au 24/08/2026, et
# l'EPCI d'une instance rendait alors 0 procès-verbal sans qu'on sache dire si
# c'était une lacune de la source ou un outil qu'on ne savait pas lire.
CONNECTEUR_EPCI = _I.get("connecteur_epci", "")
PAGES       = _I.get("pages", {})     # slugs des pages utiles, par connecteur
# Les portails déclarés dans `pages` (`{"epci": {"portail": "https://…"}}`).
# Un portail de publicité légale est un site officiel de la collectivité au même
# titre que le sien, mais c'est un TROISIÈME domaine : il ne se déduit ni de
# `commune_url` ni d'`epci_url`. Les règles qui parlent des « sites que nous
# lisons » — l'origine des faits, les sources publiables — doivent le connaître,
# sans quoi ce qu'il apporte entre en base et n'en sort jamais.
PORTAILS    = tuple(r["portail"] for r in PAGES.values()
                    if isinstance(r, dict) and r.get("portail"))
# Particularités de mise en forme des procès-verbaux (convention d'écriture des
# noms, notamment) : cf. collectors/conseils.py.
FORMAT_PV   = _I.get("format_pv", {})

# ── Préfecture — recueil des actes administratifs ────────────────────────────
# L'arborescence diffère d'une préfecture à l'autre (page annuelle, ou année →
# mois → acte avec pagination) : le parcours est récursif, le chemin se déclare.
PREFECTURE_NOM      = _I.get("prefecture_nom", f"Préfecture ({DEPARTEMENT})")
PREFECTURE_URL      = _I.get("prefecture_url", "")
PREFECTURE_RAA_PATH = _I.get("prefecture_raa_path", "")

# ── Géographie ───────────────────────────────────────────────────────────────
BBOX     = tuple(_I.get("bbox", []))       # (sud, ouest, nord, est) — Overpass
CENTROID = tuple(_I.get("centroid", []))

# Suivi de fraîcheur par collecteur : (ttl_jours, priorité, table, where).
# Source unique de vérité, consommée par `run_all.run_step` (journal
# collector_runs), `scripts/collect_loop` (relance des sources périmées) et
# `scripts/qa_loop` (alerte source muette). Elle vit ici parce que qa_loop doit
# la lire sans importer les collecteurs. `init` n'est pas un collecteur : pas
# d'entrée. Priorité : petit = d'abord.
STEP_META = {
    "events":     (3,   1,  "events",            "type='local_event'"),
    "cm":         (7,   2,  "events",            "type IN ('deliberation','conseil_municipal')"),
    "seed":       (365, 2,  "financial_flows",   "type='subvention'"),
    "marches":    (7,   3,  "marches_publics",   ""),
    "bodacc":     (7,   4,  "events",            "source='bodacc'"),
    "cc_epci":    (14,  5,  "events",            "type='deliberation_cc'"),
    # L'archive du web ne change pas : une fois les PV disparus repris, il n'y a
    # plus rien à y chercher avant la prochaine refonte du site.
    "cm_archive": (365, 5,  "events",            "source_url LIKE '%web.archive.org%'"),
    "banatic":    (30,  5,  "epci_competences",  ""),
    "web":        (7,   6,  "entity_notes",      ""),
    "raa":        (30,  7,  "events",            "type='raa_prefecture'"),
    # Une observation de chambre régionale est rare — quelques-unes par mandat,
    # et jamais pour la plupart des communes. 90 jours ne dit donc pas « ça
    # bouge tous les trois mois », mais « au-delà, le silence cesse d'être une
    # information sur la commune et devient une question sur le collecteur ».
    "crc":        (90,  7,  "events",            "type IN ('crc_rapport','crc_rapport_epci')"),
    "profiles":   (30,  8,  "persons",           ""),
    "osm":        (30,  9,  "places",            "osm_category<>'patrimoine'"),
    "sirene":     (30,  10, "businesses",        ""),
    "rna":        (30,  11, "associations",      ""),
    "georisques": (90,  12, "risques_gaspar",    ""),
    "dvf":        (90,  13, "dvf_transactions",  ""),
    "patrimoine": (180, 14, "places",            "osm_category='patrimoine'"),
    "insee":      (180, 15, "insee_indicateurs", ""),
    # L'annuaire de l'éducation bouge à la rentrée : une fermeture d'école se
    # constate en septembre, pas en juillet.
    "education":  (180, 15, "etablissements_scolaires", ""),
    "rne":        (30,  16, "elus_rne",          ""),
    "fiscalite":  (180, 17, "fiscalite_taux",    ""),
    "sitadel":    (30,  18, "urbanisme_autorisations", ""),
    "elections":  (365, 19, "elections_resultats", ""),
    "dir_deports":(30,  20, "relation_candidates", "signal='deport_conseil'"),
    "dir_web":    (90,  21, "relation_candidates", "signal='site_web_asso'"),
    # Finances et environnement. Ces collecteurs existaient mais n'étaient
    # appelés par personne : une collecte complète produisait une base sans
    # budget, alors que le site en publie les pages.
    "ofgl":       (180, 22, "ofgl_agregats",     ""),
    "budget":     (180, 23, "budget_annuel",     ""),
    "subventions":(180, 24, "financial_flows",   "source IN ('OFGL','DGCL')"),
    "cm_flux":    (30,  25, "financial_flows",   "source LIKE 'CR CM%'"),
    "eau":        (90,  26, "eau_analyses",      ""),
    # 365 jours : l'OFB publie UN exercice par an, vers la mi-année. Réclamer
    # plus frais ferait rougir un indicateur que rien ne peut rafraîchir.
    "sispea":     (365, 26, "sispea_indicateurs", ""),
    "urbanisme":  (90,  27, "events",            "type='urbanisme'"),
    # Ce qu'on compte est le RELEVÉ, pas la trouvaille : une commune au RNU n'a
    # aucun document, et c'est le cas ordinaire. Compter `urbanisme_documents`
    # ferait rougir une source qui a parfaitement fonctionné — cf.
    # [[feedback-un-zero-qui-vient-dune-absence]]. 180 jours : un document
    # d'urbanisme se révise en années, son dépôt au GPU en mois.
    "plu":        (180, 27, "urbanisme_statut",  ""),
    # L'INSEE publie UN millésime de la BPE par an, à l'été.
    "equipements":(365, 15, "equipements",       ""),
    # L'ADEME publie en continu : un mois suffit à voir la source se taire.
    "dpe":        (30,  15, "dpe_couverture",    ""),
    # Un GTFS se republie en continu, la table de l'ANCT quelques fois par an :
    # 30 jours suit le plus vif des deux.
    "mobilite":   (30,  18, "mobilite_aom",      ""),
    # Le ministère dépose une extraction par mois.
    "sante":      (30,  15, "etablissements_sante", ""),
    # Le plan cadastral est mis à jour tous les trimestres.
    "cadastre":   (90,  13, "cadastre_parcelles", ""),
    # La HATVP met sa liste à jour en continu, mais ce qu'elle change pour une
    # commune est rare : 30 jours suffisent à voir la source se taire.
    "hatvp":      (30,  20, "hatvp_declarations", ""),
    # Les incréments de la DILA sont quotidiens ; 30 jours de retard restent
    # rattrapables sans reprendre le corpus.
    "justice":    (30,  21, "justice_decisions", ""),
    # Pas une source : une dérivation de ce que les autres ont écrit. Journalisée
    # quand même, parce qu'un classement qui n'a pas tourné bloque la publication
    # et doit se lire dans collector_runs comme n'importe quelle panne. Fraîcheur
    # alignée sur le collecteur le plus fréquent : il se périme avec eux.
    "commissions":(180, 28, "relation_candidates", "signal='commission_pv'"),
    "perimetre":  (7,   29, "entities",          "perimetre IS NOT NULL"),
}

# ── Chemins ──────────────────────────────────────────────────────────────────
# La base porte le code INSEE et non le nom de la commune : deux communes
# françaises peuvent s'appeler pareil, leurs codes non.
#
# `VIGIE_DB` la déplace ailleurs — les tests s'en servent pour travailler sur
# une base jetable plutôt que d'écrire dans le dépôt.
DB_PATH     = pathlib.Path(
    os.environ.get("VIGIE_DB") or ROOT / "db" / f"{COMMUNE_INSEE}.db")
SCHEMA_PATH = ROOT / "db" / "schema.sql"
TERRITOIRE  = ROOT / "territoire"
PROFILS_DIR = ROOT / "profils"
FINANCES    = ROOT / "finances"
ASSOC_DIR   = ROOT / "associations"
ENTRE_DIR   = ROOT / "entreprises"
SEED_LOCAL  = ROOT / "config" / "seed_local.json"

# Magasin des gros jeux nationaux réutilisables entre instances. Sans variable,
# le moteur conserve son comportement autonome sous data/raw/. Un portail peut
# fixer un dossier extérieur aux copies de génération : aucune donnée n'entre
# dans Git et les communes lisent les mêmes téléchargements.
NATIONAL_STORE = pathlib.Path(
    os.environ.get("VIGIE_NATIONAL_STORE") or ROOT / "data" / "raw"
).expanduser().resolve()

# ── API nationales ───────────────────────────────────────────────────────────
# Ce bloc est le cœur générique du dispositif : ces sources sont indexées par
# code INSEE, code postal ou SIREN, et fonctionnent pour n'importe quelle
# commune française sans une ligne de code à écrire.
SIRENE_API  = "https://recherche-entreprises.api.gouv.fr/search"
JO_ASSO_API = ("https://www.journal-officiel.gouv.fr/api/explore/v2.1"
               "/catalog/datasets/jo_associations/records")
DVF_API     = "https://api-dvf.cerema.fr/api/v1/mutations/"
BAN_API     = "https://api-adresse.data.gouv.fr/search/"
OVERPASS    = "https://overpass-api.de/api/interpreter"
GEO_API     = "https://geo.api.gouv.fr"

# ── HTTP ─────────────────────────────────────────────────────────────────────
# ASCII strictement : les en-têtes HTTP sont encodés en latin-1 par urllib, et
# un tiret cadratin dans le User-Agent fait échouer TOUTES les requêtes avec un
# « 'latin-1' codec can't encode character » que rien ne rattache à sa cause.
HEADERS = {
    "User-Agent": f"VigieCivique/1.0 (INSEE {COMMUNE_INSEE}; veille citoyenne, "
                  "donnees publiques)"
}
REQUEST_DELAY = 0.5   # secondes entre requêtes

# ── Catégories NAF — regroupements thématiques pour la carte ─────────────────
NAF_THEMES = {
    "agriculture":   ["01", "02", "03"],
    "artisanat":     ["10", "11", "12", "13", "14", "15", "16", "17", "18",
                      "19", "20", "21", "22", "23", "24", "25", "26", "27",
                      "28", "29", "30", "31", "32", "33"],
    "construction":  ["41", "42", "43"],
    "commerce":      ["45", "46", "47"],
    "transport":     ["49", "50", "51", "52", "53"],
    "hébergement":   ["55", "56"],
    "information":   ["58", "59", "60", "61", "62", "63"],
    "finance":       ["64", "65", "66"],
    "immobilier":    ["68"],
    "services_pro":  ["69", "70", "71", "72", "73", "74", "75"],
    "admin_pub":     ["84"],
    "education":     ["85"],
    "santé":         ["86", "87", "88"],
    "culture":       ["90", "91"],
    "sport_loisir":  ["93"],
    "associations":  ["94"],
    "autres":        [],
}


def naf_theme(code: str) -> str:
    """Retourne le thème d'un code NAF (4 chars)."""
    prefix = code[:2] if code else ""
    for theme, prefixes in NAF_THEMES.items():
        if prefix in prefixes:
            return theme
    return "autres"
