"""Le contrôle d'étanchéité du snapshot publié.

Il est écrit comme un adversaire et ne partage aucun code avec le builder :
si les deux avaient le même bug, la fuite passerait. Ces tests portent donc sur
le contrôleur seul, en lui donnant des répertoires publiés fabriqués à la main.

L'invariant de périmètre est né du 14/08/2026 : un site de commune qui publiait
6 151 fiches d'une voisine pour 1 012 des siennes, sans qu'aucun contrôle ne
bronche.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Les chaînes que le contrôle du kit interdit sont assemblées à l'exécution :
# écrites en clair, elles feraient refuser l'archive qui contient ces tests —
# et à raison, puisque la règle est qu'aucun chemin personnel n'y figure. Le
# détecteur est bien exercé, il reçoit la même chaîne.
CHEMIN_PERSONNEL = "/" + "Users/quelquun"


@pytest.fixture(scope="module")
def vs():
    spec = importlib.util.spec_from_file_location(
        "verify_snapshot", ROOT / "scripts" / "verify_snapshot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _publier(dossier: Path, entites: list[dict]) -> Path:
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "entity_index.json").write_text(
        json.dumps({"entities": entites}, ensure_ascii=False), encoding="utf-8")
    return dossier


def _fiches(commune: str, n: int, depart: int = 0) -> list[dict]:
    return [{"id": depart + i, "n": f"Acteur {depart + i}", "t": "business",
             "c": commune} for i in range(n)]


# ── L'invariant de périmètre ─────────────────────────────────────────────────

def test_site_conforme_passe(vs, tmp_path, monkeypatch):
    monkeypatch.setitem(vs.RULES, "project", {"commune": "Testonville"})
    rep = vs.Report()
    vs.check_perimetre(_publier(tmp_path / "ok",
                                _fiches("Testonville", 94) + _fiches("Voisinbourg", 6, 100)),
                       rep)
    assert rep.errors == {} and rep.warnings == {}


def test_commune_minoritaire_bloque(vs, tmp_path, monkeypatch):
    """Le cas Saillans : 1 012 fiches de la commune, 6 151 d'une voisine."""
    monkeypatch.setitem(vs.RULES, "project", {"commune": "Testonville"})
    rep = vs.Report()
    vs.check_perimetre(_publier(tmp_path / "ko",
                                _fiches("Testonville", 10) + _fiches("Voisinbourg", 60, 100)),
                       rep)
    assert rep.errors, "un site publiant surtout une autre commune doit être refusé"


def test_commune_majoritaire_mais_diluee_bloque(vs, tmp_path, monkeypatch):
    """Le cas Lasalle-v3 : la commune reste première, mais à 24 %."""
    monkeypatch.setitem(vs.RULES, "project", {"commune": "Testonville"})
    rep = vs.Report()
    entites = (_fiches("Testonville", 24)
               + _fiches("Voisinbourg", 20, 100)
               + _fiches("Les Essarts-d'Épreuve", 20, 200)
               + _fiches("Ailleurs", 36, 300))
    vs.check_perimetre(_publier(tmp_path / "dilue", entites), rep)
    assert rep.errors, "être la commune la plus publiée ne suffit pas"


def test_derive_signalee_avant_de_bloquer(vs, tmp_path, monkeypatch):
    monkeypatch.setitem(vs.RULES, "project", {"commune": "Testonville"})
    rep = vs.Report()
    vs.check_perimetre(_publier(tmp_path / "warn",
                                _fiches("Testonville", 60) + _fiches("Voisinbourg", 40, 100)),
                       rep)
    assert not rep.errors
    assert rep.warnings, "60 % doit alerter sans interrompre la publication"


def test_index_absent_ne_fait_rien(vs, tmp_path):
    """Un répertoire sans index n'est pas une violation : c'est un autre dossier."""
    rep = vs.Report()
    (tmp_path / "vide").mkdir()
    vs.check_perimetre(tmp_path / "vide", rep)
    assert rep.errors == {} and rep.warnings == {}


# ── Les règles de fond ───────────────────────────────────────────────────────

def test_confidence_privee_refusee(vs, tmp_path):
    rep = vs.Report()
    fichier = tmp_path / "acteurs.json"
    fichier.write_text(json.dumps(
        {"entities": [{"name": "Piste", "confidence": "hypothesis"}]}), encoding="utf-8")
    vs.check_file(fichier, rep, tmp_path)
    assert any("confidence" in r for r in rep.errors)


def test_personne_avec_coordonnees_refusee(vs, tmp_path):
    rep = vs.Report()
    fichier = tmp_path / "acteurs.json"
    fichier.write_text(json.dumps(
        {"entities": [{"name": "Quelqu'un", "type": "person",
                       "lat": 45.0, "lng": 3.0}]}), encoding="utf-8")
    vs.check_file(fichier, rep, tmp_path)
    assert any("coordonnées" in r for r in rep.errors)


def test_date_de_naissance_refusee(vs, tmp_path):
    rep = vs.Report()
    fichier = tmp_path / "acteurs.json"
    fichier.write_text(json.dumps(
        {"entities": [{"name": "Quelqu'un", "birth_date": "1970-01-01"}]}),
        encoding="utf-8")
    vs.check_file(fichier, rep, tmp_path)
    assert any("clé interdite" in r for r in rep.errors)


def test_chemin_local_refuse(vs, tmp_path):
    rep = vs.Report()
    fichier = tmp_path / "actes.json"
    fichier.write_text(json.dumps(
        {"events": [{"title": "Acte",
                     "url": "file://" + CHEMIN_PERSONNEL + "/pv.pdf"}]}),
        encoding="utf-8")
    vs.check_file(fichier, rep, tmp_path)
    assert any("chaîne locale" in r for r in rep.errors)


def test_base_dans_le_repertoire_publie_refusee(vs, tmp_path):
    rep = vs.Report()
    (tmp_path / "99001.db").write_bytes(b"SQLite format 3\x00")
    vs.check_dir(tmp_path, rep)
    assert any("fichier interdit" in r for r in rep.errors)


def test_rebuts_du_systeme_de_fichiers_refuses(vs, tmp_path):
    """`.DS_Store` passait le contrôle, et il nomme ce qu'on a retiré du public.

    Le 23/08, le contrôleur relancé sur un vieux brouillon a signalé son
    `review_report.json` et laissé passer le `.DS_Store` posé à côté. Ce
    fichier-là porte le nom de TOUS les fichiers que le dossier a contenus —
    y compris les fiches écartées de la publication — et il part chez
    l'hébergeur avec le reste.
    """
    for rebut in (".DS_Store", "._entities.json", "Thumbs.db"):
        rep = vs.Report()
        (tmp_path / rebut).write_bytes(b"\x00\x00\x00\x01Bud1")
        vs.check_dir(tmp_path, rep)
        assert any("fichier interdit" in r for r in rep.errors), rebut
        (tmp_path / rebut).unlink()


# ── L'invariant de renvoi sortant ────────────────────────────────────────────
#
# Symétrique de `check_fiches_orphelines`, ajouté le 21/08/2026 après un audit
# externe : `/elus` liait `/entite/<id>` pour tous les conseillers municipaux de
# l'intercommunalité, dont 78 à 90 % n'ont pas de fiche. 152 à 191 liens morts
# par instance, EN PRODUCTION, avec un contrôleur qui rendait « 0 violation ».

def _publier_entites(dossier: Path, ids: list[int]) -> Path:
    """Un répertoire publié minimal : `entities.json` et rien d'autre."""
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "entities.json").write_text(
        json.dumps({"entities": [{"id": i, "name": f"Acteur {i}"} for i in ids]}),
        encoding="utf-8")
    return dossier


def test_renvoi_vers_fiche_publiee_passe(vs, tmp_path):
    base = _publier_entites(tmp_path / "ok", [1, 2, 3])
    (base / "elus_rne.json").write_text(
        json.dumps({"elus": [{"nom": "A", "entity_id": 2}]}), encoding="utf-8")
    rep = vs.Report()
    vs.check_renvois_sortants(base, rep)
    assert rep.errors == {}


def test_renvoi_vers_fiche_absente_bloque(vs, tmp_path):
    base = _publier_entites(tmp_path / "ko", [1, 2, 3])
    (base / "elus_rne.json").write_text(
        json.dumps({"elus": [{"nom": "A", "entity_id": 99}]}), encoding="utf-8")
    rep = vs.Report()
    vs.check_renvois_sortants(base, rep)
    assert any("renvoi vers une fiche non publiée" in r for r in rep.errors)


def test_fiche_false_dispense_du_renvoi(vs, tmp_path):
    """La sortie explicite : publier un nom sans promettre de page.

    C'est l'arbitrage du 21/08/2026 sur `/elus` — la composition d'un conseil
    municipal vient du RNE, registre public rediffusable, et reste publiée ;
    c'est la FICHE que le filtre de périmètre refuse, pas le nom. L'export le
    dit champ par champ, et la page ne construit un lien que là où il existe.
    """
    base = _publier_entites(tmp_path / "flag", [1, 2, 3])
    (base / "elus_rne.json").write_text(json.dumps({"elus": [
        {"nom": "Siège à l'EPCI", "entity_id": 2, "fiche": True},
        {"nom": "Conseiller d'une commune membre", "entity_id": 99, "fiche": False},
    ]}), encoding="utf-8")
    rep = vs.Report()
    vs.check_renvois_sortants(base, rep)
    assert rep.errors == {}


def test_fiche_true_mensonger_bloque(vs, tmp_path):
    """`fiche: true` sur un identifiant absent est un mensonge, pas une dispense."""
    base = _publier_entites(tmp_path / "menteur", [1, 2, 3])
    (base / "elus_rne.json").write_text(
        json.dumps({"elus": [{"nom": "A", "entity_id": 99, "fiche": True}]}),
        encoding="utf-8")
    rep = vs.Report()
    vs.check_renvois_sortants(base, rep)
    assert any("renvoi vers une fiche non publiée" in r for r in rep.errors)


def test_renvoi_compte_ids_et_occurrences(vs, tmp_path):
    """Deux unités, parce qu'elles ne disent pas la même chose : les ids
    distincts comptent les fiches manquantes, les occurrences comptent les liens
    qu'un lecteur peut heurter. L'audit et le relevé interne différaient de ce
    seul facteur."""
    base = _publier_entites(tmp_path / "compte", [1])
    (base / "urbanisme.json").write_text(json.dumps({"autorisations": [
        {"num_dau": "A", "demandeur_entity_id": 50},
        {"num_dau": "B", "demandeur_entity_id": 50},
        {"num_dau": "C", "demandeur_entity_id": 51},
        {"num_dau": "D", "demandeur_entity_id": 1},
    ]}), encoding="utf-8")
    rep = vs.Report()
    vs.check_renvois_sortants(base, rep)
    detail = " ".join(sum(rep.errors.values(), []))
    assert "2 identifiant(s) mort(s)" in detail
    assert "3 occurrence(s)" in detail


def test_renvoi_ignore_les_cles_qui_ne_designent_pas_une_entite(vs, tmp_path):
    """`id`, `event_id`, `raw_document_id` ne promettent pas de fiche.

    Un contrôle qui se trompe de champ crie sur du bruit, et un contrôle qui
    crie sur du bruit finit désactivé. La liste `CHAMPS_RENVOI` est explicite
    pour cette raison.
    """
    base = _publier_entites(tmp_path / "bruit", [1])
    (base / "events.json").write_text(json.dumps({"events": [
        {"id": 4242, "event_id": 777, "raw_document_id": 999, "title": "Acte"},
    ]}), encoding="utf-8")
    rep = vs.Report()
    vs.check_renvois_sortants(base, rep)
    assert rep.errors == {}


def test_renvoi_dans_un_sous_dossier_bloque(vs, tmp_path):
    """Les fiches `entite/<id>.json` sont servies, donc contrôlées.

    Le premier jet ne lisait que la racine. Or c'est la fiche pré-résolue qui
    porte les renvois que `relations.json` n'a pas — un snapshot de Lasalle-v3
    avait `relations.json` parfaitement propre pendant que `entite/8514.json`
    renvoyait vers trois acteurs jamais publiés. `check_dir` inspecte déjà ces
    fichiers en `rglob` pour toutes les autres règles.
    """
    base = _publier_entites(tmp_path / "sous-dossier", [1, 2])
    (base / "entite").mkdir()
    (base / "entite" / "1.json").write_text(json.dumps({
        "entity": {"id": 1, "name": "Acteur 1"},
        "relations": [{"id": 7, "from_id": 1, "to_id": 404, "autre_id": 404}],
    }), encoding="utf-8")
    rep = vs.Report()
    vs.check_renvois_sortants(base, rep)
    detail = " ".join(sum(rep.errors.values(), []))
    assert "renvoi vers une fiche non publiée" in rep.errors
    assert "entite/1.json" in detail


def test_fiche_false_ne_dispense_pas_ce_qui_est_imbrique(vs, tmp_path):
    """La dispense couvre l'enregistrement, pas sa descendance.

    `return` sur `fiche: false` coupait la récursion entière : un objet
    imbriqué sous une ligne dispensée n'était plus contrôlé du tout.
    `elus_rne.json` est plat, donc rien ne fuyait — mais l'exception était
    écrite plus large que l'arbitrage qu'elle transcrit.
    """
    base = _publier_entites(tmp_path / "imbrique", [1])
    (base / "elus_rne.json").write_text(json.dumps({"elus": [{
        "nom": "Conseiller d'une commune membre",
        "entity_id": 99,
        "fiche": False,
        "mandats": [{"role": "adjoint", "entite_id": 77}],
    }]}), encoding="utf-8")
    rep = vs.Report()
    vs.check_renvois_sortants(base, rep)
    detail = " ".join(sum(rep.errors.values(), []))
    assert "entite_id" in detail          # le renvoi imbriqué est vu
    assert "entity_id" not in detail      # la dispense de la ligne tient


def test_renvoi_sans_entities_ne_crie_pas(vs, tmp_path):
    """Dépôt fraîchement cloné : pas de snapshot, donc rien à promettre."""
    base = tmp_path / "vide"
    base.mkdir()
    rep = vs.Report()
    vs.check_renvois_sortants(base, rep)
    assert rep.errors == {}
