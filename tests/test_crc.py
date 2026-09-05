"""Rapports des chambres régionales des comptes : lecture et rapprochement.

Aucun appel réseau. Le balisage est celui servi par ccomptes.fr le 01/09/2026,
réduit à ce qui compte — et les intrus sont de VRAIS résultats, ceux que la
recherche a effectivement rendus quand on l'a interrogée.

Ce que ces essais protègent tient en une phrase : la recherche de ccomptes.fr
est un plein-texte FLOU, pas un filtre, et rapprocher sur la seule présence du
mot attribuerait à une commune le rapport d'une autre.
"""
from __future__ import annotations

from collectors.crc import correspond, departement_nom, extraire

# Le balisage réel d'un résultat, réduit. La date est prise dans l'ATTRIBUT
# `datetime` et non dans le texte « 01.10.2018 » : le premier est écrit pour une
# machine et déjà au format ISO, le second pour un lecteur français.
def _resultat(chemin: str, titre: str, date: str = "2018-10-01",
              chambre: str = "CRC AUVERGNE-RHÔNE-ALPES",
              description: str = "La chambre régionale des comptes a procédé au contrôle.",
              documents: int = 1) -> str:
    return f'''<li class="search-result"> <a href="{chemin}"> <h2 class="title">
      {titre} </h2> <div class="sr-content"> <p class="description"> {description}
      </p> </div> <div class="sr-info"> <p class="text">{documents} Document</p>
      </div> </a> <div class="result-date"> <p> <span class="title-hover"> {chambre}
      </span> </p> <p><time class="date-text" datetime="{date}"> 01.10.2018
      </time></p> </div> </li>'''


PAGE = "<ul class=\"search-list-results\">" + "".join([
    _resultat("/fr/publications/commune-de-saillans-drome", "Commune de Saillans (Drôme)"),
    _resultat("/fr/publications/cc-crestois-pays-saillans",
              "Communauté de communes du Crestois et du Pays de Saillans (Drôme)",
              date="2018-10-09"),
    # Les quatre suivants sont de VRAIS résultats rendus par la recherche : ce
    # sont eux qu'il s'agit d'écarter, pas des intrus imaginés pour l'occasion.
    _resultat("/fr/publications/cc-val-de-drome", "Communauté de communes Val-de-Drôme en Biovallée (Drôme)"),
    _resultat("/fr/publications/commune-de-lure", "Commune de Lure (Haute-Saône)"),
    _resultat("/fr/publications/cc-cevennes-garrigues", "Communauté de communes Cévennes Garrigues (Gard)"),
    _resultat("/fr/publications/cias-astarac", "CIAS Cœur d&#039;Astarac en Gascogne (Gers)"),
]) + "</ul>"


class TestLecture:
    def test_toutes_les_publications_sont_lues(self):
        """Une première version cherchait des conteneurs `card` : elle
        n'extrayait qu'UNE publication sur dix, et l'unique retenue était la
        bonne par chance. C'est l'épreuve sur la page réelle qui l'a montré."""
        assert len(extraire(PAGE)) == 6

    def test_un_resultat_porte_tout_ce_qu_il_faut(self):
        premier = extraire(PAGE)[0]
        assert premier["titre"] == "Commune de Saillans (Drôme)"
        assert premier["url"] == "https://www.ccomptes.fr/fr/publications/commune-de-saillans-drome"
        assert premier["date"] == "2018-10-01"
        assert premier["chambre"] == "CRC AUVERGNE-RHÔNE-ALPES"
        assert premier["documents"] == 1
        assert "chambre régionale" in premier["resume"]

    def test_les_entites_html_sont_decodees(self):
        """« Cœur d&#039;Astarac » se lit, sinon le rapprochement échoue sur une
        apostrophe et le titre publié serait illisible."""
        titres = [p["titre"] for p in extraire(PAGE)]
        assert "CIAS Cœur d'Astarac en Gascogne (Gers)" in titres

    def test_une_page_sans_resultat_ne_leve_pas(self):
        assert extraire("<ul class=\"search-list-results\"></ul>") == []
        assert extraire("") == []


class TestRapprochement:
    def test_la_commune_est_reconnue(self):
        assert correspond("Commune de Saillans (Drôme)", "Saillans", "Drôme", epci=False)

    def test_un_homonyme_d_un_autre_departement_est_ecarte(self):
        """Sans le département, trois communes homonymes se partageraient le
        même rapport. 3 675 communes sur 34 969 portent un nom partagé."""
        assert not correspond("Commune de Saillans (Gard)", "Saillans", "Drôme", epci=False)

    def test_une_autre_commune_du_meme_departement_est_ecartee(self):
        assert not correspond("Commune de Crest (Drôme)", "Saillans", "Drôme", epci=False)

    def test_les_vrais_intrus_de_la_recherche_sont_ecartes(self):
        """Interrogée sur « Lasalle », la recherche rend ceci — et rien de
        pertinent. C'est le cas ordinaire, pas l'exception."""
        for intrus in ("Commune de Lure (Haute-Saône)",
                       "Communauté de communes Cévennes Garrigues (Gard)",
                       "Région Picardie (Somme)"):
            assert not correspond(intrus, "Lasalle", "Gard", epci=False), intrus

    def test_un_titre_sans_departement_est_ecarte(self):
        """Le département entre parenthèses est une des deux conditions : sans
        lui, on ne rapproche pas — on devine."""
        assert not correspond("Commune de Saillans", "Saillans", "Drôme", epci=False)


class TestRapprochementEPCI:
    NOM_DECLARE = "CC du Crestois et de Pays de Saillans Coeur de Drôme"

    def test_le_nom_officiel_plus_court_est_reconnu(self):
        """Le sens de l'inclusion n'est pas indifférent. Une première version
        exigeait que TOUS les mots du nom déclaré soient dans le titre — et
        écartait le bon rapport, l'instance déclarant « … Coeur de Drôme » là où
        le site écrit seulement « … du Pays de Saillans »."""
        assert correspond(
            "Communauté de communes du Crestois et du Pays de Saillans (Drôme)",
            self.NOM_DECLARE, "Drôme", epci=True)

    def test_une_intercommunalite_voisine_est_ecartee(self):
        assert not correspond("Communauté de communes Val-de-Drôme en Biovallée (Drôme)",
                              self.NOM_DECLARE, "Drôme", epci=True)

    def test_un_mot_commun_ne_suffit_pas(self):
        """« Cévennes Garrigues » contre « Causses Aigoual Cévennes » : le mot
        « Cévennes » est partagé, « garrigues » ne l'est pas. Un seul mot commun
        laisserait passer une intercommunalité voisine au nom plus court."""
        assert not correspond("Communauté de communes Cévennes Garrigues (Gard)",
                              "CC Causses Aigoual Cévennes", "Gard", epci=True)
        assert not correspond("Communauté de communes Cévennes (Gard)",
                              "CC Causses Aigoual Cévennes", "Gard", epci=True)

    def test_une_variante_du_titre_est_ecartee_et_c_est_le_prix(self):
        """⚠️ Cet essai DOCUMENTE UNE OMISSION VOULUE, il ne la célèbre pas.

        « … (3CPS) à Aouste-sur-Sye » désigne bien le même EPCI — son sigle et
        son siège. Le rapprochement l'écarte, parce que relâcher la règle pour
        le rattraper rouvrirait la porte aux faux positifs, et attribuer un
        rapport à la mauvaise collectivité est la faute qu'un dispositif de
        transparence ne peut pas commettre.

        Le collecteur NOMME les titres écartés dans sa sortie : l'omission est
        visible, un humain peut la rattraper. C'est ce qui rend cette prudence
        tenable — une prudence silencieuse serait un défaut."""
        assert not correspond(
            "Communauté de communes du Crestois et du Pays de Saillans (3CPS) à Aouste-sur-Sye (Drôme)",
            self.NOM_DECLARE, "Drôme", epci=True)


class TestDepartement:
    def test_le_nom_se_tire_de_la_prefecture(self):
        """L'instance déclare le département en CODE ; le titre porte son NOM.
        Plutôt qu'une table des cent-un départements, on le tire de
        `prefecture_nom`, que l'instance déclare déjà et qu'un humain a relu."""
        assert departement_nom() == "Épreuve"

    def test_les_formes_courantes_sont_couvertes(self, monkeypatch):
        import collectors.crc as crc
        for prefecture, attendu in (("Préfecture du Gard", "Gard"),
                                    ("Préfecture de la Drôme", "Drôme"),
                                    ("Préfecture de l'Épreuve", "Épreuve"),
                                    ("Préfecture de l’Aude", "Aude"),
                                    ("Préfecture des Landes", "Landes"),
                                    ("Préfecture de Vaucluse", "Vaucluse")):
            monkeypatch.setattr(crc, "PREFECTURE_NOM", prefecture)
            assert crc.departement_nom() == attendu

    def test_le_nom_declare_prime_sur_la_prefecture(self, monkeypatch):
        """`departement_nom` est la voie normale ; la préfecture n'est qu'un
        rattrapage pour les instances relues à la main avant qu'il existe."""
        import collectors.crc as crc
        monkeypatch.setattr(crc, "DEPARTEMENT_NOM", "Gard")
        monkeypatch.setattr(crc, "PREFECTURE_NOM", "Sous-préfecture de Nulle Part")
        assert crc.departement_nom() == "Gard"

    def test_la_forme_ecrite_par_l_amorcage_ne_fait_plus_tomber_le_step(self, monkeypatch):
        """La panne du 05/09/2026, et elle ne se voyait pas ici.

        `init_instance.py` écrit « Préfecture (30) » — aucun article ne la
        rattrape. Toute instance amorcée automatiquement levait donc SystemExit,
        `run_all --step crc` sortait en 1, et le portail national comptait `crc`
        en échec sur CHAQUE dossier livré : trois d'affilée, son veilleur a
        conclu à une panne chez nous. Il avait raison. Les dossiers d'Uzès
        perdaient au passage quatre vrais rapports de la CRC.
        """
        import collectors.crc as crc
        monkeypatch.setattr(crc, "PREFECTURE_NOM", "Préfecture (30)")
        monkeypatch.setattr(crc, "DEPARTEMENT_NOM", "Gard")
        assert crc.departement_nom() == "Gard"

    def test_une_forme_illisible_refuse_au_lieu_de_deviner(self, monkeypatch):
        """Deviner un département relâcherait la seule condition qui empêche
        d'attribuer un rapport à la mauvaise collectivité."""
        import collectors.crc as crc
        monkeypatch.setattr(crc, "DEPARTEMENT_NOM", "")
        monkeypatch.setattr(crc, "PREFECTURE_NOM", "Sous-préfecture de Nulle Part")
        try:
            crc.departement_nom()
        except SystemExit as refus:
            assert "departement_nom" in str(refus)
        else:
            raise AssertionError("une préfecture illisible doit faire refuser, pas deviner")
