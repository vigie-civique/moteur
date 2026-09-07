"""Le redécoupage d'une portée ne relit pas les procès-verbaux de l'autre.

`redecouper_pv.deja_en_cache` complète le catalogue du SITE par les séances que
la base connaît et dont le PDF dort encore dans `data/pv/` — sans quoi les
documents retirés du site gardent à jamais leur découpage d'origine.

🔴 Elle recevait la portée, la documentait, et ne s'en servait pas : sa requête
interrogeait les DEUX types d'actes. Appelée pour la commune — le seul cas —
elle rendait donc aussi les procès-verbaux de l'INTERCOMMUNALITÉ présents en
cache, et `conseils.traiter` les enregistrait en portée communale. Chaque
redécoupage fabriquait ainsi un jumeau de chaque acte communautaire : même
titre, même date, même URL, mais le type `deliberation` au lieu de
`deliberation_cc` et sans le champ `instance` qui nomme la collectivité.

Relevé sur l'instance de référence le 07/09/2026 : **833 actes en double**,
créés le 29/08 à 18 h 31 — et publiés. `stats.json` annonçait
`deliberations_public = 2425` pour 1 593 délibérations réelles, et `events.json`
servait 832 paires (date, titre) identiques sous les deux types. Un lecteur du
site voyait donc chaque décision de l'intercommunalité deux fois.

⚠️ Le défaut s'entretenait lui-même : les jumeaux portant le type `deliberation`,
le redécoupage suivant les reprenait comme des séances communales. Corriger le
filtre ne suffit donc pas à réparer une base déjà touchée — il faut retirer les
doublons, ce qui est un geste de publication et non de code.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture
def base_avec_les_deux_portees(base: sqlite3.Connection) -> sqlite3.Connection:
    """Une séance communale et une séance communautaire, chacune avec son acte."""
    for type_, url, titre in (
            ("deliberation", "https://www.exemple-commune.fr/pv/cm-2026-01.pdf",
             "Subvention à l'association des parents d'élèves"),
            ("deliberation_cc", "https://www.exemple-epci.fr/pv/cc-2026-01.pdf",
             "Convention avec le SICTOM pour la collecte des déchets")):
        base.execute(
            "INSERT INTO events (type, date, title, content, source, source_url,"
            " metadata) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (type_, "2026-01-31", titre, "corps", "exemple", url, "{}"))
    base.commit()
    return base


def test_la_portee_commune_ignore_les_pv_de_lintercommunalite(
        base_avec_les_deux_portees, monkeypatch, tmp_path):
    """Le filtre porte sur le type de la portée demandée, jamais sur les deux."""
    import redecouper_pv

    # Tous les PDF sont réputés en cache : sans cela, le filtre du cache
    # masquerait celui de la portée et l'essai serait vert des deux côtés.
    faux_cache = tmp_path / "pv.pdf"
    faux_cache.write_bytes(b"%PDF-1.4 ")
    monkeypatch.setattr("collectors.conseils._cible_cache", lambda url: faux_cache)

    from contextlib import contextmanager

    @contextmanager
    def _transaction():
        yield base_avec_les_deux_portees
    monkeypatch.setattr(redecouper_pv, "transaction", _transaction)

    urls_commune = {d.url for d in redecouper_pv.deja_en_cache("commune", set())}
    assert urls_commune == {"https://www.exemple-commune.fr/pv/cm-2026-01.pdf"}, (
        "le redécoupage communal reprend un procès-verbal de l'intercommunalité : "
        "il en fera des actes communaux, jumeaux de ceux qui existent déjà")

    urls_epci = {d.url for d in redecouper_pv.deja_en_cache("epci", set())}
    assert urls_epci == {"https://www.exemple-epci.fr/pv/cc-2026-01.pdf"}
