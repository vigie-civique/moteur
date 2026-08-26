"""DECP et DVF partagent leurs gros téléchargements entre instances."""
from __future__ import annotations

import gzip
from datetime import date


def test_decp_reutilise_le_fichier_du_magasin(tmp_path, monkeypatch):
    from collectors import marches_publics as marches

    monkeypatch.setattr(marches, "DECP_CACHE", tmp_path / "decp")
    appels = []

    class Reponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            appels.append(1)
            return b'{"marches":[]}'

    monkeypatch.setattr(marches.urllib.request, "urlopen", lambda *a, **k: Reponse())
    assert marches._telecharger_decp("https://example.test/decp", "decp-2025.json")
    assert marches._telecharger_decp("https://example.test/decp", "decp-2025.json")
    assert len(appels) == 1


def test_dvf_cerema_reutilise_la_reponse_du_magasin(tmp_path, monkeypatch):
    from collectors import dvf

    monkeypatch.setattr(dvf, "DVF_CACHE", tmp_path / "dvf")
    appels = []

    def fetch(*args, **kwargs):
        appels.append(1)
        return {"results": [{"date_mutation": "2025-01-01"}]}

    monkeypatch.setattr(dvf, "fetch_json", fetch)
    assert len(dvf.fetch_dvf_cerema("99001")) == 1
    assert len(dvf.fetch_dvf_cerema("99001")) == 1
    assert len(appels) == 1


def test_dvf_bulk_lit_les_departements_sans_reseau(tmp_path, monkeypatch):
    from collectors import dvf

    monkeypatch.setattr(dvf, "DVF_CACHE", tmp_path / "dvf")
    monkeypatch.setattr(dvf, "archive_fetch", lambda *a, **k: None)
    contenu = (
        "code_commune,date_mutation,valeur_fonciere,id_parcelle\n"
        "99001,2025-01-01,100000,99001000AB0001\n"
        "99002,2025-01-02,200000,99002000AB0002\n"
    ).encode()
    for annee in range(2020, date.today().year + 1):
        chemin = dvf.DVF_CACHE / "departements" / str(annee) / f"{dvf.DEPARTEMENT}.csv.gz"
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_bytes(gzip.compress(contenu))

    def reseau_interdit(*args, **kwargs):
        raise AssertionError("le magasin rempli ne doit pas appeler le réseau")

    monkeypatch.setattr(dvf.urllib.request, "urlopen", reseau_interdit)
    lignes = dvf.fetch_dvf_csv_bulk("99001")
    assert len(lignes) == date.today().year - 2019
    assert {ligne["code_commune"] for ligne in lignes} == {"99001"}
