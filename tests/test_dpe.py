"""DPE : la garde qui empêche une adresse d'entrer en base.

Aucun appel réseau. Deux essais de lecture, et une garde de STRUCTURE.

La garde est le cœur du fichier. Un collecteur qui « ne devrait pas » ramener
de lignes n'en ramène pas tant que personne n'ajoute une ligne de code : la
règle doit donc porter sur le code, pas sur l'intention. Ici, toute requête vers
la route `lines` de l'ADEME — celle qui rend les diagnostics UN PAR UN, avec
l'adresse du logement, sa surface et son mode de chauffage — doit demander
`size=0`. Sans ce contrôle, un `size=1000` ajouté un jour pour « voir » ferait
entrer un fichier d'adresses dans une base publiée.
"""
from __future__ import annotations

import ast
import pathlib

from collectors.dpe import PASSOIRES, part_passoires

MODULE = pathlib.Path(__file__).resolve().parent.parent / "collectors" / "dpe.py"


class TestGardeAucuneLigne:
    def test_toute_requete_de_lignes_demande_zero_ligne(self):
        source = MODULE.read_text(encoding="utf-8")
        arbre = ast.parse(source)
        fautives = []
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.FunctionDef):
                continue
            bloc = ast.get_source_segment(source, noeud) or ""
            if "/lines" in bloc and '"size": 0' not in bloc:
                fautives.append(noeud.name)
        assert not fautives, (
            "ces fonctions interrogent la route `lines` sans borner la réponse à "
            f"zéro ligne : {', '.join(fautives)}. Une ligne de DPE porte l'adresse "
            "d'un logement.")

    def test_le_module_ne_lit_aucun_champ_d_adresse(self):
        """Les champs d'adresse de l'ADEME ne doivent apparaître nulle part.

        `adresse_ban`, `adresse_brut`, `_geopoint` : les nommer serait le
        premier geste d'une collecte nominative. Le filtre communal, lui, passe
        par `code_insee_ban`, qui est un code de commune et rien d'autre.
        """
        source = MODULE.read_text(encoding="utf-8")
        # Le préambule explique justement pourquoi ces champs sont écartés :
        # la garde porte sur le CODE, pas sur la prose qui l'entoure.
        code = source.split('"""', 2)[-1]
        for champ in ("adresse_ban", "adresse_brut", "_geopoint",
                      "numero_dpe", "surface_habitable"):
            assert champ not in code, f"le module manipule le champ « {champ} »"


class TestPassoires:
    def test_la_definition_legale_est_f_et_g(self):
        assert PASSOIRES == ("F", "G")

    def test_sans_releve_la_part_n_est_pas_zero(self, monkeypatch, tmp_path):
        """Une commune jamais collectée doit rendre None, pas 0 %.

        Zéro pour cent de passoires est une excellente nouvelle qu'on ne peut
        pas annoncer sur une absence de mesure.
        """
        import collectors.dpe as module

        class _ConnVide:
            def execute(self, *a, **k):
                return type("C", (), {"fetchall": staticmethod(lambda: [])})()

            def close(self):
                pass

        monkeypatch.setattr(module, "get_conn", lambda **k: _ConnVide())
        assert part_passoires("99001") is None
