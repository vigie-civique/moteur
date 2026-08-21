"""La saisie manuelle : ce qu'elle écrit, et ce qu'elle ne peut pas toucher.

Deux propriétés à tenir, et elles comptent autant l'une que l'autre.

**Rejouable** — une saisie vit dans `config/saisies.json` et non en base, parce
que la base est reconstructible et le jugement humain non. Si le rejeu n'est pas
idempotent, chaque collecte double les montants publiés : ce piège a déjà été
payé deux fois dans ce projet, sur les subventions puis sur les baux.

**Cloisonnée** — le collecteur de saisies n'écrit et ne supprime que des lignes
dont il est l'auteur. La règle « ne pas corrompre ce qui vient d'un collecteur
institutionnel » doit tenir même si le fichier de saisies est trafiqué.
"""
from __future__ import annotations

import json

import pytest

from collectors.origine import ATELIER, INSTITUTIONNEL


@pytest.fixture
def atelier(tmp_path, monkeypatch, schema_sql):
    """Une base réelle et un fichier de saisies, tous deux jetables."""
    import sqlite3

    from collectors import db as db_mod

    chemin_db = tmp_path / "instance.db"
    conn = sqlite3.connect(chemin_db)
    conn.executescript(schema_sql)
    conn.commit()
    conn.close()
    monkeypatch.setattr(db_mod, "DB_PATH", chemin_db)

    fichier = tmp_path / "saisies.json"

    from collectors import saisies as mod
    monkeypatch.setattr(mod, "SAISIES", fichier)

    def ecrire(*lignes):
        fichier.write_text(json.dumps({"version": 1, "saisies": list(lignes)},
                                      ensure_ascii=False), encoding="utf-8")

    def lire(sql, params=()):
        c = sqlite3.connect(chemin_db)
        c.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in c.execute(sql, params)]
        finally:
            c.close()

    return {"ecrire": ecrire, "lire": lire, "db": chemin_db, "fichier": fichier}


def saisie_flux(**surcharge):
    base = {
        "id": "a1b2c3d4",
        "objet": "flux",
        "valeurs": {
            "type": "subvention", "year": 2026, "amount": 1200.0,
            "sens": "verse", "tiers": {"nom": "Foyer rural", "type": "association"},
            "description": "Subvention votée au conseil du 27 avril",
        },
        "source": {"raw_document_id": None, "sans_document_motif": "test",
                   "citation": "« une subvention de 1 200 € »"},
        "confidence": "confirmed",
        "saisi_par": "julien@exemple.fr",
        "saisi_le": "2026-08-20T22:00:00+00:00",
    }
    base.update(surcharge)
    return base


class TestEcriture:
    def test_un_flux_saisi_arrive_en_base(self, atelier):
        from collectors.saisies import import_saisies

        atelier["ecrire"](saisie_flux())
        resultat = import_saisies()

        assert resultat["ecrites"] == 1
        lignes = atelier["lire"]("SELECT * FROM financial_flows")
        assert len(lignes) == 1
        ligne = lignes[0]
        assert ligne["amount"] == 1200.0
        assert ligne["origine"] == ATELIER
        assert ligne["source"] == "atelier:a1b2c3d4"
        assert ligne["saisi_par"] == "julien@exemple.fr"

    def test_le_sens_decide_du_payeur(self, atelier):
        """« Versé » et « reçu » ne sont pas un détail d'affichage : ils
        décident de quel côté du budget la somme apparaît."""
        from collectors.saisies import import_saisies

        atelier["ecrire"](saisie_flux(),
                          saisie_flux(id="e5f6", valeurs={
                              **saisie_flux()["valeurs"], "sens": "recu",
                              "type": "dotation"}))
        import_saisies()

        recue, versee = atelier["lire"](
            "SELECT from_id, to_id, type FROM financial_flows ORDER BY type")
        assert recue["type"] == "dotation"           # encaissée par la commune
        assert versee["type"] == "subvention"        # payée par la commune
        assert recue["from_id"] == versee["to_id"]   # le tiers, des deux côtés
        assert recue["to_id"] == versee["from_id"]   # la commune, des deux côtés

    def test_le_rejeu_ne_double_pas(self, atelier):
        """Le piège déjà payé deux fois : `financial_flows` n'a aucune contrainte
        UNIQUE, donc un INSERT OR IGNORE n'y ignore rien."""
        from collectors.saisies import import_saisies

        atelier["ecrire"](saisie_flux())
        import_saisies()
        second = import_saisies()

        assert second["ecrites"] == 0
        assert second["ignorees"] == 1
        assert len(atelier["lire"]("SELECT id FROM financial_flows")) == 1

    def test_une_ligne_de_budget_vote(self, atelier):
        from collectors.saisies import import_saisies

        atelier["ecrire"]({
            "id": "bv01", "objet": "budget_vote",
            "valeurs": {"year": 2026, "agregat": "Recettes de fonctionnement",
                        "value": 2459773.03, "scope": "principal"},
            "source": {"sans_document_motif": "test"},
            "confidence": "confirmed", "saisi_par": "julien@exemple.fr",
            "saisi_le": "2026-08-20T22:00:00+00:00",
        })
        import_saisies()

        ligne, = atelier["lire"]("SELECT * FROM budget_vote")
        assert ligne["value"] == pytest.approx(2459773.03)
        assert ligne["origine"] == ATELIER


class TestRetrait:
    def test_retirer_efface_la_ligne_saisie(self, atelier):
        from collectors.saisies import import_saisies

        atelier["ecrire"](saisie_flux())
        import_saisies()
        atelier["ecrire"](saisie_flux(retire=True))
        resultat = import_saisies()

        assert resultat["retirees"] == 1
        assert atelier["lire"]("SELECT id FROM financial_flows") == []

    def test_le_retrait_natteint_aucune_ligne_de_collecteur(self, atelier):
        """LE test de cloisonnement. Même avec un fichier de saisies fabriqué
        pour désigner une ligne institutionnelle, le retrait ne peut pas
        l'atteindre : il ne filtre que sur `source = atelier:<id>`."""
        import sqlite3

        conn = sqlite3.connect(atelier["db"])
        conn.execute(
            "INSERT INTO financial_flows(type, year, amount, source, origine) "
            "VALUES('dotation', 2024, 90000, 'OFGL', ?)", (INSTITUTIONNEL,))
        conn.commit()
        conn.close()

        from collectors.saisies import import_saisies

        # Une saisie dont l'identifiant est choisi pour tenter d'attraper autre
        # chose que ses propres lignes.
        atelier["ecrire"]({"id": "' OR 1=1 --", "objet": "flux", "retire": True,
                           "valeurs": {}, "source": {}})
        import_saisies()

        restantes = atelier["lire"]("SELECT source, origine FROM financial_flows")
        assert len(restantes) == 1
        assert restantes[0]["source"] == "OFGL"
        assert restantes[0]["origine"] == INSTITUTIONNEL


class TestContratDesChamps:
    def test_chaque_objet_declare_sa_table(self):
        from collectors.saisies import CHAMPS_SAISIE
        for objet, contrat in CHAMPS_SAISIE.items():
            assert contrat.get("_table"), objet
            assert contrat.get("_libelle"), objet

    def test_tout_objet_saisissable_a_un_inserteur(self):
        """Un objet annoncé au formulaire sans code pour l'écrire produirait une
        saisie acceptée, enregistrée dans le fichier, et jamais visible nulle
        part — la pire des pannes, celle qui ne dit rien."""
        from collectors.saisies import CHAMPS_SAISIE, _INSERTEURS
        assert set(CHAMPS_SAISIE) == set(_INSERTEURS)

    def test_verified_nest_pas_offert_a_la_saisie(self):
        """Un humain qui lit un procès-verbal *confirme* ; il ne certifie pas.
        `verified` reste la marque d'une source institutionnelle."""
        from collectors.saisies import CONFIANCES
        assert "verified" not in CONFIANCES
