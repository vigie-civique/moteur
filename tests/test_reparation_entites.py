"""Le type d'une fiche vient de sa source, et une structure n'a qu'une fiche.

Trois défauts se répondaient, et sortaient ensemble sur le même exemple réel :
l'association VIVALTO de Lasalle existait en TROIS fiches — une « entreprise »
née de SIRENE, une association au nom recollé « VIVALTO. VIV'ALTO », une autre
née du compte rendu — et ses six années de subvention étaient réparties sur
deux d'entre elles. Aucune ne disait la vérité.

  1. `sirene` écrivait `type="business"` sans lire `nature_juridique`, que le
     collecteur stockait pourtant juste après ;
  2. `rna` repliait sur `titre_search`, un champ d'INDEXATION, quand `titre`
     est vide — ce qu'il est sur toute annonce de Modification ;
  3. l'entité était cherchée par son NOM alors que la fiche est unique par
     `rna_id` : le `INSERT OR IGNORE` avalait la collision, laissant une entité
     sans identifiant ni objet.
"""
from __future__ import annotations

import json

import pytest

from collectors.formes_juridiques import type_pour_forme
from collectors.rna import titre_du_record
from scripts.fusionner_entites import choisir_garde, fusionner, grappes, jeton


# ── La forme juridique dit le type ───────────────────────────────────────────

@pytest.mark.parametrize("code, attendu", [
    ("9220", "association"),   # association déclarée
    ("9230", "association"),   # reconnue d'utilité publique
    ("7210", "service"),       # commune
    ("7172", "service"),       # administration de l'État
    ("7321", "service"),       # association syndicale autorisée
    ("1000", "business"),      # entrepreneur individuel
    ("5499", "business"),      # SAS
    ("9150", "business"),      # association syndicale libre — hors table, exprès
    ("", "business"),
    (None, "business"),
])
def test_type_pour_forme(code, attendu):
    assert type_pour_forme(code) == attendu


def test_sirene_type_une_association_comme_telle(base, monkeypatch):
    from collectors import sirene

    monkeypatch.setattr(sirene, "upsert_entity", _upsert_direct(base))
    sirene._import_one(base, {
        "siren": "804557353", "nom_complet": "VIV'ALTO",
        "nature_juridique": "9220", "etat_administratif": "A",
        "date_creation": "2013-11-06", "siege": {},
    }, counters=(0, 0, 0), commune="Lasalle")

    r = base.execute("SELECT type FROM entities WHERE name=?", ("VIV'ALTO",)).fetchone()
    assert r["type"] == "association"
    # La fiche SIRENE reste écrite : c'est elle qui porte le SIREN et le NAF.
    assert base.execute("SELECT siren FROM businesses WHERE entity_id="
                        "(SELECT id FROM entities WHERE name=?)",
                        ("VIV'ALTO",)).fetchone()["siren"] == "804557353"
    # Et le SIREN est recopié sur la fiche association : c'est le SEUL champ
    # que SIRENE et le RNA ont en commun, donc le seul point de rencontre.
    assert base.execute("SELECT siren FROM associations WHERE entity_id="
                        "(SELECT id FROM entities WHERE name=?)",
                        ("VIV'ALTO",)).fetchone()["siren"] == "804557353"


def test_sirene_type_une_commune_en_service(base, monkeypatch):
    from collectors import sirene

    monkeypatch.setattr(sirene, "upsert_entity", _upsert_direct(base))
    sirene._import_one(base, {
        "siren": "213001411", "nom_complet": "COMMUNE DE LASALLE",
        "nature_juridique": "7210", "siege": {},
    }, counters=(0, 0, 0), commune="Lasalle")
    assert base.execute("SELECT type FROM entities WHERE name=?",
                        ("COMMUNE DE LASALLE",)).fetchone()["type"] == "service"


def _upsert_direct(base):
    """`upsert_entity` réduit à l'essentiel : la config d'instance n'est pas ici."""
    def _u(conn, *, type, name, short_name=None, lat=None, lng=None,
           address=None, confidence="verified", commune=None):
        row = conn.execute("SELECT id FROM entities WHERE type=? AND name=?",
                           (type, name)).fetchone()
        if row:
            return row["id"]
        return conn.execute(
            "INSERT INTO entities (type,name,name_norm,short_name,commune,confidence)"
            " VALUES (?,?,?,?,?,?)",
            (type, name, name.lower(), short_name, commune, confidence)).lastrowid
    return _u


# ── Le nom d'une association vient de l'annonce, pas de l'index ──────────────

ANNONCE_MODIFICATION = {
    "id": "201500260506", "numero_rna": "W303001619",
    "titre": None,
    "titre_search": "VIVALTO. VIV'ALTO.  VIVALTO VIVALTO",
    "commune_actuelle": "Lasalle",
    "contenu": json.dumps({"assoLoi1901": {
        "dateDeclaration": "2015-06-14",
        "modification": {"ancienTitre": "VIVALTO.", "nouveauTitre": "VIV'ALTO."},
    }}),
}


def test_titre_vient_de_nouveau_titre():
    """`titre_search` empile ancien titre, nouveau titre et formes normalisées.

    Le prendre pour un nom fabriquait « VIVALTO. VIV'ALTO » — un libellé que
    personne ne porte, et qui ne pouvait plus rejoindre la fiche « VIVALTO ».
    """
    assert titre_du_record(ANNONCE_MODIFICATION) == "VIV'ALTO"


def test_titre_normal_intouche():
    assert titre_du_record({"titre": "LES AMIS DE LASALLE"}) == "LES AMIS DE LASALLE"


def test_contenu_illisible_ne_leve_pas():
    assert titre_du_record({"titre": None, "titre_search": "REPLI",
                            "contenu": "{pas du json"}) == "REPLI"


# ── Deux annonces, une association ───────────────────────────────────────────

def test_deux_annonces_meme_rna_une_seule_entite(base, monkeypatch):
    """La fiche est unique par `rna_id`, pas par nom.

    Chercher par le nom faisait une entité par graphie, et le
    `INSERT OR IGNORE` suivant échouait en silence sur `rna_id UNIQUE` : la
    seconde entité restait sans identifiant, sans objet, irrattachable.
    """
    from collectors import rna

    monkeypatch.setattr(rna, "upsert_entity", _upsert_direct(base))
    monkeypatch.setattr(rna, "_match_commune", lambda v: v or None)

    creation = {"id": "199900410468", "numero_rna": "W303001619",
                "titre": "VIVALTO", "objet": "musique classique",
                "commune_actuelle": "Lasalle", "typeavis": "Création"}
    rna._import_jo_record(base, creation)
    rna._import_jo_record(base, ANNONCE_MODIFICATION)

    ids = base.execute(
        "SELECT id, name FROM entities WHERE type='association'").fetchall()
    assert len(ids) == 1, [dict(r) for r in ids]
    # Le `nouveauTitre` est une déclaration de changement de nom : elle vaut.
    assert ids[0]["name"] == "VIV'ALTO"
    fiche = base.execute("SELECT rna_id, object FROM associations"
                         " WHERE entity_id=?", (ids[0]["id"],)).fetchone()
    assert fiche["rna_id"] == "W303001619"
    assert fiche["object"] == "musique classique"   # complété, pas écrasé


def test_renommage_refuse_si_le_nom_est_pris(base, monkeypatch, entite):
    """Renommer sur un nom occupé, c'est une fusion — pas une décision de collecte."""
    from collectors import rna

    monkeypatch.setattr(rna, "upsert_entity", _upsert_direct(base))
    monkeypatch.setattr(rna, "_match_commune", lambda v: v or None)
    entite("VIV'ALTO", "association", "Lasalle")
    rna._import_jo_record(base, {"numero_rna": "W303001619", "titre": "VIVALTO",
                                 "commune_actuelle": "Lasalle"})
    rna._import_jo_record(base, ANNONCE_MODIFICATION)
    noms = {r["name"] for r in base.execute(
        "SELECT name FROM entities WHERE type='association'")}
    assert noms == {"VIV'ALTO", "VIVALTO"}      # rien d'écrasé, rien de perdu


# ── La fusion ────────────────────────────────────────────────────────────────

def test_fusion_reporte_l_argent(base, entite):
    """Une subvention ne se perd pas en route. C'est toute la raison de l'outil."""
    garde = entite("VIV'ALTO", "association", "Lasalle")
    absorbe = entite("VIVALTO", "association", "Lasalle")
    commune = entite("Commune de Lasalle", "service", "Lasalle")
    for annee, montant, cible in ((2021, 2200, absorbe), (2024, 1800, garde)):
        base.execute("INSERT INTO financial_flows (type,year,amount,from_id,to_id)"
                     " VALUES ('subvention',?,?,?,?)", (annee, montant, commune, cible))
    base.commit()

    fusionner(base, garde, absorbe)

    flux = base.execute("SELECT year, amount FROM financial_flows"
                        " WHERE to_id=? ORDER BY year", (garde,)).fetchall()
    assert [(r["year"], r["amount"]) for r in flux] == [(2021, 2200), (2024, 1800)]
    assert base.execute("SELECT 1 FROM entities WHERE id=?", (absorbe,)).fetchone() is None


def test_fusion_ecarte_le_doublon_sans_le_dupliquer(base, entite):
    """La même relation des deux côtés ne doit pas ressortir en double."""
    garde = entite("LA SOIERIE", "association", "Lasalle")
    absorbe = entite("La Soierie", "place", "Lasalle")
    personne = entite("Jean DUPONT", "person", "Lasalle")
    for cible in (garde, absorbe):
        base.execute("INSERT INTO relations (from_id,to_id,relation_type,source)"
                     " VALUES (?,?,'président','rna')", (personne, cible))
    base.commit()

    fusionner(base, garde, absorbe)

    assert base.execute("SELECT COUNT(*) FROM relations WHERE to_id=?",
                        (garde,)).fetchone()[0] == 1
    assert base.execute("SELECT COUNT(*) FROM relations").fetchone()[0] == 1


def test_fusion_complete_les_champs_vides(base, entite):
    garde = entite("VIV'ALTO", "association", "Lasalle")
    absorbe = entite("VIVALTO", "association", "Lasalle")
    base.execute("UPDATE entities SET address=?, lat=?, lng=? WHERE id=?",
                 ("95 rue de la Place", 44.1, 3.8, absorbe))
    base.execute("INSERT INTO associations (entity_id, rna_id) VALUES (?,?)",
                 (garde, "W303001619"))
    base.execute("INSERT INTO associations (entity_id, object) VALUES (?,?)",
                 (absorbe, "musique classique"))
    base.commit()

    fusionner(base, garde, absorbe)

    e = base.execute("SELECT address, lat FROM entities WHERE id=?", (garde,)).fetchone()
    assert e["address"] == "95 rue de la Place" and e["lat"] == 44.1
    a = base.execute("SELECT rna_id, object FROM associations WHERE entity_id=?",
                     (garde,)).fetchone()
    assert a["rna_id"] == "W303001619" and a["object"] == "musique classique"


def test_fusion_supprime_la_boucle_sur_soi(base, entite):
    """Après fusion, « X dirige X » n'est pas une relation : c'est une cicatrice."""
    garde = entite("LA SOIERIE", "association", "Lasalle")
    absorbe = entite("La Soierie", "business", "Lasalle")
    base.execute("INSERT INTO relations (from_id,to_id,relation_type,source)"
                 " VALUES (?,?,'même_adresse','profile')", (garde, absorbe))
    base.commit()
    fusionner(base, garde, absorbe)
    assert base.execute("SELECT COUNT(*) FROM relations").fetchone()[0] == 0


def test_choisir_garde_prefere_la_fiche_identifiee(base, entite):
    """Six subventions ne valent pas un identifiant : l'argent se déplace, l'identité non."""
    identifiee = entite("VIV'ALTO", "association", "Lasalle")
    fournie = entite("VIVALTO", "association", "Lasalle")
    base.execute("INSERT INTO associations (entity_id, rna_id) VALUES (?,?)",
                 (identifiee, "W303001619"))
    commune = entite("Commune de Lasalle", "service", "Lasalle")
    for annee in range(2021, 2027):
        base.execute("INSERT INTO financial_flows (type,year,amount,from_id,to_id)"
                     " VALUES ('subvention',?,1000,?,?)", (annee, commune, fournie))
    base.commit()
    assert choisir_garde(base, [identifiee, fournie]) == identifiee


def test_un_numero_d_annonce_ne_vaut_pas_un_identifiant(base, entite):
    """`ASS00786` n'est pas un numéro RNA : c'est un numéro d'annonce du JO.

    Le prendre pour un identifiant national ferait croire à deux associations
    distinctes, et interdirait la fusion précisément là où elle est due.
    """
    a = entite("ASSOCIATION DZOGCHEN", "association", "Lasalle")
    b = entite("Association Dzogchen", "association", "Lasalle")
    base.execute("INSERT INTO associations (entity_id, rna_id) VALUES (?,?)",
                 (a, "ASS00786"))
    base.execute("INSERT INTO associations (entity_id, rna_id) VALUES (?,?)",
                 (b, "W303000451"))
    base.commit()
    grappe = [g for g in grappes(base) if {m["id"] for m in g["membres"]} == {a, b}]
    assert len(grappe) == 1
    assert grappe[0]["obstacle"] is None
    assert choisir_garde(base, [a, b]) == b


def test_deux_siren_distincts_ne_se_fusionnent_pas(base, entite):
    """Deux SIREN, deux personnes morales. Aucune ressemblance de nom ne vaut contre ça."""
    a = entite("LES AMIS DU PONT", "association", "Lasalle")
    b = entite("Les Amis du Pont", "business", "Lasalle")
    base.execute("INSERT INTO businesses (entity_id, siren) VALUES (?,?)", (a, "111111111"))
    base.execute("INSERT INTO businesses (entity_id, siren) VALUES (?,?)", (b, "222222222"))
    base.commit()
    grappe = [g for g in grappes(base) if {m["id"] for m in g["membres"]} == {a, b}]
    assert grappe and grappe[0]["obstacle"] and "SIREN" in grappe[0]["obstacle"]


def test_grappes_ignorent_les_personnes(base, entite):
    """« ALAIN ANDRE » l'entreprise et « Alain ANDRE » la personne ne sont pas un doublon.

    C'est une entreprise individuelle : le nom de l'entreprise EST celui de son
    fondateur. Les fusionner mettrait une personne et une société dans la même
    fiche — 1 285 fois sur la seule instance de Lasalle.
    """
    entite("ALAIN ANDRE", "business", "Lasalle")
    entite("Alain ANDRE", "person", "Lasalle")
    assert not [g for g in grappes(base)
                if any(m["name"].upper() == "ALAIN ANDRE" for m in g["membres"])]


def test_grappes_ne_franchissent_pas_les_communes(base, entite):
    entite("COMITE DES FETES", "association", "Lasalle")
    entite("Comité des fêtes", "association", "Soudorgues")
    assert not grappes(base)


def test_jeton_soude_les_apostrophes():
    assert jeton("VIV'ALTO") == jeton("VIVALTO") == frozenset({"vivalto"})
    assert jeton("Les Amis de la Bibliothèque") == frozenset({"amis", "bibliotheque"})


def test_un_lieu_homonyme_ne_se_fusionne_pas_tout_seul(base, entite):
    """Un point OSM qui porte le nom d'une association peut être son local.

    Et un local peut en abriter plusieurs. Le nom ne tranche pas — ces
    grappes-là sortent en liste, elles ne se fusionnent pas d'office.
    """
    entite("LA SOIERIE", "association", "Lasalle")
    entite("La Soierie", "place", "Lasalle")
    g = [x for x in grappes(base) if len(x["membres"]) == 2]
    assert g and g[0]["obstacle"] == "un lieu et une structure portent le même nom"


def test_fusion_herite_d_un_identifiant_unique(base, entite):
    """`rna_id` est UNIQUE : recopier avant de supprimer ferait porter le même
    identifiant aux deux fiches le temps d'un UPDATE — et la fusion échouait là."""
    garde = entite("VIV'ALTO", "association", "Lasalle")
    absorbe = entite("VIVALTO", "association", "Lasalle")
    base.execute("INSERT INTO associations (entity_id, object) VALUES (?,?)",
                 (garde, "musique"))
    base.execute("INSERT INTO associations (entity_id, rna_id) VALUES (?,?)",
                 (absorbe, "W303001619"))
    base.commit()
    fusionner(base, garde, absorbe)
    a = base.execute("SELECT rna_id, object FROM associations WHERE entity_id=?",
                     (garde,)).fetchone()
    assert a["rna_id"] == "W303001619" and a["object"] == "musique"
