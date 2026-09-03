"""`public_entity` — la fonction qui décide, fiche par fiche.

Elle applique quatre règles dans l'ordre : niveau de confiance, rôle civique
pour les personnes, périmètre, puis pertinence. Chacune a son motif de rejet,
consigné dans les statistiques du snapshot pour que les exclusions se comptent
au lieu de se deviner.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def bps():
    spec = importlib.util.spec_from_file_location(
        "build_public_snapshot", ROOT / "scripts" / "build_public_snapshot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fiche(**kw) -> dict:
    base = {"id": 1, "type": "business", "name": "Une entreprise",
            "confidence": "verified", "perimetre": "C1", "commune": "Testonville"}
    base.update(kw)
    return base


# ── Niveau de confiance ──────────────────────────────────────────────────────

@pytest.mark.parametrize("niveau", ["probable", "hypothesis", "unverified", "retracted"])
def test_confidence_privee_rejetee(bps, niveau):
    publiee, motifs = bps.public_entity(fiche(confidence=niveau), [], set())
    assert publiee is None
    assert motifs == ["private_confidence"]


@pytest.mark.parametrize("niveau", ["verified", "confirmed"])
def test_confidence_publique_acceptee(bps, niveau):
    publiee, _ = bps.public_entity(fiche(confidence=niveau), [], set())
    assert publiee is not None


# ── Personnes : jamais sans rôle civique ─────────────────────────────────────

def test_personne_sans_role_civique_rejetee(bps):
    publiee, motifs = bps.public_entity(
        fiche(type="person", name="Un particulier"), [], set())
    assert publiee is None
    assert motifs == ["person_without_public_civic_role"]


def test_personne_avec_role_civique_publiee(bps):
    publiee, _ = bps.public_entity(
        fiche(id=7, type="person", name="Une élue"), [], {7})
    assert publiee is not None


# ── Périmètre ────────────────────────────────────────────────────────────────

def test_entite_non_classee_rejetee(bps):
    publiee, motifs = bps.public_entity(fiche(perimetre=None), [], set())
    assert publiee is None
    assert motifs == ["hors_fiche_perimetre_None"]


def test_commerce_de_commune_voisine_rejete(bps):
    publiee, motifs = bps.public_entity(fiche(perimetre="C2"), [], set())
    assert publiee is None
    assert "perimetre" in motifs[0]


def test_institution_intercommunale_publiee(bps):
    publiee, _ = bps.public_entity(
        fiche(type="service", name="CC des Épreuves Réunies", perimetre="C2"),
        [], set())
    assert publiee is not None


def test_elu_communautaire_publie(bps):
    """Il vote le budget qui s'applique à la commune : le masquer amputerait la
    chaîne de décision de sa moitié intercommunale."""
    publiee, _ = bps.public_entity(
        fiche(id=9, type="person", name="Un délégué", perimetre="C2"),
        [], {9}, ids_conseil_communautaire={9})
    assert publiee is not None


# ── Flux financiers : un montant ne sort pas sans ses deux extrémités ────────
# Les relations avaient cette règle (`endpoint_not_public`) depuis toujours, les
# flux ne l'ont jamais eue : le filtre voisin ne regardait que les personnes
# physiques. Un flux vers une association d'une commune limitrophe sortait donc
# avec un lien vers une fiche que le snapshot n'écrit pas, et le build du site
# s'arrêtait sur `404 /entite/<id> (linked from /finances)` — l'instance entière
# impubliable à cause de trois associations.

def test_flux_vers_une_entite_publiee_passe(bps):
    assert bps.flux_extremites_publiees({"from_id": 1, "to_id": 2}, {1, 2})


def test_flux_vers_une_entite_non_publiee_ecarte(bps):
    assert not bps.flux_extremites_publiees({"from_id": 1, "to_id": 8405}, {1})


def test_flux_depuis_une_entite_non_publiee_ecarte(bps):
    """Les deux sens comptent : une subvention REÇUE d'une entité écartée
    renverrait vers la même fiche absente."""
    assert not bps.flux_extremites_publiees({"from_id": 8405, "to_id": 1}, {1})


def test_flux_sans_beneficiaire_identifie_reste(bps):
    """Une extrémité vide ne prétend renvoyer nulle part : le flux se publie,
    sans lien. L'écarter effacerait de l'argent public au motif que le
    collecteur n'a pas su nommer qui l'a touché."""
    assert bps.flux_extremites_publiees({"from_id": 1, "to_id": None}, {1})


# ── Marchés : le lien tombe, la pièce reste ──────────────────────────────────
# Un flux est écarté quand son extrémité n'a pas de fiche ; un marché non. La
# pièce décrit un achat de la collectivité, et le nom du titulaire est public —
# seul le renvoi vers une fiche absente est coupé. Saillans, 23/08/2026 : deux
# titulaires C2 d'un marché intercommunal refusaient le snapshot entier.

def test_titulaire_sans_fiche_perd_son_lien_pas_son_nom(bps):
    marches = [{"id": 1, "acheteur_id": 5, "titulaire_id": 19017,
                "titulaire_nom": "TRUCKS SOLUTIONS VALENCE"}]
    assert bps.delier_renvois_morts(marches, {5}) == 1
    assert marches[0]["titulaire_id"] is None
    assert marches[0]["acheteur_id"] == 5
    assert marches[0]["titulaire_nom"] == "TRUCKS SOLUTIONS VALENCE"


def test_acheteur_sans_fiche_perd_son_lien_aussi(bps):
    marches = [{"id": 1, "acheteur_id": 8405, "titulaire_id": 2}]
    assert bps.delier_renvois_morts(marches, {2}) == 1
    assert marches[0]["acheteur_id"] is None


def test_marche_entierement_publie_est_laisse_intact(bps):
    marches = [{"id": 1, "acheteur_id": 5, "titulaire_id": 2}]
    assert bps.delier_renvois_morts(marches, {2, 5}) == 0
    assert (marches[0]["acheteur_id"], marches[0]["titulaire_id"]) == (5, 2)


def test_un_renvoi_absent_nest_pas_un_renvoi_mort(bps):
    """`NULL` ne prétend renvoyer nulle part : rien à couper, rien à compter —
    sinon le décompte des exclusions gonflerait de marchés que personne n'a
    déliés."""
    marches = [{"id": 1, "acheteur_id": 5, "titulaire_id": None}]
    assert bps.delier_renvois_morts(marches, {5}) == 0


# ── L'ordre des règles est lui-même une garantie ─────────────────────────────

def test_une_personne_privee_c1_reste_privee(bps):
    """Le bon périmètre n'ouvre aucun droit : les règles s'additionnent."""
    publiee, _ = bps.public_entity(
        fiche(type="person", name="Un habitant", perimetre="C1"), [], set())
    assert publiee is None


def test_une_piste_c1_reste_privee(bps):
    publiee, _ = bps.public_entity(
        fiche(perimetre="C1", confidence="hypothesis"), [], set())
    assert publiee is None


# ── Le bénéficiaire d'une aide n'est pas un élu ──────────────────────────────
# Ajouté le 21/08/2026, en ouvrant la saisie manuelle et l'extraction assistée.
# Le modèle a sorti d'un vrai PV, correctement, des aides à la rénovation de
# façades NOMINATIVES : « Mme BOURRET Martine », « M. et Mme DUEZ », avec le
# numéro de rue. Ce sont des particuliers qui reçoivent de l'argent public — la
# collecte les prend (doctrine de l'atelier), la publication ne doit pas.
#
# Le risque est précis : saisir un flux crée une RELATION vers le bénéficiaire,
# et une relation est justement ce qui rend une personne publiable. Le 19/08,
# 1 229 fiches d'entités écartées dont 80 personnes physiques ont été servies en
# production. Ces trois tests ferment la porte par le code, pas par l'attention.

def test_beneficiaire_dune_aide_nest_pas_publiable(bps):
    """Recevoir de l'argent public n'entre PAS une personne dans l'ensemble
    civique : sa fiche est refusée, et pour ce motif précis."""
    publiee, motifs = bps.public_entity(
        fiche(id=42, type="person", name="Une bénéficiaire", perimetre="C1"),
        [], set())
    assert publiee is None
    assert motifs == ["person_without_public_civic_role"]


def test_seuls_les_roles_civiques_ouvrent_la_publication(bps):
    """Contrôle croisé sur les règles elles-mêmes : si un type de relation
    « économique » entrait un jour dans la liste civique, toute personne payée
    par la commune deviendrait publiable d'un coup, et silencieusement."""
    import json
    regles = json.loads(
        (ROOT / "config" / "publication_rules.exemple.json").read_text(encoding="utf-8"))
    civiques = set(regles["people"]["publish_only_with_relation_types"])
    jamais = {"subventionné", "locataire_commune", "bail", "cession",
              "prestataire", "titulaire", "acheteur"}
    assert not (civiques & jamais), (
        f"rôles non civiques dans la liste de publication : {civiques & jamais}")


def test_un_elu_reste_publiable(bps):
    """Le contre-test : fermer la porte ne doit pas fermer la maison. Une
    personne entrée dans l'ensemble civique en amont reste publiée."""
    publiee, _ = bps.public_entity(
        fiche(id=7, type="person", name="Une élue", perimetre="C1"), [], {7})
    assert publiee is not None


# ── L'allowlist des sources ──────────────────────────────────────────────────

def test_toute_source_de_marche_est_publiable():
    """Une source qu'on collecte et que l'allowlist ignore est une source morte.

    `events.public_sources` compare à l'IDENTIQUE, et elle a longtemps été
    fabriquée à partir des DOMAINES de l'instance plus quelques mots-clés —
    « BOAMP », « bodacc », « sitadel », « interieur ». Les trois libellés DECP
    n'y figuraient sur aucune instance : 53 marchés collectés sur l'une d'elles,
    aucun publié, et rien ne le signalait. C'est la source la plus sûre du lot,
    la seule qui recoupe par SIREN d'acheteur.

    Ce test porte sur les règles D'EXEMPLE, celles que reçoit toute nouvelle
    instance : c'est là que le défaut naissait.
    """
    import json

    from collectors.marches_publics import SOURCES

    regles = json.loads(
        (ROOT / "config" / "publication_rules.exemple.json").read_text(encoding="utf-8"))
    publiables = set(regles["events"]["public_sources"])

    absentes = [s for s in SOURCES if s not in publiables]
    assert not absentes, (
        f"sources collectées mais non publiables : {absentes}. "
        "Le collecteur écrit ces libellés dans events.source ; l'allowlist les "
        "compare à l'identique.")


def test_toute_source_d_evenement_est_publiable():
    """Le même défaut, généralisé : ce qui écrit un `event` doit être publiable.

    `ccomptes` a été ajouté aux trois instances le 01/09 et OUBLIÉ dans les
    règles d'exemple : une instance amorcée depuis ce fichier collectait les
    rapports de chambre régionale des comptes et ne les publiait jamais. Le
    défaut ne se voit pas — la collecte réussit, la page reste vide.

    Ce test lit les constantes `SOURCE` des collecteurs qui écrivent dans
    `events`, et exige qu'elles figurent dans l'allowlist d'exemple. Ajouter un
    collecteur d'événements sans l'y déclarer fait donc échouer la suite, au
    lieu de produire une source morte.
    """
    import json

    from collectors import crc, plu

    regles = json.loads(
        (ROOT / "config" / "publication_rules.exemple.json").read_text(encoding="utf-8"))
    publiables = set(regles["events"]["public_sources"])

    # Les collecteurs qui écrivent un `event` avec leur propre libellé de source.
    sources = {"crc": crc.SOURCE, "plu": plu.SOURCE}
    absentes = {nom: s for nom, s in sources.items() if s not in publiables}
    assert not absentes, (
        f"collecteurs dont la source n'est pas publiable : {absentes}. "
        "L'événement sera collecté et jamais publié, sans que rien ne le dise.")


# ── Les fossiles de la base permanente des équipements ───────────────────────

def test_les_lignes_bpe_fossiles_ne_sont_plus_publiees(bps, tmp_path):
    """La BPE a déménagé de `insee_social` vers `equipements`, avec sa
    nomenclature. Cesser de la collecter n'a pas effacé ce qui était déjà en
    base : 502 lignes sur Lasalle, 97 % sans libellé, publiées à côté des
    lignes propres. Les mêmes faits deux fois, dont une illisible.

    L'essai porte sur la REQUÊTE de publication, pas sur son texte : il la joue
    contre une base et compte ce qui sort.
    """
    import sqlite3

    base = tmp_path / "essai.db"
    conn = sqlite3.connect(base)
    conn.execute("""CREATE TABLE insee_indicateurs (
        insee TEXT, commune TEXT, dataset TEXT, indicateur TEXT,
        libelle TEXT, annee TEXT, valeur REAL, dims TEXT)""")
    conn.executemany(
        "INSERT INTO insee_indicateurs VALUES (?,?,?,?,?,?,?,?)", [
            ("30140", "Lasalle", "DS_BPE", "BPE_A104", None, "2025", 3.0, None),
            ("30140", "Lasalle", "DS_BPE", "BPE_A129", None, "2025", 1.0, None),
            ("30140", "Lasalle", "DS_RP_POPULATION", "POP", "Population",
             "2022", 1080.0, None),
        ])
    conn.commit()
    conn.row_factory = sqlite3.Row

    sortis = [dict(r) for r in conn.execute(bps.INSEE_PUBLIABLES)]
    assert [r["indicateur"] for r in sortis] == ["POP"]
    assert all(r["dataset"] != "DS_BPE" for r in sortis)
