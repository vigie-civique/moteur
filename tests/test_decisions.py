"""Les décisions d'un atelier s'appliquent-elles sur une AUTRE base ?

C'est la seule question qui compte. Deux ateliers qui collectent la même commune
produisent deux bases dont les `id` n'ont rien à voir : ce sont des compteurs
locaux. Une décision exportée sous « annotation sur l'objet 1430 » ne désigne
rien ailleurs, et l'import la poserait sur un objet pris au hasard.

Ces tests fabriquent donc DEUX bases avec les mêmes entités dans un ordre
différent — donc des identifiants volontairement décalés — et vérifient que la
décision atterrit sur le bon objet.
"""
from __future__ import annotations

import sqlite3

import pytest

from scripts.decisions import cle_entite, cle_evenement, resoudre

SCHEMA = """
CREATE TABLE entities (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, name TEXT,
                       commune TEXT, validation_status TEXT DEFAULT 'unverified');
CREATE TABLE businesses (entity_id INTEGER PRIMARY KEY, siren TEXT UNIQUE);
CREATE TABLE associations (entity_id INTEGER PRIMARY KEY, rna_id TEXT UNIQUE);
CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, date TEXT,
                     source TEXT, source_url TEXT, title TEXT);
CREATE TABLE marches_publics (id INTEGER PRIMARY KEY AUTOINCREMENT, raw_id TEXT,
                              objet TEXT, source TEXT, date_notif TEXT, event_id INTEGER);
CREATE TABLE financial_flows (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT,
                              year INTEGER, amount REAL, description TEXT, source TEXT);
"""


def base(ordre: list[tuple]) -> sqlite3.Connection:
    """Une base peuplée dans l'ordre donné — donc avec les id qui en découlent."""
    c = sqlite3.connect(":memory:")
    c.executescript(SCHEMA)
    for type_, nom, commune, ident in ordre:
        eid = c.execute("INSERT INTO entities (type, name, commune) VALUES (?,?,?)",
                        (type_, nom, commune)).lastrowid
        if type_ == "business" and ident:
            c.execute("INSERT INTO businesses VALUES (?,?)", (eid, ident))
        elif type_ == "association" and ident:
            c.execute("INSERT INTO associations VALUES (?,?)", (eid, ident))
    return c


ACTEURS = [
    ("business", "SARL DU PONT", "Testonville", "812345678"),
    ("association", "LES AMIS DU LAVOIR", "Testonville", "W301234567"),
    ("person", "Camille MERCADIER", "Testonville", None),
    ("service", "École élémentaire", "Testonville", None),
]


def test_les_deux_bases_ont_bien_des_identifiants_differents():
    """Sans quoi le test ne prouverait rien."""
    a, b = base(ACTEURS), base(list(reversed(ACTEURS)))
    id_a = a.execute("SELECT id FROM entities WHERE name='SARL DU PONT'").fetchone()[0]
    id_b = b.execute("SELECT id FROM entities WHERE name='SARL DU PONT'").fetchone()[0]
    assert id_a != id_b


@pytest.mark.parametrize("nom", [a[1] for a in ACTEURS])
def test_une_entite_se_retrouve_dans_une_base_ordonnee_autrement(nom):
    a, b = base(ACTEURS), base(list(reversed(ACTEURS)))
    id_a = a.execute("SELECT id FROM entities WHERE name=?", (nom,)).fetchone()[0]
    cle = cle_entite(a, id_a)[0]

    trouve = resoudre(b, cle)
    assert trouve is not None, f"clé {cle} non résolue"
    assert b.execute("SELECT name FROM entities WHERE id=?", (trouve,)).fetchone()[0] == nom


def test_un_identifiant_officiel_prime_sur_le_nom():
    """Un SIREN désigne la même entreprise partout ; « LA POSTE » non."""
    a = base(ACTEURS)
    eid = a.execute("SELECT id FROM entities WHERE name='SARL DU PONT'").fetchone()[0]
    assert cle_entite(a, eid)[0] == "siren:812345678"


def test_deux_entreprises_homonymes_restent_distinctes_par_leur_siren():
    c = base([("business", "GARAGE CENTRAL", "Testonville", "111111111"),
              ("business", "GARAGE CENTRAL", "Autreville", "222222222")])
    cles = {cle_entite(c, i)[0] for (i,) in c.execute("SELECT id FROM entities")}
    assert cles == {"siren:111111111", "siren:222222222"}


def test_un_acte_se_retrouve_par_son_empreinte_de_source():
    """`events` n'a aucune contrainte d'unicité : la clé est calculée."""
    acte = ("deliberation", "2026-04-13", "mairie.fr",
            "https://mairie.fr/cr/2026-04-13", "Cession de la parcelle AD180")
    a, b = base(ACTEURS), base(list(reversed(ACTEURS)))
    b.execute("INSERT INTO events (type,date,source,source_url,title) VALUES (?,?,?,?,?)",
              ("deliberation", "2026-01-01", "mairie.fr", "https://mairie.fr/x", "Autre acte"))
    for c in (a, b):
        c.execute("INSERT INTO events (type,date,source,source_url,title) VALUES (?,?,?,?,?)", acte)

    id_a = a.execute("SELECT id FROM events WHERE title=?", (acte[4],)).fetchone()[0]
    id_b = b.execute("SELECT id FROM events WHERE title=?", (acte[4],)).fetchone()[0]
    assert id_a != id_b, "les id doivent différer pour que le test ait un sens"
    assert resoudre(b, cle_evenement(a, id_a)[0]) == id_b


def test_deux_actes_du_meme_compte_rendu_ne_se_confondent_pas():
    """Sur les communes qui publient un compte rendu par séance, vingt
    délibérations partagent la même URL : l'URL seule ne peut pas être la clé."""
    c = base([])
    for titre in ("Cession parcelle AD180", "Subvention au comité des fêtes"):
        c.execute("INSERT INTO events (type,date,source,source_url,title) VALUES (?,?,?,?,?)",
                  ("deliberation", "2026-04-13", "mairie.fr",
                   "https://mairie.fr/cr/2026-04-13", titre))
    cles = {cle_evenement(c, i)[0] for (i,) in c.execute("SELECT id FROM events")}
    assert len(cles) == 2


def test_un_marche_se_retrouve_par_son_identifiant_d_avis():
    """Le BOAMP donne un identifiant : il survit à une reformulation de l'objet,
    contrairement à une empreinte du texte."""
    c = base([])
    ev = c.execute("INSERT INTO events (type,title) VALUES ('marché_public','Voirie')").lastrowid
    c.execute("INSERT INTO marches_publics (raw_id, objet, event_id) VALUES (?,?,?)",
              ("boamp_24-99887", "Voirie", ev))
    assert cle_evenement(c, ev)[0] == "marche:boamp_24-99887"
    assert resoudre(c, "marche:boamp_24-99887") is not None


def test_une_cle_absente_renvoie_None_plutot_que_de_deviner():
    """L'autre atelier a pu collecter ce que cette base n'a pas. L'import doit
    le signaler, jamais rattacher au hasard."""
    assert resoudre(base(ACTEURS), "siren:999999999") is None
    assert resoudre(base(ACTEURS), "acte:0000000000000000") is None
