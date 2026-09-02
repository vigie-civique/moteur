"""Justice administrative : le nom d'une commune n'est pas la commune.

Aucun appel réseau. Le texte reproduit est celui d'une VRAIE décision — CAA de
Toulouse, 28/08/2026, `CETATEXT000054762059` — dont la commune requérante est
Jonquières-Saint-Vincent.

Ce que cet essai protège : le rapprochement se fait dans du texte libre, où
« Saillans » et « Lasalle » sont aussi des patronymes, et où le nom d'une
commune est souvent le début du nom d'une autre. Le premier rapprochement écrit
retenait « commune de Jonquières » dans une décision qui parle de
Jonquières-Saint-Vincent : c'est exactement la faute à ne pas commettre.
"""
from __future__ import annotations

from collectors.justice import _lire, cite, normaliser

DECISION = normaliser(
    "CAA de TOULOUSE, 2ème chambre, 28/08/2026, 24TL01234 "
    "Vu la procédure suivante : la commune de Jonquières-Saint-Vincent, "
    "représentée par Me Allegre, a demandé au tribunal administratif de Nîmes "
    "d'annuler l'arrêté du maire de Beaucaire. La commune de "
    "Jonquières-Saint-Vincent (Gard) soutient que… Fait à Toulouse le 28 août.")


class TestRapprochement:
    def test_la_commune_requerante_est_reconnue(self):
        assert cite(DECISION, "Jonquières-Saint-Vincent")

    def test_un_nom_tronque_est_refuse(self):
        """« Jonquières » n'est pas « Jonquières-Saint-Vincent »."""
        assert not cite(DECISION, "Jonquières")
        assert not cite(DECISION, "Saint-Vincent")

    def test_une_autre_commune_du_texte_est_reconnue_pour_elle_meme(self):
        assert cite(DECISION, "Beaucaire")

    def test_une_commune_absente_ne_l_est_pas(self):
        assert not cite(DECISION, "Testonville")

    def test_le_nom_seul_ne_suffit_pas(self):
        """Sans « commune de » devant, un nom peut être un patronyme."""
        texte = normaliser("M. Saillans a demandé au tribunal administratif…")
        assert not cite(texte, "Saillans")

    def test_l_intercommunalite_est_reconnue_par_sa_formule(self):
        texte = normaliser("la communauté de communes du Crestois a formé un recours")
        assert cite(texte, "du Crestois")


class TestLecture:
    def test_les_metadonnees_sont_lues(self):
        import xml.etree.ElementTree as ET
        xml = """<TEXTE_JURI_ADMIN><META><META_COMMUN><ID>CETATEXT000054762059</ID>
          </META_COMMUN><META_SPEC><META_JURI>
          <TITRE>CAA de TOULOUSE, 28/08/2026, 24TL01234</TITRE>
          <DATE_DEC>2026-08-28</DATE_DEC><JURIDICTION>CAA de TOULOUSE</JURIDICTION>
          <NUMERO>24TL01234</NUMERO></META_JURI>
          <META_JURI_ADMIN><TYPE_REC>Excès de pouvoir</TYPE_REC></META_JURI_ADMIN>
          </META_SPEC></META><TEXTE><BLOC_TEXTUEL><CONTENU>La commune de X<br/>
          a demandé</CONTENU></BLOC_TEXTUEL></TEXTE></TEXTE_JURI_ADMIN>"""
        d = _lire(ET.fromstring(xml))
        assert d["id"] == "CETATEXT000054762059"
        assert d["date"] == "2026-08-28"
        assert d["juridiction"] == "CAA de TOULOUSE"
        assert d["type_recours"] == "Excès de pouvoir"
        # Le contenu porte des <br/> : le texte doit être recollé, sinon le
        # rapprochement échoue sur une coupure de ligne.
        assert "commune de X" in d["contenu"]
