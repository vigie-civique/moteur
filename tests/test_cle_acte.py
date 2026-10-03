"""L'identité datée d'un acte : une clé, une seule fonction, et ce qu'elle doit tenir.

Ce que ces tests protègent (03/10/2026) : un lien vers un acte ne doit plus
casser au rejeu de la collecte. La clé reprend l'identité de dédoublonnage de
`conseils.enregistrer_deliberation` — numéro DANS L'ANNÉE, à défaut séance, à
défaut titre — et le dernier repli n'est jamais présenté comme stable.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys

import pytest

from collectors.cle_acte import (FORME, PREFIXE_PAR_TYPE, cle_acte, cle_de_ligne,
                                 cle_seance, numero_normalise, seance_de)


# ── la forme ─────────────────────────────────────────────────────────────────

def test_la_cle_dit_la_portee_l_annee_et_le_numero():
    assert cle_acte("deliberation", "2021-04-14", "41").valeur == "c-2021-41"
    assert cle_acte("deliberation_cc", "2025-04-02", "12").valeur == "cc-2025-12"


def test_le_meme_numero_deux_annees_fait_deux_cles():
    """🔴 Le défaut du 30/09/2026 : sans l'année, la n°41 d'une année écrasait
    celle d'une autre."""
    assert cle_acte("deliberation", "2021-04-14", "41") != cle_acte("deliberation", "2022-05-11", "41")


def test_c_est_l_annee_qui_compte_pas_la_date():
    """La date de télétransmission précède parfois la date de séance : le même
    acte doit garder sa clé quand elle est corrigée."""
    assert cle_acte("deliberation", "2021-04-20", "41") == cle_acte("deliberation", "2021-04-14", "41")


@pytest.mark.parametrize("ecrit", ["41", "n°41", "N° 041", "041", "41/2021", "2021-041", "No41"])
def test_les_ecritures_du_meme_numero_donnent_la_meme_cle(ecrit):
    assert cle_acte("deliberation", "2021-04-14", ecrit).valeur == "c-2021-41"


def test_une_annee_collee_au_numero_n_est_pas_devinee():
    """Dans « DE2026116BIS », rien ne dit où l'année finit : on n'invente pas
    un autre numéro."""
    assert numero_normalise("DE2026116BIS", "2026") == "de2026116bis"


def test_sans_numero_d_acte_la_seance_puis_le_titre():
    par_seance = cle_acte("deliberation", "2021-04-14", None, "3")
    assert (par_seance.valeur, par_seance.faible, par_seance.par) == ("c-2021-04-14-s3", False, "seance")
    faible = cle_acte("deliberation", "2023-03-06", None, None, "Compte administratif 2022")
    assert faible.faible and faible.par == "titre"
    assert faible.valeur.startswith("c-2023-03-06-t")
    # La casse et les espaces ne la changent pas ; une lettre, si — d'où « faible ».
    assert cle_acte("deliberation", "2023-03-06", None, None, "COMPTE  administratif 2022") == faible
    assert cle_acte("deliberation", "2023-03-06", None, None, "Compte administratif 2021") != faible


def test_une_seance_a_sa_cle_et_ses_actes_de_repli_la_prolongent():
    assert cle_seance("conseil_municipal", "2021-04-14").valeur == "c-2021-04-14"
    assert cle_seance("conseil_communautaire", "2025-04-02").valeur == "cc-2025-04-02"
    assert seance_de(cle_acte("deliberation", "2021-04-14", None, "3").valeur) == "c-2021-04-14"
    assert seance_de("c-2021-41") is None


@pytest.mark.parametrize("type_,date", [("deliberation", None), ("deliberation", "sans date"),
                                         ("bodacc", "2021-04-14"), ("conseil_municipal", "2021-04-14")])
def test_pas_de_cle_sans_date_ni_pour_un_autre_type(type_, date):
    assert cle_acte(type_, date, "41") is None


def test_toute_cle_sert_d_ancre_sans_echappement():
    for c in (cle_acte("deliberation", "2021-04-14", "41 bis"),
              cle_acte("deliberation_cc", "2025-01-02", "DE_2025_116"),
              cle_acte("deliberation", "2021-04-14", None, "2021/3"),
              cle_acte("deliberation", "2021-04-14", None, None, "Questions <diverses> « ok »"),
              cle_seance("conseil_municipal", "2021-04-14")):
        assert FORME.match(c.valeur), c.valeur


def test_cle_de_ligne_lit_les_metadonnees():
    meta = json.dumps({"numero_acte": "12"})
    assert cle_de_ligne("deliberation_cc", "2025-04-02", json.loads(meta)).valeur == "cc-2025-12"
    assert cle_de_ligne("conseil_municipal", "2025-04-02", None).valeur == "c-2025-04-02"


def test_la_portee_suit_conseils_portees():
    """La portée vient du TYPE d'événement — la même table que la collecte."""
    conseils = pytest.importorskip("collectors.conseils",
                                   reason="job « tests-deps » : pdfplumber")
    for portee, p in conseils.PORTEES.items():
        attendu = "cc" if portee == "epci" else "c"
        assert PREFIXE_PAR_TYPE[p["seance"]] == PREFIXE_PAR_TYPE[p["delib"]] == attendu


# ── la collecte ──────────────────────────────────────────────────────────────

class _Doc:
    def __init__(self, date, url="https://exemple.invalid/a.pdf"):
        self.date, self.url, self.source, self.libelle = date, url, "exemple.invalid", "PV"
        self.acte, self.meta = None, None


def _delib(numero, titre="Objet", seance=None):
    return {"titre": titre, "texte": "Le conseil décide.", "categorie": None, "tags": [],
            "vote": None, "montants": [], "numero_seance": seance, "numero_acte": numero,
            "regime": "test"}


def test_la_collecte_pose_la_cle_et_retrouve_l_acte_par_elle(base):
    conseils = pytest.importorskip("collectors.conseils", reason="job « tests-deps » : pdfplumber")
    a = conseils.enregistrer_deliberation(base, _Doc("2021-04-14"), "commune", _delib("41"))
    # Rejeu : le numéro écrit autrement, la date de séance corrigée — même acte.
    b = conseils.enregistrer_deliberation(base, _Doc("2021-04-20"), "commune", _delib("041", "Objet relu"))
    autre = conseils.enregistrer_deliberation(base, _Doc("2022-05-11"), "commune", _delib("41"))
    assert a == b != autre
    cles = dict(base.execute("SELECT id, cle_acte FROM events").fetchall())
    assert (cles[a], cles[autre]) == ("c-2021-41", "c-2022-41")
    s = conseils.enregistrer_seance(base, _Doc("2021-04-14"), "commune")
    assert base.execute("SELECT cle_acte FROM events WHERE id=?", (s,)).fetchone()[0] == "c-2021-04-14"


# ── la migration ─────────────────────────────────────────────────────────────

def _ancienne_base(tmp_path, schema_sql):
    """Une base d'avant le 03/10/2026 : pas de colonne `cle_acte`."""
    chemin = tmp_path / "ancienne.db"
    conn = sqlite3.connect(chemin)
    conn.executescript(schema_sql.replace("    cle_acte        TEXT\n", "    fin_de_table    TEXT\n"))
    assert "cle_acte" not in {r[1] for r in conn.execute("PRAGMA table_info(events)")}
    for type_, date, titre, meta in (
            ("deliberation", "2021-04-14", "Captages", {"numero_acte": "41"}),
            ("deliberation", "2022-05-11", "Tarifs", {"numero_acte": "41"}),
            # Deux fiches pour le même acte : une collision à MONTRER.
            ("deliberation_cc", "2025-04-02", "Redevance", {"numero_acte": "12"}),
            ("deliberation_cc", "2025-04-09", "Redevance (doublon)", {"numero_acte": "012"}),
            ("conseil_municipal", "2021-04-14", "Conseil municipal du 14 avril 2021", {}),
            ("deliberation", None, "Sans date", {})):
        conn.execute("INSERT INTO events(type, date, title, metadata) VALUES(?,?,?,?)",
                     (type_, date, titre, json.dumps(meta)))
    conn.commit()
    conn.close()
    return chemin


def _migrer(chemin, *args):
    from pathlib import Path
    racine = Path(__file__).resolve().parent.parent
    import os
    return subprocess.run([sys.executable, "scripts/migrer_cles_actes.py", *args], cwd=racine,
                          env={**os.environ, "VIGIE_DB": str(chemin)},
                          capture_output=True, text=True)


def test_la_migration_est_a_blanc_par_defaut(tmp_path, schema_sql):
    chemin = _ancienne_base(tmp_path, schema_sql)
    r = _migrer(chemin)
    assert r.returncode == 0, r.stderr
    assert "à blanc" in r.stdout and "COLLISIONS" in r.stdout
    conn = sqlite3.connect(chemin)
    assert "cle_acte" not in {x[1] for x in conn.execute("PRAGMA table_info(events)")}


def test_la_migration_pose_les_cles_et_laisse_les_collisions_sans_cle(tmp_path, schema_sql):
    chemin = _ancienne_base(tmp_path, schema_sql)
    r = _migrer(chemin, "--appliquer")
    assert r.returncode == 0, r.stderr
    assert "cc-2025-12" in r.stdout, "la collision est listée, avec sa clé"
    conn = sqlite3.connect(chemin)
    cles = dict(conn.execute("SELECT title, cle_acte FROM events"))
    assert cles["Captages"] == "c-2021-41" and cles["Tarifs"] == "c-2022-41"
    assert cles["Conseil municipal du 14 avril 2021"] == "c-2021-04-14"
    assert cles["Redevance"] is None and cles["Redevance (doublon)"] is None, \
        "deux fiches pour une clé : aucune n'est choisie à la place de quelqu'un"
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 6, "rien n'est fusionné ni effacé"
    # Rejouée, elle ne pose rien de plus.
    r2 = _migrer(chemin, "--appliquer")
    assert "     0  clés posées" in r2.stdout
