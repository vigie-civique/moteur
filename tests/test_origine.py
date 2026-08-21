"""L'origine d'un fait, et ce qu'elle autorise.

Ces tests figent la règle posée le 20/08/2026 : une donnée structurée par une
administration ne se réécrit pas à la main ; ce qui vient d'une lecture — PDF,
page web, OCR — le peut. La règle est facile à énoncer et facile à contourner
par distraction : elle n'a de valeur que vérifiée mécaniquement.
"""
from __future__ import annotations

import pytest

from collectors.origine import (ATELIER, INSTITUTIONNEL, VERBATIM,
                                modifiable, origine_de)


class TestClassement:
    @pytest.mark.parametrize("source", [
        "bodacc", "BOAMP", "sitadel", "georisques", "banatic", "interieur",
        "OFGL", "DECP v3 data.economie.gouv.fr", "DECP data.gouv.fr",
        "sirene", "insee-melodi", "dgfip",
    ])
    def test_sources_institutionnelles(self, source):
        assert origine_de(source) == INSTITUTIONNEL

    @pytest.mark.parametrize("source", [
        "CR CM 2024", "CR 2023-09-13", "CM vote subventions 2025",
        "CM 28/05/2026 DEL2605_07", "prefecture-30", "urbanisme:tests:PLU",
        "web.archive.org", "conseil municipal",
    ])
    def test_sources_de_lecture(self, source):
        assert origine_de(source) == VERBATIM

    def test_saisie_reconnue(self):
        assert origine_de("atelier:9f3c1a2b") == ATELIER

    def test_source_inconnue_nest_pas_devinee(self):
        """Le point important. Classer au hasard, ce serait soit protéger une
        ligne que personne n'a vérifiée, soit ouvrir à la réécriture un chiffre
        publié par une administration — deux erreurs silencieuses."""
        assert origine_de("un truc jamais vu") is None
        assert origine_de("") is None
        assert origine_de(None) is None

    def test_le_site_de_la_commune_est_du_verbatim(self):
        """Le domaine vient de `config/instance.json`, jamais du code : c'est ce
        qui rend la règle transposable d'une commune à l'autre sans la toucher."""
        from collectors.config import COMMUNE_URL
        domaine = COMMUNE_URL.split("//")[-1].removeprefix("www.")
        assert domaine, "l'instance de test doit déclarer commune_url"
        assert origine_de(domaine) == VERBATIM

    def test_les_accents_et_la_casse_ne_changent_rien(self):
        assert origine_de("Préfecture-30") == origine_de("prefecture-30")


class TestDroitDeModifier:
    def test_verbatim_et_atelier_sont_modifiables(self):
        assert modifiable(VERBATIM)
        assert modifiable(ATELIER)

    def test_institutionnel_ne_lest_pas(self):
        assert not modifiable(INSTITUTIONNEL)

    def test_non_classe_traite_comme_institutionnel(self):
        """Devant l'inconnu, ne rien casser."""
        assert not modifiable(None)


class TestOrdreDesSteps:
    """L'ordre de `run_all` porte deux invariants, et rien ne les vérifiait.

    Ils tiennent par un commentaire depuis le 14/08/2026, date à laquelle leur
    oubli avait produit deux instances entièrement NULL dont le snapshot
    publiait l'intercommunalité au lieu de la commune. Ajouter un step juste
    avant `perimetre` — ce qui vient d'être fait deux fois — est précisément
    l'occasion de le casser sans s'en apercevoir.
    """

    def test_perimetre_est_le_dernier(self):
        from collectors.run_all import STEPS
        assert list(STEPS)[-1] == "perimetre", (
            "`perimetre` classe ce que tous les autres ont écrit. Un step "
            "placé après lui laisse ses entités avec perimetre=NULL, et le "
            "snapshot refuse alors de se construire.")

    def test_saisies_et_origine_precedent_perimetre(self):
        """`saisies` crée des entités, que `perimetre` doit classer ; `origine`
        classe les lignes que `saisies` vient d'écrire."""
        from collectors.run_all import STEPS
        ordre = list(STEPS)
        assert ordre.index("saisies") < ordre.index("origine") < ordre.index("perimetre")


class TestClassementEnBase:
    """Le script de classement, joué sur une base au schéma réel."""

    def _colonnes(self, base, table):
        return {r[1] for r in base.execute(f"PRAGMA table_info({table})")}

    def test_la_colonne_existe_sur_les_tables_de_faits(self, base):
        from collectors.origine import TABLES_ORIGINE
        for table in TABLES_ORIGINE:
            assert "origine" in self._colonnes(base, table), table

    def test_la_saisie_porte_son_auteur_et_sa_source(self, base):
        """Trois colonnes indissociables : sans `raw_document_id` la ligne n'est
        pas défendable, sans `saisi_par` elle n'est imputable à personne."""
        for table in ("events", "financial_flows", "marches_publics"):
            cols = self._colonnes(base, table)
            assert {"origine", "raw_document_id", "saisi_par", "saisi_le"} <= cols, table

    def test_le_schema_refuse_une_origine_inventee(self, base):
        import sqlite3
        with pytest.raises(sqlite3.IntegrityError):
            base.execute("INSERT INTO events(type, title, origine) "
                         "VALUES('deliberation', 'x', 'institutionel')")  # faute de frappe
