"""La purge qui suit la profondeur de collecte — ce qu'elle emporte, ce qu'elle laisse.

Réduire la collecte n'efface pas ce qu'elle a déjà rapporté : les fiches des
communes membres resteraient servies sans jamais se rafraîchir. Elles doivent
donc partir — mais une purge ne se rejoue pas, et deux erreurs ont été trouvées
en la préparant sur une base réelle, toutes deux invisibles à la lecture du
code :

  * `embeddings` comptait comme un rattachement. 726 entreprises sur 3 013
    étaient retenues au seul motif d'avoir été indexées : une fiche se sauvait
    en ayant été lue.
  * partir de la table fille sans regarder le type mettait seize mairies,
    l'intercommunalité et le Parc national dans le lot. SIRENE immatricule les
    collectivités comme le reste, et leur ligne `businesses` existe bel et bien.

Ces tests tiennent les deux, et le principe qui les commande : aucun euro,
aucun mandat, aucun acte ne part avec une fiche.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def purge():
    spec = importlib.util.spec_from_file_location(
        "purger_profondeur", ROOT / "scripts" / "purger_profondeur.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# L'instance factice suit Testonville ; Voisinbourg est une commune membre.
FOND, MEMBRE = "Testonville", "Voisinbourg"


@pytest.fixture
def commerce(base, entite):
    """Une entreprise, sa ligne d'immatriculation, dans la commune voulue."""
    def _creer(nom: str, commune: str, forme: str = "5710",
               type_: str = "business") -> int:
        eid = entite(nom, type_=type_, commune=commune)
        base.execute("INSERT INTO businesses (entity_id, siren, legal_form_code) "
                     "VALUES (?,?,?)", (eid, f"{eid:09d}", forme))
        base.commit()
        return eid
    return _creer


def _lot(purge, base) -> set[int]:
    a_retirer, _, _ = purge.fiches_a_retirer(base)
    return {ligne[0] for lot in a_retirer.values() for ligne in lot}


# ── Ce qui part ──────────────────────────────────────────────────────────────

def test_un_commerce_d_une_commune_membre_part(purge, base, commerce):
    eid = commerce("GARAGE DU PONT", MEMBRE)
    assert eid in _lot(purge, base)


def test_un_commerce_de_la_commune_suivie_reste(purge, base, commerce):
    eid = commerce("BOULANGERIE CENTRALE", FOND)
    assert eid not in _lot(purge, base)


def test_une_commune_sans_nom_ne_se_purge_pas(purge, base, commerce):
    """On ne sait pas où elle est : une purge ne tranche pas ce qu'un classement refuse."""
    eid = commerce("ENSEIGNE SANS ADRESSE", None)
    assert eid not in _lot(purge, base)


# ── Ce qui reste ─────────────────────────────────────────────────────────────

def test_la_mairie_d_une_commune_membre_reste(purge, base, commerce):
    """Type `service` et forme juridique 7210 : une institution du territoire.

    Elle a une ligne `businesses` — c'est sa fiche d'immatriculation, SIREN
    compris. Partir de cette table seule la faisait disparaître.
    """
    eid = commerce("COMMUNE DE VOISINBOURG", MEMBRE, forme="7210", type_="service")
    assert eid not in _lot(purge, base)


def test_une_fiche_de_droit_public_mal_typee_reste(purge, base, commerce):
    """Second garde : même restée typée `business`, sa forme juridique la sauve.

    Une base où le retypage par la forme juridique n'aurait pas tourné ne doit
    pas perdre ses mairies.
    """
    eid = commerce("SYNDICAT DES EAUX", MEMBRE, forme="7353", type_="business")
    assert eid not in _lot(purge, base)


def test_un_titulaire_de_marche_reste(purge, base, commerce):
    eid = commerce("TP DES CEVENNES", MEMBRE)
    base.execute("INSERT INTO marches_publics "
                 "(objet, titulaire_id, acheteur_siren, acheteur_nom, source) "
                 "VALUES (?,?,?,?,?)",
                 ("Réfection de la voirie", eid, "219900017",
                  "Commune de Testonville", "DECP"))
    base.commit()
    assert eid not in _lot(purge, base)


def test_un_beneficiaire_de_subvention_reste(purge, base, commerce):
    eid = commerce("CLUB DE RUGBY", MEMBRE)
    base.execute("INSERT INTO financial_flows (type, to_id, amount) VALUES (?,?,?)",
                 ("subvention", eid, 1500))
    base.commit()
    assert eid not in _lot(purge, base)


def test_une_fiche_seulement_indexee_part(purge, base, commerce):
    """`embeddings` est une trace, pas un rattachement — et elle se régénère."""
    eid = commerce("CAVE COOPERATIVE", MEMBRE)
    base.execute("INSERT INTO embeddings "
                 "(source_table, source_id, entity_id, chunk_text, vector) "
                 "VALUES (?,?,?,?,?)", ("entities", eid, eid, "texte", b"\x00"))
    base.commit()
    assert eid in _lot(purge, base)


# ── Le contrôle final ────────────────────────────────────────────────────────

def test_le_controle_refuse_si_une_deliberation_cite_une_fiche(purge, base, commerce):
    """Une fiche citée par le conseil est un sujet du conseil, où qu'elle soit.

    Le lien partirait en cascade sans rien dire : le contrôle doit le voir.
    """
    eid = commerce("SCIERIE DU CAUSSE", MEMBRE)
    cur = base.execute(
        "INSERT INTO events (type, source, title) VALUES (?,?,?)",
        ("deliberation", "commune.fr", "Convention avec la scierie"))
    base.execute("INSERT INTO event_entities (event_id, entity_id, role) VALUES (?,?,?)",
                 (cur.lastrowid, eid, "sujet"))
    base.commit()
    assert purge.controle_final(base, {eid})


def test_le_controle_laisse_passer_une_annonce_bodacc(purge, base, commerce):
    """C'est justement ce que la purge retire : le step ne la collectera plus."""
    eid = commerce("MENUISERIE DU VALLON", MEMBRE)
    cur = base.execute("INSERT INTO events (type, source, title) VALUES (?,?,?)",
                       ("bodacc_creation", "bodacc", "Immatriculation"))
    base.execute("INSERT INTO event_entities (event_id, entity_id, role) VALUES (?,?,?)",
                 (cur.lastrowid, eid, "sujet"))
    base.commit()
    assert purge.controle_final(base, {eid}) == []


def test_le_controle_voit_un_budget_annexe(purge, base, commerce):
    """Une régie dont la commune vote le budget ne peut pas disparaître."""
    eid = commerce("REGIE DES EAUX", MEMBRE)
    base.execute(
        "INSERT INTO budget_annexe "
        "(entity_id, year, section, sens, libelle, montant, source) "
        "VALUES (?,?,?,?,?,?,?)",
        (eid, 2025, "fonctionnement", "depense", "Achat d'eau", 12000, "DGFiP"))
    base.commit()
    assert purge.controle_final(base, {eid})


# ── Annonces orphelines ──────────────────────────────────────────────────────

def test_une_annonce_dont_le_sujet_part_devient_orpheline(purge, base, commerce):
    eid = commerce("ATELIER DU HAUT", MEMBRE)
    cur = base.execute("INSERT INTO events (type, source, title) VALUES (?,?,?)",
                       ("bodacc_radiation", "bodacc", "Radiation"))
    base.commit()
    base.execute("INSERT INTO event_entities (event_id, entity_id, role) VALUES (?,?,?)",
                 (cur.lastrowid, eid, "sujet"))
    base.commit()
    assert purge.annonces_orphelines(base, {eid}) == [cur.lastrowid]


def test_une_annonce_dont_le_sujet_reste_n_est_pas_touchee(purge, base, commerce):
    garde = commerce("EPICERIE DU FOND", FOND)
    cur = base.execute("INSERT INTO events (type, source, title) VALUES (?,?,?)",
                       ("bodacc_creation", "bodacc", "Immatriculation"))
    base.execute("INSERT INTO event_entities (event_id, entity_id, role) VALUES (?,?,?)",
                 (cur.lastrowid, garde, "sujet"))
    base.commit()
    assert purge.annonces_orphelines(base, set()) == []


# ── Dérivation depuis la configuration ───────────────────────────────────────

def test_un_step_remis_en_institution_n_est_plus_purge(purge, base, commerce,
                                                       monkeypatch):
    """La liste des tables purgeables se dérive de PROFONDEUR_STEP.

    Une instance qui remet `sirene` en « institution » doit voir ce script
    cesser de toucher aux entreprises, sans qu'une ligne change ici.
    """
    eid = commerce("GARAGE DU PONT", MEMBRE)
    assert eid in _lot(purge, base)
    monkeypatch.setitem(purge.PROFONDEUR_STEP, "sirene", "institution")
    assert eid not in _lot(purge, base)
