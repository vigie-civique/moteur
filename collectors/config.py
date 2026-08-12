"""Configuration centrale — collecteurs Lasalle OSINT."""
import pathlib

# ─────────────────────────────────────────────────────────────────────────────
# PÉRIMÈTRE — recadré le 11/08/2026 (T0)
#
# Le périmètre suit la CHAÎNE DE DÉCISION, pas le bassin de vie. On entre dans
# une donnée par l'autorité qui l'a produite ou par le lien à un acteur suivi,
# jamais par la proximité géographique.
#
# L'ancien périmètre (les 7 communes du vallon de la Salindrenque) était un
# périmètre de bassin de vie. Vérifié via geo.api.gouv.fr le 11/08/2026 : ces
# 7 communes relèvent de 3 EPCI distincts (CC Causses Aigoual Cévennes Terres Solidaires,
# CC du Piémont Cévenol, CA Alès Agglomération). Aucune décision commune ne
# les relie. C'est le territoire du média VIF, pas celui de cette veille.
#
#   C1  la commune (Lasalle)                → profondeur maximale
#   C2  l'intercommunalité (CC CAC)         → l'institution ET ses 14 autres
#                                             communes membres, au même niveau
#                                             de collecte (symétrie, 11/08/2026)
#   C3  contexte descendant (Gard, Région)  → filtré par mention, pas collecté
# ─────────────────────────────────────────────────────────────────────────────

# ── C1 — la commune ──────────────────────────────────────────────────────────
COMMUNE_INSEE  = "30140"
COMMUNE_NAME   = "Lasalle"
CODE_POSTAL    = "30460"
DEPARTEMENT    = "30"

# ── Registre de COLLECTE — les 15 communes de l'EPCI ─────────────────────────
# Piloter le périmètre de collecte se fait ici et nulle part ailleurs : rna.py,
# bodacc.py, marches_publics.py, rne.py, fiscalite.py, elections.py,
# georisques.py, insee_social.py, urbanisme_sitadel.py et dgf_notifications.py
# filtrent tous sur ce registre.
#
# COMMUNES ≠ C1. C1, c'est COMMUNE_INSEE seul. Les 14 autres sont C2 : elles
# sont collectées au même niveau (SIRENE, RNA, indicateurs, fiscalité, risques,
# élus, urbanisme, élections) parce qu'elles délèguent leurs compétences à la
# même intercommunalité que Lasalle et siègent au même conseil communautaire.
# La distinction C1/C2 se lit dans `entities.perimetre`, pas ici.
# Source des codes postaux et populations : geo.api.gouv.fr, relevé le 11/08/2026.
COMMUNES = {
    "30140": {"nom": "Lasalle",                    "cp": "30460", "population": 1202},
    "30074": {"nom": "Causse-Bégon",               "cp": "30750", "population": 25},
    "30105": {"nom": "Dourbies",                   "cp": "30750", "population": 177},
    "30108": {"nom": "L'Estréchure",               "cp": "30124", "population": 151},
    "30139": {"nom": "Lanuéjols",                  "cp": "30750", "population": 341},
    "30195": {"nom": "Peyrolles-en-Cévennes",      "cp": "30124", "population": 30},
    "30198": {"nom": "Les Plantiers",              "cp": "30122", "population": 228},
    "30213": {"nom": "Revens",                     "cp": "30750", "population": 37},
    "30229": {"nom": "Saint-André-de-Majencoules", "cp": "30570", "population": 599},
    "30231": {"nom": "Saint-André-de-Valborgne",   "cp": "30940", "population": 366},
    "30297": {"nom": "Saint-Sauveur-Camprieu",     "cp": "30750", "population": 207},
    "30310": {"nom": "Saumane",                    "cp": "30125", "population": 303},
    "30322": {"nom": "Soudorgues",                 "cp": "30460", "population": 269},
    "30332": {"nom": "Trèves",                     "cp": "30750", "population": 116},
    "30339": {"nom": "Val-d'Aigoual",              "cp": "30570", "population": 1412},
}
COMMUNES_INSEE = list(COMMUNES)
# ATTENTION : un code postal ne délimite pas une commune. Le 30460 couvre aussi
# Colognac, Saint-Bonnet-de-Salendrinque, Sainte-Croix-de-Caderle et Vabres, qui
# sont HORS périmètre (autres EPCI) ; le 30750 et le 30570 débordent également.
# Les collecteurs qui interrogent par code postal (RNA/JO, BODACC) sur-collectent
# donc mécaniquement, puis rejettent sur le nom de commune via COMMUNES. Ne pas
# supprimer ce filtre aval en croyant que le CP suffit.
COMMUNES_CP    = sorted({c["cp"] for c in COMMUNES.values()})

# Communes déléguées — la fusion d'une commune nouvelle n'est pas répercutée
# dans toutes les sources ADRESSÉES (SIRENE, DVF continuent d'indexer sous
# l'ancien code). Lasalle n'est concernée par aucune fusion : registre vide.
# Conservé comme point d'accroche pour l'export du modèle vers une commune
# nouvelle. Le cas traité ici jusqu'au 11/08/2026 était Corbès (30094) →
# Thoiras-Corbès (30329), désormais hors périmètre.
COMMUNES_DELEGUEES: dict[str, dict] = {}
COMMUNES_ADRESSE       = {**COMMUNES, **COMMUNES_DELEGUEES}
COMMUNES_INSEE_ADRESSE = list(COMMUNES_ADRESSE)

# ── C2 — l'intercommunalité ──────────────────────────────────────────────────
# Suivie comme INSTITUTION : conseil communautaire et délégués, compétences
# transférées (eau et assainissement depuis 2023, déchets, tourisme…), budget
# principal et annexes, marchés, délibérations.
# Ses 14 autres communes membres sont collectées au même niveau que Lasalle
# (registre COMMUNES ci-dessus) depuis le 11/08/2026 : une base où Soudorgues
# comptait 253 entités et les 13 autres membres aucune n'était pas lisible.
# EPCI_COMMUNES reste la liste de référence de l'EPCI, source geo.api.gouv.fr.
EPCI_SIREN = "200034601"   # SIREN SIRENE confirmé
# Nom officiel, tel qu'il figure au RNE et au répertoire SIRENE. « CC Causses
# Aigoual Cévennes » (sans « Terres Solidaires ») était le nom utilisé jusqu'au
# 12/08/2026 : il est incomplet et ne correspond à aucune source.
EPCI_NOM   = "CC Causses Aigoual Cévennes Terres Solidaires"
# Source : geo.api.gouv.fr/epcis/200034601/communes — relevé le 11/08/2026.
EPCI_COMMUNES = {
    "30074": {"nom": "Causse-Bégon",                "population": 25},
    "30105": {"nom": "Dourbies",                    "population": 177},
    "30108": {"nom": "L'Estréchure",                "population": 151},
    "30139": {"nom": "Lanuéjols",                   "population": 341},
    "30140": {"nom": "Lasalle",                     "population": 1202},
    "30195": {"nom": "Peyrolles-en-Cévennes",       "population": 30},
    "30198": {"nom": "Les Plantiers",               "population": 228},
    "30213": {"nom": "Revens",                      "population": 37},
    "30229": {"nom": "Saint-André-de-Majencoules",  "population": 599},
    "30231": {"nom": "Saint-André-de-Valborgne",    "population": 366},
    "30297": {"nom": "Saint-Sauveur-Camprieu",      "population": 207},
    "30310": {"nom": "Saumane",                     "population": 303},
    "30322": {"nom": "Soudorgues",                  "population": 269},
    "30332": {"nom": "Trèves",                      "population": 116},
    "30339": {"nom": "Val-d'Aigoual",               "population": 1412},
}
EPCI_COMMUNES_INSEE = list(EPCI_COMMUNES)
EPCI_COMMUNES_NOMS  = {c["nom"] for c in EPCI_COMMUNES.values()}

# Structures intercommunales exerçant une compétence de la commune (syndicats
# d'eau, d'assainissement, de déchets, syndicats mixtes). Elles relèvent de C2
# au même titre que l'EPCI : elles décident à la place de la commune.
# Détectées sans liste en dur, par la relation d'adhésion posée sur la commune —
# condition nécessaire à l'export du modèle vers une autre commune.
RELATIONS_ADHESION = ("adhère_à", "membre_de")

# ── Classement des entités (colonne entities.perimetre) ──────────────────────
# 'C1'   commune de collecte
# 'C2'   l'intercommunalité : commune membre de l'EPCI, l'EPCI lui-même, et
#        toute structure à laquelle la commune adhère (RELATIONS_ADHESION)
# 'C3'   autorité supra-communale : préfecture, département, région, agences
#        d'État. Produit des actes qui s'appliquent à C1/C2, n'est pas collectée
#        pour elle-même.
# 'lien' hors périmètre géographique MAIS rattachée à un acteur C1/C2 par une
#        relation, un marché ou un flux financier — le cas des SCI détenues
#        hors commune par des élus de Lasalle, ou d'un titulaire de marché
#        domicilié ailleurs. À conserver : c'est le matériau du graphe
#        d'influence et de la commande publique.
# 'hors' ni l'un ni l'autre → purgeable (scripts/purge_hors_perimetre.py)
PERIMETRES = ("C1", "C2", "C3", "lien", "hors")

# Suivi de fraîcheur par collecteur : (ttl_jours, priorité, table, where).
# Source unique de vérité, consommée par :
#   - `run_all.run_step`      → journal `collector_runs` (tout chemin d'appel)
#   - `scripts/collect_loop`  → relance des sources périmées + backoff
#   - `scripts/qa_loop`       → check_silent_source (alerte source muette)
# Elle vit ici parce que qa_loop doit la lire sans importer les collecteurs.
# `init` n'est pas un collecteur : pas d'entrée. Priorité : petit = d'abord.
STEP_META = {
    "events":     (3,   1,  "events",            ""),
    "cm":         (7,   2,  "events",            "type IN ('deliberation','conseil_municipal')"),
    "marches":    (7,   3,  "marches_publics",   ""),
    "bodacc":     (7,   4,  "events",            "source='bodacc'"),
    "cc_cac":     (14,  5,  "events",            "source LIKE '%cc%'"),
    "banatic":    (30,  5,  "epci_competences",  ""),
    "web":        (7,   6,  "entity_notes",      ""),
    "raa":        (30,  7,  "events",            "type='raa_prefecture'"),
    "profiles":   (30,  8,  "persons",           ""),
    "osm":        (30,  9,  "places",            "osm_category<>'patrimoine'"),
    "sirene":     (30,  10, "businesses",        ""),
    "rna":        (30,  11, "associations",      ""),
    "georisques": (90,  12, "risques_gaspar",    ""),
    "dvf":        (90,  13, "dvf_transactions",  ""),
    "patrimoine": (180, 14, "places",            "osm_category='patrimoine'"),
    "insee":      (180, 15, "insee_indicateurs", ""),
    "rne":        (30,  16, "elus_rne",          ""),
    "fiscalite":  (180, 17, "fiscalite_taux",    ""),
    "sitadel":    (30,  18, "urbanisme_autorisations", ""),
    "elections":  (365, 19, "elections_resultats", ""),
    "dir_deports":(30,  20, "relation_candidates", "signal='deport_conseil'"),
    "dir_web":    (90,  21, "relation_candidates", "signal='site_web_asso'"),
}

# Paths
ROOT        = pathlib.Path(__file__).parent.parent
DB_PATH     = ROOT / "db" / "lasalle.db"
SCHEMA_PATH = ROOT / "db" / "schema.sql"
TERRITOIRE  = ROOT / "territoire"
PROFILS_DIR = ROOT / "profils"
FINANCES    = ROOT / "finances"
ASSOC_DIR   = ROOT / "associations"
ENTRE_DIR   = ROOT / "entreprises"

# APIs
SIRENE_API  = "https://recherche-entreprises.api.gouv.fr/search"
JO_ASSO_API = ("https://www.journal-officiel.gouv.fr/api/explore/v2.1"
               "/catalog/datasets/jo_associations/records")
DVF_API     = "https://api-dvf.cerema.fr/api/v1/mutations/"
BAN_API     = "https://api-adresse.data.gouv.fr/search/"
OVERPASS    = "https://overpass-api.de/api/interpreter"

# Lasalle CM CR base URL
LASALLE_CR  = "https://lasalle.fr/CR/"
LASALLE_URL = "https://www.lasalle.fr"

# HTTP
HEADERS = {
    "User-Agent": "Lasalle-OSINT/1.0 (veille citoyenne, données publiques)"
}
REQUEST_DELAY = 0.5   # secondes entre requêtes

# Coordonnées bbox Lasalle (pour Overpass)
BBOX = (44.01, 3.81, 44.07, 3.90)  # south, west, north, east
CENTROID = (44.050, 3.859)

# Catégories NAF — regroupements thématiques pour la carte
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
