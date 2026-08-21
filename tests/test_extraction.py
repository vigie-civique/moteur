"""L'extraction assistée : découpage, lecture des réponses, contrôle des citations.

Le modèle est SIMULÉ ici, et c'est le seul endroit du projet où quelque chose
l'est. La raison n'est pas la commodité : un test qui appelle un modèle de
langage mesure le modèle, pas le code — il changerait de résultat sans qu'une
ligne bouge, et ne tournerait pas en CI. Ce qui est éprouvé ici, c'est ce dont
nous répondons : le découpage du texte, la lecture d'une réponse mal formée, et
le contrôle qui attrape une invention.

Le modèle réel, lui, est mesuré par `scripts/banc_essai_ia.py`, sur de vrais
procès-verbaux, à la main et quand on en a besoin.
"""
from __future__ import annotations

import json

from collectors import extraction


class TestDecoupage:
    def test_un_texte_court_reste_entier(self):
        assert extraction.tranches("court") == ["court"]

    def test_un_texte_long_est_decoupe_avec_recouvrement(self):
        texte = "\n".join(f"ligne {i} du procès-verbal" for i in range(4000))
        morceaux = extraction.tranches(texte)
        assert len(morceaux) > 1
        # Le recouvrement n'est pas un détail : une délibération à cheval sur
        # deux tranches serait sinon coupée en deux délibérations imaginaires.
        assert morceaux[0][-200:] in texte
        assert sum(len(m) for m in morceaux) > len(texte)

    def test_la_coupe_tombe_sur_une_fin_de_ligne(self):
        texte = "\n".join(f"délibération numéro {i}" for i in range(3000))
        for morceau in extraction.tranches(texte)[:-1]:
            assert not morceau.endswith(" ")


class TestLectureDeLaReponse:
    def test_json_nu(self):
        assert extraction.json_du_modele('{"flux": []}') == {"flux": []}

    def test_json_entoure_de_balises(self):
        """Un fournisseur qui ignore `response_format` encadre son JSON. Refuser
        ces réponses reviendrait à n'accepter que certains modèles — ce que le
        dispositif s'interdit."""
        assert extraction.json_du_modele('```json\n{"flux": [1]}\n```') == {"flux": [1]}

    def test_json_precede_de_bavardage(self):
        brut = 'Voici les flux que j\'ai trouvés :\n{"flux": [{"amount": 12}]}\nVoilà.'
        assert extraction.json_du_modele(brut)["flux"][0]["amount"] == 12

    def test_reponse_illisible_ne_leve_pas(self):
        """Un modèle qui répond à côté est un cas courant, pas une panne."""
        assert extraction.json_du_modele("je ne sais pas") == {}
        assert extraction.json_du_modele("") == {}
        assert extraction.json_du_modele('{"flux": [') == {}


TEXTE = """
CONSEIL MUNICIPAL DU 27 AVRIL 2026

DÉLIBÉRATION N° 3 — SUBVENTIONS AUX ASSOCIATIONS
Le conseil municipal, après en avoir délibéré, ATTRIBUE une subvention de
1 200 € au Foyer rural pour l'année 2026.
"""


class TestControleDesCitations:
    def test_une_phrase_du_texte_est_retrouvee(self):
        assert extraction.citation_presente(
            "ATTRIBUE une subvention de 1 200 € au Foyer rural", TEXTE)

    def test_les_cesures_du_pdf_ne_font_pas_echouer(self):
        """L'extraction d'un PDF coupe les phrases n'importe où. Un modèle qui
        recopie proprement ne doit pas être accusé d'invention pour autant."""
        assert extraction.citation_presente(
            "ATTRIBUE   une subvention\nde 1 200 €\tau Foyer rural".replace("\tau", " au"),
            TEXTE)

    def test_une_citation_desaccentuee_reste_valable(self):
        """Un modèle qui écrit « subvention » sans accents n'invente rien. Le
        contrôle réduit les accents des deux côtés ; les supprimer purement
        aurait fait de « aménagement » un « am nagement » introuvable."""
        assert extraction.citation_presente(
            "apres en avoir delibere, ATTRIBUE une subvention", TEXTE)

    def test_une_citation_reformulee_est_refusee(self):
        """Mesuré au banc du 21/08/2026 : le texte disait « DU produit de la
        taxe », le modèle a cité « LE produit de la taxe ». Le chiffre était
        bon, la citation retouchée — et c'est bien ce qu'il faut signaler, sans
        quoi la citation ne prouve plus rien."""
        assert not extraction.citation_presente(
            "ATTRIBUE la subvention de 1 200 € au Foyer rural", TEXTE)

    def test_une_phrase_inventee_est_detectee(self):
        assert not extraction.citation_presente(
            "ATTRIBUE une subvention de 15 000 € au Comité des fêtes", TEXTE)

    def test_une_citation_trop_courte_ne_prouve_rien(self):
        """« 1 200 € » se retrouve dans n'importe quel procès-verbal."""
        assert not extraction.citation_presente("1 200 €", TEXTE)
        assert not extraction.citation_presente("", TEXTE)


class TestExtraction:
    def _modele(self, reponse):
        """Un modèle qui répond toujours la même chose."""
        def appel(message, system="", max_tokens=0, json_strict=False):
            assert "PROCÈS-VERBAL" in message      # le gabarit est bien envoyé
            assert "citation" in system            # la consigne aussi
            return reponse
        return appel

    def test_une_proposition_fondee_est_marquee_verifiee(self):
        reponse = json.dumps({"flux": [{
            "type": "subvention", "year": 2026, "amount": 1200.0,
            "citation": "ATTRIBUE une subvention de 1 200 € au Foyer rural"}]})
        r = extraction.extraire(TEXTE, "flux", self._modele(reponse))
        assert r["citations_verifiees"] == 1
        assert r["propositions"][0]["citation_verifiee"] is True

    def test_une_invention_est_signalee_mais_pas_supprimee(self):
        """Supprimer masquerait le comportement du modèle. Or c'est justement
        ce comportement qu'on veut voir : une ligne barrée en rouge apprend
        quelque chose, une ligne absente n'apprend rien."""
        reponse = json.dumps({"flux": [{
            "amount": 99999.0,
            "citation": "ATTRIBUE une subvention de 99 999 € au Comité des fêtes"}]})
        r = extraction.extraire(TEXTE, "flux", self._modele(reponse))
        assert len(r["propositions"]) == 1
        assert r["citations_introuvables"] == 1
        assert r["propositions"][0]["citation_verifiee"] is False

    def test_une_reponse_illisible_est_comptee(self):
        r = extraction.extraire(TEXTE, "flux", self._modele("désolé, je ne peux pas"))
        assert r["propositions"] == []
        assert r["reponses_illisibles"] == 1
        assert r["motifs_echec"]        # jamais un échec sans motif

    def test_un_modele_a_raisonnement_muet_est_diagnostique(self):
        """Le piège du 21/08/2026 : gemma4:26b rend `content` VIDE avec un HTTP
        200 quand tout son budget de tokens est parti dans `reasoning`. Sans ce
        diagnostic, on lit « 0 proposition » et on croit le procès-verbal vide
        de flux financiers."""
        def appel(message, system="", max_tokens=0, json_strict=False):
            return extraction.contenu_openai({"choices": [{
                "message": {"role": "assistant", "content": "",
                            "reasoning": "Je réfléchis longuement…"},
                "finish_reason": "stop"}]})

        r = extraction.extraire(TEXTE, "flux", appel)
        assert r["reponses_illisibles"] == 1
        assert "raisonnement" in r["motifs_echec"][0]

    def test_une_reponse_normale_est_lue(self):
        assert extraction.contenu_openai(
            {"choices": [{"message": {"content": '{"flux": []}'}}]}) == '{"flux": []}'

    def test_une_reponse_coupee_est_diagnostiquee(self):
        import pytest
        with pytest.raises(extraction.ReponseSansContenu, match="tokens"):
            extraction.contenu_openai({"choices": [{
                "message": {"content": ""}, "finish_reason": "length"}]})

    def test_objet_inconnu_refuse(self):
        import pytest
        with pytest.raises(ValueError):
            extraction.extraire(TEXTE, "chaussettes", self._modele("{}"))

    def test_chaque_gabarit_demande_une_citation(self):
        """Sans citation, aucune proposition n'est vérifiable — et le contrôle
        automatique tombe."""
        for objet, (forme, _) in extraction.GABARITS.items():
            assert "citation" in forme, objet
