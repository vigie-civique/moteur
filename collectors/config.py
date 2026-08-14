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
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
INSTANCE = ROOT / "config" / "instance.json"

if not INSTANCE.exists():
    raise SystemExit(
        f"Aucune instance configurée : {INSTANCE.relative_to(ROOT)} est absent.\n"
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

# ── Bruit propre à la mise en page des PV de cette mairie ─────────────────────
# En-têtes de colonnes, intitulés d'équipements, patronymes d'agents qui
# reviennent à chaque page : `cm_parser` les écarte du découpage en
# délibérations. Ils ne relèvent pas du français mais d'un gabarit de document,
# et parfois ils NOMMENT des personnes — ils ne peuvent donc pas vivre dans le
# moteur, qui est publié. Liste vide par défaut : sans elle, le découpage est
# seulement un peu plus bruyant.
BRUIT_PV: list[str] = _I.get("bruit_pv", [])

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
PAGES       = _I.get("pages", {})     # slugs des pages utiles, par connecteur
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
    # Finances et environnement. Ces collecteurs existaient mais n'étaient
    # appelés par personne : une collecte complète produisait une base sans
    # budget, alors que le site en publie les pages.
    "ofgl":       (180, 22, "ofgl_agregats",     ""),
    "budget":     (180, 23, "budget_annuel",     ""),
    "subventions":(180, 24, "financial_flows",   "source IN ('OFGL','DGCL')"),
    "cm_flux":    (30,  25, "financial_flows",   "source LIKE 'CR CM%'"),
    "eau":        (90,  26, "eau_analyses",      ""),
    "urbanisme":  (90,  27, "events",            "type='urbanisme'"),
    # Pas une source : une dérivation de ce que les autres ont écrit. Journalisée
    # quand même, parce qu'un classement qui n'a pas tourné bloque la publication
    # et doit se lire dans collector_runs comme n'importe quelle panne. Fraîcheur
    # alignée sur le collecteur le plus fréquent : il se périme avec eux.
    "perimetre":  (7,   28, "entities",          "perimetre IS NOT NULL"),
}

# ── Chemins ──────────────────────────────────────────────────────────────────
# La base porte le code INSEE et non le nom de la commune : deux communes
# françaises peuvent s'appeler pareil, leurs codes non.
DB_PATH     = ROOT / "db" / f"{COMMUNE_INSEE}.db"
SCHEMA_PATH = ROOT / "db" / "schema.sql"
TERRITOIRE  = ROOT / "territoire"
PROFILS_DIR = ROOT / "profils"
FINANCES    = ROOT / "finances"
ASSOC_DIR   = ROOT / "associations"
ENTRE_DIR   = ROOT / "entreprises"
SEED_LOCAL  = ROOT / "config" / "seed_local.json"

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
