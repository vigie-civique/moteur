"""Un panneau numéroté n'est pas un lieu, un titre déposé n'est pas un nom propre.

Le 22/08/2026, la page « Acteurs publics » de l'atelier de Lasalle affichait dix
lieux nommés « 2 » à « 10 » et « ? » — la totalité de son onglet « Lieu », et sa
tête de liste, les chiffres se triant avant les lettres. OSM range là ses
panneaux d'information et met le NUMÉRO du panneau dans `name`. À côté, 25
titres d'associations portaient leurs guillemets, 280 un point final, et un
était écrit deux fois de suite avec deux orthographes.

Trois gardes en sont sorties, et ces tests les tiennent. Les cas sont relevés
tels quels dans la base ; les inventés sont signalés comme tels.
"""
from __future__ import annotations

import pytest

from collectors.nom_normalise import nettoyer_libelle, normaliser, rectifier
from collectors.osm import nom_utilisable

# ─── nom_utilisable ────────────────────────────────────────────────────────────

# Relevés dans `entities` le 22/08/2026, tous `tourism=information`.
NUMEROS_DE_PANNEAU = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "?", "", "  ", "-", "1"]

VRAIS_LIEUX = [
    "Abîme de Bramabiau",
    "L'Hort de Dieu",
    "Aire de camping-cars de Lanuéjols",
    "4L CÉVENNES",
    "Panneau 3 — le Valat",          # inventé : une borne utilement nommée passe
    "Café",
]


@pytest.mark.parametrize("nom", NUMEROS_DE_PANNEAU)
def test_un_nom_sans_lettre_est_refuse(nom):
    assert not nom_utilisable(nom), f"{nom!r} accepté comme nom de lieu"


def test_un_nom_absent_est_refuse():
    assert not nom_utilisable(None)


@pytest.mark.parametrize("nom", VRAIS_LIEUX)
def test_un_lieu_nomme_passe(nom):
    assert nom_utilisable(nom), f"{nom!r} refusé à tort"


# ─── nettoyer_libelle ──────────────────────────────────────────────────────────

# (ce que la source écrit, ce qu'on affiche)
CAS = [
    # Guillemets du RNA.
    ('"AMIS DE LA BIBLIOTHEQUE DE LASALLE"', "AMIS DE LA BIBLIOTHEQUE DE LASALLE"),
    ('"DES 2 MAINS"', "DES 2 MAINS"),
    ('""SAVEURS ET ARTISANATS DES CAUSSENOLS""', "SAVEURS ET ARTISANATS DES CAUSSENOLS"),
    # Point final déposé avec le titre.
    ("A MAIN NUE.", "A MAIN NUE"),
    ('"LES HABITANTS".', "LES HABITANTS"),
    ("001 LES ATELIERS DU BIEN-ETRE.", "001 LES ATELIERS DU BIEN-ETRE"),
    # …mais le point d'un sigle lui appartient.
    ("A.A.P.P.M.A.", "A.A.P.P.M.A."),
    ("A.A.P.P.M.A. LA SAINT-JEANNAISE.", "A.A.P.P.M.A. LA SAINT-JEANNAISE"),
    # Une parenthèse fermante ne retient rien.
    ("ASSOCIATION DES CONSEILLERS LOCAUX DU GARD (A.C.L.G.).",
     "ASSOCIATION DES CONSEILLERS LOCAUX DU GARD (A.C.L.G.)"),
    # Les points de suspension font partie du nom.
    ("EN ATTENDANT...", "EN ATTENDANT..."),
    ("ON DISAIT QUE...", "ON DISAIT QUE..."),
    # Le nom écrit deux fois, avec deux orthographes (entité 8209).
    ('"APE INTERCOMMUNALE" APE PONT-D\'HERAULT  "APE INTERCOMMUNALE" APE PONT-DHERAULT',
     "APE INTERCOMMUNALE APE PONT-D'HERAULT"),
    # Élision décollée de son mot, dans une adresse.
    ("le Village, 30124 L' Estréchure", "le Village, 30124 L'Estréchure"),
    ("rue de l' Église , 30460 Lasalle", "rue de l'Église, 30460 Lasalle"),
    # Espaces multiples de SIRENE.
    ("SARL CHARDENON  ET FILS", "SARL CHARDENON ET FILS"),
    # Rien à faire : le nom sort intact.
    ("Abîme de Bramabiau", "Abîme de Bramabiau"),
    (None, ""),
]


@pytest.mark.parametrize("source,attendu", CAS)
def test_le_libelle_est_nettoye(source, attendu):
    assert nettoyer_libelle(source) == attendu


@pytest.mark.parametrize("source,_attendu", CAS)
def test_nettoyer_est_idempotent(source, _attendu):
    """`scripts/nettoyer_entites.py` se rejoue sur une base déjà nettoyée. Une
    fonction qui mordrait à chaque passage raccourcirait les noms un peu plus
    à chaque exécution, sans que rien ne le signale."""
    une_fois = nettoyer_libelle(source)
    assert nettoyer_libelle(une_fois) == une_fois


def _sous_suite(petite: str, grande: str) -> bool:
    it = iter(grande)
    return all(c in it for c in petite)


@pytest.mark.parametrize("source,_attendu", [c for c in CAS if c[0]])
def test_la_casse_n_est_jamais_touchee(source, _attendu):
    """599 des 721 titres du RNA sont en capitales parce que le registre les
    publie ainsi. Les rabattre demanderait de reconnaître les sigles — ACVEN,
    4L, A.A.P.P.M.A. — et un sigle abîmé n'est plus le nom de personne.

    L'invariant est plus fort qu'une comparaison de casse : les lettres du
    résultat doivent être une SOUS-SUITE de celles de la source, à la casse
    près de rien du tout. Le nettoyage retire, il n'ajoute ni ne transforme.
    """
    lettres = lambda t: "".join(c for c in t if c.isalpha())
    assert _sous_suite(lettres(nettoyer_libelle(source)), lettres(source))


def test_les_guillemets_ne_font_plus_deux_fiches():
    """`normaliser` est la clé de dédoublonnage. Tant que les guillemets n'y
    étaient pas des séparateurs, « "LES HABITANTS" » et « LES HABITANTS »
    étaient deux associations."""
    assert normaliser('"LES HABITANTS"') == normaliser("LES HABITANTS")
    assert normaliser("«  L'ART SCÈNE. »") == normaliser("l art scene")


# ─── rectifier ─────────────────────────────────────────────────────────────────

LOUUIS = [{"source": "place Louuis Léonard", "lecture": "place Louis Léonard"}]


def test_sans_rectification_declaree_rien_ne_bouge():
    """L'instance de test n'en déclare aucune : une instance qui n'en veut pas
    ne doit voir aucune différence."""
    assert rectifier("place Louuis Léonard") == "place Louuis Léonard"
    assert rectifier(None) is None


def test_une_rectification_declaree_s_applique(monkeypatch):
    monkeypatch.setattr("collectors.config.RECTIFICATIONS", LOUUIS)
    assert rectifier("place Louuis Léonard 30570 Saint-André-de-Majencoules") \
        == "place Louis Léonard 30570 Saint-André-de-Majencoules"


def test_la_variante_en_capitales_sans_accents_aussi(monkeypatch):
    """SIRENE livre ses adresses en capitales et sans accents : une
    rectification qui ne vaudrait que pour une casse laisserait la moitié des
    fiches fautives."""
    monkeypatch.setattr("collectors.config.RECTIFICATIONS", LOUUIS)
    assert rectifier("PLACE LOUUIS LEONARD 30570 ST ANDRE") \
        == "PLACE LOUIS LEONARD 30570 ST ANDRE"


def test_ce_qui_n_est_pas_declare_n_est_pas_touche(monkeypatch):
    """Une RÈGLE (« uu se lit u ») abîmerait « continuum » et les patronymes
    néerlandais. C'est pourquoi il y a une liste, et rien d'autre."""
    monkeypatch.setattr("collectors.config.RECTIFICATIONS", LOUUIS)
    for intact in ("continuum de Vandewalle", "Lennart CLAASSEN", "M VVE BALSAN"):
        assert rectifier(intact) == intact


def test_une_lecture_qui_contient_sa_source_se_rejoue_sans_fin(monkeypatch):
    """La contrainte que la liste doit respecter, démontrée par son contraire :
    une `lecture` contenant sa `source` n'est pas idempotente, et la base
    grossirait d'une occurrence à chaque collecte. Documenté dans `rectifier`.
    """
    monkeypatch.setattr("collectors.config.RECTIFICATIONS", LOUUIS)
    assert rectifier(rectifier("place Louuis Léonard")) == rectifier("place Louuis Léonard")

    monkeypatch.setattr("collectors.config.RECTIFICATIONS",
                        [{"source": "Louis", "lecture": "Louuis Louis"}])
    une = rectifier("place Louis")
    assert rectifier(une) != une, "une lecture qui contient sa source devrait boucler"


def test_upsert_entity_rectifie_a_l_ecriture(base, monkeypatch):
    """Le point d'application est `db.upsert_entity`, seul passage commun à
    tous les collecteurs : une rectification déclarée ne peut plus être défaite
    par une recollecte."""
    from collectors.db import upsert_entity

    monkeypatch.setattr("collectors.config.RECTIFICATIONS", LOUUIS)
    eid = upsert_entity(base, type="association", name="Les amis du pont",
                        address="place Louuis Léonard 30570 Majencoules",
                        commune="Majencoules")
    adresse = base.execute("SELECT address FROM entities WHERE id=?", (eid,)).fetchone()[0]
    assert adresse == "place Louis Léonard 30570 Majencoules"
