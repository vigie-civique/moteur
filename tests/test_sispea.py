"""Le prix de l'eau : lecture des classeurs, rattachement, et écriture.

Aucun appel réseau. Les formes éprouvées ici sont celles que les sources rendent
réellement, relevées le 02/09/2026 : quatre conventions d'en-têtes pour un seul
champ, un vide écrit « . », des nombres tantôt nombres tantôt chaînes, et une
API qui rend deux fois la même ligne.

Ce que ces essais protègent : une série de prix ne vaut que si chaque valeur est
bien celle du service qu'on croit, à l'année qu'on croit.
"""
from __future__ import annotations

import pytest

from collectors.sispea import (INDICATEURS, _ecrire_indicateur, _ecrire_service,
                               _format_reel, _identite, _indice, ensure_tables,
                               nombre, plat)


class TestFormesDeLaSource:
    def test_les_quatre_conventions_den_tete_se_rejoignent(self):
        """Un seul champ, quatre graphies selon la génération de l'export.

        2015-2019 « Id SISPEA du service », 2020-2023 `id_sispea_serv`, 2024
        « Id SISPEA de l'entité de gestion ». Et l'assainissement écrit
        `N_iNSEE_si_commune`, avec une capitale au milieu d'un mot.
        """
        assert plat("N° INSEE si commune") == plat("N_INSEE_si_commune") == plat("n_insee_si_commune")
        assert plat("N_iNSEE_si_commune") == "n_insee_si_commune"
        assert plat("Id SISPEA de l'entité de gestion") == "id_sispea_de_l_entite_de_gestion"
        assert plat("Mode de gestion") == "mode_de_gestion"

    def test_le_vide_secrit_un_point(self):
        """« . » est le vide de ces classeurs. Le prendre pour un nombre
        remplirait la base de valeurs qui n'existent pas."""
        assert nombre(".") is None
        assert nombre("") is None
        assert nombre(None) is None

    def test_un_nombre_est_parfois_une_chaine(self):
        """2023 écrit '4.21', 2024 écrit 4.63, et un poste français peut écrire
        une virgule décimale."""
        assert nombre("4.21") == pytest.approx(4.21)
        assert nombre(4.63) == pytest.approx(4.63)
        assert nombre("2,18") == pytest.approx(2.18)
        assert nombre(4) == 4.0

    def test_le_format_se_lit_aux_octets_pas_au_nom(self, tmp_path):
        """🔴 L'extension MENT : une archive livre un `.xls` qui est un `.xlsx`.
        Le nom ne décide de rien."""
        menteur = tmp_path / "SISPEA_2021_AC.xls"
        menteur.write_bytes(b"PK\x03\x04" + b"\x00" * 32)
        assert _format_reel(menteur) == "xlsx"

        ancien = tmp_path / "SISPEA_2024_AEP.xls"
        ancien.write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 32)
        assert _format_reel(ancien) == "xls"

        etranger = tmp_path / "surprise.xls"
        etranger.write_bytes(b"%PDF" + b"\x00" * 32)
        with pytest.raises(RuntimeError, match="ni xlsx ni xls"):
            _format_reel(etranger)

    def test_une_colonne_absente_arrete_tout_en_nommant_ce_quon_a_vu(self):
        """Un index à demi rempli, écrit en silence, serait pire qu'un échec :
        personne ne saurait que la moitié des prix manque."""
        with pytest.raises(RuntimeError) as arret:
            _indice(["dpt", "nom_coll"], ("id_sispea_serv",), "service", "SISPEA_2019.xlsx")
        assert "service" in str(arret.value)
        assert "nom_coll" in str(arret.value), "le message doit montrer les en-têtes lus"


class TestRattachement:
    def test_une_ligne_de_services_nomme_un_service(self):
        code, identite = _identite({
            "code_service": 173349, "nom_service": "eau potable",
            "type_collectivite": "Syndicat Intercommunal à Vocation Unique",
            "mode_gestion": "Délégation", "numero_siren": "253000426",
            "codes_commune": ["30140", "30236"], "annee": 2018,
        }, "AEP")
        assert code == "173349"
        assert identite["mode_gestion"] == "Délégation"
        assert identite["communes"] == "30140,30236"

    def test_le_jumeau_anonyme_designe_le_meme_service(self):
        """`/communes` rend chaque ligne DEUX fois : une fois nommée, une fois
        avec `nom_commune` à null. Les deux désignent le même service."""
        nommee = _identite({"codes_service": [71694], "noms_service": ["assainissement collectif"],
                            "nom_commune": "Saillans", "annee": 2019}, "AC")
        anonyme = _identite({"codes_service": [71694], "noms_service": ["assainissement collectif"],
                             "nom_commune": None, "annee": 2019}, "AC")
        assert nommee[0] == anonyme[0] == "71694"

    def test_une_ligne_qui_couvre_plusieurs_services_nest_pas_attribuee(self):
        """Ses indicateurs sont ceux d'un agrégat : on ne saurait pas à qui les
        attribuer, et les donner au premier venu serait une valeur fausse sous
        un nom juste."""
        assert _identite({"codes_service": [71694, 88888], "annee": 2019}, "AC") is None
        assert _identite({"codes_service": [], "annee": 2019}, "AC") is None


class TestEcriture:
    def test_zero_nest_pas_un_prix_mais_reste_un_taux(self, base):
        """Des services déclarent 0 €/m³ : une case laissée vide, pas une eau
        gratuite. Le zéro reste légitime ailleurs — un service peut n'avoir
        renouvelé aucune canalisation dans l'année."""
        ensure_tables(base)
        _ecrire_service(base, "1", "AEP", {"nom": "Régie d'essai"})
        assert _ecrire_indicateur(base, "1", 2024, "AEP", "P107.2", 0.0, "ofb")
        prix_ecrit = base.execute(
            "SELECT COUNT(*) FROM sispea_indicateurs WHERE code='D102.0'").fetchone()[0]
        assert prix_ecrit == 0, "aucun prix n'a été écrit, et c'est bien le sujet"
        assert base.execute(
            "SELECT valeur FROM sispea_indicateurs WHERE code='P107.2'").fetchone()[0] == 0.0

    def test_le_fichier_du_producteur_fait_foi_sur_l_api_qui_le_republie(self, base):
        """Les deux sources se recouvrent sur 2015-2019. À valeur discordante,
        c'est l'extraction de l'OFB qui l'emporte, quel que soit l'ordre de
        passage — sans quoi le résultat dépendrait de qui a couru le premier."""
        ensure_tables(base)
        _ecrire_service(base, "1", "AEP", {"nom": "Régie d'essai"})

        _ecrire_indicateur(base, "1", 2019, "AEP", "D102.0", 2.04, "hubeau")
        _ecrire_indicateur(base, "1", 2019, "AEP", "D102.0", 2.11, "ofb")
        ligne = base.execute(
            "SELECT valeur, origine FROM sispea_indicateurs WHERE annee=2019").fetchone()
        assert (ligne["valeur"], ligne["origine"]) == (2.11, "ofb")

        # Et dans l'autre sens : Hub'Eau ne doit pas reprendre la main.
        _ecrire_indicateur(base, "1", 2019, "AEP", "D102.0", 2.04, "hubeau")
        ligne = base.execute(
            "SELECT valeur, origine FROM sispea_indicateurs WHERE annee=2019").fetchone()
        assert (ligne["valeur"], ligne["origine"]) == (2.11, "ofb")

    def test_une_source_complete_l_autre_sans_l_effacer(self, base):
        """Hub'Eau donne le SIREN et les communes desservies, l'OFB un nom de
        collectivité plus complet. Un `INSERT OR REPLACE` aurait fait perdre à
        chaque passage ce que l'autre source venait d'apporter."""
        ensure_tables(base)
        _ecrire_service(base, "173349", "AEP", {
            "nom": None, "siren": "253000426", "communes": "30140,30236",
            "type_collectivite": "Syndicat Intercommunal à Vocation Unique"})
        _ecrire_service(base, "173349", "AEP", {
            "nom": "SYNDICAT AEP DE LA REGION", "mode_gestion": "Délégation"})

        ligne = base.execute("SELECT * FROM sispea_services").fetchone()
        assert ligne["nom"] == "SYNDICAT AEP DE LA REGION"
        assert ligne["mode_gestion"] == "Délégation"
        assert ligne["siren"] == "253000426", "le SIREN de Hub'Eau a été effacé"
        assert ligne["communes"] == "30140,30236"

    def test_chaque_mesure_porte_son_libelle_et_son_unite(self, base):
        """Une valeur nue ne se lit pas : 72,5 est un pourcentage, 2,04 des
        euros par mètre cube. Les deux viennent de la même table, écrite une
        fois pour toutes."""
        ensure_tables(base)
        _ecrire_service(base, "1", "AEP", {})
        _ecrire_indicateur(base, "1", 2024, "AEP", "D102.0", 2.18, "ofb")
        ligne = base.execute("SELECT libelle, unite FROM sispea_indicateurs").fetchone()
        assert ligne["unite"] == "€/m³"
        assert "120 m³" in ligne["libelle"]


class TestDeclaration:
    def test_les_deux_competences_declarent_leur_prix(self):
        """L'eau potable et l'assainissement se paient sur la même facture :
        n'en collecter qu'une la ferait lire pour le tout."""
        assert "D102.0" in INDICATEURS["AEP"]
        assert "D204.0" in INDICATEURS["AC"]

    def test_le_step_est_declare_dans_la_configuration(self):
        """Un collecteur qui n'est cité par personne ne tourne jamais — le
        défaut qui avait laissé une base sans budget alors que le site en
        publiait les pages. Ces deux tables-là se lisent sans les collecteurs."""
        from collectors.config import PROFONDEUR_STEP, STEP_META
        assert "sispea" in STEP_META
        assert PROFONDEUR_STEP["sispea"] == "fond"

    def test_le_step_est_appelable(self):
        """`run_all` importe les quarante collecteurs, donc la lecture des PDF.
        Le job de tests léger ne les installe pas — la suite ne doit dépendre ni
        des collecteurs ni de l'API —, `tests-deps` les joue. Sans ce garde-fou,
        ce test a fait rougir la CI sur `pdfplumber`, exactement comme le test
        de cohérence des steps le 26/08."""
        pytest.importorskip("pdfplumber", reason="job « tests-deps »")
        from collectors.run_all import STEPS
        assert "sispea" in STEPS


class TestDegradation:
    def test_l_absence_des_millesimes_ne_perd_pas_la_serie(self, base, monkeypatch, capsys):
        """Les exercices récents demandent un téléchargement national, `bsdtar`
        et parfois `xlrd`. Rien de tout cela n'est acquis sur la machine qui
        collecte — et leur absence ne doit pas emporter ce que Hub'Eau vient de
        rendre. Une branche jamais empruntée est une branche fausse : celle-ci
        l'est ici, pour de bon.
        """
        from collectors import sispea

        ensure_tables(base)
        _ecrire_service(base, "1", "AEP", {"nom": "Régie d'essai"})
        _ecrire_indicateur(base, "1", 2019, "AEP", "D102.0", 2.04, "hubeau")

        def _absent(_competence):
            raise RuntimeError("bsdtar est introuvable")
        monkeypatch.setattr(sispea, "_archives", _absent)

        releve = {"services": 1, "mesures": 1, "millesimes": 0, "annees": set()}
        motif = sispea.completer_par_millesimes(base, {"1": "AEP"}, releve)

        assert motif and "bsdtar" in motif
        assert releve["millesimes_erreur"]
        # La série de Hub'Eau est intacte : c'est tout l'objet.
        assert base.execute("SELECT COUNT(*) FROM sispea_indicateurs").fetchone()[0] == 1
        # Et la dégradation se DIT : une souplesse muette est un défaut.
        assert "exercices récents indisponibles" in capsys.readouterr().out


class TestGraphies:
    def test_les_accents_survivent_au_passage_de_l_ofb(self, base):
        """🔴 Hub'Eau écrit « Régie », les extractions de l'OFB « Regie ». La
        source qui passe en dernier l'emportant, la base se remplissait de mots
        français sans leurs accents, et deux services d'une même commune
        s'affichaient sous deux graphies du même mot."""
        ensure_tables(base)
        _ecrire_service(base, "1", "AEP", {"mode_gestion": "Régie"})
        _ecrire_service(base, "1", "AEP", {"mode_gestion": "Regie"})
        assert base.execute("SELECT mode_gestion FROM sispea_services").fetchone()[0] == "Régie"

        # Et dans l'ordre inverse : la graphie accentuée gagne quand elle arrive.
        _ecrire_service(base, "2", "AEP", {"mode_gestion": "Delegation"})
        _ecrire_service(base, "2", "AEP", {"mode_gestion": "Délégation"})
        assert base.execute(
            "SELECT mode_gestion FROM sispea_services WHERE code_service='2'").fetchone()[0] == "Délégation"

    def test_une_valeur_qui_change_vraiment_l_emporte(self, base):
        """La règle ne fige rien : elle départage deux GRAPHIES. Un service qui
        passe de la régie à la délégation doit se voir — c'est même l'un des
        faits les plus intéressants qu'on puisse lire ici."""
        ensure_tables(base)
        _ecrire_service(base, "1", "AEP", {"mode_gestion": "Régie"})
        _ecrire_service(base, "1", "AEP", {"mode_gestion": "Délégation"})
        assert base.execute("SELECT mode_gestion FROM sispea_services").fetchone()[0] == "Délégation"

    def test_le_nom_du_service_et_celui_de_la_collectivite_ne_se_melangent_pas(self, base):
        """Hub'Eau nomme le SERVICE (« eau potable »), l'OFB la COLLECTIVITÉ.
        Rangés dans la même colonne, l'un chassait l'autre selon la source
        arrivée en dernier : deux services voisins s'affichaient, l'un sous le
        nom de sa commune, l'autre sous le mot « eau potable »."""
        ensure_tables(base)
        _ecrire_service(base, "1", "AEP", {"libelle": "eau potable"})
        _ecrire_service(base, "1", "AEP", {"nom": "SYNDICAT AEP DE LA REGION"})
        ligne = base.execute("SELECT nom, libelle FROM sispea_services").fetchone()
        assert ligne["libelle"] == "eau potable"
        assert ligne["nom"] == "SYNDICAT AEP DE LA REGION"
